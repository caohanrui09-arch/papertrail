"""Three real same-budget policies; no scoring labels enter any policy."""
import argparse
import json
from pathlib import Path
import time
from gsearch.unified_agent import load_model,run,request
from gsearch.constrained_agent import run as run_constrained
from gsearch.quality_protocol import save,digest

ROOT=Path('data/stage21-constraints')
REPORT=Path('reports/stage21')
CODE=['gsearch/state_constraints.py','gsearch/constrained_agent.py','scripts/benchmark_state_constraints.py',
    'scripts/score_state_constraints.py','tests/test_state_constraints.py','gsearch/unified_agent.py',
    'gsearch/local_model.py','gsearch/budget_model.py','gsearch/qwen_messages.py','gsearch/prompts/unified.txt']


def fingerprints() -> dict:
    paths=[Path(p) for p in CODE]+[REPORT/'evaluation-plan.json',REPORT/'upstream-audit.json']
    for split in ('tuning','evaluation'):
        paths += [Path(f'data/stage19-unified/benchmark/{split}-{kind}.json') for kind in ('tasks','gold')]
    paths += [Path(f'reports/stage{n}/final-validation.json') for n in (19,20)]
    source=Path('.cache/models/Qwen2.5-1.5B-Instruct/source.json')
    manifest=json.loads(source.read_text())
    for entry in manifest['files']:
        if digest(source.parent/entry['file'])!=entry['sha256']:raise ValueError('Frozen model changed')
    paths.append(source)
    return {str(p):digest(p) for p in paths}


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=('prepare','tuning','lock','evaluation'),required=True)
    args=parser.parse_args()
    lock=REPORT/'locked-before-evaluation.json'
    if args.phase=='prepare':
        if (REPORT/'evaluation-plan.json').exists():raise ValueError('Protocol already prepared')
        save(REPORT/'evaluation-plan.json',{'policies':['fixed','llm_agent','constrained'],
            'tasks':'unchanged stage19 tuning4 and reused descriptive evaluation12; no new independent or relevance claims',
            'budgets':{'server_application_attempts':6,'retrieval_attempts':2,'read_attempts':2,'framework_steps':7,
                'llm_calls_including_fallback':8,'input_tokens':30000,'output_tokens':1280},
            'local_rejections':'constrained native callbacks charge equivalent application/retrieval/read allowances even if not sent to server; all parser errors consume LLM budget',
            'scope':'no decoder-level grammar; native dynamic tools/types plus project state constraints; no argument repair/automatic reads/finalization',
            'policy_details':'mixed retrieval can occur in either order; model selects IDs/quotes, final contract from explicit intent, never gold target IDs',
            'thresholds':{'success_at_least_fixed':True,'no_budget_violation':True,'mean_time_ratio_to_original_lte':.8,
                'llm_token_total_ratio_to_original_lte':.8,'mean_time_ratio_to_fixed_lte':5.},
            'decision':'Engineering point-estimate gates for these simple explicit tasks, not statistical noninferiority. Keep fixed if any gate fails; stop this optimization round, no post-evaluation prompt search.',
            'tuning_policy':'one trial; fix only reproducible implementation defects, not task/result selection; freeze even on negative tuning outcomes',
            'attribution':'report state-mask changes, only-one-tool states, rejected/virtual attempts and model token cost separately; gain cannot be attributed solely to model reasoning'})
        print(json.dumps({'prepared':True}));return
    if args.phase=='lock':
        if lock.exists():raise ValueError('Already frozen')
        cases=list((ROOT/'tuning').glob('tuning-*.json'))
        if len(cases)!=12:raise ValueError('Complete4 tasks times3 policies first')
        save(lock,{'fingerprints':fingerprints(),'tuning':{str(p):digest(p) for p in sorted(cases)},
            'evaluation_not_started':not (ROOT/'evaluation').exists()})
        print(json.dumps({'frozen':True}));return
    if args.phase=='evaluation':
        frozen=json.loads(lock.read_text())
        if fingerprints()!=frozen['fingerprints'] or any(digest(Path(p))!=h for p,h in frozen['tuning'].items()):raise ValueError('Frozen trial drift')
    elif lock.exists():raise ValueError('Tuning already closed')
    target=ROOT/args.phase
    if target.exists():raise ValueError('Preserve existing trial')
    target.mkdir(parents=True)
    tasks=json.loads(Path(f'data/stage19-unified/benchmark/{args.phase}-tasks.json').read_text(encoding='utf-8'))
    code,health=request('GET','/health')
    if code!=200 or health['candidates']!=10000:raise ValueError('Original shared service not ready')
    start=time.perf_counter();model=load_model()
    import torch,importlib.metadata as m
    save(target/'runtime.json',{'model_load_seconds':time.perf_counter()-start,'torch':torch.__version__,
        'smolagents':m.version('smolagents'),'cuda':torch.cuda.is_available(),'service_instance':health['instance_id'],
        'shared_gpu_environment_read_only':True,'no_new_dependencies':True})
    policies=('fixed','llm_agent','constrained')
    for index,task in enumerate(tasks):
        offset=index%3
        for policy in policies[offset:]+policies[:offset]:
            result=run_constrained(task,model) if policy=='constrained' else run(task,policy,model)
            save(target/f"{task['id']}-{policy}.json",result)
            print(json.dumps({'phase':args.phase,'index':index,'policy':policy,'completed':result['completed_protocol'],
                'seconds':round(result['seconds'],3)}),flush=True)


if __name__=='__main__':main()
