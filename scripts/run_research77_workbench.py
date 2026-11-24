"""First-view presentation only, all native reading/handoff/trial APIs retained."""
from pathlib import Path
from scripts.run_research76_workbench import create_app as retained_app
ROOT=Path(__file__).resolve().parents[1]
def create_app(settings=None):
    from fastapi.responses import FileResponse
    app=retained_app(settings)
    mounts=[r for r in app.router.routes if getattr(r,'path',None) in ('','/') and hasattr(r,'app')]
    for route in mounts:app.router.routes.remove(route)
    for route in list(app.router.routes):
        if getattr(route,'path',None) in ('/','/index.html'):app.router.routes.remove(route)
    @app.get('/')
    @app.get('/index.html')
    def page():return FileResponse(ROOT/'research77/web/index.html',headers={'Cache-Control':'no-cache'})
    @app.get('/main-experience77.mjs')
    def script():return FileResponse(ROOT/'research77/web/main-experience.mjs',media_type='text/javascript')
    @app.get('/first-view77.css')
    def style():return FileResponse(ROOT/'research77/first-view.css',media_type='text/css')
    app.router.routes.extend(mounts);return app
if __name__=='__main__':
    from trialsite.app import main
    main(factory=create_app)
