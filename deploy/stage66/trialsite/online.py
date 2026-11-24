"""Bounded live metadata search, separate from the frozen experiment catalog."""
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import threading
import time
from typing import Literal
from urllib.parse import urlsplit

from fastapi import HTTPException, Query

VENDOR = Path(__file__).resolve().parents[1] / 'api-vendor'
if str(VENDOR) not in sys.path:
    sys.path.append(str(VENDOR))
import requests
import arxiv
from .openalex_abstract import invert_abstract

PAGE_SIZE = 10
MAX_BODY = 2 * 1024 * 1024
ENDPOINTS = {'arxiv': 'https://export.arxiv.org/api/query', 'openalex': 'https://api.openalex.org/works'}


def text(value, limit=2000):
    return value[:limit] if isinstance(value, str) else ''


def safe_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return None


def abstract_from_index(value):
    if not isinstance(value, dict) or len(value) > 12000:
        return None
    count = 0
    for word, positions in value.items():
        if not isinstance(word, str) or len(word) > 1000 or not isinstance(positions, list):
            return None
        count += len(positions)
        if count > 16000 or any(type(p) is not int or p < 0 or p > 50000 for p in positions):
            return None
    return text(invert_abstract(value), 24000) or None


class OnlineSearch:
    def __init__(self, transport=None, clock=time.monotonic):
        self.clock = clock
        self.transport = transport or self.fetch
        self.lock = threading.Lock()
        self.cache = OrderedDict()
        self.next_call = {'arxiv': 0., 'openalex': 0.}
        self.cooldown = {'arxiv': 0., 'openalex': 0.}
        self.window = self.clock()
        self.calls = 0

    def fetch(self, provider, params):
        # Only these fixed public endpoints are requested. Returned links are never fetched.
        with requests.get(ENDPOINTS[provider], params=params, timeout=(5, 12),
                          allow_redirects=False, stream=True,
                          headers={'User-Agent': 'Papertrail/61 (independent academic metadata search)', 'Accept': 'application/atom+xml' if provider == 'arxiv' else 'application/json'}) as response:
            if response.status_code != 200:
                delay = response.headers.get('Retry-After', '')
                retry = min(max(int(delay), 60), 3600) if delay.isdigit() else 300
                if response.status_code in (429, 403):
                    self.cooldown[provider] = self.clock() + retry
                    raise HTTPException(503, '来源限流或额度暂不可用，请稍后重试或切换来源。', headers={'Retry-After': str(retry)})
                raise HTTPException(502, '论文来源暂时未能返回结果，请稍后重试。')
            chunks, size, deadline = [], 0, self.clock() + 18
            for chunk in response.iter_content(32768):
                size += len(chunk)
                if size > MAX_BODY or self.clock() > deadline:
                    raise HTTPException(502, '来源响应超过本次大小或时间限制。')
                chunks.append(chunk)
            return b''.join(chunks)

    def search(self, provider, query, page=1, year=None):
        query = query.strip()
        if not 2 <= len(query) <= 300 or any(ord(c) < 32 for c in query):
            raise HTTPException(422, '请输入2–300个字符的论文关键词。')
        if provider not in ENDPOINTS or not 1 <= page <= 100 or (year is not None and not 1900 <= year <= datetime.now(timezone.utc).year):
            raise HTTPException(422, '来源、页码或年份不合法。')
        params = self.params(provider, query, page, year)
        key = (provider, query, page, year)
        if not self.lock.acquire(blocking=False):
            raise HTTPException(503, '另一个在线查询正在进行，请稍后重试。', headers={'Retry-After': '3'})
        try:
            now = self.clock()
            if key in self.cache and now - self.cache[key][0] < 900:
                self.cache.move_to_end(key)
                return self.cache[key][1] | {'cached': True}
            if now < self.cooldown[provider]:
                delay = max(1, int(self.cooldown[provider] - now) + 1)
                raise HTTPException(503, '该来源正在冷却，请稍后重试或选择其他来源。', headers={'Retry-After': str(delay)})
            if now - self.window >= 86400:
                self.window, self.calls = now, 0
            if self.calls >= 80:
                raise HTTPException(429, '本机在线搜索已达到本轮24小时试用预算（80次未缓存请求）。')
            wait = self.next_call[provider] - now
            if wait > 0:
                time.sleep(min(wait, 3.1))
            self.next_call[provider] = self.clock() + (3.1 if provider == 'arxiv' else 1.1)
            self.calls += 1
            try:
                raw = self.transport(provider, params)
                if len(raw) > MAX_BODY:
                    raise ValueError('oversized')
                papers, total = self.parse(provider, raw)
            except HTTPException:
                raise
            except requests.exceptions.Timeout:
                raise HTTPException(504, '论文来源响应超时，可重试或切换来源。') from None
            except requests.exceptions.RequestException:
                raise HTTPException(502, '暂时无法连接论文来源，请检查网络或稍后重试。') from None
            except (ValueError, TypeError, KeyError, AttributeError):
                raise HTTPException(502, '来源数据暂时无法解析，没有把它当作“无结果”。') from None
            value = {'provider': provider, 'query': query, 'page': page, 'page_size': PAGE_SIZE,
                     'year': year, 'total': total, 'papers': papers,
                     'source_endpoint': ENDPOINTS[provider], 'source_parameters': params,
                     'page_limit': 100,
                     'has_next': page < 100 and page * PAGE_SIZE < total,
                     'cached': False, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                     'response_sha256': hashlib.sha256(raw).hexdigest(),
                     'scope': '来源当前返回的在线元数据，按来源排序；未写入站内167篇目录或冻结实验。'}
            self.cache[key] = (self.clock(), value)
            self.cache.move_to_end(key)
            while len(self.cache) > 64:
                self.cache.popitem(last=False)
            return value
        finally:
            self.lock.release()

    @staticmethod
    def params(provider, query, page, year):
        if provider == 'arxiv':
            # Treat the input as literal terms, never as arXiv query operators.
            terms = re.findall(r'[^\W_]+(?:[-.][^\W_]+)*', query, re.UNICODE)
            if not terms:
                raise HTTPException(422, '请输入标题或主题关键词。')
            if len(terms) > 40:
                raise HTTPException(422, 'arXiv单次最多40个词项，请精简检索词。')
            expression = ' AND '.join('all:"' + term + '"' for term in terms)
            if year:
                expression += f' AND submittedDate:[{year}01010000 TO {year}12312359]'
            search = arxiv.Search(query=expression, max_results=PAGE_SIZE, sort_by=arxiv.SortCriterion.Relevance)
            return search._url_args() | {'start': str((page - 1) * PAGE_SIZE), 'max_results': str(PAGE_SIZE)}
        params = {'search': query, 'page': page, 'per_page': PAGE_SIZE,
                  'select': 'id,doi,title,publication_year,publication_date,authorships,abstract_inverted_index,primary_location,best_oa_location,open_access,ids'}
        if year:
            params['filter'] = f'publication_year:{year}'
        return params

    @staticmethod
    def parse(provider, raw):
        if provider == 'arxiv':
            feed = arxiv._feed.parse(raw)
            if feed.malformed:
                raise ValueError('malformed atom')
            papers = []
            for row in feed.results[:PAGE_SIZE]:
                identity = row.get_short_id()
                if not re.fullmatch(r'(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})v\d+', identity):
                    continue
                abstract = text(row.summary, 24000) or None
                papers.append({'id': 'arxiv:' + identity, 'title': text(row.title),
                    'authors': [text(a.name, 160) for a in row.authors[:30]],
                    'year': row.published.year, 'date': row.published.date().isoformat(),
                    'date_kind': 'arXiv首次提交', 'version': identity,
                    'abstract': abstract, 'abstract_source': 'arXiv API原摘要',
                    'source_url': 'https://arxiv.org/abs/' + identity,
                    'open_url': 'https://arxiv.org/pdf/' + identity,
                    'access': 'open_fulltext', 'doi': text(row.doi), 'provider': 'arxiv'})
            return papers, feed.header.total_results
        data = json.loads(raw)
        if not isinstance(data.get('results'), list) or type(data.get('meta', {}).get('count')) is not int:
            raise ValueError('invalid response')
        papers = []
        for row in data['results'][:PAGE_SIZE]:
            identity = text(row.get('id'))
            if not re.fullmatch(r'https://openalex.org/W\d+', identity):
                continue
            abstract = abstract_from_index(row.get('abstract_inverted_index'))
            location = row.get('primary_location') or {}
            oa = row.get('best_oa_location') or {}
            open_url = safe_url(oa.get('pdf_url')) or safe_url(oa.get('landing_page_url'))
            doi = safe_url(row.get('doi'))
            papers.append({'id': identity, 'title': text(row.get('title')) or '题名缺失',
                'authors': [text((a.get('author') or {}).get('display_name'), 160) for a in (row.get('authorships') or [])[:30] if isinstance(a, dict)],
                'year': row.get('publication_year') if type(row.get('publication_year')) is int else None,
                'date': text(row.get('publication_date'), 20), 'date_kind': 'OpenAlex发表日期记录',
                'version': None, 'abstract': abstract, 'abstract_source': 'OpenAlex摘要索引还原' if abstract else None,
                'source_url': safe_url(location.get('landing_page_url')) or doi or identity,
                'open_url': open_url, 'access': 'open_fulltext' if open_url else 'abstract_only' if abstract else 'metadata_only',
                'doi': doi, 'provider': 'openalex'})
        return papers, max(0, data['meta']['count'])


def install_online(app, service=None):
    service = service or OnlineSearch()
    app.state.online_search = service

    @app.get('/api/online/search')
    def online_search(provider: Literal['arxiv', 'openalex'] = 'arxiv',
                      q: str = Query(min_length=2, max_length=300),
                      page: int = Query(default=1, ge=1, le=100),
                      year: int | None = Query(default=None, ge=1900, le=datetime.now(timezone.utc).year)):
        return service.search(provider, q, page, year)
