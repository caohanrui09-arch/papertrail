"""Portable path mapping and actual fresh-interpreter audit-policy boundaries."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from gsearch.relocated_demo import relocated_records, verify_bundle


class RelocationTests(unittest.TestCase):
    def test_path_mapping_changes_only_in_memory_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory(dir='.cache') as folder:
            root = Path(folder).resolve(); cache = root / '.cache/stage13/raw'; cache.mkdir(parents=True)
            raw = b'official bytes'; sha = hashlib.sha256(raw).hexdigest()
            body = cache / (sha + '.body'); body.write_bytes(raw)
            original = [{'doc_id': '2401.00001', 'title': 'unchanged', 'provenance': {'raw_path': 'Z:/old-root/response.body', 'raw_sha256': sha}}]
            result = relocated_records(original, root)
            self.assertEqual(original[0]['provenance']['raw_path'], 'Z:/old-root/response.body')
            self.assertEqual(result[0]['title'], original[0]['title'])
            self.assertEqual(Path(result[0]['provenance']['raw_path']), body)
            body.write_bytes(b'tampered')
            with self.assertRaises(ValueError): relocated_records(original, root)

    def test_bundle_hash_and_escape_rejected(self):
        with tempfile.TemporaryDirectory(dir='.cache') as folder:
            root = Path(folder); asset = root / 'asset.txt'; asset.write_bytes(b'original')
            manifest = root / 'bundle-manifest.json'
            manifest.write_text(json.dumps({'files': {'asset.txt': hashlib.sha256(asset.read_bytes()).hexdigest()}}))
            self.assertEqual(len(verify_bundle(root)['files']), 1)
            asset.write_bytes(b'changed')
            with self.assertRaises(ValueError): verify_bundle(root)
            manifest.write_text(json.dumps({'files': {'../outside.txt': 'a' * 64}}))
            with self.assertRaises(ValueError): verify_bundle(root)

    def test_actual_fresh_python_denies_old_reads_and_socket_connect(self):
        from scripts.run_stage17_replay import GUARD
        from scripts.manage_stage17_env import BASE, VENV, environment
        python = VENV / 'Scripts/python.exe'
        if not python.exists(): self.skipTest('Managed clean environment not installed')
        # Install the same audited hook, then probe negative paths without running the model.
        prefix = GUARD.split("sys.argv = ['gsearch.relocated_demo'")[0]
        probe = r'''
import socket
denied = []
try:
    open(old_project / 'AGENTS.md', 'rb')
except PermissionError:
    denied.append('old_read')
with socket.socket() as sock:
    try:
        sock.connect(('127.0.0.1', 1))
    except PermissionError:
        denied.append('network')
assert denied == ['old_read', 'network'], denied
print(json.dumps({'denied': denied, 'counts': counts}))
'''
        env = environment(); env['GSEARCH_ISOLATION_ROOT'] = str(BASE)
        import sys
        env['GSEARCH_OLD_BASE_PYTHON'] = sys.base_prefix
        result = subprocess.run([str(python), '-E', '-s', '-c', prefix + probe], cwd=BASE / 'replica',
            env=env, capture_output=True, text=True, check=True)
        output = json.loads(result.stdout)
        self.assertEqual(output['counts']['old_root_read_attempts'], 1)
        self.assertEqual(output['counts']['network_attempts'], 1)


if __name__ == '__main__': unittest.main()
