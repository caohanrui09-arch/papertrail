"""Live API/record integrity tests. Automated labeling uses verification namespace only."""
import http.cookiejar
import json
from pathlib import Path
import urllib.error
import urllib.request

from research73.common import ROOT,DATA,read,digest,verify_protocol,value_hash


def main():
    verify_protocol();checks=[];jar=http.cookiejar.CookieJar()
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(jar))
    def api(path,body=None,method=None,headers=None):
        req=urllib.request.Request('http://127.0.0.1:8802'+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers={'Content-Type':'application/json','X-Papertrail-Verification':'1',**(headers or {})})
        try:
            with op.open(req,timeout=30) as response:
                raw=response.read()
                try:return response.status,json.loads(raw)
                except ValueError:return response.status,raw.decode('utf8')
        except urllib.error.HTTPError as error:return error.code,json.load(error)
    def check(name,value):assert value,name;checks.append(name)
    code,summary=api('/api/evaluation/summary');check('12_cells_finished',code==200 and summary['agent']['finished']==12)
    check('pending_quality_zero_human',summary['algorithm']['human_submitted_pairs']==0 and summary['algorithm']['quality_scores'] is None)
    check('frozen_source_counts',summary['materials']['queries']==26 and summary['materials']['pairs']==406 and summary['materials']['sources']=={'reused_assistant_drafts':24,'user_authored_need':1,'synthetic_empty_control':1})
    methods=summary['agent']['methods'];check('all_outcomes_preserved',[methods[p]['protocol_completed'] for p in ('fixed','llm_agent','constrained')]==[4,0,3])
    check('fixed_zero_model',methods['fixed']['model_calls']==methods['fixed']['input_tokens']==methods['fixed']['output_tokens']==0)
    check('accepted_sources_only',all(v['citation_source_checks_passed']==v['citation_checks_total'] for v in methods.values()))
    check('no_semantic_quality_claim',summary['agent']['semantic_quality_claim'] is False and summary['agent']['pure_scheduling_gain_claim'] is False)
    tasks=read(DATA/'inputs/agent-tasks.json');order=read(DATA/'inputs/run-order.json')
    for cell in order:
        base=DATA/'agent-runs'/cell['cell'];started=read(base/'started.json');row=read(base/'result.json');task=tasks[cell['task_index']]
        check(cell['cell']+'_identical_task_once',started['task']==task and started['attempt']==1)
        usage=row.get('metadata',{}).get('llm_usage',{});trace=row['trace']['trace']
        check(cell['cell']+'_budgets',len(trace)<=6 and usage.get('calls',0)<=8 and usage.get('input_tokens',0)<=30000 and usage.get('output_tokens',0)<=1280 and row['wall_seconds']<900)
        check(cell['cell']+'_exact_query',all(e['arguments']['query']==task['query'] for e in trace if e['tool']=='search_papers'))
        _,public=api('/api/evaluation/agent/'+cell['cell'])
        check(cell['cell']+'_private_messages_removed','unverified_model_final' not in public['result']['metadata'] and all('model_input_messages' not in s and 'model_output' not in s for s in public['result']['metadata'].get('steps',[])))
    check('model_loaded_once',summary['agent']['runtime']['model_loads']==1)
    check('different_exposure_flagged',any(r['same_unique_document_set'] is False for r in summary['agent']['candidate_exposure_differences']))
    _,workspace=api('/api/annotation/workspace');check('blind_26_materials',workspace['total_queries']==26 and workspace['total_pairs']==406 and workspace['verification'] is True)
    pool=read(DATA/'blind/tasks.json');mapping=read(DATA/'private/pool-map.json')
    for qid,task in pool.items():
        _,detail=api('/api/annotation/queries/'+qid)
        check(qid+'_no_candidate_method_leak',all(set(c)=={'annotation_id','paper','record','valid_submission'} and not any(k in c['paper'] for k in ('methods','rank','score','algorithm_evidence')) for c in detail['candidates']))
        check(qid+'_original_versions',all(c['paper']['source_verified'] and c['paper']['version']==1 and c['paper']['abstract'] for c in detail['candidates']))
        ids=[c['paper']['doc_id'] for c in task['candidates']]
        check(qid+'_dedup_random_order',len(ids)==len(set(ids)) and ids==sorted(ids,key=lambda d:value_hash(['blind73-v1',qid,d])))
    qid=next(q for q in pool if pool[q]['candidates']);_,detail=api('/api/annotation/queries/'+qid);aid=detail['candidates'][0]['annotation_id']
    grade={'revision':0,'operation':'submit','grade':1,'reviewer':'automated verification','rationale':'synthetic acceptance record; never human evidence','attest':True}
    check('judgment_locked_before_review',api('/api/annotation/judgments/'+qid+'/'+aid,grade,'PUT')[0]==422)
    review={'revision':0,'operation':'draft','decision':'approve','reviewer':'automated verification','note':'fixture only','attest':False}
    code,saved=api('/api/annotation/reviews/'+qid,review,'PUT');check('review_draft_saved',code==200 and saved['revision']==1)
    _,again=api('/api/annotation/queries/'+qid);check('draft_resume',again['review']['value']['status']=='draft')
    review.update(revision=1,operation='submit',attest=True);code,saved=api('/api/annotation/reviews/'+qid,review,'PUT');check('review_automation_source',code==200 and saved['value']['origin']=='automation_test')
    grade.update(operation='draft',attest=False);code,saved=api('/api/annotation/judgments/'+qid+'/'+aid,grade,'PUT');check('judgment_draft_saved',code==200 and saved['revision']==1)
    grade.update(revision=1,operation='submit',attest=True);code,saved=api('/api/annotation/judgments/'+qid+'/'+aid,grade,'PUT');check('judgment_automation_not_human',code==200 and saved['value']['origin']=='automation_test')
    check('stale_revision_rejected',api('/api/annotation/judgments/'+qid+'/'+aid,grade,'PUT')[0]==409)
    grade.update(revision=2,grade=None);check('null_grade_submit_rejected',api('/api/annotation/judgments/'+qid+'/'+aid,grade,'PUT')[0]==422)
    grade['grade']=True;check('boolean_grade_rejected',api('/api/annotation/judgments/'+qid+'/'+aid,grade,'PUT')[0]==422)
    review['revision']=2;api('/api/annotation/reviews/'+qid,review,'PUT');_,again=api('/api/annotation/queries/'+qid)
    check('new_review_invalidates_previous_judgment',again['candidates'][0]['valid_submission'] is False)
    _,history=api('/api/annotation/history/'+qid+'/review/_');check('revision_history_retained',len(history)==3)
    _,native=api('/api/annotation/export');check('export_keeps_automation_origin',native['verification'] and native['queries'][0]['review']['value']['origin']=='automation_test')
    code,studio=api('/api/annotation/export?format=label-studio');check('label_studio_native_structure',code==200 and len(studio)==406 and all(set(t)=={'data','annotations'} for t in studio))
    _,after=api('/api/evaluation/summary');check('automation_does_not_create_quality',after['algorithm']['human_submitted_pairs']==0 and after['algorithm']['quality_scores'] is None)
    for path in ('/api/evaluation/agent/unknown','/api/annotation/queries/not-a-query'):
        check('unknown_'+path,api(path)[0] in (404,422))
    check('cross_origin_write_rejected',api('/api/annotation/reviews/'+qid,review,'PUT',{'Origin':'https://other.example'})[0]==403)
    check('auxiliary_separate_empty',read(DATA/'auxiliary/model-judgments.json')==[])
    from gsearch.human_quality import native_scores
    qrels={'synthetic-metric-fixture':{'a':2,'b':0}}
    a=native_scores(qrels,{'synthetic-metric-fixture':['a','b']});b=native_scores(qrels,{'synthetic-metric-fixture':['b','a']})
    check('native_metric_synthetic_order_fixture',a['pooled_ndcg_at10']==a['pooled_mrr_at10']==1 and b['pooled_ndcg_at10']<1 and b['pooled_mrr_at10']==.5)
    result={'status':'passed','checks':len(checks),'passed':checks,'automated_records_namespace_only':True,'real_human_labels_added':0,'model_jobs_started':0,'metric_fixture_is_synthetic_not_human':True}
    write=__import__('research73.common',fromlist=['write']).write
    write(ROOT/'reports/stage73/http-validation.json',result);print(json.dumps({'status':'passed','checks':len(checks),'model_jobs_started':0,'human_labels_added':0}))


if __name__=='__main__':main()
