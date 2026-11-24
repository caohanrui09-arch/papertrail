"""Verify official npm archive and vendor its prebuilt editor; no install scripts."""
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
import urllib.request


def main():
    out=Path('web/papertrail-v26/dist')
    cache=Path('.cache/stage26/npm');cache.mkdir(parents=True,exist_ok=True)
    meta=json.loads((cache/'metadata.json').read_text()) if (cache/'metadata.json').exists() else json.load(urllib.request.urlopen('https://registry.npmjs.org/@json-editor/json-editor/2.17.3',timeout=30))
    archive=(cache/'json-editor-2.17.3.tgz').read_bytes() if (cache/'json-editor-2.17.3.tgz').exists() else urllib.request.urlopen(meta['dist']['tarball'],timeout=60).read()
    integrity='sha512-'+base64.b64encode(hashlib.sha512(archive).digest()).decode()
    if integrity!=meta['dist']['integrity']:raise ValueError('Published archive integrity mismatch')
    (cache/'metadata.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    (cache/'json-editor-2.17.3.tgz').write_bytes(archive)
    if not out.exists():shutil.copytree('web/papertrail-v24/dist',out)
    else:
        for p in Path('web/papertrail-v24/dist').rglob('*'):
            if p.is_file() and p.read_bytes()!=(out/p.relative_to('web/papertrail-v24/dist')).read_bytes():
                raise ValueError('Existing UI differs; refuse overwrite')
    with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as tar:
        names=[m.name for m in tar.getmembers() if m.isfile()]
        chosen={'package/dist/jsoneditor.js':'jsoneditor.js','package/LICENSE':'JSON_EDITOR_LICENSE'}
        for name in names:
            if name.startswith('package/dist/') and name.endswith('LICENSE.txt'):
                chosen[name]=Path(name).name
        for name,target in chosen.items():
            member=tar.getmember(name)
            if not member.isfile() or member.size>5_000_000:raise ValueError('Unexpected archive member')
            destination=out/'vendor'/target;content=tar.extractfile(member).read()
            if destination.exists() and destination.read_bytes()!=content:raise ValueError('Refuse changed vendor asset')
            destination.write_bytes(content)
    report=Path('reports/stage26');report.mkdir(parents=True,exist_ok=True)
    files=[p for p in (out/'vendor').iterdir() if p.name.startswith(('jsoneditor','JSON_EDITOR'))]
    value={'component':'@json-editor/json-editor','version':meta['version'],'license':meta['license'],
        'git_head':meta.get('gitHead'),'archive_integrity':integrity,'archive_files':names,
        'lifecycle_scripts_executed':False,'files':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    (report/'editor-assets.json').write_text(json.dumps(value,indent=2),encoding='utf-8')
    print(json.dumps({'component':value['component'],'version':value['version'],'files':len(files),'bytes':sum(p.stat().st_size for p in files)}))


if __name__=='__main__':main()
