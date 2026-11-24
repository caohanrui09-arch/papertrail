"""Custom input, identity/scope and confirmation checks; never starts model jobs."""
import json
from pathlib import Path
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8802'


def main():
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}));checks=[]
    def request(path,body=None,headers=None):
        req=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json',**(headers or {})})
        try:
            with op.open(req,timeout=20) as response:raw=response.read();code=response.status
        except urllib.error.HTTPError as error:raw=error.read();code=error.code
        try:return code,json.loads(raw)
        except ValueError:return code,raw.decode('utf8')
    def check(name,condition):
        assert condition,name
        checks.append(name)
    _,before=request('/lab/activity');code,options=request('/lab/custom/options')
    check('four_public_profiles_without_raw_user_ids',code==200 and len(options['profiles'])==4 and all('user_id' not in p for p in options['profiles']))
    check('fixed_server_scope',options['scope']['at']=='2025-02-23T05:28:26.401006+00:00' and options['scope']['catalog']==10000)
    original='找2024年以后多模态快慢思考论文，不要纯文本'
    code,plan=request('/lab/custom/plan',{'original_need':original,'intent':'search','profile_id':'cold'})
    check('original_need_exact',code==200 and plan['original_need']==original)
    check('year_exclusion_unknowns_visible',bool(plan['conditions']) and '2024' in json.dumps(plan['warnings'],ensure_ascii=False) and '不要纯文本' in json.dumps(plan['warnings'],ensure_ascii=False))
    check('semantic_fulfillment_not_claimed',plan['conditions_programmatically_verified'] is False)
    check('existing_glossary_reused',plan['query_plan']['method']=='domain_glossary_native_regex')
    check('plan_retrievable_by_server_id',request('/lab/custom/plans/'+plan['id'])[1]==plan)
    valid={'plan_id':plan['id'],'executed_query':'multimodal fast slow thinking','reviewed':True,'conditions_reviewed':True,'policy':'constrained'}
    for name,patch in [('unreviewed',{'reviewed':False}),('conditions_unreviewed',{'conditions_reviewed':False}),('bool_coercion',{'reviewed':1}),('empty_query',{'executed_query':''}),('fixed_policy',{'policy':'fixed'}),('arbitrary_identity',{'user_id':'999'}),('arbitrary_time',{'at':'2026-11-16T00:00:00Z'}),('arbitrary_output_path',{'output':'C:/elsewhere/file'}),('multiline_query',{'executed_query':'a\nb'})]:
        check('reject_'+name,request('/lab/custom/run',{**valid,**patch})[0]==422)
    for name,body in [('unknown_profile',{'original_need':'test','profile_id':'other'}),('future_scope',{'original_need':'test','scope_id':'today'}),('empty_original',{'original_need':'   '}),('too_long',{'original_need':'a'*1001}),('identity_field',{'original_need':'test','user_id':'3603'}),('control_character',{'original_need':'test\u0000'})]:
        check('reject_plan_'+name,request('/lab/custom/plan',body)[0]==422)
    check('unknown_plan_not_executed',request('/lab/custom/run',{**valid,'plan_id':'00000000-0000-0000-0000-000000000000'})[0]==404)
    check('cross_site_plan_rejected',request('/lab/custom/plan',{'original_need':'test'},{'Sec-Fetch-Site':'cross-site'})[0]==403)
    check('foreign_origin_run_rejected',request('/lab/custom/run',valid,{'Origin':'https://outside.example'})[0]==403)
    code,cold=request('/lab/custom/algorithms',{'plan_id':plan['id']})
    lists=[[p['doc_id'] for p in rows] for rows in cold['methods'].values()]
    check('cold_profile_is_not_random_training_user',code==200 and all(ids==lists[0] for ids in lists) and all(p['cold_user_fallback'] and p['algorithm_evidence']['history_size']==0 for rows in cold['methods'].values() for p in rows))
    check('cold_popularity_score_display_not_zero_content_score',all(p['algorithm_evidence']['selected_score']>0 for p in cold['methods']['content']))
    _,rec=request('/lab/custom/plan',{'original_need':'根据冻结画像推荐一篇未读论文','intent':'recommend','profile_id':'profile-a'})
    check('recommend_plan_has_no_silent_search',rec['suggested_query']=='' and '不执行搜索词' in ' '.join(rec['warnings']))
    check('recommend_rejects_hidden_query',request('/lab/custom/run',{**valid,'plan_id':rec['id'],'executed_query':'hidden search'})[0]==422)
    _,english=request('/lab/custom/plan',{'original_need':'Find papers after 2024 without training','intent':'search','profile_id':'profile-a'})
    check('english_numbers_and_negation_preserved',english['suggested_query']=='Find papers after 2024 without training')
    _,after=request('/lab/activity');check('invalid_requests_start_no_jobs',len(before['jobs'])==len(after['jobs']))
    report={'status':'passed','checks':len(checks),'passed':checks,'scope':'no model jobs launched; input/identity/scope/consent/metadata verification'}
    (ROOT/'reports/stage71/custom-http-validation.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps({'status':'passed','checks':len(checks)}))


if __name__=='__main__':main()
