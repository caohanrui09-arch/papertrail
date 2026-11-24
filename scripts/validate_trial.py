"""ASGI acceptance using disposable stores; do not write real visitor preferences."""
import asyncio
from dataclasses import replace
import hashlib
from http.cookies import SimpleCookie
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deploy/stage39'))
from trialsite.app import create_app
from trialsite.security import Settings, TrialBoundary, TrialStore

CHECKS = []


def check(name, passed):
    if not passed: raise AssertionError(name)
    CHECKS.append(name)


async def call(app, path, method='GET', value=None, cookie=None, origin='https://trial.example', headers=None, chunks=None):
    target = urlsplit(path)
    request_headers = {'host':'trial.example'}
    if method != 'GET': request_headers['origin'] = origin
    if cookie: request_headers['cookie']=cookie
    if value is not None: request_headers['content-type']='application/json'
    if headers: request_headers.update(headers)
    request_headers = {k:v for k,v in request_headers.items() if v is not None}
    body = json.dumps(value,ensure_ascii=False).encode() if value is not None else b''
    parts = list(chunks) if chunks is not None else [body]
    sent=[]
    async def receive():
        if parts:
            part = parts.pop(0)
            return {'type':'http.request','body':part,'more_body':bool(parts)}
        return {'type':'http.disconnect'}
    async def send(message): sent.append(message)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':method,
           'scheme':'https','path':target.path,'raw_path':target.path.encode(),'query_string':target.query.encode(),
           'headers':[(k.encode(),v.encode()) for k,v in request_headers.items()],
           'client':('127.0.0.20',1234),'server':('trial.example',443)}
    await app(scope,receive,send)
    start=next(m for m in sent if m['type']=='http.response.start')
    raw=b''.join(m.get('body',b'') for m in sent if m['type']=='http.response.body')
    hdr={k.decode().lower():v.decode() for k,v in start['headers']}
    try: result=json.loads(raw)
    except (ValueError,UnicodeDecodeError): result=raw.decode(errors='replace')
    return start['status'],result,hdr


def extract(headers):
    jar=SimpleCookie();jar.load(headers['set-cookie'])
    return '; '.join(key+'='+value.value for key,value in jar.items())


async def main():
    with tempfile.TemporaryDirectory(prefix='trial-',dir=ROOT/'.cache/stage39') as folder:
        settings=Settings('https://trial.example',Path(folder)/'main')
        app=create_app(settings)
        catalog=app.state.catalog
        key=catalog.catalog_key
        code,first,headers=await call(app,'/api/profile')
        a=extract(headers)
        _,second,hb=await call(app,'/api/profile');b=extract(hb)
        check('independent_credentials',a!=b and first['items']==second['items']==[])
        check('secure_cookie',all(x in headers['set-cookie'] for x in ['__Host-papertrail_trial','HttpOnly','Secure','SameSite=strict','Path=/']) and 'Domain=' not in headers['set-cookie'])
        check('security_headers',all(x in headers for x in ['content-security-policy','strict-transport-security','x-content-type-options','permissions-policy','referrer-policy','cache-control']))
        check('catalog_162',len(catalog.catalog)==162)
        check('catalog_all_v1',all(catalog.valid(d) and catalog.by_id[d]['version']==1 for d in catalog.catalog))
        review=json.loads((ROOT/'reports/stage39/catalog-review.json').read_text(encoding='utf-8'))
        check('review_gate_exclusions',not set(review['exclude_ids'])&set(catalog.catalog))
        check('preview_exact_prefixes',all(catalog.by_id[d]['abstract'].startswith(p['abstract_excerpt']) for d,p in catalog.previews()['papers'].items()))
        for topic,config in catalog.topics.items():
            for method in ('bm25','tfidf'):
                original=None
                for context in ('none','same','cross'):
                    code,result,_=await call(app,f'/api/search?topic={topic}&q='+config['core'].replace(' ','%20')+f'&method={method}&context={context}',cookie=a)
                    check(f'search_{topic}_{method}_{context}',code==200 and len(result['papers'])<=10 and all(r['review'] is None for r in result['papers']) and result['trace'][0]['eligible']==156)
                    current=set(r['doc_id'] for r in result['papers'])
                    if original is None: original=current
                    else: check(f'same_candidates_{topic}_{method}_{context}',current==original)
        doc='2202.06991'
        def feedback(d,value='like',revision=0):
            return {'doc_id':d,'version_key':catalog.by_id[d]['version_key'],'catalog_key':key,'value':value,'revision':revision}
        code,result,_=await call(app,'/api/profile/feedback','POST',feedback(doc),a)
        check('save_to_a',code==200 and result['like_count']==1)
        check('b_not_a',(await call(app,'/api/profile',cookie=b))[1]['items']==[])
        check('recommend_unauthenticated',(await call(app,'/api/recommendations'))[0]==401)
        check('forged_cookie',(await call(app,'/api/recommendations',cookie='__Host-papertrail_trial='+'a'*64+'.'+'b'*64))[0]==401)
        code,recs,_=await call(app,'/api/recommendations',cookie=a)
        check('real_anchors',code==200 and recs['papers'] and all(all(anchor['doc_id']==doc for anchor in r['explanation']['anchors']) for r in recs['papers']))
        check('empty_b_recommend',(await call(app,'/api/recommendations',cookie=b))[1]['papers']==[])
        _,backup,_=await call(app,'/api/profile/export',cookie=a)
        check('export_no_credentials',doc==backup['items'][0]['doc_id'] and not any(k in json.dumps(backup) for k in ['__Host-','session.key','owner']))
        text=json.dumps(backup,ensure_ascii=False)
        code,preview,_=await call(app,'/api/profile/import/preview','POST',{'text':text,'revision':0},b)
        check('import_preview_readonly',code==200 and preview['counts']['added']==1 and (await call(app,'/api/profile',cookie=b))[1]['items']==[])
        body={'text':text,'revision':0,'preview_token':preview['preview_token']}
        check('token_bound_to_visitor',(await call(app,'/api/profile/import/apply','POST',body,a))[0]==409)
        # New app instance with the same private volume proves persistent key / preview binding.
        restarted=create_app(settings)
        check('persistent_cookie',(await call(restarted,'/api/profile',cookie=a))[1]['like_count']==1)
        check('persistent_preview_token',(await call(restarted,'/api/profile/import/apply','POST',body,b))[0]==200)
        app=restarted
        races=await asyncio.gather(*[call(app,'/api/profile/feedback','POST',feedback(d,revision=1),a) for d in ['2403.12499','2311.08593']])
        check('concurrent_cas',sorted(r[0] for r in races)==[200,409])
        check('reject_cross_origin',(await call(app,'/api/profile/reset','POST',{'catalog_key':key,'revision':2},a,origin='https://evil.example'))[0]==403)
        check('require_origin',(await call(app,'/api/profile/reset','POST',{'catalog_key':key,'revision':2},a,origin=None))[0]==403)
        check('cross_site_get',(await call(app,'/api/profile',cookie=a,headers={'sec-fetch-site':'cross-site'}))[0]==403)
        check('trusted_host',(await call(app,'/api/health',headers={'host':'evil.example'}))[0]==400)
        check('reject_owner_injection',(await call(app,'/api/profile/feedback','POST',feedback(doc,revision=2)|{'owner':'other'},a))[0]==422)
        check('reject_wrong_version',(await call(app,'/api/profile/feedback','POST',feedback(doc,revision=2)|{'version_key':'arxiv:'+doc+'v2'},a))[0]==409)
        check('chunked_body_limit',(await call(app,'/api/profile/import/preview','POST',cookie=a,chunks=[b'x'*(256*1024),b'x'*(256*1024+1)]))[0]==413)
        check('invalid_schema',(await call(app,'/api/profile/import/preview','POST',{'text':'{}','revision':2},a))[0]==422)
        check('invalid_search',(await call(app,'/api/search?topic=cold&q=%20&method=bad',cookie=a))[0]==422)
        old=json.loads((ROOT/'deploy/stage39/catalog/migration.json').read_text())
        backup['catalog_key']=old['accepted_previous_catalog']
        code,result,_=await call(app,'/api/profile/import/preview','POST',{'text':json.dumps(backup),'revision':2},a)
        check('old_backup_explicit_migration',code==200 and result['migrated_from']==old['accepted_previous_catalog'])
        new_doc=next(d for d in catalog.catalog if d not in old['original_ids'])
        backup['items']=[{k:v for k,v in catalog.paper(new_doc).items() if k!='version'}|{'preference':'like'}]
        check('old_catalog_cannot_claim_new_paper',(await call(app,'/api/profile/import/preview','POST',{'text':json.dumps(backup),'revision':2},a))[0]==422)
        check('reset_own_only',(await call(app,'/api/profile/reset','POST',{'catalog_key':key,'revision':2},a))[0]==200 and (await call(app,'/api/profile',cookie=b))[1]['like_count']==1)
        with app.state.preferences.connect() as db:
            check('sqlite_bound',db.execute('PRAGMA max_page_count').fetchone()[0]==8192)
        for path in ['/session.key','/visitor-data','/catalog/documents.json','/trialsite/app.py']:
            check('not_public_'+path,(await call(app,path))[0]==404)
        # Deterministic small limits in disposable instances, without waiting out real production quotas.
        limited=create_app(replace(settings,data_dir=Path(folder)/'limited',expensive_per_minute=2,writes_per_minute=1))
        _,p,h=await call(limited,'/api/profile');c=extract(h)
        codes=[(await call(limited,'/api/search?topic=cold&q=cold',cookie=c,headers={'x-forwarded-for':str(i)}))[0] for i in range(3)]
        check('limits_component_expensive',codes==[200,200,429])
        body={'doc_id':doc,'version_key':catalog.by_id[doc]['version_key'],'catalog_key':key,'value':'like','revision':0}
        code= (await call(limited,'/api/profile/feedback','POST',body,c))[0]
        retry=await call(limited,'/api/profile/feedback','POST',body,c)
        check('write_limit',code==200 and retry[0]==429 and retry[2]['retry-after']=='60')
        quota=create_app(replace(settings,data_dir=Path(folder)/'quota',max_visitors=2))
        _,_,h=await call(quota,'/api/profile');existing=extract(h)
        await call(quota,'/api/profile')
        check('visitor_quota',(await call(quota,'/api/profile'))[0]==503 and (await call(quota,'/api/profile',cookie=existing))[0]==200)
        blocked=[]
        for candidate in [replace(settings,origin='http://trial.example'),replace(settings,origin='https://trial.example/path'),replace(settings,origin='https://u:p@trial.example')]:
            try: candidate.validate()
            except ValueError: blocked.append(True)
        check('fail_closed_configuration',len(blocked)==3)
        # Hold one real ASGI operation; the next is rejected before any app computation.
        started,release=asyncio.Event(),asyncio.Event()
        async def held(scope,receive,send):
            started.set();await release.wait()
            from starlette.responses import Response
            await Response('ok')(scope,receive,send)
        boundary=TrialBoundary(held,replace(settings,max_active=1),app.state.preferences,b'1'*32)
        task=asyncio.create_task(call(boundary,'/work'))
        await started.wait()
        check('inflight_limit',(await call(boundary,'/work'))[0]==503)
        release.set();await task
        check('inflight_slot_released',boundary.active==0)
        for current in [app,limited,quota]: current.state.catalog.bm25.close()
    report={'passed':len(CHECKS),'checks':CHECKS,'scope':'disposable ASGI stores; simulated HTTPS scope checks cookie/headers, not a live certificate or public ingress test'}
    path=ROOT/'reports/stage39/security-validation.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({'passed':len(CHECKS),'report':str(path)})


if __name__=='__main__': asyncio.run(main())
