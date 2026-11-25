"""Build a 40-item human-labeling sheet from the local Agent and follow-up runs.

The sheet is written under data/ (git-ignored) because citation quotes come from the
frozen catalog, which is not redistributable. The guide and this script are public.
"""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/annotation'
CSV_PATH = OUT / 'labels_v98.csv'
META_PATH = OUT / 'meta_v98.json'
TASK_FILES = [
    ROOT / 'data/stage19-unified/benchmark/evaluation-tasks.json',
    ROOT / 'data/stage73-evaluation/inputs/agent-tasks.json',
]
REFUSAL = '无法从已读摘要确定'


def load_tasks() -> dict:
    tasks = {}
    for path in TASK_FILES:
        if not path.exists():
            continue
        value = json.loads(path.read_text(encoding='utf8'))
        rows = value.get('value') if isinstance(value, dict) else value
        for row in rows or []:
            text = row.get('original_need') or row.get('instruction') or row.get('query') or ''
            tasks[row['id']] = {'text': text, 'intent': row.get('intent')}
    return tasks


def clean(text: str, limit: int = 320) -> str:
    text = ' '.join((text or '').split())
    return text[:limit] + ('…' if len(text) > limit else '')


def valid_question(question: str) -> bool:
    text = (question or '').strip()
    if len(text) < 3:
        return False
    return not re.fullmatch(r'\?+', text)


def evidence_of(citations: list) -> tuple[str, str]:
    quotes, refs = [], []
    for citation in citations or []:
        quote = citation.get('quote') or ''
        if quote:
            quotes.append(clean(quote))
        refs.append(str(citation.get('doc_id')))
    return ' | '.join(quotes), ','.join(refs)


def rows_from_agent(path: Path, tasks: dict) -> list[dict]:
    try:
        value = json.loads(path.read_text(encoding='utf8'))
    except (OSError, json.JSONDecodeError):
        return []
    context = value.get('task_context') or {}
    out = []
    for index, row in enumerate(value.get('results') or []):
        answer = row.get('answer') or {}
        text = answer.get('answer') or ''
        citations = answer.get('citations') or []
        if not text and not citations:
            continue
        task_id = row.get('task_id', '')
        question = (context.get('original_need') or (tasks.get(task_id) or {}).get('text') or task_id)
        flags = []
        if not row.get('completed_protocol'):
            flags.append('incomplete')
        if not citations:
            flags.append('no_citation')
        if not text:
            flags.append('no_answer_text')
        quote, refs = evidence_of(citations)
        out.append({
            'item_id': '',
            'kind': 'agent',
            'task_or_question': clean(question, 220),
            'answer': clean(text, 500),
            'evidence': quote,
            'flags': ','.join(flags),
            '_key': (str(path.relative_to(ROOT)), index),
            '_meta': {'source': str(path.relative_to(ROOT)), 'policy': row.get('policy'),
                      'task_id': task_id, 'completed': bool(row.get('completed_protocol')),
                      'doc_ids': [c.get('doc_id') for c in citations], 'seconds': row.get('seconds')},
        })
    return out


def rows_from_followup(path: Path) -> list[dict]:
    try:
        value = json.loads(path.read_text(encoding='utf8'))
    except (OSError, json.JSONDecodeError):
        return []
    question = value.get('question') or ''
    if not valid_question(question):
        return []
    answer = value.get('answer') or ''
    if not answer:
        return []
    citations = value.get('citations') or []
    flags = []
    if value.get('refusal') or answer.strip() == REFUSAL:
        flags.append('refusal')
    if not citations:
        flags.append('no_citation')
    quote, refs = evidence_of(citations)
    return [{
        'item_id': '',
        'kind': 'followup',
        'task_or_question': clean(question, 220),
        'answer': clean(answer, 500),
        'evidence': quote,
        'flags': ','.join(flags),
        '_key': (str(path.relative_to(ROOT)), 0),
        '_meta': {'source': str(path.relative_to(ROOT)), 'policy': 'followup',
                  'task_id': path.parent.name, 'completed': bool(value.get('complete')),
                  'doc_ids': [c.get('doc_id') for c in citations], 'seconds': value.get('seconds')},
    }]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tasks = load_tasks()
    items: list[dict] = []
    for path in sorted((ROOT / 'data/stage77-lab').glob('*/result.json')):
        items += rows_from_agent(path, tasks)
    for path in sorted((ROOT / 'data/stage77-custom/jobs').glob('*/result.json')):
        items += rows_from_agent(path, tasks)
    for path in sorted(ROOT.glob('data/**/followup-*/result.json')):
        items += rows_from_followup(path)

    answered = [i for i in items if i['kind'] == 'agent' and 'no_citation' not in i['flags']]
    no_cite = [i for i in items if i['kind'] == 'agent' and 'no_citation' in i['flags']]
    followups = [i for i in items if i['kind'] == 'followup' and 'refusal' not in i['flags']]
    refusals = [i for i in items if 'refusal' in i['flags']]

    picked = answered[:16] + followups[:12] + refusals[:8] + no_cite[:4]
    seen, unique = set(), []
    for item in picked:
        if item['_key'] in seen:
            continue
        seen.add(item['_key'])
        unique.append(item)
    unique = unique[:40]

    meta = {}
    with CSV_PATH.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['item_id', 'kind', 'task_or_question', 'answer', 'evidence', 'flags',
                         'support_0_2', 'relevance_0_2', 'citation_ok_Y_N', 'refusal_ok_Y_N_NA', 'notes'])
        for index, item in enumerate(unique, start=1):
            item_id = f'L{index:03d}'
            meta[item_id] = item['_meta']
            writer.writerow([item_id, item['kind'], item['task_or_question'], item['answer'],
                             item['evidence'], item['flags'], '', '', '', '', ''])
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf8')

    counts = {}
    for item in unique:
        counts[item['kind']] = counts.get(item['kind'], 0) + 1
    print(json.dumps({'items': len(unique), 'by_kind': counts,
                      'refusals': sum(1 for i in unique if 'refusal' in i['flags']),
                      'no_citation': sum(1 for i in unique if 'no_citation' in i['flags']),
                      'csv': str(CSV_PATH.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == '__main__':
    main()
