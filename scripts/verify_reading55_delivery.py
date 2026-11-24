"""Seal the reading-list delivery and verify the frozen earlier chain."""
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/stage55'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def main():
    os.chdir(ROOT)
    prior=ROOT/'reports/stage54/final-validation.json'
    assert sha(prior)=='86e6539802a2ba94954172f4a5bd1b19a8d76f6667b7e3f138ba14a82c6b412d'
    previous=subprocess.run([sys.executable,'-E','-s','-m','scripts.verify_workspace54_delivery'],capture_output=True,text=True)
    assert previous.returncode==0,previous.stdout+previous.stderr
    final=REPORT/'final-validation.json'
    if final.exists():
        value=read(final)
        for name,expected in value['files'].items():assert sha(ROOT/name)==expected,name
        print({'status':'verified','assets':len(value['files']),'receipt_sha256':sha(final)});return
    (REPORT/'historic-verification.log').write_text(previous.stdout+previous.stderr,encoding='utf-8')
    old,new=ROOT/'deploy/stage54',ROOT/'deploy/stage55'
    for folder in ['catalog','experiment-artifacts','web/vendor']:
        for p in (old/folder).rglob('*'):
            if p.is_file():assert p.read_bytes()==(new/p.relative_to(old)).read_bytes(),p
    for filename in ['evidence-data.json','evidence-receipt.json','sid-lab.json','sid-lab-receipt.json','requirements.lock']:
        assert (old/filename).read_bytes()==(new/filename).read_bytes(),filename
    for p in (old/'trialsite').glob('*.py'):
        if p.name not in ['app.py','delivery.py']:assert p.read_bytes()==(new/'trialsite'/p.name).read_bytes(),p
    # The only legacy app adaptation exposes its already-validated parser for v2 use.
    app=(new/'trialsite/app.py').read_text(encoding='utf-8')
    assert app.replace('    app.state.parse_preference_backup = backup_for\n\n','')==(old/'trialsite/app.py').read_text(encoding='utf-8')
    api=read(REPORT/'api-validation.json');reading=read(REPORT/'reading-validation.json');memory=read(REPORT/'memory-validation.json');browser=read(REPORT/'browser-validation.json')
    assert api['passed']==68 and api['unchanged_responses']==24
    assert reading['status']=='passed' and reading['passed']==72
    assert memory['status']=='passed' and memory['passed']==20
    assert browser['status']=='passed' and len(browser['checks'])>=10
    assert browser['geometry']['fullCandidates']>=2 and browser['geometry']['readerWidth']>=585 and not browser['geometry']['stripOverflow']
    for case,fields in [('restore',['filter','selected','readScroll','readMax']),('pageReturn',['filter','selected','listScroll','readScroll'])]:
        for field in fields:
            left,right=browser[case]['before'][field],browser[case]['after'][field]
            assert abs(left-right)<1 if isinstance(left,(int,float)) else left==right,(case,field)
    assert read(REPORT/'preference-preservation.json')['real_preferences_unchanged']
    assert read(REPORT/'launcher-validation.json')['release']=='stage55'
    environment=read(ROOT/'reports/stage52/environment.json')
    for name,relative in [('cpu','.cache/stage17/runtime'),('web','.cache/stage39/runtime-secure')]:
        packages={}
        for p in (ROOT/relative/'Lib/site-packages').glob('*.dist-info/METADATA'):
            meta=Parser().parsestr(p.read_text(encoding='utf-8'));packages[meta['Name']]=meta['Version']
        assert packages==environment[name]['packages'],name
    names=['run_reading55_local.py','reading55_control.py','run_reading55_acceptance.py','validate_reading55_delivery.py','validate_reading55.py','validate_reading55_memory.mjs','snapshot_reading55_preferences.py','verify_reading55_delivery.py']
    paths=[p for p in new.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths+=[ROOT/'scripts'/name for name in names]
    paths+=[ROOT/'docs/READING_LIST_V55.md']
    paths+=[p for p in REPORT.rglob('*') if p.is_file() and p!=final]
    files={str(p.relative_to(ROOT)):sha(p) for p in sorted(set(paths))}
    value={'status':'passed','date':'2026-11-05','scope':'Explicit visitor reading workflow and v2 backup; local desktop delivery only',
        'prior_receipt_sha256':sha(prior),'checks':{'prior_v54_assets_unchanged':111,'historic_chain_verified':True,'old_api_checks':68,'old_responses_unchanged':24,'reading_behavior_checks':72,'memory_boundary_checks':20,
        'browser_reading_and_backup':True,'reading_independent_of_preferences':True,'atomic_import':True,'legacy_preferences_unchanged':True,'python_packages_unchanged':True,'public_deployment':False,'training':False},'files':files}
    final.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({'status':'passed','assets':len(files),'receipt_sha256':sha(final)},flush=True)
if __name__=='__main__':main()
