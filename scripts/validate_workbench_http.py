"""Actual localhost integration, including expected failures; not a quality study."""
import json
from pathlib import Path
import urllib.request
import urllib.error
from uuid import uuid4
from gsearch.quality_protocol import save,digest

URL='http://127.0.0.1:8767'
REPORT=Path('reports/stage23/http-validation.json')
CACHE=Path('.cache/stage23/http-validation')


def request(method: str,path: str,body: dict|None=None,headers: dict|None=None):
    headers={'Content-Type':'application/json',**(headers or {})}
    req=urllib.request.Request(URL+path,json.dumps(body).encode() if body is not None else None,headers,method=method)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req,timeout=120) as response:return response.status,response.headers,response.read()
    except urllib.error.HTTPError as response:return response.code,response.headers,response.read()


def main() -> None:
    import argparse
    global REPORT,CACHE
    parser=argparse.ArgumentParser();parser.add_argument('--final',action='store_true');args=parser.parse_args()
    if args.final:
        REPORT=Path('reports/stage23/http-validation-final.json');CACHE=Path('.cache/stage23/http-validation-final')
    if REPORT.exists():raise ValueError('Preserve actual verification; do not overwrite')
    CACHE.mkdir(parents=True,exist_ok=True);checks=[];runs=[]
    def expect(name,method,path,body=None,headers=None,status=200):
        code,response_headers,data=request(method,path,body,headers)
        save(CACHE/(str(len(checks))+'-response.json'),{'status':code,'headers':dict(response_headers),'body':data.decode(errors='replace')})
        if code!=status:raise ValueError(f'{name}: expected{status}, received{code}')
        checks.append({'name':name,'status':code,'passed':True})
        return response_headers,data
    headers,_=expect('home','GET','/')
    if 'frame-ancestors' not in headers.get('Content-Security-Policy',''):raise ValueError('Missing presentation boundary headers')
    _,data=expect('config','GET','/api/config');config=json.loads(data)
    expect('health','GET','/api/health')
    expect('foreign_origin_refused','POST','/api/runs',{'thread_id':str(uuid4()),'mode':'recommend'},
        {'Origin':'https://foreign.example'},403)
    expect('foreign_host_refused','GET','/api/config',headers={'Host':'foreign.example'},status=400)
    expect('no_private_static_path','GET','/data/stage9-recommendation/train.csv',status=404)
    expect('invalid_profile_refused','POST','/api/runs',{'thread_id':str(uuid4()),'mode':'recommend','profile':'arbitrary'},status=422)
    expect('hidden_user_override_refused','POST','/api/runs',{'thread_id':str(uuid4()),'mode':'recommend','user_id':'arbitrary'},status=422)
    expect('blank_search_refused','POST','/api/runs',{'thread_id':str(uuid4()),'mode':'search','query':' '},status=422)
    thread=str(uuid4());nohit='stage23nomatch1a1be4ad3ac14657bd0c96b892a8c7a0'
    for mode,profile,query,wanted in [('search','warm',config['example_query'],'completed'),('recommend','warm','','completed'),
        ('mixed','warm',config['example_query'],'completed'),('recommend','cold','','completed'),
        ('search','warm',nohit,'no_results'),('mixed','warm',nohit,'partial')]:
        _,body=expect(mode+'_'+profile+'_'+wanted,'POST','/api/runs',
            {'thread_id':thread,'mode':mode,'profile':profile,'query':query,'origin':'verification'})
        events=[json.loads(line) for line in body.decode().splitlines() if line.strip()]
        if events[0]['type']!='start' or events[-1]['type']!='done':raise ValueError('Incomplete actual stream')
        run=events[-1]['run'];runs.append(run)
        if run['status']!=wanted:raise ValueError('Wrong presentation completion state')
        if run['llm_calls']!=0 or len(run['trace'])>6:raise ValueError('Unexpected LLM or excess tool work')
        if len([e for e in events if e['type']=='tool_result'])!=len(run['trace']):raise ValueError('Unaccounted tool event')
        if mode=='mixed' and wanted=='completed' and [e['tool'] for e in run['trace']]!=['search_papers','recommend_papers','read_paper','read_paper','finalize']:
            raise ValueError('Frozen fixed chain changed')
        if mode in ('recommend','mixed'):
            actual=next(e['result']['cold_user_fallback'] for e in run['trace'] if e['tool']=='recommend_papers')
            if actual!=(profile=='cold'):raise ValueError('Personalization/fallback falsely presented')
        if '_task' in run or 'raw_path' in json.dumps(run):raise ValueError('Private identity/path leaked in presentation')
    full=runs[2];ident=full['id'];read={e['result']['doc_id'] for e in full['trace'] if e['tool']=='read_paper'}
    candidate=next(p for e in full['trace'] if e['tool']=='search_papers' for p in e['result']['papers'] if p['doc_id'] not in read)
    _,body=expect('fresh_source_read','POST',f"/api/runs/{ident}/papers/{candidate['doc_id']}")
    fresh=json.loads(body)
    if not fresh['new_source_session'] or [e['tool'] for e in fresh['trace']]!=['search_papers','read_paper']:
        raise ValueError('Fresh source read not separately accounted')
    _,body=expect('cached_source_read','POST',f"/api/runs/{ident}/papers/{candidate['doc_id']}")
    cached=json.loads(body)
    if cached['new_source_session'] or not cached['cached_original'] or cached['trace'] or len(cached['source_session_trace'])!=2:
        raise ValueError('Cached read falsely billed/re-executed')
    expect('unreturned_id_refused','POST',f'/api/runs/{ident}/papers/0000.00000',status=403)
    headers,body=expect('private_trace_export','GET',f'/api/runs/{ident}/export')
    if 'attachment' not in headers.get('Content-Disposition','') or json.loads(body)['trace']!=full['trace']:
        raise ValueError('Trace export differs')
    _,body=expect('thread_restored','GET','/api/threads/'+thread)
    if len(json.loads(body))!=6:raise ValueError('Thread history missing actual requests')
    _,body=expect('verification_separate_from_user_history','GET','/api/threads')
    if any(t['id']==thread for t in json.loads(body)):raise ValueError('Verification run mislabeled as interactive history')
    save(CACHE/'actual-runs.json',runs)
    save(REPORT,{'status':'passed','checks':checks,'actual_runs':len(runs),'no_results_and_partial_preserved':True,
        'real_cold_user_fallback':True,'separate_source_read_and_cache_accounting':True,'llm_calls':0,
        'no_new_quality_or_latency_claim':True,'private_validation_assets':{str(p):digest(p) for p in CACHE.glob('*') if p.is_file()}})
    print(json.dumps({'status':'passed','http_checks':len(checks),'actual_runs':len(runs)}),flush=True)


if __name__=='__main__':main()
