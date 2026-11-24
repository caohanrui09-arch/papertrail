"""Delivery output isolation, literal source rendering and genuine tool reuse."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from gsearch.showcase import create_run_dir, choose_user, fenced, render_demo, run_tools, verify_receipt, verify_demo


class ShowcaseTests(unittest.TestCase):
    def test_train_user_choice_is_order_independent_and_empty_fails(self):
        users = ['a', 'b', 'c']
        expected = min(users, key=lambda user: hashlib.sha256(('stage16-demo:' + user).encode()).hexdigest())
        self.assertEqual(choose_user(users), expected)
        self.assertEqual(choose_user(users[::-1]), expected)
        with self.assertRaises(ValueError):
            choose_user([])

    def test_personal_outputs_cannot_escape_or_overwrite(self):
        Path('data').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir='data') as folder:
            target = Path(folder) / 'new-demo'
            self.assertEqual(create_run_dir(target), target.resolve())
            with self.assertRaises(FileExistsError):
                create_run_dir(target)
        for target in (Path('data'), Path('reports/should-not-create'), Path('data/../reports/should-not-create')):
            with self.assertRaises(ValueError):
                create_run_dir(target)

    def test_original_text_cannot_terminate_markdown_fence(self):
        text = 'Title\n```\n# injected heading\n````\n<script>literal source</script>'
        quoted = fenced(text)
        self.assertEqual(quoted.splitlines()[0], '`````text')
        self.assertEqual(quoted.splitlines()[-1], '`````')
        self.assertIn(text, quoted)

    def test_delivery_receipt_detects_changed_assets(self):
        with tempfile.TemporaryDirectory(dir='data') as folder:
            base = Path(folder); asset = base / 'asset.txt'; asset.write_text('original', encoding='utf-8')
            receipt = base / 'receipt.json'
            receipt.write_text(json.dumps({'code': {str(asset): hashlib.sha256(asset.read_bytes()).hexdigest()}}), encoding='utf-8')
            self.assertEqual(verify_receipt(receipt, ('code',)), 1)
            asset.write_text('changed', encoding='utf-8')
            with self.assertRaises(ValueError):
                verify_receipt(receipt, ('code',))

    def test_three_methods_use_real_tools_and_original_v1_parser(self):
        import copy
        import pandas as pd
        from gsearch.expansion_data import available_at, read
        from gsearch.catalog_audit import stamp
        from gsearch.expansion_recommendation import ExpansionRecommender
        from gsearch.cold_fusion import ColdAwareRecommender
        paths = sorted(Path('.cache/stage13/batches').glob('00000-*.json'))
        if not paths:
            self.skipTest('Official source cache not prepared')
        source = [r for r in read(paths[0])['records'] if available_at(r['published_at']) < stamp('2024-10-27T18:52:32Z')][:3]
        records = []
        for i, row in enumerate(source):
            record = copy.deepcopy(row)
            record.update(cohort='warm' if i < 2 else 'old_cold',
                available_at=available_at(row['published_at']).isoformat(), version_key='arxiv:' + row['doc_id'] + 'v1',
                time_assumption='source-only test fixture')
            records.append(record)
        train = pd.DataFrame([('a', records[0]['doc_id'], 1), ('b', records[1]['doc_id'], 1)],
                             columns=['user_id', 'arxiv_id', 'rating'])
        original = ExpansionRecommender(train, records, '2024-10-27T18:52:32Z',
            params={'ngram_range': [1, 2], 'min_df': 1, 'norm': 'l2'})
        model = ColdAwareRecommender(original)
        result = run_tools(model, 'a', '2025-02-23T13:28:26+08:00', .25, 2)
        self.assertEqual(set(result), {'content', 'original_rrf', 'cold_aware'})
        for value in result.values():
            self.assertTrue(value['original_version_abstract']['source_verified'])
            self.assertEqual(value['original_version_abstract']['version'], 1)
            self.assertEqual([r['tool'] for r in value['trace']], ['recommend_papers', 'read_paper'])
            self.assertEqual(len(value['recommendation']['papers']), 2)
        text = render_demo({'user_id': 'a', 'as_of': '2025-02-23', 'methods': result})
        self.assertIn('## cold_aware', text)
        self.assertIn('语义立场核验：False', text)
        payload = {'user_id': 'a', 'as_of': '2025-02-23T13:28:26+08:00', 'research_alpha': .25, 'methods': result}
        self.assertEqual(verify_demo(model, payload, .25), 3)
        changed = copy.deepcopy(payload)
        changed['methods']['cold_aware']['original_version_abstract']['abstract'] = 'tampered'
        with self.assertRaises(ValueError):
            verify_demo(model, changed, .25)


if __name__ == '__main__':
    unittest.main()
