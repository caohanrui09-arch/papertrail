"""Relocatable public reading app. Research Agent assets remain explicitly absent."""
import argparse
from pathlib import Path
import os
import re
import sys

ROOT=Path(__file__).resolve().parents[2]
if (ROOT/'runtime/deps').is_dir():sys.path.insert(0,str(ROOT/'runtime/deps'))
sys.path.insert(0,str(ROOT))

def create_app(port=8791):
    os.environ.update(PAPERTRAIL_LOCAL_PREVIEW='1',PAPERTRAIL_ORIGIN=f'http://127.0.0.1:{port}',
        PAPERTRAIL_DATA_DIR=str(ROOT/'visitor-data'),PORT=str(port),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
    from scripts.run_research77_workbench import create_app as retained_app
    from trialsite.security import Settings
    from fastapi.responses import HTMLResponse,Response
    app=retained_app(Settings(f'http://127.0.0.1:{port}',ROOT/'visitor-data',production=False))
    mounts=[r for r in app.router.routes if getattr(r,'path',None) in ('','/') and hasattr(r,'app')]
    for route in mounts:app.router.routes.remove(route)
    for route in list(app.router.routes):
        if getattr(route,'path',None) in ('/main-experience77.mjs','/handoff-entry.mjs','/evidence.html'):app.router.routes.remove(route)
    def agent_links(s):return re.sub(r'http://127\.0\.0\.1:8802/[^\s\"\'<>`]*','/handoff-status.html',s)
    @app.get('/main-experience77.mjs')
    def main_script():
        s=(ROOT/'research77/web/main-experience.mjs').read_text(encoding='utf8')
        return Response(agent_links(s).replace('算法与 Agent 实验台','Agent 接入说明'),media_type='text/javascript')
    @app.get('/handoff-entry.mjs')
    def handoff_script():
        s=(ROOT/'research76/web/handoff-entry.mjs').read_text(encoding='utf8')
        return Response(s.replace('http://127.0.0.1:8802/','/handoff-status.html').replace('交给 Agent ↗','Agent 接入说明 ↗'),media_type='text/javascript')
    @app.get('/task-preview.mjs')
    def preview_script():
        s=(ROOT/'deploy/stage66/web/task-preview.mjs').read_text(encoding='utf8')
        return Response(agent_links(s).replace('打开实验台，查看与执行','查看 Agent 接入说明').replace('前往算法与 Agent 实验台','查看 Agent 接入说明'),media_type='text/javascript')
    @app.get('/evidence.html')
    def evidence_page():return HTMLResponse(agent_links((ROOT/'research75/web/evidence.html').read_text(encoding='utf8')))
    @app.get('/handoff-status.css')
    def agent_scope_style():return Response('body{margin:10vh auto;max-width:720px;padding:28px;font:18px/1.9 sans-serif;color:#242424;background:#f7f7f7}a{color:#315eb3}h1{font-size:36px}p{margin:24px 0}',media_type='text/css')
    @app.get('/handoff-status.html')
    def agent_scope():
        return HTMLResponse('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Agent资产接入 · Papertrail</title><link rel="stylesheet" href="/handoff-status.css"><h1>阅读网站已就绪。</h1><p>这是Windows交接演示包。真实Agent与万篇冻结实验需要单独恢复原许可数据、训练画像、运行环境和Qwen权重；当前没有执行模型或产生新答案。</p><p>完整代码在源码包的research77/server.py。请从交接资料的FULL_AGENT_ASSETS.md和NEXT_AGENT_PROMPT.md继续。</p><p><a href="/">返回论文网站 →</a></p></html>''')
    app.router.routes.extend(mounts)
    return app

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8791);p.add_argument('--check',action='store_true');args=p.parse_args()
    if args.check:
        from fastapi.testclient import TestClient
        with TestClient(create_app(args.port)) as c:
            h=c.get('/api/health').json();assert h['catalog']==167 and h['llm_enabled'] is False
            assert c.get('/handoff-status.html').status_code==200
            print(h)
        return
    import uvicorn
    print(f'Papertrail reading preview: http://127.0.0.1:{args.port}/ ; stop with Ctrl+C',flush=True)
    uvicorn.run(create_app(args.port),host='127.0.0.1',port=args.port,workers=1,proxy_headers=False,
                limit_concurrency=32,backlog=64,timeout_keep_alive=5,access_log=False,ws='none',server_header=False)

if __name__=='__main__':main()
