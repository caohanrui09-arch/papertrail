"""Diagnose a stalled shard request: status, redirect target, first bytes."""
import time
import urllib.request

REV = 'aa8e72537993ba99e69dfaafa59ed015b17504d1'
NAME = 'model-00001-of-00002.safetensors'
URL = f'https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/resolve/{REV}/{NAME}'

start = time.time()
request = urllib.request.Request(URL, headers={'Range': 'bytes=0-8388607'})
with urllib.request.urlopen(request, timeout=60) as response:
    print('status', response.status, 'final_url', response.url[:120], 'len', response.headers.get('content-length'), flush=True)
    total = 0
    while total < 2 * 1024 * 1024:
        block = response.read(256 * 1024)
        if not block:
            break
        total += len(block)
print(f'read {total / 1e6:.1f} MB in {time.time() - start:.1f}s = {total / 1e6 / (time.time() - start):.2f} MB/s')
