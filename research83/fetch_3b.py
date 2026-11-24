"""Resilient stage-83 upward-arm fetch for Qwen2.5-3B-Instruct.

- pinned revision, licence recorded (Qwen Research Licence: local research only)
- resumable shards via HTTP Range, retry with backoff, sha256 verified against the
  hub's published LFS digest
- never marks a file complete unless size and hash match
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / '.cache/models/Qwen2.5-3B-Instruct'
LOG = ROOT / 'data/stage83-download/download.log'
REPO = 'Qwen/Qwen2.5-3B-Instruct'
REV = 'aa8e72537993ba99e69dfaafa59ed015b17504d1'
SMALL = ['config.json', 'generation_config.json', 'merges.txt', 'model.safetensors.index.json',
         'tokenizer.json', 'tokenizer_config.json', 'vocab.json', 'LICENSE']
SHARDS = ['model-00001-of-00002.safetensors', 'model-00002-of-00002.safetensors']
CHUNK = 8 * 1024 * 1024


def log(message: str) -> None:
    line = f'{time.strftime("%H:%M:%S")} {message}'
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a', encoding='utf8') as stream:
        stream.write(line + '\n')


def digests() -> dict:
    # `?blobs=true` is what exposes lfs.sha256 for the weight shards.
    url = f'https://huggingface.co/api/models/{REPO}/revision/{REV}?blobs=true'
    with urllib.request.urlopen(url, timeout=60) as response:
        info = json.loads(response.read())
    out = {}
    for sibling in info.get('siblings', []):
        lfs = sibling.get('lfs') or {}
        out[sibling['rfilename']] = {'sha256': lfs.get('sha256'), 'bytes': lfs.get('size') or sibling.get('size')}
    return out


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(CHUNK), b''):
            digest.update(block)
    return digest.hexdigest()


def fetch(name: str, expected: dict) -> None:
    destination = TARGET / name
    if destination.exists() and expected['sha256'] and sha256(destination) == expected['sha256']:
        log(f'{name}: already complete')
        return
    part = destination.with_suffix(destination.suffix + '.part')
    for attempt in range(1, 6):
        start_size = part.stat().st_size if part.exists() else 0
        headers = {'Range': f'bytes={start_size}-'} if start_size else {}
        url = f'https://huggingface.co/{REPO}/resolve/{REV}/{name}'
        log(f'{name}: attempt {attempt} from {start_size / 1e6:.0f} MB')
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=120) as response, part.open('ab') as stream:
                received = start_size
                last = time.time()
                while True:
                    block = response.read(CHUNK)
                    if not block:
                        break
                    stream.write(block)
                    received += len(block)
                    if received - last >= 512 * 1024 * 1024:
                        log(f'{name}: {received / 1e9:.2f} GB at {(received - start_size) / 1e6 / (time.time() - last):.1f} MB/s')
                        last = received
            size = part.stat().st_size
            if expected['bytes'] and size != expected['bytes']:
                log(f'{name}: size mismatch {size} != {expected["bytes"]}')
                continue
            digest = sha256(part)
            if expected['sha256'] and digest != expected['sha256']:
                log(f'{name}: sha256 mismatch, deleting partial')
                part.unlink(missing_ok=True)
                continue
            part.replace(destination)
            log(f'{name}: complete {size} bytes sha256={digest}')
            return
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            log(f'{name}: attempt {attempt} failed: {type(error).__name__} {str(error)[:120]}')
            time.sleep(min(60, 5 * attempt))
    raise SystemExit(f'{name}: giving up after retries')


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    log(f'start {REPO}@{REV}')
    table = digests()
    for name in SMALL + SHARDS:
        expected = table.get(name) or {}
        if not expected.get('sha256') and name in SHARDS:
            raise SystemExit(f'no published digest for {name}')
        fetch(name, expected)
    (TARGET / 'source.json').write_text(json.dumps({
        'repo': REPO, 'revision': REV, 'license': 'qwen-research',
        'license_note': 'Qwen Research Licence, local non-commercial research only, not redistributable',
        'downloaded_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'files': [{'file': name, 'sha256': (table.get(name) or {}).get('sha256')} for name in SMALL + SHARDS],
    }, ensure_ascii=False, indent=2), encoding='utf8')
    log('all files complete')


if __name__ == '__main__':
    main()
