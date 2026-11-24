"""Stage89: which action does the model choose after an empty retrieval?"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / 'data/stage89-choice/result.json'
OUT = ROOT / 'reports/stage89/choice-summary.json'


def first_choice(run: dict) -> dict:
    events = (run.get('metadata') or {}).get('proposal_events') or []
    names = [event['proposal']['name'] for event in events]
    try:
        index = names.index('search_papers')
    except ValueError:
        return {'sequence': names, 'choice': 'no_search'}
    rest = names[index + 1:]
    choice = rest[0] if rest else 'none'
    return {'sequence': names, 'choice': choice, 'retries': rest.count('search_papers')}


def main() -> None:
    value = json.loads(BATCH.read_text(encoding='utf8'))
    rows = []
    for index, run in enumerate(value['results']):
        info = first_choice(run)
        rows.append({
            'run': index,
            'completed': run.get('completed_protocol'),
            'seconds': round(run.get('seconds') or 0, 1),
            'choice': info['choice'],
            'retries': info.get('retries', 0),
            'sequence': info['sequence'],
        })
    submits = sum(1 for r in rows if r['choice'] == 'final_answer')
    retries = sum(1 for r in rows if r['choice'] == 'search_papers')
    summary = {
        'protocol': 'stage89-empty-choice-v1',
        'runs': len(rows),
        'submitted_empty': submits,
        'retried_retrieval': retries,
        'completed': sum(1 for r in rows if r['completed']),
        'reading': 'submit-first means the model accepts emptiness without being forced; retry-first means the stage88 pass was structural',
        'rows': rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: summary[k] for k in ('runs', 'submitted_empty', 'retried_retrieval', 'completed')}, ensure_ascii=False, indent=2))
    for row in rows:
        print(f"#{row['run']} choice={row['choice']:<14} retries={row['retries']} complete={row['completed']} "
              f"sec={row['seconds']} seq={'->'.join(row['sequence'])}")


if __name__ == '__main__':
    main()
