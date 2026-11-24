"""Real fixed/raw-LLM SSE checks; replay uses retained events, never starts a model."""
import hashlib
import json
import argparse
from copy import deepcopy
from pathlib import Path
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8802'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--fixed-job');args=parser.parse_args()
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));checks=[];outcomes=[]
    def api(path,body=None,headers=None):
        req=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json',**(headers or {})})
        with opener.open(req,timeout=30) as response:return json.load(response)
    def frames(response):
        event={'id':None,'kind':None,'data':[]}
        for raw in response:
            line=raw.decode('utf8').rstrip('\r\n')
            if not line:
                if event['data']:yield event['id'],event['kind'],json.loads('\n'.join(event['data']))
                event={'id':None,'kind':None,'data':[]}
            elif line.startswith('id: '):event['id']=int(line[4:])
            elif line.startswith('event: '):event['kind']=line[7:]
            elif line.startswith('data: '):event['data'].append(line[6:])
    for policy,task in [('fixed','evaluation-002'),('llm_agent','evaluation-001')]:
        job={'id':args.fixed_job} if policy=='fixed' and args.fixed_job else api('/lab/run',{'task_id':task,'policy':policy})
        ident=job['id'];print(json.dumps({'policy':policy,'job_id':ident,'existing_job_reused':bool(policy=='fixed' and args.fixed_job)}),flush=True)
        rows=[];live_tools=False;terminal=None
        with opener.open(BASE+'/lab/jobs/'+ident+'/events',timeout=120) as response:
            assert response.headers.get_content_type()=='text/event-stream'
            for event_id,kind,payload in frames(response):
                if kind=='record':
                    assert payload['id']==event_id==len(rows)+1
                    rows.append(payload)
                    if payload['kind']=='tool_returned':
                        state=api('/lab/jobs/'+ident)
                        live_tools|=state['status']=='running'
                        print(json.dumps({'policy':policy,'event':event_id,'tool':payload['payload']['tool'],'worker':state['status']}),flush=True)
                elif kind=='job_state':terminal=payload
                elif kind=='stream_error':raise AssertionError(payload)
        state=api('/lab/jobs/'+ident);assert state['status']=='complete' and terminal['status']=='complete'
        row=state['result']['results'][0]
        disk=[json.loads(line) for line in (ROOT/f'data/stage70-lab/{ident}/events.jsonl').read_text(encoding='utf8').splitlines()]
        assert disk==rows
        assert [r['payload'] for r in rows if r['kind']=='tool_returned']==row['trace']['trace']
        assert len(row['trace']['trace'])<=6 and row['metadata'].get('llm_usage',{}).get('calls',0)<=8
        assert state['result']['observability_errors']==0
        if policy=='fixed':
            assert row['completed_protocol'] and len(row['answer']['citations'])==2
            previous=json.loads((ROOT/'data/stage64-http/fixed-http-result.json').read_text(encoding='utf8'))['result']['results'][0]
            assert row['answer']==previous['answer']
            def stable(entries):
                values=deepcopy([(e['tool'],e['arguments'],e['result']) for e in entries])
                for tool,arguments,result in values:
                    if tool=='search_papers':
                        for field in ('snapshot_cache_hit','snapshot_seconds'):
                            result.get('index',{}).pop(field,None)
                return values
            assert stable(row['trace']['trace'])==stable(previous['trace']['trace'])
        else:
            assert live_tools,'LLM tools were not observed before completion'
            assert row['metadata']['prompt_sha256']==hashlib.sha256((ROOT/'gsearch/prompts/unified.txt').read_bytes()).hexdigest()
        checks.append(policy+'_actual_stream_disk_and_native_trace_match')
        # Last-Event-ID wins over an older query cursor; replay never POSTs a job.
        after=min(3,len(rows));req=urllib.request.Request(BASE+f'/lab/jobs/{ident}/events?after=1',headers={'Last-Event-ID':str(after)})
        with opener.open(req,timeout=10) as response:
            replay=[value for event_id,kind,value in frames(response) if kind=='record']
        assert replay==rows[after:];checks.append(policy+'_cursor_replay_exact_without_execution')
        for suffix,headers,expected in [('?after=-1',{},422),('?after=10000',{},409),('',{'Last-Event-ID':'bad'},400),('',{'Sec-Fetch-Site':'cross-site'},403)]:
            try:
                with opener.open(urllib.request.Request(BASE+f'/lab/jobs/{ident}/events'+suffix,headers=headers),timeout=5):pass
                raise AssertionError('Request should have failed')
            except urllib.error.HTTPError as error:assert error.code==expected,(error.code,expected)
        checks.append(policy+'_invalid_cursors_and_cross_site_rejected')
        outcomes.append({'policy':policy,'job_id':ident,'completed_protocol':row['completed_protocol'],'tools':len(row['trace']['trace']),
            'failed_executions':sum(bool(e['result'].get('error')) for e in row['trace']['trace']),'gateway_or_guard_rejections':sum(e['kind']=='tool_rejected' for e in rows),
            'model_usage':row['metadata'].get('llm_usage',{}),'event_count':len(rows),'existing_completed_job_replayed':bool(policy=='fixed' and args.fixed_job),'tools_before_exit':None if policy=='fixed' and args.fixed_job else live_tools})
    report={'status':'passed','checks':checks,'outcomes':outcomes,'scope':'real integration/stream acceptance, reused tasks not new independent quality evidence'}
    (ROOT/'reports/stage70/job-validation.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report),flush=True)


if __name__=='__main__':main()
