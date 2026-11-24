"""Relocate, run and verify the public Windows handoff without original environments."""
from pathlib import Path
import argparse
import hashlib
import http.cookiejar
import json
import os
import re
import socket
import subprocess
import time
import urllib.request
import urllib.error
import zipfile

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/stage78'
BASE=ROOT/'.cache/stage78'

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--reuse',type=Path);args=parser.parse_args()
    checks=[]
    def check(n,v):
        if not v:raise AssertionError(n)
        checks.append(n)
    summary=json.loads((ROOT/'exports/stage78/PACKAGE-SUMMARY.json').read_text(encoding='utf8'))
    dest=args.reuse.resolve() if args.reuse else BASE/('relocated preview '+str(time.time_ns()))
    assert dest.is_relative_to(BASE.resolve())
    dest.mkdir(parents=True,exist_ok=bool(args.reuse))
    for b in summary['bundles']:
        p=ROOT/'exports/stage78'/b['filename'];check(b['filename']+'_hash',sha(p)==b['sha256'])
        with zipfile.ZipFile(p) as z:
            manifest=json.loads(z.read('PACKAGE-MANIFEST.json'))['files']
            check(b['filename']+'_explicit_inventory',len(manifest)==b['files'])
            check(b['filename']+'_no_original_private_roots',all(n.split('/')[0] not in ('data','runs','.cache','.git','visitor-data') for n in z.namelist()))
            check(b['filename']+'_no_visitor_keys_or_databases',not any(n.endswith(('.sqlite','.sqlite3','.db','session.key','.env')) for n in z.namelist()))
            for n,row in manifest.items():
                check_member=hashlib.sha256(z.read(n)).hexdigest()==row['sha256']
                if not check_member:raise AssertionError('Archive mismatch '+n)
            check(b['filename']+'_all_member_hashes',True)
            if 'Preview' in b['filename']:
                if args.reuse:
                    previous=json.loads((dest/'PACKAGE-MANIFEST.json').read_text(encoding='utf8'))['files']
                    for n,row in manifest.items():
                        if previous.get(n,{}).get('sha256')!=row['sha256'] or not (dest/n).is_file():
                            (dest/n).parent.mkdir(parents=True,exist_ok=True);(dest/n).write_bytes(z.read(n))
                    (dest/'PACKAGE-MANIFEST.json').write_bytes(z.read('PACKAGE-MANIFEST.json'))
                else:z.extractall(dest)
    python=dest/'runtime/python/python.exe'
    clean=os.environ.copy()
    for n in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV','CONDA_PREFIX'):clean.pop(n,None)
    with socket.socket() as probe:probe.bind(('127.0.0.1',8808))
    log=REPORT/'relocated-server.log'
    with log.open('w',encoding='utf8') as stream:
        proc=subprocess.Popen([str(python),'-E','-s','-u',str(dest/'handoff/2026-11-22/preview_server.py'),'--port','8808'],
            cwd=dest,env=clean,stdout=stream,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    origin='http://127.0.0.1:8808'
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def req(path,body=None,headers=None):
        r=urllib.request.Request(origin+path,data=None if body is None else json.dumps(body).encode(),headers={'Origin':origin,'Content-Type':'application/json',**(headers or {})})
        try:
            with op.open(r,timeout=15) as res:return res.status,res.read()
        except urllib.error.HTTPError as e:return e.code,e.read()
    def obj(path,body=None):
        code,raw=req(path,body);check(path+'_http200',code==200);return json.loads(raw)
    try:
        for _ in range(60):
            if proc.poll() is not None:raise RuntimeError('Relocated process failed; see log')
            try:
                if req('/api/health')[0]==200:break
            except (OSError,urllib.error.URLError):pass
            time.sleep(.3)
        h=obj('/api/health');check('real_public_catalog_no_llm',h['catalog']==167 and h['llm_enabled'] is False)
        code,raw=req('/');html=raw.decode();check('current_stage77_home',code==200 and 'main-experience77.mjs' in html)
        paths=re.findall(r'(?:src|href)="(/[^"]+)"',html)
        check('all_first_page_assets_resolve',all(req(p)[0]==200 for p in paths))
        for path in ('/main-experience77.mjs','/task-preview.mjs','/handoff-entry.mjs','/evidence.html'):
            code,raw=req(path);check('explicit_agent_gate_'+path,code==200 and b'http://127.0.0.1:8802/' not in raw)
        check('agent_gate_never_claims_model_execution','没有执行模型' in req('/handoff-status.html')[1].decode())
        check('agent_gate_uses_external_style',b'<style>' not in req('/handoff-status.html')[1])
        check('agent_gate_style_resolves',req('/handoff-status.css')[0]==200)
        profile=obj('/api/profile');check('no_sender_preferences',profile['like_count']==0 and profile['hidden_count']==0)
        found=obj('/api/search?topic=generative&q=retrieval&method=bm25&context=none')
        check('real_bm25_search_returns_papers',len(found['papers'])>0)
        p=found['papers'][0];doc=p['doc_id'];paper=obj('/api/paper/'+doc)['paper']
        check('actual_versioned_original_abstract',bool(paper['abstract']) and paper['source_verified'] and 'v1' in paper['version_key'] and paper['source_url'].startswith('https://arxiv.org/'))
        common={'doc_id':doc,'version_key':paper['version_key'],'catalog_key':profile['catalog_key']}
        changed=obj('/api/profile/feedback',{**common,'value':'like','revision':profile['revision']})
        check('likes_saved_to_new_visitor',changed['like_count']==1)
        rec=obj('/api/recommendations');check('content_recommendation_excludes_seen',len(rec['papers'])>0 and all(r['doc_id']!=doc for r in rec['papers']))
        backup=obj('/api/profile/export');check('actual_backup_contains_favorite',any(r['doc_id']==doc for r in backup['items']))
        check('visitor_profile_persists_across_requests',obj('/api/profile')['like_count']==1)
        other=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        with other.open(origin+'/api/profile') as r:check('second_visitor_isolated',json.load(r)['like_count']==0)
        hidden=obj('/api/profile/feedback',{**common,'value':'hide','revision':changed['revision']})
        check('dislike_applies_and_removes_like',hidden['hidden_count']==1 and hidden['like_count']==0)
        code,_=req('/api/profile/feedback',{**common,'value':'like','revision':hidden['revision'],'illegal':True});check('invalid_parameters_still_rejected',code==422)
        code,_=req('/api/profile/feedback',{**common,'value':'like','revision':hidden['revision']},{'Origin':'https://outside.example'});check('cross_origin_writes_rejected',code==403)
        check('no_original_environment_used',python.is_relative_to(dest) and not (dest/'.cache').exists())
    finally:
        proc.terminate();proc.wait(timeout=15)
    check('temporary_test_service_stopped',proc.poll() is not None)
    original=json.loads((ROOT/'reports/stage77/final-validation.json').read_text(encoding='utf8'))['files']
    for n,d in original.items():
        if sha(ROOT/n)!=d:raise AssertionError('Frozen source changed '+n)
    check('stage77_frozen_delivery_preserved',True)
    result={'status':'passed','date':'2026-11-22','checks':len(checks),'passed':checks,
        'validation_scope':'same Windows machine, new extraction path with spaces and bundled standalone Python; not a second machine',
        'zip_hashes':{b['filename']:b['sha256'] for b in summary['bundles']},'frozen_stage77_files_unchanged':len(original),
        'catalog':167,'new_model_runs':0,'private_source_data_included':False,'original_preferences_modified':False,
        'native_agent_runtime_included':False,'new_machine_validated':False,'temporary_service_stopped':True,
        'relocated_path':str(dest.relative_to(ROOT))}
    for target in (REPORT/'handoff-validation.json',ROOT/'exports/stage78/handoff-validation.json'):target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('passed','zip_hashes')},ensure_ascii=False))

if __name__=='__main__':main()
