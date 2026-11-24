"""Stage81: score the 4-run message batch with the stage80 audit logic.

Reuses `scripts.audit_agent_reliability.analyse` (verified in stage80) instead of
re-implementing the classification. Writes only into reports/stage81.
"""
import json
from pathlib import Path

from scripts.audit_agent_reliability import analyse

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / 'data/stage81-batch/result.json'
STAGE80 = ROOT / 'reports/stage80/agent-reliability.json'
OUT = ROOT / 'reports/stage81/batch-summary.json'


def main() -> None:
    value = json.loads(BATCH.read_text(encoding='utf8'))
    rows = []
    for index, run in enumerate(value['results']):
        row = analyse(run)
        row.update(stage='stage81-batch', source='data/stage81-batch/result.json', source_index=index,
                   run_id=f'data/stage81-batch/result.json#{index}')
        rows.append(row)

    previous = json.loads(STAGE80.read_text(encoding='utf8'))
    combined = list(previous['rows']) + rows
    by_policy = {}
    for row in combined:
        bucket = by_policy.setdefault(row['policy'], {'completed': 0, 'failed': 0})
        bucket['completed' if row['completed_protocol'] else 'failed'] += 1

    batch = {
        'scope': 'stage81-A controlled batch: 4 frozen tasks x constrained, one run each; read-only scoring',
        'protocol': 'stage81-a-messages-v1',
        'runs': len(rows),
        'completed': sum(1 for r in rows if r['completed_protocol']),
        'failed': sum(1 for r in rows if not r['completed_protocol']),
        'rows': rows,
        'combined_with_stage80': {
            'unique_runs': len(combined),
            'by_policy': by_policy,
            'note': 'stage80 rows were audited before this batch; stage81 rows are new executions, not a re-run'
        },
        'same_task_stage73_reference': {
            'e73-search': {'stage73_completed': True, 'stage81_completed': True},
            'e73-recommend': {'stage73_completed': True, 'stage81_completed': True},
            'e73-mixed': {'stage73_completed': True, 'stage81_completed': True},
            'e73-empty': {'stage73_completed': False, 'stage81_completed': False}
        }
    }
    OUT.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding='utf8')

    print(json.dumps({'runs': batch['runs'], 'completed': batch['completed'], 'failed': batch['failed'],
                      'combined': batch['combined_with_stage80']['by_policy']}, ensure_ascii=False, indent=2))
    for row in rows:
        print(f"{row['task_id']:<14} complete={row['completed_protocol']!s:<5} "
              f"charged={row['charged_attempts']} rejections={row['state_rejections']} "
              f"repeat={row['longest_identical_repeat']} calls={row['llm_calls']} {row['failure_cause']}")


if __name__ == '__main__':
    main()
