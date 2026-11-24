"""Compare throughput between huggingface.co and hf-mirror.com before downloading."""
import time
import urllib.request

REV = 'aa8e72537993ba99e69dfaafa59ed015b17504d1'
NAME = 'model-00001-of-00002.safetensors'
BASES = {
    'huggingface': 'https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/resolve',
    'hf-mirror': 'https://hf-mirror.com/Qwen/Qwen2.5-3B-Instruct/resolve',
}

for label, base in BASES.items():
    url = f'{base}/{REV}/{NAME}'
    try:
        start = time.time()
        with urllib.request.urlopen(urllib.request.Request(url, headers={'Range': 'bytes=0-31457279'}), timeout=60) as response:
            received = len(response.read())
        elapsed = time.time() - start
        print(f'{label}: {received / 1e6:.1f} MB in {elapsed:.1f}s = {received / 1e6 / elapsed:.2f} MB/s', flush=True)
    except Exception as error:
        print(f'{label}: FAIL {type(error).__name__} {str(error)[:120]}', flush=True)
