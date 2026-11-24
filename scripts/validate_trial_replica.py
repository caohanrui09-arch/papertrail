"""Extract allowlisted archive and run it without the original application directory."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import uuid
import zipfile

import psutil
import requests

ROOT=Path(__file__).resolve().parents[1]
package=json.loads((ROOT/'reports/stage39/package.json').read_text(encoding='utf-8'))
archive=ROOT/package['zip']
if hashlib.sha256(archive.read_bytes()).hexdigest()!=package['zip_sha256']: raise ValueError('Archive changed')
dest=ROOT/'.cache/stage39/replica'/str(uuid.uuid4())
dest.mkdir(parents=True)
with zipfile.ZipFile(archive) as source:
    if set(source.namelist())!=set(package['files']): raise ValueError('Archive allowlist mismatch')
    for member in source.namelist():
        if not (dest/member).resolve().is_relative_to(dest.resolve()): raise ValueError('Unsafe archive path')
    source.extractall(dest)
for name,expected in package['files'].items():
    if hashlib.sha256((dest/name).read_bytes()).hexdigest()!=expected: raise ValueError('Extracted file mismatch')
python=ROOT/'.cache/stage39/runtime-secure/Scripts/python.exe'
env=os.environ.copy()
for key in ['PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','CONDA_PREFIX']: env.pop(key,None)
env.update(PAPERTRAIL_LOCAL_PREVIEW='1',PAPERTRAIL_ORIGIN='http://127.0.0.1:8784',PORT='8784',
           PAPERTRAIL_DATA_DIR=str(dest/'visitor-data'),PAPERTRAIL_INSTANCE='replica-'+dest.name,
           OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
probe=subprocess.run([str(python),'-E','-s','-c',
    "import sys,json; import trialsite.app; print(json.dumps({'file':trialsite.app.__file__,'no_gsearch_import':not any(m.startswith('gsearch') for m in sys.modules),'python':sys.version,'system_site_packages':False}))"],
    cwd=dest,env=env,capture_output=True,text=True,check=True)
imported=json.loads(probe.stdout)
if not Path(imported['file']).resolve().is_relative_to(dest.resolve()) or not imported['no_gsearch_import']:
    raise ValueError('Replica depends on original application')
with socket.socket() as sock: sock.bind(('127.0.0.1',8784))
with (dest/'out.log').open('w') as out,(dest/'err.log').open('w') as err:
    process=subprocess.Popen([str(python),'-E','-s','-m','trialsite.app'],cwd=dest,env=env,
            stdout=out,stderr=err,stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
client=requests.Session();client.trust_env=False
checks=[]
try:
    for _ in range(100):
        if process.poll() is not None:raise RuntimeError('Replica exited; inspect '+str(dest/'err.log'))
        try:
            response=client.get('http://127.0.0.1:8784/api/health',timeout=1)
            if response.status_code==200:break
        except requests.RequestException:pass
        time.sleep(.1)
    else:raise RuntimeError('Replica not ready')
    if response.json()['catalog']!=162:raise ValueError('Wrong catalog')
    checks.append('isolated_health_162')
    for path in ['/','/legal.html','/open-source.txt','/api/meta','/api/paper-previews']:
        if client.get('http://127.0.0.1:8784'+path,timeout=10).status_code!=200:raise ValueError(path)
        checks.append('replica_asset_'+path)
    result=client.get('http://127.0.0.1:8784/api/search',params={'topic':'generative','q':'generative retrieval'},timeout=10).json()
    if not result['papers']:raise ValueError('No search candidates')
    paper=client.get('http://127.0.0.1:8784/api/paper/'+result['papers'][0]['doc_id'],timeout=10).json()['paper']
    if not paper['source_verified'] or not paper['abstract']:raise ValueError('Reader failed')
    checks.append('standalone_search_original_read')
    p=client.get('http://127.0.0.1:8784/api/profile',timeout=10).json()
    if p['items'] or p['revision']!=0:raise ValueError('Private preferences were shipped')
    checks.append('fresh_profile_no_shipped_preferences')
finally:
    parent=psutil.Process(process.pid)
    if 'trialsite.app' not in parent.cmdline():raise ValueError('Unowned fixture')
    for child in parent.children(recursive=True):
        try:
            if 'trialsite.app' in child.cmdline() and Path(child.exe()).resolve().is_relative_to(ROOT/'.cache/stage39'):
                child.terminate();child.wait(timeout=10)
        except psutil.NoSuchProcess:pass
    if process.poll() is None:process.terminate()
    process.wait(timeout=10)
result={'status':'passed','checks':checks,'allowlisted_files_verified':len(package['files']),
        'archive_sha256':package['zip_sha256'],'no_original_app_import':True,'replica':str(dest.relative_to(ROOT)),
        'python':imported['python'],'fixture_stopped':True,'scope':'same Windows computer, separate extracted application directory and isolated runtime; not second machine or Linux host'}
(ROOT/'reports/stage39/replica-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print({k:v for k,v in result.items() if k!='checks'})
