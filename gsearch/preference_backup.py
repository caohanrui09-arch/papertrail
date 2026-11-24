"""Versioned preference interchange; reuse SQLite store, validate before atomic merge."""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .personal_search_v2 import create_app as personal_app
from .quality_protocol import aware_timestamp

MAX_FILE = 256 * 1024
MAX_REQUEST = 2 * MAX_FILE  # JSON string escaping plus small envelope.


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class BackupItem(StrictModel):
    doc_id: str = Field(pattern=r'^\d{4}\.\d{4,5}$')
    version_key: str = Field(max_length=80)
    title: str = Field(max_length=2000)
    source_url: str = Field(max_length=200)
    preference: Literal['like', 'hide']


class Backup(StrictModel):
    format: Literal['papertrail-preferences']
    schema_version: int = Field(ge=1, le=1)
    catalog_key: str = Field(max_length=100)
    exported_at: str = Field(max_length=80)
    items: list[BackupItem] = Field(max_length=500)

    @field_validator('exported_at')
    @classmethod
    def timestamp(cls, value: str) -> str:
        aware_timestamp(value)
        return value


class ImportRequest(StrictModel):
    text: str = Field(max_length=MAX_FILE)
    revision: int = Field(ge=0)
    policy: Literal['keep_current', 'use_backup'] = 'keep_current'
    preview_token: str | None = Field(default=None, max_length=64)


def unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('备份存在重复 JSON 字段')
        result[key] = value
    return result


def parse_backup(text: str, catalog) -> Backup:
    if len(text.encode('utf-8')) > MAX_FILE:
        raise HTTPException(413, '备份文件不能超过 256 KiB')
    try:
        value = json.loads(text.lstrip('\ufeff'), object_pairs_hook=unique_object)
        backup = Backup.model_validate(value)
    except (ValueError, RecursionError, ValidationError) as error:
        raise HTTPException(422, '备份格式无效：需使用本站导出的 v1 JSON 文件，且字段完整、无重复') from error
    if backup.catalog_key != catalog.catalog_key:
        raise HTTPException(409, '备份目录与当前目录不一致，未导入任何偏好')
    seen = set()
    for item in backup.items:
        if item.doc_id in seen:
            raise HTTPException(422, '备份存在重复论文 ID：' + item.doc_id)
        seen.add(item.doc_id)
        if not catalog.valid(item.doc_id):
            raise HTTPException(422, '论文不在当前可用目录：' + item.doc_id)
        canonical = catalog.paper(item.doc_id)
        if any(getattr(item, key) != canonical[key] for key in ('version_key', 'title', 'source_url')):
            raise HTTPException(409, '论文版本、标题或来源不一致：' + item.doc_id + '；未导入任何偏好')
    return backup


def merge_plan(backup: Backup, snapshot: dict, policy: str) -> tuple[dict, dict]:
    merged = dict(snapshot['items'])
    rows = []
    counts = dict(added=0, changed=0, conflicts=0, unchanged=0, skipped=0)
    for item in backup.items:
        current = merged.get(item.doc_id, 'none')
        conflict = current != 'none' and current != item.preference
        final = current if conflict and policy == 'keep_current' else item.preference
        status = 'added' if current == 'none' else 'unchanged' if current == item.preference else 'skipped' if final == current else 'changed'
        counts[status] += 1
        counts['conflicts'] += int(conflict)
        merged[item.doc_id] = final
        rows.append({**item.model_dump(), 'current': current, 'result': final, 'status': status, 'conflict': conflict})
    if len(merged) > 500:
        raise HTTPException(422, '合并后偏好超过 500 篇，未导入')
    return merged, {'rows': rows, 'counts': counts, 'total_after': len(merged),
                    'retained_outside_backup': len(set(snapshot['items']) - {item.doc_id for item in backup.items})}


def create_app(data=None):
    # Same catalog, cookie namespace and DB as v35: preserve real existing preferences.
    app = personal_app(data=data)
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, 'name', None) != 'personal-search-v2']
    catalog, preferences = app.state.personal_catalog, app.state.preferences
    secret = secrets.token_bytes(32)

    @app.middleware('http')
    async def bound_import(request: Request, call_next):
        if request.url.path.startswith('/api/profile/import'):
            size, parts = 0, []
            async for part in request.stream():
                size += len(part)
                if size > MAX_REQUEST:
                    return JSONResponse({'detail': '导入请求过大'}, status_code=413, headers={'Cache-Control': 'no-store'})
                parts.append(part)
            request._body = b''.join(parts)
        response = await call_next(request)
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def token(owner: str, body: ImportRequest, snapshot: dict) -> str:
        binding = [owner, body.text, body.policy, snapshot]
        raw = json.dumps(binding, sort_keys=True, ensure_ascii=False).encode('utf-8')
        return hmac.new(secret, raw, hashlib.sha256).hexdigest()

    def checked_revision(body: ImportRequest, snapshot: dict) -> None:
        if body.revision != snapshot['revision']:
            raise HTTPException(409, '偏好已更新，请重新预览后导入')

    @app.get('/api/profile/export')
    def export(request: Request):
        snapshot = preferences.get(request.state.owner)
        payload = {'format': 'papertrail-preferences', 'schema_version': 1, 'catalog_key': catalog.catalog_key,
                   'exported_at': datetime.now(timezone.utc).isoformat(),
                   'items': [{key: value for key, value in catalog.paper(doc).items() if key != 'version'} | {'preference': pref}
                             for doc, pref in snapshot['items'].items()]}
        # No visitor identifier, cookie, authentication material or experiment labels.
        return Response(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', media_type='application/json',
                        headers={'Content-Disposition': 'attachment; filename="papertrail-preferences-v1.json"'})

    @app.post('/api/profile/import/preview')
    def preview(body: ImportRequest, request: Request):
        backup = parse_backup(body.text, catalog)
        snapshot = preferences.get(request.state.owner)
        checked_revision(body, snapshot)
        _, plan = merge_plan(backup, snapshot, body.policy)
        return {**plan, 'revision': snapshot['revision'], 'catalog_key': catalog.catalog_key, 'policy': body.policy,
                'exported_at': backup.exported_at, 'preview_token': token(request.state.owner, body, snapshot),
                'file_sha256': hashlib.sha256(body.text.encode('utf-8')).hexdigest()}

    @app.post('/api/profile/import/apply')
    def apply(body: ImportRequest, request: Request):
        backup = parse_backup(body.text, catalog)
        # Existing store connection/snapshot/schema; one CAS transaction for the batch.
        with preferences.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            snapshot = preferences.snapshot(db, request.state.owner)
            checked_revision(body, snapshot)
            expected = token(request.state.owner, body, snapshot)
            if not body.preview_token or not hmac.compare_digest(expected, body.preview_token):
                raise HTTPException(409, '预览已失效或与当前文件、合并方式不符，请重新预览')
            merged, plan = merge_plan(backup, snapshot, body.policy)
            changed = [(doc, value) for doc, value in merged.items() if snapshot['items'].get(doc) != value]
            if changed:
                now = datetime.now(timezone.utc).isoformat()
                db.executemany('INSERT OR REPLACE INTO preferences VALUES(?,?,?,?)',
                               [(request.state.owner, doc, value, now) for doc, value in changed])
                db.execute('INSERT OR REPLACE INTO visitors VALUES(?,?)', (request.state.owner, snapshot['revision'] + 1))
            final = preferences.snapshot(db, request.state.owner)
        return {**plan, 'revision': final['revision'], 'applied': len(changed), 'catalog_key': catalog.catalog_key}

    app.mount('/', StaticFiles(directory='web/papertrail-v36/dist', html=True), name='personal-backup')
    return app


if __name__ == '__main__':
    import uvicorn
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        uvicorn.run(create_app(), host='127.0.0.1', port=8778, access_log=False, ws='none')
