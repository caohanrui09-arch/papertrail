"""Protocol completion/source audit/cost; never semantic correctness scoring."""
from collections import defaultdict,Counter
import json
from pathlib import Path

from research73.common import ROOT,DATA,read,value_hash,digest


def public_row(row: dict) -> dict:
    value={k:v for k,v in row.items() if k!='metadata'};meta=dict(row.get('metadata') or {})
    meta.pop('unverified_model_final',None)
    meta['steps']=[{k:s[k] for k in ('step_number','timing','tool_calls','error','token_usage','is_final_answer') if k in s} for s in meta.get('steps',[]) if 'step_number' in s]
    value['metadata']=meta;return value


def report() -> dict:
    order=read(DATA/'inputs/run-order.json');rows=[];methods=defaultdict(list);docs={d['doc_id']:d for d in read(ROOT/'data/stage13-expansion/documents.json')}
    for cell in order:
        base=DATA/'agent-runs'/cell['cell'];path=base/'result.json'
        if not path.exists():
            rows.append({**cell,'status':'running' if (base/'started.json').exists() else 'not_started'});continue
        raw=read(path);trace=(raw.get('trace') or {}).get('trace',[])
        from research70.event_stream import available
        events,_=available(base/'events.jsonl')
        if raw.get('failure_kind') in ('execution_timeout_unattributed','infrastructure_interruption') and not trace:
            trace=[e['payload'] for e in events if e['kind']=='tool_returned']
        reads={e['result']['doc_id']:e['result'] for e in trace if e['tool']=='read_paper' and not e['result'].get('error')}
        citations=(raw.get('answer') or {}).get('citations',[]);checks=[]
        for c in citations:
            source=docs.get(c['doc_id']);read_original=reads.get(c['doc_id'])
            checks.append(bool(source and read_original and c['quote'] in read_original['abstract'] and read_original['abstract']==source['abstract'] and c['version_key']==source['version_key'] and c['source_url']==source['source_url'] and digest(ROOT/Path(source['provenance']['raw_path']))==source['provenance']['raw_sha256']))
        exposure={};arguments=[]
        for e in trace:
            if e['tool'] in ('search_papers','recommend_papers'):
                arguments.append({'tool':e['tool'],'arguments':e['arguments'],'error':e['result'].get('error')})
                if not e['result'].get('error'):exposure.setdefault(e['tool'],[]).append([p['doc_id'] for p in e['result']['papers']])
        meta=raw.get('metadata') or {};usage=meta.get('llm_usage') or {};proposals=meta.get('proposal_events',[])
        errors=[e['payload'] for e in events if e['kind']=='tool_rejected']
        gateway_fail=sum(bool(e['result'].get('error')) for e in trace)
        state_fail=sum(bool(p.get('error')) for p in proposals)
        error_types=Counter((s.get('error') or {}).get('type','unknown') for s in meta.get('steps',[]) if s.get('error'))
        signatures=[value_hash([e['tool'],e['arguments']]) for e in trace]
        unique_ids=sorted({d for lists in exposure.values() for ids in lists for d in ids})
        kind=raw.get('failure_kind')
        reason=raw.get('error') or meta.get('error') or ('framework step budget exhausted' if meta.get('framework_steps_exhausted') else 'No accepted final submission' if not raw.get('completed_protocol') else None)
        record={**cell,'status':'complete','completed_protocol':raw.get('completed_protocol',False),'failure_kind':kind,'failure_reason':reason,
                'gateway_executions':len(trace),'gateway_execution_failures':gateway_fail,'client_or_gateway_rejections':len(errors),'constraint_proposal_errors':state_fail,'model_step_error_types':dict(error_types),'repeated_gateway_tool_signatures':len(signatures)-len(set(signatures)),
                'charged_application_actions':meta.get('charged_application_attempts',len(trace)),
                'model_calls':usage.get('calls',0),'input_tokens':usage.get('input_tokens',0),'output_tokens':usage.get('output_tokens',0),
                'execution_seconds':raw.get('seconds'),'wall_seconds':raw.get('wall_seconds'),'citations':len(citations),'citation_source_checks_passed':sum(checks),
                'citation_checks_total':len(checks),'source_check_status':'all_passed' if checks and all(checks) else 'no_citations' if not checks else 'failed',
                'retrieval_arguments':arguments,'candidate_exposure':exposure,'candidate_exposure_sha256':value_hash(exposure),'unique_exposed_ids':unique_ids,'unique_exposure_sha256':value_hash(unique_ids),
                'semantic_correctness':None,'needs_further_failure_inspection':bool(not raw.get('completed_protocol') and not reason)}
        methods[cell['policy']].append(record);rows.append(record)
    summary={}
    for policy in ('fixed','llm_agent','constrained'):
        items=methods[policy];completed=sum(r['completed_protocol'] for r in items)
        summary[policy]={'planned':4,'finished':len(items),'protocol_completed':completed,'protocol_completion_rate_over_planned':completed/4,
            'gateway_execution_failures':sum(r['gateway_execution_failures'] for r in items),'client_or_gateway_rejections':sum(r['client_or_gateway_rejections'] for r in items),
            'constraint_proposal_errors':sum(r['constraint_proposal_errors'] for r in items),
            'model_calls':sum(r['model_calls'] for r in items),'input_tokens':sum(r['input_tokens'] for r in items),'output_tokens':sum(r['output_tokens'] for r in items),
            'execution_seconds':sum(r.get('execution_seconds') or 0 for r in items),'wall_seconds':sum(r.get('wall_seconds') or 0 for r in items),
            'citation_checks_total':sum(r['citation_checks_total'] for r in items),'citation_source_checks_passed':sum(r['citation_source_checks_passed'] for r in items)}
    differences=[]
    for task in read(DATA/'inputs/agent-tasks.json'):
        items=[r for r in rows if r['task_id']==task['id'] and r['status']=='complete']
        differences.append({'task_id':task['id'],'policies_finished':len(items),'same_observed_candidates':len({r['candidate_exposure_sha256'] for r in items})==1 if len(items)==3 else None,'same_unique_document_set':len({r['unique_exposure_sha256'] for r in items})==1 if len(items)==3 else None,
                            'actual_exposure':{r['policy']:r['candidate_exposure'] for r in items}})
    return {'scope':'stage73 frozen reused controlled tasks; completion/source checks are not semantic correctness',
            'planned':12,'finished':sum(r['status']=='complete' for r in rows),'methods':summary,'rows':rows,'candidate_exposure_differences':differences,
            'runtime':read(DATA/'agent-runtime.json') if (DATA/'agent-runtime.json').exists() else None,
            'pure_scheduling_gain_claim':False,'semantic_quality_claim':False,'human_labels_used':0,
            'counting_note':'gateway failures, rejected calls and proposal errors overlap; do not sum them as unique failures. Unfinished cells remain in planned denominator.'}
