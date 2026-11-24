"""New static UI over the unchanged sealed v30 API."""
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from gsearch.search_v2_workbench import create_app as base_app


def create_app():
 app=base_app()
 app.router.routes[:]=[r for r in app.router.routes if getattr(r,'name',None)!='search-v2']
 app.mount('/',StaticFiles(directory=Path('web/papertrail-v32/dist').resolve(),html=True),name='search-v2-polished')
 return app


if __name__=='__main__':
 import uvicorn
 from threadpoolctl import threadpool_limits
 with threadpool_limits(limits=1):uvicorn.run(create_app(),host='127.0.0.1',port=8771,access_log=False,ws='none')
