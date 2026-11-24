"""Stage53 acceptance: existing behavior unchanged; disposable visitor stores only."""
import asyncio, hashlib, json, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASELINE='--baseline' in sys.argv
sys.path.insert(0,str(ROOT/('deploy/stage43' if BASELINE else 'deploy/stage53')))
if BASELINE:
    from trialsite.sidlab import create_app
else:
    from trialsite.delivery import create_app
from trialsite.security import Settings
from scripts.validate_trial import call, extract
CHECKS=[]
def check(name, value):
    if not value: raise AssertionError(name)
    CHECKS.append(name)
async def main():
    with tempfile.TemporaryDirectory(prefix='asgi-',dir=ROOT/'.cache/stage53') as folder:
        settings=Settings('https://trial.example',Path(folder))
        app=create_app(settings)
        c=app.state.catalog
        old={}
        for topic,config in c.topics.items():
            for method in ('bm25','tfidf'):
                for context in ('none','same','cross'):
                    path=f"/api/search?topic={topic}&q={config['core'].replace(' ','%20')}&method={method}&context={context}"
                    status,value,_=await call(app,path)
                    check('unchanged_search_'+topic+'_'+method+'_'+context,status==200)
                    old[path]=value
        for path in ['/api/meta','/api/project/minionerec','/api/paper/2202.06991']+['/api/learning-path/'+t for t in c.topics]:
            status,value,_=await call(app,path)
            check('existing_'+path,status==200)
            old[path]=value
        reference=ROOT/'.cache/stage53/api-baseline.json'
        if BASELINE:
            reference.write_text(json.dumps(old,ensure_ascii=False,sort_keys=True),encoding='utf-8')
            c.bm25.close()
            print({'baseline_responses':len(old)})
            return
        check('old_response_exact_equality',old==json.loads(reference.read_text(encoding='utf-8')))
        status,evidence,h=await call(app,'/api/experiments')
        check('aggregate_payload_exact',status==200 and evidence==json.loads((ROOT/'deploy/stage53/evidence-data.json').read_text(encoding='utf-8')))
        check('read_only_evidence_no_cookie','set-cookie' not in h)
        check('security_headers',all(k in h for k in ['content-security-policy','strict-transport-security','x-content-type-options','permissions-policy','referrer-policy','cache-control']))
        check('scope_162_vs_9000',evidence['live']['catalog']==len(c.catalog)==162 and evidence['sft']['catalog']==9000 and evidence['diagnosis']['models_beating_prefix_prior']==0)
        for key,d in evidence['downloads'].items():
            status,text,h=await call(app,'/api/experiment-artifacts/'+key)
            check('download_'+key,status==200 and hashlib.sha256(text.encode()).hexdigest()==d['sha256'] and 'attachment' in h['content-disposition'] and 'set-cookie' not in h)
        for path in ['/api/experiment-artifacts/private','/reports/stage51/final-validation.json','/evidence-data.json','/catalog/documents.json','/session.key','/trialsite/delivery.py','/experiment-artifacts/closure.md']:
            check('private_404_'+path,(await call(app,path))[0]==404)
        check('evidence_readonly',(await call(app,'/api/experiments','POST',{}))[0]==405)
        for path in ['/evidence.html','/evidence.mjs','/evidence.css','/sid-lab.html','/','/open-source.txt']:
            check('static_'+path,(await call(app,path))[0]==200)
        _,pa,ha=await call(app,'/api/profile');a=extract(ha)
        _,pb,hb=await call(app,'/api/profile');b=extract(hb)
        check('isolated_visitors',a!=b and pa['items']==pb['items']==[])
        check('secure_cookie',all(x in ha['set-cookie'] for x in ['HttpOnly','Secure','SameSite=strict']))
        check('cold_start_empty',(await call(app,'/api/recommendations',cookie=a))[1]['papers']==[])
        doc='2202.06991'; key=c.catalog_key
        def feedback(value,rev):
            return {'doc_id':doc,'version_key':c.by_id[doc]['version_key'],'catalog_key':key,'value':value,'revision':rev}
        status,p,_=await call(app,'/api/profile/feedback','POST',feedback('like',0),a)
        check('favorite_saved',status==200 and p['like_count']==1 and p['revision']==1)
        check('other_visitor_untouched',(await call(app,'/api/profile',cookie=b))[1]['items']==[])
        status,r,_=await call(app,'/api/recommendations',cookie=a)
        check('favorite_updates_recommendations',status==200 and r['papers'] and doc not in [x['doc_id'] for x in r['papers']])
        check('computed_anchor_explanations',all(x['explanation']['anchors'] and all(z['doc_id']==doc for z in x['explanation']['anchors']) for x in r['papers']))
        check('recommendation_trace',bool(r['trace']))
        target=r['papers'][0]['doc_id']
        status,read,_=await call(app,'/api/paper/'+target,cookie=a)
        check('original_abstract',status==200 and read['paper']['abstract']==c.by_id[target]['abstract'] and read['paper']['version_key'].endswith('v1') and read['trace'][0]['source_verified'])
        check('version_and_source',bool(read['paper']['version_key']) and 'arxiv.org' in json.dumps(read['paper']))
        check('stale_revision_rejected',(await call(app,'/api/profile/feedback','POST',feedback('hide',0),a))[0]==409)
        _,backup,_=await call(app,'/api/profile/export',cookie=a)
        check('backup_no_identity',not any(x in json.dumps(backup) for x in ['owner','session.key','__Host-']))
        text=json.dumps(backup,ensure_ascii=False)
        status,preview,_=await call(app,'/api/profile/import/preview','POST',{'text':text,'revision':0,'policy':'keep_current'},b)
        check('preview_without_write',status==200 and (await call(app,'/api/profile',cookie=b))[1]['items']==[])
        body={'text':text,'revision':0,'policy':'keep_current','preview_token':preview['preview_token']}
        check('preview_token_bound',(await call(app,'/api/profile/import/apply','POST',body,a))[0]==409)
        check('backup_apply',(await call(app,'/api/profile/import/apply','POST',body,b))[0]==200)
        again=create_app(settings)
        check('persistent_preferences',(await call(again,'/api/profile',cookie=a))[1]['like_count']==1)
        check('imported_preferences',(await call(again,'/api/profile',cookie=b))[1]['like_count']==1)
        status,p,_=await call(app,'/api/profile/feedback','POST',feedback('hide',1),a)
        check('hide_and_update',status==200 and p['hidden_count']==1 and p['like_count']==0)
        status,p,_=await call(app,'/api/profile/feedback','POST',feedback('like',2),a)
        check('undo_hide',status==200 and p['like_count']==1)
        status,p,_=await call(app,'/api/profile/reset','POST',{'catalog_key':key,'revision':3},a)
        check('reset_own_only',status==200 and p['items']==[] and (await call(app,'/api/profile',cookie=b))[1]['like_count']==1)
        check('cross_origin_rejected',(await call(app,'/api/profile/reset','POST',{'catalog_key':key,'revision':4},a,origin='https://evil.example'))[0]==403)
        again.state.catalog.bm25.close();c.bm25.close()
    report={'passed':len(CHECKS),'checks':CHECKS,'unchanged_responses':len(old),'scope':'isolated ASGI; simulated HTTPS headers, not public TLS/load verification'}
    (ROOT/'reports/stage53/api-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({'passed':len(CHECKS),'unchanged_responses':len(old)})
if __name__=='__main__':asyncio.run(main())
