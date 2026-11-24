"""Verify immutable v52 evidence and the independent v53 workspace delivery."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/stage53'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def main():
    os.chdir(ROOT)
    prior=ROOT/'reports/stage52/final-validation.json'
    assert sha(prior)=='eb983a3d870e8d3551c701657d3f556f7318086c72c111ff84e9219acca253ad'
    final=REPORT/'final-validation.json'
    historical=subprocess.run([sys.executable,'-E','-s','-m','scripts.verify_demo_delivery'],capture_output=True,text=True)
    assert historical.returncode==0,historical.stdout+historical.stderr
    if final.exists():
        value=read(final)
        for name,expected in value['files'].items():assert sha(ROOT/name)==expected,name
        print({'status':'verified','assets':len(value['files']),'receipt_sha256':sha(final)})
        return
    (REPORT/'historic-verification.log').write_text(historical.stdout+historical.stderr,encoding='utf-8')
    old,new=ROOT/'deploy/stage52',ROOT/'deploy/stage53'
    for path in (old/'catalog').rglob('*'):
        if path.is_file():assert path.read_bytes()==(new/path.relative_to(old)).read_bytes()
    for filename in ['evidence-data.json','evidence-receipt.json','sid-lab.json','sid-lab-receipt.json']:
        assert (old/filename).read_bytes()==(new/filename).read_bytes(),filename
    for path in (old/'trialsite').glob('*.py'):
        if path.name!='delivery.py':assert path.read_bytes()==(new/'trialsite'/path.name).read_bytes(),path
    src=(new/'web/vendor/split.mjs').read_bytes()
    assert hashlib.sha1(b'blob '+str(len(src)).encode()+b'\0'+src).hexdigest()=='6e1871c3e9bb8596bf9ee0bd20dd55856632ea8d'
    license=(new/'web/vendor/SPLIT_LICENSE').read_bytes()
    assert hashlib.sha1(b'blob '+str(len(license)).encode()+b'\0'+license).hexdigest()=='35bcf12a25810385d9aac42a47ebdd8908899c6e'
    assert '/main.mjs?v=53.1' in (new/'web/index.html').read_text(encoding='utf-8')
    api=read(REPORT/'api-validation.json');before=read(REPORT/'before-layout.json');after=read(REPORT/'after-layout.json')
    assert api['passed']==68 and api['unchanged_responses']==24
    assert before['viewport']==after['viewport']==[1280,720]
    assert before['candidate_ids']==after['candidate_ids']
    assert before['full_candidates']==1 and after['full_candidates']==2
    assert after['reader_width']>before['reader_width'] and after['list_height']>before['list_height']
    assert read(REPORT/'browser-validation.json')['status']=='passed'
    assert read(REPORT/'preference-preservation.json')['real_preferences_unchanged']
    assert read(REPORT/'launcher-validation.json')['release']=='stage53'
    # Verify package metadata without importing ML modules or changing either environment.
    expected=read(ROOT/'reports/stage52/environment.json')
    from email.parser import Parser
    for name,relative in [('cpu','.cache/stage17/runtime'),('web','.cache/stage39/runtime-secure')]:
        packages={}
        for p in (ROOT/relative/'Lib/site-packages').glob('*.dist-info/METADATA'):
            meta=Parser().parsestr(p.read_text(encoding='utf-8'))
            packages[meta['Name']]=meta['Version']
        assert packages==expected[name]['packages'],name
    paths=[p for p in new.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths += [ROOT/'docs/WORKBENCH_V53.md']
    paths += [ROOT/'scripts'/name for name in ['run_workbench_local.py','workbench_control.py','run_workbench_acceptance.py','validate_workbench_delivery.py','snapshot_workbench_preferences.py','verify_workbench_delivery.py']]
    paths += [p for p in REPORT.rglob('*') if p.is_file() and p!=final]
    # The root current-version launcher is mutable; its audited snapshot is frozen above.
    files={str(p.relative_to(ROOT)):sha(p) for p in sorted(set(paths))}
    value={'status':'passed','date':'2026-11-05','scope':'desktop workspace layout and compact cards; algorithm/evidence unchanged',
        'prior_receipt_sha256':sha(prior),'checks':{'prior_v52_assets_unchanged':104,'older_historic_chain_verified':True,
        'api_checks':68,'old_responses_unchanged':24,'same_candidates':True,'complete_visible_candidates':[1,2],
        'reader_width_px':[before['reader_width'],after['reader_width']],'real_preferences_unchanged':True,
        'python_packages_unchanged':True,'vendored_module':'Split.js1.6.5 MIT','training':False,'public_deployment':False},'files':files}
    final.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({'status':'passed','assets':len(files),'receipt_sha256':sha(final)},flush=True)
if __name__=='__main__':main()
