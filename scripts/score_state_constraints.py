"""Reuse the frozen source/contract scorer through byte-identical file views."""
import argparse
import json
from pathlib import Path
import shutil
from collections import Counter
from gsearch.quality_protocol import save,digest
from scripts import score_unified as original

ROOT=Path('data/stage21-constraints')
REPORT=Path('reports/stage21')


def view_score(split: str,policy: str) -> dict:
    view=ROOT/'scoring-views'/f'{split}-{policy}'
    aliases={}
    if not view.exists():
        (view/split).mkdir(parents=True)
        for kind in ('tasks','gold'):
            source=Path(f'data/stage19-unified/benchmark/{split}-{kind}.json')
            target=view/source.name;shutil.copy2(source,target)
            aliases[str(target)]={'source':str(source),'sha256':digest(source)}
        tasks=json.loads((view/f'{split}-tasks.json').read_text(encoding='utf-8'))
        for task in tasks:
            for alias,actual in [('fixed','fixed'),('llm_agent',policy)]:
                source=ROOT/split/f"{task['id']}-{actual}.json"
                target=view/split/f"{task['id']}-{alias}.json"
                shutil.copy2(source,target)
                aliases[str(target)]={'source':str(source),'sha256':digest(source),'actual_policy':actual}
        save(view/'file-aliases.json',aliases)
    for name,item in json.loads((view/'file-aliases.json').read_text()).items():
        if digest(Path(name))!=item['sha256'] or digest(Path(item['source']))!=item['sha256']:
            raise ValueError('Evaluator file view differs from original bytes')
    previous=original.ROOT
    try:
        original.ROOT=view
        result=original.score(split)
    finally:original.ROOT=previous
    for case in result['cases']:
        if case['policy']=='llm_agent':case['policy']=policy
    if policy!='llm_agent':result['methods'][policy]=result['methods'].pop('llm_agent')
    return result


def summarize(split: str) -> dict:
    a=view_score(split,'llm_agent');b=view_score(split,'constrained')
    if a['methods']['fixed']!=b['methods']['fixed']:raise ValueError('Shared fixed baseline differs')
    methods={**a['methods'],**b['methods']}
    cases=[c for c in a['cases']]+[c for c in b['cases'] if c['policy']=='constrained']
    interventions=Counter()
    for path in sorted((ROOT/split).glob(f'{split}-*-constrained.json')):
        raw=json.loads(path.read_text(encoding='utf-8'));meta=raw['metadata']
        charged=sum(e['charged'] for e in meta['proposal_events'])
        if charged!=meta['charged_application_attempts'] or charged>6:
            raise ValueError('Equivalent application charging invalid')
        events=meta['proposal_events'];snapshots=meta['constraint_snapshots']
        active_steps=[s for s in meta['steps'] if 'step_number' in s]
        if len(snapshots)!=len(active_steps)+1:raise ValueError('Native callback/state snapshot missing')
        for index,step in enumerate(active_steps):
            if step.get('model_output_message'):
                interventions['model_steps_with_state']+=1
                if len(snapshots[index]['legal_tools'])==1:interventions['single_registered_tool_steps']+=1
            if index and snapshots[index]['legal_tools']!=snapshots[index-1]['legal_tools']:
                interventions['toolset_changes']+=1
        interventions['charged_application_attempts']+=charged
        interventions['parsed_proposals']+=len(events)
        interventions['proposal_rejections']+=sum(bool(e['error']) for e in events)
        interventions['local_guard_rejections']+=sum(not e['sent_to_server'] for e in meta['wire_attempts'])
        interventions['native_schema_or_mask_rejections']+=sum(bool(e['error']) for e in events)-sum('error' in e for e in meta['wire_attempts'])
        for event in events:
            if event['charged'] and event['charged_total']>6:raise ValueError('Logical budget exceeded')
        if sum(t['tool'] in ('search_papers','recommend_papers') and 'error' not in t['result'] for t in raw['trace']['trace'])>2:
            raise ValueError('Retrieval budget exceeded')
    fixed,old,new=(methods[p] for p in ('fixed','llm_agent','constrained'))
    oldtokens=old['input_tokens']+old['output_tokens'];newtokens=new['input_tokens']+new['output_tokens']
    guards={'success_at_least_fixed':new['task_success']>=fixed['task_success'],
        'no_budget_violation':all(m['all_budgets_pass'] for m in methods.values()),
        'mean_time_ratio_to_original_lte_0.8':new['mean_seconds']<=.8*old['mean_seconds'],
        'token_total_ratio_to_original_lte_0.8':newtokens<=.8*oldtokens,
        'mean_time_ratio_to_fixed_lte5':new['mean_seconds']<=5*fixed['mean_seconds']}
    return {'split':split,'methods':methods,'cases':cases,'constraint_interventions':dict(interventions),
        'engineering_guards':guards,'engineering_guards_all_pass':all(guards.values()),
        'decision':'retain_as_experimental_only' if all(guards.values()) else 'keep_fixed_and_end_this_optimization_round',
        'default_policy':'fixed','scope':'reused controlled explicit-intent protocol; no independent or semantic relevance/LLM reasoning superiority claim',
        'frozen_native_scorer_reused':True,'native_scorer_source_sha256':digest(Path('scripts/score_unified.py')),
        'evaluator_views_are_byte_identical_with_explicit_filename_aliases':True}


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument('--split',choices=('tuning','evaluation'),required=True);args=parser.parse_args()
    output=REPORT/f'{args.split}-summary.json'
    if output.exists():raise ValueError('Preserve existing score')
    result=summarize(args.split);save(output,result)
    print(json.dumps({'methods':result['methods'],'engineering_guards':result['engineering_guards'],
        'interventions':result['constraint_interventions']},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
