"""Resumable 3B shard fetch using requests streaming.

1 MB chunks, 30 s read timeout, resume from .part, sha256 verified against the
hub's published LFS digest. Progress every 64 MB so a stall is visible.
"""
import hashlib
import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / '.cache/models/Qwen2.5-3B-Instruct'
LOG = ROOT / 'data/stage83-download/download.log'
REPO = 'Qwen/Qwen2.5-3B-Instruct'
REV = 'aa8e72537993ba99e69dfaafa59ed015b17504d1'
SHARDS = ['model-00001-of-00002.safetensors', 'model-00002-of-00002.safetensors']
CHUNK = 1024 * 1024

# Read from the hub API at run time; these pinned values are the recorded fallback
# used if the metadata call hits a transient TLS error.
FALLBACK = {
    'model-00001-of-00002.safetensors': {
        'sha256': '67347b23fb4165b652eb6611f5e1f2a06dfcddba8e909df1b2b0b1857bee06c2',
        'bytes': 3968658944},
    'model-00002-of-00002.safetensors': {
        'sha256': 'a40d941d0e7e0b966ad8b62bb6d6b7c88cce1299197b599d9d0a4ce59aabfc1d',
        'bytes': 2203268048},
}


def log(message: str) -> None:
    line = f'{time.strftime("%H:%M:%S")} {message}'
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a', encoding='utf8') as stream:
        stream.write(line + '\n')


def digests() -> dict:
    for attempt in range(1, 4):
        try:
            response = requests.get(f'https://huggingface.co/api/models/{REPO}/revision/{REV}?blobs=true', timeout=60)
            response.raise_for_status()
            out = {}
            for sibling in response.json().get('siblings', []):
                lfs = sibling.get('lfs') or {}
                out[sibling['rfilename']] = {'sha256': lfs.get('sha256'), 'bytes': lfs.get('size')}
            log('digests: from hub api')
            return out
        except Exception as error:
            log(f'digests: attempt {attempt} failed {type(error).__name__}; using pinned fallback')
            time.sleep(3 * attempt)
    return dict(FALLBACK)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def fetch(name: str, expected: dict) -> None:
    destination = TARGET / name
    part = destination.with_suffix(destination.suffix + '.part')
    if destination.exists() and expected['sha256'] and sha256(destination) == expected['sha256']:
        log(f'{name}: already complete')
        return
    url = f'https://huggingface.co/{REPO}/resolve/{REV}/{name}'
    for attempt in range(1, 12):
        start_size = part.stat().st_size if part.exists() else 0
        if expected['bytes'] and start_size > expected['bytes']:
            log(f'{name}: partial larger than expected, discarding')
            part.unlink(missing_ok=True)
            start_size = 0
        log(f'{name}: attempt {attempt} from {start_size / 1e6:.0f} MB')
        try:
            headers = {'Range': f'bytes={start_size}-'} if start_size else {}
            with requests.get(url, headers=headers, stream=True, timeout=(30, 30)) as response:
                response.raise_for_status()
                if start_size and response.status_code != 206:
                    # Server ignored the range: restart this shard instead of appending.
                    log(f'{name}: server returned {response.status_code}, restarting from 0')
                    response.close()
                    part.unlink(missing_ok=True)
                    continue
                received = start_size
                marked = received
                with part.open('ab') as stream:
                    for block in response.iter_content(CHUNK):
                        if not block:
                            continue
                        stream.write(block)
                        received += len(block)
                        if received - marked >= 64 * 1024 * 1024:
                            log(f'{name}: {received / 1e9:.2f} GB')
                            marked = received
            size = part.stat().st_size
            if expected['bytes'] and size != expected['bytes']:
                log(f'{name}: size {size} != {expected["bytes"]}, resuming')
                continue
            digest = sha256(part)
            if expected['sha256'] and digest != expected['sha256']:
                log(f'{name}: sha256 mismatch, discarding partial')
                part.unlink(missing_ok=True)
                continue
            part.replace(destination)
            log(f'{name}: complete {size} bytes sha256={digest}')
            return
        except Exception as error:
            log(f'{name}: attempt {attempt} failed: {type(error).__name__} {str(error)[:120]}')
            time.sleep(min(60, 5 * attempt))
    if not destination.exists():
        raise SystemExit(f'{name}: giving up')


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    log('resume shards')
    table = digests()
    for name in SHARDS:
        expected = table.get(name) or {}
        if not expected.get('sha256'):
            raise SystemExit(f'no digest for {name}')
        fetch(name, expected)
    log('shards complete')
    (TARGET / 'source.json').write_text(json.dumps({
        'repo': REPO, 'revision': REV, 'license': 'qwen-research',
        'license_note': 'Qwen Research Licence, local non-commercial research only, not redistributable',
        'files': [{'file': n, 'sha256': (table.get(n) or {}).get('sha256')} for n in SHARDS],
    }, ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
