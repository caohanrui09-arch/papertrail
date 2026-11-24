"""New v40 assets; preserve v39 bytes, catalog namespace and existing preferences."""
from pathlib import Path
import shutil

SRC=Path('deploy/stage39')
DEST=Path('deploy/stage40')
DEST.mkdir(parents=True,exist_ok=True)
for folder in ['trialsite','catalog','web']:
    shutil.copytree(SRC/folder,DEST/folder,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
for name in ['requirements.in','requirements.lock','reuse-receipt.json']:
    shutil.copyfile(SRC/name,DEST/name)
# Do not copy a paid Blueprint. Free persistence adaptation remains a separate task.

