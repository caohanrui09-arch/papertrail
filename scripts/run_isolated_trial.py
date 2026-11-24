"""Fresh worker, private stdout file, no console-buffer coupling in timings."""
import argparse
import os
from pathlib import Path
import subprocess
from scripts.manage_stage17_env import environment


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=('prepare','tuning','lock','evaluation'),required=True)
    args=parser.parse_args()
    root=Path('.cache/stage21-isolated');root.mkdir(parents=True,exist_ok=True)
    log=root/(args.phase+'-driver.log')
    if log.exists():raise ValueError('Preserve prior worker log')
    with log.open('w',encoding='utf-8') as stream:
        result=subprocess.run([str(Path('.cache/stage6-env/Scripts/python.exe').resolve()),'-u','-m',
            'scripts.benchmark_isolated_constraints','--phase',args.phase],env=environment(),stdout=stream,
            stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,timeout=7200,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    print(f'phase={args.phase} exit_code={result.returncode} private_log={log}',flush=True)
    result.check_returncode()


if __name__=='__main__':main()
