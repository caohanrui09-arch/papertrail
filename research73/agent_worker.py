"""Single frozen 4x3 evaluation; native policy functions own all decisions/execution."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime,timezone
import json
import os
import random
import threading
import time
import urllib.request

from research73.common import ROOT,DATA,read,write,digest,verify_protocol


def main():
    os.chdir(ROOT);protocol=verify_protocol()
    if not (DATA/'manifest.json').exists():raise ValueError('Finish and freeze unjudged material pool before Agent execution')
    lock=DATA/'agent.lock'
    with lock.open('x',encoding='utf8') as handle:handle.write(str(os.getpid()))
    from research70.observability import EventJournal
    from research71.runner import observed_run,observed_constrained
    from gsearch.unified_agent import load_model
    from smolagents.default_tools import FinalAnswerTool
    import torch
    original_schema=deepcopy(FinalAnswerTool.inputs);tasks=read(DATA/'inputs/agent-tasks.json');order=read(DATA/'inputs/run-order.json')
    model=None;op=urllib.request.build_opener(urllib.request.ProxyHandler({}));runtime={'pid':os.getpid(),'started_at':datetime.now(timezone.utc).isoformat(),'protocol_sha256':digest(DATA/'protocol.json'),'model_loads':0,'service_pid':None}
    write(DATA/'agent-runtime.json',runtime)
    try:
        for cell in order:
            base=DATA/'agent-runs'/cell['cell'];base.mkdir(parents=True,exist_ok=True)
            if (base/'started.json').exists():
                # A started cell is never rerun, including after infrastructure interruption.
                if not (base/'result.json').exists():write(base/'result.json',{'task_id':cell['task_id'],'policy':cell['policy'],'completed_protocol':False,'failure_kind':'infrastructure_interruption','error':'Previously started cell has no final response; not retried','trace':{'trace':[]},'answer':None,'metadata':{}})
                continue
            task=deepcopy(tasks[cell['task_index']]);policy=cell['policy'];wall=time.perf_counter()
            write(base/'started.json',{'task':task,'policy':policy,'at':datetime.now(timezone.utc).isoformat(),'attempt':1})
            journal=EventJournal(base/'events.jsonl');journal.context_for(task['id'],policy,0)
            def timeout(folder=base,log=journal,task_id=task['id'],method=policy):
                log.record('execution_timeout',{'budget_seconds':900,'classification':'execution timeout, cause not attributed'})
                write(folder/'result.json',{'task_id':task_id,'policy':method,'completed_protocol':False,'failure_kind':'execution_timeout_unattributed','error':'900-second cell budget exhausted','trace':{'trace':[]},'answer':None,'metadata':{},'wall_seconds':900})
                os._exit(124)
            timer=threading.Timer(900,timeout);timer.daemon=True;timer.start()
            try:
                with op.open('http://127.0.0.1:8802/health',timeout=15) as response:health=json.load(response)
                assert health['candidates']==10000 and health['history_cutoff']==protocol['history_cutoff']
                if runtime['service_pid'] is None:runtime['service_pid']=health['pid']
                if runtime['service_pid']!=health['pid']:raise RuntimeError('Service changed during frozen evaluation')
                random.seed(73);torch.manual_seed(73)
                if policy!='fixed' and model is None:
                    journal.record('model_loading',{'model':protocol['model']['name']});model=load_model();runtime['model_loads']+=1
                    journal.record('model_ready',{'device':'cuda' if torch.cuda.is_available() else 'cpu'})
                assert FinalAnswerTool.inputs==original_schema
                journal.record('run_started',{'intent':task['intent'],'policy':policy,'scope':'frozen stage73 evaluation'})
                result=observed_constrained(task,model,journal,port=8802) if policy=='constrained' else observed_run(task,policy,model if policy!='fixed' else None,port=8802,observer=journal)
                assert FinalAnswerTool.inputs==original_schema and task==tasks[cell['task_index']]
                result['failure_kind']=None if result['completed_protocol'] else 'agent_protocol_failure'
            except Exception as error:
                result={'task_id':task['id'],'policy':policy,'completed_protocol':False,'failure_kind':'infrastructure_or_runtime_failure','error':type(error).__name__+': '+str(error),'trace':{'trace':[]},'answer':None,'metadata':{}}
                journal.record('worker_failed',{'error':result['error']})
            finally:timer.cancel()
            result['wall_seconds']=time.perf_counter()-wall
            write(base/'result.json',result)
            journal.record('run_completed',{'completed_protocol':result['completed_protocol'],'failure_kind':result['failure_kind'],'wall_seconds':result['wall_seconds']});journal.handle.close()
            runtime['last_cell']=cell['cell'];write(DATA/'agent-runtime.json',runtime)
            print(json.dumps({'cell':cell['cell'],'completed':result['completed_protocol'],'seconds':result.get('seconds'),'calls':result.get('metadata',{}).get('llm_usage',{}).get('calls',0),'failure_kind':result['failure_kind']}),flush=True)
        runtime['complete']=True;runtime['finished_at']=datetime.now(timezone.utc).isoformat();write(DATA/'agent-runtime.json',runtime)
    finally:
        if lock.exists():lock.unlink()


if __name__=='__main__':main()
