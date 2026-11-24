"""Switch only the two owned local services after a presentation-only change."""
from pathlib import Path
import json,subprocess,sys,time,urllib.request
ROOT=Path(__file__).resolve().parents[1]

def main():
    import os,psutil
    os.chdir(ROOT)
    for p in psutil.process_iter(['cmdline']):
        if 'research63.worker' in (p.info['cmdline'] or []) and p.is_running():
            raise RuntimeError('A real model worker is active; wait before switching the lab')
    from scripts.snapshot_research61_preferences import snapshot
    before=snapshot()
    cpu=ROOT/'.cache/stage17/runtime/Scripts/python.exe'
    for module,action in [('scripts.research61_control','stop'),('scripts.research66_control','start'),('research63.control','stop'),('research66.control','start')]:
        args=[str(cpu),'-E','-s','-u','-m',module,action]
        if module.startswith('scripts.'):args.append('--no-open')
        subprocess.run(args,cwd=ROOT,check=True,timeout=90)
    for filename,old,new in [('papertrail-workbench.cmd','scripts.research61_control','scripts.research66_control'),('project-agent.cmd','research63.control','research66.control')]:
        p=ROOT/filename;p.write_text(p.read_text().replace(old,new),encoding='utf8')
    assert before==snapshot(),'Concurrent private data change: inspect rather than overwrite'
    (ROOT/'reports/stage66/preference-preservation.json').write_text(json.dumps({'status':'passed','before':before,'after':before,'all_existing_namespaces_unchanged':True},indent=2),encoding='utf8')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for port,path in [(8791,'/api/health'),(8802,'/health')]:
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            try:
                with opener.open(f'http://127.0.0.1:{port}{path}',timeout=3) as r:
                    value=json.load(r)
                    if value.get('status')=='ready':break
            except (OSError,ValueError):pass
            time.sleep(1)
        else:raise RuntimeError(f'{port} not ready; inspect owned service logs')
        print(json.dumps({'ready':port,'status':value}),flush=True)

if __name__=='__main__':main()
