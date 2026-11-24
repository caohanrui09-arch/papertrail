"""Behavioral reading-list acceptance, isolated stores and canonical real metadata."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deploy/stage55'))
from trialsite.delivery import create_app
from trialsite.app import create_app as legacy_app
from trialsite.security import Settings
from scripts.validate_trial import call,extract

CHECKS=[]
def check(name,passed):
    if not passed:raise AssertionError(name)
    CHECKS.append(name)

async def main():
    with tempfile.TemporaryDirectory(prefix='reading-',dir=ROOT/'.cache/stage55') as folder:
        settings=replace(Settings('https://trial.example',Path(folder)),visitor_per_minute=2000,writes_per_minute=1000,global_per_minute=5000,expensive_per_minute=200)
        # Upgrade a legacy database instead of creating only an empty new one.
        old=legacy_app(settings);c=old.state.catalog;key=c.catalog_key;docs=c.catalog[:5]
        def fb(doc,value,revision):return dict(doc_id=doc,version_key=c.by_id[doc]['version_key'],catalog_key=key,value=value,revision=revision)
        async def req(app,path,who=None,body=None,**kw):return await call(app,path,'POST' if body is not None else 'GET',body,who,**kw)
        _,_,ha=await req(old,'/api/profile');a=extract(ha)
        check('legacy_like',(await req(old,'/api/profile/feedback',a,fb(docs[0],'like',0)))[0]==200)
        before_profile=(await req(old,'/api/profile',a))[1]
        before_recs=(await req(old,'/api/recommendations',a))[1]
        secret=(Path(folder)/'session.key').read_bytes()
        app=create_app(settings)
        check('additive_upgrade_keeps_profile',(await req(app,'/api/profile',a))[1]==before_profile)
        check('upgrade_keeps_session_secret',(Path(folder)/'session.key').read_bytes()==secret)
        check('upgrade_empty_reading',(await req(app,'/api/profile/reading',a))[1]['items']==[])
        _,_,hb=await req(app,'/api/profile');b=extract(hb)
        check('reading_requires_visitor',(await req(app,'/api/profile/reading'))[0]==401)
        check('reading_forged_cookie',(await req(app,'/api/profile/reading','__Host-papertrail_trial=forged'))[0]==401)
        for value,revision in [('to_read',0),('reading',1),('read',2)]:
            code,result,_=await req(app,'/api/profile/reading/feedback',a,fb(docs[0],value,revision))
            check('transition_'+value,code==200 and result['revision']==revision+1 and result['counts'][value]==1 and result['items'][0]['reading_state']==value)
        check('same_state_idempotent',(await req(app,'/api/profile/reading/feedback',a,fb(docs[0],'read',3)))[1]['revision']==3)
        check('other_visitor_isolated',(await req(app,'/api/profile/reading',b))[1]['items']==[])
        check('profile_unchanged_by_reading',(await req(app,'/api/profile',a))[1]==before_profile)
        check('recommendations_byte_equal',(await req(app,'/api/recommendations',a))[1]==before_recs)
        await req(app,'/api/paper/'+docs[1],a)
        check('abstract_open_not_completion',len((await req(app,'/api/profile/reading',a))[1]['items'])==1)
        check('stale_state_rejected',(await req(app,'/api/profile/reading/feedback',a,fb(docs[0],'reading',2)))[0]==409)
        for name,change,expected in [('null',{'value':None},422),('bad_state',{'value':'done'},422),('boolean_revision',{'revision':True},422),('string_revision',{'revision':'3'},422),('negative_revision',{'revision':-1},422),('owner_injection',{'owner':'other'},422),('bad_doc',{'doc_id':'9999.99999'},422),('bad_version',{'version_key':'arxiv:'+docs[0]+'v2'},409),('bad_catalog',{'catalog_key':'wrong'},409)]:
            body=fb(docs[0],'reading',3)|change
            check('reject_'+name,(await req(app,'/api/profile/reading/feedback',a,body))[0]==expected)
        check('cross_origin_write_rejected',(await req(app,'/api/profile/reading/feedback',a,fb(docs[0],'reading',3),origin='https://evil.example'))[0]==403)
        results=await asyncio.gather(*[req(app,'/api/profile/reading/feedback',a,fb(docs[0],v,3)) for v in ['reading','to_read']])
        check('concurrent_CAS_one_winner',sorted(r[0] for r in results)==[200,409])
        check('remove_from_reading',(await req(app,'/api/profile/reading/feedback',a,fb(docs[0],'none',4)))[1]['items']==[])
        check('remove_keeps_favorite',(await req(app,'/api/profile',a))[1]['like_count']==1)
        await req(app,'/api/profile/reading/feedback',a,fb(docs[0],'read',5))
        await req(app,'/api/profile/reading/feedback',a,fb(docs[1],'to_read',6))
        again=create_app(settings)
        check('restart_reading_persists',(await req(again,'/api/profile/reading',a))[1]['counts']=={'to_read':1,'reading':0,'read':1})
        code,backup,headers=await req(app,'/api/profile/library/export',a)
        check('export_v2',code==200 and backup['schema_version']==2 and len(backup['reading'])==2 and len(backup['preferences'])==1 and 'attachment' in headers['content-disposition'])
        check('export_canonical_identity',all(r['title']==c.paper(r['doc_id'])['title'] and r['version_key'].endswith('v1') for r in backup['reading']))
        check('export_no_credentials_or_queries',not any(x in json.dumps(backup) for x in ['owner','session.key','query','revision','updated_at','__Host-']))
        async def snapshot(who):return ((await req(app,'/api/profile',who))[1],(await req(app,'/api/profile/reading',who))[1])
        async def preview(value,who=b,policy='keep_current'):
            p,r=await snapshot(who);body={'text':value if isinstance(value,str) else json.dumps(value,ensure_ascii=False),'revision':p['revision'],'reading_revision':r['revision'],'policy':policy}
            result=await req(app,'/api/profile/library/import/preview',who,body)
            return result,body
        before_b=await snapshot(b)
        (code,plan,_),body=await preview(backup)
        check('v2_preview_both_sections',code==200 and plan['changes_total']==3 and plan['counts']['added']==1 and plan['reading']['counts']['added']==2)
        check('preview_is_read_only',await snapshot(b)==before_b)
        apply_body=body|{'preview_token':plan['preview_token']}
        # A visitor at equal revisions still cannot replay another visitor's token.
        _,_,hd=await req(app,'/api/profile');d=extract(hd)
        check('token_visitor_bound',(await req(app,'/api/profile/library/import/apply',d,apply_body))[0]==409)
        code,applied,_=await req(app,'/api/profile/library/import/apply',b,apply_body)
        check('v2_apply_atomic_both',code==200 and applied['applied']==1 and applied['reading_applied']==2)
        check('imported_reading_and_favorite',(await snapshot(b))[0]['like_count']==1 and (await snapshot(b))[1]['counts']=={'to_read':1,'reading':0,'read':1})
        check('import_token_stale_after_apply',(await req(app,'/api/profile/library/import/apply',b,apply_body))[0]==409)
        await req(app,'/api/profile/feedback',b,fb(docs[0],'hide',1))
        await req(app,'/api/profile/reading/feedback',b,fb(docs[0],'reading',1))
        await req(app,'/api/profile/reading/feedback',b,fb(docs[2],'to_read',2))
        (code,keep,_),body=await preview(backup)
        check('separate_conflict_keep',code==200 and keep['counts']['skipped']==1 and keep['reading']['counts']['skipped']==1 and keep['changes_total']==0 and keep['reading']['retained_outside_backup']==1)
        (code,use,_),body=await preview(backup,policy='use_backup')
        check('separate_conflict_replace',code==200 and use['changes_total']==2 and use['counts']['changed']==1 and use['reading']['counts']['changed']==1)
        code,applied,_=await req(app,'/api/profile/library/import/apply',b,body|{'preview_token':use['preview_token']})
        check('replace_preserves_outside',code==200 and len((await snapshot(b))[1]['items'])==3)
        _,v1,_=await req(app,'/api/profile/export',a)
        before_read=(await snapshot(b))[1]
        (code,plan,_),body=await preview(v1)
        check('v1_preview_preserves_reading',code==200 and plan['file_version']==1 and plan['reading']['rows']==[] and plan['reading']['total_after']==3)
        await req(app,'/api/profile/library/import/apply',b,body|{'preview_token':plan['preview_token']})
        check('v1_apply_preserves_reading',(await snapshot(b))[1]==before_read)
        migration=json.loads((ROOT/'deploy/stage55/catalog/migration.json').read_text(encoding='utf-8'))
        previous_doc=next(x for x in c.catalog if x in migration['original_ids'])
        old_backup=v1|{'catalog_key':migration['accepted_previous_catalog'],'items':[{k:v for k,v in c.paper(previous_doc).items() if k!='version'}|{'preference':'like'}]}
        (code,legacy_plan,_),legacy_body=await preview(old_backup,b)
        check('legacy42_backup_accepted',code==200 and legacy_plan['migrated_from']==migration['accepted_previous_catalog'])
        check('legacy42_apply_preserves_reading',(await req(app,'/api/profile/library/import/apply',b,legacy_body|{'preview_token':legacy_plan['preview_token']}))[0]==200 and (await snapshot(b))[1]==before_read)
        new_doc=next(x for x in c.catalog if x not in migration['original_ids'])
        old_backup['items']=[{k:v for k,v in c.paper(new_doc).items() if k!='version'}|{'preference':'like'}]
        check('legacy42_cannot_forge_membership',(await preview(old_backup,b))[0][0]==422)
        (code,plan,_),body=await preview(backup)
        check('preview_token_policy_bound',(await req(app,'/api/profile/library/import/apply',b,body|{'policy':'use_backup','preview_token':plan['preview_token']}))[0]==409)
        check('preview_token_exact_file_bound',(await req(app,'/api/profile/library/import/apply',b,body|{'text':body['text']+' ','preview_token':plan['preview_token']}))[0]==409)
        await req(app,'/api/profile/reading/feedback',b,fb(docs[2],'read',before_read['revision']))
        check('reading_change_invalidates_preview',(await req(app,'/api/profile/library/import/apply',b,body|{'preview_token':plan['preview_token']}))[0]==409)
        (code,plan,_),body=await preview(backup)
        p,r=await snapshot(b);await req(app,'/api/profile/feedback',b,fb(docs[3],'like',p['revision']))
        check('preference_change_invalidates_preview',(await req(app,'/api/profile/library/import/apply',b,body|{'preview_token':plan['preview_token']}))[0]==409)
        invalid=[]
        def mutate(name,edit,expected):
            value=json.loads(json.dumps(backup));edit(value);invalid.append((name,value,expected))
        mutate('duplicate_reading',lambda v:v['reading'].append(v['reading'][0]),422)
        mutate('unknown_state',lambda v:v['reading'][0].update(state='finished'),422)
        mutate('incorrect_version',lambda v:v['reading'][0].update(version_key='v2'),409)
        mutate('incorrect_title',lambda v:v['reading'][0].update(title='wrong'),409)
        mutate('external_source',lambda v:v['reading'][0].update(source_url='https://evil.example'),409)
        mutate('unexpected_field',lambda v:v['reading'][0].update(owner='x'),422)
        mutate('unsupported_schema',lambda v:v.update(schema_version=True),422)
        mutate('wrong_catalog',lambda v:v.update(catalog_key='wrong'),409)
        for name,value,expected in invalid:
            before=await snapshot(d);(code,_,_),body=await preview(value,d)
            check('invalid_preview_'+name,code==expected)
            check('invalid_apply_atomic_'+name,(await req(app,'/api/profile/library/import/apply',d,body|{'preview_token':'a'*64}))[0]==expected and await snapshot(d)==before)
        duplicate=json.dumps(backup).replace('"schema_version": 2','"schema_version": 2, "schema_version": 2')
        check('duplicate_json_fields',(await preview(duplicate,d))[0][0]==422)
        check('oversized_utf8_file',(await preview('文'*90000,d))[0][0]==413)
        check('oversized_text_field',(await preview(' '*262145,d))[0][0]==422)
        p,r=await snapshot(a)
        await req(app,'/api/profile/reset',a,{'catalog_key':key,'revision':p['revision']})
        check('reset_preference_preserves_reading',(await snapshot(a))[1]==r)
        (ROOT/'.cache/stage55/ui-import-v2.json').write_text(json.dumps(backup,ensure_ascii=False,indent=2),encoding='utf-8')
        (ROOT/'.cache/stage55/ui-import-v1.json').write_text(json.dumps(v1,ensure_ascii=False,indent=2),encoding='utf-8')
        # Verify unchanged write throttling on a fresh app with a one-write budget.
        limited=create_app(replace(settings,data_dir=Path(folder)/'limited',writes_per_minute=1))
        _,_,hl=await req(limited,'/api/profile');l=extract(hl)
        check('budget_first_write',(await req(limited,'/api/profile/reading/feedback',l,fb(docs[0],'to_read',0)))[0]==200)
        check('budget_second_write_429',(await req(limited,'/api/profile/reading/feedback',l,fb(docs[0],'read',1)))[0]==429)
        for item in [old,app,again,limited]:item.state.catalog.bm25.close()
    report={'status':'passed','passed':len(CHECKS),'checks':CHECKS,'scope':'isolated ASGI; visitor separation, legacy upgrade, CAS races, atomic v2/v1 imports, inherited resource limits; no real visitor writes'}
    (ROOT/'reports/stage55/reading-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({'passed':len(CHECKS)})

if __name__=='__main__':asyncio.run(main())
