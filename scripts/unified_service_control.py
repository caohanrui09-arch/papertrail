"""Owned hidden stage19 process; stage18 remains available unchanged."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
import urllib.error
import uuid

from .manage_stage17_env import BASE, VENV, environment
from .local_service_control import request

ROOT = Path('.cache/stage19').resolve()
STATE = ROOT / 'service.json'
MODULE = 'gsearch.unified_service'


def prepare() -> None:
    files = ['gsearch/unified_search.py', 'gsearch/unified_session.py', 'gsearch/unified_service.py']
    manifest = {}
    for name in files:
        source, target = Path(name), BASE / 'replica' / name
        if target.exists() and target.read_bytes() != source.read_bytes():
            previous = ROOT / 'previous-code' / (hashlib.sha256(target.read_bytes()).hexdigest() + '.py')
            previous.parent.mkdir(parents=True, exist_ok=True)
            if not previous.exists():
                shutil.copy2(target, previous)
        shutil.copy2(source, target)
        manifest[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    (ROOT / 'overlay.json').write_text(json.dumps(manifest, indent=2) + '\n')


def start(port: int) -> dict:
    ROOT.mkdir(parents=True, exist_ok=True)
    if STATE.exists():
        state = json.loads(STATE.read_text())
        if state['state'] != 'stopped':
            status, health = request('GET', '/health', port=state['port'])
            if status == 200 and health['instance_id'] == state['instance_id']:
                return {'state': 'already_running', **health}
            raise ValueError('Existing instance requires inspection')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    prepare()
    instance = str(uuid.uuid4())
    logs = ROOT / 'logs'; logs.mkdir(exist_ok=True)
    env = environment(); env['GSEARCH_SERVICE_INSTANCE'] = instance
    with (logs / (instance + '.out.log')).open('w', encoding='utf-8') as out, (logs / (instance + '.err.log')).open('w', encoding='utf-8') as err:
        process = subprocess.Popen([str(VENV / 'Scripts/python.exe'), '-E', '-s', '-u', '-m', MODULE, '--port', str(port)],
            cwd=BASE / 'replica', env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError('Service exited; inspect private stage19 logs')
        try:
            status, health = request('GET', '/health', port=port)
            if status == 200 and health['instance_id'] == instance:
                import psutil
                state = {'state': 'running', 'pid': health['pid'], 'port': port, 'instance_id': instance,
                         'created': psutil.Process(health['pid']).create_time()}
                STATE.write_text(json.dumps(state, indent=2) + '\n')
                return {'url': f'http://127.0.0.1:{port}', **health}
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(1)
    raise RuntimeError('Startup timeout; inspect owned process and private logs')


def stop() -> dict:
    import psutil
    state = json.loads(STATE.read_text())
    if state['state'] == 'stopped':
        return state
    try:
        process = psutil.Process(state['pid'])
        if abs(process.create_time() - state['created']) > .01 or MODULE not in process.cmdline() or not Path(process.exe()).resolve().is_relative_to(BASE):
            raise ValueError('Process ownership mismatch; refusing to terminate')
        process.terminate(); process.wait(timeout=15)
    except psutil.NoSuchProcess:
        pass
    state['state'] = 'stopped'
    STATE.write_text(json.dumps(state, indent=2) + '\n')
    return {'state': 'stopped', 'port': state['port']}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('start', 'status', 'stop'))
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        raise ValueError('Unprivileged port required')
    if args.action == 'start':
        result = start(args.port)
    elif args.action == 'stop':
        result = stop()
    elif not STATE.exists():
        result = {'state': 'not_started'}
    else:
        state = json.loads(STATE.read_text())
        if state['state'] == 'stopped':
            result = {'state': 'stopped'}
        else:
            status, result = request('GET', '/health', port=state['port'])
            if status != 200 or result['instance_id'] != state['instance_id']:
                raise ValueError('Instance ownership mismatch')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
