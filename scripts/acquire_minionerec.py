"""Fetch only three explicit v1 metadata records using the existing pinned client."""
from datetime import datetime, timezone
from pathlib import Path
from filelock import FileLock
from gsearch import metadata_fetch as mf
from gsearch.quality_protocol import save

DEST = Path('reports/stage41')
CACHE = Path('.cache/stage41/acquisition')
IDS = ['2305.05065', '2510.24431', '2510.12211']


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    target = DEST / 'papers.json'
    if target.exists():
        print({'cached': True, 'records': len(mf.read(target)['records'])})
        return
    for folder in ['stage10', 'stage13', 'stage29', 'stage39/acquisition', 'stage41/acquisition']:
        cooldown = Path('.cache') / folder / 'rate-limit.json'
        if cooldown.exists() and datetime.fromisoformat(mf.read(cooldown)['retry_not_before']) > datetime.now(timezone.utc):
            raise ValueError('Active official API cooldown: ' + str(cooldown))
    api = mf.upstream()
    original = mf.ROOT
    mf.ROOT = CACHE
    session = mf.RecordedSession('arxiv', 3.1)
    session.trust_env = False
    records, error = [], None
    try:
        with FileLock(str(CACHE / 'acquisition.lock'), timeout=0):
            client = api.Client(page_size=10, delay_seconds=3.1, num_retries=0)
            client._session = session
            for result in client.results(api.Search(id_list=[i+'v1' for i in IDS], max_results=3)):
                records.append(mf.record_api(result, session.receipts[-1]))
            assert {r['doc_id'] for r in records} == set(IDS)
            assert all(r['version'] == 1 and r['abstract'].strip() for r in records)
    except Exception as exc:
        error = type(exc).__name__ + ': ' + str(exc)
    finally:
        session.close()
        mf.ROOT = original
    receipt = {'records': records, 'error': error, 'requests': session.receipts,
               'scope': 'independent educational supplement; not historic catalog admission'}
    save(DEST / ('papers-failure.json' if error else 'papers.json'), receipt)
    print({'records': len(records), 'error': error}, flush=True)
    if error:
        raise RuntimeError(error)


if __name__ == '__main__':
    main()
