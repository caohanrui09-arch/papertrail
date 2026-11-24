"""Read-only current local service and two real online metadata requests."""
import base64
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8791'


def main():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(path):
        with opener.open(BASE + path, timeout=45) as response:
            return response.read(), {key.lower(): value for key, value in response.headers.items()}
    raw, _ = get('/api/health')
    health = json.loads(raw)
    assert health['release'] == 'stage61'
    page, headers = get('/online.html')
    source = page.decode()
    mapping = re.search(r'<script type="importmap">(.*?)</script>', source).group(1)
    digest = base64.b64encode(hashlib.sha256(mapping.encode()).digest()).decode()
    assert 'sha256-' + digest in headers['content-security-policy']
    assets = {}
    for path in ['/online.mjs?v=61.1', '/online.css?v=61.1', '/vendor/preact.mjs', '/vendor/hooks.mjs', '/vendor/htm.mjs', '/papers.mjs?v=60.1', '/query-bridge.mjs?v=57.1']:
        body, _ = get(path)
        assets[path] = hashlib.sha256(body).hexdigest()
    old, _ = get('/')
    main_source, _ = get('/main.mjs?v=61.1')
    assert b'scholar.css' not in old and b'HeroArt' in main_source and '在线找论文' in main_source.decode()
    live = []
    for provider in ['arxiv', 'openalex']:
        started = time.perf_counter()
        body, _ = get('/api/online/search?' + urlencode({'provider': provider, 'q': 'multimodal fast slow thinking'}))
        data = json.loads(body)
        assert data['papers'] and data['source_parameters'] and data['source_endpoint'].startswith('https://')
        live.append({'provider': provider, 'count': len(data['papers']), 'total': data['total'], 'seconds': round(time.perf_counter() - started, 2), 'response_sha256': data['response_sha256'], 'source_parameters': data['source_parameters']})
    report = {'status': 'passed', 'release': health['release'], 'health': health, 'original_style_and_online_link_served': True, 'importmap_csp_matches': True, 'assets': assets, 'live': live, 'scope': 'HTTP assets and actual public metadata requests; no browser or real-feedback writes'}
    (ROOT / 'reports/stage61/service-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print({'release': health['release'], 'live': live})


if __name__ == '__main__':
    main()
