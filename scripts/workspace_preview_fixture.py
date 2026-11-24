"""Local acceptance fixture only: first preview request fails, retry uses real metadata."""
from fastapi.responses import JSONResponse
from gsearch.paper_workspace import create_app


def main():
    import uvicorn
    app=create_app()
    route=next(r for r in app.routes if getattr(r,'path',None)=='/api/paper-previews')
    endpoint=route.endpoint
    app.router.routes.remove(route)
    attempts={'count':0}
    @app.get('/api/paper-previews')
    def preview_fixture():
        attempts['count']+=1
        if attempts['count']==1:
            return JSONResponse({'detail':'acceptance preview failure'},status_code=503)
        return endpoint()
    app.router.routes.insert(0,app.router.routes.pop())  # Before the catch-all static mount.
    uvicorn.run(app,host='127.0.0.1',port=8781,access_log=False,ws='none')


if __name__=='__main__':main()
