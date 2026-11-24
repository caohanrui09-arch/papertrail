"""Native tool loop with state-dependent registration and strict local gates."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
from .unified_agent import ToolClient
from .state_constraints import ActionState,parsed_calls


class GuardedClient(ToolClient):
    def __init__(self, task: dict, state: ActionState, port: int=8766):
        self.controller=state
        super().__init__(task,port)

    def finalize(self, answer: object) -> dict:
        # Stage88-v2: zero-result runs submit an empty object; map it to the existing
        # {"citations":[]} shape so all validation stays unchanged.
        parsed=json.loads(answer) if isinstance(answer,str) else answer
        if isinstance(parsed,dict) and not parsed and not self.controller.returned:
            parsed={'citations':[]}
        return super().finalize(parsed)

    def call(self, name: str, **arguments: object) -> dict:
        record={'name':name,'arguments':arguments,'sent_to_server':False}
        try:
            self.controller.validate(name,arguments)
            record['sent_to_server']=True
            result=super().call(name,**arguments)
            self.controller.observe(name,result)
            return result
        except ValueError as error:
            record['error']=str(error);raise
        finally:self.controller.wire.append(record)


def tools_for(client: GuardedClient) -> list:
    from smolagents import tool
    @tool
    def search_papers(query: str,k: int) -> str:
        """Search available unread papers once for the supplied query.

        Args:
            query: Original task query, up to2000 characters.
            k: Required nonnullable integer from1 to3.
        """
        return json.dumps(client.call('search_papers',query=query,k=k),ensure_ascii=False)
    @tool
    def recommend_papers(k: int) -> str:
        """Retrieve available unread recommendations once for the bound user.

        Args:
            k: Required nonnullable integer from1 to3.
        """
        return json.dumps(client.call('recommend_papers',k=k),ensure_ascii=False)
    @tool
    def read_paper(doc_id: str) -> str:
        """Read a returned, not-yet-read original v1 source from the current enum.

        Args:
            doc_id: One current unread returned ID; repeated reads are unavailable.
        """
        return json.dumps(client.call('read_paper',doc_id=doc_id),ensure_ascii=False)
    return [search_papers,recommend_papers,read_paper]


def run(task: dict,model: object,port: int=8766) -> dict:
    from smolagents import ToolCallingAgent
    from .bundle_session import BundleBudget
    started=time.perf_counter();state=ActionState(task)
    client=GuardedClient(task,state,port)
    model.reset_budget(BundleBudget(max_steps=8,input_tokens=30000,output_tokens=1280))
    all_tools={}
    def final_check(answer: object,memory: object) -> bool:
        client.finalize(answer);return True
    def after_step(step: object,agent: object) -> None:
        state.charge(parsed_calls(step),str(step.error) if getattr(step,'error',None) else None)
        state.refresh(agent,all_tools)
    agent=ToolCallingAgent(model=model,tools=tools_for(client),max_steps=7,max_tool_threads=1,
        final_answer_checks=[final_check],step_callbacks=[after_step],verbosity_level=0)
    all_tools.update(agent.tools)
    prompt=Path(__file__).parent/'prompts/unified.txt'
    agent.prompt_templates['system_prompt']=prompt.read_text(encoding='utf-8')
    state.refresh(agent,all_tools)
    answer=None;error=None
    try:
        answer=agent.run(json.dumps({key:task[key] for key in ('intent','query','instruction')},ensure_ascii=False))
    except Exception as exc:error=type(exc).__name__+': '+str(exc)
    steps=[step.dict() for step in agent.memory.steps]
    exhausted=any((step.get('error') or {}).get('type')=='AgentMaxStepsError' for step in steps)
    if error is None and not exhausted:
        try:client.finalize(answer)
        except (ValueError,TypeError,json.JSONDecodeError) as exc:error=str(exc)
    result=client.accepted if error is None and not exhausted else None
    trace=client.snapshot();client.close()
    return {'task_id':task['id'],'policy':'constrained','completed_protocol':result is not None,'answer':result,
        'trace':trace,'error':error,'seconds':time.perf_counter()-started,
        'metadata':{'framework_steps_exhausted':exhausted,'steps':steps,'unverified_model_final':str(answer),
            'llm_usage':{k:v for k,v in asdict(model.meter).items() if k!='budget'},
            'prompt_sha256':hashlib.sha256(prompt.read_bytes()).hexdigest(),
            'constraint_snapshots':state.snapshots,'proposal_events':state.events,'wire_attempts':state.wire,
            'charged_application_attempts':state.charged,'no_automatic_calls_or_fallback':True,
            'constraint_kind':'native registration/type schema + state membership; not token-level decoding'}}
