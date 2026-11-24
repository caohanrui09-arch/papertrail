"""Download Qwen2.5-3B-Instruct at a pinned revision, hash every file, keep the licence.

Stage83 model-capability comparison. The 3B repo is under the Qwen Research Licence
(not Apache-2.0), so weights stay local and are never added to a distributable package.
"""
import datetime
import hashlib
import json
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / '.cache/models/Qwen2.5-3B-Instruct'
REPO = 'Qwen/Qwen2.5-3B-Instruct'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    api = HfApi()
    info = api.model_info(REPO)
    card = info.cardData.to_dict() if info.cardData else {}
    print(json.dumps({'repo': REPO, 'sha': info.sha, 'license': card.get('license'),
                      'license_name': card.get('license_name'), 'gated': info.gated}, ensure_ascii=False))
    snapshot_download(REPO, revision=info.sha, local_dir=str(TARGET),
                      allow_patterns=['*.json', '*.safetensors', '*.txt', 'LICENSE'])
    files = []
    for path in sorted(TARGET.iterdir()):
        if path.is_file() and path.name != 'source.json':
            files.append({'file': path.name, 'sha256': sha256(path), 'bytes': path.stat().st_size})
            print(f'{path.name} {path.stat().st_size} {files[-1]["sha256"][:16]}')
    (TARGET / 'source.json').write_text(json.dumps({
        'repo': REPO, 'revision': info.sha,
        'license': card.get('license'), 'license_name': card.get('license_name'),
        'downloaded_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'local_only': True, 'redistribute': False,
        'files': files,
    }, ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
