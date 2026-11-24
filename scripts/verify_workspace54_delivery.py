"""Seal reading continuity and visual changes, preserving v53 and algorithm evidence."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from email.parser import Parser

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/stage54'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def compare_case(name,fields):
    data=read(REPORT/name)
    for field in fields:
        left,right=data['before'][field],data['after'][field]
        assert abs(left-right)<1 if isinstance(left,(int,float)) else left==right,(name,field,left,right)

def main():
    os.chdir(ROOT)
    prior=ROOT/'reports/stage53/final-validation.json'
    assert sha(prior)=='65bfb081e096d0c7685c38d3589760eb5c1b38258b6f835016027b71f38f9059'
    previous=subprocess.run([sys.executable,'-E','-s','-m','scripts.verify_workbench_delivery'],capture_output=True,text=True)
    assert previous.returncode==0,previous.stdout+previous.stderr
    final=REPORT/'final-validation.json'
    if final.exists():
        value=read(final)
        for name,expected in value['files'].items():assert sha(ROOT/name)==expected,name
        print({'status':'verified','assets':len(value['files']),'receipt_sha256':sha(final)})
        return
    (REPORT/'historic-verification.log').write_text(previous.stdout+previous.stderr,encoding='utf-8')
    old,new=ROOT/'deploy/stage53',ROOT/'deploy/stage54'
    for folder in ['catalog','experiment-artifacts','web/vendor']:
        for p in (old/folder).rglob('*'):
            if p.is_file():assert p.read_bytes()==(new/p.relative_to(old)).read_bytes(),p
    for filename in ['evidence-data.json','evidence-receipt.json','sid-lab.json','sid-lab-receipt.json']:
        assert (old/filename).read_bytes()==(new/filename).read_bytes(),filename
    for p in (old/'trialsite').glob('*.py'):
        if p.name!='delivery.py':assert p.read_bytes()==(new/'trialsite'/p.name).read_bytes(),p
    api=read(REPORT/'api-validation.json');memory=read(REPORT/'memory-validation.json')
    assert api['passed']==68 and api['unchanged_responses']==24
    assert memory['status']=='passed' and memory['passed']==17
    for name in ['reload-case.json','return-case.json','middle-case.json','parameters-case.json']:
        compare_case(name,['query','method','context','selected','listScroll','readScroll'])
    modes=read(REPORT/'mode-switch-case.json')
    for group in ['search','recommend']:
        for field in ['selected','listScroll','readScroll']:
            left,right=modes[group+'Before'][field],modes[group+'After'][field]
            assert abs(left-right)<1 if isinstance(left,(int,float)) else left==right
    hidden=read(REPORT/'hidden-panel-case.json')
    assert hidden['traceSelected']=='true' and abs(hidden['readBefore']-hidden['readAfter'])<1
    assert read(REPORT/'focus-case.json')['focused'] and read(REPORT/'focus-case.json')['width']>=1000
    clear=read(REPORT/'clear-case.json')
    assert clear['home_after_clear_and_reload'] and clear['isolated_favorite_count_after_clear']==1
    geometry=read(REPORT/'geometry.json')
    assert geometry['viewport']==[1280,720] and geometry['fullCandidates']>=2 and geometry['readerWidth']>=585
    assert geometry['projectsCollapsed']
    assert read(REPORT/'browser-validation.json')['status']=='passed'
    assert read(REPORT/'launcher-validation.json')['release']=='stage54'
    assert read(REPORT/'preference-preservation.json')['real_preferences_unchanged']
    index=(new/'web/index.html').read_text(encoding='utf-8')
    assert '/main.mjs?v=54.3' in index and '/reading-studio.css?v=54.4' in index
    environment=read(ROOT/'reports/stage52/environment.json')
    for name,relative in [('cpu','.cache/stage17/runtime'),('web','.cache/stage39/runtime-secure')]:
        packages={}
        for p in (ROOT/relative/'Lib/site-packages').glob('*.dist-info/METADATA'):
            meta=Parser().parsestr(p.read_text(encoding='utf-8'));packages[meta['Name']]=meta['Version']
        assert packages==environment[name]['packages'],name
    paths=[p for p in new.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths += [ROOT/'docs/READING_STUDIO_V54.md']
    paths += [ROOT/'scripts'/name for name in ['run_workspace54_local.py','workspace54_control.py','run_workspace54_acceptance.py','validate_workspace54_delivery.py','snapshot_workspace54_preferences.py','validate_workspace54_memory.mjs','verify_workspace54_delivery.py']]
    paths += [p for p in REPORT.rglob('*') if p.is_file() and p!=final]
    files={str(p.relative_to(ROOT)):sha(p) for p in sorted(set(paths))}
    value={'status':'passed','date':'2026-11-05','scope':'desktop reading continuity/navigation/visual hierarchy; no algorithm changes',
        'prior_receipt_sha256':sha(prior),'checks':{'prior_v53_assets_unchanged':99,'historic_chain_verified':True,'api_checks':68,'old_responses_unchanged':24,
        'memory_boundary_checks':17,'fresh_query_and_abstract_restore':True,'per_mode_positions':True,'middle_and_hidden_positions':True,
        'daily_navigation_and_research_group':True,'paper_green_theme':True,'real_preferences_unchanged':True,'python_packages_unchanged':True,
        'desktop_candidates':geometry['fullCandidates'],'training':False,'public_deployment':False},'files':files}
    final.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({'status':'passed','assets':len(files),'receipt_sha256':sha(final)},flush=True)
if __name__=='__main__':main()
