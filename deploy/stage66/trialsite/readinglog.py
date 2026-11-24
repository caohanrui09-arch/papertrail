"""Visitor reading workflow, separate from preference/ranking signals."""
from datetime import datetime, timezone
import hashlib
import hmac
import json
from types import SimpleNamespace
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .reuse import ImportRequest, MAX_FILE, aware_timestamp, merge_plan, unique_object
from .security import persistent_secret

READING_STATES=('to_read','reading','read')

class ReadingFeedback(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    doc_id: str=Field(pattern=r'^\d{4}\.\d{4,5}$')
    version_key: str=Field(max_length=80)
    catalog_key: str=Field(max_length=100)
    value: Literal['to_read','reading','read','none']
    revision: int=Field(ge=0,strict=True)

class ReadingRow(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    doc_id: str=Field(pattern=r'^\d{4}\.\d{4,5}$')
    version_key: str=Field(max_length=80)
    title: str=Field(max_length=1000)
    source_url: str=Field(max_length=500)
    state: Literal['to_read','reading','read']

    @property
    def preference(self):
        # Existing generic merge planner compares values; no recommendation signal is added.
        return self.state

class LibraryBackup(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    format: Literal['papertrail-library']
    schema_version: Literal[2]
    catalog_key: str=Field(max_length=100)
    exported_at: str=Field(max_length=80)
    preferences: list[dict]=Field(max_length=500)
    reading: list[ReadingRow]=Field(max_length=500)

class LibraryImport(ImportRequest):
    reading_revision: int=Field(ge=0,strict=True)

def reading_snapshot(db,owner):
    row=db.execute('SELECT revision FROM reading_revisions WHERE owner=?',(owner,)).fetchone()
    rows=db.execute('SELECT doc_id,value,updated FROM reading_status WHERE owner=? ORDER BY doc_id',(owner,)).fetchall()
    return {'revision':row[0] if row else 0,'items':{d:v for d,v,_ in rows},'updated':{d:t for d,_,t in rows}}

def write_reading(db,owner,revision,changed,now):
    for doc,value in changed:
        if value=='none':db.execute('DELETE FROM reading_status WHERE owner=? AND doc_id=?',(owner,doc))
        else:db.execute('INSERT OR REPLACE INTO reading_status VALUES(?,?,?,?)',(owner,doc,value,now))
    if changed:db.execute('INSERT INTO reading_revisions VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET revision=excluded.revision',(owner,revision+1))

def install_readinglog(app):
    store,catalog=app.state.preferences,app.state.catalog
    secret=persistent_secret(app.state.settings.data_dir)
    with store.connect() as db:
        # Additive schema only. No FK cascade: legacy preference reset replaces its own revision row.
        db.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS reading_revisions(owner TEXT PRIMARY KEY, revision INTEGER NOT NULL CHECK(revision>=0));
            CREATE TABLE IF NOT EXISTS reading_status(owner TEXT NOT NULL,doc_id TEXT NOT NULL,
                value TEXT NOT NULL CHECK(value IN ('to_read','reading','read')),updated TEXT NOT NULL,
                PRIMARY KEY(owner,doc_id));
            COMMIT;
        """)

    def same(key):
        if not catalog.compatible_key(key):raise HTTPException(409,'目录版本已变化，请刷新后重试')

    def check_doc(doc,version):
        if not catalog.valid(doc):raise HTTPException(422,'论文不在当前目录')
        if version!=catalog.by_id[doc]['version_key']:raise HTTPException(409,'论文版本不一致')

    def view(snapshot):
        order=sorted(snapshot['items'],key=lambda d:(snapshot['updated'].get(d,''),d),reverse=True)
        return {'revision':snapshot['revision'],'catalog_key':catalog.catalog_key,
            'items':[{**catalog.paper(d),'reading_state':snapshot['items'][d],'updated_at':snapshot['updated'][d]} for d in order],
            'counts':{state:sum(v==state for v in snapshot['items'].values()) for state in READING_STATES},
            'scope':'显式阅读状态，独立于收藏与推荐；打开摘要不会自动标为已读。'}

    @app.get('/api/profile/reading')
    def reading_list(request:Request):
        with store.connect() as db:
            db.execute('BEGIN');return view(reading_snapshot(db,request.state.owner))

    @app.post('/api/profile/reading/feedback')
    def reading_change(body:ReadingFeedback,request:Request):
        same(body.catalog_key);check_doc(body.doc_id,body.version_key)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE');before=reading_snapshot(db,request.state.owner)
            if body.revision!=before['revision']:raise HTTPException(409,'阅读清单已变化，请刷新后重试')
            previous=before['items'].get(body.doc_id,'none')
            if previous!=body.value:
                if body.value!='none' and body.doc_id not in before['items'] and len(before['items'])>=500:
                    raise HTTPException(422,'阅读清单最多保存500篇')
                write_reading(db,request.state.owner,before['revision'],[(body.doc_id,body.value)],datetime.now(timezone.utc).isoformat())
            final=reading_snapshot(db,request.state.owner)
        return {**view(final),'change':{'doc_id':body.doc_id,'previous_value':previous,'value':body.value}}

    def parse_library(text):
        if len(text.encode('utf-8'))>MAX_FILE:raise HTTPException(413,'备份文件不能超过256 KiB')
        try:value=json.loads(text.lstrip('\ufeff'),object_pairs_hook=unique_object)
        except (ValueError,RecursionError) as error:raise HTTPException(422,'备份JSON格式无效或字段重复') from error
        if isinstance(value,dict) and value.get('format')=='papertrail-preferences':
            return app.state.parse_preference_backup(text),[],1
        try:
            if not isinstance(value,dict) or type(value.get('schema_version')) is not int:raise ValueError('version')
            backup=LibraryBackup.model_validate(value);aware_timestamp(backup.exported_at)
        except (ValueError,ValidationError,RecursionError) as error:raise HTTPException(422,'需要本站v2清单备份或v1偏好备份') from error
        same(backup.catalog_key)
        prefs=app.state.parse_preference_backup(json.dumps({'format':'papertrail-preferences','schema_version':1,
            'catalog_key':backup.catalog_key,'exported_at':backup.exported_at,'items':backup.preferences},ensure_ascii=False))
        seen=set()
        for row in backup.reading:
            if backup.catalog_key==catalog.core.catalog_key and row.doc_id not in catalog.core.by_id:raise HTTPException(422,'旧目录备份不能伪装包含新增论文')
            if row.doc_id in seen:raise HTTPException(422,'阅读清单存在重复论文ID')
            seen.add(row.doc_id);check_doc(row.doc_id,row.version_key)
            if any(getattr(row,k)!=catalog.paper(row.doc_id)[k] for k in ('title','source_url')):
                raise HTTPException(409,'阅读清单标题或来源不一致，未导入')
        return prefs,backup.reading,2

    def revision_check(body,prefs,reading):
        if type(body.revision) is not int or body.revision!=prefs['revision'] or body.reading_revision!=reading['revision']:
            raise HTTPException(409,'收藏或阅读清单已变化，请重新预览')

    def token(owner,body,prefs,reading):
        raw=json.dumps([catalog.catalog_key,owner,body.text,body.policy,prefs,reading],sort_keys=True,ensure_ascii=False).encode()
        return hmac.new(secret,b'library-import:'+raw,hashlib.sha256).hexdigest()

    def plans(backup,rows,prefs,reading,policy):
        pmerged,pplan=merge_plan(backup,prefs,policy)
        rmerged,rplan=merge_plan(SimpleNamespace(items=rows),reading,policy)
        return pmerged,rmerged,{**pplan,'reading':rplan,'changes_total':pplan['counts']['added']+pplan['counts']['changed']+rplan['counts']['added']+rplan['counts']['changed']}

    @app.get('/api/profile/library/export')
    def library_export(request:Request):
        with store.connect() as db:
            db.execute('BEGIN');prefs=store.snapshot(db,request.state.owner);reading=reading_snapshot(db,request.state.owner)
        def identity(doc):return {k:v for k,v in catalog.paper(doc).items() if k!='version'}
        value={'format':'papertrail-library','schema_version':2,'catalog_key':catalog.catalog_key,'exported_at':datetime.now(timezone.utc).isoformat(),
            'preferences':[identity(d)|{'preference':v} for d,v in prefs['items'].items()],
            'reading':[identity(d)|{'state':v} for d,v in reading['items'].items()]}
        return Response(json.dumps(value,ensure_ascii=False,indent=2)+'\n',media_type='application/json',
            headers={'Content-Disposition':'attachment; filename="papertrail-library-v2.json"'})

    @app.post('/api/profile/library/import/preview')
    def library_preview(body:LibraryImport,request:Request):
        backup,rows,version=parse_library(body.text)
        with store.connect() as db:
            db.execute('BEGIN');prefs=store.snapshot(db,request.state.owner);reading=reading_snapshot(db,request.state.owner)
        revision_check(body,prefs,reading)
        _,_,plan=plans(backup,rows,prefs,reading,body.policy)
        return {**plan,'revision':prefs['revision'],'reading_revision':reading['revision'],'catalog_key':catalog.catalog_key,
            'policy':body.policy,'file_version':version,'exported_at':backup.exported_at,'preview_token':token(request.state.owner,body,prefs,reading),
            'migrated_from':backup.catalog_key if backup.catalog_key!=catalog.catalog_key else None,
            'file_sha256':hashlib.sha256(body.text.encode()).hexdigest()}

    @app.post('/api/profile/library/import/apply')
    def library_apply(body:LibraryImport,request:Request):
        backup,rows,version=parse_library(body.text)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE');prefs=store.snapshot(db,request.state.owner);reading=reading_snapshot(db,request.state.owner)
            revision_check(body,prefs,reading)
            if not body.preview_token or not hmac.compare_digest(body.preview_token,token(request.state.owner,body,prefs,reading)):
                raise HTTPException(409,'预览已失效，请重新预览')
            pmerged,rmerged,plan=plans(backup,rows,prefs,reading,body.policy)
            pchanged=[(d,v) for d,v in pmerged.items() if prefs['items'].get(d)!=v]
            rchanged=[(d,v) for d,v in rmerged.items() if reading['items'].get(d)!=v]
            now=datetime.now(timezone.utc).isoformat()
            if pchanged:
                db.executemany('INSERT OR REPLACE INTO preferences VALUES(?,?,?,?)',[(request.state.owner,d,v,now) for d,v in pchanged])
                db.execute('UPDATE visitors SET revision=? WHERE owner=?',(prefs['revision']+1,request.state.owner))
            write_reading(db,request.state.owner,reading['revision'],rchanged,now)
            final_p=store.snapshot(db,request.state.owner);final_r=reading_snapshot(db,request.state.owner)
        return {**plan,'revision':final_p['revision'],'reading_revision':final_r['revision'],'applied':len(pchanged),
            'reading_applied':len(rchanged),'total_applied':len(pchanged)+len(rchanged),'catalog_key':catalog.catalog_key,'file_version':version}

    app.state.reading_snapshot=reading_snapshot
    app.state.library_parse=parse_library
    app.state.library_plans=plans
