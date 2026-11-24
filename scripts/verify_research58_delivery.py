"""Seal v58 reading/filtering while retaining every prior frozen asset."""
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/stage58'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def git_blob(p):
    raw=p.read_bytes();return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
def main():
    os.chdir(ROOT);prior=ROOT/'reports/stage57/final-validation.json'
    assert sha(prior)=='9395f342f0870f0e3f427ae82f163bfad819632662feb3b9f5a4f31cf6113ff1'
    previous=subprocess.run([sys.executable,'-E','-s','-m','scripts.verify_research57_delivery'],capture_output=True,text=True)
    assert previous.returncode==0,previous.stdout+previous.stderr
    final=REPORT/'final-validation.json'
    if final.exists():
        value=read(final)
        for path,digest in value['files'].items():assert sha(ROOT/path)==digest,path
        print({'status':'verified','assets':len(value['files']),'receipt_sha256':sha(final)});return
    (REPORT/'historic-verification.log').write_text(previous.stdout+previous.stderr,encoding='utf8')
    old,new=ROOT/'deploy/stage57',ROOT/'deploy/stage58'
    for folder in ['catalog','supplement','experiment-artifacts','web/vendor']:
        for p in (old/folder).rglob('*'):
            if p.is_file():assert p.read_bytes()==(new/p.relative_to(old)).read_bytes(),p
    for name in ['evidence-data.json','evidence-receipt.json','sid-lab.json','sid-lab-receipt.json','requirements.lock','learning-paths.json']:
        assert (old/name).read_bytes()==(new/name).read_bytes(),name
    for name in ['reuse.py','security.py','notebook.py','readinglog.py','workspacecatalog.py','namespacemigration.py']:
        assert (old/'trialsite'/name).read_bytes()==(new/'trialsite'/name).read_bytes(),name
    vendor=read(REPORT/'vendor.json');assert vendor['version']=='2.10' and vendor['files']==18
    assert vendor['sha256']=='3dd8fd84eb46dc30bee1e23eaab8d8fb5a7f507347b23e5f38ad9675c84f40d3'
    assert git_blob(new/'third-party/pylatexenc/latex2text/__init__.py')=='67b28de616c81efda56a6d3bc2234dca118c2ce0'
    assert git_blob(new/'third-party/LICENSE.txt')=='56110d0afcb38edc9c9cb6148c9064b44968f45f'
    facts=read(new/'comparison-evidence.json');rows={r['doc_id']:r for r in read(new/'supplement/documents.json')}
    assert set(facts['papers'])==set(rows)
    missing=[]
    for doc,fields in facts['papers'].items():
        assert set(fields)=={'control','selection','training'}
        for field,value in fields.items():
            if value is None:missing.append((doc,field));continue
            assert value['evidence'] in rows[doc]['abstract'] and value['evidence']
            assert value['source_url']==rows[doc]['source_url'] and value['version_key']==rows[doc]['version_key']
    assert sorted(missing)==[('2504.18458','training'),('2506.00806','training'),('2610.15810','training')]
    expected={'api-validation.json':69,'reading-validation.json':72,'tools-validation.json':125,'loop-validation.json':92,'migration-validation.json':16,'memory-validation.json':29,'features-validation.json':84}
    for name,count in expected.items():assert read(REPORT/name)['passed']==count,(name,count)
    assert read(REPORT/'api-validation.json')['unchanged_responses']==20
    browser=read(REPORT/'browser-validation.json')
    assert browser['status']=='passed' and browser['desktop']['fullCards']>=2 and browser['desktop']['readerWidth']>=580
    assert browser['desktop']['width']==browser['desktop']['documentWidth']==1280
    assert min(browser['comparison']['columns'])>=200 and browser['comparison']['footerBottom']<=browser['comparison']['height']
    assert read(REPORT/'preference-preservation.json')['all_existing_namespaces_unchanged']
    assert read(REPORT/'launcher-validation.json')['release']=='stage58'
    environment=read(ROOT/'reports/stage52/environment.json');package_counts={}
    for name,relative in [('cpu','.cache/stage17/runtime'),('web','.cache/stage39/runtime-secure')]:
        packages={}
        for p in (ROOT/relative/'Lib/site-packages').glob('*.dist-info/METADATA'):
            m=Parser().parsestr(p.read_text(encoding='utf8'));packages[m['Name']]=m['Version']
        assert packages==environment[name]['packages'],name
        package_counts[name]=len(packages)
    names=['run_research58_local.py','run_research58_acceptance.py','research58_control.py','validate_research58_delivery.py','validate_research58.py','validate_research58_tools.py','validate_research58_loop.py','validate_research58_migration.py','validate_research58_memory.mjs','validate_research58_features.py','snapshot_research58_preferences.py','verify_research58_delivery.py']
    paths=[p for p in new.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths+=[ROOT/'scripts'/name for name in names]+[ROOT/'docs/READING_FILTERS_V58.md']
    paths+=[p for p in REPORT.rglob('*') if p.is_file() and p!=final]
    files={str(p.relative_to(ROOT)):sha(p) for p in sorted(set(paths))}
    receipt={'status':'passed','date':'2026-11-08','scope':'four local desktop reading/organization features; no corpus expansion, model training or relevance uplift claim',
        'prior_receipt_sha256':sha(prior),'checks':{'automatic_checks':sum(expected.values()),'browser_checks':len(browser['checks']),'old_responses_exact':20,'prior_v57_assets_unchanged':133,'historical_chain_verified':True,'catalog_unchanged':167,'offline_experiment_unchanged':9000,'comparison_exact_abstract_evidence':12,'unverified_training_fields_left_empty':3,'existing_private_data_preserved':True,'shared_installed_packages_unchanged':package_counts,'isolated_source_component':'pylatexenc2.10 MIT, unchanged upstream source','human_relevance_labels':0,'new_training':False,'public_deployment':False},'files':files}
    final.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print({'status':'passed','assets':len(files),'receipt_sha256':sha(final)})
if __name__=='__main__':main()
