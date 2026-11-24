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
    shared=[]
    for port in (8791,8802):
        with opener.open(f'http://127.0.0.1:{port}/shared-design.css?v=69.1',timeout=10) as response:
            shared.append(response.read())
    check('shared_styles_identical_on_both_origins',shared[0] == shared[1] == (ROOT/'deploy/stage66/web/shared-design.css').read_bytes())
    with opener.open('http://127.0.0.1:8791/task-preview.json?v=69.1',timeout=10) as response:preview=json.load(response)
    original_path=ROOT/'data/stage64-http/constrained-http-result.json'
    original=json.loads(original_path.read_text(encoding='utf8'))['result']['results'][0]
    check('homepage_preview_exact_tool_trace',preview['trace'] == original['trace']['trace'])
    check('homepage_preview_exact_answer_and_cost',preview['answer'] == original['answer'] and preview['seconds'] == original['seconds'])
    check('homepage_preview_source_hash',preview['source']['sha256'] == hashlib.sha256(original_path.read_bytes()).hexdigest())
    check('homepage_preview_no_model_prompts_or_user_identifier','metadata' not in preview and 'user_id' not in preview['task'])
    code,activity=request('/lab/activity')
    check('readonly_recovery_index',code == 200 and isinstance(activity['jobs'],list))
    check('recovery_index_cross_site_rejected',request('/lab/activity',headers={'Sec-Fetch-Site':'cross-site'})[0] == 403)
    old68=json.loads((ROOT/'reports/stage68/final-validation.json').read_text())['files']
    checked68=0
    for name,digest in old68.items():
        if name=='project-agent.cmd':continue
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest,name
        checked68+=1
    check('stage68_frozen_delivery_preserved',checked68 == 19)
    old69=json.loads((ROOT/'reports/stage69/final-validation.json').read_text())['files']
    checked69=0
    for name,digest in old69.items():
        if name=='project-agent.cmd':continue
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest,name
        checked69+=1
    check('stage69_frozen_delivery_preserved',checked69 == 31)
    old70=json.loads((ROOT/'reports/stage70/final-validation.json').read_text())['files']
    checked70=0
    for name,digest in old70.items():
        if name.replace('\\','/')=='project-agent.cmd':continue
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
        checked70+=1
    check('stage70_frozen_delivery_preserved',checked70==34)
    check('live_event_script_served',request('/live-events.js')[0] == 200)
    check('custom_script_served',request('/custom-ui.js')[0] == 200)
    check('candidate_script_served',request('/candidate-ui.js')[0] == 200)
    old72=json.loads((ROOT/'reports/stage72/final-validation.json').read_text())['files']
    count72=0
    for name,digest in old72.items():
        if name.replace('\\','/') in ('project-agent.cmd','papertrail-workbench.cmd'):continue
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
        count72+=1
    check('stage72_frozen_delivery_preserved',count72==46)
    check('evaluation_entry',request('/evaluation.html')[0]==200)
    old71=json.loads((ROOT/'reports/stage71/final-validation.json').read_text())['files']
    checked71=0
    for name,digest in old71.items():
        if name.replace('\\','/')=='project-agent.cmd':continue
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
        checked71+=1
    check('stage71_frozen_delivery_preserved',checked71==45)
    result={'status':'passed', 'checks':len(checks), 'passed':checks, 'frozen_assets_unchanged':frozen,
            'new_algorithm_quality_claim':False, 'new_model_training':False}
    (ROOT/'reports/stage76/http-regression.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({'status':'passed','checks':len(checks),'frozen_assets':frozen}))


if __name__ == '__main__':
    main()
