"""Clock-controlled native API TTL/capacity/schema checks, no 15min wait claim."""
from datetime import datetime
from pathlib import Path
import unittest

from fastapi import HTTPException
from pydantic import ValidationError
from gsearch.unified_service import create_app, SessionRequest, ToolRequest
from tests.test_unified import Model
from .prepare_stage19_tasks import save


class APITests(unittest.TestCase):
    def setUp(self):
        self.now = 0.
        self.app = create_app(Model(), 'test', capacity=1, ttl=15., clock=lambda: self.now)
        self.routes = {route.name: route.endpoint for route in self.app.routes}
        self.spec = SessionRequest(user_id='u', at=datetime.fromisoformat('2024-06-01T00:00:00Z'))

    def test_capacity_expiry_and_reuse(self):
        first = self.routes['create'](self.spec)['session_id']
        with self.assertRaises(HTTPException) as blocked: self.routes['create'](self.spec)
        self.assertEqual(blocked.exception.status_code, 503)
        self.now = 15.
        with self.assertRaises(HTTPException) as expired: self.routes['snapshot'](first)
        self.assertEqual(expired.exception.status_code, 404)
        self.assertNotEqual(self.routes['create'](self.spec)['session_id'], first)

    def test_time_and_schema(self):
        for at in ['2024-06-01', '2023-01-01T00:00:00Z']:
            with self.assertRaises(HTTPException): self.routes['create'](SessionRequest(user_id='u', at=at))
        with self.assertRaises(ValidationError): SessionRequest(method='unknown')
        with self.assertRaises(ValidationError): SessionRequest(alpha=.9)
        with self.assertRaises(ValidationError): ToolRequest(name='shell', arguments={})

    def test_failed_attempt_recorded(self):
        token = self.routes['create'](self.spec)['session_id']
        with self.assertRaises(HTTPException) as rejected:
            self.routes['tool'](token, ToolRequest(name='read_paper', arguments={'doc_id': 'c'}))
        self.assertEqual(rejected.exception.status_code, 400)
        snapshot = self.routes['snapshot'](token)
        self.assertEqual(snapshot['attempts'], 1)
        self.assertIn('error', snapshot['trace'][0]['result'])


def main() -> None:
    output = Path('reports/stage19/api-policy-validation.json')
    if output.exists(): raise ValueError('API policy validation already recorded')
    log = Path('.cache/stage19/api-policy-tests.log')
    with log.open('w', encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(APITests))
    save(output, {'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
        'passed': result.wasSuccessful(), 'clock_controlled': True, 'real_15min_wait_performed': False})
    if not result.wasSuccessful(): raise ValueError('Native API policy tests failed')
    print(f'{result.testsRun} native API policy tests passed')


if __name__ == '__main__': main()
