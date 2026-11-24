"""Meaningful transactional/validation checks, always in automation-only space."""
from pathlib import Path
from uuid import uuid4
import concurrent.futures
import unittest
from unittest.mock import patch
import json
from urllib.error import URLError

from gsearch.annotation_store import BlindPool,AnnotationStore,ReviewInput,JudgmentInput
from gsearch.visitor_profile import PreferenceConflict


class AnnotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.pool=BlindPool()

    def setUp(self):
        self.path=Path('.cache/stage26/policy')/str(uuid4())/'test.sqlite3'
        self.store=AnnotationStore(self.path,self.pool);self.owner='verification:test'
        self.qid=next(iter(self.pool.tasks));self.aid=self.pool.tasks[self.qid]['candidates'][0]['annotation_id']

    def approve(self,revision=0):
        return self.store.review(self.owner,self.qid,ReviewInput(revision=revision,operation='submit',decision='approve',reviewer='TEST',note='Automation fixture, not a human opinion',attest=True))

    def test_unconfirmed_cannot_write_judgments(self):
        with self.assertRaises(ValueError):self.store.judge(self.owner,self.qid,self.aid,JudgmentInput(revision=0,operation='draft'))

    def test_draft_and_skip_not_submitted(self):
        self.approve()
        self.store.judge(self.owner,self.qid,self.aid,JudgmentInput(revision=0,operation='draft',grade=2))
        r=self.store.judge(self.owner,self.qid,self.aid,JudgmentInput(revision=1,operation='skip',grade=2,rationale='test insufficient evidence'))
        self.assertIsNone(r['value']['grade']);self.assertEqual(self.store.workspace(self.owner)['submitted'],0)

    def test_revisions_and_review_invalidation(self):
        self.approve()
        self.store.judge(self.owner,self.qid,self.aid,JudgmentInput(revision=0,operation='submit',grade=1,reviewer='TEST',rationale='test reason',attest=True))
        self.assertEqual(self.store.workspace(self.owner)['submitted'],1)
        self.approve(1)
        self.assertEqual(self.store.workspace(self.owner)['submitted'],0)
        self.assertEqual(len(self.store.history(self.owner,self.qid,'judgment',self.aid)),1)

    def test_isolation_and_reopen(self):
        self.approve()
        reopened=AnnotationStore(self.path,self.pool)
        self.assertTrue(reopened.detail(self.owner,self.qid)['labeling_unlocked'])
        self.assertFalse(reopened.detail('verification:other',self.qid)['labeling_unlocked'])
        self.assertEqual(reopened.workspace('test')['approved'],0)

    def test_concurrent_revision_is_not_overwritten(self):
        def write(_):
            try:self.approve();return 'ok'
            except PreferenceConflict:return 'conflict'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(pool.map(write,[1,2]),['ok','conflict'])

    def test_strict_grade_and_missing_provenance(self):
        for grade in (True,'1',-1,3):
            with self.assertRaises(ValueError):JudgmentInput(revision=0,operation='draft',grade=grade)
        self.approve()
        with self.assertRaises(ValueError):self.store.judge(self.owner,self.qid,self.aid,JudgmentInput(revision=0,operation='submit',grade=0,reviewer='TEST',rationale='test',attest=False))

    def test_forbidden_query_and_candidate(self):
        with self.assertRaises(ValueError):self.pool.task('q25-004')
        with self.assertRaises(ValueError):self.pool.candidate(self.qid,'../evaluator/runs.json')


class LauncherRecoveryTests(unittest.TestCase):
    def test_exited_backend_can_recover_without_touching_live_gateway(self):
        import psutil
        from scripts import annotation_workbench_control as control
        root=Path('.cache/stage26/policy')/str(uuid4());root.mkdir(parents=True)
        state=root/'ui.json';backend=root/'backend.json'
        state.write_text(json.dumps({'state':'running','instance_id':'test'}))
        backend.write_text(json.dumps({'state':'running','pid':123}))
        with patch.object(control,'ROOT',root),patch.object(control,'STATE',state),patch.object(control,'owned'),\
             patch.object(control,'health',return_value=(200,{'instance_id':'test'})),\
             patch.object(control,'start_backend',side_effect=[URLError('refused'),None]) as start,\
             patch('scripts.unified_service_control.STATE',backend),patch('scripts.unified_service_control.stop') as stop,\
             patch('psutil.Process',side_effect=psutil.NoSuchProcess(123)):
            self.assertEqual(control.start()['state'],'already_running')
            self.assertEqual(start.call_count,2);stop.assert_called_once()

    def test_unresponsive_live_backend_is_not_terminated(self):
        from scripts import annotation_workbench_control as control
        root=Path('.cache/stage26/policy')/str(uuid4());root.mkdir(parents=True)
        backend=root/'backend.json';backend.write_text(json.dumps({'state':'running','pid':123}))
        with patch.object(control,'start_backend',side_effect=URLError('refused')),\
             patch('scripts.unified_service_control.STATE',backend),patch('scripts.unified_service_control.stop') as stop,\
             patch('psutil.Process',return_value=object()):
            with self.assertRaises(URLError):control.start()
            stop.assert_not_called()


if __name__=='__main__':unittest.main()
