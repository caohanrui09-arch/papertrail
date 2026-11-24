"""Publish-readiness audit: what is safe to put on GitHub, what is not.

Read-only. Produces reports/stage86/publish-audit.json.
"""
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/stage86/publish-audit.json'
EXCLUDE_DIRS = {'.cache', 'data', 'runs', '__pycache__', 'node_modules', '.git', 'visitor-data'}
TEXT_EXT = {'.py', '.js', '.mjs', '.cjs', '.html', '.css', '.md', '.json', '.txt', '.cmd', '.in', '.lock', '.xml', '.csv'}
SECRET_PATTERNS = {
    'absolute_user_path': re.compile(r'C:\\\\?Users\\\\?[A-Za-z0-9_.-]+', re.I),
    'hf_token': re.compile(r'hf_[A-Za-z0-9]{20,}'),
    'openai_key': re.compile(r'sk-[A-Za-z0-9]{20,}'),
    'aws_key': re.compile(r'AKIA[0-9A-Z]{16}'),
    'private_key': re.compile(r'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY'),
    'session_key_path': re.compile(r'session\.key'),
    'password_assignment': re.compile(r'(?i)(password|passwd|secret)\s*[:=]\s*[\'"][^\'"]{6,}[\'"]'),
}


def walk(base: Path):
    for path in base.rglob('*'):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        yield path


def main() -> None:
    files = list(walk(ROOT))
    total = sum(p.stat().st_size for p in files)
    by_ext = {}
    for path in files:
        ext = path.suffix.lower() or '(none)'
        bucket = by_ext.setdefault(ext, {'files': 0, 'bytes': 0})
        bucket['files'] += 1
        bucket['bytes'] += path.stat().st_size

    findings = []
    for path in files:
        if path.suffix.lower() not in TEXT_EXT:
            continue
        try:
            text = path.read_text(encoding='utf8', errors='ignore')
        except OSError:
            continue
        for name, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count('\n', 0, match.start()) + 1
                findings.append({'kind': name, 'file': str(path.relative_to(ROOT)),
                                 'line': line, 'sample': match.group(0)[:60]})

    excluded = {}
    for name in ('data', '.cache', 'runs'):
        base = ROOT / name
        if base.is_dir():
            size = sum(p.stat().st_size for p in base.rglob('*') if p.is_file())
            count = sum(1 for p in base.rglob('*') if p.is_file())
            excluded[name] = {'files': count, 'bytes': size}

    gitignore = (ROOT / '.gitignore').read_text(encoding='utf8') if (ROOT / '.gitignore').exists() else ''
    licence_files = [str(p.relative_to(ROOT)) for p in ROOT.glob('*LICENSE*')] + \
                    [str(p.relative_to(ROOT)) for p in ROOT.glob('*NOTICES*')]

    result = {
        'publishable_tree': {
            'files': len(files),
            'bytes': total,
            'mb': round(total / 1e6, 1),
            'by_extension': dict(sorted(by_ext.items(), key=lambda kv: -kv[1]['bytes'])[:12]),
        },
        'excluded_private': excluded,
        'gitignore': gitignore.splitlines(),
        'licence_files': licence_files,
        'findings': findings,
        'finding_counts': {kind: sum(1 for f in findings if f['kind'] == kind) for kind in SECRET_PATTERNS},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: result[k] for k in ('publishable_tree', 'excluded_private', 'finding_counts')},
                     ensure_ascii=False, indent=2))
    print('licence files:', licence_files)
    print('gitignore:', result['gitignore'])


if __name__ == '__main__':
    main()
