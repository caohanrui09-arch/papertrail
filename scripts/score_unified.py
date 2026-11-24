"""Recount raw policy outputs and verify citations against native parsed XML."""
import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import statistics

from .prepare_stage19_tasks import ROOT, digest, save


def score(split: str) -> dict:
    from gsearch.metadata_fetch import upstream
    from gsearch.paper_identity import arxiv_identity
    rows = json.loads(Path('data/stage13-expansion/documents.json').read_text(encoding='utf-8'))
    by_id = {r['doc_id']: r for r in rows}
    tasks = json.loads((ROOT / (split + '-tasks.json')).read_text(encoding='utf-8'))
    gold = {g['id']: g for g in json.loads((ROOT / (split + '-gold.json')).read_text(encoding='utf-8'))}
    users = {t['user_id'] for t in tasks}
    seen = {u: set() for u in users}
    with Path('data/stage9-recommendation/train.csv').open(encoding='utf-8', newline='') as stream:
        for r in csv.DictReader(stream):
            if r['user_id'] in seen:
                seen[r['user_id']].add(r['arxiv_id'])
    parsed: dict[str, object] = {}
    summaries = {}
    cases = []
    for policy in ('fixed', 'llm_agent'):
        current = []
        for task in tasks:
            path = ROOT / split / f"{task['id']}-{policy}.json"
            result = json.loads(path.read_text(encoding='utf-8'))
            trace = result['trace']['trace']
            returned: dict[str, set[str]] = {}
            successful = [t for t in trace if 'error' not in t['result']]
            read = {}
            for event in successful:
                name, output = event['tool'], event['result']
                if name in ('search_papers', 'recommend_papers'):
                    for paper in output['papers']:
                        doc = paper['doc_id']
                        if doc not in by_id or doc in seen[task['user_id']] or datetime.fromisoformat(by_id[doc]['available_at']) > datetime.fromisoformat(task['at']):
                            raise ValueError('Returned future, seen or unknown paper')
                        returned.setdefault(doc, set()).add(name)
                elif name == 'read_paper':
                    if output['doc_id'] not in returned:
                        raise ValueError('Read without retrieval')
                    read[output['doc_id']] = output
            answer = result['answer']
            citations = answer['citations'] if answer else []
            valid = 0
            for citation in citations:
                doc = citation['doc_id']
                if doc not in read or doc not in by_id:
                    raise ValueError('Citation was not read')
                row = by_id[doc]
                raw = Path(row['provenance']['raw_path'])
                if digest(raw) != row['provenance']['raw_sha256']:
                    raise ValueError('Original response changed')
                if str(raw) not in parsed:
                    parsed[str(raw)] = upstream()._feed.parse(raw.read_bytes()).results
                matches = [r for r in parsed[str(raw)] if arxiv_identity(r.entry_id) == (doc, 1)]
                if len(matches) != 1:
                    raise ValueError('Ambiguous original v1')
                original = matches[0]
                if citation['version'] != 1 or citation['source_url'] != row['source_url'] or citation['version_key'] != row['version_key'] or citation['title'] != original.title or not citation['quote'] or citation['quote'] not in original.summary:
                    raise ValueError('Incorrect exact citation/version/source')
                if read[doc]['abstract'] != original.summary or citation['retrieved_by'] != sorted(returned[doc]):
                    raise ValueError('Trace does not match original/citation provenance')
                valid += 1
            budget_ok = len(trace) <= 6 and sum(t['tool'] in ('search_papers', 'recommend_papers') for t in successful) <= 2 and sum(t['tool'] == 'read_paper' for t in successful) <= 2
            usage = result['metadata'].get('llm_usage', {})
            budget_ok = budget_ok and usage.get('calls', 0) <= 8 and usage.get('input_tokens', 0) <= 30000 and usage.get('output_tokens', 0) <= 1280
            if not budget_ok:
                raise ValueError('Executed work exceeded protocol')
            ids = {c['doc_id'] for c in citations}
            expected = gold[task['id']]
            success = bool(result['completed_protocol'] and answer and len(ids) == expected['expected_citations'] and len(ids) == len(citations))
            if task['intent'] in ('search', 'mixed'):
                success = success and expected['target_doc_id'] in ids and 'search_papers' in returned.get(expected['target_doc_id'], set())
            if task['intent'] in ('recommend', 'mixed'):
                success = success and any('recommend_papers' in returned.get(doc, set()) and (task['intent'] != 'mixed' or doc != expected['target_doc_id']) for doc in ids)
            if task['intent'] == 'empty':
                success = success and not returned and any(t['tool'] == 'search_papers' for t in successful)
            entry = {'task_id': task['id'], 'intent': task['intent'], 'cold_user': expected['user_cold'],
                'completed': result['completed_protocol'], 'success': bool(success), 'citations': len(citations),
                'valid_citations': valid, 'server_attempts': len(trace), 'failed_attempts': len(trace)-len(successful),
                'llm_calls': usage.get('calls', 0), 'input_tokens': usage.get('input_tokens', 0),
                'output_tokens': usage.get('output_tokens', 0), 'llm_denied_calls': usage.get('denied_calls', 0),
                'seconds': result['seconds'], 'budget_ok': budget_ok}
            current.append(entry)
            cases.append({'policy': policy, **entry})
        times = sorted(c['seconds'] for c in current)
        summaries[policy] = {'tasks': len(current), 'completed': sum(c['completed'] for c in current),
            'task_success': sum(c['success'] for c in current), 'citations': sum(c['citations'] for c in current),
            'valid_citations': sum(c['valid_citations'] for c in current),
            'server_attempts': sum(c['server_attempts'] for c in current), 'failed_attempts': sum(c['failed_attempts'] for c in current),
            'llm_calls': sum(c['llm_calls'] for c in current), 'input_tokens': sum(c['input_tokens'] for c in current),
            'output_tokens': sum(c['output_tokens'] for c in current), 'mean_seconds': statistics.mean(times),
            'p95_seconds_nearest_rank': times[max(0, __import__('math').ceil(.95*len(times))-1)],
            'by_intent': {intent: {'tasks': sum(c['intent']==intent for c in current),
                'success': sum(c['intent']==intent and c['success'] for c in current)} for intent in ('search', 'recommend', 'mixed', 'empty')},
            'all_budgets_pass': all(c['budget_ok'] for c in current)}
    return {'split': split, 'scope': 'controlled routing/known-item and exact-source existence, NOT semantic correctness or user preference utility',
            'methods': summaries, 'cases': cases, 'independently_parsed_raw_responses': len(parsed)}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument('--split', choices=('tuning', 'evaluation'), required=True)
    args = parser.parse_args()
    path = Path(f'reports/stage19/{args.split}-summary.json')
    if path.exists(): raise ValueError('Score summary already exists')
    result = score(args.split)
    save(path, result)
    print(json.dumps(result['methods'], ensure_ascii=False), flush=True)


if __name__ == '__main__': main()
