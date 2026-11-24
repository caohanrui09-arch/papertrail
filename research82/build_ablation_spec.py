"""Build a 2-run ablation spec: only e73-recommend, to isolate the state-string change."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / 'data/stage73-evaluation/inputs/agent-tasks.json'
OUT = ROOT / 'data/stage82-ablation/spec.json'


def main() -> None:
    raw = json.loads(TASKS.read_text(encoding='utf8'))
    tasks = raw['value'] if isinstance(raw, dict) and 'value' in raw else raw
    task = next(item for item in tasks if item['id'] == 'e73-recommend')
    spec = {'tasks': [task, task], 'policies': ['constrained']}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'runs': 2, 'task': task['id']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
