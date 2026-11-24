"""Reading app retained; add explicit requirement handoff without sharing visitor state."""
from pathlib import Path
from scripts.run_research75_workbench import create_app as retained_app
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
    def page():return FileResponse(ROOT/'research76/web/index.html',headers={'Cache-Control':'no-cache'})
    @app.get('/main-experience76.mjs')
    def main_script():return FileResponse(ROOT/'research76/web/main-experience.mjs',media_type='text/javascript')
    @app.get('/handoff-entry.mjs')
    def handoff_script():return FileResponse(ROOT/'research76/web/handoff-entry.mjs',media_type='text/javascript')
    @app.get('/workspace76.css')
    def style():return FileResponse(ROOT/'research76/workspace.css',media_type='text/css')
    @app.get('/trial.html')
    def trial():return FileResponse(ROOT/'research76/web/trial.html',headers={'Cache-Control':'no-cache'})
    @app.get('/trial76.js')
    def trial_script():return FileResponse(ROOT/'research76/web/trial.js',media_type='text/javascript')
    @app.get('/trial76.css')
    def trial_style():return FileResponse(ROOT/'research76/web/trial.css',media_type='text/css')
    @app.get('/trial/vendor/jsoneditor.js')
    def trial_editor():return FileResponse(ROOT/'web/papertrail-v26/dist/vendor/jsoneditor.js',media_type='text/javascript')
    app.router.routes.extend(mounts);return app
if __name__=='__main__':
    from trialsite.app import main
    main(factory=create_app)
