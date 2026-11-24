"""Regression against stage41 plus new read-only diagnostics in disposable stores."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument('--baseline', action='store_true')
args = ap.parse_args()
sys.path.insert(0, str(ROOT/('deploy/stage41' if args.baseline else 'deploy/stage43')))
if args.baseline:
    from trialsite.minionerec import create_app
else:
    from trialsite.sidlab import create_app
from trialsite.security import Settings
from scripts.validate_trial import call, extract


async def main() -> None:
    checks = []
    def check(name: str, passed: bool) -> None:
        if not passed:
            raise AssertionError(name)
        checks.append(name)
    cache = ROOT/'.cache/stage43'
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='project-', dir=cache) as folder:
        app = create_app(Settings('https://trial.example', Path(folder)))
        catalog = app.state.catalog
        responses = {}
        for topic, config in catalog.topics.items():
            for method in ['bm25', 'tfidf']:
                for context in ['none', 'same', 'cross']:
                    key = ':'.join([topic, method, context])
                    status, body, _ = await call(app, '/api/search?topic='+topic+'&q='+config['core'].replace(' ','%20')+'&method='+method+'&context='+context)
                    assert status == 200
                    responses[key] = body
        for path in ['/api/project/minionerec', '/api/meta', '/api/paper-previews', '/api/paper/2202.06991']+['/api/learning-path/'+t for t in ['generative','cold','bias']]:
            status, body, _ = await call(app, path)
            assert status == 200
            responses[path] = body
        baseline = cache/'baseline.json'
        if args.baseline:
            baseline.write_text(json.dumps(responses, ensure_ascii=False), encoding='utf-8')
            catalog.bm25.close()
            print({'baseline_responses': len(responses)})
            return
        old = json.loads(baseline.read_text(encoding='utf-8'))
        for key, body in responses.items():
            check('unchanged:'+key, body == old[key])
        code, lab, headers = await call(app, '/api/sid-lab')
        check('frozen_diagnostic_payload', code == 200 and lab == json.loads((ROOT/'deploy/stage43/sid-lab.json').read_text(encoding='utf-8')))
        check('sid_security_headers', headers['cache-control'] == 'no-store' and 'content-security-policy' in headers)
        check('sid_no_identity_creation', 'set-cookie' not in headers)
        check('three_fits_sixty_controls', len(lab['fits']) == 3 and sum(len(f['shuffles']) for f in lab['fits']) == 60)
        check('sid_paper_identity', all(all(p[k] == catalog.paper(p['doc_id'])[k] for k in ['title','version_key','source_url']) for p in lab['papers']))
        check('sid_no_model_claim', not lab['decision']['sft_started'] and not lab['decision']['rl_started'])
        check('sid_post_rejected', (await call(app,'/api/sid-lab','POST',{}))[0] == 405)
        check('sid_data_not_static', (await call(app,'/sid-lab.json'))[0] == 404)
        check('sid_receipt_not_static', (await call(app,'/sid-lab-receipt.json'))[0] == 404)
        check('sid_page_served', (await call(app,'/sid-lab.html'))[0] == 200)
        code, project, headers = await call(app, '/api/project/minionerec')
        check('three_originals', code == 200 and len(project['papers']) == 3)
        check('security_headers', headers['cache-control'] == 'no-store' and 'content-security-policy' in headers and 'strict-transport-security' in headers)
        check('independent_recent_supplement', project['historic_catalog_admission'] is False and project['model_trained_here'] is False)
        config = json.loads((catalog.root/'config.json').read_text(encoding='utf-8'))
        check('historic_162', len(catalog.catalog) == 162 and config['at'].startswith('2025-02-23'))
        acquired = json.loads((ROOT/'reports/stage41/papers.json').read_text(encoding='utf-8'))
        originals = {p['doc_id']: p for p in acquired['records']}
        for paper in project['papers']:
            doc = paper['doc_id']
            check('original:'+doc, all(paper[k] == originals[doc][k] for k in ['title','abstract','version','source_url','published_at','authors']))
            check('exact_span:'+doc, paper['evidence'] in paper['abstract'])
            check('fixed_version:'+doc, paper['source_url'].endswith(doc+'v1') and paper['version_key'] == 'arxiv:'+doc+'v1')
        check('future_not_in_historic_search', all(doc not in catalog.by_id for doc in ['2510.24431','2510.12211']))
        check('future_read_rejected', (await call(app,'/api/paper/2510.24431'))[0] == 404)
        check('post_not_supported', (await call(app,'/api/project/minionerec','POST',{}))[0] == 405)
        for path in ['/project.json','/project-original.atom','/api/project/unknown']:
            check('private_asset:'+path, (await call(app,path))[0] == 404)
        _, before, response_headers = await call(app, '/api/profile')
        cookie = extract(response_headers)
        await call(app, '/api/project/minionerec', cookie=cookie)
        await call(app, '/api/sid-lab', cookie=cookie)
        check('read_does_not_mutate_profile', (await call(app,'/api/profile',cookie=cookie))[1] == before)
        feedback = {'doc_id':'2510.24431','version_key':'arxiv:2510.24431v1','catalog_key':catalog.catalog_key,'value':'like','revision':0}
        check('recent_feedback_not_accepted', (await call(app,'/api/profile/feedback','POST',feedback,cookie))[0] in [400,404,422])
        check('rejected_feedback_atomic', (await call(app,'/api/profile',cookie=cookie))[1] == before)
        recs = (await call(app,'/api/recommendations',cookie=cookie))[1]
        check('no_fake_project_recs', recs['papers'] == [])
        from trialsite.learning import create_app as previous
        compat = previous(Settings('https://trial.example', Path(folder)))
        check('cookie_namespace_compatible', (await call(compat,'/api/profile',cookie=cookie))[1] == before)
        check('recommendation_behavior_compatible', (await call(compat,'/api/recommendations',cookie=cookie))[1] == recs)
        compat.state.catalog.bm25.close()
        catalog.bm25.close()
    sources = json.loads((ROOT/'reports/stage41/sources.json').read_text(encoding='utf-8'))
    for item in sources['files']:
        data = (ROOT/'reports/stage41/upstream/MiniOneRec'/item['path']).read_bytes()
        blob = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        check('git_blob:'+item['path'], blob == item['blob'])
    result = {'status':'passed','count':len(checks),'checks':checks,'unchanged_response_count':len(responses),
              'catalog':162,'supplement_originals':3,'training_executed':False,'human_labels_added':0}
    (ROOT/'reports/stage43/core-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({k:v for k,v in result.items() if k != 'checks'})


if __name__ == '__main__':
    asyncio.run(main())
