"""Vendor the constrained-decoding stack into .cache/decoder-deps (no system install).

lm-format-enforcer (MIT) needs pydantic; the GPU worker environment has none, so the
whole tiny stack is unpacked into an isolated directory and added to sys.path.
"""
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / '.cache/decoder-deps'

# (package, filename predicate)
PACKAGES = [
    ('lm-format-enforcer', lambda name: name.endswith('-none-any.whl')),
    ('interegular', lambda name: name.endswith('-none-any.whl')),
    ('pydantic', lambda name: name.endswith('-none-any.whl')),
    ('pydantic-core', lambda name: 'cp312' in name and 'win_amd64' in name),
    ('annotated-types', lambda name: name.endswith('-none-any.whl')),
    ('typing-extensions', lambda name: name.endswith('-none-any.whl')),
    ('typing-inspection', lambda name: name.endswith('-none-any.whl')),
]


def pick(name: str, predicate) -> tuple[str, str]:
    with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/json', timeout=30) as response:
        data = json.loads(response.read())
    candidates = [entry for entry in data['urls'] if entry['filename'].endswith('.whl') and predicate(entry['filename'])]
    if not candidates:
        raise SystemExit(f'no matching wheel for {name}')
    entry = candidates[0]
    return entry['filename'], entry['url']


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, predicate in PACKAGES:
        filename, url = pick(name, predicate)
        with urllib.request.urlopen(url, timeout=120) as response:
            blob = response.read()
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            archive.extractall(TARGET)
        print(f'{name}: {filename} ({len(blob)} bytes)')
    sys.path.insert(0, str(TARGET))
    import lmformatenforcer
    from lmformatenforcer import JsonSchemaParser, build_transformers_prefix_allowed_tokens_fn
    print('lmformatenforcer', getattr(lmformatenforcer, '__version__', '?'), 'ok')


if __name__ == '__main__':
    main()

