"""Local presentation gateway; frozen algorithms and Agent policies stay unchanged."""
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import base64
import json
import secrets
from pathlib import Path
from queue import Queue
import re
from threading import Thread,Event
import time
from typing import Literal
from uuid import UUID,uuid4
from urllib.error import URLError
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import JSONResponse,StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel,ConfigDict,Field,model_validator
from .unified_agent import ToolClient,fixed,request as upstream
from .portfolio_demo import select_task,ASOF
from .quality_protocol import save
from .visitor_profile import Catalog,Preferences,PreferenceConflict,PersonalClient

STATIC=Path('web/papertrail-v24/dist').resolve()
DATA=Path('data/stage24-personal').resolve()
RUNS=DATA/'runs'
READS=DATA/'reads'
ACTIVE: dict[str,Event]={}
PAPER_KEYS=('doc_id','version','version_key','title','abstract','source_url','available_at','source_verified','quotes')


class RunRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    thread_id: UUID
    mode: Literal['search','recommend','mixed']='search'
    query: str=Field(default='',max_length=2000)
    profile: Literal['personal','warm','cold']='personal'
    origin: Literal['interactive','verification']='interactive'

    @model_validator(mode='after')
    def query_required(self):
        if self.mode!='recommend' and not self.query.strip():raise ValueError('请输入英文关键词或论文标题')
        return self


class FeedbackRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    doc_id: str=Field(pattern=r'^\d{4}\.\d{4,5}$')
    value: Literal['like','hide','none']
    revision: int=Field(ge=0,strict=True)
    run_id: UUID | None=None


class ResetRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision: int=Field(ge=0,strict=True)


def safe_result(name: str,result: dict) -> dict:
    if 'error' in result:return result
    if name=='read_paper':return {k:result[k] for k in PAPER_KEYS if k in result}
    if 'papers' in result:
        return {**result,'papers':[{k:p[k] for k in ('doc_id','version','title','source_url','score','explanation') if k in p} for p in result['papers']]}
    return result


def public_record(record: dict) -> dict:
    value={k:v for k,v in record.items() if not k.startswith('_')}
    value=deepcopy(value)
    for event in value.get('trace',[]):event['result']=safe_result(event['tool'],event['result'])
    return value


def load_run(run_id: UUID, owner: str) -> dict:
    path=RUNS/f'{run_id}.json'
    if not path.is_file():raise HTTPException(404,'找不到这次请求')
    value=json.loads(path.read_text(encoding='utf-8'))
    if value.get('_owner')!=owner:raise HTTPException(404,'找不到这次请求')
    return value


def store(record: dict) -> None:
    path=RUNS/(record['id']+'.json');tmp=path.with_suffix('.tmp')
    save(tmp,record);tmp.replace(path)


def execute(body: RunRequest,context: dict,owner: str,catalog: Catalog,preferences: dict):
    ident=str(uuid4());queue=Queue();cancel=Event();ACTIVE[ident]=cancel
    task={**context,'id':ident,'intent':body.mode,'query':body.query.strip(),
        'user_id':context['user_id'] if body.profile=='warm' else 'papertrail-unknown-profile',
        'instruction':'Use the frozen fixed policy; cite exact original v1 abstract excerpts.'}
    record={'id':ident,'thread_id':str(body.thread_id),'created':datetime.now(timezone.utc).isoformat(),
        'params':body.model_dump(mode='json'),'title':body.query.strip()[:60] if body.mode!='recommend' else
            ('基于我的收藏发现论文' if body.profile=='personal' else '基于训练画像发现论文' if body.profile=='warm' else '冷启动用户论文推荐'),
        'status':'running','trace':[],'answer':None,'error':None,'seconds':0,'llm_calls':0,
        'workflow':'fixed','as_of':ASOF,'_task':task,'_owner':owner,'_preferences':preferences,
        'profile_revision':preferences['revision'] if body.profile=='personal' else None}
    store(record)

    class ObservedClient(PersonalClient if body.profile=='personal' else ToolClient):
        def call(self,name: str,**arguments: object) -> dict:
            if cancel.is_set():raise ValueError('请求已取消；已执行工具仍保留在轨迹中')
            queue.put({'type':'tool_start','tool':name,'arguments':arguments})
            started=time.perf_counter()
            try:
                result=super().call(name,**arguments)
                queue.put({'type':'tool_result','tool':name,'arguments':arguments,
                    'result':safe_result(name,result),'seconds':time.perf_counter()-started})
                return result
            except (ValueError,URLError,TimeoutError,OSError) as error:
                queue.put({'type':'tool_error','tool':name,'message':str(error)})
                raise

    def worker() -> None:
        started=time.perf_counter();client=None
        try:
            client=ObservedClient(task,catalog,preferences) if body.profile=='personal' else ObservedClient(task)
            answer=fixed(client,task);record['answer']=answer
            citations=answer['citations'];expected=2 if body.mode=='mixed' else 1
            record['status']='completed' if len(citations)==expected else 'no_results' if not citations else 'partial'
        except Exception as error:
            record['status']='cancelled' if cancel.is_set() else 'failed'
            record['error']=str(error)
        finally:
            if client is not None:
                try:record['trace']=client.snapshot()['trace']
                except (ValueError,URLError,TimeoutError,OSError):record['trace_unavailable']=True
                try:client.close()
                except (ValueError,URLError,TimeoutError,OSError):record['session_cleanup_pending']=True
            record['seconds']=time.perf_counter()-started;store(record);ACTIVE.pop(ident,None)
            queue.put({'type':'done','run':public_record(record)})

    Thread(target=worker,name='papertrail-'+ident[:8],daemon=True).start()
    yield json.dumps({'type':'start','run_id':ident,'thread_id':str(body.thread_id)},ensure_ascii=False)+'\n'
    while True:
        event=queue.get()
        yield json.dumps(event,ensure_ascii=False)+'\n'
        if event['type']=='done':break


def create_app() -> FastAPI:
    context,_=select_task()
    catalog=Catalog()
    preferences=Preferences(DATA/'preferences.sqlite3')
    app=FastAPI(title='Papertrail local workbench',docs_url=None,redoc_url=None)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost'])
    importmap=re.search(r'<script type="importmap">([\s\S]*?)</script>',(STATIC/'index.html').read_text(encoding='utf-8')).group(1)
    script_hash=base64.b64encode(hashlib.sha256(importmap.encode()).digest()).decode()

    @app.middleware('http')
    async def local_boundary(request: Request,call_next):
        origin=request.headers.get('origin')
        if request.method not in ('GET','HEAD') and origin and origin!=str(request.base_url).rstrip('/'):
            return JSONResponse({'detail':'本地工作台仅接受同源请求'},status_code=403)
        if request.headers.get('sec-fetch-site')=='cross-site':
            return JSONResponse({'detail':'仅接受本站请求'},status_code=403)
        token=request.cookies.get('papertrail_visitor')
        fresh=not token or not re.fullmatch(r'[a-f0-9]{64}',token)
        if fresh:token=secrets.token_hex(32)
        request.state.owner=hashlib.sha256(token.encode()).hexdigest()
        response=await call_next(request)
        if fresh:response.set_cookie('papertrail_visitor',token,httponly=True,samesite='strict',max_age=31536000,path='/')
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']=f"default-src 'self'; script-src 'self' 'sha256-{script_hash}'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
        if request.url.path.startswith('/api/'):response.headers['Cache-Control']='no-store'
        return response

    @app.get('/api/health')
    def health():
        try:
            code,value=upstream('GET','/health')
            if code!=200:raise ValueError('upstream unavailable')
            return {'status':'ready','candidates':value['candidates'],'default_recommendation':value['default_recommendation'],
                'execution':'fixed','llm_enabled':False,'instance_id':__import__('os').environ.get('GSEARCH_WORKBENCH_INSTANCE','foreground')}
        except (URLError,TimeoutError,OSError,ValueError):raise HTTPException(503,'论文服务尚未连接，请运行workbench.cmd start')

    @app.get('/api/config')
    def config():
        return {'name':'Papertrail','as_of':ASOF,'history_cutoff':'2024-10-27','catalog_size':10000,
            'execution':'fixed','llm_enabled':False,'example_query':context['query'],
            'profiles':[{'value':'personal','label':'我的收藏画像'},{'value':'warm','label':'训练画像用户'},{'value':'cold','label':'冷启动用户'}],
            'deployment':'local','sharing_ready':False}

    @app.post('/api/runs')
    def run(body: RunRequest,request: Request):
        snapshot=preferences.get(request.state.owner)
        return StreamingResponse(execute(body,context,request.state.owner,catalog,snapshot),media_type='application/x-ndjson',headers={'X-Accel-Buffering':'no'})

    @app.post('/api/runs/{run_id}/cancel')
    def cancel(run_id: UUID,request: Request):
        load_run(run_id,request.state.owner)
        flag=ACTIVE.get(str(run_id))
        if flag:flag.set()
        return {'cancellation_requested':flag is not None,'note':'已执行的请求继续保留真实轨迹'}

    @app.get('/api/threads')
    def threads(request: Request):
        groups={}
        for path in RUNS.glob('*.json'):
            r=json.loads(path.read_text(encoding='utf-8'));key=r['thread_id']
            if r.get('_owner')!=request.state.owner:continue
            if r['params'].get('origin')=='verification':continue
            if key not in groups or r['created']>groups[key]['updated']:
                title=r['title']
                if r['params']['mode']=='recommend' and r['params']['profile']=='cold':title='冷启动用户论文推荐'
                groups[key]={'id':key,'title':title,'updated':r['created'],'status':r['status']}
        return sorted(groups.values(),key=lambda r:r['updated'],reverse=True)[:50]

    @app.get('/api/threads/{thread_id}')
    def thread(thread_id: UUID,request: Request):
        values=[json.loads(p.read_text(encoding='utf-8')) for p in RUNS.glob('*.json')]
        return [public_record(r) for r in sorted(values,key=lambda r:r['created']) if r['thread_id']==str(thread_id) and r.get('_owner')==request.state.owner]

    @app.get('/api/runs/{run_id}/export')
    def export(run_id: UUID,request: Request):
        return JSONResponse(public_record(load_run(run_id,request.state.owner)),headers={
            'Content-Disposition':f'attachment; filename="papertrail-{run_id}.json"'})

    @app.post('/api/runs/{run_id}/papers/{doc_id}')
    def read_paper(run_id: UUID,doc_id: str,request: Request):
        run=load_run(run_id,request.state.owner)
        if not re.fullmatch(r'\d{4}\.\d{4,5}',doc_id):raise HTTPException(400,'无效论文ID')
        for event in run['trace']:
            if event['tool']=='read_paper' and event['result'].get('doc_id')==doc_id:
                return {'paper':safe_result('read_paper',event['result']),'trace':[],'cached_original':True,'new_source_session':False}
        retrieval=None
        for event in run['trace']:
            if event['tool'] in ('search_papers','recommend_papers') and any(p['doc_id']==doc_id for p in event['result'].get('papers',[])):
                retrieval=event;break
        if retrieval is None:raise HTTPException(403,'仅可读取这次请求返回的论文')
        cached=READS/str(run_id)/(doc_id+'.json')
        if cached.is_file():
            previous=json.loads(cached.read_text(encoding='utf-8'))
            return {**previous,'trace':[],'source_session_trace':previous['trace'],
                'cached_original':True,'new_source_session':False}
        client=None;response={}
        try:
            client=PersonalClient(run['_task'],catalog,run['_preferences']) if run['params']['profile']=='personal' else ToolClient(run['_task'])
            output=client.call(retrieval['tool'],**retrieval['arguments'])
            if not any(p['doc_id']==doc_id for p in output['papers']):raise ValueError('重放检索没有返回该ID')
            paper=client.call('read_paper',doc_id=doc_id)
            response={'paper':safe_result('read_paper',paper),'new_source_session':True,'cached_original':False,
                'trace':client.snapshot()['trace'],'note':'单独来源读取会话，重新检索后读取；不占用已结束会话额度'}
            for event in response['trace']:event['result']=safe_result(event['tool'],event['result'])
            # Keep each executed source session, including simultaneous reads.
            save(cached.with_name(doc_id+'-'+str(uuid4())+'-audit.json'),response)
            temp=cached.with_suffix('.'+str(uuid4())+'.tmp');save(temp,response);temp.replace(cached)
            return response
        except (ValueError,URLError,TimeoutError,OSError) as error:
            failure={'error':str(error),'trace':[]}
            if client:
                try:failure['trace']=client.snapshot()['trace']
                except (ValueError,URLError,TimeoutError,OSError):failure['trace_unavailable']=True
            save(READS/str(run_id)/(doc_id+'-failed-'+str(uuid4())+'.json'),failure)
            raise HTTPException(400,'原摘要读取失败，真实失败轨迹已保留')
        finally:
            if client:
                try:client.close()
                except (ValueError,URLError,TimeoutError,OSError):pass

    @app.get('/api/evidence')
    def evidence():
        value=json.loads(Path('reports/stage22/evidence-index.json').read_text(encoding='utf-8'))
        return {'claims':value['claims'],'defaults':value['defaults'],'scope':value['scope']}

    def profile_view(snapshot: dict) -> dict:
        return {'revision':snapshot['revision'],'items':[catalog.paper(d)|{'preference':v} for d,v in snapshot['items'].items()],
                'scope':'当前浏览器个人空间；当下偏好作用于冻结历史目录，不是历史质量评价'}

    @app.get('/api/profile')
    def profile(request: Request):
        return profile_view(preferences.get(request.state.owner))

    @app.post('/api/profile/feedback')
    def feedback(body: FeedbackRequest,request: Request):
        if not catalog.valid(body.doc_id):raise HTTPException(422,'论文不在可用目录中')
        snapshot=preferences.get(request.state.owner)
        if body.doc_id not in snapshot['items']:
            if body.run_id is None:raise HTTPException(403,'先搜索或推荐这篇论文')
            run=load_run(body.run_id,request.state.owner)
            if not any(p['doc_id']==body.doc_id for e in run['trace'] for p in e['result'].get('papers',[])):
                raise HTTPException(403,'论文未在当前结果中返回')
        try:return profile_view(preferences.change(request.state.owner,body.revision,body.doc_id,body.value))
        except PreferenceConflict as error:raise HTTPException(409,str(error))
        except ValueError as error:raise HTTPException(422,str(error))

    @app.post('/api/profile/reset')
    def reset(body: ResetRequest,request: Request):
        try:return profile_view(preferences.change(request.state.owner,body.revision,None,'reset'))
        except PreferenceConflict as error:raise HTTPException(409,str(error))

    @app.get('/api/quality-status')
    def quality_status():
        from .human_quality import load_state
        from .quality_protocol import coverage
        return coverage(*load_state())

    app.mount('/',StaticFiles(directory=STATIC,html=True),name='workbench')
    return app


def main() -> None:
    import argparse,uvicorn
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8768);args=parser.parse_args()
    if not 1024<=args.port<=65535:raise ValueError('Unprivileged local port required')
    uvicorn.run(create_app(),host='127.0.0.1',port=args.port,access_log=False,ws='none',workers=1)


if __name__=='__main__':main()
