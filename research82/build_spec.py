"""Build the stage82-B batch spec: each frozen task twice, constrained policy only."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / 'data/stage73-evaluation/inputs/agent-tasks.json'
OUT = ROOT / 'data/stage82-batch/spec.json'


def main() -> None:
    raw = json.loads(TASKS.read_text(encoding='utf8'))
    tasks = raw['value'] if isinstance(raw, dict) and 'value' in raw else raw
    if len(tasks) != 4:
        raise SystemExit(f'expected 4 frozen tasks, got {len(tasks)}')
    spec = {'tasks': tasks + tasks, 'policies': ['constrained']}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'runs': len(spec['tasks']), 'order': [t['id'] for t in spec['tasks']]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
