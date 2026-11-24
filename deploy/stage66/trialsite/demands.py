"""Opt-in unmet-demand records; directory evidence is distinct from relevance judgment."""
from datetime import datetime,timezone
import json
import re
from urllib.parse import urlsplit,unquote
from uuid import uuid4
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import Response
from pydantic import BaseModel,ConfigDict,Field,field_validator
from .researchtools import SearchContext
from .querybridge import plan_query
from .reuse import MAX_FILE
from .catalogfilters import scoped_ids,filter_info

def expected_id(value:str)->str:
    text=value.strip()
    if not text:return ''
    if text.startswith(('https://','http://')):
        p=urlsplit(text)
        if p.hostname not in ('arxiv.org','www.arxiv.org','export.arxiv.org') or p.username or p.password or p.query or p.fragment:
            raise ValueError('Expected canonical arXiv record')
        path=unquote(p.path)
        if not path.startswith(('/abs/','/pdf/')):raise ValueError('Expected arXiv abs/pdf')
        text=path[5:]
    if text.lower().startswith('arxiv:'):text=text[6:]
    if text.endswith('.pdf'):text=text[:-4]
    match=re.fullmatch(r'([0-9]{2}(?:0[1-9]|1[0-2])\.[0-9]{4,5})(?:v1)?',text)
    if not match:raise ValueError('需现代arXiv编号，不带版本或明确v1')
    return match[1]

class DemandSave(SearchContext):
    catalog_key:str=Field(max_length=100)
    revision:int=Field(ge=0,strict=True)
    reason:str=Field(pattern=r'^(no_candidates|poor_match|missing_known_paper)$')
    expected_paper:str=Field(default='',max_length=200)
    comment:str=Field(default='',max_length=500)

    @field_validator('expected_paper')
    @classmethod
    def identifier(cls,value:str)->str:return expected_id(value)

class DemandStatus(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    id:str=Field(pattern=r'^[a-f0-9]{32}$')
    revision:int=Field(ge=0,strict=True)
    status:str=Field(pattern=r'^(open|resolved|archived)$')
    catalog_key:str=Field(max_length=100)

def demand_snapshot(db,owner:str)->dict:
    row=db.execute('SELECT revision FROM demand_revisions WHERE owner=?',(owner,)).fetchone()
    records=db.execute('SELECT request_id,created_at,updated_at,status,data FROM paper_demands WHERE owner=? ORDER BY updated_at DESC,request_id',(owner,)).fetchall()
    return {'revision':row[0] if row else 0,'items':[json.loads(data)|{'id':d,'created_at':created,'updated_at':updated,'status':status} for d,created,updated,status,data in records]}

def install_demands(app:FastAPI)->None:
    c,store=app.state.catalog,app.state.preferences
    with store.connect() as db:
        db.executescript('''BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS demand_revisions(owner TEXT PRIMARY KEY,revision INTEGER NOT NULL CHECK(revision>=0));
            CREATE TABLE IF NOT EXISTS paper_demands(owner TEXT NOT NULL,request_id TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('open','resolved','archived')),data TEXT NOT NULL,PRIMARY KEY(owner,request_id));
            COMMIT;''')
    def same(key):
        if key!=c.catalog_key:raise HTTPException(409,'目录已变化，请刷新后重试')
    def envelope(items):return {'format':'papertrail-demand-audit','schema_version':1,'catalog_key':c.catalog_key,'exported_at':datetime.now(timezone.utc).isoformat(),'items':items}
    def view(snapshot):
        return snapshot|{'catalog_key':c.catalog_key,'limit':30,'scope':'仅包含你显式保存的需求；诊断为可核查的目录/词项证据，不是人工相关性判断。'}

    @app.get('/api/profile/demands')
    def get(request:Request):
        with store.connect() as db:db.execute('BEGIN');return view(demand_snapshot(db,request.state.owner))

    @app.post('/api/profile/demands/save')
    def save(body:DemandSave,request:Request):
        same(body.catalog_key)
        if not body.executed_query.strip():raise HTTPException(422,'请先完成一次非空查询')
        bridge=plan_query(body.original_need,body.executed_query,body.plan_reviewed) if body.original_need.strip() else None
        if bridge and bridge['review_required'] and not body.plan_reviewed:raise HTTPException(422,'请先检查并确认术语转换')
        selected=c.core if body.catalog_scope=='core' else c
        adapter=app.state.core_search_feedback if body.catalog_scope=='core' else app.state.search_feedback
        allowed=scoped_ids(c,body.catalog_scope,body.year)
        result=selected.search(body.topic,body.executed_query,body.method,body.context,allowed_ids=allowed)
        scope=filter_info(c,body.catalog_scope,body.year)
        target=body.expected_paper;shown={p['doc_id'] for p in result['papers']}
        if not target:
            diagnosis={'code':'unresolved','label':'尚未核定缺口','evidence':'缺少已知目标论文ID；结果为空或不满意都不能单独证明目录缺失或排序错误。','source_verified':None}
        elif target not in c.by_id:
            diagnosis={'code':'outside_catalog','label':'该ID未在当前目录','evidence':'当前目录未包含此ID；论文是否存在、主题是否相关，仍须核查来源。','source_verified':None}
        elif target not in selected.by_id:
            diagnosis={'code':'outside_scope','label':'已在新增目录，当前只搜历史核心','evidence':'请将目录范围切到全部主题；这不是整个网站缺论文。','source_verified':True}
        elif target not in scoped_ids(c,body.catalog_scope):
            diagnosis={'code':'outside_scope','label':'不在本次收录主题范围','evidence':'目标在网站目录中；应扩大主题范围，而不是直接补目录。','source_verified':True}
        elif body.year is not None and int(c.by_id[target]['published_at'][:4])!=body.year:
            diagnosis={'code':'outside_year','label':'被本次年份条件排除','evidence':'目标在目录中，但arXiv首次提交年份不同；请清除或调整年份条件。','source_verified':True}
        elif not selected.valid(target):
            diagnosis={'code':'outside_time','label':'未满足当前可用时间规则','evidence':'已知目录记录未通过当前时间可用性检查。','source_verified':True}
        elif target in selected.model.sar.seen['paired']:
            diagnosis={'code':'filtered','label':'目录内，但被演示过滤','evidence':'该ID存在于目录，当前搜索继承的演示已见过滤排除了它；不应归为缺论文。','source_verified':True}
        elif target in shown:
            diagnosis={'code':'returned','label':'目标已在前十返回','evidence':'目标ID已返回；用户的不满意反馈仍保留，不自动认定其语义相关。','source_verified':True}
        else:
            probe=result|{'papers':[c.paper(target)],'candidate_ids_before_rerank':[target]}
            match=adapter.explain(probe,body.method)['papers'][0]['search_match']
            positive=bool(match['terms']) if body.method=='bm25' else bool(selected.vectorizer.transform([body.executed_query]).dot(selected.documents[selected.position[target]].T)[0,0]>0)
            diagnosis={'code':'not_top10' if positive else 'no_term_match','label':'有词项匹配，未进入前十候选' if positive else '目录内，查询词项未匹配',
                'evidence':'候选截断/排序值得检查；这不是中间剪枝或语义相关性证据。' if positive else '应先检查术语与标题/摘要，不把未命中直接归为目录缺失。',
                'source_verified':True,'match':match}
        record={'original_need':body.original_need,'executed_query':body.executed_query,'topic':body.topic,'method':body.method,'context':body.context,
            'query_plan':bridge,'reason':body.reason,'expected_paper':target,'comment':body.comment,'diagnosis':diagnosis,
            'catalog_key':c.catalog_key,'catalog_scope':body.catalog_scope,'scope_key':selected.catalog_key,'catalog_size':scope['count'],'scope_label':scope['label'],'year':body.year,'as_of':selected.at,'shown_papers':result['papers'],
            'feedback_source':'explicit_visitor_report','relevance_judged':False}
        text=json.dumps(record,ensure_ascii=False)
        if len(text.encode())>16384:raise HTTPException(422,'需求记录过长，请缩短原问题、查询或补充说明')
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE');snapshot=demand_snapshot(db,request.state.owner)
            if body.revision!=snapshot['revision']:raise HTTPException(409,'需求记录已变化，请刷新后重试')
            if len(snapshot['items'])>=30:raise HTTPException(422,'当前试用空间最多保存30条需求（含归档），请先导出审计表')
            now=datetime.now(timezone.utc).isoformat();identifier=uuid4().hex
            candidate=record|{'id':identifier,'created_at':now,'updated_at':now,'status':'open'}
            if len(json.dumps(envelope(snapshot['items']+[candidate]),ensure_ascii=False,indent=2).encode())+1024>MAX_FILE:
                raise HTTPException(422,'需求审计空间已满，请缩短内容或先导出')
            db.execute('INSERT INTO paper_demands VALUES(?,?,?,?,?,?)',(request.state.owner,identifier,now,now,'open',text))
            db.execute('INSERT INTO demand_revisions VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET revision=excluded.revision',(request.state.owner,snapshot['revision']+1))
            final=demand_snapshot(db,request.state.owner)
        return view(final)|{'saved_id':identifier}

    @app.post('/api/profile/demands/status')
    def status(body:DemandStatus,request:Request):
        same(body.catalog_key)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE');snapshot=demand_snapshot(db,request.state.owner)
            if body.revision!=snapshot['revision']:raise HTTPException(409,'需求记录已变化，请刷新后重试')
            row=next((r for r in snapshot['items'] if r['id']==body.id),None)
            if row is None:raise HTTPException(404,'当前空间没有这条需求')
            if row['status']!=body.status:
                db.execute('UPDATE paper_demands SET status=?,updated_at=? WHERE owner=? AND request_id=?',(body.status,datetime.now(timezone.utc).isoformat(),request.state.owner,body.id))
                db.execute('UPDATE demand_revisions SET revision=? WHERE owner=?',(snapshot['revision']+1,request.state.owner))
            final=demand_snapshot(db,request.state.owner)
        return view(final)

    @app.get('/api/profile/demands/export')
    def export(request:Request):
        with store.connect() as db:db.execute('BEGIN');snapshot=demand_snapshot(db,request.state.owner)
        return Response(json.dumps(envelope(snapshot['items']),ensure_ascii=False,indent=2)+'\n',media_type='application/json',headers={'Content-Disposition':'attachment; filename="papertrail-demand-audit.json"'})
    app.state.demand_snapshot=demand_snapshot
