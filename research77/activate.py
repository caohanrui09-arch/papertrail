"""Switch the owned presentation services only when the real Agent is idle."""
from pathlib import Path
import json,os,subprocess,sys,urllib.request
ROOT=Path(__file__).resolve().parents[1]
def main():
    os.chdir(ROOT);op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open('http://127.0.0.1:8802/lab/activity',timeout=8) as r:assert not any(j['status']=='running' for j in json.load(r)['jobs'])
    for module,action,extra in [('research76.control','stop',[]),('scripts.research76_workbench_control','stop',[]),('research77.control','start',[]),('scripts.research77_workbench_control','start',['--no-open'])]:subprocess.run([sys.executable,'-E','-s','-m',module,action,*extra],check=True,timeout=45)
if __name__=='__main__':main()
