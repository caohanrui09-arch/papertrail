"""Loopback-only API around the frozen native recommendation/source tools."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import Literal
import uuid

# Respect the frozen project's target layout before legacy imports can load sklearn.
sys.path.insert(0, str((Path.cwd() / '.cache/stage11/deps').resolve()))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field


class CreateSession(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: str | None = Field(default=None, min_length=1, max_length=128)
    at: datetime = datetime.fromisoformat('2025-02-23T13:28:26.401006+08:00')
    method: Literal['content', 'rrf', 'cold_aware'] = 'content'


class RecommendRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    k: int = Field(default=3, ge=1, le=10, strict=True)


class ReadRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    doc_id: str = Field(min_length=1, max_length=80)


class SessionStore:
    def __init__(self, model: object, alpha: float, capacity: int = 64, ttl_seconds: float = 900., clock=time.monotonic):
        self.model = model; self.alpha = alpha; self.capacity = capacity; self.ttl = ttl_seconds
        self.clock = clock; self.lock = threading.RLock(); self.sessions = {}

    def expire(self) -> None:
        now = self.clock()
        for key in [key for key, value in self.sessions.items() if value['expires'] <= now]:
            del self.sessions[key]

    def create(self, request: CreateSession) -> dict:
        from .showcase import choose_user
        from .expansion_discovery import ExpansionSession, make_tools
        with self.lock:
            self.expire()
            if len(self.sessions) >= self.capacity:
                raise HTTPException(503, 'Local session capacity reached')
            if request.at.tzinfo is None:
                raise HTTPException(422, 'Request time must include a timezone')
            user = request.user_id if request.user_id is not None else choose_user(self.model.users)
            mode = 'hybrid' if request.method == 'rrf' else request.method
            alpha = .5 if mode == 'hybrid' else self.alpha
            try:
                session = ExpansionSession(self.model, user, request.at.isoformat(), mode, alpha, max_calls=4)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            token = str(uuid.uuid4())
            self.sessions[token] = {'session': session, 'tools': {tool.name: tool for tool in make_tools(session)},
                                    'expires': self.clock() + self.ttl}
            return {'session_id': token, 'method': request.method, 'as_of': session.at,
                    'call_budget': 4, 'ttl_seconds': self.ttl, 'cold_user_fallback': user not in self.model.user2row}

    def call(self, token: str, name: str, **kwargs) -> dict:
        with self.lock:
            self.expire()
            entry = self.sessions.get(token)
            if entry is None:
                raise HTTPException(404, 'Unknown or expired local session')
            session = entry['session']
            if len(session.trace) >= session.max_calls:
                raise HTTPException(429, 'Session tool-call budget exhausted')
            try:
                return entry['tools'][name](**kwargs)
            except ValueError as error:
                raise HTTPException(400, str(error)) from error

    def delete(self, token: str) -> dict:
        with self.lock:
            if self.sessions.pop(token, None) is None:
                raise HTTPException(404, 'Unknown local session')
            return {'deleted': True}


def create_app(model: object, alpha: float, instance: str) -> FastAPI:
    store = SessionStore(model, alpha)
    app = FastAPI(title='Local frozen paper-tool service', docs_url=None, redoc_url=None, debug=False)

    @app.get('/')
    def index():
        return {'service': 'local-paper-tools', 'mode': 'frozen_historical_demo', 'bind': '127.0.0.1',
            'endpoints': ['/health', '/openapi.json', 'POST /sessions', 'POST /sessions/{id}/recommend',
                          'POST /sessions/{id}/read', 'DELETE /sessions/{id}'],
            'notes': 'No public exposure, external UI assets, new feedback training or LLM-policy quality claim.'}

    @app.get('/health')
    def health():
        return {'status': 'ready', 'instance_id': instance, 'pid': os.getpid(), 'candidates': len(model.catalog),
            'history_cutoff': model.cutoff.isoformat(), 'default_method': 'content', 'research_alpha': alpha,
            'source_time_assumption': 'v1 submission-day end plus24h; not proven historical ingestion'}

    @app.post('/sessions')
    def create(request: CreateSession):
        return store.create(request)

    @app.post('/sessions/{token}/recommend')
    def recommend(token: str, request: RecommendRequest):
        return store.call(token, 'recommend_papers', k=request.k)

    @app.post('/sessions/{token}/read')
    def read(token: str, request: ReadRequest):
        return store.call(token, 'read_paper', doc_id=request.doc_id)

    @app.delete('/sessions/{token}')
    def delete(token: str):
        return store.delete(token)

    return app


def load_model():
    from .relocated_demo import verify_bundle, relocated_records
    root = Path.cwd().resolve(); verify_bundle(root)
    from .content_recommendation import sklearn_runtime
    sklearn_runtime()
    from .expansion_recommendation import ExpansionRecommender, signature
    from .cold_fusion import ColdAwareRecommender
    import pandas as pd
    rows = json.loads(Path('data/stage13-expansion/documents.json').read_text(encoding='utf-8'))
    train = pd.read_csv('data/stage9-recommendation/train.csv', dtype={'user_id': str, 'arxiv_id': str})
    cutoff = json.loads(Path('reports/stage13/admission-plan.json').read_text())['cutoff']
    model = ColdAwareRecommender(ExpansionRecommender(train, relocated_records(rows, root), cutoff))
    expected = json.loads(Path('reports/stage13/resource-10000.json').read_text())['model_signature']
    if signature(model) != expected:
        raise ValueError('Service fit differs from frozen model signature')
    return model


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        raise ValueError('Use an unprivileged local port')
    from .content_recommendation import sklearn_runtime
    sklearn_runtime()
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        model = load_model()
        from .relocated_demo import runtime_origins
        runtime_origins(Path.cwd().resolve())
        alpha = json.loads(Path('reports/stage15/locked-before-dev.json').read_text())['diagnostic_alpha']
        instance = os.environ.get('GSEARCH_SERVICE_INSTANCE', str(uuid.uuid4()))
        import uvicorn
        uvicorn.run(create_app(model, alpha, instance), host='127.0.0.1', port=args.port,
                    workers=1, access_log=False, log_level='info', ws='none')


if __name__ == '__main__':
    main()
