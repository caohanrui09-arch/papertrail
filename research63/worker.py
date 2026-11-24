"""Real local-model execution; no scripted replacement of model choices."""
import argparse
import json
from pathlib import Path
from copy import deepcopy

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);p.add_argument('--port',type=int,default=8802);a=p.parse_args()
    from gsearch.unified_agent import load_model,run
    from gsearch.constrained_agent_isolated import run as constrained
    from smolagents.default_tools import FinalAnswerTool
    spec=json.loads(Path(a.input).read_text()); results=[];model=None
    baseline=deepcopy(FinalAnswerTool.inputs)
    for task in spec['tasks']:
        for policy in spec['policies']:
            if policy!='fixed' and model is None:model=load_model()
            assert FinalAnswerTool.inputs==baseline
            result=constrained(task,model,port=a.port) if policy=='constrained' else run(task,policy,model,port=a.port)
            assert FinalAnswerTool.inputs==baseline
            results.append(result)
            Path(a.output).write_text(json.dumps({'complete':False,'results':results},ensure_ascii=False,indent=2),encoding='utf8')
    Path(a.output).write_text(json.dumps({'complete':True,'results':results},ensure_ascii=False,indent=2),encoding='utf8')

if __name__=='__main__':main()
