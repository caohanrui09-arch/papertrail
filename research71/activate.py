"""Switch only the owned lab after confirming no active model job."""
from pathlib import Path
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open('http://127.0.0.1:8802/lab/activity',timeout=5) as response:
            activity=json.load(response)
        if any(j['status']=='running' for j in activity['jobs']):
            raise RuntimeError('Active job: wait rather than switching lab')
    except urllib.error.URLError:
        pass
    for module,action in [('research70.control','stop'),('research71.control','start')]:
        subprocess.run([sys.executable,'-E','-s','-m',module,action],cwd=ROOT,check=True,timeout=30)


if __name__=='__main__':main()
