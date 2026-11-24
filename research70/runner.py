"""Versioned adapters derived from local frozen policy orchestration; native loops reused.
Only client observation and native callbacks added. See adapter-provenance.json.
"""
from dataclasses import asdict
from copy import deepcopy
import hashlib,json,time
from pathlib import Path
from gsearch.unified_agent import fixed,make_tools,__file__ as NATIVE_POLICY_FILE
from gsearch.schema_isolation import IsolatedActionState
from gsearch.state_constraints import parsed_calls
from gsearch.constrained_agent import tools_for
from research70.observability import ObservedClient as ToolClient,ObservedGuardedClient as GuardedClient

def observed_llm(client: ToolClient, task: dict, model: object, observer) -> tuple[dict | None, dict]:
    from smolagents import ToolCallingAgent
    from gsearch.bundle_session import BundleBudget
    model.reset_budget(BundleBudget(max_steps=8, input_tokens=30000, output_tokens=1280))

    def final_check(answer: object, agent: object) -> bool:
        client.finalize(answer)
        return True

    agent = ToolCallingAgent(model=model, tools=make_tools(client), max_steps=7, max_tool_threads=1,
        final_answer_checks=[final_check], step_callbacks=[observer.model_step], verbosity_level=0)
    prompt = Path(NATIVE_POLICY_FILE).parent / 'prompts/unified.txt'
    agent.prompt_templates['system_prompt'] = prompt.read_text(encoding='utf-8')
    answer = None
    error = None
    try:
        answer = agent.run(json.dumps({key: task[key] for key in ('intent', 'query', 'instruction')}, ensure_ascii=False))
    except Exception as exc:
        error = type(exc).__name__ + ': ' + str(exc)
    steps = [step.dict() for step in agent.memory.steps]
    exhausted = any(step.get('error', {}).get('type') == 'AgentMaxStepsError' for step in steps if step.get('error'))
    if error is None and not exhausted:
        try:
            client.finalize(answer)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            error = str(exc)
    result = client.accepted if error is None and not exhausted else None
    return result, {'error': error, 'framework_steps_exhausted': exhausted, 'steps': steps,
        'unverified_model_final': str(answer), 'llm_usage': {k: v for k, v in asdict(model.meter).items() if k != 'budget'},
        'prompt_sha256': hashlib.sha256(prompt.read_bytes()).hexdigest()}


def observed_run(task: dict, policy: str, model: object | None = None, port: int = 8766, observer=None) -> dict:
    start = time.perf_counter()
    client = ToolClient(task, port,observer=observer)
    result = None
    metadata = {}
    error = None
    try:
        if policy == 'fixed':
            result = fixed(client, task)
        elif policy == 'llm_agent':
            result, metadata = observed_llm(client, task, model, observer)
        else:
            raise ValueError('Unknown policy')
    except Exception as exc:
        error = type(exc).__name__ + ': ' + str(exc)
    finally:
        trace = client.snapshot()
        client.close()
    return {'task_id': task['id'], 'policy': policy, 'completed_protocol': result is not None,
        'answer': result, 'trace': trace, 'metadata': metadata, 'error': error,
        'seconds': time.perf_counter() - start}


def observed_constrained(task: dict,model: object,observer,port: int=8766) -> dict:
    from smolagents import ToolCallingAgent
    from smolagents.default_tools import FinalAnswerTool
    from gsearch.bundle_session import BundleBudget
    native_default=deepcopy(FinalAnswerTool.inputs)
    started=time.perf_counter();state=IsolatedActionState(task)
    client=GuardedClient(task,state,port,observer=observer)
    model.reset_budget(BundleBudget(max_steps=8,input_tokens=30000,output_tokens=1280))
    all_tools={}
    def final_check(answer: object,memory: object) -> bool:
        client.finalize(answer);return True
    def after_step(step: object,agent: object) -> None:
        state.charge(parsed_calls(step),str(step.error) if getattr(step,'error',None) else None)
        state.refresh(agent,all_tools)
        observer.model_step(step,agent)
        observer.record('constraint_state',state.snapshots[-1])
    agent=ToolCallingAgent(model=model,tools=tools_for(client),max_steps=7,max_tool_threads=1,
        final_answer_checks=[final_check],step_callbacks=[after_step],verbosity_level=0)
    all_tools.update(agent.tools)
    prompt=Path(NATIVE_POLICY_FILE).parent/'prompts/unified.txt'
    agent.prompt_templates['system_prompt']=prompt.read_text(encoding='utf-8')
    state.refresh(agent,all_tools)
    answer=None;error=None
    try:answer=agent.run(json.dumps({key:task[key] for key in ('intent','query','instruction')},ensure_ascii=False))
    except Exception as exc:error=type(exc).__name__+': '+str(exc)
    steps=[step.dict() for step in agent.memory.steps]
    exhausted=any((step.get('error') or {}).get('type')=='AgentMaxStepsError' for step in steps)
    if error is None and not exhausted:
        try:client.finalize(answer)
        except (ValueError,TypeError,json.JSONDecodeError) as exc:error=str(exc)
    result=client.accepted if error is None and not exhausted else None
    trace=client.snapshot();client.close()
    if FinalAnswerTool.inputs!=native_default:raise ValueError('Native default schema changed')
    return {'task_id':task['id'],'policy':'constrained','completed_protocol':result is not None,'answer':result,
        'trace':trace,'error':error,'seconds':time.perf_counter()-started,
        'metadata':{'framework_steps_exhausted':exhausted,'steps':steps,'unverified_model_final':str(answer),
            'llm_usage':{k:v for k,v in asdict(model.meter).items() if k!='budget'},
            'prompt_sha256':hashlib.sha256(prompt.read_bytes()).hexdigest(),
            'constraint_snapshots':state.snapshots,'proposal_events':state.events,'wire_attempts':state.wire,
            'charged_application_attempts':state.charged,'no_automatic_calls_or_fallback':True,
            'schema_instances_isolated':True,'native_default_schema_unchanged':True,
            'constraint_kind':'native registration/type schema + state membership; not token-level decoding'}}
