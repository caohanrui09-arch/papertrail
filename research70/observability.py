"""Passive observation of the existing tool client and native step callbacks."""
from datetime import datetime, timezone
from dataclasses import asdict
import json
from pathlib import Path
import sys
import threading
import time

from gsearch.unified_agent import ToolClient
from gsearch.constrained_agent import GuardedClient
from gsearch.state_constraints import parsed_calls


class EventJournal:
    def __init__(self, path: Path):
        self.path=path
        self.started=time.monotonic()
        self.sequence=0
        self.errors=0
        self.context={}
        self.lock=threading.Lock()
        self.handle=path.open('x',encoding='utf8',newline='\n')

    def context_for(self, task_id: str, policy: str, run_index: int):
        self.context={'task_id':task_id,'policy':policy,'run_index':run_index}

    def record(self, kind: str, payload: dict):
        # Observability failures must not repair, retry or alter model/tool execution.
        try:
            with self.lock:
                row={'id':self.sequence+1,'kind':kind,'utc':datetime.now(timezone.utc).isoformat(),
                     'elapsed_seconds':time.monotonic()-self.started,**self.context,'payload':payload}
                self.handle.write(json.dumps(row,ensure_ascii=False,default=str)+'\n')
                self.handle.flush()
                self.sequence+=1
        except Exception as error:
            self.errors+=1
            print('Event observation failed: '+type(error).__name__,file=sys.stderr,flush=True)

    def model_step(self, step, agent):
        timing=getattr(step,'timing',None)
        usage=getattr(getattr(agent,'model',None),'meter',None)
        self.record('model_step',{'step_number':getattr(step,'step_number',None),
            'tool_calls':parsed_calls(step),'error':str(step.error) if getattr(step,'error',None) else None,
            'duration':getattr(timing,'duration',None),
            'usage':{k:v for k,v in asdict(usage).items() if k!='budget'} if usage is not None else None})


class ObserveCalls:
    def __init__(self,*args,observer: EventJournal,**kwargs):
        self.observer=observer
        self.observed_attempts=0
        super().__init__(*args,**kwargs)
        self.observer.record('session_ready',{'state':'native session created'})

    def observe_snapshot(self):
        try:
            snapshot=self.snapshot()
            for entry in snapshot['trace']:
                if entry['attempt']>self.observed_attempts:
                    self.observer.record('tool_returned',entry)
                    self.observed_attempts=entry['attempt']
            return True
        except Exception:
            # The original final snapshot remains authoritative.
            self.observer.record('observation_error',{'operation':'read-only session snapshot'})
            return False

    def call(self,name: str,**arguments):
        self.observer.record('tool_requested',{'tool':name,'arguments':arguments,
            'note':'requested, not proof of gateway execution'})
        before=self.observed_attempts
        try:
            result=super().call(name,**arguments)
        except Exception as error:
            observed=self.observe_snapshot()
            if observed and self.observed_attempts==before:
                self.observer.record('tool_rejected',{'tool':name,'arguments':arguments,
                    'error':str(error),'native_trace_changed':False})
            raise
        self.observe_snapshot()
        return result


class ObservedClient(ObserveCalls,ToolClient):
    pass


class ObservedGuardedClient(ObserveCalls,GuardedClient):
    pass


def atomic_json(path: Path, value: dict):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    temporary.replace(path)
