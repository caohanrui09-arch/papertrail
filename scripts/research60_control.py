"""Owned local UI process; reuse the original paper backend without changing it."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request
from uuid import uuid4
from scripts.manage_stage17_env import environment
BASE=Path('.cache/stage39').resolve()
VENV=BASE/'runtime-secure'

ROOT=Path('.cache/stage60').resolve()
STATE=ROOT/'service.json'
URL='http://127.0.0.1:8791'
MODULE='scripts.run_research60_local'


def health() -> tuple[int,dict]:
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(URL+'/api/health',timeout=5) as response:return response.status,json.load(response)
    except urllib.error.HTTPError as error:return error.code,json.load(error)


def owned(state: dict):
    import psutil
    process=psutil.Process(state['pid'])
    if abs(process.create_time()-state['created'])>.01 or MODULE not in process.cmdline() or not Path(process.exe()).resolve().is_relative_to(BASE):
        raise ValueError('Process ownership mismatch; refusing to control it')
    return process


def start() -> dict:
    import psutil
    ROOT.mkdir(parents=True,exist_ok=True)
    if STATE.exists():
        state=json.loads(STATE.read_text())
        if state['state']!='stopped':
            try:owned(state)
            except psutil.NoSuchProcess:
                state['state']='stopped';STATE.write_text(json.dumps(state,indent=2)+'\n')
            else:
                code,value=health()
                if code==200 and value.get('instance_id')==state['instance_id']:
                    return {'state':'already_running','url':URL,**value}
                raise ValueError('Existing workbench instance needs inspection; do not start a duplicate')
    with socket.socket() as probe:probe.bind(('127.0.0.1',8791))
    ident=str(uuid4());logs=ROOT/'logs';logs.mkdir(exist_ok=True)
    env=environment();env['PAPERTRAIL_INSTANCE']=ident
    with (logs/(ident+'.out.log')).open('w',encoding='utf-8') as out,(logs/(ident+'.err.log')).open('w',encoding='utf-8') as err:
        process=subprocess.Popen([str(VENV/'Scripts/python.exe'),'-E','-s','-u','-m',MODULE],cwd=Path.cwd(),
            env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    for _ in range(45):
        if process.poll() is not None:raise RuntimeError('Workbench exited; inspect private .cache/stage60/logs')
        try:
            code,value=health()
            if code==200 and value.get('instance_id')==ident:
                import psutil
                state={'state':'running','instance_id':ident,'pid':process.pid,'created':psutil.Process(process.pid).create_time()}
                STATE.write_text(json.dumps(state,indent=2)+'\n')
                return {'state':'started','url':URL,**value}
        except (urllib.error.URLError,TimeoutError,OSError):pass
        time.sleep(.5)
    raise RuntimeError('Workbench startup timeout; inspect owned process log')


def stop() -> dict:
    import psutil
    if not STATE.exists():return {'state':'not_started'}
    state=json.loads(STATE.read_text())
    if state['state']=='stopped':return state
    try:
        process=owned(state)
        for child in process.children(recursive=True):
            if MODULE in child.cmdline() and (Path(child.exe()).resolve().is_relative_to(BASE) or Path(child.exe()).resolve().is_relative_to(Path('.cache/stage17/python').resolve())):
                child.terminate();child.wait(timeout=10)
        process.terminate();process.wait(timeout=10)
    except psutil.NoSuchProcess:pass
    state['state']='stopped';STATE.write_text(json.dumps(state,indent=2)+'\n')
    return {'state':'stopped','previous_versions_preserved':True}


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('start','stop','status'),nargs='?',default='start')
    parser.add_argument('--no-open',action='store_true');args=parser.parse_args()
    if args.action=='start':result=start()
    elif args.action=='stop':result=stop()
    elif not STATE.exists():result={'state':'not_started'}
    else:
        state=json.loads(STATE.read_text())
        if state['state']=='stopped':result=state
        else:
            import psutil
            try:owned(state)
            except psutil.NoSuchProcess:result={'state':'process_exited','url':URL,'restart':'papertrail-workbench.cmd start'}
            else:
                code,value=health()
                result={'state':'running' if code==200 else 'backend_unavailable','url':URL,**value}
    print(json.dumps(result,ensure_ascii=False),flush=True)
    if args.action=='start' and not args.no_open:
        import webbrowser
        webbrowser.open(URL)


if __name__=='__main__':main()
