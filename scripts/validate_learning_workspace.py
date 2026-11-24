"""Source/response checks in disposable stores; old implementations remain sealed."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
AP=argparse.ArgumentParser();AP.add_argument('--baseline',action='store_true');ARGS=AP.parse_args()
sys.path.insert(0,str(ROOT/('deploy/stage39' if ARGS.baseline else 'deploy/stage40')))
if ARGS.baseline:
    from trialsite.app import create_app
else:
    from trialsite.learning import create_app
from trialsite.security import Settings
from scripts.validate_trial import call,extract


async def main():
    checks=[]
    def check(name,passed):
        if not passed:raise AssertionError(name)
        checks.append(name)
    with tempfile.TemporaryDirectory(prefix='learning-',dir=ROOT/'.cache/stage40') as folder:
        settings=Settings('https://trial.example',Path(folder))
        app=create_app(settings)
        catalog=app.state.catalog
        responses={}
        for topic,config in catalog.topics.items():
            for method in ('bm25','tfidf'):
                for context in ('none','same','cross'):
                    key=':'.join([topic,method,context])
                    path='/api/search?topic='+topic+'&q='+config['core'].replace(' ','%20')+'&method='+method+'&context='+context
                    code,body,_=await call(app,path)
                    assert code==200
                    responses[key]=body
        for path in ['/api/meta','/api/paper-previews','/api/paper/2202.06991']:
            code,body,_=await call(app,path);assert code==200;responses[path]=body
        if ARGS.baseline:
            (ROOT/'.cache/stage40/baseline-responses.json').write_text(json.dumps(responses,ensure_ascii=False),encoding='utf-8')
            print({'baseline_responses':len(responses)})
            return
        baseline=json.loads((ROOT/'.cache/stage40/baseline-responses.json').read_text(encoding='utf-8'))
        for key,body in responses.items():check('unchanged_'+key,body==baseline[key])
        for topic in ['generative','cold','bias']:
            code,result,headers=await call(app,'/api/learning-path/'+topic)
            check('three_papers_'+topic,code==200 and len(result['papers'])==3)
            check('source_fields_'+topic,all(all(p[k]==catalog.paper(p['doc_id'])[k] for k in ['doc_id','title','version_key','source_url']) for p in result['papers']))
            check('exact_abstract_evidence_'+topic,all(p['learning']['evidence'] in catalog.read(p['doc_id'])['abstract'] for p in result['papers']))
            check('editorial_not_grades_'+topic,result['review_applies'] is False and all(p['review'] is None for p in result['papers']) and not result['trace'][0]['used_for_search_or_recommendation_ranking'])
            check('no_hidden_progress_'+topic,'已读' not in result['guide'] and 'completion' not in result)
            check('headers_preserved_'+topic,headers['cache-control']=='no-store' and 'content-security-policy' in headers and 'strict-transport-security' in headers)
        check('invalid_topic',(await call(app,'/api/learning-path/nope'))[0]==422)
        check('path_data_not_static',(await call(app,'/learning-paths.json'))[0]==404)
        _,profile,h=await call(app,'/api/profile');a=extract(h)
        _,other,h=await call(app,'/api/profile');b=extract(h)
        body={'doc_id':'2406.01197','version_key':catalog.by_id['2406.01197']['version_key'],
              'catalog_key':catalog.catalog_key,'value':'like','revision':0}
        check('save_guide_paper',(await call(app,'/api/profile/feedback','POST',body,a))[0]==200)
        before=(await call(app,'/api/profile',cookie=a))[1]
        for topic in ['generative','cold','bias']:await call(app,'/api/learning-path/'+topic,cookie=a)
        check('read_only_profile',(await call(app,'/api/profile',cookie=a))[1]==before)
        check('other_visitor_isolated',(await call(app,'/api/profile',cookie=b))[1]['items']==[])
        code,recs,_=await call(app,'/api/recommendations',cookie=a)
        check('real_favorite_drives_recommendation',code==200 and recs['papers'] and all(all(anchor['doc_id']=='2406.01197' for anchor in p['explanation']['anchors']) for p in recs['papers']))
        exported=(await call(app,'/api/profile/export',cookie=a))[1]
        code,plan,_=await call(app,'/api/profile/import/preview','POST',{'text':json.dumps(exported),'revision':0},b)
        check('backup_preview',code==200 and plan['counts']['added']==1)
        check('backup_apply',(await call(app,'/api/profile/import/apply','POST',{'text':json.dumps(exported),'revision':0,'preview_token':plan['preview_token']},b))[0]==200)
        _,restored,h=await call(app,'/api/profile',cookie=a)
        check('no_new_identity_cookie','set-cookie' not in h)
        # The same volume/key/catalog is compatible across the old base and new wrapper.
        from trialsite.app import create_app as base
        again=base(settings)
        check('same_existing_profile',(await call(again,'/api/profile',cookie=a))[1]==restored)
        check('identical_recommendations',(await call(again,'/api/recommendations',cookie=a))[1]==recs)
        app.state.catalog.bm25.close();again.state.catalog.bm25.close()
    result={'status':'passed','count':len(checks),'checks':checks,'unchanged_response_count':len(responses),
            'guide_papers':9,'scope':'disposable stores; existing routes/rankings/content/preference namespace preserved; no human learning-effect measurement'}
    (ROOT/'reports/stage40/core-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({k:v for k,v in result.items() if k!='checks'})


if __name__=='__main__':asyncio.run(main())
