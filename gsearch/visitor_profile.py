"""Local preferences and sklearn content adaptation; no experimental feedback writes."""
from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize
from sklearn.metrics.pairwise import linear_kernel

from .content_recommendation import PARAMS
from .expansion_recommendation import ExpansionRecommender
from .portfolio_demo import ASOF
from .unified_search import AsOfBM25
from .unified_session import UnifiedSession
from .unified_agent import ToolClient


class PreferenceConflict(ValueError):
    pass


class Preferences:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS visitors(owner TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS preferences(owner TEXT, doc_id TEXT, value TEXT NOT NULL,
                    updated TEXT NOT NULL, PRIMARY KEY(owner,doc_id));
            ''')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def snapshot(db, owner: str) -> dict:
        row = db.execute('SELECT revision FROM visitors WHERE owner=?', (owner,)).fetchone()
        prefs = db.execute('SELECT doc_id,value FROM preferences WHERE owner=? ORDER BY doc_id', (owner,)).fetchall()
        return {'revision': row[0] if row else 0, 'items': dict(prefs)}

    def get(self, owner: str) -> dict:
        with self.connect() as db:
            db.execute('BEGIN')
            return self.snapshot(db, owner)

    def change(self, owner: str, revision: int, doc: str | None, value: str) -> dict:
        if value not in ('like', 'hide', 'none', 'reset') or (value == 'reset') != (doc is None):
            raise ValueError('Invalid preference action')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self.snapshot(db, owner)
            if current['revision'] != revision:
                raise PreferenceConflict('偏好已在其他页面更新，请刷新后重试')
            if value not in ('none', 'reset') and doc not in current['items'] and len(current['items']) >= 500:
                raise ValueError('本地画像最多保存 500 篇偏好，请先移除一些记录')
            if value == 'reset':
                db.execute('DELETE FROM preferences WHERE owner=?', (owner,))
            elif value == 'none':
                db.execute('DELETE FROM preferences WHERE owner=? AND doc_id=?', (owner, doc))
            else:
                db.execute('INSERT OR REPLACE INTO preferences VALUES(?,?,?,?)',
                           (owner, doc, value, datetime.now(timezone.utc).isoformat()))
            db.execute('INSERT OR REPLACE INTO visitors VALUES(?,?)', (owner, revision + 1))
            return self.snapshot(db, owner)


class Catalog:
    """Rebuild only the frozen text representation, never the dense SAR matrices."""
    def __init__(self):
        source = Path('data/stage13-expansion/documents.json')
        receipt = json.loads(Path('reports/stage13/corpus-receipt.json').read_text())
        if hashlib.sha256(source.read_bytes()).hexdigest() != receipt['documents_sha256']:
            raise ValueError('Frozen corpus changed')
        records = json.loads(source.read_text(encoding='utf-8'))
        self.by_id = {r['doc_id']: r for r in records}
        self.catalog = sorted(self.by_id)
        self.position = {d: i for i, d in enumerate(self.catalog)}
        self.cutoff = datetime.fromisoformat(json.loads(Path('reports/stage13/admission-plan.json').read_text())['cutoff'].replace('Z', '+00:00'))
        self.available = np.array([datetime.fromisoformat(self.by_id[d]['available_at'].replace('Z', '+00:00')).timestamp() for d in self.catalog])
        args = dict(PARAMS); args['ngram_range'] = tuple(args['ngram_range'])
        self.vectorizer = TfidfVectorizer(**args)
        text = lambda d: self.by_id[d]['title'] + '\n' + self.by_id[d]['abstract']
        self.vectorizer.fit([text(d) for i, d in enumerate(self.catalog) if self.available[i] < self.cutoff.timestamp()])
        self.documents = self.vectorizer.transform([text(d) for d in self.catalog])
        self.features = self.vectorizer.get_feature_names_out()
        expected = json.loads(Path('reports/stage13/resource-10000.json').read_text())['model_signature']
        h = hashlib.sha256(str(self.documents.shape).encode())
        for a in (self.documents.data, self.documents.indices, self.documents.indptr): h.update(memoryview(a))
        actual = {'documents_sha256': h.hexdigest(),
                  'idf_sha256': hashlib.sha256(self.vectorizer.idf_.tobytes()).hexdigest(),
                  'vocabulary_sha256': hashlib.sha256(json.dumps({k: int(v) for k, v in self.vectorizer.vocabulary_.items()}, sort_keys=True).encode()).hexdigest()}
        if any(expected[k] != v for k, v in actual.items()):
            raise ValueError('Text representation differs from frozen model')
        self.signature = actual
        import pandas as pd
        train = pd.read_csv('data/stage9-recommendation/train.csv', dtype={'arxiv_id': str})
        warm = {d for d in self.catalog if self.by_id[d]['cohort'] == 'warm'}
        counts = train[(train.rating == 1) & train.arxiv_id.isin(warm)].arxiv_id.value_counts()
        self.popularity = np.array([float(counts.get(d, 0)) for d in self.catalog])

    def valid(self, doc: str) -> bool:
        return doc in self.position and self.available[self.position[doc]] <= datetime.fromisoformat(ASOF).timestamp()

    def paper(self, doc: str) -> dict:
        return {k: self.by_id[doc][k] for k in ('doc_id', 'title', 'version', 'source_url')}


class PersonalModel:
    def __init__(self, catalog: Catalog, snapshot: dict):
        self.base = catalog
        self.by_id, self.catalog = catalog.by_id, catalog.catalog
        self.cutoff, self.available = catalog.cutoff, catalog.available
        self.snapshot = snapshot
        self.likes = sorted(d for d, v in snapshot['items'].items() if v == 'like' and catalog.valid(d))
        self.sar = SimpleNamespace(seen={'visitor': set(snapshot['items'])})
        vector = csr_matrix(catalog.documents[[catalog.position[d] for d in self.likes]].sum(axis=0)) if self.likes else csr_matrix((1, catalog.documents.shape[1]))
        self.norm = float(np.sqrt(vector.multiply(vector).sum()))
        self.profile = normalize(vector)
        self.user2row = {'visitor': 0} if self.norm else {}

    def recommend(self, user: str, at: str, method: str, k: int, alpha: float) -> list[dict]:
        if method != 'content' or type(k) is not int or not 1 <= k <= 10:
            raise ValueError('Personal content recommendation requires k=1..10')
        when = datetime.fromisoformat(at).timestamp()
        scores = linear_kernel(self.profile, self.base.documents).ravel() if self.norm else self.base.popularity
        indices = np.array([i for i, d in enumerate(self.catalog) if self.available[i] <= when and d not in self.snapshot['items']], dtype=int)
        indices = indices[np.argsort(-scores[indices], kind='stable')[:k]]
        return [self.base.paper(self.catalog[i]) | {'score': float(scores[i]), 'explanation': self.explain(int(i), float(scores[i]))} for i in indices]

    def explain(self, index: int, score: float) -> dict:
        if not self.norm:
            return {'kind': 'popularity_fallback', 'training_likes': int(score), 'reason': '尚无有效收藏画像，按冻结训练期点赞数排序'}
        document = self.base.documents[index]
        contributions = document.multiply(self.profile).tocsr()
        order = np.argsort(-contributions.data, kind='stable')[:6]
        similar = linear_kernel(document, self.base.documents[[self.base.position[d] for d in self.likes]]).ravel()
        anchors = np.argsort(-similar, kind='stable')[:3]
        return {'kind': 'content_similarity', 'cosine': score, 'profile_revision': self.snapshot['revision'],
                'anchors': [self.base.paper(self.likes[j]) | {'cosine': float(similar[j]), 'score_contribution': float(similar[j] / self.norm)} for j in anchors if similar[j] > 0],
                'terms': [{'term': str(self.base.features[contributions.indices[j]]), 'contribution': float(contributions.data[j])} for j in order if contributions.data[j] > 0],
                'all_term_contribution_sum': float(contributions.sum()), 'all_anchor_contribution_sum': float(similar.sum() / self.norm),
                'note': '词项重合与收藏论文向量贡献；不是语义正确性或推荐效果证明'}

    def read(self, doc: str, at: str) -> dict:
        return ExpansionRecommender.read(self, doc, at)


class PersonalClient(ToolClient):
    def __init__(self, task: dict, catalog: Catalog, snapshot: dict):
        model = PersonalModel(catalog, snapshot)
        self.searcher = AsOfBM25(model)
        self.session = UnifiedSession(model, self.searcher, 'visitor', task['at'])
        self.accepted = self.accepted_input = None

    def call(self, name: str, **arguments: object) -> dict:
        result = self.session.invoke(name, arguments)
        if 'error' in result: raise ValueError(result['error'])
        return result

    def snapshot(self) -> dict:
        return self.session.snapshot()

    def close(self) -> None:
        self.searcher.close()
