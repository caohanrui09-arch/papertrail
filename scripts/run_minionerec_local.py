"""Start v41 against the existing v39 catalog and private visitor volume."""
from pathlib import Path
import os
import sys

ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0,str(ROOT/'deploy/stage41'))
os.environ['PAPERTRAIL_LOCAL_PREVIEW']='1'
os.environ.setdefault('PAPERTRAIL_DATA_DIR',str(ROOT/'data/stage39-visitors'))
os.environ.setdefault('PAPERTRAIL_ORIGIN','http://127.0.0.1:8787')
os.environ.setdefault('PORT','8787')

if __name__=='__main__':
    from trialsite.minionerec import create_app
    from trialsite.app import main
    main(factory=create_app)
