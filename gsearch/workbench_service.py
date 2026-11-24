"""Local presentation gateway; frozen algorithms and Agent policies stay unchanged."""
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import base64
import json
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

STATIC=Path('web/papertrail/dist').resolve()
DATA=Path('data/stage23-web').resolve()
RUNS=DATA/'runs'
READS=DATA/'reads'
ACTIVE: dict[str,Event]={}
PAPER_KEYS=('doc_id','version','version_key','title','abstract','source_url','available_at','source_verified','quotes')


class RunRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    thread_id: UUID
    mode: Literal['search','recommend','mixed']='search'
    query: str=Field(default='',max_length=2000)
    profile: Literal['warm','cold']='warm'
    origin: Literal['interactive','verification']='interactive'

    @model_validator(mode='after')
    def query_required(self):
        if self.mode!='recommend' and not self.query.strip():raise ValueError('请输入英文关键词或论文标题')
        return self


def safe_result(name: str,result: dict) -> dict:
    if 'error' in result:return result
    if name=='read_paper':return {k:result[k] for k in PAPER_KEYS if k in result}
    if 'papers' in result:
        return {**result,'papers':[{k:p[k] for k in ('doc_id','version','title','source_url','score') if k in p} for p in result['papers']]}
    return result


def public_record(record: dict) -> dict:
    value={k:v for k,v in record.items() if not k.startswith('_')}
    value=deepcopy(value)
    for event in value.get('trace',[]):event['result']=safe_result(event['tool'],event['result'])
    return value


def load_run(run_id: UUID) -> dict:
    path=RUNS/f'{run_id}.json'
    if not path.is_file():raise HTTPException(404,'找不到这次请求')
    return json.loads(path.read_text(encoding='utf-8'))


def store(record: dict) -> None:
    path=RUNS/(record['id']+'.json');tmp=path.with_suffix('.tmp')
    save(tmp,record);tmp.replace(path)


def execute(body: RunRequest,context: dict):
    ident=str(uuid4());queue=Queue();cancel=Event();ACTIVE[ident]=cancel
    task={**context,'id':ident,'intent':body.mode,'query':body.query.strip(),
        'user_id':context['user_id'] if body.profile=='warm' else 'papertrail-unknown-profile',
        'instruction':'Use the frozen fixed policy; cite exact original v1 abstract excerpts.'}
    record={'id':ident,'thread_id':str(body.thread_id),'created':datetime.now(timezone.utc).isoformat(),
        'params':body.model_dump(mode='json'),'title':body.query.strip()[:60] if body.mode!='recommend' else
            ('基于训练画像发现论文' if body.profile=='warm' else '冷启动用户论文推荐'),
        'status':'running','trace':[],'answer':None,'error':None,'seconds':0,'llm_calls':0,
        'workflow':'fixed','as_of':ASOF,'_task':task}
    store(record)

    class ObservedClient(ToolClient):
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
            client=ObservedClient(task);answer=fixed(client,task);record['answer']=answer
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
    app=FastAPI(title='Papertrail local workbench',docs_url=None,redoc_url=None)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost'])
    importmap=re.search(r'<script type="importmap">([\s\S]*?)</script>',(STATIC/'index.html').read_text(encoding='utf-8')).group(1)
    script_hash=base64.b64encode(hashlib.sha256(importmap.encode()).digest()).decode()

    @app.middleware('http')
    async def local_boundary(request: Request,call_next):
        origin=request.headers.get('origin')
        if request.method not in ('GET','HEAD') and origin and origin!=str(request.base_url).rstrip('/'):
            return JSONResponse({'detail':'本地工作台仅接受同源请求'},status_code=403)
        response=await call_next(request)
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
            'profiles':[{'value':'warm','label':'训练画像用户'},{'value':'cold','label':'冷启动用户'}],
            'deployment':'local','sharing_ready':False}

    @app.post('/api/runs')
    def run(body: RunRequest):
        return StreamingResponse(execute(body,context),media_type='application/x-ndjson',headers={'X-Accel-Buffering':'no'})

    @app.post('/api/runs/{run_id}/cancel')
    def cancel(run_id: UUID):
        flag=ACTIVE.get(str(run_id))
        if flag:flag.set()
        return {'cancellation_requested':flag is not None,'note':'已执行的请求继续保留真实轨迹'}

    @app.get('/api/threads')
    def threads():
        groups={}
        for path in RUNS.glob('*.json'):
            r=json.loads(path.read_text(encoding='utf-8'));key=r['thread_id']
            if r['params'].get('origin')=='verification':continue
            if key not in groups or r['created']>groups[key]['updated']:
                title=r['title']
                if r['params']['mode']=='recommend' and r['params']['profile']=='cold':title='冷启动用户论文推荐'
                groups[key]={'id':key,'title':title,'updated':r['created'],'status':r['status']}
        return sorted(groups.values(),key=lambda r:r['updated'],reverse=True)[:50]

    @app.get('/api/threads/{thread_id}')
    def thread(thread_id: UUID):
        values=[json.loads(p.read_text(encoding='utf-8')) for p in RUNS.glob('*.json')]
        return [public_record(r) for r in sorted(values,key=lambda r:r['created']) if r['thread_id']==str(thread_id)]

    @app.get('/api/runs/{run_id}/export')
    def export(run_id: UUID):
        return JSONResponse(public_record(load_run(run_id)),headers={
            'Content-Disposition':f'attachment; filename="papertrail-{run_id}.json"'})

    @app.post('/api/runs/{run_id}/papers/{doc_id}')
    def read_paper(run_id: UUID,doc_id: str):
        run=load_run(run_id)
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
            client=ToolClient(run['_task'])
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

    app.mount('/',StaticFiles(directory=STATIC,html=True),name='workbench')
    return app


def main() -> None:
    import argparse,uvicorn
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8767);args=parser.parse_args()
    if not 1024<=args.port<=65535:raise ValueError('Unprivileged local port required')
    uvicorn.run(create_app(),host='127.0.0.1',port=args.port,access_log=False,ws='none',workers=1)


if __name__=='__main__':main()
