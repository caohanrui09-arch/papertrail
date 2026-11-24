"""Reuse the owned local-process controller with new stage/runtime/module constants."""
from pathlib import Path

source = Path('scripts/paper_workspace_control.py').read_text(encoding='utf-8')
source = source.replace('from scripts.manage_stage17_env import VENV,BASE,environment',
    "from scripts.manage_stage17_env import environment\nBASE=Path('.cache/stage39').resolve()\nVENV=BASE/'runtime-secure'")
source = source.replace('.cache/stage38','.cache/stage39').replace('8780','8782')
source = source.replace('gsearch.paper_workspace','scripts.run_trial_local')
source = source.replace('GSEARCH_WORKBENCH_INSTANCE','PAPERTRAIL_INSTANCE')
source = source.replace('papertrail-workspace.cmd','papertrail-trial.cmd')
source = source.replace('paper_backend_preserved','previous_versions_preserved')
source = source.replace("and Path(child.exe()).resolve().is_relative_to(BASE)",
    "and (Path(child.exe()).resolve().is_relative_to(BASE) or Path(child.exe()).resolve().is_relative_to(Path('.cache/stage17/python').resolve()))")
Path('scripts/trial_control.py').write_text(source,encoding='utf-8')
