"""Isolated v61 browser test on a separate hostname and visitor volume."""
from pathlib import Path
import os,runpy
ROOT=Path(__file__).resolve().parents[1]
os.environ['PAPERTRAIL_DATA_DIR']=str(ROOT/'.cache/stage61/ui-visitors')
os.environ['PAPERTRAIL_ORIGIN']='http://localhost:8801'
os.environ['PORT']='8801'
os.environ['PAPERTRAIL_INSTANCE']='stage61-isolated-ui'
runpy.run_module('scripts.run_research61_local',run_name='__main__')
