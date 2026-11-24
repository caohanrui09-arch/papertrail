"""Stage83: score the 0.5B ladder arm and compare it with the retained 1.5B batch."""
import json
from pathlib import Path

from scripts.audit_agent_reliability import analyse

ROOT = Path(__file__).resolve().parents[1]
LOWER = ROOT / 'data/stage83-batch/result.json'
BASELINE = ROOT / 'reports/stage82/batch-summary.json'
OUT = ROOT / 'reports/stage83/ladder-summary.json'


def failure_kinds(run: dict) -> dict:
    counts = {}
    for step in (run.get('metadata') or {}).get('steps') or []:
        kind = (step.get('error') or {}).get('type') or 'none'
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def main() -> None:
    value = json.loads(LOWER.read_text(encoding='utf8'))
    lower = []
    for index, run in enumerate(value['results']):
        row = analyse(run)
        row['run_index'] = index
        row['step_errors'] = failure_kinds(run)
        lower.append(row)

    baseline_raw = json.loads((ROOT / 'data/stage82-batch/result.json').read_text(encoding='utf8'))
    base_rows = []
    for index, run in enumerate(baseline_raw['results']):
        row = analyse(run)
        row['run_index'] = index
        row['step_errors'] = failure_kinds(run)
        base_rows.append(row)

    def summary(rows):
        return {
            'runs': len(rows),
            'completed': sum(1 for r in rows if r['completed_protocol']),
            'causes': {cause: sum(1 for r in rows if r['failure_cause'] == cause)
                       for cause in sorted({r['failure_cause'] for r in rows})},
            'parse_errors': sum(r['step_errors'].get('AgentParsingError', 0) for r in rows),
            'tool_errors': sum(r['step_errors'].get('AgentToolExecutionError', 0) for r in rows),
            'rejections': sum(r['state_rejections'] for r in rows),
        }

    by_task = {}
    for label, rows in (('0.5B', lower), ('1.5B', base_rows)):
        for row in rows:
            bucket = by_task.setdefault(row['task_id'], {}).setdefault(label, {'runs': 0, 'completed': 0})
            bucket['runs'] += 1
            bucket['completed'] += 1 if row['completed_protocol'] else 0

    result = {
        'scope': 'stage83 model ladder: same harness and tasks, only the model differs',
        'protocol': 'stage83-model-ladder-v1',
        'lower': {'model': 'Qwen2.5-0.5B-Instruct', **summary(lower), 'rows': lower},
        'baseline': {'model': 'Qwen2.5-1.5B-Instruct', **summary(base_rows)},
        'by_task': by_task,
        'note': 'one lower ladder point; it cannot establish where a capacity threshold is'
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')

    print(json.dumps({'0.5B': {k: result['lower'][k] for k in ('runs', 'completed', 'causes', 'parse_errors', 'rejections')},
                      '1.5B': {k: result['baseline'][k] for k in ('runs', 'completed', 'causes', 'parse_errors', 'rejections')}},
                     ensure_ascii=False, indent=2))
    for row in lower:
        print(f"#{row['run_index']} {row['task_id']:<14} complete={row['completed_protocol']!s:<5} "
              f"charged={row['charged_attempts']} rej={row['state_rejections']} "
              f"steps={row['steps_recorded']} calls={row['llm_calls']} parse_err={row['step_errors'].get('AgentParsingError', 0)} "
              f"{row['failure_cause']}")


if __name__ == '__main__':
    main()
