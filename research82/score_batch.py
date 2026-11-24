"""Stage82-B: score the 8-run batch with the stage80 audit logic.

Reuses `analyse` so the classification is identical to the stage80/81 reports.
"""
import json
from pathlib import Path

from scripts.audit_agent_reliability import analyse

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / 'data/stage82-batch/result.json'
STAGE81 = ROOT / 'reports/stage81/batch-summary.json'
OUT = ROOT / 'reports/stage82/batch-summary.json'


def main() -> None:
    value = json.loads(BATCH.read_text(encoding='utf8'))
    rows = []
    for index, run in enumerate(value['results']):
        row = analyse(run)
        row.update(stage='stage82-batch', run_index=index,
                   source='data/stage82-batch/result.json', source_index=index,
                   run_id=f'data/stage82-batch/result.json#{index}')
        rows.append(row)

    causes = {}
    for row in rows:
        causes[row['failure_cause']] = causes.get(row['failure_cause'], 0) + 1

    by_task = {}
    for row in rows:
        bucket = by_task.setdefault(row['task_id'], {'runs': 0, 'completed': 0, 'causes': {}})
        bucket['runs'] += 1
        bucket['completed'] += 1 if row['completed_protocol'] else 0
        bucket['causes'][row['failure_cause']] = bucket['causes'].get(row['failure_cause'], 0) + 1

    previous = json.loads(STAGE81.read_text(encoding='utf8'))
    reference = {row['task_id']: row for row in previous['rows']}

    summary = {
        'scope': 'stage82-B controlled batch: 4 frozen tasks x 2 runs, constrained, read-only scoring',
        'protocol': 'stage82-b-free-rejections-v2',
        'runs': len(rows),
        'completed': sum(1 for r in rows if r['completed_protocol']),
        'failed': sum(1 for r in rows if not r['completed_protocol']),
        'terminal_causes': causes,
        'by_task': by_task,
        'rows': rows,
        'stage81_reference': {
            task_id: {'completed': row['completed_protocol'], 'rejections': row['state_rejections'],
                      'charged': row['charged_attempts'], 'failure_cause': row['failure_cause']}
            for task_id, row in reference.items()
        },
        'stage73_reference': {'e73-search': True, 'e73-recommend': True, 'e73-mixed': True, 'e73-empty': False},
        'note': 'same tasks, different accounting; descriptive comparison only'
    }
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')

    print(json.dumps({'runs': summary['runs'], 'completed': summary['completed'],
                      'failed': summary['failed'], 'causes': causes}, ensure_ascii=False, indent=2))
    for row in rows:
        print(f"#{row['run_index']} {row['task_id']:<14} complete={row['completed_protocol']!s:<5} "
              f"charged={row['charged_attempts']} rejections={row['state_rejections']} "
              f"steps={row['steps_recorded']} calls={row['llm_calls']} {row['failure_cause']}")


if __name__ == '__main__':
    main()
