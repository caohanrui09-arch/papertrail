"""Run clock-controlled policy checks in the fresh API runtime, not the old env."""
import json
from pathlib import Path
import subprocess

from .manage_stage17_env import BASE, VENV, environment

CODE = r'''
import json, unittest
from types import SimpleNamespace
from datetime import datetime, timezone
from fastapi import HTTPException
from pydantic import ValidationError
from gsearch.local_service import SessionStore, CreateSession, RecommendRequest

class PolicyTests(unittest.TestCase):
    def model(self):
        return SimpleNamespace(cutoff=datetime(2024,1,1,tzinfo=timezone.utc), users=['train-user'],user2row={'train-user':0})
    def test_clock_ttl_and_capacity(self):
        clock=[0.]; store=SessionStore(self.model(),.25,capacity=1,ttl_seconds=10,clock=lambda:clock[0])
        token=store.create(CreateSession())['session_id']
        with self.assertRaises(HTTPException) as raised: store.create(CreateSession())
        self.assertEqual(raised.exception.status_code,503)
        clock[0]=11.
        with self.assertRaises(HTTPException) as raised: store.call(token,'recommend_papers',k=1)
        self.assertEqual(raised.exception.status_code,404)
        fresh=store.create(CreateSession())['session_id']
        self.assertTrue(store.delete(fresh)['deleted'])
    def test_native_read_before_return_and_time(self):
        store=SessionStore(self.model(),.25)
        token=store.create(CreateSession())['session_id']
        with self.assertRaises(HTTPException) as raised: store.call(token,'read_paper',doc_id='not-returned')
        self.assertEqual(raised.exception.status_code,400)
        with self.assertRaises(HTTPException) as raised: store.create(CreateSession(at='2020-01-01T00:00:00Z'))
        self.assertEqual(raised.exception.status_code,422)
    def test_native_strict_schema(self):
        for value in (True,11,'3',0):
            with self.assertRaises(ValidationError): RecommendRequest(k=value)
        with self.assertRaises(ValidationError): CreateSession(alpha=.9)

result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(PolicyTests))
if not result.wasSuccessful(): raise SystemExit(1)
print(json.dumps({'native_api_policy_tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors)}))
'''


def main():
    log = Path('.cache/stage18/policy-tests.log')
    with log.open('w', encoding='utf-8') as stream:
        result = subprocess.run([str(VENV/'Scripts/python.exe'),'-E','-s','-u','-c',CODE],
            cwd=BASE/'replica',env=environment(),stdout=stream,stderr=subprocess.STDOUT)
    result.check_returncode()
    text = log.read_text(encoding='utf-8')
    summary = json.loads(next(line for line in reversed(text.splitlines()) if line.startswith('{')))
    Path('reports/stage18/policy-validation.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
