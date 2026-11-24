"""Explicit v2 research CLI; native schemas remain owned by each tool instance."""
import argparse
import json
from pathlib import Path
import tempfile
from gsearch.unified_agent import load_model
from gsearch.constrained_agent_isolated import run
from gsearch.quality_protocol import save


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--intent',choices=('search','recommend','mixed'),default='recommend')
    parser.add_argument('--query',default='');args=parser.parse_args()
    if args.intent in ('search','mixed') and not args.query.strip():raise ValueError('Supply a query')
    from scripts.benchmark_isolated_constraints import fingerprints,ROOT,REPORT
    frozen=json.loads((REPORT/'locked-before-evaluation.json').read_text())
    if fingerprints()!=frozen['fingerprints']:raise ValueError('Frozen research configuration changed')
    task={'id':'isolated-state-research-demo','intent':args.intent,'query':args.query,'user_id':None,
        'at':'2025-02-23T05:28:26.401006+00:00','instruction':
        'Select and read one paper for search/recommend, or two distinct search/recommend papers for mixed. Return original abstract citations.'}
    ROOT.mkdir(parents=True,exist_ok=True)
    output=Path(tempfile.mkdtemp(prefix='demo-',dir=ROOT.resolve()))/'result.json'
    result=run(task,load_model());save(output,result)
    print(json.dumps({'completed':result['completed_protocol'],'private_output':str(output),
        'experimental_only':True,'version':'isolated-v2'}),flush=True)
    if result['answer']:print(result['answer']['answer'],flush=True)
    if not result['completed_protocol']:raise SystemExit(1)


if __name__=='__main__':main()
