"""CPU-only independent checks of sampling, native beam ancestry and saved losses."""
from collections import Counter,defaultdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

from gsearch.quality_protocol import digest,save
from gsearch.supervision import json_rows

ROOT=Path('reports/stage47');DATA=Path('data/stage47-health')


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def key(kind,value):return hashlib.sha256(('stage47-source-only-20261104:'+kind+':'+value).encode()).hexdigest()


def main() -> None:
    target=ROOT/'validation.json'
    if target.exists():raise FileExistsError('Preserve validation')
    protocol=read(ROOT/'protocol.json');lock=read(ROOT/'continuation-lock.json');execution=read(ROOT/'execution.json')
    for path,expected in (protocol['files']|lock['files']).items():assert digest(Path(path))==expected,path
    assert execution['protocol_sha256']==digest(ROOT/'protocol.json')
    assert execution['continuation_lock_sha256']==digest(ROOT/'continuation-lock.json')
    profiles=read(DATA/'profiles.json');prefixes=read(DATA/'prefixes.json');priors=read(DATA/'position-priors.json')
    source_profiles={r['user_key']:r for r in json_rows(Path('data/stage44-supervision/profiles.jsonl'))}
    for length in [1,20]:
        expected=sorted((r for r in source_profiles.values() if r['eligible_train_positive_count']>0 and len(r['history_doc_ids'])==length),key=lambda r:key('profile',r['user_key']))[:16]
        actual=[r for r in profiles if r['history_length']==length]
        assert [r['user_key'] for r in actual]==[r['user_key'] for r in expected]
        assert set(r['donor_user_key'] for r in actual)==set(r['user_key'] for r in actual)
        assert Counter(tuple(r['original_history_doc_ids']) for r in actual)==Counter(tuple(r['swapped_history_doc_ids']) for r in actual)
        for row in actual:
            source=source_profiles[row['user_key']];donor=source_profiles[row['donor_user_key']]
            assert row['original_history_doc_ids']==source['history_doc_ids']
            assert row['swapped_history_doc_ids']==donor['history_doc_ids']
            assert row['seen_doc_ids']==source['seen_doc_ids']
            assert row['original_history_doc_ids']!=row['swapped_history_doc_ids']
    pilot=set(read('data/stage45-sft/training-order.json')['sample_ids'][:1024])
    chosen_ids={r['sample_id'] for r in prefixes};cells=defaultdict(list);source_samples={};pilot_counts=Counter()
    for row in json_rows(Path('data/stage44-supervision/train.next_item.jsonl')):
        exposure='pilot' if row['sample_id'] in pilot else 'pool_not_pilot'
        if exposure=='pilot':pilot_counts[row['target_doc_id']]+=1
        length=len(row['history_doc_ids'])
        if length in [1,20]:cells[(exposure,length)].append((key('prefix',row['sample_id']),row['sample_id']))
        if row['sample_id'] in chosen_ids:source_samples[row['sample_id']]=row
    for exposure in ['pilot','pool_not_pilot']:
        for length in [1,20]:
            expected=[sid for _,sid in sorted(cells[(exposure,length)])[:8]]
            actual=[r['sample_id'] for r in prefixes if r['exposure_group']==exposure and r['history_length']==length]
            assert expected==actual
    for row in prefixes:
        source=source_samples[row['sample_id']]
        assert all(row[field]==value for field,value in source.items())
        assert row['target_doc_id'] not in row['history_doc_ids']
        assert all(datetime.fromisoformat(t)<datetime.fromisoformat(row['target_at']) for t in row['history_ats'])
    source_by_user={r['user_key']:r for r in profiles};prefix_by_id={r['sample_id']:r for r in prefixes}
    ancestry_checks=0;prefix_checks=0;request_count=0;position_checks=0;native_batch_checks=0;weight_checks=0
    for run in protocol['models']:
        arm=run.split('-')[0];mapping=read(Path('data/stage45-sft')/(arm+'.tokens.json'))
        history=read(DATA/run/'history-probe.json');loss=read(DATA/run/'position-loss.json');receipt=read(DATA/run/'receipt.json')
        assert receipt['in_memory_weights_before_sha256']==receipt['in_memory_weights_after_sha256']
        assert receipt['all_gradients_none'] and receipt['all_parameters_frozen']
        assert receipt['checkpoint_sha256_unchanged']==digest(Path('runs/stage45')/run/'final/model.safetensors')
        weight_checks+=1
        assert len(history['batches'])==4 and len(history['paired'])==32
        groups=defaultdict(list)
        for doc,tokens in mapping.items():
            for depth in range(5):groups[tuple(tokens[:depth])].append(doc)
        allowed_cache={}
        for batch in history['batches']:
            condition=batch['condition'];users=batch['users'];steps=batch['steps']
            assert len(users)==16 and len(steps)==5
            request_count+=len(users)
            for step_index,step in enumerate(steps):
                assert len(step['prefixes'])==160 and len(step['finite_branch_counts'])==160
                for index,path in enumerate(step['prefixes']):
                    assert path[0]==0 and len(path)==step_index+1
                    user=users[index//10];prefix=tuple(path[1:]);cache=(user,prefix)
                    if cache not in allowed_cache:
                        seen=set(source_by_user[user]['seen_doc_ids'])
                        allowed_cache[cache]={mapping[d][len(prefix)] for d in groups[prefix] if d not in seen}
                    assert len(allowed_cache[cache])==step['finite_branch_counts'][index]>0
                    prefix_checks+=1
            for receiver,user in enumerate(users):
                trace=history['conditions'][condition][user]
                assert len(trace['doc_ids'])==10 and len(set(trace['doc_ids']))==10
                assert not set(trace['doc_ids']).intersection(source_by_user[user]['seen_doc_ids'])
                for rank,doc in enumerate(trace['doc_ids']):
                    tokens=trace['token_ids'][rank]
                    assert tokens==mapping[doc] and len(tokens)==5 and tokens[-1]==1
                    score=sum(trace['transition_scores'][rank]);assert abs(score-trace['sequence_scores'][rank])<1e-4
                    for step_index,parent in enumerate(trace['beam_indices'][rank]):
                        assert receiver*10<=parent<(receiver+1)*10
                        assert steps[step_index]['prefixes'][parent]==[0]+tokens[:step_index]
                        assert tokens[step_index] in allowed_cache[(user,tuple(tokens[:step_index]))]
                        ancestry_checks+=1
        for pair in history['paired']:
            user=pair['user_key'];a=history['conditions']['original'][user];b=history['conditions']['swapped'][user]
            aa=set(a['doc_ids']);bb=set(b['doc_ids']);shared=aa&bb
            assert pair['shared_items']==len(shared) and pair['jaccard']==len(shared)/len(aa|bb)
            assert pair['ordered_equal']==(a['doc_ids']==b['doc_ids'])
            assert pair['top1_equal']==(a['doc_ids'][0]==b['doc_ids'][0])
            ra={d:i+1 for i,d in enumerate(a['doc_ids'])};rb={d:i+1 for i,d in enumerate(b['doc_ids'])}
            expected=sum(abs(ra.get(d,11)-rb.get(d,11)) for d in aa|bb)/110
            assert abs(pair['footrule_missing_rank11_div110']-expected)<1e-12
            score_a=dict(zip(a['doc_ids'],a['sequence_scores']));score_b=dict(zip(b['doc_ids'],b['sequence_scores']))
            expected_delta=sum(abs(score_a[d]-score_b[d]) for d in shared)/len(shared) if shared else None
            assert pair['common_doc_mean_abs_sequence_score_change']==expected_delta
            added=(bb-aa)&set(source_by_user[user]['swapped_history_doc_ids'])
            assert pair['newly_returned_donor_history_items']==len(added)
        for position,prior in enumerate(priors[arm]):
            expected_counts=Counter()
            for doc,count in pilot_counts.items():expected_counts[mapping[doc][position]]+=count
            assert prior['pilot_counts']=={str(t):expected_counts[t] for t in prior['allowed_ids']}
        assert [r['sample_id'] for r in loss['samples']]==[r['sample_id'] for r in prefixes]
        for sample in loss['samples']:
            source=prefix_by_id[sample['sample_id']];target_tokens=mapping[source['target_doc_id']]
            assert sample['exposure_group']==source['exposure_group'] and sample['history_length']==source['history_length']
            for position,row in enumerate(sample['positions']):
                assert row['target_token_id']==target_tokens[position]
                assert math.isfinite(row['full_vocab_nll']) and row['full_vocab_nll']>=0
                assert 0<row['position_mass']<=1.00001
                assert abs(row['full_vocab_nll']-row['position_conditional_nll']+math.log(row['position_mass']))<1e-4
                prior=priors[arm][position];count=prior['pilot_counts'][str(target_tokens[position])]
                expected_prior=math.log(1024+len(prior['allowed_ids']))-math.log(count+1)
                assert abs(row['pilot_position_prior_nll']-expected_prior)<1e-12
                assert abs(row['uniform_position_nll']-math.log(len(prior['allowed_ids'])))<1e-12
                assert abs(row['fp32_minus_native_amp_nll']-(row['full_vocab_nll']-row['native_amp_full_vocab_nll']))<1e-12
                position_checks+=1
        for index,check in enumerate(loss['native_batch_checks']):
            records=loss['samples'][index*8:(index+1)*8]
            amp=sum(p['native_amp_full_vocab_nll'] for r in records for p in r['positions'])/40
            fp32=sum(p['full_vocab_nll'] for r in records for p in r['positions'])/40
            assert abs(amp-check['native_loss'])<1e-4
            assert abs(fp32-check['fp32_unreduced_mean'])<1e-10
            assert abs(check['fp32_minus_native_amp_mean']-(fp32-check['native_loss']))<1e-10
            native_batch_checks+=1
    assert request_count==384 and ancestry_checks==prefix_checks==19200 and position_checks==960
    assert execution['new_beam_requests_in_continuation']+execution['reused_beam_requests']==384
    assert execution['successful_teacher_forced_samples']==192 and execution['optimizer_updates']==0
    assert execution['teacher_forward_attempt_samples_upper_bound']==192+lock['numerical_diagnostic_forward_samples']+lock['interrupted_teacher_samples_upper_bound']
    save(target,{'status':'passed','profiles_source_and_same_length_permutation':32,'strict_prefix_sources':32,
        'beam_requests':request_count,'legal_intermediate_prefixes':prefix_checks,'native_ancestry_links':ancestry_checks,
        'token_position_records':position_checks,'native_amp_mean_checks':native_batch_checks,'weight_digests_unchanged':weight_checks,
        'loss_check':'native AMP unreduced mean vs native AMP loss; FP32 decomposition labelled separately',
        'full_vocabulary_logits_not_retained':True,'no_reinference_or_optimization_in_validation':True})
    print({'validation':'passed','beam_requests':request_count,'ancestry_links':ancestry_checks,
           'positions':position_checks,'weight_digests_unchanged':weight_checks},flush=True)


if __name__=='__main__':main()
