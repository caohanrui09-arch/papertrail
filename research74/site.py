"""Read-only evaluation evidence plus retained annotation routes in a new namespace."""
import re
import secrets
from pathlib import Path

from fastapi import HTTPException,Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from gsearch.annotation_store import annotation_router
from research73.annotations import EvaluationPool,EvaluationStore
from research73.common import DATA,read,digest
from research73.metrics import algorithm_report
from research73.agent_report import report,public_row


def register_evaluation(app,root: Path):
    pool=EvaluationPool();store=EvaluationStore(DATA/'work/annotations.sqlite3',pool)
    app.state.evaluation_store=store
    @app.middleware('http')
    async def annotation_space(request:Request,call_next):
        cookie=request.cookies.get('papertrail_eval73','');valid=bool(re.fullmatch('[a-f0-9]{48}',cookie))
        owner=cookie if valid else secrets.token_hex(24);request.state.owner=owner
        response=await call_next(request)
        if not valid and response.status_code<400:response.set_cookie('papertrail_eval73',owner,httponly=True,samesite='strict',max_age=31536000)
        if request.url.path=='/api/annotation/export':response.headers['Content-Disposition']=response.headers.get('Content-Disposition','').replace('papertrail-tuning','papertrail-stage73')
        return response
    app.include_router(annotation_router(pool,store))
    app.mount('/vendor',StaticFiles(directory=root/'web/papertrail-v26/dist/vendor'),name='evaluation-retained-vendor')
    @app.get('/label')
    def label():return FileResponse(root/'research73/label/label.html')
    @app.get('/label.mjs')
    def label_script():return FileResponse(root/'research73/label/label.mjs',media_type='text/javascript')
    @app.get('/label.css')
    def label_styles():return FileResponse(root/'research73/label/label.css',media_type='text/css')
    @app.get('/label-theme.css')
    def label_theme():return FileResponse(root/'research73/label-theme.css',media_type='text/css')
    @app.get('/evaluation.html')
    def evaluation_page():return FileResponse(root/'research74/evaluation.html')
    @app.get('/evaluation.js')
    def evaluation_script():return FileResponse(root/'research74/evaluation.js',media_type='text/javascript')
    @app.get('/evaluation.css')
    def evaluation_styles():return FileResponse(root/'research73/evaluation.css',media_type='text/css')
    def owner(request):return ('verification:' if request.headers.get('x-papertrail-verification')=='1' else '')+request.state.owner
    @app.get('/api/evaluation/summary')
    def summary(request:Request):
        costs=read(DATA/'algorithm-costs.json')
        return {'stage':73,'protocol_sha256':digest(DATA/'protocol.json'),'algorithm':algorithm_report(store,owner(request)),
                'materials':read(root/'reports/stage73/preparation.json'),'agent':report(),'algorithm_costs':costs,
                'boundaries':['本轮复用草案和受控任务，不是独立自然需求测试。','协议完成、原文一致与语义正确性分开。','无人标注时不产生排序质量分数。']}
    @app.get('/visuals/v74/evaluation/tasks')
    def visual_task_contexts():
        tasks=read(DATA/'inputs/agent-tasks.json')
        return {'version':74,'evaluation_stage':73,'tasks':[{k:t.get(k) for k in ('id','intent','original_need','query','at')} for t in tasks],
                'scope':'read-only task context for the frozen stage73 result display; no new evaluation'}
    @app.get('/api/evaluation/protocol')
    def protocol():return {'sha256':digest(DATA/'protocol.json'),'protocol':read(DATA/'protocol.json')}
    @app.get('/api/evaluation/agent/{cell}')
    def agent_cell(cell:str):
        allowed={c['cell'] for c in read(DATA/'inputs/run-order.json')}
        if cell not in allowed:raise HTTPException(404,'Unknown evaluation cell')
        path=DATA/'agent-runs'/cell/'result.json'
        if not path.exists():return {'status':'pending','cell':cell}
        from research70.event_stream import available
        events,_=available(path.parent/'events.jsonl')
        return {'status':'complete','cell':cell,'source_sha256':digest(path),'result':public_row(read(path)),'events':events,
                'scope':'Native trace, proposals and source fields. No model private messages or unverified final prose.'}
