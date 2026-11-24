"""Descriptive failure counts from preserved proposals, separate from relevance."""
from collections import Counter
import json
from pathlib import Path
from scripts.replay_constraint_audit import calls
from scripts.benchmark_isolated_constraints import ROOT,REPORT
from gsearch.quality_protocol import save,digest


def main() -> None:
    path=REPORT/'failure-diagnosis.json'
    if path.exists():raise ValueError('Preserve original diagnosis')
    output={}
    for split in ('tuning','evaluation'):
        summary=json.loads((REPORT/f'{split}-summary.json').read_text())
        cases={(c['policy'],c['task_id']):c for c in summary['cases']}
        output[split]={}
        for policy in ('fixed','llm_agent','constrained'):
            totals=Counter();failures=[]
            for rawpath in sorted((ROOT/split).glob(f'{split}-*-{policy}.json')):
                raw=json.loads(rawpath.read_text(encoding='utf-8'));case=cases[(policy,raw['task_id'])]
                c=Counter(tasks=1)
                c['protocol_incomplete_tasks']=not case['completed']
                c['completed_but_controlled_target_not_met_tasks']=case['completed'] and not case['success']
                c['framework_maxstep_tasks']=raw['metadata'].get('framework_steps_exhausted',False)
                proposals=[call for step in raw['metadata'].get('steps',[]) for call in calls(step)]
                c['parsed_proposals']=len(proposals)
                signatures=Counter(json.dumps(call,sort_keys=True) for call in proposals)
                c['exact_repeated_proposals']=sum(n-1 for n in signatures.values())
                read_ids=Counter(call['arguments'].get('doc_id') for call in proposals
                    if call['name']=='read_paper' and isinstance(call['arguments'],dict))
                c['same_id_repeated_read_proposals']=sum(n-1 for n in read_ids.values())
                for call in proposals:
                    args=call['arguments']
                    if call['name'] in ('search_papers','recommend_papers') and isinstance(args,dict) and 'k' in args:
                        c['null_k_proposals']+=args['k'] is None
                totals.update(c)
                if not case['success']:failures.append({'task_id':raw['task_id'],'raw_path':str(rawpath),
                    'sha256':digest(rawpath),'intent':case['intent'],'cold_user':case['cold_user'],
                    'completed_protocol':case['completed'],'counts':dict(c)})
            output[split][policy]={'counts':dict(totals),'unsuccessful_cases':failures}
    save(path,{'results':output,'scope':'Overlapping diagnostics, not additive failure categories. Exact duplicate proposals include retries of previously rejected calls; they do not imply extra HTTP execution. Completed target mismatch refers only to known-item controlled gold, not semantic relevance.',
        'selection_used_future_or_gold_for_controller':False,'invalid_v1_comparison_used':False})
    print(json.dumps({'saved':str(path)}))


if __name__=='__main__':main()
