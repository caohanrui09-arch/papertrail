"""Chunked, verified 3B shard download.

Each 32 MB ranged request is written at an explicit offset, then the on-disk size is
checked. No append-mode: a mismatch aborts loudly instead of silently wasting an hour.
"""
import hashlib
import json
import os
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / '.cache/models/Qwen2.5-3B-Instruct'
LOG = ROOT / 'data/stage83-download/download.log'
REPO = 'Qwen/Qwen2.5-3B-Instruct'
REV = 'aa8e72537993ba99e69dfaafa59ed015b17504d1'
CHUNK = 32 * 1024 * 1024
SHARDS = {
    'model-00001-of-00002.safetensors': ('67347b23fb4165b652eb6611f5e1f2a06dfcddba8e909df1b2b0b1857bee06c2', 3968658944),
    'model-00002-of-00002.safetensors': ('a40d941d0e7e0b966ad8b62bb6d6b7c88cce1299197b599d9d0a4ce59aabfc1d', 2203268048),
}


def log(message: str) -> None:
    line = f'{time.strftime("%H:%M:%S")} {message}'
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a', encoding='utf8') as stream:
        stream.write(line + '\n')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def fetch(name: str, expected_sha: str, total: int) -> None:
    destination = TARGET / name
    if destination.exists() and destination.stat().st_size == total and sha256(destination) == expected_sha:
        log(f'{name}: already complete')
        return
    part = destination.with_suffix('.part')
    url = f'https://huggingface.co/{REPO}/resolve/{REV}/{name}'
    part.parent.mkdir(parents=True, exist_ok=True)
    with part.open('wb') as stream:
        offset = 0
        started = time.time()
        while offset < total:
            for attempt in range(1, 6):
                try:
                    end = min(offset + CHUNK, total) - 1
                    response = requests.get(url, headers={'Range': f'bytes={offset}-{end}'}, timeout=(30, 60))
                    response.raise_for_status()
                    block = response.content
                    if len(block) != end - offset + 1:
                        raise IOError(f'short chunk {len(block)} != {end - offset + 1}')
                    stream.seek(offset)
                    stream.write(block)
                    stream.flush()
                    offset += len(block)
                    break
                except Exception as error:
                    log(f'{name}: chunk at {offset / 1e6:.0f} MB attempt {attempt} failed: {type(error).__name__} {str(error)[:90]}')
                    time.sleep(min(30, 4 * attempt))
            else:
                raise SystemExit(f'{name}: stuck at {offset} bytes')
            size = part.stat().st_size
            if size < offset:
                raise SystemExit(f'{name}: on-disk size {size} < written {offset}')
            if offset % (256 * 1024 * 1024) < CHUNK:
                rate = offset / 1e6 / (time.time() - started)
                log(f'{name}: {offset / 1e9:.2f}/{total / 1e9:.2f} GB at {rate:.1f} MB/s')
    size = part.stat().st_size
    if size != total:
        raise SystemExit(f'{name}: final size {size} != {total}')
    digest = sha256(part)
    if digest != expected_sha:
        raise SystemExit(f'{name}: sha256 mismatch {digest}')
    part.replace(destination)
    log(f'{name}: complete {size} bytes sha256={digest}')


def main() -> None:
    for name, (expected_sha, total) in SHARDS.items():
        fetch(name, expected_sha, total)
    (TARGET / 'source.json').write_text(json.dumps({
        'repo': REPO, 'revision': REV, 'license': 'qwen-research',
        'license_note': 'Qwen Research Licence, local non-commercial research only, not redistributable',
        'files': [{'file': n, 'sha256': s[0], 'bytes': s[1]} for n, s in SHARDS.items()],
    }, ensure_ascii=False, indent=2), encoding='utf8')
    log('shards complete')


if __name__ == '__main__':
    main()
