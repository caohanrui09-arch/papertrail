"""Compare unchanged native gateway endpoints with the direct pre-invoke budget gate."""
import ast,json,sys
from pathlib import Path
from datetime import datetime,timezone
from types import SimpleNamespace

def main():
    import fastapi
    sys.modules.setdefault('gsearch.showcase',SimpleNamespace(choose_user=lambda users:'test'))
    from gsearch.unified_agent import ToolClient
    from gsearch.unified_session import UnifiedSession
    from gsearch.unified_service import create_app,SessionRequest,ToolRequest
    root=Path(__file__).resolve().parents[1]
    tree=ast.parse((root/'research63/inprocess_v2.py').read_text())
    definition=next(n for n in ast.walk(tree) if isinstance(n,ast.ClassDef) and n.name=='DirectClient')
    model=SimpleNamespace(cutoff=datetime(2024,1,1,tzinfo=timezone.utc))
    namespace={'ToolClient':ToolClient,'UnifiedSession':UnifiedSession,'algorithm':model,'searcher':None}
    exec(compile(ast.Module(body=[definition],type_ignores=[]),'direct-adapter','exec'),namespace)
    task={'user_id':'test','at':'2025-02-23T05:28:26.401006+00:00'}
    direct=namespace['DirectClient'](task);app=create_app(model,'test-only')
    endpoints={r.path:r.endpoint for r in app.routes}
    create=endpoints['/sessions'];token=create(SessionRequest(**task))['session_id']
    invoke=endpoints['/sessions/{token}/tools'];snapshot=next(r.endpoint for r in app.routes if r.path=='/sessions/{token}' and 'GET' in r.methods)
    statuses=[]
    for i in range(7):
        try:invoke(token,ToolRequest(name='read_paper',arguments={'doc_id':'not-returned'}));statuses.append(200)
        except fastapi.HTTPException as error:statuses.append(error.status_code)
        try:direct.call('read_paper',doc_id='not-returned')
        except ValueError:pass
    original=snapshot(token)
    assert statuses==[400]*6+[429]
    assert len(original['trace'])==len(direct.snapshot()['trace'])==6
    assert direct.snapshot()['attempts']==original['attempts']==6
    assert len(direct.snapshot()['transport_rejections'])==1
    for a,b in zip(original['trace'],direct.snapshot()['trace']):
        assert a['tool']==b['tool'] and a['arguments']==b['arguments'] and a['result']==b['result']
    (root/'reports/stage63/transport-parity.json').write_text(json.dumps({'status':'passed','native_gateway_statuses':statuses,'executed_trace_entries':6,'seventh_rejected_before_invoke':True,'trace_results_equal':True,'scope':'native route functions and actual direct adapter; not ASGI or HTTP'},indent=2),encoding='utf8')
    print('Native gateway / direct parity passed; no ASGI, threads or sockets used')

if __name__=='__main__':main()
