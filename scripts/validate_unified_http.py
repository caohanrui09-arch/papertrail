"""Real loopback boundary tests plus native old-BM25 equivalence on same catalog."""
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from gsearch.unified_agent import request
from gsearch.retrieval import BM25
from .prepare_stage19_tasks import ROOT, save


def main() -> None:
    output = Path('reports/stage19/http-validation.json')
    if output.exists(): raise ValueError('HTTP validation already recorded')
    checks = []
    private = []
    owned = []

    def check(condition: bool, label: str) -> None:
        if not condition: raise ValueError(label)
        checks.append(label)

    def create(task: dict) -> str:
        code, response = request('POST', '/sessions', {'user_id': task['user_id'], 'at': task['at']})
        check(code == 200, 'session created')
        token = response['session_id']; owned.append(token)
        return token

    def call(token: str, name: str, arguments: dict) -> tuple[int, dict]:
        result = request('POST', f'/sessions/{token}/tools', {'name': name, 'arguments': arguments})
        private.append({'token': token, 'name': name, 'arguments': arguments, 'response': result})
        return result

    try:
        code, health = request('GET', '/health')
        check(code == 200 and health['candidates'] == 10000, 'healthy shared corpus')
        import psutil
        addresses = sorted({c.laddr.ip for c in psutil.Process(health['pid']).net_connections(kind='inet') if c.status == psutil.CONN_LISTEN})
        check(addresses == ['127.0.0.1'], 'only loopback listening')
        tasks = json.loads((ROOT / 'tuning-tasks.json').read_text(encoding='utf-8')) + json.loads((ROOT / 'evaluation-tasks.json').read_text(encoding='utf-8'))
        rows = json.loads(Path('data/stage13-expansion/documents.json').read_text(encoding='utf-8'))
        for task in [tasks[0], tasks[2], tasks[4], tasks[6], tasks[8], tasks[14]]:
            token = create(task)
            code, result = call(token, 'search_papers', {'query': task['query'], 'k': 3})
            check(code == 200, 'native search served')
            available = [r for r in rows if datetime.fromisoformat(r['available_at']) <= datetime.fromisoformat(task['at'])]
            documents = [{'doc_id': r['doc_id'], 'title': r['title'], 'sentences': [r['abstract']]} for r in available]
            baseline = BM25(SimpleNamespace(documents=documents, by_id={d['doc_id']: d for d in documents}))
            try:
                matches = baseline.search(task['query'], 100)
            finally:
                baseline.db.close()
            # train seen read independently, so no recommendation model fitting.
            import csv
            with Path('data/stage9-recommendation/train.csv').open(encoding='utf-8', newline='') as stream:
                seen = {r['arxiv_id'] for r in csv.DictReader(stream) if r['user_id'] == task['user_id']}
            expected = [r for r in matches if r['doc_id'] not in seen][:3]
            check([p['doc_id'] for p in result['papers']] == [p['doc_id'] for p in expected], 'exact old native BM25 ID ranking')
            check([p['score'] for p in result['papers']] == [p['score'] for p in expected], 'exact old native BM25 scores')
            check(result['index']['available_documents'] == len(available), 'as-of corpus statistics exclude future')
        task = tasks[0]
        token = create(task)
        code, _ = call(token, 'read_paper', {'doc_id': 'not-returned'})
        check(code == 400, 'read gate rejects unknown ID and bills attempt')
        code, result = call(token, 'search_papers', {'query': task['query'], 'k': 3})
        check(code == 200 and bool(result['papers']), 'search returns native IDs')
        doc = result['papers'][0]['doc_id']
        code, original = call(token, 'read_paper', {'doc_id': doc})
        check(code == 200 and original['source_verified'], 'official original v1 verified')
        code, _ = call(token, 'finalize', {'citations': [{'doc_id': doc, 'quote_index': True}]})
        check(code == 400, 'boolean quote index rejected')
        code, answer = call(token, 'finalize', {'citations': [{'doc_id': doc, 'quote_index': 0}]})
        check(code == 200 and answer['citations'][0]['quote'] in original['abstract'], 'exact quote finalized')
        code, _ = call(token, 'recommend_papers', {})
        check(code == 400, 'finalized session closed to further tools')
        code, _ = call(token, 'recommend_papers', {})
        check(code == 429, 'total attempt budget enforced')
        token = create(task)
        for k in [True, 11]:
            code, _ = call(token, 'recommend_papers', {'k': k})
            check(code == 400, 'strict k rejected')
        code, _ = call(token, 'recommend_papers', {'k': 1})
        check(code == 400, 'failed retrieval attempts consume retrieval budget')
        code, _ = request('POST', '/sessions', {'at': '2023-01-01T00:00:00Z'})
        check(code == 422, 'time before history cutoff rejected')
        code, _ = request('POST', '/sessions', {'at': '2025-01-01'})
        check(code == 422, 'naive date rejected')
        code, _ = request('POST', '/sessions', {'alpha': .9})
        check(code == 422, 'unfrozen alpha rejected')
        code, _ = request('GET', '/sessions/not-a-session')
        check(code == 404, 'unknown session rejected')
    finally:
        for token in owned:
            code, _ = request('DELETE', f'/sessions/{token}')
            if code == 200: checks.append('owned session deleted')
    save(Path('.cache/stage19/http-responses-private.json'), private)
    save(output, {'status': 'passed', 'checks': len(checks), 'details': checks,
        'six_independent_old_native_bm25_rankings_and_scores_exact': True, 'listening_addresses': addresses})
    print(json.dumps({'status': 'passed', 'checks': len(checks)}))


if __name__ == '__main__': main()
