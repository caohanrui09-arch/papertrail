"""Read-only comparison of all six tables and the secret across real namespace migration."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deploy/stage57'))
from trialsite.workspacecatalog import WorkspaceCatalog
TABLES=['visitors','preferences','reading_revisions','reading_status','note_revisions','paper_notes']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def fingerprint(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        rows={t:db.execute('SELECT * FROM '+t+' ORDER BY 1,2').fetchall() for t in TABLES}
    return {'counts':{k:len(v) for k,v in rows.items()},'semantic_sha256':hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()}
def main():
    c=WorkspaceCatalog(ROOT/'deploy/stage57/catalog',ROOT/'deploy/stage57/supplement')
    volume=ROOT/'data/stage39-visitors';source=volume/(c.core.signature['catalog_sha256']+'.sqlite3');target=volume/(c.signature['catalog_sha256']+'.sqlite3')
    secret=sha(volume/'session.key');before=ROOT/'.cache/stage57/real-before.json'
    if '--before' in sys.argv:
        assert not before.exists(),'Never replace the initial fingerprint'
        assert not target.exists(),'Expected the new namespace to be absent before cutover'
        before.write_text(json.dumps({'source':fingerprint(source),'session_key_sha256':secret},indent=2)+'\n',encoding='utf8')
        print({'baseline_recorded':True});c.close();return
    old=json.loads(before.read_text(encoding='utf8'));previous=fingerprint(source);current=fingerprint(target)
    assert old['source']==previous==current,'Existing rows differ; inspect before proceeding, never overwrite visitor writes'
    assert old['session_key_sha256']==secret,'Visitor credential key changed'
    with closing(sqlite3.connect(target.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        demands=db.execute('SELECT count(*) FROM paper_demands').fetchone()[0]
    assert demands==0,'Acceptance demand records must stay in the isolated volume'
    report={'status':'passed','all_six_tables_preserved':True,'source_untouched':True,'session_key_preserved':True,'counts':current['counts'],'semantic_sha256':current['semantic_sha256'],'real_demand_rows':demands,'scope':'cutover instant, before browser demo; all acceptance mutations in disposable volumes, no raw identities or credentials exported'}
    (ROOT/'reports/stage57/preference-preservation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print({'all_six_tables_preserved':True,'counts':current['counts']});c.close()
if __name__=='__main__':main()
