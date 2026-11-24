"""Readable continuous-reading UI over the unchanged sealed search API."""
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from gsearch.search_v2_workbench import create_app as base_app


def create_app():
    app = base_app()
    app.router.routes[:] = [route for route in app.router.routes if getattr(route, 'name', None) != 'search-v2']
    app.mount('/', StaticFiles(directory=Path('web/papertrail-v34/dist').resolve(), html=True), name='search-v2-reading')
    return app


if __name__ == '__main__':
    import uvicorn
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        uvicorn.run(create_app(), host='127.0.0.1', port=8775, access_log=False, ws='none')
