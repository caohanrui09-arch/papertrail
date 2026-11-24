"""Read-only preservation of legacy preference rows; permit additive reading schema."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
def snapshot():
    folder=ROOT/'data/stage39-visitors';digest=hashlib.sha256((folder/'session.key').read_bytes());counts={};reading={}
    for path in sorted(folder.glob('*.sqlite3')):
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
            for table in ['visitors','preferences']:
                rows=sorted(json.dumps(list(row),ensure_ascii=False) for row in db.execute('SELECT * FROM '+table))
                digest.update(table.encode());digest.update(json.dumps(rows,ensure_ascii=False).encode());counts[table]=counts.get(table,0)+len(rows)
            names={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ['reading_revisions','reading_status']:
                if table in names:reading[table]=reading.get(table,0)+db.execute('SELECT count(*) FROM '+table).fetchone()[0]
    return {'legacy_semantic_sha256':digest.hexdigest(),'legacy_counts':counts,'reading_schema_counts':reading}
def main():
    value=snapshot();baseline=ROOT/'.cache/stage55/real-preferences-before.json'
    if '--before' in sys.argv:
        assert not baseline.exists(),'Do not overwrite initial fingerprint'
        baseline.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8');print({'baseline_recorded':True});return
    before=json.loads(baseline.read_text(encoding='utf-8'))
    assert value['legacy_semantic_sha256']==before['legacy_semantic_sha256'] and value['legacy_counts']==before['legacy_counts'],'Existing preferences changed; do not roll back user writes'
    assert value['reading_schema_counts']=={'reading_revisions':0,'reading_status':0},'No acceptance writes allowed in actual visitor volume'
    report={'real_preferences_unchanged':True,'additive_schema_only':True,'before':before,'after':value,'scope':'read-only semantic hash of legacy rows and secret; no raw visitor rows or credentials exported'}
    (ROOT/'reports/stage55/preference-preservation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print({'real_preferences_unchanged':True,'reading_rows':0})
if __name__=='__main__':main()
