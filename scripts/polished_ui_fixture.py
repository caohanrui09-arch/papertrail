"""Isolated localhost fault/delay fixture for UI acceptance; never mounted on8771."""
import asyncio
from fastapi.responses import JSONResponse
from gsearch.search_v2_polished import create_app


def main():
 import uvicorn
 from threadpoolctl import threadpool_limits
 with threadpool_limits(limits=1):
  app=create_app();state={'mode':'normal'}
  @app.middleware('http')
  async def fixture(request,call_next):
   if request.url.path.startswith('/_probe/'):
    mode=request.url.path.rsplit('/',1)[-1]
    if mode not in ('normal','search_fail','read_fail','search_wait','read_wait'):return JSONResponse({'error':'unknown probe'},status_code=400)
    state['mode']=mode;return JSONResponse({'verification_only':True,'mode':mode})
   mode=state['mode']
   if request.url.path=='/api/search':
    if mode=='search_fail':return JSONResponse({'detail':'verification search failure'},status_code=503)
    if mode=='search_wait':await asyncio.sleep(3)
   if request.url.path.startswith('/api/paper/'):
    if mode=='read_fail':return JSONResponse({'detail':'verification read failure'},status_code=503)
    if mode=='read_wait' and request.url.path.endswith('2206.02743'):await asyncio.sleep(3)
   return await call_next(request)
  uvicorn.run(app,host='127.0.0.1',port=8772,access_log=False,ws='none')


if __name__=='__main__':main()
