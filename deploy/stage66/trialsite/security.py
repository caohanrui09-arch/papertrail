"""Small single-instance boundary; rate algorithms come from pinned limits."""
from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
from urllib.parse import urlsplit

import anyio
from limits import parse
from limits.aio.storage import MemoryStorage
from limits.aio.strategies import FixedWindowRateLimiter
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .reuse import Preferences


@dataclass(frozen=True)
class Settings:
    origin: str
    data_dir: Path
    production: bool = True
    max_visitors: int = 200
    max_active: int = 12
    visitor_per_minute: int = 90
    expensive_per_minute: int = 30
    writes_per_minute: int = 20
    global_per_minute: int = 600
    registration_per_minute: int = 20

    def validate(self) -> None:
        parsed = urlsplit(self.origin)
        if parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password or not parsed.hostname:
            raise ValueError('Exact public origin required, without path or credentials')
        if self.production and (parsed.scheme != 'https' or parsed.hostname in ('localhost', '127.0.0.1')):
            raise ValueError('Production requires an explicit HTTPS origin')
        if not self.production and (parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1')):
            raise ValueError('Preview must bind loopback only')
        if os.environ.get('WEB_CONCURRENCY','1') != '1':
            raise ValueError('Only one worker is supported')
        if not 1 <= self.max_visitors <= 200: raise ValueError('Visitor capacity out of trial range')


class TrialStore(Preferences):
    def __init__(self, path: Path, capacity: int):
        self.capacity = capacity
        super().__init__(path)

    def connect(self):
        # Same transaction/snapshot implementation; storage bound applies to every connection.
        from contextlib import contextmanager
        @contextmanager
        def bounded():
            db = sqlite3.connect(self.path, timeout=3)
            try:
                db.execute('PRAGMA busy_timeout=3000')
                if db.execute('PRAGMA max_page_count=8192').fetchone()[0] > 8192:
                    raise ValueError('Visitor database exceeds 32 MiB trial budget')
                with db: yield db
            finally: db.close()
        return bounded()

    def reserve(self, owner: str) -> bool:
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM visitors WHERE owner=?',(owner,)).fetchone(): return True
            if db.execute('SELECT count(*) FROM visitors').fetchone()[0] >= self.capacity: return False
            db.execute('INSERT INTO visitors VALUES(?,0)',(owner,))
            return True

    def exists(self, owner: str) -> bool:
        with self.connect() as db:
            return bool(db.execute('SELECT 1 FROM visitors WHERE owner=?',(owner,)).fetchone())


def persistent_secret(folder: Path) -> bytes:
    path = folder/'session.key'
    if not path.exists():
        # Atomic creation: never print or copy this key into a deployment artifact.
        try:
            fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        except FileExistsError: pass
        else:
            with os.fdopen(fd, 'wb') as out: out.write(secrets.token_bytes(32))
    value = path.read_bytes()
    if len(value) != 32: raise ValueError('Invalid persistent session key')
    return value


class TrialBoundary:
    def __init__(self, app, settings: Settings, store: TrialStore, secret: bytes):
        self.settings, self.store, self.secret = settings, store, secret
        self.app = TrustedHostMiddleware(app, allowed_hosts=[urlsplit(settings.origin).hostname], www_redirect=False)
        self.cookie = '__Host-papertrail_trial' if settings.production else 'papertrail_trial_local'
        self.active = 0
        self.storage = MemoryStorage()
        self.limiter = FixedWindowRateLimiter(self.storage)
        self.limits = {name:parse(str(value)+'/minute') for name,value in {
            'global':settings.global_per_minute, 'visitor':settings.visitor_per_minute,
            'expensive':settings.expensive_per_minute, 'write':settings.writes_per_minute,
            'register':settings.registration_per_minute}.items()}

    def signed(self) -> str:
        nonce = secrets.token_hex(32)
        return nonce+'.'+hmac.new(self.secret, ('session:'+nonce).encode(), hashlib.sha256).hexdigest()

    def owner(self, value: str | None) -> str | None:
        if not value or not re.fullmatch(r'[a-f0-9]{64}\.[a-f0-9]{64}', value): return None
        nonce, signature = value.split('.')
        expected = hmac.new(self.secret, ('session:'+nonce).encode(), hashlib.sha256).hexdigest()
        return hashlib.sha256(value.encode()).hexdigest() if hmac.compare_digest(expected, signature) else None

    async def allowed(self, name: str, key: str) -> bool:
        return await self.limiter.hit(self.limits[name], name, key)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http': return await self.app(scope, receive, send)
        fresh = None
        # Add headers to early rejects, static files, and API responses equally.
        async def secure_send(message):
            if message['type']=='http.response.start':
                from starlette.datastructures import MutableHeaders
                headers = MutableHeaders(scope=message)
                import base64
                mapping = '{"imports":{"preact":"/vendor/preact.mjs","preact/hooks":"/vendor/hooks.mjs","htm":"/vendor/htm.mjs"}}'
                integrity = base64.b64encode(hashlib.sha256(mapping.encode()).digest()).decode()
                headers['Content-Security-Policy'] = f"default-src 'self'; script-src 'self' 'sha256-{integrity}'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
                headers['X-Content-Type-Options']='nosniff'
                headers['Referrer-Policy']='no-referrer'
                headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
                if scope['path'].startswith('/api/'): headers['Cache-Control']='no-store'
                if self.settings.production: headers['Strict-Transport-Security']='max-age=31536000'
                if fresh:
                    from starlette.responses import Response
                    cookie_response = Response()
                    cookie_response.set_cookie(self.cookie, fresh, secure=self.settings.production,
                         httponly=True, samesite='strict', max_age=90*86400, path='/')
                    message['headers'].append(next(h for h in cookie_response.raw_headers if h[0]==b'set-cookie'))
            await send(message)

        async def reject(code, detail):
            return await JSONResponse({'detail':detail}, status_code=code,
                        headers={'Retry-After':'60'} if code in (429,503) else None)(scope, receive, secure_send)

        request = Request(scope, receive=receive)
        if request.headers.get('host') != urlsplit(self.settings.origin).netloc:
            return await reject(400,'站点地址不匹配')
        if request.headers.get('sec-fetch-site') == 'cross-site' and scope['path'].startswith('/api/'):
            return await reject(403,'请从本站访问接口')
        if request.method not in ('GET','HEAD') and request.headers.get('origin') != self.settings.origin:
            return await reject(403,'修改偏好需本站同源请求')
        if scope['path'] == '/api/health' and request.method == 'GET':
            return await self.app(scope,receive,secure_send)
        if self.active >= self.settings.max_active: return await reject(503,'同时请求过多，请稍后重试')
        self.active += 1
        try:
            path = scope['path']
            if path != '/api/health':
                if not await self.allowed('global','all'): return await reject(429,'试用服务繁忙，请稍后重试')
            identity_route = path.startswith('/api/profile') or path == '/api/recommendations'
            owner = self.owner(request.cookies.get(self.cookie))
            if identity_route:
                if owner is None or not await anyio.to_thread.run_sync(self.store.exists, owner):
                    if request.method != 'GET' or path != '/api/profile': return await reject(401,'请先刷新个人空间')
                    # Use actual socket peer, never user-controlled forwarded headers.
                    peer = str(scope.get('client',('unknown',))[0])
                    key = hmac.new(self.secret,peer.encode(),hashlib.sha256).hexdigest()
                    if not await self.allowed('register',key): return await reject(429,'创建空间过于频繁')
                    value = self.signed()
                    owner = self.owner(value)
                    if not await anyio.to_thread.run_sync(self.store.reserve, owner): return await reject(503,'试用名额已满，请保留备份并稍后重试')
                    fresh = value
                scope.setdefault('state',{})['owner'] = owner
            # Valid server-signed session for fairness; shared anonymous limit otherwise.
            rate_key = owner or 'anonymous'
            if path.startswith('/api/') and path != '/api/health':
                if not await self.allowed('visitor',rate_key): return await reject(429,'请求过于频繁，请稍后重试')
                if path in ('/api/search','/api/online/search','/api/recommendations','/api/profile/notes/search','/api/profile/demands/save','/api/profile/report/preview') and not await self.allowed('expensive',rate_key):
                    return await reject(429,'搜索或推荐过于频繁')
                if request.method == 'POST' and not await self.allowed('write',rate_key):
                    return await reject(429,'偏好修改过于频繁')
            # Bound POSTs before Pydantic parses them, including chunked requests.
            if request.method not in ('GET','HEAD'):
                parts, size = [], 0
                try:
                    with anyio.fail_after(10):
                        while True:
                            message = await receive()
                            if message['type']=='http.disconnect': return
                            size += len(message.get('body',b''))
                            if size > 512*1024: return await reject(413,'请求不能超过 512 KiB')
                            parts.append(message.get('body',b''))
                            if not message.get('more_body',False): break
                except TimeoutError:
                    return await reject(408,'上传超时')
                body = b''.join(parts)
                delivered = False
                async def bounded_receive():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {'type':'http.request','body':body,'more_body':False}
                    return await receive()
                receive_app = bounded_receive
            else: receive_app = receive
            await self.app(scope, receive_app, secure_send)
        except sqlite3.OperationalError:
            return await reject(503,'偏好存储繁忙或已达到容量，请稍后重试')
        finally:
            self.active -= 1
