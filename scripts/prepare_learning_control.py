"""Reuse the owned v39 controller; retain the exact isolated runtime and private store."""
from pathlib import Path

text=Path('scripts/trial_control.py').read_text(encoding='utf-8')
text=text.replace("ROOT=Path('.cache/stage39').resolve()","ROOT=Path('.cache/stage40').resolve()")
text=text.replace('8782','8785').replace('scripts.run_trial_local','scripts.run_learning_local')
text=text.replace('papertrail-trial.cmd','papertrail-learn.cmd')
text=text.replace('private .cache/stage39/logs','private .cache/stage40/logs')
# BASE and VENV intentionally stay stage39 to reuse the patched 26-package environment.
Path('scripts/learning_control.py').write_text(text,encoding='utf-8')
