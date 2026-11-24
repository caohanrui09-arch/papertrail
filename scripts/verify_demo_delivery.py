"""Seal the final local demo; preserve historic receipts, private data and models."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/stage52'

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))

def main():
    os.chdir(ROOT)
    prior=ROOT/'reports/stage51/final-validation.json'
    assert sha(prior)=='b2e34a665abb82f1e90b0a3672c97aa5194c58efab2838bd0be3dcb16762c4d3'
    final=REPORT/'final-validation.json'
    if final.exists():
        subprocess.run([sys.executable,'-E','-s','-m','scripts.verify_sid_prefix_prior'],check=True)
        value=read(final)
        for path,expected in value['files'].items():assert sha(ROOT/path)==expected,path
        print({'status':'verified','assets':len(value['files']),'receipt_sha256':sha(final)})
        return
    # Existing verifier is read-only when its historical receipt exists.
    result=subprocess.run([sys.executable,'-E','-s','-m','scripts.verify_sid_prefix_prior'],capture_output=True,text=True)
    (REPORT/'historic-verification.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    assert result.returncode==0,'Historic receipt chain failed; inspect log'
    lock=read(REPORT/'evidence-source-lock.json')
    for path,expected in lock['files'].items():assert sha(ROOT/path)==expected,path
    bundle=ROOT/'deploy/stage52'
    receipt=read(bundle/'evidence-receipt.json');evidence=read(bundle/'evidence-data.json')
    assert sha(bundle/'evidence-data.json')==receipt['sha256']
    assert evidence['live']['catalog']==162 and evidence['sft']['catalog']==9000
    assert evidence['status']=='current_budget_design_closed' and not evidence['live']['llm_in_live_path']
    assert evidence['diagnosis']['models_beating_prefix_prior']==0
    assert set(evidence['downloads'])=={'tuning','priors','closure','resume'}
    for key,item in evidence['downloads'].items():
        assert Path(item['filename']).name==item['filename']
        assert sha(bundle/'experiment-artifacts'/item['filename'])==item['sha256']==receipt['downloads'][key]
    assert (bundle/'experiment-artifacts/resume-final.md').read_bytes()==(ROOT/'docs/RESUME_FINAL_V52.md').read_bytes()
    api=read(REPORT/'api-validation.json');ui=read(REPORT/'browser-validation.json');launch=read(REPORT/'launcher-validation.json')
    assert api['passed']==68 and api['unchanged_responses']==24
    assert ui['status']==launch['status']=='passed'
    assert read(REPORT/'preference-preservation.json')['real_preferences_unchanged']
    assert len(read(prior)['files'])==30
    # Freeze only the new delivery, sources and selected aggregate material; no visitor volume.
    paths=[p for p in bundle.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths += [ROOT/'papertrail.cmd',ROOT/'docs/FINAL_DELIVERY_V52.md',ROOT/'docs/RESUME_FINAL_V52.md']
    for name in ['prepare_demo_delivery.py','adapt_demo_delivery.py','finalize_demo_assets.py','validate_demo_delivery.py','verify_demo_delivery.py','run_demo_delivery_local.py','demo_delivery_control.py','run_delivery_acceptance.py','snapshot_delivery_preferences.py']:
        paths.append(ROOT/'scripts'/name)
    paths += [p for p in REPORT.rglob('*') if p.is_file() and p!=final]
    files={str(p.relative_to(ROOT)):sha(p) for p in sorted(set(paths))}
    value={'status':'passed','date':'2026-11-05','scope':'local interactive demo and aggregate evidence; no public deployment or training',
        'prior_receipt_sha256':sha(prior),'checks':{'historic_assets_unchanged':772,'api_checks':68,'old_responses_unchanged':24,
        'browser_flow':True,'launcher_from_home_directory':True,'real_preferences_unchanged':True,
        'web_catalog':162,'offline_sft_catalog':9000,'new_training':False,'new_dependencies':False,'public_deployment':False},'files':files}
    final.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({'status':'passed','assets':len(files),'receipt_sha256':sha(final)},flush=True)

if __name__=='__main__':main()
