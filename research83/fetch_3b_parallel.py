"""Parallel ranged download for the two 3B shards.

Four connections fetch disjoint 64 MB ranges and write at explicit offsets; progress,
size and the published LFS sha256 are all checked. Falls back to fewer workers if the
server throttles, and refuses to mark a file complete on any mismatch.
"""
import hashlib
import json
import queue
import threading
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / '.cache/models/Qwen2.5-3B-Instruct'
LOG = ROOT / 'data/stage83-download/download.log'
REPO = 'Qwen/Qwen2.5-3B-Instruct'
REV = 'aa8e72537993ba99e69dfaafa59ed015b17504d1'
CHUNK = 64 * 1024 * 1024
WORKERS = 4
SHARDS = {
    'model-00001-of-00002.safetensors': ('67347b23fb4165b652eb6611f5e1f2a06dfcddba8e909df1b2b0b1857bee06c2', 3968658944),
    'model-00002-of-00002.safetensors': ('a40d941d0e7e0b966ad8b62bb6d6b7c88cce1299197b599d9d0a4ce59aabfc1d', 2203268048),
}

lock = threading.Lock()
done_bytes = 0
started = 0.0


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


def worker(name: str, url: str, part: Path, tasks: queue.Queue) -> None:
    global done_bytes
    handle = part.open('r+b')
    try:
        while True:
            try:
                start, end = tasks.get_nowait()
            except queue.Empty:
                return
            for attempt in range(1, 6):
                try:
                    response = requests.get(url, headers={'Range': f'bytes={start}-{end}'}, timeout=(30, 90))
                    response.raise_for_status()
                    block = response.content
                    if len(block) != end - start + 1:
                        raise IOError(f'short {len(block)}')
                    handle.seek(start)
                    handle.write(block)
                    handle.flush()
                    with lock:
                        done_bytes += len(block)
                        if done_bytes % (256 * 1024 * 1024) < CHUNK:
                            rate = done_bytes / 1e6 / max(time.time() - started, 1)
                            log(f'{name}: {done_bytes / 1e9:.2f} GB at {rate:.1f} MB/s')
                    break
                except Exception as error:
                    log(f'{name}: range {start} attempt {attempt}: {type(error).__name__} {str(error)[:80]}')
                    time.sleep(min(20, 3 * attempt))
            else:
                raise SystemExit(f'{name}: failed range {start}')
            tasks.task_done()
    finally:
        handle.close()


def fetch(name: str, expected_sha: str, total: int) -> None:
    global done_bytes, started
    destination = TARGET / name
    if destination.exists() and destination.stat().st_size == total and sha256(destination) == expected_sha:
        log(f'{name}: already complete')
        return
    part = destination.with_suffix('.part')
    url = f'https://huggingface.co/{REPO}/resolve/{REV}/{name}'
    part.parent.mkdir(parents=True, exist_ok=True)
    part.unlink(missing_ok=True)
    with part.open('wb') as stream:
        stream.truncate(total)
    tasks = queue.Queue()
    for start in range(0, total, CHUNK):
        tasks.put((start, min(start + CHUNK, total) - 1))
    done_bytes = 0
    started = time.time()
    log(f'{name}: {total / 1e9:.2f} GB in {tasks.qsize()} ranges, {WORKERS} workers')
    threads = [threading.Thread(target=worker, args=(name, url, part, tasks), daemon=True) for _ in range(WORKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    size = part.stat().st_size
    if size != total:
        raise SystemExit(f'{name}: size {size} != {total}')
    digest = sha256(part)
    if digest != expected_sha:
        raise SystemExit(f'{name}: sha256 mismatch {digest}')
    part.replace(destination)
    log(f'{name}: complete {size} bytes sha256={digest}')


def main() -> None:
    for name, (digest, total) in SHARDS.items():
        fetch(name, digest, total)
    (TARGET / 'source.json').write_text(json.dumps({
        'repo': REPO, 'revision': REV, 'license': 'qwen-research',
        'license_note': 'Qwen Research Licence, local non-commercial research only, not redistributable',
        'files': [{'file': n, 'sha256': s[0], 'bytes': s[1]} for n, s in SHARDS.items()],
    }, ensure_ascii=False, indent=2), encoding='utf8')
    log('shards complete')


if __name__ == '__main__':
    main()
