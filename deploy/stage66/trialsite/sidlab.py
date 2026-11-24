"""Serve precomputed structure diagnostics within the existing trial boundary."""
import hashlib
import json
import os
from pathlib import Path

from fastapi.staticfiles import StaticFiles
from .minionerec import create_app as project_app

ROOT = Path(__file__).resolve().parents[1]


def create_app(settings=None):
    app = project_app(settings)
    data = (ROOT/'sid-lab.json').read_bytes()
    receipt = json.loads((ROOT/'sid-lab-receipt.json').read_text(encoding='utf-8'))
    if hashlib.sha256(data).hexdigest() != receipt['sha256']:
        raise ValueError('Frozen SID diagnostic changed')
    lab = json.loads(data)
    catalog = app.state.catalog.core
    if lab['catalog_sha256'] != catalog.signature['catalog_sha256']:
        raise ValueError('SID mapping belongs to a different catalog')
    if sorted(p['doc_id'] for p in lab['papers']) != catalog.catalog:
        raise ValueError('SID paper identity mismatch')
    for paper in lab['papers']:
        if any(paper[k] != catalog.paper(paper['doc_id'])[k] for k in ['title','version','version_key','source_url']):
            raise ValueError('SID paper metadata mismatch')
    if [f['seed'] for f in lab['fits']] != [42,2024,3407] or any(len(f['shuffles'])!=20 for f in lab['fits']):
        raise ValueError('Incomplete frozen SID controls')
    app.state.sid_lab = lab
    app.router.routes[:] = [r for r in app.router.routes if getattr(r,'name',None) != 'project-web'
                            and getattr(r,'path',None) != '/api/health']

    @app.get('/api/health')
    def health():
        return {'status':'ready','release':'stage43','catalog':len(catalog.catalog),
                'supplement_papers':3,'sid_models':3,'llm_enabled':False,
                'instance_id':os.environ.get('PAPERTRAIL_INSTANCE','manual')}

    @app.get('/api/sid-lab')
    def sid_lab():
        return lab

    app.mount('/', StaticFiles(directory=ROOT/'web',html=True),name='sid-web')
    return app
