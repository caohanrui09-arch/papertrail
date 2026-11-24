"""Bounded v1 acquisition; review gate precedes any trial catalog admission."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import re

from filelock import FileLock
from gsearch import metadata_fetch as mf
from gsearch.expansion_data import available_at
from gsearch.quality_protocol import digest, save
from scripts.build_search_v2 import AT, TOPICS, load

ROOT = Path('data/stage39-trial')
CACHE = Path('.cache/stage39/acquisition')


def signals(row: dict, topic: str) -> dict:
    """Conservative literal topic screen, explicitly not relevance judgments."""
    text = (row['title'] + '\n' + row['abstract']).casefold()
    groups = {
        'generative': [r'generative retrieval|differentiable search index|document identifiers|neural corpus index',
                       r'retriev|search|index'],
        'cold': [r'cold[ -]start', r'recommend', r'content|metadata|feature'],
        'bias': [r'exposure|propensity|counterfactual', r'recommend', r'bias|evaluat|debias|unbiased|off.policy'],
    }[topic]
    matches = [re.search(pattern, text) for pattern in groups]
    return {'passes': all(matches), 'literal_evidence': [m.group(0) if m else None for m in matches]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--acquire', action='store_true')
    ap.add_argument('--admit', action='store_true')
    args = ap.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    if args.acquire:
        if (ROOT / 'documents.json').exists():
            raise ValueError('Trial catalog already frozen')
        for p in [Path('.cache/stage10/rate-limit.json'), Path('.cache/stage13/rate-limit.json'),
                  Path('.cache/stage29/rate-limit.json'), CACHE / 'rate-limit.json']:
            if p.exists() and datetime.fromisoformat(load(p)['retry_not_before']) > datetime.now(timezone.utc):
                raise ValueError('Official API cooldown: ' + str(p))
        api = mf.upstream()
        original_root = mf.ROOT
        mf.ROOT = CACHE
        CACHE.mkdir(parents=True, exist_ok=True)
        session = mf.RecordedSession('arxiv', 3.1)
        session.trust_env = False
        client = api.Client(page_size=100, delay_seconds=3.1, num_retries=0)
        client._session = session

        def fetch(name: str, search: object) -> list:
            path = ROOT / 'acquisition' / (name + '.json')
            if path.exists():
                old = load(path)
                if old['error']:
                    raise ValueError('Prior failure retained; inspect before retry: ' + str(path))
                return old['records']
            rows, error = [], None
            start = len(session.receipts)
            try:
                for result in client.results(search):
                    rows.append({**mf.record_api(result, session.receipts[-1]),
                                 'categories': list(result.categories), 'primary_category': result.primary_category})
            except Exception as exc:
                error = type(exc).__name__ + ': ' + str(exc)
            save(path, {'records': rows, 'error': error, 'requests': session.receipts[start:]})
            print({'batch': name, 'records': len(rows), 'error': error}, flush=True)
            if error:
                raise RuntimeError(error)
            return rows

        try:
            with FileLock(str(CACHE / 'acquisition.lock'), timeout=0):
                discovery = {topic: fetch('discover-' + topic, api.Search(
                    query='(' + config['query'] + ') AND submittedDate:[199001010000 TO 202502212359]',
                    max_results=80, sort_by=api.SortCriterion.SubmittedDate, sort_order=api.SortOrder.Descending))
                    for topic, config in TOPICS.items()}
                ids = sorted({p['doc_id'] for rows in discovery.values() for p in rows})
                records = []
                for i in range(0, len(ids), 80):
                    records += fetch('v1-' + str(i), api.Search(id_list=[d + 'v1' for d in ids[i:i+80]], max_results=80))
                save(ROOT / 'candidates.json', {'discovery': {t: [r['doc_id'] for r in rows] for t, rows in discovery.items()}, 'records': records})
        finally:
            session.close()
            mf.ROOT = original_root
    if not (ROOT / 'candidates.json').exists():
        return
    source = load(ROOT / 'candidates.json')
    old = load(Path('data/stage29-search-v2/documents.json'))
    old_ids = {r['doc_id'] for r in old}
    audited, admitted = [], []
    for row in source['records']:
        topics = [t for t, ids in source['discovery'].items() if row['doc_id'] in ids]
        checks = {t: signals(row, t) for t in topics}
        reasons = []
        if row['version'] != 1: reasons.append('not_explicit_v1')
        if not row['title'].strip() or not row['abstract'].strip(): reasons.append('empty_text')
        if available_at(row['published_at']) > datetime.fromisoformat(AT): reasons.append('after_asof')
        if not any(c['passes'] for c in checks.values()): reasons.append('topic_signal_missing')
        if digest(Path(row['provenance']['raw_path'])) != row['provenance']['raw_sha256']: reasons.append('raw_hash_mismatch')
        audited.append({'doc_id': row['doc_id'], 'title': row['title'], 'existing': row['doc_id'] in old_ids,
                        'checks': checks, 'excluded_reasons': reasons, 'admitted': not reasons})
        if not reasons and row['doc_id'] not in old_ids:
            admitted.append({**row, 'version_key': 'arxiv:' + row['doc_id'] + 'v1',
                             'available_at': available_at(row['published_at']).isoformat(),
                             'discovery_topics': [t for t, c in checks.items() if c['passes']], 'source_verified': True})
    report = {'scope': 'literal topic/noise admission screen, not human relevance labels or search-quality evaluation',
              'at': AT, 'candidates': len(audited), 'existing': sum(r['existing'] for r in audited),
              'new_admissible': len(admitted), 'excluded': sum(bool(r['excluded_reasons']) for r in audited),
              'audit': audited, 'candidate_sha256': digest(ROOT / 'candidates.json')}
    save(Path('reports/stage39/catalog-audit.json'), report)
    if args.admit:
        if (ROOT / 'documents.json').exists(): raise ValueError('Catalog frozen')
        approval = load(Path('reports/stage39/catalog-review.json'))
        if approval['candidate_sha256'] != report['candidate_sha256'] or not approval['approved']:
            raise ValueError('Review gate not met')
        excluded = set(approval['exclude_ids'])
        documents = sorted(old + [r for r in admitted if r['doc_id'] not in excluded], key=lambda r: r['doc_id'])
        assert len(documents) == len({r['doc_id'] for r in documents})
        save(ROOT / 'documents.json', documents)
        save(ROOT / 'receipt.json', {'documents': len(documents), 'previous': len(old),
             'new': len(documents)-len(old), 'documents_sha256': digest(ROOT / 'documents.json'),
             'as_of': AT, 'review_sha256': digest(Path('reports/stage39/catalog-review.json')),
             'metadata_license': 'CC0-1.0', 'rights_url': 'https://info.arxiv.org/help/api/tou.html',
             'scope': 'expanded demonstration catalog; historical experiments and relevance labels unchanged'})
    print({k: v for k, v in report.items() if k != 'audit'})


if __name__ == '__main__':
    main()
