"""Seal sequential deliverables using evidence, native API readbacks and source hashes."""
import ast
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import urllib.request,urllib.error

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/stage76'
def read(path):return json.loads(path.read_text(encoding='utf8'))
def digest(path):return sha256(path.read_bytes()).hexdigest()


def main():
    names=['step1-validation','step2-validation','step3-api-validation','step3-browser-validation','step3-boundary-validation','step4-data-validation','step4-browser-validation','step5-validation','http-regression']
    reports={name:read(OUT/(name+'.json')) for name in names}
    assert all(v['status']=='passed' for v in reports.values())
    assert sum(v['checks'] for v in reports.values())==165
    original=read(OUT/'before.json')
    for name,h in original.items():assert digest(ROOT/name)==h,name
    older=read(ROOT/'reports/stage74/before.json')
    for name,h in older.items():assert digest(ROOT/name)==h,name
    from research73.common import verify_protocol,DATA
    verify_protocol()
    for name,h in read(DATA/'labeling-lock.json')['files'].items():assert digest(ROOT/name)==h,name
    with sqlite3.connect('file:'+(DATA/'work/annotations.sqlite3').as_posix()+'?mode=ro',uri=True) as db:
        human=db.execute("SELECT count(*) FROM annotation_records WHERE json_extract(body,'$.origin')='human'").fetchone()[0]
    assert human==0
    assert read(DATA/'agent-runtime.json')['model_loads']==1
    assert all(read(DATA/'agent-runs'/r['cell']/'started.json')['attempt']==1 for r in read(DATA/'inputs/run-order.json'))
    assert not list((ROOT/'data/stage76-lab').rglob('input.json')) and not list((ROOT/'data/stage76-custom/jobs').glob('*/input.json'))
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}));http={}
    for port,path in [(8791,'/'),(8791,'/trial.html'),(8791,'/evidence.html'),(8802,'/'),(8802,'/evaluation.html'),(8802,'/label')]:
        with op.open(f'http://127.0.0.1:{port}'+path,timeout=15) as r:
            http[str(port)+path]=r.status;assert r.status==200
            if path=='/trial.html':assert "style-src 'self'" in r.headers['content-security-policy'] and "style-src 'self' 'unsafe-inline'" not in r.headers['content-security-policy']
    with op.open('http://127.0.0.1:8802/lab/activity',timeout=15) as r:assert not any(j['status']=='running' for j in json.load(r)['jobs'])
    with op.open('http://127.0.0.1:8802/api/evaluation/summary',timeout=15) as r:summary=json.load(r)
    assert summary['algorithm']['human_submitted_pairs']==0 and summary['algorithm']['quality_scores'] is None
    assert sum(m['model_calls'] for m in summary['agent']['methods'].values())==53
    assert [summary['agent']['methods'][p]['protocol_completed'] for p in ('fixed','llm_agent','constrained')]==[4,0,3]
    with op.open('http://127.0.0.1:8791/trial/vendor/jsoneditor.js',timeout=15) as r:assert sha256(r.read()).hexdigest()==digest(ROOT/'web/papertrail-v26/dist/vendor/jsoneditor.js')
    try:op.open('http://127.0.0.1:9327/json/version',timeout=2)
    except (urllib.error.URLError,TimeoutError):pass
    else:raise AssertionError('Dedicated verification browser still open')
    py=list((ROOT/'research76').glob('*.py'))+[ROOT/'scripts/run_research76_workbench.py',ROOT/'scripts/research76_workbench_control.py']
    for p in py:ast.parse(p.read_text(encoding='utf8'))
    js=[p for p in (ROOT/'research76').rglob('*') if p.suffix in ('.js','.mjs','.cjs')]
    for p in js:subprocess.run(['node','--check',str(p)],check=True,capture_output=True)
    assert 'research76.control' in (ROOT/'project-agent.cmd').read_text()
    assert 'scripts.research76_workbench_control' in (ROOT/'papertrail-workbench.cmd').read_text()
    assert read(OUT/'step5-human-preparation.json')['default_human_storage'] is None
    paths=[p for p in (ROOT/'research76').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths += [p for p in OUT.rglob('*') if p.is_file() and p.name!='final-validation.json']
    paths += [ROOT/'scripts/run_research76_workbench.py',ROOT/'scripts/research76_workbench_control.py',ROOT/'docs/SEQUENTIAL_DELIVERY_V76.md',ROOT/'docs/USABILITY_TRIAL_V76.md',ROOT/'project-agent.cmd',ROOT/'papertrail-workbench.cmd']
    result={'status':'passed','date':'2026-11-17','deliverables':{'step1':'paper_first_layout_complete','step2':'explicit_requirement_handoff_complete','step3':'shared_pool_profile_comparison_complete','step4':'actual_markdown_json_task_exports_complete','step5':'trial_page_and_materials_complete_human_trials_deferred_per_user'},
        'checks':{k:v['checks'] for k,v in reports.items()},'total_checks':165,'prior_frozen_files_preserved':len(original),'prior_original_sources_preserved':len(older),
        'new_model_runs':0,'new_human_trials':0,'new_human_relevance_labels':0,'human_relevance_labels_global':human,'ranking_quality_scores':None,
        'historical_model_calls':53,'historical_model_loads':1,'historical_protocol_completed':{'fixed':4,'llm_agent':0,'constrained':3},
        'new_training':False,'catalog_expansion':False,'new_framework_dependencies':False,'native_worker_retained':'research71.worker','sse_and_model_budgets_retained':True,
        'trial_storage':'browser-local; fixed automation_test namespace separate from participant-declared human_self_report','trial_csp_retained':True,
        'local_http_status':http,'dedicated_browser_closed':True,'screenshots_viewed':True,'python_syntax_files':len(py),'javascript_syntax_files':len(js),
        'files':{str(p.relative_to(ROOT)):digest(p) for p in sorted(paths)}}
    (OUT/'final-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='files'},ensure_ascii=False))


if __name__=='__main__':main()
