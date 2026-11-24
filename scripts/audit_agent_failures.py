"""Forensic categories from frozen stage19 traces; no new LLM judgments."""
from collections import Counter
import json
from pathlib import Path

from gsearch.quality_protocol import digest, save, write_csv


def main() -> None:
    root = Path('data/stage19-unified/benchmark')
    output = Path('reports/stage20/agent-failure-audit.json')
    if output.exists(): raise ValueError('Preserve existing audit')
    tasks = {q['id']:q for q in json.loads((root/'evaluation-tasks.json').read_text(encoding='utf-8'))}
    totals, cases, private = Counter(), [], []
    for path in sorted((root/'evaluation').glob('*-llm_agent.json')):
        result = json.loads(path.read_text(encoding='utf-8'))
        task = tasks[result['task_id']]
        trace = result['trace']['trace']
        seen, counts = set(), Counter()
        details = []
        successful = set()
        reads = []
        for i, event in enumerate(trace):
            name, args = event['tool'],event['arguments']
            key = (name,json.dumps(args,sort_keys=True,ensure_ascii=False))
            if key in seen:
                counts['duplicate_tool_attempts'] += 1
                if name == 'read_paper': counts['duplicate_read_attempts'] += 1
            seen.add(key)
            error = event['result'].get('error','')
            if error:
                if 'budget' in error.lower(): counts['budget_rejections'] += 1
                elif any(term in error for term in ('Integer k','Nonempty query','Invalid request','unexpected keyword','missing')):
                    counts['invalid_parameter_rejections'] += 1
                elif any(term in error for term in ('returned in this session','successfully read IDs','quote index')):
                    counts['structural_paper_selection_rejections'] += 1
                else: counts['other_tool_rejections'] += 1
                details.append({'trace_index':i,'tool':name,'arguments':args,'error':error})
            else:
                successful.add(name)
                if name == 'read_paper': reads.append(event['result']['doc_id'])
        steps = result['metadata'].get('steps',[])
        for step in steps:
            error = step.get('error') or {}
            if error.get('type') == 'AgentParsingError': counts['model_call_parse_errors'] += 1
            if error.get('type') == 'AgentMaxStepsError': counts['framework_step_exhaustions'] += 1
        required = {'search_papers'} if task['intent'] in ('search','empty') else {'recommend_papers'} if task['intent']=='recommend' else {'search_papers','recommend_papers'}
        missing = sorted(required-successful)
        completed = result['completed_protocol']
        if not completed: counts['no_accepted_final_answer'] += 1
        if missing: counts['missing_required_retrieval_route'] += 1
        category = 'completed' if completed else 'invalid_parameters_before_retrieval' if not successful and counts['invalid_parameter_rejections'] else 'duplicate_retrieval_loop' if not reads and counts['duplicate_tool_attempts'] else 'read_or_route_loop_before_final'
        totals.update(counts)
        entry = {'task_id':result['task_id'],'intent':task['intent'],'completed':completed,
            'observed_failure_stage':category,'missing_required_tools':missing,
            'successful_read_calls':len(reads),'distinct_read_papers':len(set(reads)),
            'events':dict(counts),'semantic_paper_selection':'not_assessable_without_human_relevance_labels',
            'input_sha256':digest(path)}
        cases.append(entry)
        private.append({**entry,'rejected_tool_events':details})
    if len(cases)!=12: raise ValueError('Expected all12 formal LLM outputs')
    # This audit identifies observable events, not exclusive psychological causes.
    summary={'tasks':12,'completed':sum(c['completed'] for c in cases),'failed':sum(not c['completed'] for c in cases),
        'event_totals':dict(totals),'cases_with_event':{name:sum(c['events'].get(name,0)>0 for c in cases) for name in totals},
        'failure_stage_counts':dict(Counter(c['observed_failure_stage'] for c in cases)),
        'categories_overlap':True,'semantic_wrong_paper_count':None,
        'semantic_selection_requires_human_labels':True,
        'interface_findings':'Omitted k produces default3 successfully in frozen native tools. Explicit model null/boolean remains invalid, never silently defaulted. Repeated reads/retrievals deliberately consume budgets. No backend interface fix asserted without a reproducible failing valid request.',
        'new_llm_runs':0,'historical_outputs_modified':False,'cases':cases}
    save(output,summary)
    save(Path('.cache/stage20/agent-failures-private.json'),private)
    write_csv(Path('data/stage20-quality/evaluator/agent-failure-review.csv'),
        ['task_id','intent','completed','observed_failure_stage','semantic_selection_status'],
        [{'task_id':c['task_id'],'intent':c['intent'],'completed':c['completed'],'observed_failure_stage':c['observed_failure_stage'],
          'semantic_selection_status':'awaiting_human_relevance_judgments'} for c in cases])
    print(json.dumps({k:summary[k] for k in ('tasks','completed','failed','event_totals','failure_stage_counts')}),flush=True)


if __name__=='__main__':main()
