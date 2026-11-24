"""Actual HTTP migration, isolation and concurrency; disposable visitor spaces only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from http.cookiejar import CookieJar
import json
from pathlib import Path
import urllib.request
import urllib.error
from gsearch.quality_protocol import save

URL = 'http://127.0.0.1:8778'
OUT = Path('reports/stage36/backup-http-validation.json')


def main():
    assert not OUT.exists(), 'Preserve completed acceptance'
    checks = []
    clients = [urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(CookieJar())) for _ in range(3)]

    def call(client, path, body=None, expected=200, headers=None, raw=None):
        sent = {'Origin': URL, **(headers or {})}
        if body is not None or raw is not None:
            sent['Content-Type'] = 'application/json'
        req = urllib.request.Request(URL + path, data=raw if raw is not None else json.dumps(body).encode() if body is not None else None, headers=sent)
        try:
            with client.open(req, timeout=15) as response:
                code, data, received = response.status, response.read(), response.headers
        except urllib.error.HTTPError as e:
            code, data, received = e.code, e.read(), e.headers
        assert code == expected, (path, code, data[:250])
        checks.append({'path': path, 'method': req.get_method(), 'status': code})
        assert received.get('Cache-Control') == 'no-store'
        return json.loads(data), received

    def get(client, path='/api/profile'):
        return call(client, path)[0]

    def change(client, paper, value):
        profile = get(client)
        return call(client, '/api/profile/feedback', dict(doc_id=paper['doc_id'], version_key=paper['version_key'],
                    catalog_key=profile['catalog_key'], revision=profile['revision'], value=value))[0]

    def prepare(client, backup, policy='keep_current'):
        body = dict(text=json.dumps(backup), policy=policy, revision=get(client)['revision'])
        plan = call(client, '/api/profile/import/preview', body)[0]
        return {**body, 'preview_token': plan['preview_token']}, plan

    a, b, c = clients
    try:
        assert not get(a)['items'] and not get(b)['items'] and not get(c)['items']
        nci, fm, extra = [get(a, '/api/paper/' + doc)['paper'] for doc in ('2206.02743', '1507.08439', '2502.02788')]
        change(a, nci, 'like'); change(a, fm, 'hide')
        original = get(a)
        original_recs = get(a, '/api/recommendations')['papers']
        backup, headers = call(a, '/api/profile/export')
        assert 'attachment' in headers['Content-Disposition']
        assert set(backup) == {'format', 'schema_version', 'catalog_key', 'exported_at', 'items'}
        assert {p['preference'] for p in backup['items']} == {'like', 'hide'}
        assert all(set(p) == {'doc_id', 'version_key', 'title', 'source_url', 'preference'} for p in backup['items'])
        # Literal duplicate keys must be rejected, not accepted by last-key-wins parsing.
        bads = [(backup | {'schema_version': True}, 422), (backup | {'schema_version': 2}, 422),
                (backup | {'catalog_key': 'old-10000'}, 409), (backup | {'owner': 'other'}, 422),
                (backup | {'items': backup['items'] * 2}, 422), (backup | {'items': backup['items'] * 251}, 422),
                (backup | {'exported_at': '2026-10-30T12:00:00'}, 422)]
        for field, value, status in [('version_key', '2206.02743v99', 409), ('title', '<script>bad</script>', 409),
                                     ('source_url', 'https://evil.invalid', 409), ('doc_id', '9999.12345', 422),
                                     ('preference', 'none', 422)]:
            bad = deepcopy(backup); bad['items'][0][field] = value; bads.append((bad, status))
        before = get(b)
        for bad, status in bads:
            call(b, '/api/profile/import/preview', dict(text=json.dumps(bad), revision=before['revision']), status)
        for text in ('{', '[]', '{"format":"x","format":"y"}', '[' * 1100 + ']' * 1100):
            call(b, '/api/profile/import/preview', dict(text=text, revision=0), 422)
        call(b, '/api/profile/import/preview', dict(text='x' * (256 * 1024 + 1), revision=0), 422)
        call(b, '/api/profile/import/preview', dict(text='中' * 90000, revision=0), 413)
        call(b, '/api/profile/import/preview', raw=b' ' * (512 * 1024 + 1), expected=413)
        call(b, '/api/profile/import/preview', dict(text=json.dumps(backup), revision=True), 422)
        assert get(b) == before
        body, plan = prepare(b, backup)
        assert plan['counts']['added'] == 2 and not get(b)['items']
        call(b, '/api/profile/import/apply', {**body, 'preview_token': None}, 409)
        call(c, '/api/profile/import/apply', body, 409)  # Token cannot cross owners.
        call(b, '/api/profile/import/apply', {**body, 'policy': 'use_backup'}, 409)
        call(b, '/api/profile/import/apply', {**body, 'text': body['text'] + ' '}, 409)
        call(b, '/api/profile/import/apply', body, 403, {'Origin': 'http://other.invalid'})
        result = call(b, '/api/profile/import/apply', body)[0]
        assert result['applied'] == 2 and result['revision'] == 1
        assert get(b)['items'] == original['items']
        actual = get(b, '/api/recommendations')['papers']
        assert [(p['doc_id'], p['score']) for p in actual] == [(p['doc_id'], p['score']) for p in original_recs]
        # Reimporting same backup is idempotent, including revision.
        body, plan = prepare(b, backup)
        assert plan['counts']['unchanged'] == 2
        noop = call(b, '/api/profile/import/apply', body)[0]
        assert noop['applied'] == 0 and noop['revision'] == 1
        # Conflicts are shown, unrelated local preference survives either policy.
        change(b, nci, 'hide'); change(b, extra, 'like')
        body, plan = prepare(b, backup)
        assert plan['counts']['conflicts'] == plan['counts']['skipped'] == 1 and plan['retained_outside_backup'] == 1
        assert call(b, '/api/profile/import/apply', body)[0]['applied'] == 0
        body, plan = prepare(b, backup, 'use_backup')
        assert plan['counts']['changed'] == 1
        assert call(b, '/api/profile/import/apply', body)[0]['applied'] == 1
        assert {p['doc_id']: p['preference'] for p in get(b)['items']} == {nci['doc_id']: 'like', fm['doc_id']: 'hide', extra['doc_id']: 'like'}
        body, _ = prepare(b, backup)
        change(b, extra, 'hide')
        call(b, '/api/profile/import/apply', body, 409)
        assert {p['doc_id']: p['preference'] for p in get(b)['items']}[extra['doc_id']] == 'hide'
        empty = backup | {'items': []}
        body, plan = prepare(b, empty)
        assert plan['total_after'] == plan['retained_outside_backup'] == 3
        assert call(b, '/api/profile/import/apply', body)[0]['applied'] == 0
        # Two identical confirmed commits: exactly one writes; old revision is refused.
        body, _ = prepare(c, backup)
        def submit():
            req = urllib.request.Request(URL + '/api/profile/import/apply', data=json.dumps(body).encode(), headers={'Content-Type':'application/json', 'Origin':URL})
            try:
                with c.open(req, timeout=15) as response: return response.status
            except urllib.error.HTTPError as error: return error.code
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = sorted(executor.map(lambda _: submit(), range(2)))
        assert statuses == [200, 409], statuses
        assert get(c)['revision'] == 1 and get(c)['items'] == original['items']
        assert get(a) == original  # Exports, previews, other's imports never modify source.
        private = Path('data/stage36-ui'); private.mkdir(parents=True, exist_ok=True)
        save(private / 'roundtrip-test-backup.json', backup)
    finally:
        for client in clients:
            p = get(client)
            if p['items']:
                call(client, '/api/profile/reset', {'catalog_key': p['catalog_key'], 'revision': p['revision']})
            assert not get(client)['items']
    save(OUT, {'status': 'passed', 'http_count': len(checks), 'checks': checks,
               'concurrent_statuses': statuses, 'roundtrip_rank_and_scores_equal': True,
               'source_unchanged': True, 'test_spaces_cleaned': True, 'no_credentials_in_export': True})
    print(json.dumps({'status':'passed', 'http_checks':len(checks), 'concurrent':statuses}))


if __name__ == '__main__':
    main()
