"""Native CPU API policy tests, separate from legacy CUDA test dependencies."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4


class WorkbenchTests(unittest.TestCase):
    def test_rejects_hidden_profile_and_extra_dispatch_fields(self):
        from gsearch.workbench_service import RunRequest
        from pydantic import ValidationError
        base={'thread_id':str(uuid4()),'mode':'search','query':'graph'}
        for extra in ({'user_id':'arbitrary-user'},{'k':None},{'profile':'anything'},{'query':'   '}):
            with self.subTest(extra=extra),self.assertRaises(ValidationError):RunRequest(**(base|extra))

    def test_source_projection_preserves_rejection_and_removes_local_paths(self):
        from gsearch.workbench_service import safe_result
        raw={'doc_id':'2401.00001','abstract':'literal <script>text</script>','version':1,
            'provenance':{'raw_path':'private-path'},'source_verified':True}
        view=safe_result('read_paper',raw)
        self.assertNotIn('provenance',view);self.assertEqual(view['abstract'],raw['abstract'])
        self.assertEqual(safe_result('read_paper',{'error':'budget exhausted'}),{'error':'budget exhausted'})

    def test_public_view_does_not_mutate_private_record(self):
        from gsearch.workbench_service import public_record
        raw={'id':'test','_task':{'user_id':'private-user'},'trace':[{'tool':'read_paper',
            'result':{'doc_id':'2401.00001','abstract':'original','provenance':{'raw_path':'private'}}}]}
        saved=deepcopy(raw);view=public_record(raw)
        self.assertEqual(raw,saved);self.assertNotIn('_task',view)
        self.assertNotIn('provenance',view['trace'][0]['result'])

    def routes(self):
        from gsearch import workbench_service as server
        context={'id':'test','user_id':'fixture','at':'2025-02-23T05:28:26.401006+00:00','query':'fixture title'}
        with patch.object(server,'select_task',return_value=(context,{})):
            app=server.create_app()
        return {r.name:r.endpoint for r in app.routes if hasattr(r,'endpoint')}

    def test_backend_unavailability_is_not_reported_ready(self):
        from gsearch import workbench_service as server
        from fastapi import HTTPException
        from urllib.error import URLError
        routes=self.routes()
        with patch.object(server,'upstream',side_effect=URLError('fixture unavailable')):
            with self.assertRaises(HTTPException) as raised:routes['health']()
            self.assertEqual(raised.exception.status_code,503)

    def test_unreturned_paper_refused_without_new_source_session(self):
        from gsearch import workbench_service as server
        with tempfile.TemporaryDirectory() as folder:
            ident=uuid4();path=Path(folder)/f'{ident}.json'
            path.write_text(json.dumps({'id':str(ident),'trace':[],'_task':{}}))
            from fastapi import HTTPException
            routes=self.routes()
            with patch.object(server,'RUNS',Path(folder)),patch.object(server,'ToolClient',side_effect=AssertionError('Unreturned ID dispatched')):
                with self.assertRaises(HTTPException) as raised:routes['read_paper'](ident,'2401.00001')
                self.assertEqual(raised.exception.status_code,403)

    def test_cached_source_does_not_claim_new_tool_execution(self):
        from gsearch import workbench_service as server
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);runs=root/'runs';reads=root/'reads';runs.mkdir();ident=uuid4()
            (runs/f'{ident}.json').write_text(json.dumps({'id':str(ident),'trace':[{'tool':'search_papers','arguments':{'query':'x','k':3},
                'result':{'papers':[{'doc_id':'2401.00001'}]}}],'_task':{}}))
            (reads/str(ident)).mkdir(parents=True)
            old={'paper':{'doc_id':'2401.00001'},'trace':[{'tool':'search_papers'},{'tool':'read_paper'}],
                'new_source_session':True,'cached_original':False}
            (reads/str(ident)/'2401.00001.json').write_text(json.dumps(old))
            routes=self.routes()
            with (patch.object(server,'RUNS',runs),patch.object(server,'READS',reads),
                  patch.object(server,'ToolClient',side_effect=AssertionError('Cached read re-executed'))):
                value=routes['read_paper'](ident,'2401.00001')
                self.assertTrue(value['cached_original']);self.assertFalse(value['new_source_session'])
                self.assertEqual(value['trace'],[]);self.assertEqual(len(value['source_session_trace']),2)


if __name__=='__main__':unittest.main()
