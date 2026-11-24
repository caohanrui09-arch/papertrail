"""Isolated local acceptance fixture; not exposed by the delivery app."""
import asyncio
from fastapi.responses import JSONResponse
from gsearch.search_v2_reading import create_app


def main() -> None:
    import uvicorn
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        app = create_app()
        state = {'mode': 'normal'}

        @app.middleware('http')
        async def fixture(request, call_next):
            if request.url.path.startswith('/_probe/'):
                mode = request.url.path.rsplit('/', 1)[-1]
                if mode not in ('normal', 'read_fail', 'read_wait'):
                    return JSONResponse({'error': 'invalid fixture mode'}, status_code=400)
                state['mode'] = mode
                return JSONResponse({'verification_only': True, 'mode': mode})
            if request.url.path.startswith('/api/paper/'):
                if state['mode'] == 'read_fail':
                    return JSONResponse({'detail': 'verification read failure'}, status_code=503)
                if state['mode'] == 'read_wait' and request.url.path.endswith('2206.02743'):
                    await asyncio.sleep(3)
            return await call_next(request)

        uvicorn.run(app, host='127.0.0.1', port=8776, access_log=False, ws='none')


if __name__ == '__main__':
    main()
