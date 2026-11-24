"""Fetch only the audited official uv release; verify before any executable use."""
import hashlib
import argparse
import json
from pathlib import Path
import urllib.request
import zipfile


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument('--direct', action='store_true')
    args = parser.parse_args()
    audit = json.loads(Path('reports/stage17/upstream-audit.json').read_text(encoding='utf-8'))
    asset = audit['choice']['release_asset']
    folder = Path('.cache/stage17/bootstrap'); folder.mkdir(parents=True, exist_ok=True)
    archive = folder / asset['name']
    if not archive.exists():
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if args.direct else urllib.request.build_opener()
        request = urllib.request.Request(asset['url'], headers={'User-Agent': 'generative-search-agent-isolated-reproduction'})
        with opener.open(request, timeout=90) as source, archive.open('xb') as target:
            while block := source.read(1024 * 1024):
                target.write(block)
    data = archive.read_bytes()
    if len(data) != asset['bytes'] or hashlib.sha256(data).hexdigest() != asset['sha256']:
        raise ValueError('Official uv release archive does not match fixed size/hash; preserve failure')
    destination = folder / 'uv.exe'
    with zipfile.ZipFile(archive) as bundle:
        entries = [item for item in bundle.infolist() if item.filename.replace('\\', '/').split('/')[-1] == 'uv.exe']
        if len(entries) != 1 or entries[0].file_size > 100_000_000:
            raise ValueError('Unexpected uv binary archive layout')
        binary = bundle.read(entries[0])
        if destination.exists() and destination.read_bytes() != binary:
            raise ValueError('Existing local uv differs; do not overwrite')
        if not destination.exists():
            destination.write_bytes(binary)
    receipt = {'version': audit['choice']['version'], 'source_url': asset['url'],
        'archive_sha256': asset['sha256'], 'executable_sha256': hashlib.sha256(binary).hexdigest(),
        'bytes': len(binary), 'tls_verification': True,
        'proxy_route': 'process-local direct' if args.direct else 'existing configured proxy; no system changes'}
    Path('reports/stage17/bootstrap-source.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'uv_executable': str(destination), 'sha256_verified': True}), flush=True)


if __name__ == '__main__':
    main()
