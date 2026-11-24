"""Temporal attribution and separate user/item cold-start boundary contracts."""
from datetime import datetime,timezone
import io
import unittest

from gsearch.catalog_audit import CountedFile,reason,sample_stratum,stamp

class CatalogAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cut=stamp('2024-10-27T18:52:32Z')
        self.event=stamp('2025-01-01T00:00:00Z')
        self.old={'first_version_date':'2024-01-01','latest_version_date':'2024-06-01'}

    def cause(self,doc: str,meta: dict|None) -> str:
        return reason(doc,meta,self.event,self.cut,{'in','truncated','excluded'},{'in'},{'in','excluded'})

    def test_old_item_attribution_preserves_topk_and_version_exclusion(self) -> None:
        self.assertEqual(self.cause('in',self.old),'inside_current_catalog')
        self.assertEqual(self.cause('truncated',self.old),'old_trainliked_topk_truncated')
        self.assertEqual(self.cause('excluded',self.old),'old_trainliked_version_excluded')
        self.assertEqual(self.cause('unliked',self.old),'old_without_training_likes')

    def test_missing_and_future_metadata_never_become_known_old_papers(self) -> None:
        self.assertEqual(self.cause('x',None),'unknown_metadata_or_first_date')
        self.assertEqual(self.cause('x',{'first_version_date':'bad'}),'unknown_metadata_or_first_date')
        self.assertEqual(self.cause('x',{'first_version_date':'2025-02-01'}),'source_first_date_after_feedback')
        self.assertEqual(self.cause('x',{'first_version_date':self.cut.isoformat()}),'published_after_train_cutoff')

    def test_sample_strata_require_no_future_feedback(self) -> None:
        row={'paper_id':'x',**self.old}
        self.assertEqual(sample_stratum(row,self.cut,self.event,{'x'}),'old_trainliked_text_pre_cutoff')
        self.assertEqual(sample_stratum(row,self.cut,self.event,set()),'old_no_trainlike_text_pre_cutoff')
        row['latest_version_date']='2024-12-01'
        self.assertEqual(sample_stratum(row,self.cut,self.event,{'x'}),'old_updated_after_cutoff')
        row['first_version_date']='2024-11-01'
        self.assertEqual(sample_stratum(row,self.cut,self.event,{'x'}),'new_between_cutoff_and_log_end')
        row['latest_version_date']='2023-01-01'
        self.assertIsNone(sample_stratum(row,self.cut,self.event,set()))

    def test_file_counting_measures_returned_bytes_and_rejects_full_read(self) -> None:
        f=CountedFile(io.BytesIO(b'abcdefghij'))
        self.assertEqual(f.read(3),b'abc')
        f.seek(8)
        self.assertEqual(f.read(9),b'ij')
        self.assertEqual(f.returned_bytes,5)
        self.assertEqual(f.read_calls,2)
        with self.assertRaises(ValueError):
            f.read()

    def test_source_timezone_normalization_is_explicit(self) -> None:
        self.assertEqual(stamp('2024-01-01'),stamp('2024-01-01T00:00:00Z'))
        self.assertEqual(stamp('2024-01-01T08:00:00+08:00'),stamp('2024-01-01'))
        self.assertIsNone(stamp(None))

if __name__=='__main__':
    unittest.main()
