"""Bounded HTTP range diagnostic: never consume a full large response."""
import json
from pathlib import Path
import time
import requests


def main() -> None:
    path = Path('.cache/stage10/mirror')
    src = json.loads((path/'parquet-source.json').read_text())
    url = 'https://huggingface.co/datasets/secemp9/arxiv-complete/resolve/'+src['repo_revision']+'/metadata/train-00000-of-00001.parquet'
    started = time.perf_counter()
    with requests.get(url, headers={'Range':'bytes=0-65535'}, stream=True, timeout=(10,45)) as response:
        prefix = response.raw.read(64)
        result = {'status':response.status_code,'content_range':response.headers.get('Content-Range'),
                  'content_length':response.headers.get('Content-Length'),'first_bytes_hex':prefix[:8].hex(),
                  'elapsed_header_and64bytes':time.perf_counter()-started,'downloaded_bytes':64}
    (path/'range-diagnostic.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)


if __name__ == '__main__':
    main()
