"""Read-only recent project supplement, separate from the historic ranking catalog."""
import hashlib
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

from fastapi.staticfiles import StaticFiles
from .learning import create_app as learning_app

ROOT = Path(__file__).resolve().parents[1]


def create_app(settings=None):
    app = learning_app(settings)
    project = json.loads((ROOT/'project.json').read_text(encoding='utf-8'))
    raw = (ROOT/'project-original.atom').read_bytes()
    if hashlib.sha256(raw).hexdigest() != project['raw_sha256']:
        raise ValueError('Project original response changed')
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    entries = {e.findtext('a:id', namespaces=ns).split('/abs/')[-1]: e
               for e in ET.fromstring(raw).findall('a:entry', ns)}
    if {p['doc_id'] for p in project['papers']} != {'2305.05065', '2510.24431', '2510.12211'}:
        raise ValueError('Unexpected project sources')
    for paper in project['papers']:
        entry = entries[paper['doc_id']+'v1']
        if (paper['version'] != 1 or paper['source_url'] != 'https://arxiv.org/abs/'+paper['doc_id']+'v1'
                or paper['version_key'] != 'arxiv:'+paper['doc_id']+'v1'
                or paper['abstract'] != entry.findtext('a:summary', namespaces=ns).strip()
                or paper['title'] != ' '.join(entry.findtext('a:title', namespaces=ns).split())
                or paper['published_at'].replace('+00:00','Z') != entry.findtext('a:published', namespaces=ns)
                or paper['evidence'] not in paper['abstract']):
            raise ValueError('Project metadata does not match exact v1 original')
    app.state.project = project
    app.router.routes[:] = [r for r in app.router.routes if getattr(r,'name',None) != 'learning-web'
                            and getattr(r,'path',None) != '/api/health']

    @app.get('/api/health')
    def health():
        return {'status': 'ready', 'catalog': len(app.state.catalog.catalog), 'supplement_papers': 3,
                'llm_enabled': False, 'release': 'stage41',
                'instance_id': os.environ.get('PAPERTRAIL_INSTANCE','manual')}

    @app.get('/api/project/minionerec')
    def minionerec():
        return project

    app.mount('/', StaticFiles(directory=ROOT/'web', html=True), name='project-web')
    return app
