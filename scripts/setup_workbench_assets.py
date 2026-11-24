"""Copy audited browser distributions only; no npm lifecycle or Python installs."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request
from gsearch.quality_protocol import digest,save

DEST=Path('web/papertrail/dist/vendor')
PACKAGES={'preact':('11.1.0',{'dist/preact.mjs':'preact.mjs','hooks/dist/hooks.mjs':'hooks.mjs','LICENSE':'PREACT_LICENSE'}),
    'htm':('3.1.1',{'dist/htm.mjs':'htm.mjs','LICENSE':'HTM_LICENSE'})}


def main() -> None:
    lock=Path('reports/stage23/assets-lock.json')
    if lock.exists():
        values=json.loads(lock.read_text())
        for name,value in values['files'].items():
            if digest(Path(name))!=value:raise ValueError('Vendor asset changed')
        print('Audited local browser assets verified');return
    DEST.mkdir(parents=True,exist_ok=True)
    cache=Path('.cache/stage23/npm');cache.mkdir(parents=True,exist_ok=True)
    packages={}
    for name,(version,files) in PACKAGES.items():
        url=f'https://registry.npmjs.org/{name}/{version}'
        with urllib.request.urlopen(url,timeout=45) as response:metadata=json.load(response)
        archive_url=metadata['dist']['tarball']
        if not archive_url.startswith('https://registry.npmjs.org/'):raise ValueError('Official npm archive required')
        with urllib.request.urlopen(archive_url,timeout=45) as response:body=response.read()
        expected=metadata['dist']['integrity'];kind,encoded=expected.split('-',1)
        if kind!='sha512' or base64.b64encode(hashlib.sha512(body).digest()).decode()!=encoded:raise ValueError('npm integrity mismatch')
        (cache/f'{name}-{version}.tgz').write_bytes(body)
        save(cache/f'{name}-{version}.json',metadata)
        with tarfile.open(fileobj=io.BytesIO(body),mode='r:gz') as tar:
            for source,target in files.items():
                member=tar.getmember('package/'+source)
                if not member.isfile():raise ValueError('Plain package file required')
                (DEST/target).write_bytes(tar.extractfile(member).read())
        packages[name]={'version':version,'license':metadata['license'],'registry_url':url,
            'archive_url':archive_url,'integrity':expected,'git_head':metadata.get('gitHead'),'install_scripts_executed':False}
    save(lock,{'packages':packages,'files':{str(p):digest(p) for p in DEST.iterdir() if p.is_file()},
        'browser_runtime_external_requests_required':False,'shared_python_environment_changed':False})
    print(json.dumps({'packages':packages,'files':len(list(DEST.iterdir()))}),flush=True)


if __name__=='__main__':main()
