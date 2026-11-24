"""Read-only preservation check of every visitor namespace and all private tables."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
TABLES=['visitors','preferences','reading_revisions','reading_status','note_revisions','paper_notes','demand_revisions','paper_demands','namespace_migrations']
def snapshot():
    folder=ROOT/'data/stage39-visitors';result={}
    for path in sorted(folder.glob('*.sqlite3')):
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            rows={t:db.execute('SELECT * FROM '+t+' ORDER BY 1,2').fetchall() for t in TABLES if t in names}
        result[path.name]={'counts':{t:len(v) for t,v in rows.items()},'sha256':hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()}
    result['key_sha256']=hashlib.sha256((folder/'session.key').read_bytes()).hexdigest()
    return result
def main():
    baseline=ROOT/'.cache/stage61/real-before.json';value=snapshot()
    if '--before' in sys.argv:
        assert not baseline.exists(),'Never replace the first fingerprint'
        baseline.write_text(json.dumps(value,indent=2)+'\n',encoding='utf8');print({'baseline_recorded':True});return
    original=json.loads(baseline.read_text(encoding='utf8'))
    assert original==value,'Visitor data changed; inspect concurrent user writes instead of overwriting them'
    report={'status':'passed','all_existing_namespaces_unchanged':True,'session_key_preserved':True,'before':original,'after':value,'scope':'all six prior tables plus demand and migration tables; no real acceptance feedback or notes, no raw rows or credentials exported'}
    (ROOT/'reports/stage61/preference-preservation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print({'all_existing_namespaces_unchanged':True,'databases':len(value)-1})
if __name__=='__main__':main()
