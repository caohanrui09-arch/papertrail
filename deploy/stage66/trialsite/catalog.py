"""Trial adapter over native SQLite BM25 and the previously verified content model."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from fastapi import HTTPException
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel
from sklearn.preprocessing import normalize

from .reuse import AsOfBM25, PersonalModel


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Catalog:
    def __init__(self, root: Path):
        self.root = root
        config = json.loads((root/'config.json').read_text(encoding='utf-8'))
        actual = sha(root/'documents.json')
        if actual != config['documents_sha256']:
            raise ValueError('Catalog hash mismatch')
        rows = json.loads((root/'documents.json').read_text(encoding='utf-8'))
        if not 42 <= len(rows) <= 1000:
            raise ValueError('Trial catalog size outside resource budget')
        self.by_id = {r['doc_id']: r for r in rows}
        self.catalog = sorted(self.by_id)
        if len(rows) != len(self.catalog): raise ValueError('Duplicate paper')
        for row in rows:
            raw = (root/row['provenance']['raw_file']).resolve()
            if not raw.is_relative_to((root/'raw').resolve()) or sha(raw) != row['provenance']['raw_sha256']:
                raise ValueError('Original metadata hash mismatch')
            if row['version'] != 1 or row['version_key'] != 'arxiv:'+row['doc_id']+'v1':
                raise ValueError('Explicit version required')
            if row['source_url'] != 'https://arxiv.org/abs/'+row['doc_id']+'v1':
                raise ValueError('Canonical source URL required')
        self.at, self.topics, self.scenes = config['at'], config['topics'], config['scenes']
        self.position = {d: i for i, d in enumerate(self.catalog)}
        self.cutoff = datetime.fromisoformat('1990-01-01T00:00:00+00:00')
        self.available = np.array([datetime.fromisoformat(self.by_id[d]['available_at']).timestamp() for d in self.catalog])
        if not all(self.valid(d) for d in self.catalog): raise ValueError('Future paper in trial catalog')
        params = config['params'] | {'ngram_range': tuple(config['params']['ngram_range'])}
        self.vectorizer = TfidfVectorizer(**params)
        self.documents = self.vectorizer.fit_transform([self.by_id[d]['title']+'\n'+self.by_id[d]['abstract'] for d in self.catalog])
        self.features = self.vectorizer.get_feature_names_out()
        self.popularity = np.zeros(len(self.catalog))
        self.catalog_key = 'search-trial-v3:'+actual
        self.signature = {'catalog_sha256': actual,
             'vocabulary_sha256': hashlib.sha256(json.dumps({k:int(v) for k,v in self.vectorizer.vocabulary_.items()}, sort_keys=True).encode()).hexdigest(),
             'idf_sha256': hashlib.sha256(self.vectorizer.idf_.tobytes()).hexdigest()}
        self.model = SimpleNamespace(catalog=self.catalog, by_id=self.by_id, cutoff=self.cutoff, available=self.available,
                                     sar=SimpleNamespace(seen={'paired': set(self.scenes['shared_seen_filter'])}))
        self.bm25 = AsOfBM25(self.model, max_snapshots=1)
        self.bm25.search('paired', self.at, 'generative retrieval', 1)  # Warm bounded index.

    def valid(self, doc: str) -> bool:
        return doc in self.position and self.available[self.position[doc]] <= datetime.fromisoformat(self.at).timestamp()

    def paper(self, doc: str) -> dict:
        row = self.by_id[doc]
        return {key: row[key] for key in ('doc_id', 'title', 'version', 'version_key', 'source_url')}

    def read(self, doc: str) -> dict:
        if not self.valid(doc): raise HTTPException(404, '论文不在当前目录')
        row = self.by_id[doc]
        if sha(self.root/row['provenance']['raw_file']) != row['provenance']['raw_sha256']:
            raise HTTPException(503, '原始响应校验失败，暂停读取')
        return {key: row[key] for key in ('doc_id','title','abstract','version_key','source_url','available_at','source_verified')}

    def previews(self) -> dict:
        result = {}
        for doc in self.catalog:
            row, source = self.by_id[doc], self.read(doc)
            end = min(420, len(source['abstract']))
            if end < len(source['abstract']):
                boundary = source['abstract'].rfind(' ', 280, end)
                if boundary >= 280: end = boundary
            result[doc] = {**self.paper(doc), 'source_name':'arXiv', 'published_at': row['published_at'],
                 'submitted_year':datetime.fromisoformat(row['published_at']).year, 'date_kind':'arxiv_first_submission',
                 'available_at':row['available_at'], 'abstract_excerpt':source['abstract'][:end],
                 'excerpt_truncated':end<len(source['abstract']), 'source_verified':True}
        return {'catalog_key': self.catalog_key, 'count':len(result), 'papers':result,
                'scope':'原v1摘要前缀；年份为arXiv首次提交年份；目录噪声初审不是相关性评价'}

    def search(self, topic: str, query: str, method: str, context: str, allowed_ids: set[str] | None = None) -> dict:
        q = self.vectorizer.transform([query])
        scores = linear_kernel(q, self.documents).ravel()
        seen = self.model.sar.seen['paired']
        if method == 'bm25':
            if allowed_ids is None:
                ranked = [r['doc_id'] for r in self.bm25.search('paired', self.at, query, 10)['papers']]
            else:
                from .catalogfilters import filtered_bm25
                ranked = filtered_bm25(self.bm25,self.at,query,allowed_ids)
        else:
            ranked = sorted((d for d in self.catalog if d not in seen and (allowed_ids is None or d in allowed_ids) and scores[self.position[d]]>0),
                            key=lambda d:(-scores[self.position[d]],d))[:10]
        original = list(ranked)
        trace = [{'tool':'核心检索','method':method,'returned':len(ranked),'catalog':len(self.catalog),
                  'eligible':len(self.catalog)-len(seen),'catalog_key':self.catalog_key}]
        history = []
        if context != 'none' and ranked:
            ids = self.scenes[context][topic]
            h = normalize(np.asarray(self.documents[[self.position[d] for d in ids]].sum(axis=0)))
            scores = linear_kernel(normalize(.7*q.toarray()+.3*h), self.documents).ravel()
            ranked = sorted(ranked, key=lambda d:(-scores[self.position[d]],original.index(d)))
            history = [self.read(d) for d in ids]
            trace.append({'tool':'候选内画像排序','context':context,'history_ids':ids,'same_candidates':True,'synthetic':True})
        return {'papers':[{**self.paper(d),'rank':i,'review':None} for i,d in enumerate(ranked,1)],
                'trace':trace,'query':query,'topic':topic,'review_applies':False,'history':history,
                'message':'扩容试用目录：原摘要已核验，尚无真人相关性评价。' if ranked else '未找到词项匹配的论文。',
                'candidate_ids_before_rerank':original}

    def recommend(self, snapshot: dict) -> dict:
        model = PersonalModel(self, snapshot)
        rows = model.recommend('visitor', self.at, 'content', 6, 0) if model.norm else []
        rows = [r for r in rows if r['score']>0]
        for row in rows:
            exp = row['explanation']
            if not (np.isclose(row['score'],exp['all_term_contribution_sum'],rtol=1e-12,atol=1e-12)
                    and np.isclose(row['score'],exp['all_anchor_contribution_sum'],rtol=1e-12,atol=1e-12)):
                raise ValueError('Explanation mismatch')
        return {'papers':[{**r,'rank':i,'review':None} for i,r in enumerate(rows,1)],
                'message':'依据实际收藏的原始标题和摘要计算，排除已反馈论文；词项相似不代表已验证相关。' if model.norm else '请先收藏感兴趣的论文，建立你自己的推荐画像。',
                'query':'基于我的收藏','history':[],'review_applies':False,'profile_revision':snapshot['revision'],
                'catalog_key':self.catalog_key,'model_signature':self.signature,
                'trace':[{'tool':'个人内容推荐','method':'content_tfidf_cosine','profile_revision':snapshot['revision'],
                          'catalog':len(self.catalog),'likes':len(model.likes),'excluded_feedback':len(snapshot['items']),
                          'returned':len(rows),'zero_profile':not bool(model.norm),'used_model_review':False}]}
