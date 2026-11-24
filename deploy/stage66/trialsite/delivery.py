"""Read-only curated aggregate evidence, inside the unchanged visitor boundary."""
import hashlib
import json
import os
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from .sidlab import create_app as sid_app
from .readinglog import install_readinglog
from .searchfeedback import install_searchfeedback
from .notebook import install_notebook
from .querybridge import install_querybridge
from .researchtools import install_researchtools
from .demands import install_demands
from .namespacemigration import migrate_namespace
from .readingview import install_readingview
from .catalogfilters import groups
from .online import install_online

ROOT=Path(__file__).resolve().parents[1]


def create_app(settings=None):
    app=sid_app(settings)
    raw=(ROOT/'evidence-data.json').read_bytes()
    receipt=json.loads((ROOT/'evidence-receipt.json').read_text(encoding='utf-8'))
    if hashlib.sha256(raw).hexdigest()!=receipt['sha256']:raise ValueError('Evidence changed')
    evidence=json.loads(raw)
    if evidence['live']['catalog']!=len(app.state.catalog.core.catalog):raise ValueError('Live catalog scope changed')
    artifacts={}
    for key,entry in evidence['downloads'].items():
        filename=entry['filename']
        if Path(filename).name!=filename:raise ValueError('Artifact name must be fixed basename')
        data=(ROOT/'experiment-artifacts'/filename).read_bytes()
        if hashlib.sha256(data).hexdigest()!=entry['sha256'] or receipt['downloads'][key]!=entry['sha256']:
            raise ValueError('Aggregate download changed')
        artifacts[key]=(data,entry['media_type'],filename)
    app.state.experiment_evidence=evidence
    app.router.routes[:]=[r for r in app.router.routes if getattr(r,'name',None)!='sid-web' and getattr(r,'path',None)!='/api/health']

    install_readinglog(app)
    install_searchfeedback(app)
    install_notebook(app)
    install_querybridge(app)
    install_researchtools(app)
    install_demands(app)
    migrate_namespace(app)
    install_readingview(app)
    # Add display-only metadata; the immutable source response stays intact.
    previews=app.state.catalog.previews()
    for doc,p in previews['papers'].items():
        view=app.state.reading_views[doc];end=min(420,len(view['text']))
        if end<len(view['text']):
            boundary=view['text'].rfind(' ',280,end)
            if boundary!=-1:end=boundary
        p['clean_excerpt']=view['text'][:end];p['clean_truncated']=end<len(view['text']);p['collections']=groups(app.state.catalog,doc);p['authors']=app.state.catalog.by_id[doc]['authors']
    app.router.routes[:]=[r for r in app.router.routes if getattr(r,'path',None)!='/api/paper-previews']
    @app.get('/api/paper-previews')
    def paper_previews():return previews

    @app.get('/api/health')
    def health():
        return {'status':'ready','release':'stage66','catalog':len(app.state.catalog.catalog),
            'offline_sft_catalog':9000,'evidence_version':'stage51-closed','llm_enabled':False,
            'instance_id':os.environ.get('PAPERTRAIL_INSTANCE','manual')}

    @app.get('/api/experiments')
    def experiments():return evidence

    @app.get('/api/experiment-artifacts/{key}')
    def artifact(key: str):
        if key not in artifacts:raise HTTPException(404,'没有这个聚合证据文件')
        data,media,name=artifacts[key]
        return Response(data,media_type=media,headers={'Content-Disposition':f'attachment; filename="{name}"'})

    install_online(app)
    app.mount('/',StaticFiles(directory=ROOT/'web',html=True),name='delivery-web')
    return app
