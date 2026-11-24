"""Stage88: score the constrained-decoding batch against the stage82 baseline."""
import json
from pathlib import Path

from scripts.audit_agent_reliability import analyse

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / 'data/stage88-batch/result.json'
BASE = ROOT / 'data/stage82-batch/result.json'
OUT = ROOT / 'reports/stage88/batch-summary.json'


def rows(path: Path) -> list[dict]:
    value = json.loads(path.read_text(encoding='utf8'))
    out = []
    for index, run in enumerate(value['results']):
        row = analyse(run)
        steps = (run.get('metadata') or {}).get('steps') or []
        row['parse_errors'] = sum(1 for s in steps if (s.get('error') or {}).get('type') == 'AgentParsingError')
        row['run_index'] = index
        out.append(row)
    return out


def by_task(rows_in: list[dict]) -> dict:
    result = {}
    for row in rows_in:
        bucket = result.setdefault(row['task_id'], {'runs': 0, 'completed': 0})
        bucket['runs'] += 1
        bucket['completed'] += 1 if row['completed_protocol'] else 0
    return result


def main() -> None:
    current = rows(BATCH)
    baseline = rows(BASE)
    summary = {
        'protocol': 'stage88-constrained-decoding-v1',
        'runs': len(current),
        'completed': sum(1 for r in current if r['completed_protocol']),
        'parse_errors': sum(r['parse_errors'] for r in current),
        'baseline': {'completed': sum(1 for r in baseline if r['completed_protocol']),
                     'parse_errors': sum(r['parse_errors'] for r in baseline),
                     'by_task': by_task(baseline)},
        'by_task': by_task(current),
        'rows': current,
        'structural_note': 'when only one action is legal the constraint forces it; per-cell completion is reported with that caveat',
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'completed': summary['completed'], 'runs': summary['runs'],
                      'parse_errors': summary['parse_errors'],
                      'baseline_completed': summary['baseline']['completed'],
                      'baseline_parse_errors': summary['baseline']['parse_errors'],
                      'by_task': summary['by_task']}, ensure_ascii=False, indent=2))
    for row in current:
        print(f"#{row['run_index']} {row['task_id']:<14} complete={row['completed_protocol']!s:<5} "
              f"charged={row['charged_attempts']} rej={row['state_rejections']} "
              f"parse={row['parse_errors']} calls={row['llm_calls']} sec={row['seconds']} {row['failure_cause']}")


if __name__ == '__main__':
    main()
