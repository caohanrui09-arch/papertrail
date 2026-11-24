import unittest
from gsearch.sid_budget import require_reference, verify_seen_order, check_resources


class BudgetContracts(unittest.TestCase):
    def setUp(self):
        self.logs = [{'step': i, 'loss': 3.0, 'grad_norm': 1.2, 'learning_rate': .0005,
                      'epoch': i / 512} for i in range(16, 129, 16)]

    def test_epoch_changes_do_not_change_update_reference(self):
        reference = [r | {'epoch': r['step'] / 128} for r in self.logs]
        self.assertEqual(require_reference(self.logs, reference), 8)

    def test_loss_mismatch_rejected(self):
        bad = [dict(r) for r in self.logs]; bad[0]['loss'] += .0001
        with self.assertRaises(ValueError): require_reference(bad, self.logs)

    def test_grad_mismatch_rejected(self):
        bad = [dict(r) for r in self.logs]; bad[-1]['grad_norm'] += 1e-8
        with self.assertRaises(ValueError): require_reference(bad, self.logs)

    def test_missing_reference_rejected(self):
        with self.assertRaises(ValueError): require_reference(self.logs[:-1], self.logs)

    def test_order_complete(self):
        verify_seen_order(list(range(4096)), 4096)

    def test_repeated_or_shuffled_order_rejected(self):
        for rows in [[0, 0], [1, 0], [0]]:
            with self.assertRaises(ValueError): verify_seen_order(rows, 2)

    def test_resource_caps(self):
        caps = {'gpu_reserved_gib': 6.5, 'process_peak_gib': 12, 'per_run_training_seconds': 900}
        check_resources({'gpu_reserved_bytes': 2**30, 'process_peak_bytes': 3*2**30}, 200, caps)
        for measured, seconds, error in [
            ({'gpu_reserved_bytes': 7*2**30, 'process_peak_bytes': 3*2**30}, 200, MemoryError),
            ({'gpu_reserved_bytes': 2**30, 'process_peak_bytes': 13*2**30}, 200, MemoryError),
            ({'gpu_reserved_bytes': 2**30, 'process_peak_bytes': 3*2**30}, 901, TimeoutError),
        ]:
            with self.assertRaises(error): check_resources(measured, seconds, caps)


if __name__ == '__main__': unittest.main()
