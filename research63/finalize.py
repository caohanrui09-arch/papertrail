"""Publish aggregates only; retain raw interaction/model traces in private data/."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))

def main():
    folder=ROOT/'data/stage63-inprocess-v2';report=ROOT/'reports/stage63'
    value=read(report/'inprocess-validation.json');raw=read(folder/'results.json')
    assert raw['complete'] and len(raw['results'])==9
    assert read(report/'transport-parity.json')['status']=='passed'
    for name,method in value['methods'].items():
        assert method['tasks']==3 and method['all_budgets_pass']
        cases=[r for r in raw['results'] if r['policy']==name]
        method['gateway_rejected_proposals']=sum(len(r['trace'].get('transport_rejections',[])) for r in cases)
        method['state_guard_rejections']=sum(sum('error' in e and not e['sent_to_server'] for e in r['metadata'].get('wire_attempts',[])) for r in cases)
    value['transport']='inprocess-v2; native gateway precheck parity verified; HTTP/browser not verified'
    value['raw_results_sha256']=sha(folder/'results.json');value['protocol_sha256']=sha(folder/'protocol.json')
    (report/'inprocess-validation.json').write_text(json.dumps(value,indent=2),encoding='utf8')
    html=ROOT/'research63/lab.html';source=html.read_text(encoding='utf8')
    if 'id="recorded"' not in source:
        source=source.replace('<button id="quality">','<button id="recorded">本轮真实对照回放</button><button id="quality">')
        html.write_text(source,encoding='utf8')
    js=ROOT/'research63/lab.js';source=js.read_text(encoding='utf8').split('// RECORDED_AGGREGATES')[0]
    source+='\n// RECORDED_AGGREGATES: real inprocess-v2 run, explicitly a replay, no private raw traces.\nconst recorded='+json.dumps(value)+';\n'
    source+="$('recorded').onclick=()=>{$('summary').replaceChildren(node('p','2026-11-11真实进程内运行回放；三条复用受控任务，非新独立质量评价。'),node('pre',JSON.stringify(recorded.methods,null,2)));$('trace').textContent='原始运行SHA256: '+recorded.raw_results_sha256+'\\n协议SHA256: '+recorded.protocol_sha256+'\\n完整原始模型/工具轨迹留在本机私有data/stage63-inprocess-v2/results.json。';$('status').textContent='已显示本轮真实运行的聚合回放；执行按钮会另起真实模型作业。';};\n"
    js.write_text(source,encoding='utf8')
    # Verify the current previous public delivery rather than silently mutating it.
    prior=ROOT/'reports/stage61/final-validation.json';old=read(prior)
    for p,digest in old['files'].items():assert sha(ROOT/p)==digest,p
    paths=[p for p in (ROOT/'research63').glob('*') if p.is_file()]
    paths+=[ROOT/'project-agent.cmd',ROOT/'docs/ALGORITHM_AGENT_LAB_V63.md']
    paths+=[p for p in report.glob('*') if p.is_file() and p.name!='final-validation.json']
    receipt={'status':'core_verified_http_not_accepted','date':'2026-11-11','real_model_runs':9,'ranking_parity_cases':15,
        'source_and_budget_scored':True,'native_schema_unchanged':True,'transport_gateway_parity':True,
        'previous_v61_assets_unchanged':len(old['files']),'old_trial_invalidated':'INVALIDATED_TRANSPORT_V1.json',
        'http_browser_verified':False,'permission_limit':'sandbox loopback request blocked; elevated process cleanup rejected by user, not retried',
        'private_raw_outputs':'data/stage63-inprocess-v2','files':{str(p.relative_to(ROOT)):sha(p) for p in sorted(paths)}}
    (report/'final-validation.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
    print(json.dumps({'status':receipt['status'],'real_runs':9,'ranking_parity':15,'previous_assets':len(old['files'])}))

if __name__=='__main__':main()
