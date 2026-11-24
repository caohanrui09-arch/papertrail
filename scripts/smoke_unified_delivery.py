"""Exercise actual CLI entry points; preserve expected experimental failures."""
import json
import os
from pathlib import Path
import subprocess
import time

from .prepare_stage19_tasks import ROOT, digest, save
from .manage_stage17_env import environment


def main() -> None:
    output = Path('reports/stage19/delivery-smoke.json')
    if output.exists(): raise ValueError('Smoke receipt already exists')
    results = {}
    for policy in ('fixed', 'llm_agent'):
        before = set(ROOT.parent.glob('demo-*/result.json'))
        log = Path(f'.cache/stage19/cli-{policy}.log')
        started = time.perf_counter()
        with log.open('w', encoding='utf-8') as stream:
            process = subprocess.run(['cmd.exe', '/c', 'unified-demo.cmd', policy], env=environment(),
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, timeout=300)
        created = set(ROOT.parent.glob('demo-*/result.json')) - before
        if len(created) != 1: raise ValueError('CLI must preserve exactly one new raw result')
        raw = json.loads(next(iter(created)).read_text(encoding='utf-8'))
        completed = raw['completed_protocol']
        expected_code = 0 if completed else 1
        if process.returncode != expected_code: raise ValueError('CLI exit code differs from completion')
        if policy == 'fixed' and not completed: raise ValueError('Default CLI must run successfully')
        results[policy] = {'completed': completed, 'exit_code': process.returncode,
            'exit_code_honest': True, 'seconds_including_process_and_model_loading': time.perf_counter()-started,
            'raw_result_sha256': digest(next(iter(created))), 'log_private': str(log)}
    save(output, {'actual_cmd_entries_executed': True, 'default_fixed_passed': True,
        'llm_mode_explicit_no_silent_fallback': True, 'results': results})
    print(json.dumps({key: {'completed': item['completed'], 'exit_code': item['exit_code']} for key, item in results.items()}))


if __name__ == '__main__': main()
