"""Versioned annotation persistence and blind projection over an immutable pool."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel,ConfigDict,Field

from .visitor_profile import Preferences,PreferenceConflict

ROOT=Path('data/stage26-annotation')


class ReviewInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision: int=Field(ge=0,strict=True)
    operation: Literal['draft','submit']
    decision: Literal['','approve','reject','clarify']=''
    reviewer: str=Field(default='',max_length=64)
    note: str=Field(default='',max_length=4000)
    attest: bool=Field(default=False,strict=True)


class JudgmentInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision: int=Field(ge=0,strict=True)
    operation: Literal['draft','skip','submit']
    grade: int | None=Field(default=None,ge=0,le=2,strict=True)
    reviewer: str=Field(default='',max_length=64)
    rationale: str=Field(default='',max_length=4000)
    attest: bool=Field(default=False,strict=True)


class BlindPool:
    def __init__(self,root: Path=ROOT):
        self.root=root
        manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        for name,expected in manifest['immutable_assets'].items():
            path=(root/name).resolve()
            if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
                raise ValueError('Annotation pool integrity failure')
        self.version=manifest['pool_version']
        self.tasks=json.loads((root/'blind/tasks.json').read_text(encoding='utf-8'))
        self.pairs=manifest['pairs']
        if len(self.tasks)!=9:raise ValueError('Only nine tuning requests belong to this pool')

    def task(self,qid: str) -> dict:
        if qid not in self.tasks:raise ValueError('找不到这条调参需求')
        return self.tasks[qid]

    def candidate(self,qid: str,aid: str) -> dict:
        for value in self.task(qid)['candidates']:
            if value['annotation_id']==aid:return value
        raise ValueError('找不到该需求下的候选论文')


class AnnotationStore(Preferences):
    def __init__(self,path: Path,pool: BlindPool):
        self.path=path;self.pool=pool
        path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS annotation_records(
                  owner TEXT,pool TEXT,qid TEXT,kind TEXT,item TEXT,revision INTEGER,body TEXT,updated TEXT,
                  PRIMARY KEY(owner,pool,qid,kind,item));
                CREATE TABLE IF NOT EXISTS annotation_audit(
                  event INTEGER PRIMARY KEY AUTOINCREMENT,owner TEXT,pool TEXT,qid TEXT,kind TEXT,item TEXT,
                  revision INTEGER,body TEXT,updated TEXT);
            ''')

    def _row(self,db,owner: str,qid: str,kind: str,item: str) -> dict:
        row=db.execute('SELECT revision,body,updated FROM annotation_records WHERE owner=? AND pool=? AND qid=? AND kind=? AND item=?',
            (owner,self.pool.version,qid,kind,item)).fetchone()
        return {'revision':row[0],'value':json.loads(row[1]),'updated':row[2]} if row else {'revision':0,'value':None,'updated':None}

    def record(self,owner: str,qid: str,kind: str,item: str='') -> dict:
        with self.connect() as db:return self._row(db,owner,qid,kind,item)

    @staticmethod
    def approved(review: dict) -> bool:
        return review['value'] is not None and review['value']['status']=='approve'

    def _write(self,db,owner: str,qid: str,kind: str,item: str,revision: int,value: dict) -> dict:
        current=self._row(db,owner,qid,kind,item)
        if current['revision']!=revision:raise PreferenceConflict('记录已在其他页面更新；先加载最新版本，再决定如何保存你的修改')
        when=datetime.now(timezone.utc).isoformat()
        fields=(owner,self.pool.version,qid,kind,item,revision+1,json.dumps(value,ensure_ascii=False),when)
        db.execute('INSERT OR REPLACE INTO annotation_records VALUES(?,?,?,?,?,?,?,?)',fields)
        db.execute('INSERT INTO annotation_audit(owner,pool,qid,kind,item,revision,body,updated) VALUES(?,?,?,?,?,?,?,?)',fields)
        return {'revision':revision+1,'value':value,'updated':when}

    def review(self,owner: str,qid: str,body: ReviewInput) -> dict:
        task=self.pool.task(qid)
        if body.operation=='submit' and (not body.decision or not body.reviewer.strip() or not body.note.strip() or not body.attest):
            raise ValueError('提交需求确认需要选择结论、填写判断者和理由，并勾选来源声明')
        value={'status':body.decision if body.operation=='submit' else 'draft','decision':body.decision,
            'reviewer':body.reviewer.strip(),'note':body.note.strip(),'query_hash':task['query']['query_hash'],
            'origin':'automation_test' if owner.startswith('verification:') else 'human' if body.operation=='submit' else 'unsubmitted_draft',
            'attested':body.attest if body.operation=='submit' else False}
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            return self._write(db,owner,qid,'review','',body.revision,value)

    def judge(self,owner: str,qid: str,aid: str,body: JudgmentInput) -> dict:
        self.pool.candidate(qid,aid)
        if body.operation=='submit' and (body.grade is None or not body.reviewer.strip() or not body.rationale.strip() or not body.attest):
            raise ValueError('提交相关性判断需要等级、判断者、依据和来源声明')
        if body.operation=='skip' and not body.rationale.strip():raise ValueError('无法判断时请说明原因')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            review=self._row(db,owner,qid,'review','')
            if not self.approved(review):raise ValueError('先确认需求可用于评价，再保存论文判断')
            value={'status':{'draft':'draft','skip':'skipped','submit':'submitted'}[body.operation],
                'grade':None if body.operation=='skip' else body.grade,'reviewer':body.reviewer.strip(),'rationale':body.rationale.strip(),
                'review_revision':review['revision'],'query_hash':self.pool.task(qid)['query']['query_hash'],
                'origin':'automation_test' if owner.startswith('verification:') else 'human' if body.operation=='submit' else 'unsubmitted_draft',
                'attested':body.attest if body.operation=='submit' else False}
            return self._write(db,owner,qid,'judgment',aid,body.revision,value)

    def detail(self,owner: str,qid: str) -> dict:
        task=self.pool.task(qid)
        with self.connect() as db:
            db.execute('BEGIN')
            review=self._row(db,owner,qid,'review','')
            candidates=[]
            for candidate in task['candidates']:
                record=self._row(db,owner,qid,'judgment',candidate['annotation_id'])
                valid=self.approved(review) and record['value'] is not None and record['value']['status']=='submitted' and record['value']['review_revision']==review['revision']
                candidates.append({**candidate,'record':record,'valid_submission':valid})
        return {'query':task['query'],'context':task['context'],'review':review,'candidates':candidates,
            'pool_version':self.pool.version,'labeling_unlocked':self.approved(review),'verification':owner.startswith('verification:')}

    def workspace(self,owner: str) -> dict:
        queries=[]
        for qid in sorted(self.pool.tasks):
            detail=self.detail(owner,qid)
            records=[c['record']['value'] for c in detail['candidates'] if c['record']['value']]
            queries.append({'query_id':qid,'topic':detail['query']['topic_zh'],'intent':detail['query']['intent'],
                'review_status':detail['review']['value']['status'] if detail['review']['value'] else 'pending',
                'candidates':len(detail['candidates']),'submitted':sum(c['valid_submission'] for c in detail['candidates']),
                'drafts':sum(r['status']=='draft' for r in records),'skipped':sum(r['status']=='skipped' for r in records)})
        return {'pool_version':self.pool.version,'queries':queries,'total_queries':9,'total_pairs':self.pool.pairs,
            'approved':sum(q['review_status']=='approve' for q in queries),'submitted':sum(q['submitted'] for q in queries),
            'verification':owner.startswith('verification:'),'quality_scores':None,'split':'tuning',
            'scope':'仅当前浏览器空间；草稿与无法判断不计入已提交覆盖'}

    def history(self,owner: str,qid: str,kind: str,item: str) -> list[dict]:
        self.pool.task(qid)
        with self.connect() as db:
            rows=db.execute('SELECT revision,body,updated FROM annotation_audit WHERE owner=? AND pool=? AND qid=? AND kind=? AND item=? ORDER BY revision DESC',
                (owner,self.pool.version,qid,kind,item)).fetchall()
        return [{'revision':r[0],'value':json.loads(r[1]),'updated':r[2]} for r in rows]

    def export(self,owner: str,studio: bool=False) -> dict | list:
        details=[self.detail(owner,q) for q in sorted(self.pool.tasks)]
        if not studio:
            return {'pool_version':self.pool.version,'verification':owner.startswith('verification:'),'scope':'declared origin, not identity authentication',
                'queries':details,'history':{q['query']['query_id']:{'review':self.history(owner,q['query']['query_id'],'review',''),
                    'judgments':{c['annotation_id']:self.history(owner,q['query']['query_id'],'judgment',c['annotation_id']) for c in q['candidates']}} for q in details}}
        tasks=[]
        for q in details:
            for c in q['candidates']:
                value=c['record']['value'];annotations=[]
                if c['valid_submission']:
                    annotations=[{'created_at':c['record']['updated'],'was_cancelled':False,'completed_by':value['reviewer'],
                        'result':[{'from_name':'relevance','to_name':'paper','type':'choices','value':{'choices':[{0:'0 不相关',1:'1 部分相关',2:'2 高度相关'}[value['grade']]]}},
                                  {'from_name':'rationale','to_name':'paper','type':'textarea','value':{'text':[value['rationale']]}}],
                        'origin':value['origin']}]
                tasks.append({'data':{'annotation_id':c['annotation_id'],'query_id':q['query']['query_id'],'request':q['query']['request'],
                    'title':c['paper']['title'],'abstract':c['paper']['abstract'],'source_url':c['paper']['source_url'],
                    'profile_context':'\n\n'.join(p['title']+'\n'+p['abstract'] for p in q['context'])},'annotations':annotations})
        return tasks


def annotation_router(pool: BlindPool,store: AnnotationStore) -> APIRouter:
    router=APIRouter(prefix='/api/annotation')
    def owner(request: Request) -> str:
        return ('verification:' if request.headers.get('x-papertrail-verification')=='1' else '')+request.state.owner
    def checked(operation):
        try:return operation()
        except PreferenceConflict as error:raise HTTPException(409,str(error))
        except ValueError as error:raise HTTPException(422,str(error))

    @router.get('/workspace')
    def workspace(request: Request):return store.workspace(owner(request))

    @router.get('/queries/{qid}')
    def query(qid: str,request: Request):return checked(lambda:store.detail(owner(request),qid))

    @router.put('/reviews/{qid}')
    def review(qid: str,body: ReviewInput,request: Request):return checked(lambda:store.review(owner(request),qid,body))

    @router.put('/judgments/{qid}/{aid}')
    def judge(qid: str,aid: str,body: JudgmentInput,request: Request):return checked(lambda:store.judge(owner(request),qid,aid,body))

    @router.get('/history/{qid}/{kind}/{item}')
    def history(qid: str,kind: Literal['review','judgment'],item: str,request: Request):
        if kind=='judgment':checked(lambda:pool.candidate(qid,item))
        return checked(lambda:store.history(owner(request),qid,kind,'' if kind=='review' else item))

    @router.get('/export')
    def export(request: Request,format: Literal['native','label-studio']='native'):
        return JSONResponse(store.export(owner(request),format=='label-studio'),headers={'Content-Disposition':f'attachment; filename="papertrail-tuning-{format}.json"'})

    return router
