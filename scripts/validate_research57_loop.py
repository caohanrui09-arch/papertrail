"""Behavioral acceptance of the research loop; isolated visitors, no external calls."""
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deploy/stage57'))
from trialsite.delivery import create_app
from trialsite.querybridge import plan_query
from trialsite.researchtools import md_text
from trialsite.security import Settings
from scripts.validate_trial import call,extract

CHECKS=[]
def check(name,value):
    if not value:raise AssertionError(name)
    CHECKS.append(name)

async def main():
    with tempfile.TemporaryDirectory(prefix='loop-',dir=ROOT/'.cache/stage57') as folder:
        settings=replace(Settings('https://trial.example',Path(folder)),visitor_per_minute=9000,writes_per_minute=8000,global_per_minute=20000,expensive_per_minute=7000)
        app=create_app(settings);c=app.state.catalog;key=c.catalog_key;docs=c.catalog[:4]
        async def req(path,who=None,body=None,**kw):return await call(app,path,'POST' if body is not None else 'GET',body,who,**kw)
        async def snap(who):return [(await req(p,who))[1] for p in ['/api/profile','/api/profile/reading','/api/profile/notes','/api/profile/demands']]
        _,_,ha=await req('/api/profile');a=extract(ha)
        _,_,hb=await req('/api/profile');b=extract(hb)
        base=await snap(a)
        p=plan_query('多模态快慢思考')
        check('real_need_domain_mapping',p['proposed_query']=='multimodal fast slow thinking' and not p['review_required'])
        for phrase in ['生成式检索','推荐冷启动','曝光偏差','视觉语言模型','双系统','无交互论文']:
            value=plan_query(phrase);check('mapping_'+phrase,bool(value['mappings']) and value['proposed_query'])
        check('retains_english_identifiers','GRPO' in plan_query('多模态 GRPO')['retained_english'])
        check('unknown_warning',plan_query('多模态电路魔法')['review_required'])
        check('negation_requires_review',plan_query('不要检索推荐')['review_required'])
        for m in p['mappings']:check('mapping_actual_span',p['original_need'][m['start']:m['end']]==m['phrase'])
        await req('/api/query-plan?'+urlencode({'need':'多模态快慢思考'}))
        check('planning_has_no_private_writes',await snap(a)==base)
        query='multimodal fast slow thinking reasoning'
        search='/api/search?'+urlencode({'topic':'generative','q':query,'method':'bm25','context':'none','explain':'true','catalog_scope':'all','need':'多模态快慢思考'})
        code,result,_=await req(search)
        check('executed_terms_preserved',code==200 and result['query_plan']['executed_query']==query and result['query_plan']['edited'])
        check('actual_bridge_trace',result['trace'][0]['tool']=='中文术语辅助' and result['trace'][0]['executed_query']==query)
        check('five_curated_papers_in_top_five',set(p['doc_id'] for p in result['papers'][:5])==c.supplement_ids)
        check('mixed_scope_explicit',result['catalog_scope']=='all' and result['feedback']['catalog']==167)
        check('historical_default_retained',(await req('/api/search?topic=generative&q=retrieval&explain=true'))[1]['feedback']['catalog']==162)
        bad='/api/search?'+urlencode({'topic':'generative','q':'retrieval','need':'不要推荐','catalog_scope':'all'})
        check('warning_without_ack_rejected',(await req(bad))[0]==422)
        check('warning_ack_accepted',(await req(bad+'&plan_reviewed=true'))[0]==200)
        check('invalid_scope_rejected',(await req(search+'&catalog_scope=evil'))[0]==422)
        check('search_does_not_auto_save_demand',(await snap(a))[3]==base[3])
        check('fixed_core_vocabulary',c.vectorizer is c.core.vectorizer and (c.documents[:162]!=c.core.documents).nnz==0)
        check('same_idf',c.vectorizer.idf_.tolist()==c.core.vectorizer.idf_.tolist())
        for doc in sorted(c.supplement_ids):
            code,paper,_=await req('/api/paper/'+doc)
            check('original_v1_'+doc,code==200 and paper['paper']['version_key']=='arxiv:'+doc+'v1' and len(paper['paper']['abstract'])>500)
            check('original_link_'+doc,paper['paper']['source_url']=='https://arxiv.org/abs/'+doc+'v1')
        check('frozen_evidence_unchanged',(await req('/api/experiments'))[1]==json.loads((ROOT/'deploy/stage56/evidence-data.json').read_text(encoding='utf8')))
        def note(doc,rev,problem,questions=''):
            return dict(doc_id=doc,version_key=c.by_id[doc]['version_key'],catalog_key=key,revision=rev,problem=problem,questions=questions)
        special='<script>alert(1)</script>\n```\n# wrong heading\n[not a source](javascript:bad)'
        code,n,_=await req('/api/profile/notes/save',a,note(docs[0],0,'多模态 FAST adaptive '+special,'如何按需推理？'))
        check('real_note_save',code==200)
        await req('/api/profile/notes/save',a,note(docs[1],1,'与快慢思考无关','多模态对齐仍有疑问'))
        await req('/api/profile/notes/save',b,note(docs[2],0,'只有另一位访客能看到SecretXYZ'))
        for term,expected in [('多模态',2),('fast',1),('FAST adaptive',1),('FAST 推理',1),('多',2),('SecretXYZ',0),('" OR *',0),('retrieval',0)]:
            code,value,_=await req('/api/profile/notes/search?'+urlencode({'q':term,'revision':2}),a)
            check('own_notes_'+term,code==200 and len(value['papers'])==expected)
            if term=='多模态':check('native_fts5_used',value['trace'][0]['method']=='sqlite_fts5_trigram')
            if term=='多':check('native_short_term_fallback',value['trace'][0]['method']=='sqlite_instr_casefold')
        check('stale_notes_rejected',(await req('/api/profile/notes/search?q=FAST&revision=1',a))[0]==409)
        check('notes_search_requires_owner',(await req('/api/profile/notes/search?q=FAST&revision=2'))[0]==401)
        check('other_owner_has_own_search',len((await req('/api/profile/notes/search?q=SecretXYZ&revision=1',b))[1]['papers'])==1)
        await req('/api/profile/notes/save',a,note(docs[0],2,''))
        check('cleared_note_immediately_absent',not (await req('/api/profile/notes/search?q=FAST&revision=3',a))[1]['papers'])
        await req('/api/profile/notes/save',a,note(docs[0],3,'多模态 FAST adaptive '+special,'如何按需推理？'))
        context=dict(original_need='多模态快慢思考',executed_query=query,method='bm25',topic='generative',context='none',catalog_scope='all',plan_reviewed=False)
        def report(**kwargs):return dict(papers=[dict(doc_id=docs[0],version_key=c.by_id[docs[0]]['version_key'])],catalog_key=key,revision=0,reading_revision=0,notes_revision=4,include_notes=True,search_context=context)|kwargs
        before=await snap(a)
        code,r,_=await req('/api/profile/report/preview',a,report())
        check('report_canonical_metadata',code==200 and c.by_id[docs[0]]['source_url'] in r['markdown'] and md_text(c.by_id[docs[0]]['version_key']) in r['markdown'])
        check('report_private_notes_only',r['notes_included']==1 and 'SecretXYZ' not in r['markdown'])
        check('report_literal_fence','````text\n多模态 FAST' in r['markdown'] and special in r['markdown'])
        check('report_actual_provenance','多模态快慢思考' in r['markdown'] and query in r['markdown'] and '英文词已编辑：是' in r['markdown'])
        check('report_hash',hashlib.sha256(r['markdown'].encode()).hexdigest()==r['sha256'])
        check('report_readonly',await snap(a)==before)
        check('omit_notes',(await req('/api/profile/report/preview',a,report(include_notes=False)))[1]['notes_included']==0)
        for name,changes,status in [('stale',{'notes_revision':3},409),('catalog',{'catalog_key':c.core.catalog_key},409),('duplicate',{'papers':report()['papers']*2},422),('wrong_version',{'papers':[{'doc_id':docs[0],'version_key':'arxiv:'+docs[0]+'v2'}]},409),('none',{'papers':[]},422),('excess',{'papers':report()['papers']*21},422),('unknown',{'owner':'other'},422)]:
            check('report_reject_'+name,(await req('/api/profile/report/preview',a,report(**changes)))[0]==status)
        check('report_no_owner',(await req('/api/profile/report/preview',None,report()))[0]==401)
        check('report_origin',(await req('/api/profile/report/preview',a,report(),origin='https://evil.example'))[0]==403)
        demand=context|dict(catalog_key=key,revision=0,reason='missing_known_paper',expected_paper='2504.18458',comment='检查具体缺口')
        check('demand_no_owner',(await req('/api/profile/demands/save',None,demand))[0]==401)
        check('demand_cross_origin',(await req('/api/profile/demands/save',a,demand,origin='https://evil.example'))[0]==403)
        for name,changes,status in [('owner',{'owner':'b'},422),('url',{'expected_paper':'https://evil.example/2504.18458v1'},422),('version',{'expected_paper':'2504.18458v2'},422),('bool',{'revision':True},422),('bad_month',{'expected_paper':'2513.12345'},422),('catalog',{'catalog_key':'bad'},409)]:
            check('demand_reject_'+name,(await req('/api/profile/demands/save',a,demand|changes))[0]==status)
        code,d,_=await req('/api/profile/demands/save',a,demand)
        identifier=d['saved_id'];record=d['items'][0]
        check('demand_real_recomputed_results',code==200 and record['diagnosis']['code']=='returned' and [p['doc_id'] for p in record['shown_papers']]==[p['doc_id'] for p in result['papers']])
        check('demand_no_relevance_claim',record['feedback_source']=='explicit_visitor_report' and not record['relevance_judged'])
        check('demand_isolation',not (await req('/api/profile/demands',b))[1]['items'])
        check('demand_stale_rejected',(await req('/api/profile/demands/save',a,demand))[0]==409)
        check('other_owner_cannot_change',(await req('/api/profile/demands/status',b,dict(catalog_key=key,revision=0,id=identifier,status='resolved')))[0]==404)
        for rev,status in [(1,'resolved'),(2,'archived'),(3,'open')]:
            code,d,_=await req('/api/profile/demands/status',a,dict(catalog_key=key,revision=rev,id=identifier,status=status));check('reversible_'+status,code==200 and d['items'][0]['status']==status)
        cases=[('outside_scope',dict(catalog_scope='core')),('outside_catalog',dict(expected_paper='2611.12345')),('no_term_match',dict(executed_query='zzzzunmatchedterm')),('unresolved',dict(expected_paper='')),('filtered',dict(expected_paper=next(iter(c.model.sar.seen['paired']))))]
        for diagnosis,changes in cases:
            rev=(await req('/api/profile/demands',a))[1]['revision'];code,d,_=await req('/api/profile/demands/save',a,demand|{'revision':rev}|changes)
            check('diagnose_'+diagnosis,code==200 and next(r for r in d['items'] if r['id']==d['saved_id'])['diagnosis']['code']==diagnosis)
        code,export,h=await req('/api/profile/demands/export',a)
        check('export_no_identity_or_notes',code==200 and export['format']=='papertrail-demand-audit' and all(k not in json.dumps(export) for k in ['SecretXYZ','session.key','HttpOnly','<script>']))
        check('export_attachment','attachment' in h['content-disposition'])
        # A repeated CAS can have exactly one winner; no stale copy may overwrite a newer record.
        rev=(await req('/api/profile/demands',a))[1]['revision']
        races=await asyncio.gather(req('/api/profile/demands/save',a,demand|{'revision':rev}),req('/api/profile/demands/save',a,demand|{'revision':rev}))
        check('demand_concurrent_one_winner',sorted(r[0] for r in races)==[200,409])
        while len((await req('/api/profile/demands',a))[1]['items'])<30:
            rev=(await req('/api/profile/demands',a))[1]['revision'];code,d,_=await req('/api/profile/demands/save',a,demand|{'revision':rev});assert code==200
        rev=(await req('/api/profile/demands',a))[1]['revision']
        check('bounded_30',(await req('/api/profile/demands/save',a,demand|{'revision':rev}))[0]==422)
        code,export,_=await req('/api/profile/demands/export',a)
        check('bounded_export',code==200 and len((json.dumps(export,ensure_ascii=False,indent=2)+'\n').encode())<=256*1024)
        check('reading_preferences_untouched',(await snap(a))[:2]==base[:2])
        c.close()
    report={'status':'passed','passed':len(CHECKS),'checks':CHECKS,'scope':'disposable ASGI only; one curated real demand is not general search-quality evidence'}
    (ROOT/'reports/stage57/loop-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print({'passed':len(CHECKS)})
if __name__=='__main__':asyncio.run(main())
