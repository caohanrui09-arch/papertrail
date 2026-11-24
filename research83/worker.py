"""Stage83 worker: same policies, journals and budgets as research71.worker, only the model differs."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

MODEL_ID = '.cache/models/Qwen2.5-0.5B-Instruct'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--events', required=True)
    parser.add_argument('--port', type=int, default=8802)
    parser.add_argument('--model', default=MODEL_ID)
    args = parser.parse_args()
    model_id = args.model
    from research70.observability import EventJournal, atomic_json
    journal = EventJournal(Path(args.events))
    journal.record('job_started', {'state': 'worker entered', 'model': model_id})
    try:
        from research70.runner import observed_run, observed_constrained
        from research71.runner import observed_run as custom_run, observed_constrained as custom_constrained
        from smolagents.default_tools import FinalAnswerTool
        from research83.loader import load_model
        spec = json.loads(Path(args.input).read_text())
        results = []
        model = None
        defaults = deepcopy(FinalAnswerTool.inputs)
        for task in spec['tasks']:
            for policy in spec['policies']:
                journal.context_for(task['id'], policy, len(results))
                if policy != 'fixed' and model is None:
                    journal.record('model_loading', {'model': model_id})
                    model = load_model(model_id)
                    journal.record('model_ready', {'state': 'native model loaded'})
                assert FinalAnswerTool.inputs == defaults
                journal.record('run_started', {'intent': task['intent'], 'task_kind': task.get('task_kind', 'preset')})
                run_constrained = custom_constrained if task.get('task_kind') == 'custom' else observed_constrained
                run_policy = custom_run if task.get('task_kind') == 'custom' else observed_run
                result = run_constrained(task, model, journal, port=args.port) if policy == 'constrained' else run_policy(task, policy, model, port=args.port, observer=journal)
                assert FinalAnswerTool.inputs == defaults
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

