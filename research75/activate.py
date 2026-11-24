"""Switch only the two owned idle services to the new color presentation."""
from pathlib import Path
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with op.open('http://127.0.0.1:8802/lab/activity',timeout=5) as response:activity=json.load(response)
        assert not any(j['status']=='running' for j in activity['jobs']),'Do not stop an active model task'
    except urllib.error.URLError:pass
    for module,action in [('research74.control','stop'),('scripts.research73_workbench_control','stop'),('research75.control','start'),('scripts.research75_workbench_control','start')]:
        extra=['--no-open'] if module=='scripts.research75_workbench_control' and action=='start' else []
        subprocess.run([sys.executable,'-E','-s','-m',module,action,*extra],cwd=ROOT,check=True,timeout=45)


if __name__=='__main__':main()
