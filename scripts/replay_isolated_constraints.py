"""Versioned replay: verifier schemas also remain instance-owned."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from gsearch.quality_protocol import digest,save
from scripts.replay_constraint_audit import calls

ROOT=Path('data/stage21-isolated')
REPORT=Path('reports/stage21-isolated')


def verify_case(raw: dict) -> dict:
    from smolagents.tools import validate_tool_arguments
    from smolagents.default_tools import FinalAnswerTool
    from gsearch.constrained_agent import tools_for
    defaults=deepcopy(FinalAnswerTool.inputs)
    class NoExecute:
        def call(self,*args,**kwargs):raise AssertionError('Verifier never executes a tool')
    tools={t.name:t for t in tools_for(NoExecute())};tools['final_answer']=FinalAnswerTool()
    for tool in tools.values():tool.inputs=deepcopy(tool.inputs)
    tools['final_answer'].inputs['answer']={'type':'object','description':'final object'}
    meta=raw['metadata'];snapshots=meta['constraint_snapshots'];wires=iter(meta['wire_attempts'])
    trace=iter(raw['trace']['trace']);events=[];read=set();returned=set();retrieved=set();charged=0;counts=Counter()
    retrieval_charges=0;read_charges=0
    steps=[s for s in meta['steps'] if 'step_number' in s]
    if len(snapshots)!=len(steps)+1:raise ValueError('Missing callback snapshot')
    for index,step in enumerate(steps):
        state=snapshots[index]
        if set(state['read_ids'])!=read or not set(state['unread_returned_ids']).issubset(returned-read) or state['charged_attempts']!=charged:
            raise ValueError('Invented state or free attempts')
        if state['successful_retrievals']!=sorted(retrieved) or state['application_attempts_remaining']!=6-charged:
            raise ValueError('Invented successful retrieval/remaining allowance')
        if state['retrieval_attempts_remaining']!=max(0,2-retrieval_charges) or state['read_attempts_remaining']!=max(0,2-read_charges):
            raise ValueError('Category charges differ from proposals')
        if any(t in retrieved for t in state['legal_tools'] if t in ('search_papers','recommend_papers')):
            raise ValueError('Successful retrieval remained registered')
        for call in calls(step):
            name,args=call['name'],call['arguments'] or {}
            primitive_valid=name in state['legal_tools']
            if primitive_valid:
                try:validate_tool_arguments(tools[name],args)
                except (ValueError,TypeError):primitive_valid=False
            final_ok=name!='final_answer' or isinstance(args.get('answer'),dict) and set(args['answer'])=={'citations'}
            if primitive_valid and final_ok:
                wire=next(wires);expected='finalize' if name=='final_answer' else name
                arguments=args['answer'] if name=='final_answer' else args
                if wire['name']!=expected or wire['arguments']!=arguments:raise ValueError('Automatic call/argument repair')
                if wire['sent_to_server']:
                    if charged>=6:raise ValueError('Application allowance exceeded')
                    if name in ('search_papers','recommend_papers') and retrieval_charges>=2:raise ValueError('Retrieval allowance exceeded')
                    if name=='read_paper' and read_charges>=2:raise ValueError('Read allowance exceeded')
                    if name in ('search_papers','recommend_papers') and (type(args['k']) is not int or not 1<=args['k']<=3):raise ValueError('Invalid k executed')
                    if name=='read_paper' and args['doc_id'] not in state['unread_returned_ids']:raise ValueError('Unavailable read')
                    event=next(trace)
                    if event['tool']!=expected or event['arguments']!=arguments:raise ValueError('Unaccounted server traffic')
                    if 'error' not in event['result']:
                        if name in ('search_papers','recommend_papers'):
                            retrieved.add(name);returned.update(p['doc_id'] for p in event['result']['papers'])
                        if name=='read_paper':read.add(event['result']['doc_id'])
                    counts['sent_to_server']+=1
                else:
                    if 'error' not in wire:raise ValueError('Unrecorded local rejection')
                    counts['local_guard_rejections']+=1
            else:counts['native_schema_mask_or_root_rejections']+=1
            admitted=charged<6
            if admitted:
                charged+=1
                retrieval_charges+=name in ('search_papers','recommend_papers')
                read_charges+=name=='read_paper'
            events.append({'proposal':call,'charged':admitted,'charged_total':charged})
    if next(wires,None) is not None or next(trace,None) is not None:raise ValueError('Unprompted wire call')
    if charged!=meta['charged_application_attempts']:raise ValueError('Logical charging differs')
    last=snapshots[-1]
    if last['charged_attempts']!=charged or set(last['read_ids'])!=read or last['successful_retrievals']!=sorted(retrieved):
        raise ValueError('Final callback state differs')
    if [{k:e[k] for k in ('proposal','charged','charged_total')} for e in meta['proposal_events']]!=events:
        raise ValueError('Proposal ledger differs')
    if FinalAnswerTool.inputs!=defaults:raise ValueError('Verifier polluted native schema')
    return dict(counts)


def main() -> None:
    output=REPORT/'replay-and-errors.json'
    if output.exists():raise ValueError('Preserve existing replay')
    totals=Counter();by_policy={};files=[];schema_guards=0
    for split in ('tuning','evaluation'):
        by_policy[split]={}
        for policy in ('fixed','llm_agent','constrained'):
            counts=Counter()
            for path in sorted((ROOT/split).glob(f'{split}-*-{policy}.json')):
                raw=json.loads(path.read_text(encoding='utf-8'));counts['tasks']+=1
                if raw['metadata'].get('native_default_schema_unchanged') is not True:
                    raise ValueError('Missing per-policy native default guard')
                schema_guards+=1
                counts['http_rejections']+=sum('error' in t['result'] for t in raw['trace']['trace'])
                for step in raw['metadata'].get('steps',[]):
                    error=step.get('error') or {}
                    counts['parse_errors']+=error.get('type')=='AgentParsingError'
                    counts['framework_errors_including_terminal']+=bool(error)
                    counts['rejected_parsed_proposals']+=bool(error) and bool(calls(step))
                if policy=='constrained':
                    if raw['metadata'].get('schema_instances_isolated') is not True:raise ValueError('Missing owned schema proof')
                    totals.update(verify_case(raw));files.append({'path':str(path),'sha256':digest(path)})
            by_policy[split][policy]=dict(counts)
    for split,n in [('tuning',4),('evaluation',12)]:
        if any(v['tasks']!=n for v in by_policy[split].values()):raise ValueError('Incomplete comparison')
    fixtures={}
    sources={'null_parameter':Path('data/stage19-unified/benchmark/evaluation/evaluation-003-llm_agent.json'),
        'duplicate_retrieval':Path('data/stage19-unified/benchmark/evaluation/evaluation-001-llm_agent.json'),
        'duplicate_read_proposal':Path('data/stage21-isolated/tuning/tuning-000-llm_agent.json'),
        'no_accepted_final':Path('data/stage19-unified/benchmark/evaluation/evaluation-002-llm_agent.json')}
    for kind,path in sources.items():
        raw=json.loads(path.read_text(encoding='utf-8'))
        proposals=[c for s in raw['metadata']['steps'] for c in calls(s)]
        if kind=='duplicate_read_proposal':
            ds=[c['arguments']['doc_id'] for c in proposals if c['name']=='read_paper']
            if not ds or max(Counter(ds).values())<2:raise ValueError('No same-ID repeated-read proposal')
        if kind=='duplicate_retrieval':
            ds=[c['name'] for c in proposals if c['name'] in ('search_papers','recommend_papers')]
            if not ds or max(Counter(ds).values())<2:raise ValueError('No repeated retrieval proposal')
        if kind=='null_parameter' and not any(isinstance(c['arguments'],dict) and c['arguments'].get('k','absent') is None for c in proposals):raise ValueError('Missing null')
        if kind=='no_accepted_final' and raw['completed_protocol']:raise ValueError('Missing final failure')
        fixtures[kind]={'source':str(path),'sha256':digest(path),'trace_retained':True}
    save(output,{'status':'passed','native_constraint_cases_replayed':len(files),'counts':dict(totals),
        'errors_all_locations':by_policy,'failure_fixtures':fixtures,'files':files,
        'native_default_schema_guard_passed_cases':schema_guards,'automatic_or_argument_repair_calls_found':0,
        'invalid_v1_metrics_used_as_evidence':False,
        'fixture_mapping_correction':'Old19 evaluation002 made3 distinct reads; first mapped invalid-v1 tuning002 also had no same-ID repeat. Verification rejected the bad mapping. The corrected fixture is valid-v2 tuning000 original-LLM, which proposed the same read ID twice; its raw bytes were frozen before evaluation. No experimental samples or labels changed.'})
    print(json.dumps({'status':'passed','replayed':len(files),'schema_guard_cases':schema_guards}),flush=True)


if __name__=='__main__':main()
