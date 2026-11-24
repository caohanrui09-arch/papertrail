from collections import Counter
import unittest

from gsearch.sid_failure_audit import (MetricAccumulator,availability_group,exposure_group,
                                     final_prefix_status,mapping_group,prefix_coverage)


class AuditBoundaries(unittest.TestCase):
    def test_outside_is_not_paper_cold(self):
        self.assertEqual(exposure_group('x',{}, {}, {}, {}, {'d'}),'outside_catalog')

    def test_source_cold_and_unselected_pilot_are_distinct(self):
        self.assertEqual(exposure_group('d',{}, {}, {}, {}, {'d'}),'no_source_train_like')
        self.assertEqual(exposure_group('d',{'d':5},{'d':4},{'d':3},{},{'d'}),'pool_target_not_selected_in_pilot')

    def test_availability_proxy_exclusion_distinct_from_supervision(self):
        self.assertEqual(exposure_group('d',{'d':5},{},{},{},{'d'}),'train_liked_without_proxy_eligible_feedback')
        self.assertEqual(exposure_group('d',{'d':5},{'d':1},{},{},{'d'}),'eligible_like_without_next_item_target')

    def test_target_exposure_has_label_count(self):
        self.assertEqual(exposure_group('d',{'d':2},{'d':2},{'d':1},{'d':1},{'d'}),'pilot_target_seen')

    def test_history_cold_differs_from_catalog(self):
        row={'rankable':True,'miss_reason':None}
        self.assertEqual(availability_group(row,False),'rankable_without_context')
        self.assertEqual(availability_group(row,True),'rankable_with_context')
        self.assertEqual(availability_group({'rankable':False,'miss_reason':'outside_frozen_catalog'},True),
                         'unrankable:outside_frozen_catalog')

    def test_first_final_prefix_absence_is_not_pruning_time(self):
        result=final_prefix_status([10,20,30,40,1],[[10,21,31,41,1],[11,20,30,40,1]],False)
        self.assertEqual(result['max_shared_sid_prefix_tokens'],1)
        self.assertEqual(result['first_missing_final_prefix_depth'],2)
        self.assertFalse(result['actual_beam_pruning_step_observed'])

    def test_identity_suffix_missing_not_semantic_layer_four(self):
        result=final_prefix_status([10,20,30,40,1],[[10,20,30,41,1]],False)
        self.assertEqual(result['first_missing_final_prefix_depth'],4)

    def test_hit_and_wrong_mapping_rejected(self):
        self.assertIsNone(final_prefix_status([10,20,1],[[10,20,1]],True)['first_missing_final_prefix_depth'])
        with self.assertRaises(ValueError):final_prefix_status([10,20,1],[[10,20,1]],False)

    def test_incomplete_trace_rejected(self):
        with self.assertRaises(ValueError):final_prefix_status([10,20,1],[[10,20]],False)
        with self.assertRaises(ValueError):final_prefix_status([10,20,1],[],False)

    def test_user_macro_not_event_micro_and_full_misses_retained(self):
        result=MetricAccumulator()
        result.add(['full'],'a',['x'],'x')
        for _ in range(3):result.add(['full'],'b',['x'],'outside')
        values=result.export()['full']
        self.assertEqual(values['events'],4)
        self.assertEqual(values['user_macro']['ndcg@10'],0.5)
        self.assertEqual(values['event_micro']['ndcg@10'],0.25)

    def test_prefix_coverage_separates_target_and_history(self):
        mapping={'a':[10,20,30,40,1],'b':[10,21,31,41,1]}
        rows=prefix_coverage(mapping,{'a':1},{'b':2},{'a':3,'b':2})
        self.assertEqual(rows[0]['pilot_label_catalog_coverage'],1)
        self.assertEqual(rows[1]['pilot_label_catalog_coverage'],0.5)
        self.assertEqual(rows[1]['pilot_history_prefixes'],1)

    def test_collision_target_group_is_explicit(self):
        content={'a':[10,20,30,40,1],'b':[10,20,30,41,1],'c':[11,20,30,40,1]}
        shuffled=content|{'c':[12,20,30,40,1]}
        counts=Counter(tuple(t[:3]) for t in content.values())
        self.assertEqual(mapping_group('a',content,shuffled,counts),'unchanged_collision_target')
        self.assertEqual(mapping_group('c',content,shuffled,counts),'changed_singleton_target')


if __name__=='__main__':unittest.main()
