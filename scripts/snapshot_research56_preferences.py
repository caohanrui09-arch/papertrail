"""Read-only preservation of v55 visitor data across additive notebook migration."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
def snapshot()->dict:
    folder=ROOT/'data/stage39-visitors';digest=hashlib.sha256((folder/'session.key').read_bytes());counts={};notes={}
    for path in sorted(folder.glob('*.sqlite3')):
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
            names={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ['visitors','preferences','reading_revisions','reading_status']:
                if table not in names:continue
                rows=sorted(json.dumps(list(row),ensure_ascii=False) for row in db.execute('SELECT * FROM '+table))
                digest.update(table.encode());digest.update(json.dumps(rows,ensure_ascii=False).encode());counts[table]=counts.get(table,0)+len(rows)
            for table in ['note_revisions','paper_notes']:
                if table in names:notes[table]=notes.get(table,0)+db.execute('SELECT count(*) FROM '+table).fetchone()[0]
    return {'existing_semantic_sha256':digest.hexdigest(),'existing_counts':counts,'notes_schema_counts':notes}
def main()->None:
    value=snapshot();baseline=ROOT/'.cache/stage56/real-preferences-before.json'
    if '--before' in sys.argv:
        assert not baseline.exists(),'Do not overwrite initial fingerprint'
        baseline.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8');print({'baseline_recorded':True});return
    before=json.loads(baseline.read_text(encoding='utf-8'))
    assert value['existing_semantic_sha256']==before['existing_semantic_sha256'] and value['existing_counts']==before['existing_counts'],'Existing data changed; do not roll back user writes'
    assert value['notes_schema_counts']=={'note_revisions':0,'paper_notes':0},'No acceptance writes in actual visitor volume'
    report={'existing_preferences_and_reading_unchanged':True,'additive_schema_only':True,'before':before,'after':value,'scope':'read-only hash of all preexisting visitor/preference/reading rows plus secret; no raw rows or credentials exported'}
    (ROOT/'reports/stage56/preference-preservation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print({'existing_data_unchanged':True,'real_note_rows':0})
if __name__=='__main__':main()
