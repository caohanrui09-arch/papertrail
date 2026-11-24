"""Activate the sequential delivery only when no real Agent task is running."""
from pathlib import Path
import json,os,subprocess,sys,urllib.request
ROOT=Path(__file__).resolve().parents[1]
def main():
    os.chdir(ROOT);op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open('http://127.0.0.1:8802/lab/activity',timeout=8) as r:assert not any(j['status']=='running' for j in json.load(r)['jobs'])
    for module,action in [('research75.control','stop'),('research76.control','start')]:subprocess.run([sys.executable,'-E','-s','-m',module,action],check=True,timeout=30)
if __name__=='__main__':main()
