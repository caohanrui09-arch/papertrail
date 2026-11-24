"""Plain-text paper notes and atomic v3 library backups, scoped to the visitor."""
from datetime import datetime,timezone
import hashlib
import hmac
import json
import sqlite3
from types import SimpleNamespace
from typing import Literal
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import Response
from pydantic import BaseModel,ConfigDict,Field,ValidationError,model_validator
from .readinglog import LibraryBackup,LibraryImport,reading_snapshot,write_reading
from .reuse import MAX_FILE,aware_timestamp,merge_plan,unique_object
from .security import persistent_secret

class NoteFeedback(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    doc_id:str=Field(pattern=r'^\d{4}\.\d{4,5}$')
    version_key:str=Field(max_length=80)
    catalog_key:str=Field(max_length=100)
    revision:int=Field(ge=0,strict=True)
    problem:str=Field(max_length=1000)
    questions:str=Field(max_length=1000)

class NoteRow(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    doc_id:str=Field(pattern=r'^\d{4}\.\d{4,5}$')
    version_key:str=Field(max_length=80)
    title:str=Field(max_length=1000)
    source_url:str=Field(max_length=500)
    problem:str=Field(max_length=1000)
    questions:str=Field(max_length=1000)

    @model_validator(mode='after')
    def nonempty(self)->'NoteRow':
        if not self.problem.strip() and not self.questions.strip():raise ValueError('Empty note')
        return self

    @property
    def preference(self)->dict:return {'problem':self.problem,'questions':self.questions}

class NotebookBackup(LibraryBackup):
    schema_version:Literal[3]
    notes:list[NoteRow]=Field(max_length=500)

class NotebookImport(LibraryImport):
    notes_revision:int=Field(ge=0,strict=True)

def note_snapshot(db:sqlite3.Connection,owner:str)->dict:
    row=db.execute('SELECT revision FROM note_revisions WHERE owner=?',(owner,)).fetchone()
    rows=db.execute('SELECT doc_id,problem,questions,updated FROM paper_notes WHERE owner=? ORDER BY doc_id',(owner,)).fetchall()
    return {'revision':row[0] if row else 0,'items':{d:{'problem':p,'questions':q} for d,p,q,_ in rows},'updated':{d:t for d,_,_,t in rows}}

def write_notes(db:sqlite3.Connection,owner:str,revision:int,changes:list[tuple[str,dict|None]],now:str)->None:
    for doc,value in changes:
        if value is None:db.execute('DELETE FROM paper_notes WHERE owner=? AND doc_id=?',(owner,doc))
        else:db.execute('INSERT OR REPLACE INTO paper_notes VALUES(?,?,?,?,?)',(owner,doc,value['problem'],value['questions'],now))
    if changes:db.execute('INSERT INTO note_revisions VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET revision=excluded.revision',(owner,revision+1))

def install_notebook(app:FastAPI)->None:
    store,catalog=app.state.preferences,app.state.catalog;secret=persistent_secret(app.state.settings.data_dir)
    with store.connect() as db:
        db.executescript('''BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS note_revisions(owner TEXT PRIMARY KEY,revision INTEGER NOT NULL CHECK(revision>=0));
            CREATE TABLE IF NOT EXISTS paper_notes(owner TEXT NOT NULL,doc_id TEXT NOT NULL,problem TEXT NOT NULL,questions TEXT NOT NULL,updated TEXT NOT NULL,PRIMARY KEY(owner,doc_id));
            COMMIT;''')
    def identity(doc):return {k:v for k,v in catalog.paper(doc).items() if k!='version'}
    def encode(value):return json.dumps(value,ensure_ascii=False,indent=2)+'\n'
    def envelope(prefs,reading,notes,now):
        return {'format':'papertrail-library','schema_version':3,'catalog_key':catalog.catalog_key,'exported_at':now,
            'preferences':[identity(d)|{'preference':v} for d,v in prefs.items()],
            'reading':[identity(d)|{'state':v} for d,v in reading.items()],
            'notes':[identity(d)|v for d,v in notes.items()]}
    empty={'problem':'','questions':''}
    # Reserve every possible current-catalog identity and both other lists. Count escaped JSON bytes,
    # not characters, so every accepted notebook remains exportable under the existing 256 KiB limit.
    reserve=len(encode(envelope({d:'hide' for d in catalog.catalog},{d:'to_read' for d in catalog.catalog},
        {d:empty for d in catalog.catalog},'2000-01-01T00:00:00.000000+00:00')).encode())+1024
    budget=MAX_FILE-reserve
    if budget<0:raise ValueError('Current catalog exceeds bounded notebook backup budget')
    def cost(notes):return sum(len(json.dumps(v[k],ensure_ascii=False).encode())-2 for v in notes.values() for k in ('problem','questions'))
    def bound(notes):
        if len(notes)>500 or cost(notes)>budget:raise HTTPException(422,'笔记空间已满，请缩短部分笔记后重试；完整备份上限256 KiB')
    def same(key):
        if not catalog.compatible_key(key):raise HTTPException(409,'目录版本已变化，请刷新后重试')
    def check_doc(doc,version):
        if not catalog.valid(doc):raise HTTPException(422,'论文不在当前目录')
        if version!=catalog.by_id[doc]['version_key']:raise HTTPException(409,'论文版本不一致')
    def view(snapshot):
        order=sorted(snapshot['items'],key=lambda d:(snapshot['updated'][d],d),reverse=True)
        return {'revision':snapshot['revision'],'catalog_key':catalog.catalog_key,
            'items':[identity(d)|snapshot['items'][d]|{'updated_at':snapshot['updated'][d]} for d in order],
            'remaining_bytes':budget-cost(snapshot['items']),'budget_bytes':budget,'max_field_length':1000,
            'scope':'访客自己的纯文本笔记，非原摘要或模型结论；不会改变收藏、阅读状态或推荐。'}

    @app.get('/api/profile/notes')
    def notes(request:Request):
        with store.connect() as db:db.execute('BEGIN');return view(note_snapshot(db,request.state.owner))

    @app.post('/api/profile/notes/save')
    def save(body:NoteFeedback,request:Request):
        same(body.catalog_key);check_doc(body.doc_id,body.version_key)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE');before=note_snapshot(db,request.state.owner)
            if body.revision!=before['revision']:raise HTTPException(409,'笔记已在其他页面变化，请刷新笔记后重试；草稿尚未保存')
            previous=before['items'].get(body.doc_id)
            value={'problem':body.problem,'questions':body.questions} if body.problem.strip() or body.questions.strip() else None
            after=dict(before['items'])
            if value is None:after.pop(body.doc_id,None)
            else:after[body.doc_id]=value
            bound(after)
            if previous!=value:write_notes(db,request.state.owner,before['revision'],[(body.doc_id,value)],datetime.now(timezone.utc).isoformat())
            final=note_snapshot(db,request.state.owner)
        return view(final)|{'change':{'doc_id':body.doc_id,'previous':previous,'value':value}}

    def parse(text):
        if len(text.encode('utf-8'))>MAX_FILE:raise HTTPException(413,'备份文件不能超过256 KiB')
        try:value=json.loads(text.lstrip('\ufeff'),object_pairs_hook=unique_object)
        except (ValueError,RecursionError) as error:raise HTTPException(422,'备份JSON格式无效或字段重复') from error
        if isinstance(value,dict) and value.get('schema_version') in (1,2):
            p,r,v=app.state.library_parse(text);return p,r,[],v
        try:
            if not isinstance(value,dict) or type(value.get('schema_version')) is not int:raise ValueError('version')
            backup=NotebookBackup.model_validate(value);aware_timestamp(backup.exported_at)
        except (ValueError,ValidationError,RecursionError) as error:raise HTTPException(422,'需要本站v3笔记备份、v2清单备份或v1偏好备份') from error
        same(backup.catalog_key)
        p,r,_=app.state.library_parse(json.dumps(backup.model_dump(exclude={'notes'})|{'schema_version':2},ensure_ascii=False))
        seen=set()
        for row in backup.notes:
            if backup.catalog_key==catalog.core.catalog_key and row.doc_id not in catalog.core.by_id:raise HTTPException(422,'旧目录笔记备份不能伪装包含新增论文')
            if row.doc_id in seen:raise HTTPException(422,'笔记存在重复论文ID')
            seen.add(row.doc_id);check_doc(row.doc_id,row.version_key)
            if any(getattr(row,k)!=identity(row.doc_id)[k] for k in ('title','source_url')):raise HTTPException(409,'笔记对应论文标题或来源不一致')
        return p,r,backup.notes,3
    def snapshot(db,owner):return store.snapshot(db,owner),reading_snapshot(db,owner),note_snapshot(db,owner)
    def check_revision(body,p,r,n):
        if (body.revision,body.reading_revision,body.notes_revision)!=(p['revision'],r['revision'],n['revision']):raise HTTPException(409,'收藏、阅读清单或笔记已变化，请重新预览')
    def token(owner,body,p,r,n):
        raw=json.dumps([catalog.catalog_key,owner,body.text,body.policy,p,r,n],sort_keys=True,ensure_ascii=False).encode()
        return hmac.new(secret,b'notebook-import:'+raw,hashlib.sha256).hexdigest()
    def plan(backup,rows,notes,p,r,n,policy):
        pm,rm,base=app.state.library_plans(backup,rows,p,r,policy)
        nm,np=merge_plan(SimpleNamespace(items=notes),n,policy);bound(nm)
        return pm,rm,nm,base|{'notes':np,'changes_total':base['changes_total']+np['counts']['added']+np['counts']['changed']}

    @app.get('/api/profile/notebook/export')
    def export(request:Request):
        with store.connect() as db:db.execute('BEGIN');p,r,n=snapshot(db,request.state.owner)
        text=encode(envelope(p['items'],r['items'],n['items'],datetime.now(timezone.utc).isoformat()))
        if len(text.encode())>MAX_FILE:raise HTTPException(503,'当前备份超出容量限制，请联系维护者')
        return Response(text,media_type='application/json',headers={'Content-Disposition':'attachment; filename="papertrail-library-v3.json"'})

    @app.post('/api/profile/notebook/import/preview')
    def preview(body:NotebookImport,request:Request):
        backup,rows,notes,version=parse(body.text)
        with store.connect() as db:db.execute('BEGIN');p,r,n=snapshot(db,request.state.owner)
        check_revision(body,p,r,n);_,_,_,preview=plan(backup,rows,notes,p,r,n,body.policy)
        return preview|{'revision':p['revision'],'reading_revision':r['revision'],'notes_revision':n['revision'],
            'catalog_key':catalog.catalog_key,'policy':body.policy,'file_version':version,'exported_at':backup.exported_at,
            'preview_token':token(request.state.owner,body,p,r,n),'file_sha256':hashlib.sha256(body.text.encode()).hexdigest(),
            'migrated_from':backup.catalog_key if backup.catalog_key!=catalog.catalog_key else None}

    @app.post('/api/profile/notebook/import/apply')
    def apply(body:NotebookImport,request:Request):
        backup,rows,notes,version=parse(body.text)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE');p,r,n=snapshot(db,request.state.owner);check_revision(body,p,r,n)
            if not body.preview_token or not hmac.compare_digest(body.preview_token,token(request.state.owner,body,p,r,n)):raise HTTPException(409,'预览已失效，请重新预览')
            pm,rm,nm,preview=plan(backup,rows,notes,p,r,n,body.policy)
            pc=[(d,v) for d,v in pm.items() if p['items'].get(d)!=v];rc=[(d,v) for d,v in rm.items() if r['items'].get(d)!=v];nc=[(d,v) for d,v in nm.items() if n['items'].get(d)!=v]
            now=datetime.now(timezone.utc).isoformat()
            if pc:
                db.executemany('INSERT OR REPLACE INTO preferences VALUES(?,?,?,?)',[(request.state.owner,d,v,now) for d,v in pc]);db.execute('UPDATE visitors SET revision=? WHERE owner=?',(p['revision']+1,request.state.owner))
            write_reading(db,request.state.owner,r['revision'],rc,now);write_notes(db,request.state.owner,n['revision'],nc,now)
        return preview|{'applied':len(pc),'reading_applied':len(rc),'notes_applied':len(nc),'total_applied':len(pc)+len(rc)+len(nc),
            'revision':p['revision']+bool(pc),'reading_revision':r['revision']+bool(rc),'notes_revision':n['revision']+bool(nc),'file_version':version}
    app.state.note_snapshot=note_snapshot
    app.state.note_budget=budget
