"""Launch fresh Python in the replica; deny old-workspace reads and any network."""
import json
import os
from pathlib import Path
import subprocess

from .manage_stage17_env import BASE, VENV, environment

GUARD = r'''
import json, os, runpy, sys
from pathlib import Path
isolation = Path(os.environ['GSEARCH_ISOLATION_ROOT']).resolve()
old_project = isolation.parent.parent
forbidden = (old_project.parent, Path(os.environ['GSEARCH_OLD_BASE_PYTHON']).resolve())
counts = {'application_file_opens': 0, 'old_root_read_attempts': 0, 'network_attempts': 0}
# Match the original project's isolated sklearn layout before Transformers can
# opportunistically import sklearn from the fresh virtualenv site-packages.
sys.path.insert(0, str((Path.cwd()/'.cache/stage11/deps').resolve()))
def audit(event, args):
    if event == 'socket.connect':
        counts['network_attempts'] += 1
        raise PermissionError('Network is disabled during isolated recommendation replay')
    if event == 'open' and isinstance(args[0], (str, bytes)):
        path = Path(os.fsdecode(args[0])).resolve()
        counts['application_file_opens'] += 1
        if not path.is_relative_to(isolation) and any(path.is_relative_to(root) for root in forbidden):
            counts['old_root_read_attempts'] += 1
            raise PermissionError('Old workspace/environment access is forbidden in relocated replay')
sys.addaudithook(audit)
sys.argv = ['gsearch.relocated_demo', '--output', 'data/relocated-run.json']
runpy.run_module('gsearch.relocated_demo', run_name='__main__')
if counts['old_root_read_attempts'] or counts['network_attempts']:
    raise RuntimeError('An attempted fallback escaped isolation, even if caught by a library')
proof = {**counts, 'audit_guard_enabled': True, 'old_workspace_reads_denied': True,
    'old_base_python_reads_denied': True, 'network_denied': True, 'user_site_disabled': True}
Path('data/isolated-io-proof.json').write_text(json.dumps(proof, indent=2)+'\n', encoding='utf-8')
'''


def main() -> None:
    root = BASE / 'replica'
    if (root / 'data/relocated-run.json').exists():
        raise ValueError('Refuse to overwrite completed isolated replay')
    env = environment()
    env['GSEARCH_ISOLATION_ROOT'] = str(BASE)
    import sys
    env['GSEARCH_OLD_BASE_PYTHON'] = sys.base_prefix
    logs = BASE / 'logs'; logs.mkdir(exist_ok=True)
    attempt = 0
    while (logs / f'replay-{attempt}.log').exists():
        attempt += 1
    path = logs / f'replay-{attempt}.log'
    with path.open('w', encoding='utf-8') as log:
        result = subprocess.run([str(VENV / 'Scripts/python.exe'), '-E', '-s', '-u', '-c', GUARD],
            cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
    print(json.dumps({'exit_code': result.returncode, 'log': str(path)}, ensure_ascii=False), flush=True)
    result.check_returncode()


if __name__ == '__main__':
    main()
