"""Same native model and policies; append passive execution events per real call."""
import argparse
from copy import deepcopy
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--events',required=True)
    parser.add_argument('--port',type=int,default=8802)
    args=parser.parse_args()
    from research70.observability import EventJournal,atomic_json
    journal=EventJournal(Path(args.events))
    journal.record('job_started',{'state':'worker entered'})
    try:
        from gsearch.unified_agent import load_model
        from research70.runner import observed_run,observed_constrained
        from smolagents.default_tools import FinalAnswerTool
        spec=json.loads(Path(args.input).read_text());results=[];model=None
        defaults=deepcopy(FinalAnswerTool.inputs)
        for task in spec['tasks']:
            for policy in spec['policies']:
                journal.context_for(task['id'],policy,len(results))
                if policy!='fixed' and model is None:
                    journal.record('model_loading',{'model':'Qwen2.5-1.5B-Instruct'})
                    model=load_model()
                    journal.record('model_ready',{'state':'native model loaded'})
                assert FinalAnswerTool.inputs==defaults
                journal.record('run_started',{'intent':task['intent']})
                result=observed_constrained(task,model,journal,port=args.port) if policy=='constrained' else observed_run(task,policy,model,port=args.port,observer=journal)
                assert FinalAnswerTool.inputs==defaults
                results.append(result)
                atomic_json(Path(args.output),{'complete':False,'results':results,'observability_errors':journal.errors})
                journal.record('run_completed',{'completed_protocol':result['completed_protocol'],
                    'seconds':result['seconds'],'error':result.get('error'),'tool_attempts':len(result['trace']['trace'])})
        atomic_json(Path(args.output),{'complete':True,'results':results,'observability_errors':journal.errors})
        journal.record('job_finished',{'results':len(results),'observability_errors':journal.errors})
    except Exception as error:
        journal.record('worker_failed',{'error':type(error).__name__+': '+str(error)})
        raise


if __name__=='__main__':main()
