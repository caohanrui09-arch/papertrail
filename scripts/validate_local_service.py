"""Real loopback HTTP checks; private responses, aggregate-only public receipt."""
import json
from pathlib import Path

from .local_service_control import request, STATE


def main() -> None:
    state = json.loads(STATE.read_text()); port = state['port']
    root = Path('.cache/stage18'); raw = []; checks = []; owned = set()
    def call(method, path, body=None, expected=200, label=''):
        code, payload = request(method, path, body, port)
        raw.append({'method': method, 'path': path, 'request': body, 'status': code, 'response': payload})
        if code != expected:
            raise ValueError(f'HTTP check failed: {label}, expected{expected}, got{code}')
        checks.append({'case': label, 'expected_status': expected, 'passed': True})
        return payload
    try:
        health = call('GET', '/health', label='ready')
        assert health['instance_id'] == state['instance_id'] and health['candidates'] == 10000
        call('GET', '/', label='offline_json_index')
        schema = call('GET', '/openapi.json', label='native_schema')
        assert schema['components']['schemas']['RecommendRequest']['properties']['k']['maximum'] == 10
        call('GET', '/docs', expected=404, label='no_external_cdn_docs')
        reference = json.loads(Path('.cache/stage17/replica/data/relocation-reference/demo.json').read_text(encoding='utf-8'))
        token = call('POST', '/sessions', {}, label='default_content_session')['session_id']; owned.add(token)
        expected_doc = reference['methods']['content']['recommendation']['papers'][0]['doc_id']
        call('POST', f'/sessions/{token}/read', {'doc_id': expected_doc}, expected=400, label='read_requires_recommendation')
        recommended = call('POST', f'/sessions/{token}/recommend', {'k': 3}, label='native_content_recommendation')
        assert recommended['papers'] == reference['methods']['content']['recommendation']['papers']
        original = call('POST', f'/sessions/{token}/read', {'doc_id': expected_doc}, label='exact_original_v1')
        assert original == reference['methods']['content']['original_version_abstract']
        call('POST', f'/sessions/{token}/read', {'doc_id': 'not-returned'}, expected=400, label='unknown_read_rejected')
        call('POST', f'/sessions/{token}/recommend', {'k': 1}, label='third_successful_tool_call')
        call('POST', f'/sessions/{token}/read', {'doc_id': expected_doc}, label='fourth_successful_tool_call')
        call('POST', f'/sessions/{token}/recommend', {'k': 1}, expected=429, label='budget_enforced')
        call('DELETE', f'/sessions/{token}', label='delete_owned_session'); owned.remove(token)
        call('POST', f'/sessions/{token}/recommend', {'k': 1}, expected=404, label='deleted_session_rejected')
        call('POST', '/sessions', {'method': 'unknown'}, expected=422, label='method_enum')
        call('POST', '/sessions', {'alpha': .9}, expected=422, label='no_runtime_parameter_tuning')
        call('POST', '/sessions', {'at': '2020-01-01T00:00:00Z'}, expected=422, label='before_cutoff_rejected')
        call('POST', '/sessions', {'at': '2025-02-23T00:00:00'}, expected=422, label='timezone_required')
        for method, name in (('content', 'content'), ('rrf', 'original_rrf'), ('cold_aware', 'cold_aware')):
            token = call('POST', '/sessions', {'method': method}, label=method + '_session')['session_id']; owned.add(token)
            call('POST', f'/sessions/{token}/recommend', {'k': 11}, expected=422, label=method + '_bounded_k')
            call('POST', f'/sessions/{token}/recommend', {'k': True}, expected=422, label=method + '_strict_integer')
            result = call('POST', f'/sessions/{token}/recommend', {'k': 3}, label=method + '_reference_ranks')
            assert result['papers'] == reference['methods'][name]['recommendation']['papers']
            result = call('POST', f'/sessions/{token}/read', {'doc_id': result['papers'][0]['doc_id']}, label=method + '_source_read')
            assert result == reference['methods'][name]['original_version_abstract']
            call('DELETE', f'/sessions/{token}', label=method + '_cleanup'); owned.remove(token)
        for i in range(64):
            token = call('POST', '/sessions', {}, label='capacity_slot_' + str(i + 1))['session_id']; owned.add(token)
        call('POST', '/sessions', {}, expected=503, label='capacity_enforced')
        for token in list(owned):
            call('DELETE', f'/sessions/{token}', label='capacity_owned_cleanup'); owned.remove(token)
        import psutil
        bindings = sorted({c.laddr.ip for c in psutil.Process(state['pid']).net_connections(kind='inet')
                           if c.status == psutil.CONN_LISTEN and c.laddr.port == port})
        assert bindings == ['127.0.0.1'], bindings
        aggregate = {'status': 'passed', 'checks': checks, 'http_requests': len(checks),
            'three_method_reference_outputs_exact': True, 'three_official_v1_reads_exact': True,
            'max_sessions': 64, 'max_calls': 4, 'observed_bind_addresses': bindings,
            'public_exposure': False, 'default_method': 'content', 'research_alpha_frozen': .25,
            'ttl_real_time_wait_tested': False, 'raw_responses_private': True}
        Path('reports/stage18/http-validation.json').write_text(json.dumps(aggregate, indent=2) + '\n')
        print(json.dumps({'status': 'passed', 'http_checks': len(checks), 'bind': bindings}), flush=True)
    finally:
        for token in owned:
            try: request('DELETE', f'/sessions/{token}', port=port)
            except Exception: pass
        (root / 'http-responses-private.json').write_text(json.dumps(raw, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__': main()
