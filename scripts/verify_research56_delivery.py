"""Seal v56 search evidence, comparison and notes while preserving v55."""
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/stage56'
def sha(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path:Path)->dict:return json.loads(path.read_text(encoding='utf-8-sig'))
def main()->None:
    os.chdir(ROOT);prior=ROOT/'reports/stage55/final-validation.json'
    assert sha(prior)=='f3097563fcdab3bb3703dc59b1f148d775d514c6bb2ac7d0e20c3739b5256c19'
    previous=subprocess.run([sys.executable,'-E','-s','-m','scripts.verify_reading55_delivery'],capture_output=True,text=True)
    assert previous.returncode==0,previous.stdout+previous.stderr
    final=REPORT/'final-validation.json'
    if final.exists():
        value=read(final)
        for name,expected in value['files'].items():assert sha(ROOT/name)==expected,name
        print({'status':'verified','assets':len(value['files']),'receipt_sha256':sha(final)});return
    (REPORT/'historic-verification.log').write_text(previous.stdout+previous.stderr,encoding='utf-8')
    old,new=ROOT/'deploy/stage55',ROOT/'deploy/stage56'
    for folder in ['catalog','experiment-artifacts','web/vendor']:
        for p in (old/folder).rglob('*'):
            if p.is_file():assert p.read_bytes()==(new/p.relative_to(old)).read_bytes(),p
    for filename in ['evidence-data.json','evidence-receipt.json','sid-lab.json','sid-lab-receipt.json','requirements.lock']:
        assert (old/filename).read_bytes()==(new/filename).read_bytes(),filename
    for p in (old/'trialsite').glob('*.py'):
        if p.name not in ['readinglog.py','delivery.py']:assert p.read_bytes()==(new/'trialsite'/p.name).read_bytes(),p
    log=(new/'trialsite/readinglog.py').read_text(encoding='utf-8')
    assert log.replace('    app.state.library_parse=parse_library\n    app.state.library_plans=plans\n','')==(old/'trialsite/readinglog.py').read_text(encoding='utf-8')
    api=read(REPORT/'api-validation.json');reading=read(REPORT/'reading-validation.json');tools=read(REPORT/'tools-validation.json');memory=read(REPORT/'memory-validation.json');browser=read(REPORT/'browser-validation.json')
    assert api['passed']==68 and api['unchanged_responses']==24
    assert reading['passed']==72 and tools['passed']==125 and memory['passed']==21
    assert browser['status']=='passed' and len(browser['checks'])==16
    assert browser['geometry']['fullCandidates']>=2 and browser['geometry']['readerWidth']>=585 and not browser['geometry']['headerOverflow']
    assert all(h>=200 for h in browser['comparisonGeometry']['abstractHeights']) and not browser['comparisonGeometry']['overflow']
    assert browser['comparisonGeometry']['footerBottom']<=browser['comparisonGeometry']['height']
    assert browser['reviewRestore']['filter']=='有笔记1' and browser['reviewRestore']['noteRestored'] and browser['reviewRestore']['comparisonCleared']
    assert browser['readerStrip']['noteButtons']==1 and not browser['readerStrip']['overflow']
    assert browser['comparisonContexts']==['generative retrieval document identifiers']*2
    assert read(REPORT/'preference-preservation.json')['existing_preferences_and_reading_unchanged']
    assert read(REPORT/'launcher-validation.json')['release']=='stage56'
    environment=read(ROOT/'reports/stage52/environment.json')
    for name,relative in [('cpu','.cache/stage17/runtime'),('web','.cache/stage39/runtime-secure')]:
        packages={}
        for p in (ROOT/relative/'Lib/site-packages').glob('*.dist-info/METADATA'):
            meta=Parser().parsestr(p.read_text(encoding='utf-8'));packages[meta['Name']]=meta['Version']
        assert packages==environment[name]['packages'],name
    names=['run_research56_local.py','research56_control.py','run_research56_acceptance.py','validate_research56_delivery.py','validate_research56.py','validate_research56_tools.py','validate_research56_memory.mjs','snapshot_research56_preferences.py','verify_research56_delivery.py']
    paths=[p for p in new.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths+=[ROOT/'scripts'/name for name in names]+[ROOT/'docs/RESEARCH_WORKBENCH_V56.md']
    paths+=[p for p in REPORT.rglob('*') if p.is_file() and p!=final]
    files={str(p.relative_to(ROOT)):sha(p) for p in sorted(set(paths))}
    value={'status':'passed','date':'2026-11-05','scope':'search evidence, 2-3 paper comparison, private notes/review/v3 backup; local desktop only',
        'prior_receipt_sha256':sha(prior),'checks':{'prior_v55_assets_unchanged':107,'historic_chain_verified':True,'automatic_checks':286,'browser_checks':16,'old_responses_unchanged':24,
        'search_ranking_unchanged':True,'actual_match_terms':True,'notes_isolated_and_CAS':True,'atomic_v3_backup':True,'old_visitor_and_reading_data_unchanged':True,'python_packages_unchanged':True,'training':False,'public_deployment':False},'files':files}
    final.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({'status':'passed','assets':len(files),'receipt_sha256':sha(final)},flush=True)
if __name__=='__main__':main()
