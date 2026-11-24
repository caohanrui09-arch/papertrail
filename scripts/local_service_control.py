"""Start/status/stop the owned loopback service; hidden window and private logs."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid

from .manage_stage17_env import BASE, VENV, environment

STATE = Path('.cache/stage18/service.json')
ROOT = Path('.cache/stage18').resolve()


def request(method: str, path: str, data: dict | None = None, port: int = 8765) -> tuple[int, dict]:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(f'http://127.0.0.1:{port}' + path, data=body, method=method,
        headers={'Content-Type': 'application/json'} if body is not None else {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=30) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def prepare_overlay() -> None:
    source = Path('gsearch/local_service.py'); target = BASE / 'replica/gsearch/local_service.py'
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    if target.exists() and target.read_bytes() != source.read_bytes():
        previous = ROOT / 'previous-code' / (hashlib.sha256(target.read_bytes()).hexdigest() + '.py')
        previous.parent.mkdir(parents=True, exist_ok=True)
        if not previous.exists(): shutil.copy2(target, previous)
    shutil.copy2(source, target)
    manifest = {'code_sha256': expected, 'source': str(source), 'target_inside_relocated_bundle': True,
        'stage17_manifest_unchanged': True, 'service_lock_sha256': hashlib.sha256(Path('reports/stage18/requirements-service.lock').read_bytes()).hexdigest()}
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'service-overlay.json').write_text(json.dumps(manifest, indent=2) + '\n')


def start(port: int) -> dict:
    ROOT.mkdir(parents=True, exist_ok=True)
    if STATE.exists():
        previous = json.loads(STATE.read_text())
        if previous.get('state') != 'stopped':
            code, health = request('GET', '/health', port=previous['port'])
            if code == 200 and health['instance_id'] == previous['instance_id']:
                return {'state': 'already_running', 'url': f"http://127.0.0.1:{previous['port']}", 'pid': health['pid']}
            raise ValueError('Existing service state needs inspection; do not replace an unknown process')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    prepare_overlay()
    instance = str(uuid.uuid4()); logs = ROOT / 'logs'; logs.mkdir(exist_ok=True)
    env = environment()
    env.update(GSEARCH_SERVICE_INSTANCE=instance, GSEARCH_RUNTIME_PYTHON=str(VENV / 'Scripts/python.exe'),
        GSEARCH_BUNDLE_ROOT=str(BASE / 'replica'), GSEARCH_SERVICE_PORT=str(port),
        GSEARCH_STDOUT=str(logs / (instance + '.out.log')), GSEARCH_STDERR=str(logs / (instance + '.err.log')))
    # Direct process handles avoid a background PowerShell descendant retaining
    # captured output pipes. CREATE_NO_WINDOW keeps the helper hidden on Windows.
    with open(env['GSEARCH_STDOUT'], 'w', encoding='utf-8') as out, open(env['GSEARCH_STDERR'], 'w', encoding='utf-8') as err:
        launched = subprocess.Popen([str(VENV / 'Scripts/python.exe'), '-E', '-s', '-u', '-m',
            'gsearch.local_service', '--port', str(port)], cwd=BASE / 'replica', env=env,
            stdin=subprocess.DEVNULL, stdout=out, stderr=err,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    launcher_pid = launched.pid
    for _ in range(120):
        try:
            code, health = request('GET', '/health', port=port)
            if code == 200:
                if health['instance_id'] != instance:
                    raise ValueError('Another process answered the local port; do not claim ownership')
                import psutil
                process = psutil.Process(health['pid'])
                state = {'state': 'running', 'pid': health['pid'], 'launcher_pid': launcher_pid, 'port': port,
                    'instance_id': instance, 'process_created': process.create_time(), 'bind': '127.0.0.1',
                    'created_at_utc': datetime.now(timezone.utc).isoformat(), 'private_logs': str(logs)}
                STATE.write_text(json.dumps(state, indent=2) + '\n')
                return {'state': 'running', 'url': f'http://127.0.0.1:{port}', 'pid': state['pid'], 'instance_id': instance}
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(1)
    raise RuntimeError('Local service did not become ready; inspect private stage18 startup logs')


def stop() -> dict:
    state = json.loads(STATE.read_text())
    if state['state'] == 'stopped': return {'state': 'already_stopped'}
    import psutil
    try:
        process = psutil.Process(state['pid'])
        if abs(process.create_time() - state['process_created']) > .01 or 'gsearch.local_service' not in process.cmdline():
            raise ValueError('PID ownership changed; refusing to terminate an unrelated process')
        if not Path(process.exe()).resolve().is_relative_to(BASE):
            raise ValueError('Service executable escaped independent runtime')
        process.terminate(); process.wait(timeout=15)
    except psutil.NoSuchProcess:
        pass
    state['state'] = 'stopped'; state['stopped_at_utc'] = datetime.now(timezone.utc).isoformat()
    STATE.write_text(json.dumps(state, indent=2) + '\n')
    return {'state': 'stopped', 'port': state['port']}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument('action', choices=('start', 'status', 'stop'))
    parser.add_argument('--port', type=int, default=8765); args = parser.parse_args()
    if not 1024 <= args.port <= 65535: raise ValueError('Use an unprivileged local port')
    if args.action == 'start': result = start(args.port)
    elif args.action == 'stop': result = stop()
    else:
        if not STATE.exists():
            print(json.dumps({'state': 'not_started_or_starting'})); return
        state = json.loads(STATE.read_text())
        if state['state'] == 'stopped': result = {'state': 'stopped', 'port': state['port']}
        else:
            code, health = request('GET', '/health', port=state['port'])
            if code != 200 or health['instance_id'] != state['instance_id']: raise ValueError('Local service ownership differs')
            result = health
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__': main()
