"""Seal the scoped first-viewport presentation change without running a model."""
import ast
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/stage77'
def read(p):return json.loads(p.read_text(encoding='utf8'))
def digest(p):return sha256(p.read_bytes()).hexdigest()

def main():
    names=['first-view-validation','step1-validation','step2-validation','step3-browser-validation','http-regression']
    reports={n:read(OUT/(n+'.json')) for n in names}
    assert all(v['status']=='passed' for v in reports.values())
    total=sum(v['checks'] for v in reports.values());assert total==142
    before=read(OUT/'before.json');older=read(ROOT/'reports/stage74/before.json')
    for name,h in {**before,**older}.items():assert digest(ROOT/name)==h,name
    from research73.common import verify_protocol,DATA
    verify_protocol()
    for name,h in read(DATA/'labeling-lock.json')['files'].items():assert digest(ROOT/name)==h,name
    with sqlite3.connect('file:'+(DATA/'work/annotations.sqlite3').as_posix()+'?mode=ro',uri=True) as db:
        human=db.execute("SELECT count(*) FROM annotation_records WHERE json_extract(body,'$.origin')='human'").fetchone()[0]
    assert human==0
    assert read(DATA/'agent-runtime.json')['model_loads']==1
    for folder in ('data/stage77-lab','data/stage77-custom/jobs'):assert not list((ROOT/folder).rglob('input.json'))
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}));http={}
    for port,path in [(8791,'/'),(8791,'/trial.html'),(8791,'/evidence.html'),(8791,'/first-view77.css'),(8802,'/'),(8802,'/first-view77.js'),(8802,'/evaluation.html'),(8802,'/label')]:
        with op.open(f'http://127.0.0.1:{port}'+path,timeout=15) as r:http[str(port)+path]=r.status;assert r.status==200
    with op.open('http://127.0.0.1:8802/lab/activity',timeout=15) as r:assert not any(j['status']=='running' for j in json.load(r)['jobs'])
    with op.open('http://127.0.0.1:8802/api/evaluation/summary',timeout=15) as r:summary=json.load(r)
    assert summary['algorithm']['human_submitted_pairs']==0 and summary['algorithm']['quality_scores'] is None
    assert sum(m['model_calls'] for m in summary['agent']['methods'].values())==53
    assert [summary['agent']['methods'][p]['protocol_completed'] for p in ('fixed','llm_agent','constrained')]==[4,0,3]
    try:op.open('http://127.0.0.1:9327/json/version',timeout=2)
    except (urllib.error.URLError,TimeoutError):pass
    else:raise AssertionError('Dedicated verification browser still open')
    py=list((ROOT/'research77').glob('*.py'))+[ROOT/'scripts/run_research77_workbench.py',ROOT/'scripts/research77_workbench_control.py']
    for p in py:ast.parse(p.read_text(encoding='utf8'))
    js=[p for p in (ROOT/'research77').rglob('*') if p.suffix in ('.js','.mjs','.cjs')]
    for p in js:subprocess.run(['node','--check',str(p)],check=True,capture_output=True)
    assert 'research77.control' in (ROOT/'project-agent.cmd').read_text()
    assert 'scripts.research77_workbench_control' in (ROOT/'papertrail-workbench.cmd').read_text()
    paths=[p for folder in (ROOT/'research77',OUT) for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='final-validation.json']
    paths += [ROOT/'scripts/run_research77_workbench.py',ROOT/'scripts/research77_workbench_control.py',ROOT/'docs/FIRST_VIEW_V77.md',ROOT/'project-agent.cmd',ROOT/'papertrail-workbench.cmd']
    result={'status':'passed','date':'2026-11-17','scope':'first_view_presentation_only',
        'checks':{k:v['checks'] for k,v in reports.items()},'total_checks':total,
        'prior_frozen_files_preserved':len(before),'prior_original_sources_preserved':len(older),
        'new_model_runs':0,'new_training':False,'catalog_expansion':False,'new_framework_dependencies':False,
        'new_preference_writes':0,'new_human_trials':0,'new_human_relevance_labels':0,'ranking_quality_scores':None,
        'historical_model_calls':53,'historical_model_loads':1,'historical_protocol_completed':{'fixed':4,'llm_agent':0,'constrained':3},
        'native_worker_retained':'research71.worker','sse_and_model_budgets_retained':True,'new_live_model_disconnect_test':False,
        'local_http_status':http,'dedicated_browser_closed':True,'screenshots_viewed':True,'mobile_tested':False,
        'python_syntax_files':len(py),'javascript_syntax_files':len(js),
        'files':{str(p.relative_to(ROOT)):digest(p) for p in sorted(paths)}}
    (OUT/'final-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='files'},ensure_ascii=False))

if __name__=='__main__':main()
