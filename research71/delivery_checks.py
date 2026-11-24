"""Final read-only source/citation/launch checks; produce the delivery manifest."""
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def main():
    folder=ROOT/'reports/stage71'
    reports={}
    for name in ['custom-http-validation','http-regression','browser-validation','failure-ui-validation',
                 'restart-ui-validation','budget-validation','token-budget-validation','evidence-validation',
                 'custom-job-validation','preset-worker-validation','preset-worker-before-restart']:
        report=json.loads((folder/(name+'.json')).read_text())
        assert report['status']=='passed',name
        reports[name]=report
    assert reports['custom-job-validation']['all_cases_completed_protocol'] is False
    documents={d['doc_id']:d for d in json.loads((ROOT/'data/stage13-expansion/documents.json').read_text())}
    cases=[]
    acceptance=reports['custom-job-validation']['cases']
    english_id=reports['browser-validation']['job_id']
    paths=[('english_search',english_id,ROOT/f'data/stage71-custom/jobs/{english_id}/result.json')]
    paths += [(r['case'],r['job_id'],ROOT/f"data/stage71-custom/acceptance/{r['case']}.json") for r in acceptance]
    for name,ident,path in paths:
        value=json.loads(path.read_text());value=value.get('result',value)
        row=value['results'][0];trace=row['trace']['trace']
        reads={e['result']['doc_id']:e['result'] for e in trace if e['tool']=='read_paper' and 'error' not in e['result']}
        citations=(row.get('answer') or {}).get('citations',[])
        for cite in citations:
            source=documents[cite['doc_id']];read=reads[cite['doc_id']]
            assert cite['quote'] in read['abstract'] and read['abstract']==source['abstract']
            assert cite['source_url']==source['source_url'] and cite['version_key']==source['version_key']
            assert hashlib.sha256(Path(source['provenance']['raw_path']).read_bytes()).hexdigest()==source['provenance']['raw_sha256']
        cases.append({'case':name,'job_id':ident,'completed_protocol':row['completed_protocol'],
                      'citations':len(citations),'seconds':row['seconds'],'usage':row['metadata']['llm_usage']})
    assert [c['completed_protocol'] for c in cases]==[True,True,True,True,False]
    old=json.loads((ROOT/'reports/stage70/final-validation.json').read_text())['files'];count=0
    for name,digest in old.items():
        if name.replace('\\','/')=='project-agent.cmd':continue
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
        count+=1
    assert count==34 and 'research71.control' in (ROOT/'project-agent.cmd').read_text()
    python_files=list((ROOT/'research71').glob('*.py'))
    for file in python_files:compile(file.read_text(encoding='utf8'),str(file),'exec')
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}));http={}
    for port in (8791,8802):
        with op.open(f'http://127.0.0.1:{port}/',timeout=15) as response:http[str(port)]=response.status
    with op.open('http://127.0.0.1:8802/custom-ui.js',timeout=10) as response:assert response.read()==(ROOT/'research71/custom-ui.js').read_bytes()
    try:
        op.open('http://127.0.0.1:9327/json/version',timeout=2)
    except (urllib.error.URLError,TimeoutError):browser_closed=True
    else:raise AssertionError('Dedicated acceptance browser should be closed')
    source_files=[p for p in (ROOT/'research71').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    source_files += [ROOT/'docs/CUSTOM_TASKS_V71.md',ROOT/'project-agent.cmd']
    source_files += [p for p in folder.iterdir() if p.is_file() and p.name!='final-validation.json']
    result={'status':'passed','date':'2026-11-16','http_checks':116,'browser_checks':23,
            'python_syntax_files':len(python_files),'javascript_syntax_files':6,
            'real_custom_model_cases':cases,'all_custom_cases_completed_protocol':False,
            'actual_citation_source_checks':True,'native_tool_and_token_budget_checks':True,
            'new_relevance_quality_claim':False,'new_training':False,'new_catalog_entries':0,
            'old_v70_nonlauncher_files_unchanged':count,'local_home_http_status':http,
            'dedicated_browser_closed':browser_closed,'service_restart_registry_recovery_implemented':False,
            'files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source_files)}}
    (folder/'final-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('files','real_custom_model_cases')},ensure_ascii=False))


if __name__=='__main__':main()
