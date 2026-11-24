"""Verify presentation adaptation against retained native rankings and tool records."""
from pathlib import Path
import hashlib
import json
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    checks = []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(path, body=None, headers=None):
        req = urllib.request.Request('http://127.0.0.1:8802'+path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            with opener.open(req, timeout=30) as response:
                data=response.read(); code=response.status
        except urllib.error.HTTPError as error:
            data=error.read(); code=error.code
        try:
            return code, json.loads(data)
        except ValueError:
            return code, data.decode('utf8')

    def check(name, value):
        assert value, name
        checks.append(name)

    code, health=request('/health')
    check('same_10000_frozen_catalog', code == 200 and health['candidates'] == 10000)
    for path in ('/', '/lab.css?v=68.1', '/lab.js?v=68.1'):
        check('static_'+path, request(path)[0] == 200)
    documents={row['doc_id']:row for row in json.loads((ROOT/'data/stage13-expansion/documents.json').read_text(encoding='utf8'))}
    for task in ('evaluation-000', 'evaluation-001', 'evaluation-002'):
        previous=json.loads((ROOT/f'data/stage64-http/{task}-ranking.json').read_text(encoding='utf8'))
        code, value=request('/lab/algorithms', {'task_id': task})
        check(task+'_same_clock_and_scope', code == 200 and value['as_of'] == previous['as_of'])
        for method, rows in previous['methods'].items():
            current=value['methods'][method]
            check(task+'_'+method+'_native_order', [p['doc_id'] for p in rows] == [p['doc_id'] for p in current])
            check(task+'_'+method+'_native_scores_and_fields', all(all(p.get(k) == v for k,v in old.items()) for old,p in zip(rows,current)))
            check(task+'_'+method+'_display_metadata', all(all(p[k] == documents[p['doc_id']][k] for k in ('title','published_at','available_at','version_key')) for p in current))
    code, examples=request('/lab/examples')
    check('three_real_replay_records', code == 200 and len(examples['items']) == 3)
    for item in examples['items']:
        path=ROOT/f"data/stage64-http/{item['id']}-http-result.json"
        original=json.loads(path.read_text(encoding='utf8'))['result']['results'][0]
        current=item['result']['results'][0]
        check(item['id']+'_source_hash', item['source_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest())
        check(item['id']+'_exact_executed_trace_and_answer', current['trace'] == original['trace'] and current['answer'] == original['answer'])
        check(item['id']+'_exact_outcome_and_cost', all(current[k] == original[k] for k in ('task_id','policy','seconds','completed_protocol','error')))
        check(item['id']+'_private_model_prompts_not_in_replay', all('model_input_messages' not in step and 'model_output' not in step for step in current['metadata']['steps']))
    for path,body in [('/lab/run',{'task_id':'invalid'}),('/lab/run',{'policy':'invalid'}),('/lab/algorithms',{'task_id':'invalid'})]:
        check('invalid_input_'+str(len(checks)),request(path,body)[0] == 422)
    check('cross_origin_rejected', request('/lab/run',{}, {'Origin':'https://outside.example'})[0] == 403)
    check('cross_site_replay_rejected', request('/lab/examples',headers={'Sec-Fetch-Site':'cross-site'})[0] == 403)
    code, quality=request('/lab/quality')
    check('historical_quality_boundary', code == 200 and 'historical' in quality['scope'])
    code, aggregates=request('/lab/aggregates')
    check('same_old_aggregates', code == 200 and aggregates == json.loads((ROOT/'research68/aggregates.json').read_text(encoding='utf8')))
    frozen={}
    for version in (61, 63):
        manifest=json.loads((ROOT/f'reports/stage{version}/final-validation.json').read_text())
        count=0
        for filename, expected in manifest['files'].items():
            if filename.replace('\\','/') in ('papertrail-workbench.cmd', 'project-agent.cmd'):
                continue
            assert hashlib.sha256((ROOT/filename).read_bytes()).hexdigest() == expected, filename
            count+=1
        frozen[str(version)]=count
    check('old_frozen_experiment_assets_preserved', frozen == {'61':469,'63':16})
    result={'status':'passed', 'checks':len(checks), 'passed':checks, 'frozen_assets_unchanged':frozen,
            'new_algorithm_quality_claim':False, 'new_model_training':False}
    (ROOT/'reports/stage68/http-validation.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({'status':'passed','checks':len(checks),'frozen_assets':frozen}))


if __name__ == '__main__':
    main()
