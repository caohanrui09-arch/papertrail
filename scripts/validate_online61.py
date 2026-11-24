"""Live-search contracts with injected source responses and disposable visitor stores."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deploy/stage61'))
from fastapi import HTTPException
from trialsite.delivery import create_app
from trialsite.security import Settings
from trialsite.online import OnlineSearch, safe_url, abstract_from_index, requests, MAX_BODY
from scripts.validate_trial import call

CHECKS = []


def check(name, value):
    assert value, name
    CHECKS.append(name)


def fails(name, operation, status):
    try:
        operation()
    except HTTPException as error:
        check(name, error.status_code == status)
    else:
        raise AssertionError(name)


ATOM = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
<opensearch:totalResults>21</opensearch:totalResults><opensearch:startIndex>10</opensearch:startIndex><opensearch:itemsPerPage>10</opensearch:itemsPerPage>
<entry><id>http://arxiv.org/abs/2504.18458v3</id><updated>2026-01-02T00:00:00Z</updated><published>2025-04-25T00:00:00Z</published><title>Actual &lt;script&gt;title&lt;/script&gt;</title><summary>Original abstract</summary><author><name>First Author</name></author><category term="cs.AI"/></entry></feed>'''


def openalex_row(**changes):
    return {'id': 'https://openalex.org/W123', 'title': 'Actual paper', 'doi': 'https://doi.org/10.1234/test',
            'publication_year': 2026, 'publication_date': '2026-01-02',
            'authorships': [{'author': {'display_name': 'Author'}}],
            'abstract_inverted_index': {'world': [1], 'Hello': [0]},
            'primary_location': {'landing_page_url': 'https://publisher.example/paper'},
            'best_oa_location': None, **changes}


def payload(row=None, count=31):
    return json.dumps({'meta': {'count': count}, 'results': [row or openalex_row()]}).encode()


async def main():
    papers, total = OnlineSearch.parse('arxiv', ATOM)
    check('native_atom_parser_and_total', total == 21 and len(papers) == 1)
    check('version_is_actual_v3_not_fabricated_v1', papers[0]['version'] == '2504.18458v3' and papers[0]['source_url'].endswith('v3'))
    check('source_date_and_authors', papers[0]['date'] == '2025-04-25' and papers[0]['authors'] == ['First Author'])
    check('raw_text_not_generated_summary', papers[0]['abstract'] == 'Original abstract' and '<script>' in papers[0]['title'])
    check('canonical_pdf_same_version', papers[0]['open_url'] == 'https://arxiv.org/pdf/2504.18458v3')
    rows, total = OnlineSearch.parse('openalex', payload())
    check('native_pyalex_abstract_reconstruction', rows[0]['abstract'] == 'Hello world')
    check('no_assumed_open_access', rows[0]['access'] == 'abstract_only' and rows[0]['open_url'] is None)
    check('unknown_version_is_explicit', rows[0]['version'] is None)
    rows, _ = OnlineSearch.parse('openalex', payload(openalex_row(abstract_inverted_index=None)))
    check('missing_abstract_is_metadata_only', rows[0]['abstract'] is None and rows[0]['access'] == 'metadata_only')
    rows, _ = OnlineSearch.parse('openalex', payload(openalex_row(best_oa_location={'pdf_url': 'https://repository.example/p.pdf'})))
    check('oa_link_not_fulltext_content', rows[0]['access'] == 'open_fulltext' and 'fulltext' not in rows[0])
    for url in ['javascript:alert(1)', 'data:text/html,test', 'https://u:p@example.org', 'https://example.org/\nfoo', 'https://[invalid']:
        check('unsafe_link_' + str(len(CHECKS)), safe_url(url) is None)
    check('safe_https_source', safe_url('https://doi.org/10.123/a') is not None)
    for value in [{'word': [-1]}, {'word': ['0']}, {'word': list(range(16001))}, []]:
        check('bounded_abstract_' + str(len(CHECKS)), abstract_from_index(value) is None)
    params = OnlineSearch.params('arxiv', 'fast AND slow', 2, 2025)
    check('arxiv_page_offsets', params['start'] == '10' and params['max_results'] == '10')
    check('arxiv_terms_literal_and_year_range', 'all:"AND"' in params['search_query'] and '202501010000' in params['search_query'])
    check('openalex_native_page_year', OnlineSearch.params('openalex', 'fast slow', 3, 2026)['filter'] == 'publication_year:2026')
    fails('long_arxiv_query_rejected_not_silently_truncated', lambda: OnlineSearch.params('arxiv', 'aa ' * 41, 1, None), 422)
    calls = []
    now = [100000.]
    service = OnlineSearch(lambda provider, params: calls.append(params) or payload(), clock=lambda: now[0])
    first = service.search('openalex', 'test paper', 1)
    second = service.search('openalex', 'test paper', 1)
    check('identical_query_cached', len(calls) == 1 and not first['cached'] and second['cached'])
    check('cached_preserves_retrieval_and_hash', first['retrieved_at'] == second['retrieved_at'] and first['response_sha256'] == second['response_sha256'])
    check('pagination_from_source_total', first['has_next'] and first['total'] == 31)
    service.next_call['openalex'] = 0
    third = service.search('openalex', 'test paper', 4)
    check('last_page_has_no_next', not third['has_next'])
    now[0] += 901
    service.search('openalex', 'test paper', 1)
    check('expired_cache_refetched', len(calls) == 3)
    service.cooldown['openalex'] = now[0] + 50
    fails('cooldown_explicit_not_zero_results', lambda: service.search('openalex', 'another query'), 503)
    service.lock.acquire()
    try:
        fails('concurrency_bounded', lambda: service.search('arxiv', 'another query'), 503)
    finally:
        service.lock.release()
    for query in [' ', 'x', 'x' * 301, 'test\nquery']:
        fails('query_validation_' + str(len(CHECKS)), lambda q=query: service.search('arxiv', q), 422)
    fails('unknown_provider_rejected', lambda: service.search('custom', 'valid query'), 422)
    fails('page_budget_rejected', lambda: service.search('arxiv', 'valid query', 101), 422)
    service.cooldown['openalex'] = 0
    service.calls = 80
    fails('process_day_budget', lambda: service.search('openalex', 'new query'), 429)
    for _ in range(65):
        now[0] += 2
        service.calls = 0
        service.search('openalex', 'unique ' + str(_))
    check('cache_entry_cap', len(service.cache) == 64)
    for name, body in [('invalid_json', b'not json'), ('oversized', b'x' * (MAX_BODY + 1)), ('bad_shape', b'{"meta":{"count":0}}')]:
        s = OnlineSearch(lambda provider, params, raw=body: raw)
        fails(name, lambda: s.search('openalex', 'valid query'), 502)
        check(name + '_not_cached', not s.cache)
    for exception, status in [(requests.exceptions.Timeout(), 504), (requests.exceptions.ConnectionError(), 502)]:
        def transport(provider, params):
            raise exception
        s = OnlineSearch(transport)
        fails('network_' + str(status), lambda: s.search('arxiv', 'valid query'), status)
    class Response:
        status_code = 429
        headers = {'Retry-After': '120'}
        def __enter__(self): return self
        def __exit__(self, *args): return False
    from unittest.mock import patch
    s = OnlineSearch(clock=lambda: 100000.)
    with patch.object(requests, 'get', return_value=Response()) as network:
        fails('real_transport_429_cooldown', lambda: s.search('arxiv', 'valid query'), 503)
        check('source_cooldown_set', s.cooldown['arxiv'] == 100120.)
        check('transport_timeout_and_no_redirect', network.call_args.kwargs['timeout'] == (5, 12) and network.call_args.kwargs['allow_redirects'] is False)
    with tempfile.TemporaryDirectory(dir=ROOT / '.cache/stage61') as folder:
        app = create_app(Settings('https://trial.example', Path(folder)))
        app.state.online_search.transport = lambda provider, params: payload()
        status, data, headers = await call(app, '/api/online/search?provider=openalex&q=valid%20query')
        check('route_success_real_adapter', status == 200 and data['papers'][0]['id'] == 'https://openalex.org/W123')
        check('no_profile_created_by_search', 'set-cookie' not in headers)
        for suffix in ['provider=other&q=hello', 'provider=arxiv&q=x', 'provider=arxiv&q=hello&page=101', 'provider=arxiv&q=hello&year=2199']:
            check('route_validation_' + suffix, (await call(app, '/api/online/search?' + suffix))[0] == 422)
        check('cross_site_blocked', (await call(app, '/api/online/search?q=valid', headers={'sec-fetch-site': 'cross-site'}))[0] == 403)
        check('frozen_catalog_unchanged', len(app.state.catalog.catalog) == 167)
        app.state.catalog.close()
    (ROOT / 'reports/stage61/online-validation.json').write_text(json.dumps({'status': 'passed', 'passed': len(CHECKS), 'checks': CHECKS, 'scope': 'injected source faults and disposable API stores; not browser or real-feedback testing'}, indent=2) + '\n', encoding='utf8')
    print({'passed': len(CHECKS)})


if __name__ == '__main__':
    asyncio.run(main())
