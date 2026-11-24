"""Versioned annotation extension of the sealed personal workbench."""
from pathlib import Path
import argparse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .personal_workbench import create_app as personal_app
from .annotation_store import BlindPool,AnnotationStore,annotation_router,ROOT

STATIC=Path('web/papertrail-v26/dist').resolve()


def create_app():
    app=personal_app()
    app.router.routes[:]=[r for r in app.router.routes if getattr(r,'name',None)!='workbench']
    pool=BlindPool();store=AnnotationStore(ROOT/'work/annotations.sqlite3',pool)
    app.include_router(annotation_router(pool,store))

    @app.get('/label')
    def label():return FileResponse(STATIC/'label.html')

    @app.middleware('http')
    async def editor_styles(request,call_next):
        response=await call_next(request)
        if request.url.path=='/label':
            # Native editor uses element.style and generated theme styles.
            # Scripts remain local-only, with no unsafe-eval or remote resources.
            response.headers['Content-Security-Policy']=response.headers['Content-Security-Policy'].replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")
        return response

    app.mount('/',StaticFiles(directory=STATIC,html=True),name='annotation-workbench')
    return app


def main():
    import uvicorn
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8769);args=parser.parse_args()
    if not 1024<=args.port<=65535:raise ValueError('Unprivileged local port required')
    uvicorn.run(create_app(),host='127.0.0.1',port=args.port,access_log=False,ws='none',workers=1)


if __name__=='__main__':main()
