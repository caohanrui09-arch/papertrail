"""CPU reconstruction of new512 paths, unchanged samples and common position priors."""
from collections import Counter,defaultdict
from datetime import datetime
import math
from pathlib import Path
import sys

from gsearch.quality_protocol import digest,save
from gsearch.sid_prior_probe import ROOT,DATA,read


def main() -> None:
    output=ROOT/'validation.json'
    if output.exists():raise FileExistsError('Preserve validation')
    protocol=read(ROOT/'protocol.json');execution=read(ROOT/'execution.json')
    for name,expected in protocol['files'].items():assert digest(Path(name))==expected,name
    assert execution['protocol_sha256']==digest(ROOT/'protocol.json') and execution['optimizer_updates']==0
    profiles=read(DATA/'profiles.json');prefixes=read(DATA/'prefixes.json');priors=read(DATA/'position-priors.json')
    assert profiles==read(Path('data/stage47-health/profiles.json')) and prefixes==read(Path('data/stage47-health/prefixes.json'))
    assert len(profiles)==len(prefixes)==32
    import json
    def json_rows(path):
        with Path(path).open(encoding='utf-8') as handle:
            for line in handle:
                if line.strip():yield json.loads(line)
    source_profiles={r['user_key']:r for r in json_rows('data/stage44-supervision/profiles.jsonl')}
    for length in [1,20]:
        rows=[r for r in profiles if r['history_length']==length];assert len(rows)==16
        assert {r['donor_user_key'] for r in rows}=={r['user_key'] for r in rows}
        assert Counter(tuple(r['original_history_doc_ids']) for r in rows)==Counter(tuple(r['swapped_history_doc_ids']) for r in rows)
        for row in rows:
            assert row['original_history_doc_ids']==source_profiles[row['user_key']]['history_doc_ids']
            assert row['swapped_history_doc_ids']==source_profiles[row['donor_user_key']]['history_doc_ids']
            assert row['seen_doc_ids']==source_profiles[row['user_key']]['seen_doc_ids']
            assert row['original_history_doc_ids']!=row['swapped_history_doc_ids']
    source=list(json_rows('data/stage44-supervision/train.next_item.jsonl'))
    by_sample={r['sample_id']:r for r in source};ordering=read(Path('data/stage45-sft/training-order.json'))
    label_counts={b:Counter(source[i]['target_doc_id'] for i in ordering['indices'][:b]) for b in [1024,4096]}
    selected={b:set(ordering['sample_ids'][:b]) for b in [1024,4096]}
    metadata={r['sample_id']:r for r in read(DATA/'prefix-exposure.json')}
    for row in prefixes:
        original=by_sample[row['sample_id']]
        assert all(row[k]==v for k,v in original.items())
        assert row['target_doc_id'] not in row['history_doc_ids']
        assert all(datetime.fromisoformat(t)<datetime.fromisoformat(row['target_at']) for t in row['history_ats'])
        meta=metadata[row['sample_id']];d=row['target_doc_id'];sid=row['sample_id']
        assert meta['target_label_count1024']==label_counts[1024][d] and meta['target_label_count4096']==label_counts[4096][d]
        assert meta['event_exposure']==('first1024' if sid in selected[1024] else 'added1025to4096' if sid in selected[4096] else 'not_selected4096')
        assert meta['target_paper_exposure']==('first1024' if label_counts[1024][d] else 'added1025to4096' if label_counts[4096][d] else 'not_labelled4096')
    profile_by_user={r['user_key']:r for r in profiles};prefix_by_id={r['sample_id']:r for r in prefixes}
    n_requests=n_prefix=n_ancestry=n_loss=n_reference=n_mean=0
    for run in protocol['models']:
        arm=run.split('-')[0];mapping=read(Path('data/stage45-sft')/(arm+'.tokens.json'))
        for b in [1024,4096]:
            for pos,prior in enumerate(priors[arm][str(b)]):
                allowed=sorted({v[pos] for v in mapping.values()});counts=Counter()
                for d,n in label_counts[b].items():counts[mapping[d][pos]]+=n
                assert prior['allowed_ids']==allowed and prior['label_counts']=={str(t):counts[t] for t in allowed}
                assert prior['total']==b and prior['alpha']==1
        history=read(DATA/run/'history-probe.json');loss=read(DATA/run/'position-loss.json');receipt=read(DATA/run/'receipt.json')
        reference=read(DATA/run/'reference128-rescored.json');old_loss=read(Path('data/stage47-health')/run/'position-loss.json')
        assert receipt['in_memory_weights_before_sha256']==receipt['in_memory_weights_after_sha256']
        assert receipt['all_gradients_none'] and receipt['all_parameters_frozen'] and receipt['digest_window']=='complete A+B'
        assert receipt['checkpoint_sha256_unchanged']==digest(Path('runs/stage48')/run/'checkpoint-512/model.safetensors')
        assert len(history['batches'])==4 and len(history['paired'])==32
        descendants=defaultdict(list)
        for d,tokens in mapping.items():
            for depth in range(5):descendants[tuple(tokens[:depth])].append(d)
        allowed_cache={}
        for batch in history['batches']:
            users=batch['users'];steps=batch['steps'];condition=batch['condition']
            assert len(users)==16 and len(steps)==5;n_requests+=16
            for depth,step in enumerate(steps):
                assert len(step['prefixes'])==len(step['finite_branch_counts'])==160
                for index,path in enumerate(step['prefixes']):
                    assert len(path)==depth+1 and path[0]==0
                    u=users[index//10];prefix=tuple(path[1:]);key=(u,prefix)
                    if key not in allowed_cache:
                        seen=set(profile_by_user[u]['seen_doc_ids'])
                        allowed_cache[key]={mapping[d][depth] for d in descendants[prefix] if d not in seen}
                    assert len(allowed_cache[key])==step['finite_branch_counts'][index]>0;n_prefix+=1
            for receiver,u in enumerate(users):
                trace=history['conditions'][condition][u]
                assert len(trace['doc_ids'])==len(set(trace['doc_ids']))==10
                assert not set(trace['doc_ids']).intersection(profile_by_user[u]['seen_doc_ids'])
                for rank,d in enumerate(trace['doc_ids']):
                    tokens=trace['token_ids'][rank];assert tokens==mapping[d] and len(tokens)==5 and tokens[-1]==1
                    assert abs(sum(trace['transition_scores'][rank])-trace['sequence_scores'][rank])<1e-4
                    for depth,parent in enumerate(trace['beam_indices'][rank]):
                        assert receiver*10<=parent<(receiver+1)*10 and steps[depth]['prefixes'][parent]==[0]+tokens[:depth]
                        assert tokens[depth] in allowed_cache[(u,tuple(tokens[:depth]))];n_ancestry+=1
        for row in history['paired']:
            u=row['user_key'];a=history['conditions']['original'][u]['doc_ids'];b=history['conditions']['swapped'][u]['doc_ids']
            shared=set(a)&set(b)
            assert row['jaccard']==len(shared)/len(set(a)|set(b)) and row['shared_items']==len(shared)
            assert row['top1_equal']==(a[0]==b[0]) and row['ordered_equal']==(a==b)
            aa={d:i+1 for i,d in enumerate(a)};bb={d:i+1 for i,d in enumerate(b)}
            assert abs(row['footrule_missing_rank11_div110']-sum(abs(aa.get(d,11)-bb.get(d,11)) for d in set(a)|set(b))/110)<1e-12
            assert row['newly_returned_donor_history_items']==len((set(b)-set(a))&set(profile_by_user[u]['swapped_history_doc_ids']))
        assert [r['sample_id'] for r in loss['samples']]==[r['sample_id'] for r in prefixes]
        assert [r['sample_id'] for r in reference['samples']]==[r['sample_id'] for r in prefixes]
        for budget,records in [(128,reference['samples']),(512,loss['samples'])]:
            for sample_index,sample in enumerate(records):
                raw=prefix_by_id[sample['sample_id']];target=mapping[raw['target_doc_id']]
                assert sample['exposure_group']==raw['exposure_group'] and sample['history_length']==raw['history_length']
                for pos,row in enumerate(sample['positions']):
                    assert row['target_token_id']==target[pos]
                    assert math.isfinite(row['full_vocab_nll']) and row['full_vocab_nll']>=0
                    assert 0<row['position_mass']<=1.00001
                    assert abs(row['full_vocab_nll']-row['position_conditional_nll']+math.log(row['position_mass']))<1e-4
                    for b in [1024,4096]:
                        p=priors[arm][str(b)][pos]
                        expected=math.log(b+len(p['allowed_ids']))-math.log(p['label_counts'][str(target[pos])]+1)
                        assert abs(row['label'+str(b)+'_position_prior_nll']-expected)<1e-12
                    expanded=priors[arm]['4096'][pos]
                    predict=sorted(expanded['allowed_ids'],key=lambda t:(-expanded['label_counts'][str(t)],t))[0]
                    assert row['label4096_prior_top1_correct']==(predict==target[pos])
                    assert abs(row['uniform_position_nll']-math.log(len(expanded['allowed_ids'])))<1e-12
                    if budget==128:
                        old=old_loss['samples'][sample_index]['positions'][pos]
                        assert all(row[k]==v for k,v in old.items() if k!='pilot_position_prior_nll')
                        assert abs(row['label1024_position_prior_nll']-old['pilot_position_prior_nll'])<1e-12;n_reference+=1
                    else:
                        assert abs(row['fp32_minus_native_amp_nll']-(row['full_vocab_nll']-row['native_amp_full_vocab_nll']))<1e-12;n_loss+=1
        assert len(loss['native_batch_checks'])==4
        for index,check in enumerate(loss['native_batch_checks']):
            samples=loss['samples'][index*8:(index+1)*8]
            amp=sum(p['native_amp_full_vocab_nll'] for r in samples for p in r['positions'])/40
            fp32=sum(p['full_vocab_nll'] for r in samples for p in r['positions'])/40
            assert abs(amp-check['native_loss'])<1e-4 and abs(fp32-check['fp32_unreduced_mean'])<1e-10
            assert abs(check['fp32_minus_native_amp_mean']-(fp32-check['native_loss']))<1e-10;n_mean+=1
    assert n_requests==384 and n_prefix==n_ancestry==19200 and n_loss==n_reference==960 and n_mean==24
    assert execution['beam_requests']==384 and execution['successful_teacher_forced_samples']==192
    assert execution['additional_model_forward_samples']==0
    assert 'torch' not in sys.modules and 'transformers' not in sys.modules
    save(output,{'status':'passed','unchanged_profiles':32,'unchanged_strict_prefixes':32,
        'beam_requests':n_requests,'legal_intermediate_prefixes':n_prefix,'native_ancestry_links':n_ancestry,
        'new_token_positions':n_loss,'old128_positions_prior_only_rescored':n_reference,'native_amp_mean_checks':n_mean,
        'frozen_checkpoints_unchanged':6,'old_losses_preserved':True,'source_only_two_priors_rebuilt':True,
        'full_vocabulary_logits_not_retained':True,'no_model_inference_in_validation':True})
    print(read(output),flush=True)


if __name__=='__main__':main()
