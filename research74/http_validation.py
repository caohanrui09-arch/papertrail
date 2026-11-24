"""Read-only source verification and bounded CPU diagnostics; never starts a model."""
import hashlib
import json
from pathlib import Path
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/stage74'


def main():
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    checks=[]

    def check(name, value):
        assert value,name
        checks.append(name)

    def request(path, body=None):
        req=urllib.request.Request('http://127.0.0.1:8802'+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        try:
            with opener.open(req,timeout=45) as response:
                raw=response.read();status=response.status
        except urllib.error.HTTPError as error:
            raw=error.read();status=error.code
        try:return status,json.loads(raw)
        except ValueError:return status,raw.decode('utf8')

    def save(name,value):
        (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')

    check('frozen_10000_catalog',request('/health')[1]['candidates']==10000)
    check('no_running_model_jobs',not any(j['status']=='running' for j in request('/lab/activity')[1]['jobs']))
    for path in ['/','/visuals.js','/visuals.css','/visuals/vendor/d3-path.min.js','/visuals/vendor/d3-shape.min.js','/evaluation.html','/evaluation.js']:
        check('served_'+path,request(path)[0]==200)
    check('vendor_whitelist',request('/visuals/vendor/unknown.js')[0]==404)
    check('task_contexts_versioned',request('/visuals/v74/evaluation/tasks')[1]['version']==74)
    examples=request('/lab/examples')[1]
    save('example-rows.json',{i['id']:i['result']['results'][0] for i in examples['items']})
    fixed=request('/lab/v72/examples/fixed/candidates')[1];save('actual-fixed.json',fixed)
    check('fixed_actual_6_candidates_2_reads_2_cites',len(fixed['papers'])==6 and sum(p['read_success'] for p in fixed['papers'])==2 and sum(p['cited'] for p in fixed['papers'])==2)
    for key in ['english_search','chinese_search','cold_recommend','mixed','no_results']:
        row=request('/lab/v72/retained/'+key)[1];value=request('/lab/v72/retained/'+key+'/candidates')[1]
        save('retained-'+key+'.json',{'record':row,'candidates':value})
        check(key+'_actual_source',value['source']['kind']=='historical_v71' and value['task_id']==row['result']['results'][0]['task_id'])
        if key=='no_results':check('empty_failure_retained',not value['papers'] and not row['result']['results'][0]['completed_protocol'])
    status,value=request('/lab/v72/diagnostics/preset',{'task_id':'evaluation-002'})
    check('shared_pool_diagnostic',status==200);save('rank-diagnostic.json',value)
    a=value['methods']['pool_content'];b=value['methods']['profile_rerank']
    check('full_shared_pool_same_ids',set(p['doc_id'] for p in a)==set(p['doc_id'] for p in b)==set(value['pool_ids']))
    check('full_shared_pool_same_hash',value['method_info']['pool_content']['pool_ids_sha256']==value['method_info']['profile_rerank']['pool_ids_sha256']==value['pool_ids_sha256'])
    check('invalid_diagnostic_rejected',request('/lab/v72/diagnostics/preset',{'task_id':'evaluation-002','k':None})[0]==422)
    evaluation=request('/api/evaluation/summary')[1];save('evaluation-summary.json',evaluation)
    check('frozen_matrix_12_cells',len(evaluation['agent']['rows'])==12)
    for key,n in [('fixed',4),('llm_agent',0),('constrained',3)]:check(key+'_completion_preserved',evaluation['agent']['methods'][key]['protocol_completed']==n)
    check('human_zero_quality_unavailable',evaluation['algorithm']['human_submitted_pairs']==0 and evaluation['algorithm']['quality_scores'] is None)
    for row in evaluation['agent']['rows']:
        value=request('/api/evaluation/agent/'+row['cell'])[1];save('evaluation-'+row['cell']+'.json',value)
        check(row['cell']+'_source_hash',value['source_sha256']==hashlib.sha256((ROOT/'data/stage73-evaluation/agent-runs'/row['cell']/'result.json').read_bytes()).hexdigest())
    before=json.loads((OUT/'before.json').read_text(encoding='utf8'))
    check('all_179_frozen_files_unchanged',len(before)==179 and all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==expected for name,expected in before.items()))
    check('no_new_model_job_inputs',not list((ROOT/'data/stage74-lab').rglob('input.json')) and not list((ROOT/'data/stage74-custom/jobs').glob('*/input.json')))
    save('http-validation.json',{'status':'passed','checks':len(checks),'passed':checks,'new_model_calls':0,'quality_claim':False})
    print(json.dumps({'status':'passed','checks':len(checks)}))


if __name__=='__main__':main()
