"""Adapt the existing preference store and PersonalModel to the frozen v2 catalog."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import secrets
from typing import Literal

import numpy as np
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .quality_protocol import digest
from .search_v2_workbench import SearchV2, create_app as base_app
from .visitor_profile import PersonalModel, Preferences, PreferenceConflict
from scripts.build_search_v2 import ROOT, AT

DATA = Path('data/stage35-personal-v2')
STATIC = Path('web/papertrail-v35/dist')


class Feedback(BaseModel):
    model_config = ConfigDict(extra='forbid')
    doc_id: str = Field(pattern=r'^\d{4}\.\d{4,5}$')
    version_key: str = Field(max_length=80)
    catalog_key: str = Field(max_length=100)
    value: Literal['like', 'hide', 'none']
    revision: int = Field(ge=0, strict=True)


class Reset(BaseModel):
    model_config = ConfigDict(extra='forbid')
    catalog_key: str = Field(max_length=100)
    revision: int = Field(ge=0, strict=True)


class V2Catalog:
    """Interface adapter only; reuse the sealed SearchV2 TF-IDF matrix as-is."""
    def __init__(self, engine: SearchV2):
        self.engine = engine
        self.by_id, self.catalog, self.position = engine.by_id, engine.ids, engine.pos
        self.documents = engine.docs
        self.features = engine.vectorizer.get_feature_names_out()
        self.available, self.cutoff = engine.model.available, engine.model.cutoff
        # No v2 historical popularity claim. Zero-profile results are handled explicitly.
        self.popularity = np.zeros(len(self.catalog))
        self.catalog_key = 'search-v2:' + digest(ROOT / 'documents.json')
        self.signature = {
            'catalog_sha256': digest(ROOT / 'documents.json'),
            'vocabulary_sha256': hashlib.sha256(json.dumps({k: int(v) for k, v in engine.vectorizer.vocabulary_.items()}, sort_keys=True).encode()).hexdigest(),
            'idf_sha256': hashlib.sha256(engine.vectorizer.idf_.tobytes()).hexdigest(),
        }

    def valid(self, doc: str) -> bool:
        return doc in self.position and self.available[self.position[doc]] <= datetime.fromisoformat(AT).timestamp()

    def paper(self, doc: str) -> dict:
        row = self.by_id[doc]
        return {key: row[key] for key in ('doc_id', 'title', 'version', 'version_key', 'source_url')}

    def recommend(self, snapshot: dict, k: int = 6) -> dict:
        model = PersonalModel(self, snapshot)
        if not model.norm:
            papers = []
            message = '还没有有效收藏画像，请先从检索结果收藏论文。'
        else:
            rows = model.recommend('visitor', AT, 'content', k, 0)
            # Presentation rule: do not label zero-overlap ties as similar recommendations.
            rows = [row for row in rows if row['score'] > 0]
            papers = [{**row, 'rank': rank, 'review': None} for rank, row in enumerate(rows, 1)]
            message = '依据当前收藏的标题与摘要计算，只展示正分词项重合，已排除收藏和不感兴趣论文。'
            if not papers:
                message = '当前收藏与剩余论文没有正分词项重合，可继续搜索并收藏其他论文。'
            for row in papers:
                explanation = row['explanation']
                assert np.isclose(row['score'], explanation['all_term_contribution_sum'], rtol=1e-12, atol=1e-12)
                assert np.isclose(row['score'], explanation['all_anchor_contribution_sum'], rtol=1e-12, atol=1e-12)
                assert all(anchor['doc_id'] in model.likes for anchor in explanation['anchors'])
        return {'papers': papers, 'message': message, 'query': '基于我的收藏', 'history': [], 'review_applies': False,
                'profile_revision': snapshot['revision'], 'catalog_key': self.catalog_key, 'model_signature': self.signature,
                'trace': [{'tool': '个人内容推荐', 'method': 'content_tfidf_cosine', 'profile_revision': snapshot['revision'],
                           'catalog': len(self.catalog), 'likes': len(model.likes), 'excluded_feedback': len(snapshot['items']),
                           'returned': len(papers), 'zero_profile': not bool(model.norm), 'used_model_review': False}],
                'scope': '当前偏好作用于冻结开发目录，不是历史回放或新质量评价。'}


def create_app(data: Path | None = None):
    catalog = V2Catalog(SearchV2())
    folder = data or DATA
    folder.mkdir(parents=True, exist_ok=True)
    # The namespace is also in the filename; later catalogs cannot silently reuse this DB.
    preferences = Preferences(folder / (catalog.signature['catalog_sha256'] + '.sqlite3'))
    app = base_app()
    app.router.routes[:] = [route for route in app.router.routes if getattr(route, 'name', None) != 'search-v2']
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost'])
    app.state.personal_catalog = catalog
    app.state.preferences = preferences

    @app.middleware('http')
    async def local_preferences(request: Request, call_next):
        origin = request.headers.get('origin')
        if request.method not in ('GET', 'HEAD') and origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail': '偏好修改仅接受本站同源请求'}, status_code=403)
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': '仅接受本站请求'}, status_code=403)
        token = request.cookies.get('papertrail_v2_visitor')
        fresh = not token or not re.fullmatch(r'[a-f0-9]{64}', token)
        if fresh:
            token = secrets.token_hex(32)
        request.state.owner = hashlib.sha256((catalog.catalog_key + '\0' + token).encode()).hexdigest()
        response = await call_next(request)
        if fresh:
            response.set_cookie('papertrail_v2_visitor', token, httponly=True, samesite='strict', max_age=31536000, path='/')
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def view(snapshot: dict) -> dict:
        items = [{**catalog.paper(doc), 'preference': value} for doc, value in snapshot['items'].items()]
        return {'revision': snapshot['revision'], 'catalog_key': catalog.catalog_key, 'catalog_size': len(catalog.catalog),
                'items': items, 'like_count': sum(row['preference'] == 'like' for row in items),
                'hidden_count': sum(row['preference'] == 'hide' for row in items),
                'scope': '当前浏览器的搜索v2偏好空间；不自动混入旧万篇目录画像。'}

    def same_catalog(key: str) -> None:
        if key != catalog.catalog_key:
            raise HTTPException(409, '目录版本已变化，请刷新后重试')

    @app.get('/api/profile')
    def profile(request: Request):
        return view(preferences.get(request.state.owner))

    @app.post('/api/profile/feedback')
    def feedback(body: Feedback, request: Request):
        same_catalog(body.catalog_key)
        if not catalog.valid(body.doc_id):
            raise HTTPException(422, '论文不在当前可用目录')
        if body.version_key != catalog.by_id[body.doc_id]['version_key']:
            raise HTTPException(409, '论文版本不一致，请刷新后重试')
        previous = preferences.get(request.state.owner)
        try:
            snapshot = preferences.change(request.state.owner, body.revision, body.doc_id, body.value)
        except PreferenceConflict as error:
            raise HTTPException(409, str(error))
        except ValueError as error:
            raise HTTPException(422, str(error))
        return {**view(snapshot), 'change': {'doc_id': body.doc_id, 'version_key': body.version_key,
                'previous_value': previous['items'].get(body.doc_id, 'none'), 'value': body.value}}

    @app.post('/api/profile/reset')
    def reset(body: Reset, request: Request):
        same_catalog(body.catalog_key)
        try:
            return view(preferences.change(request.state.owner, body.revision, None, 'reset'))
        except PreferenceConflict as error:
            raise HTTPException(409, str(error))

    @app.get('/api/recommendations')
    def recommend(request: Request):
        return catalog.recommend(preferences.get(request.state.owner))

    app.mount('/', StaticFiles(directory=STATIC.resolve(), html=True), name='personal-search-v2')
    return app


if __name__ == '__main__':
    import uvicorn
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        uvicorn.run(create_app(), host='127.0.0.1', port=8777, access_log=False, ws='none')
