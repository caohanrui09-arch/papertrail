"""Disposable real HTTP fixture: separate browser jars, concurrent requests, real restart."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import uuid

import psutil
import requests

ROOT=Path(__file__).resolve().parents[1]
URL='http://127.0.0.1:8783'
MODULE='scripts.run_trial_local'
CHECKS=[]
SAMPLES=[]


def check(name, passed):
    if not passed: raise AssertionError(name)
    CHECKS.append(name)


def session():
    client=requests.Session();client.trust_env=False
    return client


def main():
    with socket.socket() as probe: probe.bind(('127.0.0.1',8783))
    run=ROOT/'.cache/stage39/http-validation'/str(uuid.uuid4())
    run.mkdir(parents=True)
    env=os.environ.copy()
    for key in ['PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','CONDA_PREFIX']: env.pop(key,None)
    env.update(PAPERTRAIL_LOCAL_PREVIEW='1',PAPERTRAIL_ORIGIN=URL,PORT='8783',PAPERTRAIL_DATA_DIR=str(run/'visitors'),
               OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',PAPERTRAIL_INSTANCE='validation-'+run.name)
    done=threading.Event()
    process=None
    def sample():
        while not done.wait(.05):
            if process is not None:
                try:
                    for child in [psutil.Process(process.pid)]+psutil.Process(process.pid).children(recursive=True):
                        if MODULE in child.cmdline():
                            info=child.memory_info()
                            SAMPLES.append({'rss':info.rss,'peak_wset':getattr(info,'peak_wset',info.rss)})
                except (psutil.NoSuchProcess,psutil.AccessDenied): pass
    sampler=threading.Thread(target=sample,daemon=True);sampler.start()
    def start():
        nonlocal process
        with (run/'out.log').open('a',encoding='utf-8') as out,(run/'err.log').open('a',encoding='utf-8') as err:
            process=subprocess.Popen([str(ROOT/'.cache/stage39/runtime-secure/Scripts/python.exe'),'-E','-s','-u','-m',MODULE],cwd=ROOT,
                env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
        before=time.perf_counter()
        client=session()
        for _ in range(100):
            if process.poll() is not None: raise RuntimeError('Fixture exited: '+str(run/'err.log'))
            try:
                response=client.get(URL+'/api/health',timeout=1)
                if response.status_code==200 and response.json()['instance_id']==env['PAPERTRAIL_INSTANCE']:
                    return time.perf_counter()-before
            except requests.RequestException: pass
            time.sleep(.1)
        raise RuntimeError('Fixture startup timeout')
    def stop():
        nonlocal process
        if process is None:return
        parent=psutil.Process(process.pid)
        if MODULE not in parent.cmdline(): raise ValueError('Not owned fixture')
        for child in parent.children(recursive=True):
            try:
                if MODULE in child.cmdline() and Path(child.exe()).resolve().is_relative_to(ROOT/'.cache'):
                    child.terminate();child.wait(timeout=10)
            except psutil.NoSuchProcess:pass
        if process.poll() is None:process.terminate()
        process.wait(timeout=10);process=None
    timings=[]
    try:
        first_start=start()
        clients=[session() for _ in range(12)]
        with ThreadPoolExecutor(max_workers=6) as pool:
            profiles=list(pool.map(lambda c:c.get(URL+'/api/profile',timeout=10).json(),clients))
        check('12_independent_spaces',len({c.cookies.get('papertrail_trial_local') for c in clients})==12 and all(not p['items'] for p in profiles))
        previews=clients[0].get(URL+'/api/paper-previews',timeout=10).json()
        ids=list(previews['papers'])[:12]
        def save(pair):
            i,client=pair
            body={'doc_id':ids[i],'version_key':previews['papers'][ids[i]]['version_key'],'catalog_key':profiles[i]['catalog_key'],'value':'like','revision':0}
            return client.post(URL+'/api/profile/feedback',json=body,headers={'Origin':URL},timeout=10)
        with ThreadPoolExecutor(max_workers=6) as pool: replies=list(pool.map(save,enumerate(clients)))
        check('12_concurrent_saves',all(r.status_code==200 for r in replies))
        for i,client in enumerate(clients):
            result=client.get(URL+'/api/profile',timeout=10).json()
            check('isolated_'+str(i),[p['doc_id'] for p in result['items']]==[ids[i]])
        def recommendation(pair):
            i,client=pair;before=time.perf_counter()
            response=client.get(URL+'/api/recommendations',timeout=10)
            timings.append(time.perf_counter()-before)
            result=response.json()
            return response.status_code==200 and result['papers'] and all(
                all(a['doc_id']==ids[i] for a in p['explanation']['anchors']) for p in result['papers'])
        with ThreadPoolExecutor(max_workers=6) as pool: checks=list(pool.map(recommendation,enumerate(clients)))
        check('12_own_recommendation_anchors',all(checks))
        exports=[c.get(URL+'/api/profile/export',timeout=10).json() for c in clients]
        check('12_export_isolation',all([p['doc_id'] for p in data['items']]==[ids[i]] for i,data in enumerate(exports)))
        def search(i):
            client=clients[i%12];before=time.perf_counter()
            response=client.get(URL+'/api/search',params={'topic':'generative','q':'generative retrieval','context':'none'},timeout=10)
            timings.append(time.perf_counter()-before)
            return response.status_code==200 and response.json()['trace'][0]['catalog']==162
        with ThreadPoolExecutor(max_workers=6) as pool: checks=list(pool.map(search,range(24)))
        check('24_searches_six_concurrent',all(checks))
        paper=clients[0].get(URL+'/api/paper/'+ids[0],timeout=10).json()['paper']
        check('original_reader',paper['abstract'].startswith(previews['papers'][ids[0]]['abstract_excerpt']) and paper['source_verified'])
        stop();second_start=start()
        for i,client in enumerate(clients):
            profile=client.get(URL+'/api/profile',timeout=10).json()
            check('restart_persistence_'+str(i),profile['revision']==1 and [p['doc_id'] for p in profile['items']]==[ids[i]])
        for i,client in enumerate(clients):
            response=client.post(URL+'/api/profile/reset',json={'catalog_key':profiles[i]['catalog_key'],'revision':1},headers={'Origin':URL},timeout=10)
            check('cleanup_'+str(i),response.status_code==200 and not response.json()['items'])
    finally:
        stop();done.set();sampler.join(timeout=2)
        (run/'stopped.json').write_text(json.dumps({'stopped':True,'module':MODULE,'visitor_preferences_left':0})+'\n')
    timings.sort()
    report={'passed':len(CHECKS),'checks':CHECKS,'visitors':12,'concurrent_workers':6,
            'startup_seconds':[first_start,second_start], 'http_timing_samples':len(timings),
            'sample_p50_seconds':timings[len(timings)//2],'sample_p95_seconds':timings[int(.95*(len(timings)-1))],
            'peak_process_rss_bytes':max(r['rss'] for r in SAMPLES),'peak_process_working_set_bytes':max(r['peak_wset'] for r in SAMPLES),
            'memory_samples':len(SAMPLES),'fixture_stopped':True,'private_fixture':str(run.relative_to(ROOT)),
            'scope':'local Windows loopback HTTP, six concurrent requests; not public load, production QPS, Linux container or TLS validation'}
    (ROOT/'reports/stage39/http-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({k:v for k,v in report.items() if k!='checks'})


if __name__=='__main__':main()
