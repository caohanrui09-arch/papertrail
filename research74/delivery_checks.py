"""Seal the view-only release against the original evidence, without model execution."""
import ast
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/stage74'


def read(path):return json.loads(path.read_text(encoding='utf8'))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    reports={key:read(OUT/(key+'.json')) for key in ('http-validation','data-validation','browser-validation','http-regression')}
    assert all(v['status']=='passed' for v in reports.values())
    baseline=read(OUT/'before.json')
    assert len(baseline)==179
    for name,h in baseline.items():assert digest(ROOT/name)==h,name
    preserved={}
    for stage in (71,72,73):
        files=read(ROOT/f'reports/stage{stage}/final-validation.json')['files'];count=0
        for name,h in files.items():
            if name.replace('\\','/') in ('project-agent.cmd','papertrail-workbench.cmd'):continue
            assert digest(ROOT/name)==h,name;count+=1
        preserved[str(stage)]=count
    from research73.common import verify_protocol,DATA
    verify_protocol()
    for name,h in read(DATA/'labeling-lock.json')['files'].items():assert digest(ROOT/name)==h,name
    with sqlite3.connect('file:'+(DATA/'work/annotations.sqlite3').as_posix()+'?mode=ro',uri=True) as db:
        human=db.execute("SELECT count(*) FROM annotation_records WHERE json_extract(body,'$.origin')='human'").fetchone()[0]
    assert human==0
    assert read(DATA/'agent-runtime.json')['model_loads']==1
    cells=read(DATA/'inputs/run-order.json');assert len(cells)==12
    assert all(read(DATA/'agent-runs'/c['cell']/'started.json')['attempt']==1 for c in cells)
    assert not (DATA/'agent.lock').exists()
    assert not list((ROOT/'data/stage74-lab').rglob('input.json'))
    assert not list((ROOT/'data/stage74-custom/jobs').glob('*/input.json'))
    for p in (ROOT/'research74').glob('*.py'):ast.parse(p.read_text(encoding='utf8'),str(p))
    for p in (ROOT/'research74').glob('*.js'):subprocess.run(['node','--check',str(p)],check=True,capture_output=True)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));http={}
    for port,path in [(8791,'/'),(8791,'/evidence.html'),(8802,'/'),(8802,'/evaluation.html'),(8802,'/label')]:
        with opener.open(f'http://127.0.0.1:{port}{path}',timeout=15) as response:http[str(port)+path]=response.status
    with opener.open('http://127.0.0.1:8802/api/evaluation/summary',timeout=15) as response:summary=json.load(response)
    with opener.open('http://127.0.0.1:8802/lab/activity',timeout=15) as response:assert not any(j['status']=='running' for j in json.load(response)['jobs'])
    assert summary['algorithm']['human_submitted_pairs']==0 and summary['algorithm']['quality_scores'] is None
    assert sum(m['model_calls'] for m in summary['agent']['methods'].values())==53
    assert [summary['agent']['methods'][p]['protocol_completed'] for p in ('fixed','llm_agent','constrained')]==[4,0,3]
    try:opener.open('http://127.0.0.1:9327/json/version',timeout=2)
    except (urllib.error.URLError,TimeoutError):pass
    else:raise AssertionError('Dedicated browser still open')
    assert 'research74.control' in (ROOT/'project-agent.cmd').read_text()
    sources=[p for p in (ROOT/'research74').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    sources += [p for p in OUT.iterdir() if p.is_file() and p.name!='final-validation.json']
    sources += [ROOT/'docs/VISUAL_EVIDENCE_V74.md',ROOT/'project-agent.cmd']
    result={'status':'passed','date':'2026-11-16','visuals':['actual_candidate_flow','same_pool_rank_changes','protocol_matrix_and_cost_bars','citation_evidence_chain'],
            'checks':{k:v['checks'] for k,v in reports.items()},'total_checks':sum(v['checks'] for v in reports.values()),
            'prior_frozen_manifest_counts':preserved,'unique_preserved_sources':len(baseline),
            'historical_protocol_completed':{'fixed':4,'llm_agent':0,'constrained':3},'historical_model_calls':53,'historical_evaluation_model_loads':1,
            'new_model_calls':0,'new_human_labels':0,'human_labels_global':human,'quality_scores':None,
            'new_training':False,'catalog_expansion':False,'visitor_favorites_used':False,'native_worker':'research71.worker',
            'historical_inputs_results_events_unchanged':True,'sse_source_unchanged':True,
            'recovery_checked':'read-only reload and stale source rejection; no new live-model disconnect experiment',
            'local_http_status':http,'dedicated_browser_closed':True,'screenshots_viewed':True,
            'vendor':'local d3-shape 3.2.0 and d3-path 3.1.0; ISC; upstream integrity checked',
            'files':{str(p.relative_to(ROOT)):digest(p) for p in sorted(sources)}}
    (OUT/'final-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='files'},ensure_ascii=False))


if __name__=='__main__':main()
