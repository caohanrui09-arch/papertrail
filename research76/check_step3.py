"""Compare the new adapter with independently returned native diagnostic ranks."""
import json
from pathlib import Path
import urllib.request,urllib.error
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/stage76'

def main():
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}));checks=[]
    def check(name,v):assert v,name;checks.append(name)
    def req(path,body):
        r=urllib.request.Request('http://127.0.0.1:8802'+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        try:
            with op.open(r,timeout=30) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as e:return e.code,json.load(e)
    code,source=req('/lab/v72/diagnostics/preset',{'task_id':'evaluation-002'});check('original_native_diagnostic',code==200)
    request={'version':76,'diagnostic_id':source['id'],'profile_a':'profile-c','profile_b':'cold'}
    code,value=req('/lab/v76/profile-comparison',request);check('new_adapter_complete',code==200 and value['status']=='complete')
    a,b=value['profiles'];check('warm_native_order_matches_independent_existing_diagnostic',[r['doc_id'] for r in a['rows']]==[r['doc_id'] for r in source['methods']['profile_rerank']])
    check('cold_keeps_query_order_without_popularity',[r['doc_id'] for r in b['rows']]==[r['doc_id'] for r in source['methods']['pool_content']] and b['cold'] and all(r['profile_cosine'] is None and r['nearest_history_paper'] is None for r in b['rows']))
    original={r['doc_id']:r for r in source['methods']['profile_rerank']}
    check('warm_actual_cosines_and_anchors_match',all(r['profile_cosine']==original[r['doc_id']]['profile_cosine'] and r['nearest_history_paper']==original[r['doc_id']]['nearest_history_paper'] for r in a['rows']))
    base=ROOT/'data/stage76-profile-comparisons'/value['id'];check('protocol_saved_before_result_and_hash_correct',sha256((base/'protocol.json').read_bytes()).hexdigest()==value['protocol_sha256'] and (base/'protocol.json').stat().st_mtime<=(base/'result.json').stat().st_mtime)
    (OUT/'step3-cold-comparison.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    code,both=req('/lab/v76/profile-comparison',{**request,'profile_a':'profile-a','profile_b':'profile-b'});check('two_warm_profiles_same_pool',code==200 and set(r['doc_id'] for r in both['profiles'][0]['rows'])==set(r['doc_id'] for r in both['profiles'][1]['rows'])==set(both['protocol']['pool_ids']))
    seen=set(sum(both['protocol']['history_ids'].values(),[]));check('neither_profile_already_read_common_candidates',not seen&set(both['protocol']['pool_ids']))
    check('excluded_documents_accounted_for',len(both['protocol']['source_pool_ids'])==len(both['protocol']['pool_ids'])+len(both['protocol']['excluded_before_freeze']))
    check('no_fabricated_fused_score',all(r['fused_score'] is None for side in both['profiles'] for r in side['rows']))
    check('real_full_ranks_and_deltas',all(c['delta_b_vs_a']==c['rank_a']-c['rank_b'] for c in both['changes']))
    check('diagnostic_only_no_model_or_quality_claim',both['model_calls']==0 and both['protocol']['quality_evaluation'] is False and both['protocol']['sent_to_agent'] is False)
    (OUT/'step3-warm-comparison.json').write_text(json.dumps(both,ensure_ascii=False,indent=2),encoding='utf8')
    codes=[req('/lab/v76/profile-comparison',{**request,**patch})[0] for patch in [{'profile_a':'cold'},{'version':75},{'profile_b':'visitor'},{'k':10},{'diagnostic_id':'../not-a-real-diagnostic.json'},{'diagnostic_id':'00000000-0000-0000-0000-000000000000'}]]
    check('strict_parameters_and_unknown_source_rejected',codes==[422,422,422,422,422,404])
    (OUT/'step3-source.json').write_text(json.dumps(source,ensure_ascii=False,indent=2),encoding='utf8')
    (OUT/'step3-api-validation.json').write_text(json.dumps({'status':'passed','checks':len(checks),'passed':checks,'invalid_statuses':codes,'model_calls':0},indent=2),encoding='utf8');print({'status':'passed','checks':len(checks),'pool':len(both['protocol']['pool_ids'])})
if __name__=='__main__':main()
