"""As-of SQLite FTS5 BM25 over the frozen recommendation catalog.

Only catalog/time/seen and native FTS interfaces are adapted here. SQLite owns
tokenization, BM25 and ranking. Future documents never enter index statistics.
"""
from collections import OrderedDict
from datetime import datetime
import re
import sqlite3
import threading
import time


def request_time(at: str, cutoff: datetime) -> datetime:
    when = datetime.fromisoformat(at.replace('Z', '+00:00'))
    if when.tzinfo is None or when < cutoff:
        raise ValueError('Timezone-aware request time at/after history cutoff required')
    return when


class AsOfBM25:
    def __init__(self, model: object, max_snapshots: int = 2):
        if type(max_snapshots) is not int or max_snapshots < 1:
            raise ValueError('Positive snapshot capacity required')
        self.model = model
        self.max_snapshots = max_snapshots
        self.snapshots: OrderedDict[tuple[str, ...], sqlite3.Connection] = OrderedDict()
        self.lock = threading.RLock()

    def _snapshot(self, at: str) -> tuple[sqlite3.Connection, dict]:
        when = request_time(at, self.model.cutoff).timestamp()
        # Include available seen documents in corpus statistics, then filter seen
        # before LIMIT. All users at this time share the same catalog statistics.
        ids = tuple(d for i, d in enumerate(self.model.catalog) if self.model.available[i] <= when)
        cached = ids in self.snapshots
        started = time.perf_counter()
        if not cached:
            db = sqlite3.connect(':memory:', check_same_thread=False)
            try:
                db.execute("CREATE VIRTUAL TABLE docs USING fts5(doc_id UNINDEXED, title, body, tokenize='porter unicode61')")
                db.executemany('INSERT INTO docs VALUES (?,?,?)',
                    [(d, self.model.by_id[d]['title'], self.model.by_id[d]['abstract']) for d in ids])
                db.execute('CREATE TEMP TABLE seen(doc_id TEXT PRIMARY KEY) WITHOUT ROWID')
                db.commit()
            except Exception:
                db.close()
                raise
            self.snapshots[ids] = db
            if len(self.snapshots) > self.max_snapshots:
                _, evicted = self.snapshots.popitem(last=False)
                evicted.close()
        else:
            self.snapshots.move_to_end(ids)
        return self.snapshots[ids], {'available_documents': len(ids), 'snapshot_cache_hit': cached,
            'snapshot_seconds': time.perf_counter() - started, 'sqlite_version': sqlite3.sqlite_version,
            'statistics_scope': 'only available documents; all users share IDF at this time'}

    def search(self, user: str, at: str, query: str, k: int = 3) -> dict:
        if not isinstance(query, str) or not query.strip() or len(query) > 2000:
            raise ValueError('Nonempty query up to 2000 characters required')
        if type(k) is not int or not 1 <= k <= 10:
            raise ValueError('Integer k between 1 and 10 required')
        words = list(dict.fromkeys(re.findall(r'\w+', query.casefold())))[:128]
        stop = {'a', 'an', 'the', 'is', 'are', 'of', 'to', 'in', 'and', 'or', 'that', 'with', 'for', 'by'}
        expression = ' OR '.join('"' + word + '"' for word in words if word not in stop)
        with self.lock:
            db, stats = self._snapshot(at)
            db.execute('DELETE FROM seen')
            db.executemany('INSERT INTO seen VALUES (?)', [(d,) for d in self.model.sar.seen.get(user, set())])
            rows = db.execute('SELECT doc_id, bm25(docs,0,2,1) AS score FROM docs '
                'WHERE docs MATCH ? AND doc_id NOT IN (SELECT doc_id FROM seen) '
                'ORDER BY score, doc_id LIMIT ?', (expression, k)).fetchall() if expression else []
            hits = [{'doc_id': d, 'score': -score, 'title': self.model.by_id[d]['title'],
                'version': self.model.by_id[d]['version'], 'source_url': self.model.by_id[d]['source_url']}
                for d, score in rows]
            return {'papers': hits, 'as_of': at, 'method': 'sqlite_fts5_bm25', 'index': stats}

    def close(self) -> None:
        with self.lock:
            for db in self.snapshots.values():
                db.close()
            self.snapshots.clear()
