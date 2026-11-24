"""Project-local uv orchestration; no registry, PATH, shared env or user-site writes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

BASE = Path('.cache/stage17').resolve()
UV = BASE / 'bootstrap/uv.exe'
VENV = BASE / 'runtime'


def environment() -> dict:
    env = os.environ.copy()
    for name in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'CONDA_PREFIX'):
        env.pop(name, None)
    env.update(UV_CACHE_DIR=str(BASE / 'uv-cache'), UV_PYTHON_INSTALL_DIR=str(BASE / 'python'),
               UV_NO_CONFIG='true', UV_SYSTEM_CERTS='true', PYTHONNOUSERSITE='1',
               OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
    proxies = urllib.request.getproxies()
    for scheme in ('http', 'https'):
        if scheme in proxies:
            env[scheme.upper() + '_PROXY'] = proxies[scheme]
    return env


def run(args: list[str]) -> None:
    receipt = json.loads(Path('reports/stage17/bootstrap-source.json').read_text())
    if hashlib.sha256(UV.read_bytes()).hexdigest() != receipt['executable_sha256']:
        raise ValueError('Audited uv executable changed')
    print(json.dumps({'uv_command': args}, ensure_ascii=False), flush=True)
    logs = BASE / 'logs'; logs.mkdir(parents=True, exist_ok=True)
    log = logs / ('uv-' + '-'.join(args[:2]) + '.log')
    with log.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'command': args}) + '\n'); stream.flush()
        result = subprocess.run([str(UV), *args], env=environment(), stdout=stream, stderr=subprocess.STDOUT)
    print(json.dumps({'exit_code': result.returncode, 'log': str(log)}), flush=True)
    result.check_returncode()


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument('--phase', choices=('python', 'venv', 'lock', 'target-lock', 'install', 'target'), required=True)
    args = parser.parse_args()
    if args.phase == 'python':
        run(['python', 'install', '3.12.3', '--no-bin', '--no-registry', '--managed-python', '--no-config'])
    elif args.phase == 'venv':
        if VENV.exists():
            raise ValueError('Fresh venv already exists; do not replace it')
        candidates = list((BASE / 'python').glob('cpython-3.12.3-windows-x86_64-none/python.exe'))
        if len(candidates) != 1:
            raise ValueError('Expected one independently installed managed Python3.12.3')
        run(['venv', str(VENV), '--python', str(candidates[0]), '--no-config', '--no-python-downloads'])
    elif args.phase == 'lock':
        path = Path('reports/stage17/requirements-win-cpu.lock')
        if path.exists():
            raise ValueError('Dependency resolution already locked')
        run(['pip', 'compile', 'requirements-stage17.in', '--python', str(VENV / 'Scripts/python.exe'),
             '--generate-hashes', '--only-binary', ':all:', '--default-index', 'https://pypi.org/simple',
             '--output-file', str(path), '--no-config'])
    elif args.phase == 'target-lock':
        path = Path('reports/stage17/sklearn-target.lock')
        if path.exists():
            raise ValueError('Target requirements already locked')
        run(['pip', 'compile', 'requirements-stage17-sklearn.in', '--python', str(VENV / 'Scripts/python.exe'),
             '--no-deps', '--generate-hashes', '--only-binary', ':all:', '--default-index', 'https://pypi.org/simple',
             '--output-file', str(path), '--no-config'])
    elif args.phase == 'install':
        run(['pip', 'sync', 'reports/stage17/requirements-win-cpu.lock', '--python', str(VENV / 'Scripts/python.exe'),
             '--require-hashes', '--only-binary', ':all:', '--default-index', 'https://pypi.org/simple', '--no-config'])
    else:
        target = BASE / 'replica/.cache/stage11/deps'
        run(['pip', 'install', '--target', str(target), '--python', str(VENV / 'Scripts/python.exe'),
             '--require-hashes', '--no-deps', '--only-binary', ':all:', '-r', 'reports/stage17/sklearn-target.lock', '--no-config'])


if __name__ == '__main__':
    main()
