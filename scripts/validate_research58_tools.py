"""Independent behavior checks for real match evidence and private plain-text notes."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deploy/stage58'))
from trialsite.delivery import create_app
from trialsite.security import Settings
from scripts.validate_trial import call,extract
CHECKS=[]
def check(name,passed):
    if not passed:raise AssertionError(name)
    CHECKS.append(name)
async def main():
    with tempfile.TemporaryDirectory(prefix='tools-',dir=ROOT/'.cache/stage58') as folder:
        settings=replace(Settings('https://trial.example',Path(folder)),visitor_per_minute=3000,writes_per_minute=2000,global_per_minute=10000,expensive_per_minute=1000)
        app=create_app(settings);c=app.state.catalog;key=c.catalog_key;docs=c.catalog[:5]
        async def req(path,who=None,body=None,**kw):return await call(app,path,'POST' if body is not None else 'GET',body,who,**kw)
        for method in ['bm25','tfidf']:
            for topic,config in c.topics.items():
                for context in ['none','same','cross']:
                    path='/api/search?'+urlencode(dict(topic=topic,q=config['core'],method=method,context=context))
                    old=(await req(path))[1];code,new,h=await req(path+'&explain=true')
                    stripped={k:v for k,v in new.items() if k!='feedback'};stripped['papers']=[{k:v for k,v in p.items() if k!='search_match'} for p in new['papers']]
                    check('same_ranking_'+method+'_'+topic+'_'+context,code==200 and stripped==old)
                    check('evidence_no_cookie_'+method+'_'+topic+'_'+context,'set-cookie' not in h)
                    check('actual_terms_'+method+'_'+topic+'_'+context,all(p['search_match']['terms'] and p['search_match']['query']==config['core'] for p in new['papers']))
                    if method=='bm25':
                        with c.core.bm25.lock:
                            db,_=c.core.bm25._snapshot(c.core.at)
                            for p in new['papers']:
                                for term in p['search_match']['terms']:
                                    fields=[]
                                    for field,column in [('title','title'),('abstract','body')]:
                                        if db.execute('SELECT 1 FROM docs WHERE doc_id=? AND docs MATCH ?',(p['doc_id'],column+' : "'+term['term']+'"')).fetchone():fields.append(field)
                                    assert fields==term['fields']
                    else:
                        for p in new['papers']:
                            for t in p['search_match']['terms']:assert c.documents[c.position[p['doc_id']],c.vectorizer.vocabulary_[t['term']]]>0
        check('term_fields_verified',True)
        for method in ['bm25','tfidf']:
            for query in ['qzvxnotincatalog2026','!!!','the and of','我想研究完全陌生的主题']:
                code,result,_=await req('/api/search?'+urlencode(dict(topic='generative',q=query,method=method,context='none',explain='true')))
                check('honest_empty_'+method+'_'+query,code==200 and not result['papers'] and '不代表论文不存在' in result['feedback']['notice'] and result['feedback']['eligible']==156 and result['feedback']['catalog']==162)
                check('suggestions_verified_'+method+'_'+query,all(c.search(s['topic'],s['query'],method,'none')['papers'] for s in result['feedback']['suggestions']))
        code,stem,_=await req('/api/search?topic=generative&q=retrieving&method=bm25&context=none&explain=true')
        check('porter_match_not_substring_claim',code==200 and stem['papers'] and '词干' in stem['papers'][0]['search_match']['kind'])
        check('invalid_explain_422',(await req('/api/search?topic=cold&q=content&explain=wrong'))[0]==422)
        _,_,ha=await req('/api/profile');a=extract(ha);_,_,hb=await req('/api/profile');b=extract(hb)
        async def snap(who):return tuple([(await req(path,who))[1] for path in ['/api/profile','/api/profile/reading','/api/profile/notes']])
        before=await snap(a)
        def note(doc,rev,p='我的理解',q='还有疑问'):return {'doc_id':doc,'version_key':c.by_id[doc]['version_key'],'catalog_key':key,'revision':rev,'problem':p,'questions':q}
        code,saved,_=await req('/api/profile/notes/save',a,note(docs[0],0,'<script>alert(1)</script>\n真实的个人理解','为什么成立？'))
        check('save_plain_text',code==200 and saved['revision']==1 and saved['items'][0]['problem'].startswith('<script>'))
        after=await snap(a);check('notes_independent',after[:2]==before[:2] and after[2]['items'])
        check('notes_visitor_isolation',(await snap(b))[2]['items']==[])
        check('notes_require_visitor',(await req('/api/profile/notes'))[0]==401)
        check('notes_cross_origin',(await req('/api/profile/notes/save',a,note(docs[1],1),origin='https://evil.example'))[0]==403)
        for name,changed,expected in [('owner',{'owner':'other'},422),('bool_revision',{'revision':True},422),('string_revision',{'revision':'1'},422),('negative',{'revision':-1},422),('bad_version',{'version_key':'v2'},409),('bad_catalog',{'catalog_key':'wrong'},409),('long_field',{'problem':'x'*1001},422),('null',{'problem':None},422),('bad_doc',{'doc_id':'9999.99999'},422)]:
            check('notes_reject_'+name,(await req('/api/profile/notes/save',a,note(docs[0],1)|changed))[0]==expected)
        check('note_stale_CAS',(await req('/api/profile/notes/save',a,note(docs[0],0)))[0]==409)
        races=await asyncio.gather(*[req('/api/profile/notes/save',a,note(docs[0],1,'并发'+str(i))) for i in range(2)])
        check('note_concurrent_one_winner',sorted(x[0] for x in races)==[200,409])
        current=(await snap(a))[2];entry=current['items'][0]
        check('note_idempotent',(await req('/api/profile/notes/save',a,note(docs[0],2,entry['problem'],entry['questions'])))[1]['revision']==2)
        check('blank_removes',(await req('/api/profile/notes/save',a,note(docs[0],2,'',' ')))[1]['items']==[])
        await req('/api/profile/notes/save',a,note(docs[0],3,'说明该论文解决的问题','待核验的疑问'))
        same=create_app(settings)
        check('note_restart_persistence',(await call(same,'/api/profile/notes',cookie=a))[1]['items']==(await snap(a))[2]['items']);same.state.catalog.bm25.close()
        def feedback(doc,value,revision):return {'doc_id':doc,'version_key':c.by_id[doc]['version_key'],'catalog_key':key,'revision':revision,'value':value}
        await req('/api/profile/feedback',a,feedback(docs[0],'like',0));await req('/api/profile/reading/feedback',a,feedback(docs[0],'read',0))
        code,backup,h=await req('/api/profile/notebook/export',a)
        check('v3_export_all_sections',code==200 and backup['schema_version']==3 and all(backup[k] for k in ['preferences','reading','notes']) and 'v3.json' in h['content-disposition'])
        check('v3_export_private_text_only',not any(k in json.dumps(backup) for k in ['owner','revision','updated_at','__Host-','query']) and backup['notes'][0]['problem']=='说明该论文解决的问题')
        async def preview(value,who=b,policy='keep_current'):
            p,r,n=await snap(who);body={'text':value if isinstance(value,str) else json.dumps(value,ensure_ascii=False),'revision':p['revision'],'reading_revision':r['revision'],'notes_revision':n['revision'],'policy':policy}
            return await req('/api/profile/notebook/import/preview',who,body),body
        before_b=await snap(b);(code,plan,_),body=await preview(backup)
        check('v3_readonly_preview',code==200 and plan['changes_total']==3 and await snap(b)==before_b)
        _,_,hx=await req('/api/profile');x=extract(hx)
        check('v3_cross_visitor_token',(await req('/api/profile/notebook/import/apply',x,body|{'preview_token':plan['preview_token']}))[0]==409)
        code,applied,_=await req('/api/profile/notebook/import/apply',b,body|{'preview_token':plan['preview_token']})
        check('v3_atomic_apply',code==200 and applied['notes_applied']==applied['reading_applied']==applied['applied']==1)
        bp,br,bn=await snap(b)
        await req('/api/profile/notes/save',b,note(docs[0],bn['revision'],'当前自己的不同理解','当前疑问'))
        (code,keep,_),body=await preview(backup)
        check('note_keep_conflict',code==200 and keep['notes']['counts']['skipped']==1 and keep['changes_total']==0)
        (code,use,_),body=await preview(backup,policy='use_backup')
        check('note_overwrite_preview',code==200 and use['notes']['counts']['changed']==1)
        check('note_overwrite_apply',(await req('/api/profile/notebook/import/apply',b,body|{'preview_token':use['preview_token']}))[0]==200 and (await snap(b))[2]['items'][0]['problem']==backup['notes'][0]['problem'])
        for route,version in [('/api/profile/export',1),('/api/profile/library/export',2)]:
            old_backup=(await req(route,a))[1];before_n=(await snap(b))[2];(code,plan,_),body=await preview(old_backup)
            check('legacy_preview_'+str(version),code==200 and plan['file_version']==version and plan['notes']['rows']==[])
            check('legacy_keeps_notes_'+str(version),(await req('/api/profile/notebook/import/apply',b,body|{'preview_token':plan['preview_token']}))[0]==200 and (await snap(b))[2]==before_n)
        (code,plan,_),body=await preview(backup);n=(await snap(b))[2]
        await req('/api/profile/notes/save',b,note(docs[1],n['revision']))
        check('notes_change_invalidates_v3',(await req('/api/profile/notebook/import/apply',b,body|{'preview_token':plan['preview_token']}))[0]==409)
        (code,plan,_),body=await preview(backup);r=(await snap(b))[1]
        await req('/api/profile/reading/feedback',b,feedback(docs[1],'to_read',r['revision']))
        check('reading_change_invalidates_v3',(await req('/api/profile/notebook/import/apply',b,body|{'preview_token':plan['preview_token']}))[0]==409)
        (code,plan,_),body=await preview(backup);p=(await snap(b))[0]
        await req('/api/profile/feedback',b,feedback(docs[1],'like',p['revision']))
        check('pref_change_invalidates_v3',(await req('/api/profile/notebook/import/apply',b,body|{'preview_token':plan['preview_token']}))[0]==409)
        for name,change,expected in [('bad_note_version',{'version_key':'v2'},409),('bad_note_title',{'title':'fake'},409),('bad_source',{'source_url':'https://evil.example'},409),('bad_note_extra',{'owner':'x'},422),('bad_note_empty',{'problem':'','questions':''},422),('bad_note_length',{'problem':'x'*1001},422)]:
            value=json.loads(json.dumps(backup));value['notes'][0].update(change);before_x=await snap(x);(code,_,_),body=await preview(value,x)
            check('reject_backup_'+name,code==expected)
            check('reject_atomic_'+name,(await req('/api/profile/notebook/import/apply',x,body|{'preview_token':'a'*64}))[0]==expected and await snap(x)==before_x)
        duplicate=json.loads(json.dumps(backup));duplicate['notes'].append(duplicate['notes'][0]);check('duplicate_note_row',(await preview(duplicate))[0][0]==422)
        (code,plan,_),body=await preview(backup)
        check('v3_policy_token_bound',(await req('/api/profile/notebook/import/apply',b,body|{'policy':'use_backup','preview_token':plan['preview_token']}))[0]==409)
        check('v3_file_token_bound',(await req('/api/profile/notebook/import/apply',b,body|{'text':body['text']+' ','preview_token':plan['preview_token']}))[0]==409)
        before_n=(await snap(a))[2];p=(await snap(a))[0]
        await req('/api/profile/reset',a,{'catalog_key':key,'revision':p['revision']})
        check('reset_keeps_notes',(await snap(a))[2]==before_n)
        # Fill a disposable notebook with escaped multibyte/newline content until its byte budget rejects.
        _,_,hc=await req('/api/profile');capacity=extract(hc);rev=0;rejected=False
        for doc in c.catalog:
            code,value,_=await req('/api/profile/notes/save',capacity,note(doc,rev,('界\n')*500,('问\t')*500))
            if code==422:rejected=True;break
            assert code==200;rev=value['revision']
        check('bounded_total_notebook',rejected and (await snap(capacity))[2]['revision']==rev)
        code,full,_=await req('/api/profile/notebook/export',capacity)
        check('all_accepted_notes_exportable',code==200 and len((json.dumps(full,ensure_ascii=False,indent=2)+'\n').encode())<=256*1024)
        (ROOT/'.cache/stage58/ui-import-v3.json').write_text(json.dumps(backup,ensure_ascii=False,indent=2),encoding='utf-8')
        (ROOT/'.cache/stage58/ui-import-v2.json').write_text(json.dumps((await req('/api/profile/library/export',a))[1],ensure_ascii=False,indent=2),encoding='utf-8')
        c.bm25.close()
    (ROOT/'reports/stage58/tools-validation.json').write_text(json.dumps({'status':'passed','passed':len(CHECKS),'checks':CHECKS,'scope':'isolated ASGI; source-backed matching and ranking parity, note isolation/CAS, v3 atomic backup, compatibility and bounded export'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print({'passed':len(CHECKS)})
if __name__=='__main__':asyncio.run(main())
