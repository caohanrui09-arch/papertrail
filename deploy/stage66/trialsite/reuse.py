"""Generated unchanged local primitives; provenance in reuse-receipt.json. Do not hand edit."""
from __future__ import annotations
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
import hashlib, json, re, sqlite3, threading, time
import numpy as np
from scipy.sparse import csr_matrix
from sklearn.preprocessing import normalize
from sklearn.metrics.pairwise import linear_kernel
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
MAX_FILE = 256 * 1024
MAX_REQUEST = 2 * MAX_FILE
def aware_timestamp(value):
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if d.tzinfo is None: raise ValueError('Timezone required')
    return d


class PreferenceConflict(ValueError):
    pass

class Preferences:

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('\n                CREATE TABLE IF NOT EXISTS visitors(owner TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0);\n                CREATE TABLE IF NOT EXISTS preferences(owner TEXT, doc_id TEXT, value TEXT NOT NULL,\n                    updated TEXT NOT NULL, PRIMARY KEY(owner,doc_id));\n            ')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
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
            if value not in ('none', 'reset') and doc not in current['items'] and (len(current['items']) >= 500):
                raise ValueError('本地画像最多保存 500 篇偏好，请先移除一些记录')
            if value == 'reset':
                db.execute('DELETE FROM preferences WHERE owner=?', (owner,))
            elif value == 'none':
                db.execute('DELETE FROM preferences WHERE owner=? AND doc_id=?', (owner, doc))
            else:
                db.execute('INSERT OR REPLACE INTO preferences VALUES(?,?,?,?)', (owner, doc, value, datetime.now(timezone.utc).isoformat()))
            db.execute('INSERT OR REPLACE INTO visitors VALUES(?,?)', (owner, revision + 1))
            return self.snapshot(db, owner)

class PersonalModel:

    def __init__(self, catalog: Catalog, snapshot: dict):
        self.base = catalog
        self.by_id, self.catalog = (catalog.by_id, catalog.catalog)
        self.cutoff, self.available = (catalog.cutoff, catalog.available)
        self.snapshot = snapshot
        self.likes = sorted((d for d, v in snapshot['items'].items() if v == 'like' and catalog.valid(d)))
        self.sar = SimpleNamespace(seen={'visitor': set(snapshot['items'])})
        vector = csr_matrix(catalog.documents[[catalog.position[d] for d in self.likes]].sum(axis=0)) if self.likes else csr_matrix((1, catalog.documents.shape[1]))
        self.norm = float(np.sqrt(vector.multiply(vector).sum()))
        self.profile = normalize(vector)
        self.user2row = {'visitor': 0} if self.norm else {}

    def recommend(self, user: str, at: str, method: str, k: int, alpha: float) -> list[dict]:
        if method != 'content' or type(k) is not int or (not 1 <= k <= 10):
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
        return {'kind': 'content_similarity', 'cosine': score, 'profile_revision': self.snapshot['revision'], 'anchors': [self.base.paper(self.likes[j]) | {'cosine': float(similar[j]), 'score_contribution': float(similar[j] / self.norm)} for j in anchors if similar[j] > 0], 'terms': [{'term': str(self.base.features[contributions.indices[j]]), 'contribution': float(contributions.data[j])} for j in order if contributions.data[j] > 0], 'all_term_contribution_sum': float(contributions.sum()), 'all_anchor_contribution_sum': float(similar.sum() / self.norm), 'note': '词项重合与收藏论文向量贡献；不是语义正确性或推荐效果证明'}

def request_time(at: str, cutoff: datetime) -> datetime:
    when = datetime.fromisoformat(at.replace('Z', '+00:00'))
    if when.tzinfo is None or when < cutoff:
        raise ValueError('Timezone-aware request time at/after history cutoff required')
    return when

class AsOfBM25:

    def __init__(self, model: object, max_snapshots: int=2):
        if type(max_snapshots) is not int or max_snapshots < 1:
            raise ValueError('Positive snapshot capacity required')
        self.model = model
        self.max_snapshots = max_snapshots
        self.snapshots: OrderedDict[tuple[str, ...], sqlite3.Connection] = OrderedDict()
        self.lock = threading.RLock()

    def _snapshot(self, at: str) -> tuple[sqlite3.Connection, dict]:
        when = request_time(at, self.model.cutoff).timestamp()
        ids = tuple((d for i, d in enumerate(self.model.catalog) if self.model.available[i] <= when))
        cached = ids in self.snapshots
        started = time.perf_counter()
        if not cached:
            db = sqlite3.connect(':memory:', check_same_thread=False)
            try:
                db.execute("CREATE VIRTUAL TABLE docs USING fts5(doc_id UNINDEXED, title, body, tokenize='porter unicode61')")
                db.executemany('INSERT INTO docs VALUES (?,?,?)', [(d, self.model.by_id[d]['title'], self.model.by_id[d]['abstract']) for d in ids])
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
        return (self.snapshots[ids], {'available_documents': len(ids), 'snapshot_cache_hit': cached, 'snapshot_seconds': time.perf_counter() - started, 'sqlite_version': sqlite3.sqlite_version, 'statistics_scope': 'only available documents; all users share IDF at this time'})

    def search(self, user: str, at: str, query: str, k: int=3) -> dict:
        if not isinstance(query, str) or not query.strip() or len(query) > 2000:
            raise ValueError('Nonempty query up to 2000 characters required')
        if type(k) is not int or not 1 <= k <= 10:
            raise ValueError('Integer k between 1 and 10 required')
        words = list(dict.fromkeys(re.findall('\\w+', query.casefold())))[:128]
        stop = {'a', 'an', 'the', 'is', 'are', 'of', 'to', 'in', 'and', 'or', 'that', 'with', 'for', 'by'}
        expression = ' OR '.join(('"' + word + '"' for word in words if word not in stop))
        with self.lock:
            db, stats = self._snapshot(at)
            db.execute('DELETE FROM seen')
            db.executemany('INSERT INTO seen VALUES (?)', [(d,) for d in self.model.sar.seen.get(user, set())])
            rows = db.execute('SELECT doc_id, bm25(docs,0,2,1) AS score FROM docs WHERE docs MATCH ? AND doc_id NOT IN (SELECT doc_id FROM seen) ORDER BY score, doc_id LIMIT ?', (expression, k)).fetchall() if expression else []
            hits = [{'doc_id': d, 'score': -score, 'title': self.model.by_id[d]['title'], 'version': self.model.by_id[d]['version'], 'source_url': self.model.by_id[d]['source_url']} for d, score in rows]
            return {'papers': hits, 'as_of': at, 'method': 'sqlite_fts5_bm25', 'index': stats}

    def close(self) -> None:
        with self.lock:
            for db in self.snapshots.values():
                db.close()
            self.snapshots.clear()

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

class BackupItem(StrictModel):
    doc_id: str = Field(pattern='^\\d{4}\\.\\d{4,5}$')
    version_key: str = Field(max_length=80)
    title: str = Field(max_length=2000)
    source_url: str = Field(max_length=200)
    preference: Literal['like', 'hide']

class Backup(StrictModel):
    format: Literal['papertrail-preferences']
    schema_version: int = Field(ge=1, le=1)
    catalog_key: str = Field(max_length=100)
    exported_at: str = Field(max_length=80)
    items: list[BackupItem] = Field(max_length=500)

    @field_validator('exported_at')
    @classmethod
    def timestamp(cls, value: str) -> str:
        aware_timestamp(value)
        return value

class ImportRequest(StrictModel):
    text: str = Field(max_length=MAX_FILE)
    revision: int = Field(ge=0)
    policy: Literal['keep_current', 'use_backup'] = 'keep_current'
    preview_token: str | None = Field(default=None, max_length=64)

def unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('备份存在重复 JSON 字段')
        result[key] = value
    return result

def parse_backup(text: str, catalog) -> Backup:
    if len(text.encode('utf-8')) > MAX_FILE:
        raise HTTPException(413, '备份文件不能超过 256 KiB')
    try:
        value = json.loads(text.lstrip('\ufeff'), object_pairs_hook=unique_object)
        backup = Backup.model_validate(value)
    except (ValueError, RecursionError, ValidationError) as error:
        raise HTTPException(422, '备份格式无效：需使用本站导出的 v1 JSON 文件，且字段完整、无重复') from error
    if backup.catalog_key != catalog.catalog_key:
        raise HTTPException(409, '备份目录与当前目录不一致，未导入任何偏好')
    seen = set()
    for item in backup.items:
        if item.doc_id in seen:
            raise HTTPException(422, '备份存在重复论文 ID：' + item.doc_id)
        seen.add(item.doc_id)
        if not catalog.valid(item.doc_id):
            raise HTTPException(422, '论文不在当前可用目录：' + item.doc_id)
        canonical = catalog.paper(item.doc_id)
        if any((getattr(item, key) != canonical[key] for key in ('version_key', 'title', 'source_url'))):
            raise HTTPException(409, '论文版本、标题或来源不一致：' + item.doc_id + '；未导入任何偏好')
    return backup

def merge_plan(backup: Backup, snapshot: dict, policy: str) -> tuple[dict, dict]:
    merged = dict(snapshot['items'])
    rows = []
    counts = dict(added=0, changed=0, conflicts=0, unchanged=0, skipped=0)
    for item in backup.items:
        current = merged.get(item.doc_id, 'none')
        conflict = current != 'none' and current != item.preference
        final = current if conflict and policy == 'keep_current' else item.preference
        status = 'added' if current == 'none' else 'unchanged' if current == item.preference else 'skipped' if final == current else 'changed'
        counts[status] += 1
        counts['conflicts'] += int(conflict)
        merged[item.doc_id] = final
        rows.append({**item.model_dump(), 'current': current, 'result': final, 'status': status, 'conflict': conflict})
    if len(merged) > 500:
        raise HTTPException(422, '合并后偏好超过 500 篇，未导入')
    return (merged, {'rows': rows, 'counts': counts, 'total_after': len(merged), 'retained_outside_backup': len(set(snapshot['items']) - {item.doc_id for item in backup.items})})

class Feedback(BaseModel):
    model_config = ConfigDict(extra='forbid')
    doc_id: str = Field(pattern='^\\d{4}\\.\\d{4,5}$')
    version_key: str = Field(max_length=80)
    catalog_key: str = Field(max_length=100)
    value: Literal['like', 'hide', 'none']
    revision: int = Field(ge=0, strict=True)

class Reset(BaseModel):
    model_config = ConfigDict(extra='forbid')
    catalog_key: str = Field(max_length=100)
    revision: int = Field(ge=0, strict=True)
