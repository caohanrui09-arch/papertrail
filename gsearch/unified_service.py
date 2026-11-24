"""Stage19 loopback API, separate from the sealed stage18 service."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import sys
import threading
import time
from typing import Literal
import uuid

sys.path.insert(0, str((Path.cwd() / '.cache/stage11/deps').resolve()))
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .unified_search import AsOfBM25
from .unified_session import UnifiedSession


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: str | None = Field(default=None, min_length=1, max_length=128)
    at: datetime = datetime.fromisoformat('2025-02-23T05:28:26.401006+00:00')
    method: Literal['content', 'rrf', 'cold_aware'] = 'content'


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Literal['search_papers', 'recommend_papers', 'read_paper', 'finalize']
    arguments: dict


def create_app(model: object, instance: str, capacity: int = 64, ttl: float = 900., clock=time.monotonic) -> FastAPI:
    from .showcase import choose_user
    app = FastAPI(title='Unified local paper tools', docs_url=None, redoc_url=None)
    search = AsOfBM25(model)
    sessions: dict[str, dict] = {}
    lock = threading.RLock()

    def expire() -> None:
        for token in [t for t, entry in sessions.items() if entry['expires'] <= clock()]:
            del sessions[token]

    def entry(token: str) -> UnifiedSession:
        expire()
        if token not in sessions:
            raise HTTPException(404, 'Unknown or expired session')
        return sessions[token]['session']

    @app.get('/health')
    def health():
        return {'status': 'ready', 'instance_id': instance, 'pid': os.getpid(), 'candidates': len(model.catalog),
            'bind': '127.0.0.1', 'tools': ['search_papers', 'recommend_papers', 'read_paper'],
            'retrieval': 'sqlite_fts5_bm25', 'default_recommendation': 'content',
            'history_cutoff': model.cutoff.isoformat(), 'llm_in_service': False}

    @app.post('/sessions')
    def create(request: SessionRequest):
        with lock:
            expire()
            if len(sessions) >= capacity:
                raise HTTPException(503, 'Session capacity reached')
            try:
                session = UnifiedSession(model, search, request.user_id or choose_user(model.users), request.at.isoformat(), request.method)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            token = str(uuid.uuid4())
            sessions[token] = {'session': session, 'expires': clock() + ttl}
            return {'session_id': token, 'as_of': session.at, 'tool_attempt_budget': 6,
                    'retrieval_attempt_budget': 2, 'read_attempt_budget': 2, 'ttl_seconds': ttl}

    @app.post('/sessions/{token}/tools')
    def tool(token: str, request: ToolRequest):
        with lock:
            session = entry(token)
            if session.attempts >= 6:
                raise HTTPException(429, 'Six-attempt tool budget exhausted')
            result = session.invoke(request.name, request.arguments)
            # Policy/argument failures are recorded and billed, then returned to
            # native Agent error handling. No permissive tool-output repair.
            if 'error' in result:
                raise HTTPException(400, result['error'])
            return result

    @app.get('/sessions/{token}')
    def snapshot(token: str):
        with lock:
            return entry(token).snapshot()

    @app.delete('/sessions/{token}')
    def delete(token: str):
        with lock:
            entry(token)
            del sessions[token]
            return {'deleted': True}

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        raise ValueError('Unprivileged loopback port required')
    from .local_service import load_model
    from .content_recommendation import sklearn_runtime
    sklearn_runtime()
    from threadpoolctl import threadpool_limits
    import uvicorn
    with threadpool_limits(limits=1):
        model = load_model()
        uvicorn.run(create_app(model, os.environ['GSEARCH_SERVICE_INSTANCE']), host='127.0.0.1',
            port=args.port, access_log=False, ws='none', workers=1)


if __name__ == '__main__':
    main()
