"""Frozen-scope real model acceptance for custom Chinese/recommend/mixed/empty tasks."""
import hashlib
import json
from pathlib import Path
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8802'


def main():
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}));outcomes=[]
    data=ROOT/'data/stage71-custom/acceptance';data.mkdir(exist_ok=False)
    cases=[
        {'name':'chinese_search','need':'帮我找几何感知3D生成的论文，并引用原摘要','intent':'search','profile':'profile-a','query':'Efficient Geometry-aware 3D Generative Adversarial Networks'},
        {'name':'cold_recommend','need':'请根据所选冷启动画像推荐一篇未读论文，并给出原摘要引用','intent':'recommend','profile':'cold','query':''},
        {'name':'mixed','need':'Find All in One: Exploring Unified Video-Language Pre-training AND one DIFFERENT unread recommendation. Cite both original abstracts.','intent':'mixed','profile':'profile-c','query':'All in One: Exploring Unified Video-Language Pre-training'},
        {'name':'no_results','need':'qzxpapertrailnevermatches71','intent':'search','profile':'cold','query':'qzxpapertrailnevermatches71'}]
    (data/'protocol.json').write_text(json.dumps({'cases':cases,'scope':'integration acceptance, no independent relevance labels or quality improvement claim','policy':'constrained','budgets_unchanged':True},ensure_ascii=False,indent=2),encoding='utf8')
    def api(path,body=None):
        req=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        with op.open(req,timeout=30) as response:return json.load(response)
    def frames(response):
        kind=None;lines=[]
        for raw in response:
            line=raw.decode('utf8').rstrip('\r\n')
            if not line:
                if lines:yield kind,json.loads('\n'.join(lines))
                kind=None;lines=[]
            elif line.startswith('event: '):kind=line[7:]
            elif line.startswith('data: '):lines.append(line[6:])
    documents={d['doc_id']:d for d in json.loads((ROOT/'data/stage13-expansion/documents.json').read_text(encoding='utf8'))}
    for case in cases:
        plan=api('/lab/custom/plan',{'original_need':case['need'],'intent':case['intent'],'profile_id':case['profile']})
        payload={'plan_id':plan['id'],'executed_query':case['query'],'reviewed':True,'conditions_reviewed':True,'policy':'constrained'}
        started=time.monotonic();job=api('/lab/custom/run',payload);ident=job['id'];print(json.dumps({'started':case['name'],'job_id':ident}),flush=True)
        observed=[]
        with op.open(BASE+f'/lab/jobs/{ident}/events',timeout=120) as response:
            for kind,value in frames(response):
                if kind=='record':
                    observed.append(value)
                    if value['kind']=='tool_returned':print(json.dumps({'case':case['name'],'tool':value['payload']['tool'],'failed':bool(value['payload']['result'].get('error'))}),flush=True)
                elif kind=='stream_error':raise AssertionError(value)
        state=api('/lab/jobs/'+ident);wall=time.monotonic()-started
        (data/(case['name']+'.json')).write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8')
        assert state['status']=='complete' and state['result']['complete'],state
        row=state['result']['results'][0];context=state['task_context'];trace=row['trace']['trace'];usage=row['metadata']['llm_usage']
        assert row['task_id'].startswith('custom-') and context['original_need']==case['need'] and context['executed_query']==case['query']
        assert context['profile']['id']==case['profile'] and context['scope']['at']==row['trace']['as_of']
        assert context['conditions_programmatically_verified'] is False
        assert 0<usage['calls']<=8 and usage['input_tokens']<=30000 and usage['output_tokens']<=1280 and len(trace)<=6
        assert row['metadata']['native_default_schema_unchanged']
        assert [r['payload'] for r in observed if r['kind']=='tool_returned']==trace
        for event in trace:
            if event['tool']=='search_papers':assert event['arguments']['query']==case['query']
        reads={e['result']['doc_id']:e['result'] for e in trace if e['tool']=='read_paper' and 'error' not in e['result']}
        citations=(row.get('answer') or {}).get('citations',[])
        for cite in citations:
            source=documents[cite['doc_id']];original=reads[cite['doc_id']]
            assert cite['quote'] in original['abstract'] and original['abstract']==source['abstract']
            assert cite['version_key']==source['version_key'] and cite['source_url']==source['source_url']
            assert hashlib.sha256(Path(source['provenance']['raw_path']).read_bytes()).hexdigest()==source['provenance']['raw_sha256']
        if case['name']=='cold_recommend':assert all(e['result']['cold_user_fallback'] for e in trace if e['tool']=='recommend_papers' and 'error' not in e['result'])
        if case['name']=='no_results':assert all(not e['result']['papers'] for e in trace if e['tool']=='search_papers' and 'error' not in e['result']);assert not reads and not citations
        outcome={'case':case['name'],'job_id':ident,'task_id':row['task_id'],'completed_protocol':row['completed_protocol'],'citations':len(citations),'tool_executions':len(trace),'failed_executions':sum(bool(e['result'].get('error')) for e in trace),'events':len(observed),'execution_seconds':row['seconds'],'wall_seconds_including_loading':wall,'usage':usage,'error':row.get('error') or row['metadata'].get('error'),'rejected_proposals':sum(bool(e.get('error')) for e in row['metadata'].get('proposal_events',[])),'charged_application_attempts':row['metadata'].get('charged_application_attempts'),'framework_steps_exhausted':row['metadata'].get('framework_steps_exhausted',False)}
        outcomes.append(outcome);print(json.dumps(outcome),flush=True)
    result={'status':'passed','scope':'real custom task integration and citation-source checks, not a relevance evaluation','cases':outcomes,'all_cases_completed_protocol':all(r['completed_protocol'] for r in outcomes)}
    (ROOT/'reports/stage71/custom-job-validation.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result),flush=True)


if __name__=='__main__':main()
