"""Private localhost fixture: fail only the first learning-path request."""
import json
import os
from pathlib import Path
import sys
from typing import Literal

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deploy/stage40'))
from fastapi import HTTPException
from fastapi.staticfiles import StaticFiles
from trialsite.learning import create_app
from trialsite.security import Settings


if __name__=='__main__':
    import uvicorn
    from threadpoolctl import threadpool_limits
    folder=ROOT/'.cache/stage40/failure-fixture';folder.mkdir(parents=True,exist_ok=True)
    app=create_app(Settings('http://localhost:8786',folder/'visitors',production=False))
    app.router.routes[:]=[r for r in app.router.routes if getattr(r,'name',None)!='learning-web' and getattr(r,'path',None)!='/api/learning-path/{topic}']
    first=True
    @app.get('/api/learning-path/{topic}')
    def path(topic:Literal['generative','cold','bias']):
        global first
        if first:
            first=False
            raise HTTPException(503,'一次性导读故障夹具')
        return app.state.learning_paths[topic]
    app.mount('/',StaticFiles(directory=ROOT/'deploy/stage40/web',html=True),name='failure-web')
    (folder/'process.json').write_text(json.dumps({'pid':os.getpid(),'module':'scripts.learning_failure_fixture','state':'running'})+'\n')
    with threadpool_limits(limits=1):
        uvicorn.run(app,host='127.0.0.1',port=8786,ws='none',access_log=False)
