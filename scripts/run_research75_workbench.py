"""Site-wide color presentation, original reading app and API retained verbatim."""
from pathlib import Path
from scripts.run_research73_workbench import create_app as retained_app

ROOT=Path(__file__).resolve().parents[1]


def create_app(settings=None):
    from fastapi.responses import FileResponse
    app=retained_app(settings)
    mounts=[r for r in app.router.routes if getattr(r,'path',None) in ('','/') and hasattr(r,'app')]
    for route in mounts:app.router.routes.remove(route)
    for route in list(app.router.routes):
        if getattr(route,'path',None)=='/evidence.html':app.router.routes.remove(route)

    def page(name):
        def endpoint():return FileResponse(ROOT/'research75/web'/name,headers={'Cache-Control':'no-cache'})
        return endpoint

    for name in ('index.html','online.html','evidence.html','minionerec.html','sid-lab.html','legal.html'):
        app.add_api_route('/'+name,page(name),methods=['GET'],include_in_schema=False)
    app.add_api_route('/',page('index.html'),methods=['GET'],include_in_schema=False)
    @app.get('/graphic-colors.css',include_in_schema=False)
    def colors():return FileResponse(ROOT/'research75/graphic-colors.css',media_type='text/css',headers={'Cache-Control':'no-cache'})
    app.router.routes.extend(mounts)
    return app


if __name__=='__main__':
    from trialsite.app import main
    main(factory=create_app)
