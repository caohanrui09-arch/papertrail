"""Force SQLite mid-batch failure to verify transaction rollback, independent of HTTP."""
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from gsearch.preference_backup import create_app, ImportRequest
from gsearch.quality_protocol import save


def main():
    with TemporaryDirectory(dir='.cache/stage36') as directory:
        app = create_app(data=Path(directory))
        store, catalog = app.state.preferences, app.state.personal_catalog
        endpoints = {r.path: r.endpoint for r in app.routes if hasattr(r, 'endpoint')}
        request = SimpleNamespace(state=SimpleNamespace(owner='atomic-test'))
        def row(doc):
            return {k:v for k,v in catalog.paper(doc).items() if k != 'version'} | {'preference':'like'}
        backup = dict(format='papertrail-preferences', schema_version=1, catalog_key=catalog.catalog_key,
                      exported_at='2026-10-30T12:00:00+08:00', items=[row('2206.02743'),row('1507.08439')])
        body = ImportRequest(text=json.dumps(backup), revision=0)
        preview = endpoints['/api/profile/import/preview'](body, request)
        with store.connect() as db:
            db.execute("CREATE TRIGGER forced_failure BEFORE INSERT ON preferences WHEN NEW.doc_id='1507.08439' BEGIN SELECT RAISE(ABORT, 'test rollback'); END")
        try:
            endpoints['/api/profile/import/apply'](body.model_copy(update={'preview_token':preview['preview_token']}), request)
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError('Expected forced database failure')
        assert store.get('atomic-test') == {'revision':0,'items':{}}
        with store.connect() as db:
            db.execute('DROP TRIGGER forced_failure')
        result = endpoints['/api/profile/import/apply'](body.model_copy(update={'preview_token':preview['preview_token']}), request)
        assert result['applied'] == 2 and result['revision'] == 1
        assert len(store.get('atomic-test')['items']) == 2
    save(Path('reports/stage36/atomicity-validation.json'), {'status':'passed','forced_second_insert_failure_rolled_back_first':True,
         'revision_rolled_back':True,'valid_retry_applied_once':True,'isolated_temporary_database':True})
    print('Atomic rollback and retry passed')


if __name__ == '__main__':
    main()
