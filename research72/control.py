"""Manage only this lab's verified loopback process, with retained private logs."""
import argparse,json,os,subprocess,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.cache/stage72-lab';BASE.mkdir(exist_ok=True)

def request(path,body=None):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req=urllib.request.Request('http://127.0.0.1:8802'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
    with opener.open(req,timeout=30) as response:return json.load(response)

def main():
    import psutil
    p=argparse.ArgumentParser();p.add_argument('action',choices=['start','stop','status','compare','job','algorithms']);a=p.parse_args()
    owned=[]
    for proc in psutil.process_iter(['cmdline','exe']):
        try:
            if 'research72.server' in (proc.info['cmdline'] or []) and Path(proc.info['exe']).resolve().is_relative_to(ROOT/'.cache/stage17') and Path(proc.cwd()).resolve() in (ROOT,ROOT/'.cache/stage17/replica'):owned.append(proc)
        except (psutil.NoSuchProcess,psutil.AccessDenied):continue
    if a.action=='stop':
        for proc in reversed(owned):
            try:proc.terminate();proc.wait(timeout=10)
            except psutil.NoSuchProcess:pass
        print({'stopped_owned_processes':len(owned)});return
    if a.action=='start':
        if owned:print(request('/health'));return
        from scripts.manage_stage17_env import environment
        with (BASE/'server.log').open('a',encoding='utf8') as log:
            proc=subprocess.Popen([str(ROOT/'.cache/stage17/runtime/Scripts/python.exe'),'-E','-s','-u','-m','research72.server'],cwd=ROOT,env=environment(),stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        print({'started':True,'pid':proc.pid,'url':'http://127.0.0.1:8802','loading':'verify frozen assets and fit model; check status shortly'});return
    if a.action=='status':print(request('/health'))
    elif a.action=='compare':
        value=request('/lab/run',{'compare':True});(BASE/'job.json').write_text(json.dumps(value));print(value)
    elif a.action=='job':
        job=json.loads((BASE/'job.json').read_text());value=request('/lab/jobs/'+job['id']);(BASE/'job-status.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');print({'status':value['status'],'completed_outputs':len((value.get('result') or {}).get('results',[])),'exit_code':value['exit_code']})
    elif a.action=='algorithms':
        value=request('/lab/algorithms',{'task_id':'evaluation-002'});(BASE/'algorithm-example.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');print({'methods':list(value['methods']),'top10_each':all(len(p)==10 for p in value['methods'].values())})

if __name__=='__main__':main()
