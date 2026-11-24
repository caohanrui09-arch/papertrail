"""Real native filtering and empty-pool boundaries, with no model or human labels."""
import json,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}));checks=[]
    def req(path,body):
        with op.open(urllib.request.Request('http://127.0.0.1:8802'+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'}),timeout=30) as r:return json.load(r)
    def compare(query):
        plan=req('/lab/custom/plan',{'original_need':query,'intent':'search','profile_id':'cold','scope_id':'snapshot-2025-02-23'})
        source=req('/lab/v72/diagnostics/custom',{'plan_id':plan['id'],'executed_query':query,'reviewed':True,'conditions_reviewed':True})
        result=req('/lab/v76/profile-comparison',{'version':76,'diagnostic_id':source['id'],'profile_a':'profile-a','profile_b':'cold'})
        return source,result
    previous=json.loads((ROOT/'reports/stage76/step3-warm-comparison.json').read_text(encoding='utf8'))
    target=previous['protocol']['history_ids']['profile-a'][0]
    docs=json.loads((ROOT/'data/stage13-expansion/documents.json').read_text(encoding='utf8'));title=next(d['title'] for d in docs if d['doc_id']==target)
    source,result=compare(title);assert target in source['pool_ids'] and target not in result['protocol']['pool_ids'];checks.append('actual_read_history_target_removed_before_common_pool_freeze')
    assert any(x['doc_id']==target and 'profile-a' in x['ineligible_for'] for x in result['protocol']['excluded_before_freeze']);checks.append('excluded_target_has_actual_profile_reason')
    (ROOT/'reports/stage76/step3-read-filter-case.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    source,empty=compare('zzpapertrailimpossibleunknownquery76')
    assert source['pool_ids']==[] and empty['protocol']['pool_ids']==[] and all(p['rows']==[] for p in empty['profiles']);checks.append('empty_pool_does_not_fabricate_ranks_or_candidates')
    assert empty['status']=='complete' and empty['model_calls']==0;checks.append('empty_pool_is_bounded_diagnostic_not_agent_success')
    (ROOT/'reports/stage76/step3-empty-case.json').write_text(json.dumps(empty,ensure_ascii=False,indent=2),encoding='utf8')
    (ROOT/'reports/stage76/step3-boundary-validation.json').write_text(json.dumps({'status':'passed','checks':len(checks),'passed':checks,'model_calls':0},indent=2),encoding='utf8');print({'status':'passed','checks':len(checks)})
if __name__=='__main__':main()
