"""Frozen diagnostic cases and source checks; starts zero model jobs."""
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def main():
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}));checks=[];outputs=[]
    base=ROOT/'data/stage72-acceptance';base.mkdir(exist_ok=False)
    cases=[
        ('english','Find Efficient Geometry-aware 3D Generative Adversarial Networks','profile-a','Efficient Geometry-aware 3D Generative Adversarial Networks','search'),
        ('chinese','帮我找几何感知3D生成的论文，并引用原摘要','profile-a','Efficient Geometry-aware 3D Generative Adversarial Networks','search'),
        ('topic_a','Find multimodal reasoning papers','profile-a','multimodal reasoning','search'),
        ('topic_b','找多模态推理论文','profile-b','multimodal reasoning','search'),
        ('cold','Find multimodal reasoning papers','cold','multimodal reasoning','search'),
        ('empty','qzxpapertrailnevermatches72','cold','qzxpapertrailnevermatches72','search'),
        ('recommend','根据所选画像推荐未读论文','cold','','recommend')]
    (base/'cases-before-evaluation.json').write_text(json.dumps({'cases':cases,'scope':'integration/rank changes, no human labels','protocol':'data/stage72-diagnostics/protocol.json'},ensure_ascii=False,indent=2),encoding='utf8')
    def api(path,body=None,headers=None):
        req=urllib.request.Request('http://127.0.0.1:8802'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json',**(headers or {})})
        try:
            with op.open(req,timeout=40) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as error:return error.code,json.load(error)
    def check(name,value):assert value,name;checks.append(name)
    before=api('/lab/activity')[1]
    for name,original,profile,query,intent in cases:
        code,plan=api('/lab/custom/plan',{'original_need':original,'profile_id':profile,'intent':intent})
        check(name+'_plan',code==200)
        body={'plan_id':plan['id'],'executed_query':query,'reviewed':True,'conditions_reviewed':True}
        code,result=api('/lab/v72/diagnostics/custom',body)
        check(name+'_independent_bound_snapshot',code==200 and result['kind']=='independent_algorithm_diagnostic' and result['agent_tools_changed'] is False and result['query']==query and result['context']['original_need']==original and result['as_of']==plan['scope']['at'])
        if not query:check(name+'_no_hidden_search',not result['methods']);continue
        ids=lambda method:[p['doc_id'] for p in result['methods'][method]]
        pool=set(result['pool_ids'])
        check(name+'_shared_pool_exact',set(ids('pool_content'))==set(ids('profile_rerank'))==pool==set(ids('bm25'))|set(ids('content_query')))
        check(name+'_positive_content_only',all(p['query_cosine']>0 for p in result['methods']['content_query']))
        check(name+'_separate_native_scores',all(p['score'] is None for p in result['methods']['profile_rerank']))
        check(name+'_shared_pool_hash',result['method_info']['pool_content']['pool_ids_sha256']==result['method_info']['profile_rerank']['pool_ids_sha256'])
        if result['cold_profile']:check(name+'_cold_query_fallback',ids('pool_content')==ids('profile_rerank') and all(p['profile_cosine'] is None for p in result['methods']['profile_rerank']))
        elif pool:
            rows=result['methods']['pool_content'];q=sorted(rows,key=lambda p:(-p['query_cosine'],p['doc_id']));h=sorted(rows,key=lambda p:(-p['profile_cosine'],p['doc_id']))
            qr={p['doc_id']:i+1 for i,p in enumerate(q)};hr={p['doc_id']:i+1 for i,p in enumerate(h)}
            expected=sorted(pool,key=lambda d:(-(.25/(60+hr[d])+.75/(60+qr[d])),d))
            check(name+'_native_rrf_rank_matches_independent_formula',ids('profile_rerank')==expected)
        if name=='empty':check('zero_query_no_placeholder_candidates',all(not v for v in result['methods'].values()) and result['query_nonzero_features']==0)
        if name=='english':
            _,actual=api('/lab/v72/retained/english_search/candidates')
            original_rows=sorted([o for p in actual['papers'] for o in p['occurrences'] if o['tool']=='search_papers'],key=lambda o:o['rank'])
            check('native_bm25_scores_retained_exact',all(a['native_score']==b['score'] and a['source_paper']['doc_id']==b['doc_id'] for a,b in zip(original_rows,result['methods']['bm25'])))
        (base/(name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        outputs.append({'case':name,'id':result['id'],'seconds':result['seconds'],'overlap':result['recall_overlap'],'top10':{m:ids(m)[:10] for m in result['methods']}})
    by_name={x['case']:x for x in outputs}
    check('same_confirmed_query_chinese_english_same_order',by_name['english']['top10']==by_name['chinese']['top10'])
    a=json.loads((base/'topic_a.json').read_text());b=json.loads((base/'topic_b.json').read_text())
    check('profile_change_different_seen_mask',a['eligible_ids_sha256']!=b['eligible_ids_sha256'])
    _,plan=api('/lab/custom/plan',{'original_need':'constraint validation'})
    good={'plan_id':plan['id'],'executed_query':'test','reviewed':True,'conditions_reviewed':True}
    invalid=[{**good,'reviewed':False},{**good,'conditions_reviewed':False},{**good,'reviewed':'true'},
             {**good,'executed_query':None},{**good,'executed_query':''},{**good,'executed_query':'a\nb'},
             {**good,'user_id':'any'},{**good,'at':'2026-11-16'},{**good,'method':'override'},
             {**good,'policy':'fixed'},{**good,'plan_id':'x'*36}]
    for i,body in enumerate(invalid):check('invalid_diagnostic_'+str(i),api('/lab/v72/diagnostics/custom',body)[0] in (404,422))
    check('cross_origin_diagnostic_denied',api('/lab/v72/diagnostics/custom',good,{'Origin':'https://other.example'})[0]==403)
    for path in ('/lab/v72/jobs/not-known/candidates','/lab/v72/retained/not-known','/lab/v72/examples/not-known/candidates'):
        check('unknown_source_'+path,api(path)[0]==404)
    retained=json.loads((ROOT/'reports/stage71/final-validation.json').read_text())['real_custom_model_cases']
    for item in retained:
        name=item['case'];code,view=api('/lab/v72/retained/'+name+'/candidates');raw=json.loads((ROOT/f"data/stage71-custom/jobs/{item['job_id']}/result.json").read_text())['results'][0]
        trace=raw['trace']['trace'];returned={p['doc_id'] for e in trace if e['tool'] in ('search_papers','recommend_papers') and not e['result'].get('error') for p in e['result']['papers']}
        read={e['result']['doc_id'] for e in trace if e['tool']=='read_paper' and not e['result'].get('error')};cited={p['doc_id'] for p in (raw.get('answer') or {}).get('citations',[])}
        check(name+'_actual_candidate_set_exact',code==200 and {p['doc_id'] for p in view['papers']}==returned)
        check(name+'_read_cite_states_exact',{p['doc_id'] for p in view['papers'] if p['read_success']}==read and {p['doc_id'] for p in view['papers'] if p['cited']}==cited)
        for paper in view['papers']:
            for origin in paper['occurrences']:
                entry=next(e for e in trace if e['attempt']==origin['attempt']);check(name+'_rank_'+paper['doc_id'],entry['result']['papers'][origin['rank']-1]==origin['source_paper'])
                if origin['tool']=='search_papers':check(name+'_native_explain_score',abs(origin['native_score']-origin['evidence']['native_bm25_score'])<1e-12)
        code,public=api('/lab/v72/retained/'+name)
        check(name+'_private_model_messages_not_exposed',code==200 and all('unverified_model_final' not in r['metadata'] and all('model_input_messages' not in s and 'model_output' not in s for s in r['metadata']['steps']) for r in public['result']['results']))
        if name=='no_results':check('frozen_v71_empty_failure_retained',not raw['completed_protocol'] and raw['metadata']['llm_usage']['calls']==8 and raw['metadata']['charged_application_attempts']==6 and not view['papers'])
    check('no_model_jobs_started',before==api('/lab/activity')[1])
    report={'status':'passed','checks':len(checks),'passed':checks,'diagnostics':outputs,'model_jobs_started':0,'human_labels':0,'new_quality_claim':False}
    (ROOT/'reports/stage72/http-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps({'status':'passed','checks':len(checks),'diagnostic_cases':len(cases),'model_jobs_started':0}))


if __name__=='__main__':main()
