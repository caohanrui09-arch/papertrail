"""Real HTTP preference, identity, revision, recommendation and isolation checks."""
from copy import copy
from http.cookiejar import CookieJar
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4
import numpy as np
from gsearch.quality_protocol import save

URL = 'http://127.0.0.1:8777'
ROOT = Path('reports/stage35')


def main() -> None:
    assert not (ROOT / 'personal-http-validation.json').exists(), 'Preserve completed HTTP acceptance'
    checks = []
    jars = [CookieJar(), CookieJar()]
    clients = [urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar)) for jar in jars]
    cookie_flags = {}

    def call(client, path, body=None, expected=200, headers=None):
        sent = {'Origin': URL}
        if body is not None:
            sent['Content-Type'] = 'application/json'
        sent.update(headers or {})
        request = urllib.request.Request(URL + path, data=json.dumps(body).encode() if body is not None else None, headers=sent)
        try:
            with client.open(request, timeout=15) as response:
                status, raw, response_headers = response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            status, raw, response_headers = error.code, error.read(), error.headers
        assert status == expected, (path, status, raw[:250].decode(errors='replace'))
        checks.append({'method': request.get_method(), 'path': path, 'status': status})
        cookie = response_headers.get('Set-Cookie')
        if cookie:
            cookie_flags.update(httponly='HttpOnly' in cookie, strict_samesite='SameSite=strict' in cookie, persistent='Max-Age=31536000' in cookie)
        return json.loads(raw) if 'application/json' in response_headers.get('Content-Type', '') else raw.decode()

    def profile(client):
        return call(client, '/api/profile')

    def change(client, paper, value, **overrides):
        current = profile(client)
        body = {'doc_id': paper['doc_id'], 'version_key': paper['version_key'], 'catalog_key': current['catalog_key'],
                'value': value, 'revision': current['revision']}
        body.update(overrides)
        return call(client, '/api/profile/feedback', body)

    a, b = clients
    try:
        initial = profile(a)
        assert initial['catalog_size'] == 42 and initial['revision'] == 0 and not initial['items']
        assert all(cookie_flags.values())
        assert not profile(b)['items']
        assert [cookie.value for cookie in jars[0]] != [cookie.value for cookie in jars[1]]
        empty = call(a, '/api/recommendations')
        assert not empty['papers'] and empty['trace'][0]['zero_profile']
        nci = call(a, '/api/paper/2206.02743')['paper']
        lightfm = call(a, '/api/paper/1507.08439')['paper']
        first = change(a, nci, 'like')
        assert first['like_count'] == 1 and first['hidden_count'] == 0 and first['change']['previous_value'] == 'none'
        recommendations = call(a, '/api/recommendations')
        assert 1 <= len(recommendations['papers']) <= 6 and recommendations['profile_revision'] == first['revision']
        original_ranking = [p['doc_id'] for p in recommendations['papers']]
        assert nci['doc_id'] not in original_ranking
        for paper in recommendations['papers']:
            e = paper['explanation']
            assert paper['score'] > 0 and e['profile_revision'] == first['revision']
            assert {x['doc_id'] for x in e['anchors']} == {nci['doc_id']}
            assert np.isclose(e['all_term_contribution_sum'], paper['score'], atol=1e-12)
            assert np.isclose(e['all_anchor_contribution_sum'], paper['score'], atol=1e-12)
        rec = recommendations['papers'][0]
        original = call(a, '/api/paper/' + rec['doc_id'])['paper']
        assert original['version_key'] == rec['version_key'] and original['source_url'] == rec['source_url'] and original['source_verified']
        assert not profile(b)['items'] and not call(b, '/api/recommendations')['papers']
        valid = {'doc_id': nci['doc_id'], 'version_key': nci['version_key'], 'catalog_key': initial['catalog_key'],
                 'value': 'hide', 'revision': first['revision']}
        call(a, '/api/profile/feedback', {**valid, 'revision': 0}, 409)
        call(a, '/api/profile/feedback', {**valid, 'version_key': 'arxiv:2206.02743v2'}, 409)
        call(a, '/api/profile/feedback', {**valid, 'catalog_key': 'other-catalog'}, 409)
        call(a, '/api/profile/feedback', {**valid, 'doc_id': '9999.12345', 'version_key': 'arxiv:9999.12345v1'}, 422)
        call(a, '/api/profile/feedback', {**valid, 'owner': 'someone-else'}, 422)
        call(a, '/api/profile/feedback', {**valid, 'revision': True}, 422)
        call(a, '/api/profile/feedback', valid, 403, {'Origin': 'http://other.invalid'})
        call(a, '/api/profile', expected=403, headers={'Sec-Fetch-Site': 'cross-site'})
        call(a, '/api/profile', expected=400, headers={'Host': 'other.invalid'})
        assert profile(a)['revision'] == first['revision'] and profile(a)['items'][0]['preference'] == 'like'
        hidden = change(a, rec, 'hide')
        assert hidden['like_count'] == 1 and hidden['hidden_count'] == 1
        assert not ({nci['doc_id'], rec['doc_id']} & {p['doc_id'] for p in call(a, '/api/recommendations')['papers']})
        change(a, rec, 'none')
        assert [p['doc_id'] for p in call(a, '/api/recommendations')['papers']] == original_ranking
        switched = change(a, nci, 'hide')
        assert switched['like_count'] == 0 and switched['hidden_count'] == 1 and switched['change']['previous_value'] == 'like'
        assert not call(a, '/api/recommendations')['papers']
        change(a, nci, 'like')
        assert [p['doc_id'] for p in call(a, '/api/recommendations')['papers']] == original_ranking
        refreshed_jar = CookieJar()
        for cookie in jars[0]:
            refreshed_jar.set_cookie(copy(cookie))
        refreshed = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(refreshed_jar))
        assert profile(refreshed)['items'] == profile(a)['items']
        change(b, lightfm, 'like')
        assert profile(b)['items'][0]['doc_id'] == lightfm['doc_id'] and profile(a)['items'][0]['doc_id'] == nci['doc_id']
        current = profile(a)
        call(a, '/api/profile/reset', {'catalog_key': current['catalog_key'], 'revision': 0}, 409)
        reset = call(a, '/api/profile/reset', {'catalog_key': current['catalog_key'], 'revision': current['revision']})
        assert not reset['items'] and not call(a, '/api/recommendations')['papers']
        assert profile(b)['like_count'] == 1
    except Exception as error:
        save(ROOT / ('personal-http-failure-' + str(uuid4()) + '.json'), {'status': 'failed', 'checks': checks, 'error': str(error)})
        raise
    finally:
        for client in clients:
            current = profile(client)
            if current['items']:
                call(client, '/api/profile/reset', {'catalog_key': current['catalog_key'], 'revision': current['revision']})
            assert not profile(client)['items']
    save(ROOT / 'personal-http-validation.json', {'status': 'passed', 'count': len(checks), 'checks': checks,
         'cookie_flags': cookie_flags, 'two_cookie_spaces_isolated': True, 'refresh_preserves_preferences': True,
         'revision_and_version_and_catalog_rejections': True, 'explanations_match_current_likes_and_score': True,
         'hide_undo_switch_reset_verified': True, 'http_test_preferences_cleaned': True,
         'test_actors_are_not_human_feedback_or_quality_labels': True})
    print(json.dumps({'status': 'passed', 'checks': len(checks), 'test_preferences_cleaned': True}))


if __name__ == '__main__':
    main()
