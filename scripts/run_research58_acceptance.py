"""Isolated v58 browser test on a separate hostname and visitor volume."""
from pathlib import Path
import os,runpy
ROOT=Path(__file__).resolve().parents[1]
os.environ['PAPERTRAIL_DATA_DIR']=str(ROOT/'.cache/stage58/ui-visitors')
os.environ['PAPERTRAIL_ORIGIN']='http://localhost:8798'
os.environ['PORT']='8798'
os.environ['PAPERTRAIL_INSTANCE']='stage58-isolated-ui'
runpy.run_module('scripts.run_research58_local',run_name='__main__')
