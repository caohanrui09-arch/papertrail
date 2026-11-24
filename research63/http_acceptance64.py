"""Real loopback acceptance; no browser or new relevance-quality claim."""
import hashlib,json,time,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8802'
REPORT=ROOT/'reports/stage64'
DATA=ROOT/'data/stage64-http'

def main():
    REPORT.mkdir(exist_ok=True);DATA.mkdir(exist_ok=False)
    cases=[('fixed','evaluation-002'),('constrained','evaluation-000'),('llm_agent','evaluation-001')]
    (DATA/'protocol.json').write_text(json.dumps({'cases':cases,'scope':'transport acceptance using reused tasks, not new comparison/quality test','prior_algorithms_and_budgets_unchanged':True}),encoding='utf8')
    checks=[]
    def check(name,value):
        assert value,name
        checks.append(name)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(path,body=None,headers=None,method=None):
        req=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,method=method,
            headers={'Content-Type':'application/json','Origin':BASE,**(headers or {})})
        try:
            with opener.open(req,timeout=30) as r:raw=r.read();status=r.status;hdr=dict(r.headers)
        except urllib.error.HTTPError as e:raw=e.read();status=e.code;hdr=dict(e.headers)
        try:value=json.loads(raw)
        except ValueError:value=raw.decode()
        return status,value,hdr
    code,health,_=request('/health');check('same_frozen_10000_service',code==200 and health['candidates']==10000)
    check('real_html',request('/')[0]==200 and '执行当前任务' in request('/')[1])
    code,js,_=request('/lab.js');check('real_script_and_explicit_replay',code==200 and 'RECORDED_AGGREGATES' in js)
    code,presets,_=request('/lab/presets');check('three_preset_tasks',code==200 and len(presets['tasks'])==3)
    for path,body in [('/lab/run',{'task_id':'bad'}),('/lab/run',{'policy':'fake'}),('/lab/run',{'extra':True}),('/lab/algorithms',{'task_id':'bad'})]:
        check('reject_invalid_'+str(len(checks)),request(path,body)[0]==422)
    check('cross_origin_rejected',request('/lab/run',{'task_id':'evaluation-000'},headers={'Origin':'https://outside.example'})[0]==403)
    check('cross_site_read_rejected',request('/lab/presets',headers={'Sec-Fetch-Site':'cross-site'})[0]==403)
    check('unknown_job_404',request('/lab/jobs/not-a-job')[0]==404)
    native=json.loads((ROOT/'data/stage63-inprocess-v2/rankings.json').read_text(encoding='utf8'))
    for task in presets['tasks']:
        code,ranking,_=request('/lab/algorithms',{'task_id':task['id']})
        check('five_algorithms_'+task['intent'],code==200 and len(ranking['methods'])==5)
        for method,papers in ranking['methods'].items():
            check(task['intent']+'_'+method+'_rank_and_explanation',
                [p['doc_id'] for p in papers]==[p['doc_id'] for p in native[task['id']][method]] and all('algorithm_evidence' in p for p in papers))
        (DATA/(task['id']+'-ranking.json')).write_text(json.dumps(ranking,ensure_ascii=False),encoding='utf8')
    code,quality,_=request('/lab/quality');check('old_quality_marked_historical',code==200 and 'historical' in quality['scope'])
    tasks=json.loads((ROOT/'data/stage19-unified/benchmark/evaluation-tasks.json').read_text())
    task=tasks[0]
    code,session,_=request('/sessions',{'user_id':task['user_id'],'at':task['at']})
    check('create_session',code==200)
    path='/sessions/'+session['session_id']
    statuses=[request(path+'/tools',{'name':'read_paper','arguments':{'doc_id':'not-returned'}})[0] for _ in range(7)]
    check('six_billed_failures_then_gateway_429',statuses==[400]*6+[429])
    snapshot=request(path)[1];check('no_seventh_execution',len(snapshot['trace'])==snapshot['attempts']==6)
    check('close_session',request(path,method='DELETE')[0]==200)
    outcomes=[]
    for policy,ident in cases:
        code,job,_=request('/lab/run',{'task_id':ident,'policy':policy})
        check(policy+'_job_accepted',code==200)
        check(policy+'_concurrent_job_rejected',request('/lab/run',{'task_id':ident,'policy':'fixed'})[0]==409)
        print(json.dumps({'started':policy,'id':job['id']}),flush=True)
        deadline=time.monotonic()+910
        while time.monotonic()<deadline:
            code,status,_=request('/lab/jobs/'+job['id'])
            if status['status']!='running':break
            time.sleep(2)
        else:raise AssertionError('worker exceeded advertised timeout')
        (DATA/(policy+'-http-result.json')).write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf8')
        check(policy+'_worker_exit_and_result',status['status']=='complete' and status['exit_code']==0 and status['result']['complete'])
        result=status['result']['results'][0];trace=result['trace']['trace'];usage=result['metadata'].get('llm_usage',{})
        check(policy+'_same_budget',len(trace)<=6 and usage.get('calls',0)<=8 and usage.get('input_tokens',0)<=30000 and usage.get('output_tokens',0)<=1280)
        if policy!='fixed':check(policy+'_real_model_steps',usage.get('calls',0)>0 and len(result['metadata']['steps'])>0)
        reads={e['result']['doc_id']:e['result'] for e in trace if e['tool']=='read_paper' and 'error' not in e['result']}
        citations=(result.get('answer') or {}).get('citations',[])
        from gsearch.metadata_fetch import upstream
        from gsearch.paper_identity import arxiv_identity
        documents={r['doc_id']:r for r in json.loads((ROOT/'data/stage13-expansion/documents.json').read_text(encoding='utf8'))}
        for citation in citations:
            row=documents[citation['doc_id']];raw=Path(row['provenance']['raw_path'])
            check(policy+'_original_response_hash_'+str(len(checks)),hashlib.sha256(raw.read_bytes()).hexdigest()==row['provenance']['raw_sha256'])
            original=next(r for r in upstream()._feed.parse(raw.read_bytes()).results if arxiv_identity(r.entry_id)==(citation['doc_id'],1))
            check(policy+'_independent_original_citation_'+str(len(checks)),citation['quote'] in original.summary and reads[citation['doc_id']]['abstract']==original.summary and citation['version_key']==row['version_key'] and citation['source_url']==row['source_url'])
        if policy in ('fixed','constrained'):check(policy+'_required_acceptance_task_completed',result['completed_protocol'] and bool(citations))
        outcomes.append({'policy':policy,'completed_protocol':result['completed_protocol'],'seconds':result['seconds'],'citations':len(citations),'usage':usage,'failed_executions':sum('error' in e['result'] for e in trace)})
        print(json.dumps(outcomes[-1]),flush=True)
    report={'status':'passed','date':'2026-11-14','checks':checks,'passed':len(checks),'health':health,'outcomes':outcomes,'scope':'live HTTP transport and real local model execution; raw outputs private; browser not checked; reused tasks not independent quality evaluation'}
    (REPORT/'http-validation.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps({'status':'passed','checks':len(checks)}),flush=True)

if __name__=='__main__':main()
