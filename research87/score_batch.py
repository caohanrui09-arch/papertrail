"""Stage87: score the empty-final batch and compare with the stage82 baseline."""
import json
from pathlib import Path

from scripts.audit_agent_reliability import analyse

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / 'data/stage87-batch/result.json'
BASE = ROOT / 'data/stage82-batch/result.json'
OUT = ROOT / 'reports/stage87/batch-summary.json'


def rows_from(path: Path) -> list[dict]:
    value = json.loads(path.read_text(encoding='utf8'))
    rows = []
    for index, run in enumerate(value['results']):
        row = analyse(run)
        row['run_index'] = index
        rows.append(row)
    return rows


def main() -> None:
    current = rows_from(BATCH)
    baseline = rows_from(BASE)

    def by_task(rows):
        out = {}
        for row in rows:
            bucket = out.setdefault(row['task_id'], {'runs': 0, 'completed': 0})
            bucket['runs'] += 1
            bucket['completed'] += 1 if row['completed_protocol'] else 0
        return out

    summary = {
        'protocol': 'stage87-empty-final-object-v1',
        'runs': len(current),
        'completed': sum(1 for r in current if r['completed_protocol']),
        'failed': sum(1 for r in current if not r['completed_protocol']),
        'causes': {c: sum(1 for r in current if r['failure_cause'] == c)
                   for c in sorted({r['failure_cause'] for r in current})},
        'by_task': by_task(current),
        'baseline_stage82': by_task(baseline),
        'rows': current,
        'note': 'protocol changed (empty payload); not directly comparable to stage82 on aggregate',
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')

    print(json.dumps({'runs': summary['runs'], 'completed': summary['completed'],
                      'causes': summary['causes'],
                      'by_task': summary['by_task'],
                      'baseline': summary['baseline_stage82']}, ensure_ascii=False, indent=2))
    for row in current:
        print(f"#{row['run_index']} {row['task_id']:<14} complete={row['completed_protocol']!s:<5} "
              f"charged={row['charged_attempts']} rej={row['state_rejections']} "
              f"steps={row['steps_recorded']} calls={row['llm_calls']} {row['failure_cause']}")


if __name__ == '__main__':
    main()
