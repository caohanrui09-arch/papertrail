"""Direct streaming fetch for the two 3B shards (huggingface_hub stalled on this host).

Range-probes throughput first, then streams each shard with progress, and hashes it.
"""
import hashlib
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / '.cache/models/Qwen2.5-3B-Instruct'
REV = 'aa8e72537993ba99e69dfaafa59ed015b17504d1'
BASE = f'https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/resolve/{REV}'
SHARDS = ['model-00001-of-00002.safetensors', 'model-00002-of-00002.safetensors']


def probe() -> float:
    request = urllib.request.Request(f'{BASE}/{SHARDS[0]}', headers={'Range': 'bytes=0-20971519'})
    start = time.time()
    with urllib.request.urlopen(request, timeout=60) as response:
        received = len(response.read())
    elapsed = time.time() - start
    print(f'probe: {received / 1e6:.1f} MB in {elapsed:.1f}s = {received / 1e6 / elapsed:.1f} MB/s', flush=True)
    return received / 1e6 / elapsed


def fetch(name: str) -> None:
    destination = TARGET / name
    if destination.exists() and destination.stat().st_size > 1_000_000_000:
        print(f'{name} already present ({destination.stat().st_size} bytes)', flush=True)
        return
    part = destination.with_suffix(destination.suffix + '.part')
    digest = hashlib.sha256()
    start = time.time()
    received = 0
    with urllib.request.urlopen(urllib.request.Request(f'{BASE}/{name}'), timeout=120) as response, part.open('wb') as stream:
        while True:
            block = response.read(8 * 1024 * 1024)
            if not block:
                break
            stream.write(block)
            digest.update(block)
            received += len(block)
            if received % (512 * 1024 * 1024) < 8 * 1024 * 1024:
                rate = received / 1e6 / max(time.time() - start, 1e-9)
                print(f'  {name}: {received / 1e9:.2f} GB, {rate:.1f} MB/s', flush=True)
    part.replace(destination)
    print(f'{name}: {received} bytes sha256={digest.hexdigest()} in {time.time() - start:.0f}s', flush=True)


if __name__ == '__main__':
    TARGET.mkdir(parents=True, exist_ok=True)
    rate = probe()
    if rate < 0.5:
        raise SystemExit(f'throughput too low: {rate:.2f} MB/s')
    for shard in SHARDS:
        fetch(shard)
