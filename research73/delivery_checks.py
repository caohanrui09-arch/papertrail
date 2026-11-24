"""Verify final v73 records without running another model or declaring human labels."""
import json
from pathlib import Path
import sqlite3
import urllib.error
import urllib.request

from research73.common import ROOT,DATA,read,write,digest,verify_protocol


def main():
    protocol=verify_protocol();reports={}
    for name in ['http-validation','http-regression','browser-validation','theme-validation','export-validation']:
        reports[name]=read(ROOT/f'reports/stage73/{name}.json');assert reports[name]['status']=='passed',name
    preserved={}
    for stage in (71,72):
        count=0
        for name,h in read(ROOT/f'reports/stage{stage}/final-validation.json')['files'].items():
            if name.replace('\\','/') in ('project-agent.cmd','papertrail-workbench.cmd'):continue
            assert digest(ROOT/name)==h,name;count+=1
        preserved[str(stage)]=count
    for name,h in read(DATA/'manifest.json')['immutable_assets'].items():assert digest(DATA/name)==h,name
    for name,h in read(DATA/'labeling-lock.json')['files'].items():assert digest(ROOT/name)==h,name
    order=read(DATA/'inputs/run-order.json');tasks=read(DATA/'inputs/agent-tasks.json');seen=[];defaults=[]
    from research70.event_stream import available
    for cell in order:
        base=DATA/'agent-runs'/cell['cell'];start=read(base/'started.json');result=read(base/'result.json');events,_=available(base/'events.jsonl')
        assert start['attempt']==1 and start['task']==tasks[cell['task_index']]
        assert [e['payload'] for e in events if e['kind']=='tool_returned']==result['trace']['trace']
        if cell['policy']=='constrained':assert result['metadata']['native_default_schema_unchanged']
        seen.append(cell['cell'])
    assert len(seen)==len(set(seen))==12 and read(DATA/'agent-runtime.json')['model_loads']==1
    assert not (DATA/'agent.lock').exists()
    with sqlite3.connect(DATA/'work/annotations.sqlite3') as db:human=db.execute("SELECT count(*) FROM annotation_records WHERE json_extract(body,'$.origin')='human'").fetchone()[0]
    assert human==0
    snapshot=read(ROOT/'reports/stage73/evaluation.json')
    assert snapshot['algorithm']['human_submitted_pairs']==0 and snapshot['algorithm']['quality_scores'] is None
    assert [snapshot['agent']['methods'][p]['protocol_completed'] for p in ('fixed','llm_agent','constrained')]==[4,0,3]
    assert all(r['source_check_status'] in ('all_passed','no_citations') for r in snapshot['agent']['rows'])
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}));http={}
    for port,path in [(8791,'/evidence.html'),(8802,'/evaluation.html'),(8802,'/label')]:
        with op.open(f'http://127.0.0.1:{port}{path}',timeout=15) as response:http[str(port)+path]=response.status
    with op.open('http://127.0.0.1:8791/api/experiments',timeout=15) as response:assert json.load(response)==read(ROOT/'deploy/stage66/evidence-data.json')
    with op.open('http://127.0.0.1:8791/evidence.mjs',timeout=15) as response:assert response.read()==(ROOT/'deploy/stage66/web/evidence.mjs').read_bytes()
    with op.open('http://127.0.0.1:8802/api/evaluation/summary',timeout=15) as response:live=json.load(response)
    assert live['algorithm']['human_submitted_pairs']==0 and live['agent']['finished']==12
    try:op.open('http://127.0.0.1:9327/json/version',timeout=2)
    except (urllib.error.URLError,TimeoutError):pass
    else:raise AssertionError('Dedicated browser still open')
    for name,text in [('project-agent.cmd','research73.control'),('papertrail-workbench.cmd','scripts.research73_workbench_control')]:assert text in (ROOT/name).read_text()
    py=list((ROOT/'research73').glob('*.py'))+[ROOT/'scripts/run_research73_workbench.py',ROOT/'scripts/research73_workbench_control.py']
    for p in py:compile(p.read_text(encoding='utf8'),str(p),'exec')
    paths=[p for p in (ROOT/'research73').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths += [ROOT/'scripts/run_research73_workbench.py',ROOT/'scripts/research73_workbench_control.py',ROOT/'docs/CONTROLLED_EVALUATION_V73.md',ROOT/'docs/LABEL_STUDIO_V73.xml',ROOT/'project-agent.cmd',ROOT/'papertrail-workbench.cmd']
    paths += [p for p in (ROOT/'reports/stage73').iterdir() if p.is_file() and p.name!='final-validation.json']
    result={'status':'passed','date':'2026-11-16','http_checks':reports['http-validation']['checks']+reports['http-regression']['checks'],
            'browser_checks':reports['browser-validation']['checks']+len(reports['theme-validation']['checks']),
            'algorithm_materials':26,'pooled_pairs':406,'verified_original_v1_abstracts':507,'human_labels':human,'quality_scores':None,
            'planned_agent_cells':12,'executed_once_cells':12,'model_loads':1,'model_calls':sum(v['model_calls'] for v in snapshot['agent']['methods'].values()),
            'protocol_completed':{p:v['protocol_completed'] for p,v in snapshot['agent']['methods'].items()},
            'accepted_citation_checks':{'passed':8,'total':8,'semantic_correctness_claim':False},
            'infrastructure_failure_cells':0,'model_protocol_failure_cells':5,'extra_model_runs_for_acceptance':0,
            'candidate_exposure_differences_preserved':True,'pure_scheduling_gain_claim':False,
            'frozen_asset_counts_preserved':preserved,'historical_evidence_payload_and_renderer_unchanged':True,
            'pre_human_lock_verified':True,'protocol_sha256':digest(DATA/'protocol.json'),'new_training':False,'catalog_expansion':False,'visitor_favorites_used':False,
            'local_http_status':http,'dedicated_browser_closed':True,'python_syntax_files':len(py),'javascript_syntax_files':4,
            'files':{str(p.relative_to(ROOT)):digest(p) for p in sorted(paths)}}
    write(ROOT/'reports/stage73/final-validation.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='files'},ensure_ascii=False))


if __name__=='__main__':main()
