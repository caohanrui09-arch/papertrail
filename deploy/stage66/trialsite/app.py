"""Standalone deployable trial: immutable public assets and private visitor volume."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .catalog import Catalog
from .workspacecatalog import WorkspaceCatalog
from .catalogfilters import collections
from .reuse import Feedback, Reset, PreferenceConflict, ImportRequest, parse_backup, merge_plan, unique_object
from .security import Settings, TrialStore, TrialBoundary, persistent_secret

ROOT = Path(__file__).resolve().parents[1]


def create_app(settings: Settings | None = None):
    settings = settings or Settings(os.environ.get('PAPERTRAIL_ORIGIN') or os.environ['RENDER_EXTERNAL_URL'],Path(os.environ['PAPERTRAIL_DATA_DIR']))
    settings.validate()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    catalog = WorkspaceCatalog(ROOT/'catalog',ROOT/'supplement')
    store = TrialStore(settings.data_dir/(catalog.signature['catalog_sha256']+'.sqlite3'), settings.max_visitors)
    secret = persistent_secret(settings.data_dir)
    previews = catalog.previews()
    migration = json.loads((ROOT/'catalog/migration.json').read_text(encoding='utf-8'))

    @asynccontextmanager
    async def lifespan(app):
        yield
        catalog.close()
    app = FastAPI(docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.state.catalog, app.state.preferences, app.state.settings = catalog,store,settings
    app.add_middleware(TrialBoundary,settings=settings,store=store,secret=secret)

    @app.exception_handler(sqlite3.OperationalError)
    async def database_busy(request, error):
        return JSONResponse({'detail':'偏好存储繁忙或已达到容量，请稍后重试'},503,headers={'Retry-After':'60'})

    def same(key: str):
        if key != catalog.catalog_key: raise HTTPException(409,'目录版本已变化，请刷新后重试')

    def view(snapshot: dict) -> dict:
        items = [{**catalog.paper(doc),'preference':value} for doc,value in snapshot['items'].items()]
        return {'revision':snapshot['revision'],'catalog_key':catalog.catalog_key,'catalog_size':len(catalog.catalog),
                'items':items,'like_count':sum(r['preference']=='like' for r in items),
                'hidden_count':sum(r['preference']=='hide' for r in items),
                'scope':'当前浏览器凭据对应的独立服务器空间；请定期导出备份；未登录账号。'}

    @app.get('/api/health')
    def health():
        return {'status':'ready','catalog':len(catalog.catalog),'llm_enabled':False,'release':'stage39',
                'instance_id':os.environ.get('PAPERTRAIL_INSTANCE','manual')}

    @app.get('/api/meta')
    def meta():
        return {'topics':catalog.topics,'at':catalog.at,'catalog':len(catalog.catalog),'synthetic':True,
                'rules':{k:'当前目录无真人相关性标签，不套用旧模型分级。' for k in catalog.topics},
                'summary':{k:{'0':0,'1':0,'2':0} for k in catalog.topics},'catalog_key':catalog.catalog_key,
                'previous_catalog_key':catalog.core.catalog_key,'core_catalog':len(catalog.core.catalog),'core_at':catalog.core.at,
                'supplement':len(catalog.supplement_ids),'supplement_label':catalog.supplement['label'],'supplement_query':catalog.supplement['query'],'collections':collections(catalog)}

    @app.get('/api/paper-previews')
    def get_previews(): return previews

    @app.get('/api/search')
    def search(topic:Literal['generative','cold','bias'],q:str=Query(min_length=1,max_length=1000),
               method:Literal['bm25','tfidf']='bm25',context:Literal['none','same','cross']='none'):
        if not q.strip(): raise HTTPException(422,'请输入查询')
        return catalog.search(topic,q,method,context)

    @app.get('/api/paper/{doc}')
    def paper(doc: str):
        return {'paper':catalog.read(doc),'trace':[{'tool':'读取官方原v1摘要','doc_id':doc,'source_verified':True}]}

    @app.get('/api/profile')
    def profile(request: Request): return view(store.get(request.state.owner))

    @app.post('/api/profile/feedback')
    def feedback(body: Feedback,request: Request):
        same(body.catalog_key)
        if not catalog.valid(body.doc_id): raise HTTPException(422,'论文不在当前目录')
        if body.version_key != catalog.by_id[body.doc_id]['version_key']: raise HTTPException(409,'论文版本不一致')
        before = store.get(request.state.owner)
        try: final = store.change(request.state.owner,body.revision,body.doc_id,body.value)
        except PreferenceConflict as error: raise HTTPException(409,str(error)) from error
        except ValueError as error: raise HTTPException(422,str(error)) from error
        return {**view(final),'change':{'doc_id':body.doc_id,'version_key':body.version_key,
                'previous_value':before['items'].get(body.doc_id,'none'),'value':body.value}}

    @app.post('/api/profile/reset')
    def reset(body: Reset,request: Request):
        same(body.catalog_key)
        try: return view(store.change(request.state.owner,body.revision,None,'reset'))
        except PreferenceConflict as error: raise HTTPException(409,str(error)) from error

    @app.get('/api/recommendations')
    def recommend(request: Request): return catalog.recommend(store.get(request.state.owner))

    def backup_for(text: str):
        # Old 42-paper exports migrate only after every canonical field and membership check.
        try:
            value = json.loads(text.lstrip('\ufeff'),object_pairs_hook=unique_object)
        except (ValueError,RecursionError):
            return parse_backup(text,catalog)
        if isinstance(value,dict) and value.get('catalog_key') == catalog.core.catalog_key:
            return parse_backup(text,catalog.core)
        if isinstance(value,dict) and value.get('catalog_key') == migration['accepted_previous_catalog']:
            previous = SimpleNamespace(catalog_key=migration['accepted_previous_catalog'],
                valid=lambda doc:doc in migration['original_ids'] and catalog.valid(doc),paper=catalog.paper)
            return parse_backup(text,previous)
        return parse_backup(text,catalog)

    app.state.parse_preference_backup = backup_for

    def check_revision(body: ImportRequest,snapshot: dict):
        if body.revision != snapshot['revision']: raise HTTPException(409,'偏好已变化，请重新预览')

    def preview_token(owner: str,body: ImportRequest,snapshot: dict) -> str:
        raw = json.dumps([catalog.catalog_key,owner,body.text,body.policy,snapshot],sort_keys=True,ensure_ascii=False).encode()
        return hmac.new(secret,b'import:'+raw,hashlib.sha256).hexdigest()

    @app.get('/api/profile/export')
    def export(request: Request):
        snapshot = store.get(request.state.owner)
        value = {'format':'papertrail-preferences','schema_version':1,'catalog_key':catalog.catalog_key,
           'exported_at':datetime.now(timezone.utc).isoformat(),
           'items':[{key:value for key,value in catalog.paper(doc).items() if key!='version'}|{'preference':pref}
                    for doc,pref in snapshot['items'].items()]}
        return Response(json.dumps(value,ensure_ascii=False,indent=2)+'\n',media_type='application/json',
                        headers={'Content-Disposition':'attachment; filename="papertrail-preferences-v1.json"'})

    @app.post('/api/profile/import/preview')
    def preview(body: ImportRequest,request: Request):
        backup = backup_for(body.text)
        snapshot = store.get(request.state.owner)
        check_revision(body,snapshot)
        _, plan = merge_plan(backup,snapshot,body.policy)
        return {**plan,'revision':snapshot['revision'],'catalog_key':catalog.catalog_key,'policy':body.policy,
                'exported_at':backup.exported_at,'preview_token':preview_token(request.state.owner,body,snapshot),
                'migrated_from':backup.catalog_key if backup.catalog_key!=catalog.catalog_key else None,
                'file_sha256':hashlib.sha256(body.text.encode()).hexdigest()}

    @app.post('/api/profile/import/apply')
    def apply(body: ImportRequest,request: Request):
        backup = backup_for(body.text)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            snapshot = store.snapshot(db,request.state.owner)
            check_revision(body,snapshot)
            if not body.preview_token or not hmac.compare_digest(body.preview_token,preview_token(request.state.owner,body,snapshot)):
                raise HTTPException(409,'预览已失效，请重新预览')
            merged,plan = merge_plan(backup,snapshot,body.policy)
            changed = [(doc,value) for doc,value in merged.items() if snapshot['items'].get(doc)!=value]
            if changed:
                now = datetime.now(timezone.utc).isoformat()
                db.executemany('INSERT OR REPLACE INTO preferences VALUES(?,?,?,?)',
                    [(request.state.owner,doc,value,now) for doc,value in changed])
                db.execute('UPDATE visitors SET revision=? WHERE owner=?',(snapshot['revision']+1,request.state.owner))
            final = store.snapshot(db,request.state.owner)
        return {**plan,'revision':final['revision'],'applied':len(changed),'catalog_key':catalog.catalog_key}

    app.mount('/',StaticFiles(directory=ROOT/'web',html=True),name='trial-web')
    return app


def main(factory=create_app):
    import sys
    import uvicorn
    from filelock import FileLock
    from threadpoolctl import threadpool_limits
    preview = os.environ.get('PAPERTRAIL_LOCAL_PREVIEW')=='1'
    if not preview and (sys.version_info[:2] != (3,12) or sys.version_info[:3] < (3,12,16)):
        raise RuntimeError('Production requires the security-patched Python 3.12.16+ runtime; local preview is isolated')
    settings = Settings(os.environ.get('PAPERTRAIL_ORIGIN','http://127.0.0.1:8782') if preview else (os.environ.get('PAPERTRAIL_ORIGIN') or os.environ['RENDER_EXTERNAL_URL']),
                        Path(os.environ.get('PAPERTRAIL_DATA_DIR','./visitor-data')),production=not preview)
    settings.validate()
    settings.data_dir.mkdir(parents=True,exist_ok=True)
    # Prevent two processes sharing a volume while using independent memory limiters.
    with FileLock(str(settings.data_dir/'single-instance.lock'),timeout=0),threadpool_limits(limits=1):
        uvicorn.run(factory(settings),host='127.0.0.1' if preview else '0.0.0.0',
                    port=int(os.environ.get('PORT','8782' if preview else '10000')),
                    workers=1,proxy_headers=False,limit_concurrency=32,backlog=64,
                    timeout_keep_alive=5,timeout_graceful_shutdown=15,access_log=False,ws='none',server_header=False)


if __name__=='__main__': main()
