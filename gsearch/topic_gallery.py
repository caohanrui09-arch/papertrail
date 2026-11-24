"""Visual-only v37 frontend over unchanged v36 search, preference and backup APIs."""
from fastapi.staticfiles import StaticFiles
from .preference_backup import create_app as backup_app


def create_app():
    app = backup_app()
    app.router.routes[:] = [route for route in app.router.routes if getattr(route, 'name', None) != 'personal-backup']
    app.mount('/', StaticFiles(directory='web/papertrail-v37/dist', html=True), name='topic-gallery')
    return app


if __name__ == '__main__':
    import uvicorn
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        uvicorn.run(create_app(), host='127.0.0.1', port=8779, access_log=False, ws='none')
