"""Auditable algorithms and real Agent jobs on the same frozen 10000 papers."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid
from typing import Literal

ROOT=Path(__file__).resolve().parents[1]
PORT=8802

class AuditModel:
    def __init__(self,model): self.base=model
    def __getattr__(self,key): return getattr(self.base,key)
    def recommend(self,user,at,method='content',k=3,alpha=.25):
        import numpy as np
        papers=self.base.recommend(user,at,method,k,alpha)
        cf,content=self.base.components(user)
        eligible=self.base.eligible(user,at)
        cold=user not in self.base.user2row or user in self.base.zero_profile_users
        scores=None
        if method=='cold_aware' and not cold:
            values=self.base.fused_scores(cf,content,eligible,alpha,True)
            scores={int(i):float(s) for i,s in zip(eligible,values)}
        history=self.base.history_matrix[self.base.user2row[user]].indices if not cold else []
        for paper in papers:
            i=self.base.position[paper['doc_id']]
            paper['algorithm_evidence']={'catalog':10000,'eligible_count':len(eligible),'history_size':len(history),
                'profile_kind':'frozen_training_history' if not cold else 'cold_user_popularity_fallback',
                'sar_score':float(cf[i]),'content_score':float(content[i]),
                'cf_branch_supported':bool(self.base._cf_supported[i]),
                'selected_score':scores[i] if scores is not None else float(content[i]) if method=='content' or cold else float(cf[i]) if method=='sar' else float(self.base.popularity[i]) if method=='popular' else None,
                'score_note':'RRF exposes component scores; no invented combined score' if method=='hybrid' else 'actual native score; score scales differ by method'}
            if len(history):
                similarities=(self.base.documents[history]@self.base.documents[i].T).toarray().ravel()
                j=int(np.argmax(similarities));doc=self.base.catalog[int(history[j])]
                paper['algorithm_evidence']['nearest_history_paper']={'doc_id':doc,'title':self.base.by_id[doc]['title'],'cosine':float(similarities[j])}
        return papers

def main():
    # Load the verified relocation, not a refit with newer packages or new data.
    import sys
    replica=ROOT/'.cache/stage17/replica'
    os.chdir(replica);sys.path.insert(0,str(replica))
    from gsearch.local_service import load_model
    from gsearch.unified_service import create_app
    from fastapi import HTTPException,Request
    from fastapi.responses import FileResponse,JSONResponse
    from pydantic import BaseModel,ConfigDict
    from threadpoolctl import threadpool_limits
    model=AuditModel(load_model());app=create_app(model,'algorithm-agent-lab63')
    tasks=json.loads((ROOT/'data/stage19-unified/benchmark/evaluation-tasks.json').read_text())[:3]
    presets={t['id']:t for t in tasks}
    folder=ROOT/'data/stage63-lab';folder.mkdir(parents=True,exist_ok=True)
    jobs={};lock=threading.Lock()
    @app.middleware('http')
    async def boundary(request:Request,call_next):
        if request.headers.get('host')!=f'127.0.0.1:{PORT}' or request.headers.get('sec-fetch-site')=='cross-site':
            return JSONResponse({'detail':'Use the local lab origin'},403)
        if request.method not in ('GET','HEAD') and request.headers.get('origin') not in (None,f'http://127.0.0.1:{PORT}'):
            return JSONResponse({'detail':'Same origin required'},403)
        response=await call_next(request);response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff';return response
    @app.get('/')
    def home():return FileResponse(ROOT/'research63/lab.html')
    @app.get('/lab.js')
    def js():return FileResponse(ROOT/'research63/lab.js',media_type='text/javascript')
    @app.get('/lab/presets')
    def choices():return {'tasks':[{k:t[k] for k in ('id','intent','query')} for t in tasks],
        'scope':'frozen training users, not current browser favorites; reused controlled tasks, not independent evaluation',
        'catalog':len(model.catalog),'default_algorithm':'content'}
    class Job(BaseModel):
        model_config=ConfigDict(extra='forbid')
        task_id:str='evaluation-002'
        policy:Literal['fixed','llm_agent','constrained']='constrained'
        compare:bool=False
    @app.post('/lab/run')
    def run(body:Job):
        if body.task_id not in presets:raise HTTPException(422,'Unknown preset')
        with lock:
            if any(j['process'].poll() is None for j in jobs.values()):raise HTTPException(409,'A model job is already running')
            if len(jobs)>=16:raise HTTPException(429,'Restart lab after 16 jobs; prior files retained')
            ident=str(uuid.uuid4());base=folder/ident;base.mkdir()
            spec={'tasks':tasks if body.compare else [presets[body.task_id]],'policies':['fixed','llm_agent','constrained'] if body.compare else [body.policy]}
            (base/'input.json').write_text(json.dumps(spec),encoding='utf8')
            log=(base/'worker.log').open('w',encoding='utf8')
            process=subprocess.Popen([str(ROOT/'.cache/stage6-env/Scripts/python.exe'),'-E','-s','-u','-m','research63.worker','--input',str(base/'input.json'),'--output',str(base/'result.json')],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            def expire_job():
                if process.poll() is None:process.kill()
            timer=threading.Timer(900,expire_job);timer.daemon=True;timer.start()
            log.close();jobs[ident]={'process':process,'folder':base}
            return {'id':ident,'status':'running','attempt_budget':6,'llm_calls':8,'model':'Qwen2.5-1.5B-Instruct','timeout_seconds':900}
    @app.get('/lab/jobs/{ident}')
    def status(ident:str):
        if ident not in jobs:raise HTTPException(404,'Unknown job')
        job=jobs[ident];code=job['process'].poll();path=job['folder']/'result.json'
        try:value=json.loads(path.read_text(encoding='utf8')) if path.exists() else None
        except json.JSONDecodeError:value=None
        return {'status':'running' if code is None else 'complete' if code==0 and value and value['complete'] else 'failed','exit_code':code,'result':value,'error':'Worker failed; retained local worker.log' if code not in (None,0) else None}
    class Algorithm(BaseModel):
        task_id:str='evaluation-002'
    @app.post('/lab/algorithms')
    def algorithms(body:Algorithm):
        if body.task_id not in presets:raise HTTPException(422,'Unknown preset')
        task=presets[body.task_id]
        with lock:
            return {'as_of':task['at'],'profile_kind':'frozen_training_user','methods':{name:model.recommend(task['user_id'],task['at'],name,10,.25 if name!='hybrid' else .5) for name in ('popular','sar','content','hybrid','cold_aware')},
                'scope':'same user, time, availability and seen mask; scores on incomparable scales; current diagnostic rankings, not quality evaluation'}
    @app.get('/lab/quality')
    def quality():
        return {'scope':'historical frozen descriptive dev; NOT this run or independent quality validation',
            'methods':{name:json.loads((ROOT/f'reports/stage15/{file}-dev.json').read_text())['summary'] for name,file in [('content','content'),('rrf','rrf'),('cold_aware','gated')]},
            'denominator':'49533 positive events; out-of-catalog positives remain misses; 3587-user macro mean'}
    import uvicorn
    with threadpool_limits(limits=1):uvicorn.run(app,host='127.0.0.1',port=PORT,access_log=False,ws='none')

if __name__=='__main__':main()
