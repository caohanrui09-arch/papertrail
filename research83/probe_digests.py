"""Inspect how the hub exposes shard digests for the pinned revision."""
import json
import urllib.request

REPO = 'Qwen/Qwen2.5-3B-Instruct'
REV = 'aa8e72537993ba99e69dfaafa59ed015b17504d1'

for suffix in ('', '?blobs=true'):
    url = f'https://huggingface.co/api/models/{REPO}/revision/{REV}{suffix}'
    with urllib.request.urlopen(url, timeout=60) as response:
        info = json.loads(response.read())
    print('---', suffix or '(plain)')
    for sibling in info.get('siblings', []):
        if sibling['rfilename'].endswith('.safetensors'):
            print(json.dumps(sibling, ensure_ascii=False)[:400])

request = urllib.request.Request(
    f'https://huggingface.co/{REPO}/resolve/{REV}/model-00001-of-00002.safetensors', method='HEAD')
with urllib.request.urlopen(request, timeout=60) as response:
    print('--- HEAD headers')
    for key in ('x-linked-etag', 'etag', 'content-length', 'x-linked-size'):
        print(key, '=', response.headers.get(key))
