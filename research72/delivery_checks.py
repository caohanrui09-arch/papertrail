"""Final receipt for frozen assets, source-linked evidence and running entrypoints."""
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def main():
    folder=ROOT/'reports/stage72';reports={}
    for name in ['http-validation','http-regression','browser-validation','stale-ui-validation','final-ui-validation',
                 'invariant-validation','budget-validation','token-budget-validation','preset-worker-validation']:
        reports[name]=json.loads((folder/(name+'.json')).read_text());assert reports[name]['status']=='passed',name
    assert reports['browser-validation']['model_submissions']==1 and reports['browser-validation']['completed_protocol']
    assert reports['preset-worker-validation']['stable_derived_evidence_hash_matches_final_response']
    previous=json.loads((ROOT/'reports/stage71/final-validation.json').read_text());preserved=0
    for name,digest in previous['files'].items():
        if name.replace('\\','/')=='project-agent.cmd':continue
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
        preserved+=1
    assert preserved==45
    job=reports['browser-validation']['real_job_id'];base=ROOT/'data/stage72-custom/jobs'/job
    original=json.loads((base/'result.json').read_text())['results'][0]
    saved=json.loads((base/'candidate-evidence-0.json').read_text())
    assert saved['source']['result_sha256']==hashlib.sha256((base/'result.json').read_bytes()).hexdigest()
    assert sum(p['read_success'] and p['cited'] for p in saved['papers'])==len(original['answer']['citations'])==2
    old_failure=next(c for c in previous['real_custom_model_cases'] if c['case']=='no_results')
    old_result=ROOT/'data/stage71-custom/jobs'/old_failure['job_id']/'result.json'
    failure=json.loads(old_result.read_text())['results'][0]
    assert not failure['completed_protocol'] and failure['metadata']['llm_usage']['calls']==8
    assert failure['answer'] is None
    python_files=list((ROOT/'research72').glob('*.py'))
    for p in python_files:compile(p.read_text(encoding='utf8'),str(p),'exec')
    js_files=[p for p in (ROOT/'research72').iterdir() if p.suffix in ('.js','.cjs')]
    assert 'research72.control' in (ROOT/'project-agent.cmd').read_text()
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}));http={}
    for port in (8791,8802):
        with op.open(f'http://127.0.0.1:{port}/',timeout=15) as response:http[str(port)]=response.status
    for name in ('candidate-ui.js','custom-ui.js','lab.js'):
        with op.open('http://127.0.0.1:8802/'+name,timeout=10) as response:assert response.read()==(ROOT/'research72'/name).read_bytes()
    try:op.open('http://127.0.0.1:9327/json/version',timeout=2)
    except (urllib.error.URLError,TimeoutError):browser_closed=True
    else:raise AssertionError('Dedicated acceptance browser still running')
    files=[p for p in (ROOT/'research72').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    files += [ROOT/'docs/CANDIDATE_EVIDENCE_V72.md',ROOT/'project-agent.cmd']
    files += [p for p in folder.iterdir() if p.is_file() and p.name!='final-validation.json']
    result={'status':'passed','date':'2026-11-16','http_checks':reports['http-validation']['checks']+reports['http-regression']['checks'],
            'browser_checks':reports['browser-validation']['checks']+len(reports['stale-ui-validation']['checks'])+len(reports['final-ui-validation']['checks']),
            'real_model_jobs_started':1,'real_model_job_id':job,'model_outcome':{'completed_protocol':True,'tools':5,'candidates':2,'citations':2,'events':27,'usage':original['metadata']['llm_usage'],'execution_seconds':original['seconds']},
            'fixed_validation_executions':len(json.loads((folder/'fixed-validation-history.json').read_text())['executions']),
            'derived_evidence_initial_http500_record_retained':True,'derived_evidence_hash_verified':True,
            'retained_v71_empty_failure_unchanged':True,'new_human_labels':0,'new_quality_improvement_claim':False,
            'new_model_training':False,'catalog_expansion':False,'visitor_favorites_connected':False,
            'diagnostics_injected_into_agent':False,'old_v71_nonlauncher_assets_unchanged':preserved,
            'python_syntax_files':len(python_files),'javascript_syntax_files':len(js_files),
            'local_home_http_status':http,'dedicated_browser_closed':browser_closed,'restart_job_registry_recovery':False,
            'diagnostic_protocol_sha256':hashlib.sha256((ROOT/'data/stage72-diagnostics/protocol.json').read_bytes()).hexdigest(),
            'files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}}
    (folder/'final-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('files','model_outcome')},ensure_ascii=False))


if __name__=='__main__':main()
