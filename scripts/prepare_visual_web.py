"""Prepare separate v33 assets; download only pinned official Anime.js files."""
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

REVISION = '01b81be1df6843ccfe0a71c0699a746bf740dd77'


def main() -> None:
    out = Path('web/papertrail-v33/dist/vendor')
    out.mkdir(parents=True, exist_ok=True)
    for path in Path('web/papertrail-v32/dist/vendor').iterdir():
        target = out / path.name
        if target.exists():
            assert target.read_bytes() == path.read_bytes()
        else:
            shutil.copyfile(path, target)
    receipt = []
    for source, filename, blob in [
        ('dist/bundles/anime.esm.min.js', 'anime.esm.min.js', 'c278b15616623e2b32ef499bbb1020b181324d59'),
        ('LICENSE.md', 'ANIME_LICENSE.md', 'f999fa58ebdda6d8d0f3ae581ebdfe821f09603a'),
    ]:
        url = f'https://raw.githubusercontent.com/juliangarnier/anime/{REVISION}/{source}'
        target = out / filename
        if target.exists():
            raw = target.read_bytes()
        else:
            with urllib.request.urlopen(url, timeout=40) as response:
                raw = response.read()
        assert hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest() == blob
        if not target.exists():
            target.write_bytes(raw)
        receipt.append({'path': str(target), 'url': url, 'git_blob': blob,
                        'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    folder = Path('reports/stage33')
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'vendor-source.json').write_text(json.dumps({'version': '4.5.0', 'commit': REVISION,
        'license': 'MIT', 'files': receipt}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'prepared': True, 'anime_bytes': receipt[0]['bytes'], 'git_blobs_verified': True}))


if __name__ == '__main__':
    main()
