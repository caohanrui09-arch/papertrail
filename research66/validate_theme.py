"""Check monochrome assets, preserved services and live entry points."""
from pathlib import Path
import hashlib
import json
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    web = ROOT / 'deploy/stage66/web'
    checked = 0
    for path in web.rglob('*'):
        if not path.is_file() or 'vendor' in path.parts or path.suffix not in ('.css', '.svg', '.html', '.mjs'):
            continue
        text = path.read_text(encoding='utf8')
        for m in re.finditer(r'#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![\w-])', text):
            value = m[1]
            if len(value) in (3, 4):
                value = ''.join(c*2 for c in value)
            assert value[:2].lower() == value[2:4].lower() == value[4:6].lower(), (path, m[0])
        for m in re.finditer(r'\brgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)', text):
            assert m[1] == m[2] == m[3], (path, m[0])
        if path.suffix == '.html':
            assert '/monochrome.css?v=66.1' in text, path
        checked += 1
    unchanged = 0
    for path in (ROOT / 'deploy/stage61').rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        rel = path.relative_to(ROOT / 'deploy/stage61')
        if rel.parts[0] == 'web' or str(rel).replace('\\', '/') == 'trialsite/delivery.py':
            continue
        assert digest(path) == digest(ROOT / 'deploy/stage66' / rel), rel
        unchanged += 1
    frozen = {}
    launcher_changes = {'papertrail-workbench.cmd', 'project-agent.cmd'}
    for version in (61, 63):
        manifest = json.loads((ROOT / f'reports/stage{version}/final-validation.json').read_text())
        count = 0
        for filename, expected in manifest['files'].items():
            if filename.replace('\\', '/') in launcher_changes:
                continue
            assert digest(ROOT / filename) == expected, filename
            count += 1
        frozen[str(version)] = count
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    http = []
    for port, paths in [(8791, ['/', '/api/health', '/online.html', '/evidence.html', '/monochrome.css?v=66.1', '/main.mjs?v=66.1']), (8802, ['/', '/health', '/monochrome.css'])]:
        for path in paths:
            with opener.open(f'http://127.0.0.1:{port}{path}', timeout=10) as response:
                body = response.read().decode('utf8')
                assert response.status == 200
                if path in ('/api/health', '/health'):
                    assert json.loads(body)['status'] == 'ready'
                if path == '/':
                    assert '/monochrome.css' in body
                if path.startswith('/monochrome.css'):
                    assert 'background:#202020;color:#fff' in body
                http.append({'port': port, 'path': path, 'status': response.status})
    preserved = json.loads((ROOT / 'reports/stage66/preference-preservation.json').read_text())
    assert preserved['all_existing_namespaces_unchanged']
    result = {'status': 'passed', 'neutral_assets_checked': checked, 'unchanged_backend_files': unchanged, 'frozen_assets_unchanged_excluding_updated_root_launchers': frozen, 'http': http, 'private_data_preserved': True, 'browser_visual_verified': False, 'algorithm_changes': False}
    (ROOT / 'reports/stage66/validation.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
