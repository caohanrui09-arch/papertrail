"""Reproduce upgrade from the prior release, including rollback on capacity failure."""
import asyncio
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
SEED='--seed' in sys.argv
sys.path.insert(0,str(ROOT/('deploy/stage56' if SEED else 'deploy/stage59')))
from trialsite.delivery import create_app
from trialsite.security import Settings
from scripts.validate_trial import call,extract
TABLES=['visitors','preferences','reading_revisions','reading_status','note_revisions','paper_notes']
CHECKS=[]
def check(name,value):
    if not value:raise AssertionError(name)
    CHECKS.append(name)
def settings(folder):return replace(Settings('https://trial.example',Path(folder)),visitor_per_minute=4000,writes_per_minute=3000,global_per_minute=10000,expensive_per_minute=2000)
def fingerprint(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        rows={t:db.execute('SELECT * FROM '+t+' ORDER BY 1,2').fetchall() for t in TABLES}
    return {'counts':{t:len(v) for t,v in rows.items()},'sha256':hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()}
async def seed(folder,capacity=False):
    app=create_app(settings(folder));c=app.state.catalog
    async def req(path,body=None):return await call(app,path,'POST' if body is not None else 'GET',body,a)
    _,_,headers=await call(app,'/api/profile');a=extract(headers)
    await call(app,'/api/profile')
    def feedback(doc,value):return {'doc_id':doc,'version_key':c.by_id[doc]['version_key'],'catalog_key':c.catalog_key,'revision':0,'value':value}
    assert (await req('/api/profile/feedback',feedback(c.catalog[0],'like')))[0]==200
    assert (await req('/api/profile/reading/feedback',feedback(c.catalog[0],'reading')))[0]==200
    rev=0
    for doc in c.catalog[:21 if capacity else 1]:
        payload={k:v for k,v in feedback(doc,'like').items() if k!='value'}|dict(revision=rev,problem='界'*1000 if capacity else '旧版本的阅读理解',questions='问'*1000 if capacity else '旧版本的问题')
        code,value,_=await req('/api/profile/notes/save',payload)
        assert code==200,(code,value)
        rev=value['revision']
    fixture={'cookie':a,'key':c.catalog_key,'docs':c.catalog[:2],'db':str(app.state.preferences.path),'old_backup':(await req('/api/profile/notebook/export'))[1]}
    (Path(folder)/'fixture.json').write_text(json.dumps(fixture,ensure_ascii=False),encoding='utf8')
    c.bm25.close()
async def main():
    for capacity in [False,True]:
        with tempfile.TemporaryDirectory(prefix='namespace-',dir=ROOT/'.cache/stage59') as folder:
            run=subprocess.run([sys.executable,'-E','-s','-m','scripts.validate_research59_migration','--seed',folder]+(['--capacity'] if capacity else []),cwd=ROOT,capture_output=True,text=True)
            if run.returncode:raise RuntimeError('Prior-release seed failed: '+run.stderr)
            fixture=json.loads((Path(folder)/'fixture.json').read_text(encoding='utf8'));source=Path(fixture['db'])
            before=fingerprint(source);secret=hashlib.sha256((Path(folder)/'session.key').read_bytes()).hexdigest()
            if capacity:
                try:create_app(settings(folder))
                except ValueError as e:check('oversized_notes_reject_upgrade','budget' in str(e))
                else:raise AssertionError('capacity guard did not reject')
                check('rejected_upgrade_keeps_source',fingerprint(source)==before)
                targets=[p for p in Path(folder).glob('*.sqlite3') if p!=source]
                check('failed_copy_atomic',len(targets)==1 and all(n==0 for n in fingerprint(targets[0])['counts'].values()))
                continue
            app=create_app(settings(folder));c=app.state.catalog;store=app.state.preferences
            check('six_tables_preserved',fingerprint(store.path)==before)
            check('source_untouched',fingerprint(source)==before)
            check('session_key_kept',hashlib.sha256((Path(folder)/'session.key').read_bytes()).hexdigest()==secret)
            async def req(path,body=None,who=None):return await call(app,path,'POST' if body is not None else 'GET',body,who or fixture['cookie'])
            code,profile,_=await req('/api/profile')
            check('existing_identity_works',code==200 and profile['like_count']==1 and profile['catalog_key']==c.catalog_key)
            check('reading_preserved',(await req('/api/profile/reading'))[1]['items'][0]['reading_state']=='reading')
            notes=(await req('/api/profile/notes'))[1]
            check('note_text_preserved',notes['items'][0]['problem']=='旧版本的阅读理解')
            check('new_demand_space_empty',not (await req('/api/profile/demands'))[1]['items'])
            _,_,headers=await call(app,'/api/profile');other=extract(headers)
            p=(await req('/api/profile',who=other))[1];r=(await req('/api/profile/reading',who=other))[1];n=(await req('/api/profile/notes',who=other))[1]
            body={'text':json.dumps(fixture['old_backup'],ensure_ascii=False),'revision':p['revision'],'reading_revision':r['revision'],'notes_revision':n['revision'],'policy':'keep_current'}
            code,plan,_=await req('/api/profile/notebook/import/preview',body,other)
            check('prior_v3_preview_accepted',code==200 and plan['changes_total']==3)
            code,result,_=await req('/api/profile/notebook/import/apply',body|{'preview_token':plan['preview_token']},other)
            check('prior_v3_applies',code==200 and (await req('/api/profile/notes',who=other))[1]['items'][0]['problem']=='旧版本的阅读理解')
            # Compatible key is restricted to documents that actually belonged to it.
            tampered=json.loads(json.dumps(fixture['old_backup']));newdoc=next(iter(c.supplement_ids))
            row=tampered['notes'][0];row.update(c.paper(newdoc))
            p=(await req('/api/profile',who=other))[1];r=(await req('/api/profile/reading',who=other))[1];n=(await req('/api/profile/notes',who=other))[1]
            body.update(text=json.dumps(tampered,ensure_ascii=False),revision=p['revision'],reading_revision=r['revision'],notes_revision=n['revision'])
            check('prior_key_cannot_claim_new_paper',(await req('/api/profile/notebook/import/preview',body,other))[0]==422)
            target_before=fingerprint(store.path)
            again=create_app(settings(folder))
            check('restart_never_recopies',fingerprint(store.path)==target_before and fingerprint(source)==before)
            again.state.catalog.close()
            with store.connect() as db:db.execute('DELETE FROM namespace_migrations')
            try:create_app(settings(folder))
            except ValueError as e:check('nonempty_target_without_marker_refused','not empty' in str(e))
            else:raise AssertionError('overwrite guard did not reject')
            check('overwrite_rejection_preserves_rows',fingerprint(store.path)==target_before)
            c.close()
    (ROOT/'reports/stage59/migration-validation.json').write_text(json.dumps({'status':'passed','passed':len(CHECKS),'checks':CHECKS,'scope':'two disposable v56→v57 databases; no real visitor mutations'},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print({'passed':len(CHECKS)})
if __name__=='__main__':
    if SEED:asyncio.run(seed(sys.argv[sys.argv.index('--seed')+1],'--capacity' in sys.argv))
    else:asyncio.run(main())
