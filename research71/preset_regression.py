"""One low-cost fixed preset through the new worker; no model inference."""
import json
from pathlib import Path
import time
import urllib.request


def main():
    root=Path(__file__).resolve().parents[1];op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def api(path,body=None):
        req=urllib.request.Request('http://127.0.0.1:8802'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        with op.open(req,timeout=30) as response:return json.load(response)
    job=api('/lab/run',{'task_id':'evaluation-002','policy':'fixed'})
    for _ in range(60):
        state=api('/lab/jobs/'+job['id'])
        if state['status']!='running':break
        time.sleep(.5)
    assert state['status']=='complete',state
    row=state['result']['results'][0]
    previous=json.loads((root/'data/stage64-http/fixed-http-result.json').read_text())['result']['results'][0]
    def stable(value):
        if isinstance(value,dict):return {k:stable(v) for k,v in value.items() if k not in ('snapshot_cache_hit','snapshot_seconds','seconds')}
        if isinstance(value,list):return [stable(v) for v in value]
        return value
    assert row['completed_protocol'] and row['answer']==previous['answer']
    assert stable(row['trace']['trace'])==stable(previous['trace']['trace'])
    assert not state['task_context'] and not row.get('metadata',{}).get('llm_usage')
    report={'status':'passed','job_id':job['id'],'task_id':row['task_id'],'policy':'fixed',
            'native_tool_payloads_and_answer_match_retained_preset':True,
            'cross_run_excluded_telemetry':['seconds','snapshot_cache_hit','snapshot_seconds'],
            'tool_executions':len(row['trace']['trace']),'citations':len(row['answer']['citations']),
            'model_inference_calls':0,'custom_context_absent':True}
    (root/'reports/stage71/preset-worker-validation.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report))


if __name__=='__main__':main()
