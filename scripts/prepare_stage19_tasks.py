"""Gold-blind deterministic task construction; no search runs or future likes."""
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path('data/stage19-unified/benchmark')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main() -> None:
    if ROOT.exists():
        raise ValueError('Task bundle already exists; never overwrite')
    rows = json.loads(Path('data/stage13-expansion/documents.json').read_text(encoding='utf-8'))
    cutoff = json.loads(Path('reports/stage13/admission-plan.json').read_text())['cutoff']
    warm = {r['doc_id'] for r in rows if r['cohort'] == 'warm'}
    seen: dict[str, set[str]] = {}
    users = set()
    with Path('data/stage9-recommendation/train.csv').open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            user, doc = row['user_id'], row['arxiv_id']
            seen.setdefault(user, set()).add(doc)
            if float(row['rating']) == 1 and doc in warm:
                users.add(user)
    key = lambda value: hashlib.sha256(('stage19-v1:' + value).encode()).hexdigest()
    users = sorted(users, key=key)
    cold = 'stage19-unknown-user'
    if cold in seen:
        raise ValueError('Cold-user sentinel collides with training user')
    used = set()
    bundles = {}
    for split, count in [('tuning', 4), ('evaluation', 12)]:
        tasks, gold = [], []
        for i in range(count):
            intent = ('search', 'recommend', 'mixed', 'empty')[i % 4]
            user = cold if i // 4 == 1 else users[(0 if split == 'tuning' else 8) + i]
            at = cutoff if split == 'tuning' else '2025-02-23T05:28:26.401006+00:00'
            target = None
            query = ''
            if intent in ('search', 'mixed'):
                wanted = 'warm' if split == 'tuning' or i // 4 == 0 else 'old_cold' if i // 4 == 1 else 'new_cold'
                cohort_values = sorted({r['cohort'] for r in rows})
                if wanted not in cohort_values:
                    raise ValueError('Inspect source cohort names: ' + str(cohort_values))
                candidates = [r for r in rows if r['cohort'] == wanted and r['doc_id'] not in used
                    and r['doc_id'] not in seen.get(user, set())
                    and datetime.fromisoformat(r['available_at']) <= datetime.fromisoformat(at)]
                if not candidates:
                    raise ValueError('No label-blind eligible task candidate')
                row = min(candidates, key=lambda r: key(split + str(i) + r['doc_id']))
                target, query = row['doc_id'], row['title']
                used.add(target)
            elif intent == 'empty':
                query = 'stage19nomatch' + hashlib.sha256((split + str(i)).encode()).hexdigest()
                if any(query.casefold() in (r['title'] + '\n' + r['abstract']).casefold() for r in rows):
                    raise ValueError('No-match sentinel present in source text')
            instruction = {'search': 'Find the paper with this exact title; read it and cite one original abstract excerpt.',
                'recommend': 'Recommend one unread paper using my frozen history; read it and cite an original abstract excerpt.',
                'mixed': 'Find the paper with this exact title AND one DIFFERENT personalized recommendation. Read and cite both original abstracts.',
                'empty': 'Search this exact token. If no papers match, return no citations; do not substitute recommendations.'}[intent]
            ident = f'{split}-{i:03d}'
            tasks.append({'id': ident, 'intent': intent, 'query': query, 'instruction': instruction, 'user_id': user, 'at': at})
            gold.append({'id': ident, 'target_doc_id': target, 'user_cold': user == cold, 'expected_citations': 2 if intent == 'mixed' else 0 if intent == 'empty' else 1})
        bundles[split + '-tasks.json'] = tasks
        bundles[split + '-gold.json'] = gold
    for name, value in bundles.items():
        save(ROOT / name, value)
    save(Path('reports/stage19/evaluation-plan.json'), {
        'seed_rule': 'sha256(stage19-v1: + split/index/ID); no ranking/gold success filtering',
        'tasks': {'tuning': 4, 'evaluation': 12}, 'policies': ['fixed', 'llm_agent'],
        'k': 3, 'recommendation': 'frozen content default',
        'attempt_limits': {'server_total_including_finalize': 6, 'retrieval': 2, 'reads': 2,
            'framework_steps': 7, 'llm_calls_including_fallback': 8, 'llm_input': 30000, 'llm_output': 1280},
        'selection': 'Training-only users/seen; exact-title targets hash selected from corpus cohorts, not BM25 success; no future ratings read',
        'scope': 'controlled known-item retrieval, recommendation routing and exact-source citation; NOT judged topic relevance, semantic faithfulness, independent ratings or online utility',
        'scoring': 'protocol completion separately from task-specific target/routing/count; all failures in denominator; exact quote/ID/version/URL checked independently from original source cache',
        'cost': 'paired policy order rotated; raw per-task wall time, server tools, LLM tokens and one-time model loading separate; single-run descriptive latency',
        'default_decision': 'Keep deterministic fixed flow unless independent task utility and cost justify LLM; no production default switch from small controlled evaluation',
        'task_hashes': {p.name: digest(p) for p in sorted(ROOT.glob('*.json'))},
        'documents_sha256': digest(Path('data/stage13-expansion/documents.json')),
        'train_sha256': digest(Path('data/stage9-recommendation/train.csv'))})
    print(json.dumps({'prepared': True, 'tasks': 16, 'private_root': str(ROOT)}))


if __name__ == '__main__': main()
