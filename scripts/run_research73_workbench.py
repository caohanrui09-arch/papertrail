"""Retain the whole v66 reading app; overlay only the evidence-page evaluation link."""
from pathlib import Path
import os
import sys

ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT);sys.path.insert(0,str(ROOT/'deploy/stage66'))
os.environ['PAPERTRAIL_LOCAL_PREVIEW']='1'
os.environ.setdefault('PAPERTRAIL_DATA_DIR',str(ROOT/'data/stage39-visitors'))
os.environ.setdefault('PAPERTRAIL_ORIGIN','http://127.0.0.1:8791');os.environ.setdefault('PORT','8791')


def create_app(settings=None):
    from trialsite.delivery import create_app as original_app
    from fastapi.responses import FileResponse
    app=original_app(settings)
    mounts=[r for r in app.router.routes if getattr(r,'path',None) in ('','/') and hasattr(r,'app')]
    for route in mounts:app.router.routes.remove(route)
    @app.get('/evidence.html')
    def evidence_page():return FileResponse(ROOT/'research73/workbench-evidence.html')
    @app.get('/evaluation-link.css')
    def evidence_link_style():return FileResponse(ROOT/'research73/evaluation-link.css',media_type='text/css')
    app.router.routes.extend(mounts)
    return app


if __name__=='__main__':
    from trialsite.app import main
    main(factory=create_app)
