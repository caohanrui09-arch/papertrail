"""Check proposal charging, registered actions and real wire traffic independently."""
from collections import Counter
import json
from pathlib import Path
from gsearch.quality_protocol import digest,save

ROOT=Path('data/stage21-constraints')


def calls(step: dict) -> list[dict]:
    raw=step.get('tool_calls') or (step.get('model_output_message') or {}).get('tool_calls') or []
    return [{'name':(c.get('function') or c)['name'],'arguments':(c.get('function') or c)['arguments']} for c in raw]


def verify_case(raw: dict) -> dict:
    from smolagents.tools import validate_tool_arguments
    from smolagents.default_tools import FinalAnswerTool
    from gsearch.constrained_agent import tools_for
    class NoExecute:
        def call(self,*args,**kwargs):raise AssertionError('Verifier never executes any tool')
    tools={t.name:t for t in tools_for(NoExecute())};tools['final_answer']=FinalAnswerTool()
    tools['final_answer'].inputs['answer']={'type':'object','description':'final object'}
    meta=raw['metadata'];snapshots=meta['constraint_snapshots'];wires=iter(meta['wire_attempts'])
    trace=iter(raw['trace']['trace']);events=[];read=set();returned=set();retrieved=set();charged=0;counts=Counter()
    steps=[s for s in meta['steps'] if 'step_number' in s]
    if len(snapshots)!=len(steps)+1:raise ValueError('Missing callback snapshot')
    for index,step in enumerate(steps):
        state=snapshots[index]
        if set(state['read_ids'])!=read or not set(state['unread_returned_ids']).issubset(returned-read) or state['charged_attempts']!=charged:
            raise ValueError('State contains unobserved/previously-read data or free attempts')
        if any(t in retrieved for t in state['legal_tools'] if t in ('search_papers','recommend_papers')):
            raise ValueError('Successful retrieval remained available')
        for call in calls(step):
            name,args=call['name'],call['arguments'] or {}
            primitive_valid=name in state['legal_tools']
            if primitive_valid:
                try:validate_tool_arguments(tools[name],args)
                except (ValueError,TypeError):primitive_valid=False
            # Invalid root final objects fail the frozen client's exact-field
            # check before any wire call; never guess or repair their contents.
            final_shape_ok=name!='final_answer' or isinstance(args.get('answer'),dict) and set(args['answer'])=={'citations'}
            if primitive_valid and final_shape_ok:
                wire=next(wires)
                expected_name='finalize' if name=='final_answer' else name
                expected_args=args['answer'] if name=='final_answer' else args
                if wire['name']!=expected_name or wire['arguments']!=expected_args:raise ValueError('Arguments changed or automatic call inserted')
                if wire['sent_to_server']:
                    if charged>=6:raise ValueError('Rejected proposal executed outside allowance')
                    if name in ('search_papers','recommend_papers') and (type(args['k']) is not int or not 1<=args['k']<=3):raise ValueError('Invalid k executed')
                    if name=='read_paper' and args['doc_id'] not in state['unread_returned_ids']:raise ValueError('Unavailable ID read')
                    event=next(trace)
                    if event['tool']!=expected_name or event['arguments']!=expected_args:raise ValueError('Unaccounted server traffic')
                    if 'error' not in event['result']:
                        if name in ('search_papers','recommend_papers'):
                            retrieved.add(name);returned.update(p['doc_id'] for p in event['result']['papers'])
                        if name=='read_paper':read.add(event['result']['doc_id'])
                    counts['sent_to_server']+=1
                else:
                    if 'error' not in wire:raise ValueError('Local rejection not recorded')
                    counts['local_guard_rejections']+=1
            else:counts['native_schema_mask_or_root_rejections']+=1
            admitted=charged<6
            if admitted:charged+=1
            events.append({'proposal':call,'charged':admitted,'charged_total':charged})
    if next(wires,None) is not None or next(trace,None) is not None:raise ValueError('Unprompted tool execution exists')
    if charged!=meta['charged_application_attempts']:raise ValueError('Charged counter differs')
    stripped=[{k:e[k] for k in ('proposal','charged','charged_total')} for e in meta['proposal_events']]
    if stripped!=events:raise ValueError('Rejected/model proposals omitted from accounting')
    return dict(counts)


def main() -> None:
    output=Path('reports/stage21/replay-and-errors.json')
    if output.exists():raise ValueError('Preserve prior replay')
    totals=Counter();by_policy={};files=[]
    for split in ('tuning','evaluation'):
        by_policy[split]={}
        for policy in ('fixed','llm_agent','constrained'):
            counts=Counter()
            for path in sorted((ROOT/split).glob(f'{split}-*-{policy}.json')):
                raw=json.loads(path.read_text(encoding='utf-8'));counts['tasks']+=1
                counts['http_rejections']+=sum('error' in t['result'] for t in raw['trace']['trace'])
                for step in raw.get('metadata',{}).get('steps',[]):
                    error=step.get('error') or {}
                    counts['parse_errors']+=error.get('type')=='AgentParsingError'
                    counts['framework_errors_including_terminal']+=bool(error)
                    counts['rejected_parsed_proposals']+=bool(error) and bool(calls(step))
                if policy=='constrained':
                    totals.update(verify_case(raw));files.append({'path':str(path),'sha256':digest(path)})
            by_policy[split][policy]=dict(counts)
    for split,n in [('tuning',4),('evaluation',12)]:
        if any(v['tasks']!=n for v in by_policy[split].values()):raise ValueError('Incomplete three-group comparison')
    source=Path('data/stage19-unified/benchmark/evaluation')
    fixture_names={'null_parameter':'evaluation-003','duplicate_retrieval':'evaluation-001',
        'duplicate_read':'evaluation-002','no_accepted_final':'evaluation-002'}
    fixtures={}
    for kind,task in fixture_names.items():
        path=source/(task+'-llm_agent.json');raw=json.loads(path.read_text(encoding='utf-8'))
        proposals=[c for step in raw['metadata']['steps'] for c in calls(step)]
        trace=raw['trace']['trace']
        if kind=='null_parameter' and not any(isinstance(c['arguments'],dict) and c['arguments'].get('k','absent') is None for c in proposals):raise ValueError('Null fixture not reproduced')
        if kind=='duplicate_retrieval' and max(Counter(t['tool'] for t in trace if t['tool'] in ('search_papers','recommend_papers')).values())<2:raise ValueError('Missing repeat fixture')
        if kind=='duplicate_read' and max(Counter(t['arguments']['doc_id'] for t in trace if t['tool']=='read_paper').values())<2:raise ValueError('Missing read repeat')
        if kind=='no_accepted_final' and raw['completed_protocol']:raise ValueError('Missing final failure')
        fixtures[kind]={'source':str(path),'sha256':digest(path),'original_trace_preserved':True}
    save(output,{'status':'passed','native_constraint_cases_replayed':len(files),'counts':dict(totals),
        'errors_all_locations':by_policy,'failure_fixtures':fixtures,'files':files,
        'automatic_or_argument_repair_calls_found':0,'source_scope':'regression fixtures distinct from real LLM runs'})
    print(json.dumps({'status':'passed','replayed':len(files),'counts':dict(totals)}),flush=True)


if __name__=='__main__':main()
