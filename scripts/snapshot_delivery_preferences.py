"""Read-only aggregate fingerprint; never export visitor rows or session credentials."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]

def snapshot():
    folder=ROOT/'data/stage39-visitors'
    digest=hashlib.sha256()
    digest.update((folder/'session.key').read_bytes())
    counts={}
    for path in sorted(folder.glob('*.sqlite3')):
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
            for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
                quoted='"'+table.replace('"','""')+'"'
                rows=sorted(json.dumps(list(row),ensure_ascii=False,sort_keys=True) for row in db.execute('SELECT * FROM '+quoted))
                digest.update(table.encode());digest.update(json.dumps(rows,ensure_ascii=False).encode())
                counts[table]=counts.get(table,0)+len(rows)
    return {'semantic_sha256':digest.hexdigest(),'table_counts':counts}

def main():
    value=snapshot()
    baseline=ROOT/'.cache/stage52/real-preferences-before.json'
    if '--before' in sys.argv:
        assert not baseline.exists(),'Do not overwrite original preference fingerprint'
        baseline.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
        print({'baseline_recorded':True})
    else:
        assert value==json.loads(baseline.read_text(encoding='utf-8')),'Real preference records changed'
        report={'real_preferences_unchanged':True,**value,'scope':'read-only semantic rows plus session key in combined digest; no raw rows or key exported'}
        (ROOT/'reports/stage52/preference-preservation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print({'real_preferences_unchanged':True})

if __name__=='__main__':main()
