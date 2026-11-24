"""Isolated loopback preview, never use the actual visitor volume for UI tests."""
import os
from pathlib import Path
import runpy

ROOT=Path(__file__).resolve().parents[1]
os.environ['PAPERTRAIL_DATA_DIR']=str(ROOT/'.cache/stage52/ui-visitors')
os.environ['PAPERTRAIL_ORIGIN']='http://127.0.0.1:8792'
os.environ['PORT']='8792'
os.environ['PAPERTRAIL_INSTANCE']='stage52-isolated-ui'

if __name__=='__main__':runpy.run_module('scripts.run_demo_delivery_local',run_name='__main__')
