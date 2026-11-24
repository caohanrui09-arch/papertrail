"""Common search/recommend/read state; citations are exact original excerpts."""
import json
import re
import time
from typing import Callable

from .unified_search import request_time


class UnifiedSession:
    def __init__(self, model: object, search: object, user: str, at: str,
                 method: str = 'content', alpha: float = .25):
        request_time(at, model.cutoff)
        if method not in ('content', 'rrf', 'cold_aware'):
            raise ValueError('Unknown recommendation method')
        self.model, self.searcher, self.user, self.at = model, search, user, at
        self.method, self.alpha = method, alpha
        self.trace: list[dict] = []
        self.returned: dict[str, set[str]] = {}
        self.reads: dict[str, dict] = {}
        self.retrievals = self.read_attempts = self.attempts = 0
        self.final: dict | None = None

    def invoke(self, name: str, arguments: dict) -> dict:
        started = time.perf_counter()
        self.attempts += 1
        try:
            if self.final is not None:
                raise ValueError('Session already finalized')
            if self.attempts > 6:
                raise ValueError('Shared six-attempt tool budget exhausted')
            if name in ('search_papers', 'recommend_papers'):
                self.retrievals += 1
                if self.retrievals > 2:
                    raise ValueError('Two-attempt retrieval budget exhausted')
            if name == 'read_paper':
                self.read_attempts += 1
                if self.read_attempts > 2:
                    raise ValueError('Two-attempt read budget exhausted')
            operation: Callable = {'search_papers': self.search, 'recommend_papers': self.recommend,
                'read_paper': self.read, 'finalize': self.finalize}[name]
            result = operation(**arguments)
        except (ValueError, KeyError, TypeError) as error:
            result = {'error': str(error)}
        self.trace.append({'tool': name, 'arguments': arguments, 'result': result,
                           'seconds': time.perf_counter() - started, 'attempt': self.attempts})
        return result

    def search(self, query: str, k: int = 3) -> dict:
        result = self.searcher.search(self.user, self.at, query, k)
        for paper in result['papers']:
            self.returned.setdefault(paper['doc_id'], set()).add('search_papers')
        return result

    def recommend(self, k: int = 3) -> dict:
        if type(k) is not int or not 1 <= k <= 10:
            raise ValueError('Integer k between 1 and 10 required')
        method = 'hybrid' if self.method == 'rrf' else self.method
        papers = self.model.recommend(self.user, self.at, method, k, .5 if method == 'hybrid' else self.alpha)
        for paper in papers:
            paper['title'] = self.model.by_id[paper['doc_id']]['title']
            self.returned.setdefault(paper['doc_id'], set()).add('recommend_papers')
        return {'papers': papers, 'as_of': self.at, 'method': self.method,
                'cold_user_fallback': self.user not in self.model.user2row}

    def read(self, doc_id: str) -> dict:
        if not isinstance(doc_id, str) or doc_id not in self.returned:
            raise ValueError('Read only an ID returned in this session')
        original = self.model.read(doc_id, self.at)
        if original.get('source_verified') is not True:
            raise ValueError('Original-source verification required')
        # Exact substrings, without rewriting or pretending these are full text.
        pieces = re.split(r'(?<=[.!?])\s+', original['abstract'])
        quotes = [piece[:320] for piece in pieces if piece.strip()][:3]
        if not quotes:
            raise ValueError('No original abstract text')
        result = {**original, 'quotes': [{'quote_index': i, 'text': text} for i, text in enumerate(quotes)]}
        self.reads[doc_id] = result
        return result

    def finalize(self, citations: list[dict]) -> dict:
        if not isinstance(citations, list) or len(citations) > 2:
            raise ValueError('Up to two distinct source citations required')
        if self.retrievals == 0 or not any('error' not in t['result'] and t['tool'] in
                ('search_papers', 'recommend_papers') for t in self.trace):
            raise ValueError('Retrieve before answering')
        papers = []
        used = set()
        for citation in citations:
            if not isinstance(citation, dict) or set(citation) != {'doc_id', 'quote_index'}:
                raise ValueError('Citation requires exactly doc_id and quote_index')
            doc, index = citation['doc_id'], citation['quote_index']
            if not isinstance(doc, str) or doc in used or doc not in self.reads:
                raise ValueError('Cite distinct successfully read IDs')
            original = self.reads[doc]
            if type(index) is not int or not 0 <= index < len(original['quotes']):
                raise ValueError('Existing integer quote index required')
            quote = original['quotes'][index]['text']
            if quote not in original['abstract']:
                raise ValueError('Quote not present in original abstract')
            used.add(doc)
            papers.append({key: original[key] for key in ('doc_id', 'version', 'version_key', 'title', 'source_url')} |
                {'quote': quote, 'quote_index': index, 'source_verified': True,
                 'retrieved_by': sorted(self.returned[doc])})
        if not citations and self.returned:
            raise ValueError('Empty answer allowed only for an empty retrieval')
        self.final = {'citations': papers, 'answer_kind': 'extractive_original_abstract', 'as_of': self.at,
            'answer': '\n\n'.join(f"[{p['doc_id']}v{p['version']}] {p['title']}\n{p['quote']}\n{p['source_url']}" for p in papers)
                      or 'No matching available unread papers found.',
            'semantic_correctness_verified': False,
            'time_assumption': 'v1 submission-day end plus24h; not proven historical ingestion'}
        return self.final

    def snapshot(self) -> dict:
        return {'trace': self.trace, 'attempts': self.attempts, 'retrieval_attempts': self.retrievals,
                'read_attempts': self.read_attempts, 'answer': self.final, 'as_of': self.at}
