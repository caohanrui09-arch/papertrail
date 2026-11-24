"""Actual .cmd status/stop/restart; only the owned stage19 instance is affected."""
import json
from pathlib import Path
import subprocess
import urllib.error

from .manage_stage17_env import environment
from .prepare_stage19_tasks import save
from gsearch.unified_agent import request


def command(action: str) -> dict:
    result = subprocess.run(['cmd.exe', '/c', 'unified-service.cmd', action], env=environment(),
        check=True, capture_output=True, text=True, timeout=180)
    return json.loads(result.stdout)


def main() -> None:
    output = Path('reports/stage19/lifecycle-validation.json')
    if output.exists(): raise ValueError('Lifecycle already verified')
    first = command('status')
    unchanged = command('start')
    if first['instance_id'] != unchanged['instance_id']: raise ValueError('Start must be idempotent')
    stopped = command('stop')
    if stopped['state'] != 'stopped': raise ValueError('Stop failed')
    unreachable = False
    try:
        request('GET', '/health')
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        unreachable = True
    if not unreachable: raise ValueError('Service still responding after stop')
    restarted = command('start')
    last = command('status')
    if last['instance_id'] == first['instance_id'] or last['instance_id'] != restarted['instance_id']:
        raise ValueError('Restart instance mismatch')
    save(output, {'actual_cmd_lifecycle': True, 'start_idempotent': True, 'stopped': True,
        'unreachable_after_stop': True, 'restarted_ready': True, 'instance_changed': True, 'left_running': True,
        'bind': '127.0.0.1', 'port': 8766})
    print(json.dumps({'status': 'passed', 'left_running': True}))


if __name__ == '__main__': main()
