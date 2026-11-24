"""Check whether the schema-isolation test failure is pre-existing.

Loads the frozen pre-change state machine under the module name
`gsearch.state_constraints`, then runs the native-loop test followed by the
schema-isolation test. If the same TypeError appears, the coupling is not
caused by the stage81 message change.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'gsearch.state_constraints', ROOT / 'research81/frozen_state_constraints_v79.py')
module = importlib.util.module_from_spec(spec)
sys.modules['gsearch.state_constraints'] = module
spec.loader.exec_module(module)

if __name__ == '__main__':
    unittest.main(module=None, argv=[
        'check_preexisting_isolation',
        'tests.test_state_constraints.StateConstraintTests.test_native_loop_masks_repeats_and_bills_schema_rejections',
        'tests.test_schema_isolation',
    ])
