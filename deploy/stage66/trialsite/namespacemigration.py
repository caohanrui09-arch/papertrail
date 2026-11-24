"""Copy the prior visitor namespace once, atomically, without modifying its source."""
from datetime import datetime,timezone
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from filelock import FileLock
from fastapi import FastAPI
from .notebook import note_snapshot

TABLES=['visitors','preferences','reading_revisions','reading_status','note_revisions','paper_notes']

def migrate_namespace(app:FastAPI)->None:
    c,store=app.state.catalog,app.state.preferences
    source=app.state.settings.data_dir/(c.core.signature['catalog_sha256']+'.sqlite3')
    if not source.exists() or source.resolve()==store.path.resolve():return
    with FileLock(str(app.state.settings.data_dir/'namespace-migration.lock'),timeout=3):
        with store.connect() as target:
            target.execute('BEGIN IMMEDIATE')
            target.execute('CREATE TABLE IF NOT EXISTS namespace_migrations(source_key TEXT PRIMARY KEY,applied_at TEXT NOT NULL,receipt TEXT NOT NULL)')
            if target.execute('SELECT 1 FROM namespace_migrations WHERE source_key=?',(c.core.catalog_key,)).fetchone():return
            if any(target.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in TABLES):raise ValueError('Target namespace not empty; refuse overwrite')
            counts={};digest=hashlib.sha256()
            with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as previous:
                previous.execute('BEGIN');names={r[0] for r in previous.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in TABLES:
                    if table not in names:continue
                    columns=len(previous.execute('PRAGMA table_info('+table+')').fetchall());count=0
                    cursor=previous.execute('SELECT * FROM '+table+' ORDER BY 1,2')
                    while rows:=cursor.fetchmany(100):
                        target.executemany('INSERT INTO '+table+' VALUES('+','.join('?' for _ in range(columns))+')',rows)
                        for row in rows:digest.update(json.dumps([table,list(row)],ensure_ascii=False).encode())
                        count+=len(rows)
                    counts[table]=count
            # Preserve all notes or reject the upgrade; never truncate a visitor's text to fit.
            for (owner,) in target.execute('SELECT owner FROM visitors'):
                notes=note_snapshot(target,owner)['items']
                cost=sum(len(json.dumps(v[k],ensure_ascii=False).encode())-2 for v in notes.values() for k in ('problem','questions'))
                if cost>app.state.note_budget:raise ValueError('Existing notebook exceeds new bounded backup budget; source preserved')
            receipt={'tables':counts,'semantic_sha256':digest.hexdigest(),'source_preserved':True}
            target.execute('INSERT INTO namespace_migrations VALUES(?,?,?)',(c.core.catalog_key,datetime.now(timezone.utc).isoformat(),json.dumps(receipt)))
    app.state.namespace_migration=receipt
