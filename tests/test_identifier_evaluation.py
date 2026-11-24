import unittest

from scripts.make_stage4_report import paired


class PairedEvaluationTests(unittest.TestCase):
    def test_resampling_preserves_perfectly_paired_constant_gain(self) -> None:
        left = {"queries": [{"claim_id": i, "query": str(i), "relevant": [str(i)],
                              "recall": 1.0, "mrr": 1.0, "ndcg": 1.0} for i in range(3)]}
        right = {"queries": [{**row, "recall": 0.0, "mrr": 0.0, "ndcg": 0.0}
                               for row in left["queries"]]}
        result = paired(left, right)
        for metric in ("recall", "mrr", "ndcg"):
            self.assertEqual(result[metric]["mean_delta"], 1.0)
            self.assertEqual(result[metric]["bootstrap_95_percentile_interval"], [1.0, 1.0])
            self.assertEqual(result[metric]["wins"], 3)

    def test_misaligned_queries_or_changed_labels_cannot_be_compared(self) -> None:
        left = {"queries": [{"claim_id": 1, "query": "x", "relevant": ["a"],
                              "recall": 1.0, "mrr": 1.0, "ndcg": 1.0}]}
        for change in ({"claim_id": 2}, {"relevant": ["b"]}, {"query": "y"}):
            right = {"queries": [{**left["queries"][0], **change}]}
            with self.assertRaises(ValueError):
                paired(left, right)


if __name__ == "__main__":
    unittest.main()
