"""Isolated v56 browser test on a separate hostname and visitor volume."""
from pathlib import Path
import os,runpy
ROOT=Path(__file__).resolve().parents[1]
os.environ['PAPERTRAIL_DATA_DIR']=str(ROOT/'.cache/stage56/ui-visitors')
os.environ['PAPERTRAIL_ORIGIN']='http://localhost:8796'
os.environ['PORT']='8796'
os.environ['PAPERTRAIL_INSTANCE']='stage56-isolated-ui'
runpy.run_module('scripts.run_research56_local',run_name='__main__')
