"""Read-only reliability audit over retained real Agent trajectories.

Runs no model, executes no tool and mutates no frozen artifact. It only reads
`result.json` files already on disk, re-derives the state-machine outcome from
the retained wire/proposal/step records, and writes a failure table.

Usage:
    .cache\\stage17\\runtime\\Scripts\\python.exe -E -s -m scripts.audit_agent_reliability
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Directories that hold retained real runs. Read in this order for stable output.
ROOTS = [
    'data/stage63-inprocess-v2',
    'data/stage64-http',
    'data/stage68-lab',
    'data/stage69-lab',
    'data/stage70-lab',
    'data/stage71-lab',
    'data/stage71-custom',
    'data/stage72-lab',
    'data/stage72-custom',
    'data/stage73-evaluation/agent-runs',
    'data/stage77-lab',
]

# Error text -> machine-readable cause. Order matters: first match wins.
SIGNATURES = [
    ('unknown_tool_after_budget', re.compile(r'^Unknown tool ')),
    ('read_not_readable', re.compile(r'ID is unavailable/already read')),
    ('retrieval_budget_spent', re.compile(r'State action unavailable: (search_papers|recommend_papers)')),
    ('read_budget_spent', re.compile(r'State action unavailable: read_paper')),
    ('final_budget_spent', re.compile(r'State action unavailable: final_answer')),
    ('k_schema', re.compile(r'Nonnullable integer k')),
    ('query_schema', re.compile(r'Nonempty query')),
    ('final_citation_shape', re.compile(r'(Final citation count|Exact citation fields|Cite distinct already-read|Existing integer quote index|Citations do not cover)')),
    ('agent_max_steps', re.compile(r'Reached max steps')),
]


def signature(text: str) -> str:
    for name, pattern in SIGNATURES:
        if pattern.search(text or ''):
            return name
    return 'other'


def iter_runs():
    """Yield (stage, relative_path, index, run) for every retained run record."""
    for root in ROOTS:
        base = ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob('*.json')):
            try:
                value = json.loads(path.read_text(encoding='utf8'))
            except (OSError, ValueError, UnicodeDecodeError):
                continue
            rel = path.relative_to(ROOT).as_posix()
            stage = rel.split('/')[1] if rel.startswith('data/') else rel
            # wrapper: {"complete":..., "results":[run, ...]}
            if isinstance(value, dict) and isinstance(value.get('results'), list):
                for index, item in enumerate(value['results']):
                    if isinstance(item, dict) and 'policy' in item:
                        yield stage, rel, index, item
                continue
            # wrapper: {"status":..., "result":{"results":[run, ...]}}
            if isinstance(value, dict) and isinstance(value.get('result'), dict):
                inner = value['result']
                if isinstance(inner.get('results'), list):
                    for index, item in enumerate(inner['results']):
                        if isinstance(item, dict) and 'policy' in item:
                            yield stage, rel, index, item
                    continue
            # single run record
            if isinstance(value, dict) and 'policy' in value and ('task_id' in value or 'completed_protocol' in value):
                yield stage, rel, 0, value


def analyse(run: dict) -> dict:
    md = run.get('metadata') or {}
    steps = md.get('steps') or []
    wire = md.get('wire_attempts') or []
    events = md.get('proposal_events') or []
    snaps = md.get('constraint_snapshots') or []
    errors = [(i, (s.get('error') or {}).get('message') or '') for i, s in enumerate(steps) if s.get('error')]
    error_texts = [text for _, text in errors]

    rejected = [w for w in wire if not w.get('sent_to_server') and w.get('error')]
    sent = [w for w in wire if w.get('sent_to_server')]

    # How often does the model re-send the exact same proposal? A run that keeps
    # repeating one payload shows the failure is self-correction, not budget size.
    sequence = [(e['proposal'].get('name'),
                 json.dumps(e['proposal'].get('arguments'), sort_keys=True, ensure_ascii=False))
                for e in events]
    longest_repeat = 1
    run_length = 1
    for previous, current in zip(sequence, sequence[1:]):
        run_length = run_length + 1 if current == previous else 1
        longest_repeat = max(longest_repeat, run_length)
    longest_repeat = longest_repeat if sequence else 0

    # Ordered proposals actually charged to the shared application budget.
    charged_calls = [e['proposal']['name'] for e in events if e.get('charged')]
    charged_total = md.get('charged_application_attempts')
    if charged_total is None:
        charged_total = len(charged_calls)

    completed = bool(run.get('completed_protocol'))
    exhausted = bool(md.get('framework_steps_exhausted'))
    unknown_after_budget = any(signature(t) == 'unknown_tool_after_budget' for t in error_texts)

    if completed:
        cause = 'completed'
    elif charged_total >= 6 and (unknown_after_budget or rejected):
        cause = 'budget_exhausted'
    elif exhausted or any(signature(t) == 'agent_max_steps' for t in error_texts):
        cause = 'max_steps'
    elif rejected:
        cause = signature(rejected[-1]['error'])
    elif run.get('failure_kind'):
        cause = str(run['failure_kind'])
    else:
        cause = 'other'

    first_bad = rejected[0] if rejected else None
    final_snapshot = snaps[-1] if snaps else {}
    usage = md.get('llm_usage') or {}
    return {
        'task_id': run.get('task_id') or run.get('task') or '',
        'policy': run.get('policy') or '',
        'completed_protocol': completed,
        'failure_cause': cause,
        'failure_kind_recorded': run.get('failure_kind') or '',
        'steps_recorded': len(steps),
        'llm_calls': usage.get('calls'),
        'input_tokens': usage.get('input_tokens'),
        'output_tokens': usage.get('output_tokens'),
        'denied_calls': usage.get('denied_calls'),
        'charged_attempts': charged_total,
        'charged_calls': '|'.join(charged_calls),
        'state_rejections': len(rejected),
        'wire_sent': len(sent),
        'longest_identical_repeat': longest_repeat,
        'identical_repeat_after_rejection': bool(rejected) and longest_repeat > 1,
        'first_bad_tool': (first_bad or {}).get('name', ''),
        'first_bad_error': (first_bad or {}).get('error', ''),
        'first_bad_cause': signature((first_bad or {}).get('error', '')),
        'last_legal_tools': '|'.join(final_snapshot.get('legal_tools') or []),
        'attempts_remaining_at_end': final_snapshot.get('application_attempts_remaining'),
        'framework_steps_exhausted': exhausted,
        'seconds': round(float(run.get('seconds') or 0.0), 2),
        'last_error_text': (errors[-1][1][:200] if errors else ''),
        'error_text': (run.get('error') or '')[:300] if isinstance(run.get('error'), str) else '',
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', type=Path, default=ROOT / 'reports/stage80/agent-reliability.json')
    parser.add_argument('--csv', type=Path, default=ROOT / 'reports/stage80/agent-failure-table.csv')
    args = parser.parse_args()

    # Some stages retained the same run twice (aggregate results.json plus a
    # per-job copy). Collapse exact duplicates so counts stay per real run: the
    # same policy/task with identical wall time and meter is one execution.
    rows = []
    seen = {}
    duplicates = 0
    found = sorted(iter_runs(), key=lambda item: (len(item[1]), item[1], item[2]))
    for stage, rel, index, run in found:
        record = analyse(run)
        key = (record['policy'], record['task_id'], record['seconds'],
               record['llm_calls'], record['input_tokens'], record['output_tokens'])
        if key in seen:
            duplicates += 1
            continue
        seen[key] = True
        record.update(stage=stage, source=rel, source_index=index,
                      run_id=f'{rel}#{index}')
        rows.append(record)

    if not rows:
        raise SystemExit('no retained runs found')

    args.json.parent.mkdir(parents=True, exist_ok=True)
    fields = ['run_id', 'stage', 'task_id', 'policy', 'completed_protocol', 'failure_cause',
              'first_bad_tool', 'first_bad_cause', 'charged_attempts', 'state_rejections',
              'longest_identical_repeat', 'llm_calls', 'input_tokens', 'output_tokens',
              'steps_recorded', 'seconds',
              'framework_steps_exhausted', 'last_legal_tools', 'attempts_remaining_at_end',
              'last_error_text', 'error_text', 'charged_calls']
    with args.csv.open('w', encoding='utf8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

    by_policy = defaultdict(lambda: Counter())
    for row in rows:
        by_policy[row['policy']][row['completed_protocol']] += 1
    causes = Counter(row['failure_cause'] for row in rows)
    stage_policy = defaultdict(lambda: Counter())
    for row in rows:
        if row['policy'] in ('constrained', 'llm_agent'):
            stage_policy[row['stage']][(row['policy'], row['completed_protocol'])] += 1
    waste = [r for r in rows if not r['completed_protocol'] and r['state_rejections']]

    summary = {
        'scope': 'read-only audit of retained trajectories; no model call, no tool execution',
        'runs': len(rows),
        'duplicate_copies_removed': duplicates,
        'by_policy': {policy: {'completed': counter[True], 'failed': counter[False]}
                      for policy, counter in sorted(by_policy.items())},
        'failure_causes': dict(sorted(causes.items())),
        'failures_with_state_rejections': len(waste),
        'failed_runs_repeating_identical_payload': sum(
            1 for r in rows if not r['completed_protocol'] and r['longest_identical_repeat'] > 1),
        'max_identical_repeat': max((r['longest_identical_repeat'] for r in rows), default=0),
        'model_calls_total': sum(r['llm_calls'] or 0 for r in rows),
        'rows': rows,
    }
    args.json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')

    print(json.dumps({'runs': len(rows), 'by_policy': summary['by_policy'],
                      'failure_causes': summary['failure_causes']}, ensure_ascii=False, indent=2))
    print(f'wrote {args.csv.relative_to(ROOT)} and {args.json.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
