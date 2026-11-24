"""Seal the research loop, additive live catalog and namespace migration evidence."""
from datetime import datetime
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/stage57'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def main():
    os.chdir(ROOT);prior=ROOT/'reports/stage56/final-validation.json'
    assert sha(prior)=='0d2ebe8310a875bb2acbba3cc2cc4b215f7ebe598b2c3a3bcb6bb2ed8f4b1987'
    previous=subprocess.run([sys.executable,'-E','-s','-m','scripts.verify_research56_delivery'],capture_output=True,text=True)
    assert previous.returncode==0,previous.stdout+previous.stderr
    final=REPORT/'final-validation.json'
    if final.exists():
        value=read(final)
        for name,expected in value['files'].items():assert sha(ROOT/name)==expected,name
        print({'status':'verified','assets':len(value['files']),'receipt_sha256':sha(final)});return
    (REPORT/'historic-verification.log').write_text(previous.stdout+previous.stderr,encoding='utf8')
    old,new=ROOT/'deploy/stage56',ROOT/'deploy/stage57'
    for folder in ['catalog','experiment-artifacts','web/vendor']:
        for p in (old/folder).rglob('*'):
            if p.is_file():assert p.read_bytes()==(new/p.relative_to(old)).read_bytes(),p
    for name in ['evidence-data.json','evidence-receipt.json','sid-lab.json','sid-lab-receipt.json','requirements.lock','learning-paths.json']:
        assert (old/name).read_bytes()==(new/name).read_bytes(),name
    supplement=read(new/'supplement/receipt.json');rows=read(new/'supplement/documents.json')
    assert sha(new/'supplement/documents.json')==supplement['documents_sha256']
    assert len(rows)==supplement['count']==5 and len({r['doc_id'] for r in rows})==5
    raw_files={r['provenance']['raw_file'] for r in rows};assert len(raw_files)==1
    raw=new/'catalog'/next(iter(raw_files));assert all(sha(raw)==r['provenance']['raw_sha256'] for r in rows)
    entries=ET.fromstring(raw.read_bytes());ns={'a':'http://www.w3.org/2005/Atom'}
    official={e.findtext('a:id',namespaces=ns).rsplit('/',1)[-1]:e for e in entries.findall('a:entry',ns)}
    normalized=lambda s:re.sub(r'\s+',' ',s).strip()
    for r in rows:
        doc=r['doc_id'];e=official[doc+'v1']
        assert normalized(e.findtext('a:title',namespaces=ns))==r['title']
        assert normalized(e.findtext('a:summary',namespaces=ns))==r['abstract']
        assert datetime.fromisoformat(e.findtext('a:published',namespaces=ns))==datetime.fromisoformat(r['published_at'])
        assert r['source_url']=='https://arxiv.org/abs/'+doc+'v1' and r['version_key']=='arxiv:'+doc+'v1'
    review=read(REPORT/'topic-review.json')
    assert {r['doc_id'] for r in review['included']}=={r['doc_id'] for r in rows}
    assert 'assistant' in review['reviewer'] and review['real_user_need']=='多模态快慢思考'
    expected={'api-validation.json':69,'reading-validation.json':72,'tools-validation.json':125,'loop-validation.json':92,'migration-validation.json':16,'memory-validation.json':26}
    # The copied reading acceptance keeps its previous report basename.
    if not (REPORT/'reading-validation.json').exists() and (REPORT/'validation.json').exists():
        raise AssertionError('Use the explicit reading report path')
    for name,count in expected.items():assert read(REPORT/name)['passed']==count,(name,count)
    assert read(REPORT/'api-validation.json')['unchanged_responses']==20
    browser=read(REPORT/'browser-validation.json');assert browser['status']=='passed' and browser['desktop']['fullCards']>=2
    assert browser['desktop']['readerWidth']>=580 and browser['desktop']['documentWidth']==1280
    assert min(browser['comparison']['columns'])>=200
    assert read(REPORT/'preference-preservation.json')['all_six_tables_preserved']
    assert read(REPORT/'launcher-validation.json')['release']=='stage57'
    environment=read(ROOT/'reports/stage52/environment.json');package_counts={}
    for name,relative in [('cpu','.cache/stage17/runtime'),('web','.cache/stage39/runtime-secure')]:
        packages={}
        for p in (ROOT/relative/'Lib/site-packages').glob('*.dist-info/METADATA'):
            meta=Parser().parsestr(p.read_text(encoding='utf8'));packages[meta['Name']]=meta['Version']
        assert packages==environment[name]['packages'],name
        package_counts[name]=len(packages)
    scripts=['run_research57_local.py','run_research57_acceptance.py','research57_control.py','prepare_demand57_candidates.py','validate_research57_delivery.py','validate_research57.py','validate_research57_tools.py','validate_research57_loop.py','validate_research57_migration.py','validate_research57_memory.mjs','snapshot_research57_preferences.py','verify_research57_delivery.py']
    paths=[p for p in new.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths+=[ROOT/'scripts'/n for n in scripts]+[ROOT/'docs/RESEARCH_LOOP_V57.md']
    paths+=[p for p in REPORT.rglob('*') if p.is_file() and p!=final]
    paths+=[ROOT/'data/stage57-candidates/3953c44d122832aa/acquisition.json']
    files={str(p.relative_to(ROOT)):sha(p) for p in sorted(set(paths))}
    receipt={'status':'passed','date':'2026-11-07','scope':'local desktop research loop and curated live supplement; no held-out relevance, public deployment or new training',
        'prior_receipt_sha256':sha(prior),'checks':{'automatic_checks':sum(expected.values()),'browser_checks':len(browser['checks']),'old_responses_exact':20,'intentional_metadata_changes':4,'prior_v56_assets_unchanged':118,'historical_chain_verified':True,'live_catalog':167,'historical_core':162,'offline_sft':9000,'all_six_visitor_tables_preserved':True,'no_runtime_packages_added':True,'package_counts':package_counts,'human_relevance_labels':0,'new_training':False,'public_deployment':False},'files':files}
    final.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print({'status':'passed','assets':len(files),'receipt_sha256':sha(final)})
if __name__=='__main__':main()
