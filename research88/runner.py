"""Stage88 worker: the same loop and budgets as research71, plus constrained decoding.

Only the state class (publishes a decoding schema) and the model class change; tools,
budgets, events, validation and recovery are the originals.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import time
from pathlib import Path

from gsearch.budget_model import BundleBudget
from gsearch.constrained_agent import tools_for
from gsearch.state_constraints import parsed_calls
from research70.runner import observed_run as preset_run
from research70.runner import observed_constrained as preset_constrained
from research71.runner import observed_run as custom_run
from research71.runner import observed_constrained as guarded_constrained
from research71.clients import ObservedCustomClient as ToolClient
from research71.clients import ObservedCustomGuardedClient as GuardedClient
from research88.constrained import ConstrainedActionState, load_model

MODEL_ID = '.cache/models/Qwen2.5-1.5B-Instruct'


def observed_constrained(task: dict, model: object, observer, port: int = 8766) -> dict:
    from smolagents import ToolCallingAgent
    from smolagents.default_tools import FinalAnswerTool

    native_default = deepcopy(FinalAnswerTool.inputs)
    started = time.perf_counter()
    state = ConstrainedActionState(task)
    client = GuardedClient(task, state, port, observer=observer)
    model.reset_budget(BundleBudget(max_steps=8, input_tokens=30000, output_tokens=1280))
    all_tools = {}

    def final_check(answer: object, memory: object) -> bool:
        client.finalize(answer)
        return True

    def after_step(step: object, agent: object) -> None:
        state.charge(parsed_calls(step), str(step.error) if getattr(step, 'error', None) else None)
        state.refresh(agent, all_tools)
        observer.model_step(step, agent)
        observer.record('constraint_state', state.snapshots[-1])

    agent = ToolCallingAgent(model=model, tools=tools_for(client), max_steps=7, max_tool_threads=1,
        final_answer_checks=[final_check], step_callbacks=[after_step], verbosity_level=0)
    all_tools.update(agent.tools)
    prompt = Path(__file__).resolve().parents[1] / 'research71/prompts/custom.txt'
    agent.prompt_templates['system_prompt'] = prompt.read_text(encoding='utf-8')
    state.refresh(agent, all_tools)
    answer = None
    error = None
    try:
        answer = agent.run(json.dumps({key: task[key] for key in ('intent', 'query', 'instruction')}, ensure_ascii=False))
    except Exception as exc:
        error = type(exc).__name__ + ': ' + str(exc)
    steps = [step.dict() for step in agent.memory.steps]
    exhausted = any((step.get('error') or {}).get('type') == 'AgentMaxStepsError' for step in steps)
    if error is None and not exhausted:
        try:
            client.finalize(answer)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            error = str(exc)
    result = client.accepted if error is None and not exhausted else None
    trace = client.snapshot()
    client.close()
    if FinalAnswerTool.inputs != native_default:
        raise ValueError('Native default schema changed')
    return {'task_id': task['id'], 'policy': 'constrained', 'completed_protocol': result is not None,
            'answer': result, 'trace': trace, 'error': error, 'seconds': time.perf_counter() - started,
            'metadata': {'framework_steps_exhausted': exhausted, 'steps': steps,
                'unverified_model_final': str(answer),
                'llm_usage': {k: v for k, v in model.meter.__dict__.items() if k != 'budget'},
                'prompt_sha256': hashlib.sha256(prompt.read_bytes()).hexdigest(),
                'constraint_snapshots': state.snapshots, 'proposal_events': state.events,
                'wire_attempts': state.wire, 'charged_application_attempts': state.charged,
                'decoding': 'grammar-constrained tool envelope',
                'no_automatic_calls_or_fallback': True,
                'schema_instances_isolated': True, 'native_default_schema_unchanged': True,
                'constraint_kind': 'native registration/type schema + state membership + constrained decoding'}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--events', required=True)
    parser.add_argument('--port', type=int, default=8802)
    parser.add_argument('--model', default=MODEL_ID)
    args = parser.parse_args()
    from research70.observability import EventJournal, atomic_json
    journal = EventJournal(Path(args.events))
    journal.record('job_started', {'state': 'worker entered', 'decoding': 'constrained', 'model': args.model})
    try:
        spec = json.loads(Path(args.input).read_text())
        results = []
        model = None
        for task in spec['tasks']:
            for policy in spec['policies']:
                journal.context_for(task['id'], policy, len(results))
                if policy != 'fixed' and model is None:
                    journal.record('model_loading', {'model': args.model})
                    model = load_model(args.model)
                    journal.record('model_ready', {'state': 'native model loaded'})
                journal.record('run_started', {'intent': task['intent'], 'task_kind': task.get('task_kind', 'preset')})
                if policy == 'constrained':
                    result = observed_constrained(task, model, journal, port=args.port)
                elif policy == 'guarded':
                    runner = guarded_constrained if task.get('task_kind') == 'custom' else preset_constrained
                    result = runner(task, model, journal, port=args.port)
                    result['policy'] = 'guarded'
                else:
                    runner = custom_run if task.get('task_kind') == 'custom' else preset_run
                    result = runner(task, policy, model, port=args.port, observer=journal)
                results.append(result)
                atomic_json(Path(args.output), {'complete': False, 'results': results,
                                                'observability_errors': journal.errors, 'task_context': spec.get('task_context')})
                journal.record('run_completed', {'completed_protocol': result['completed_protocol'],
                    'seconds': result['seconds'], 'error': result.get('error'), 'tool_attempts': len(result['trace']['trace'])})
        atomic_json(Path(args.output), {'complete': True, 'results': results,
                                        'observability_errors': journal.errors, 'task_context': spec.get('task_context')})
        journal.record('job_finished', {'results': len(results), 'observability_errors': journal.errors})
    except Exception as error:
        journal.record('worker_failed', {'error': type(error).__name__ + ': ' + str(error)})
        raise


if __name__ == '__main__':
    main()
