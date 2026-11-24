"""Independent source/output checks after training and scoring; no GPU imports."""
from pathlib import Path
import subprocess
import sys

from gsearch.quality_protocol import digest, save
from gsearch.sid_budget import ROOT, DATA, RUNS, SEEDS, ARMS, read, require_reference, verify_seen_order, check_resources
from gsearch.supervision import json_rows


def main() -> None:
    target=ROOT/'validation.json'
    if target.exists(): raise FileExistsError('Preserve independent validation')
    subprocess.run([sys.executable,'-E','-s','-m','scripts.verify_sid_health_probe'],check=True)
    protocol=read(ROOT/'protocol.json')
    for name,expected in protocol['files'].items(): assert digest(Path(name))==expected,name
    assert read(ROOT/'run-lock.json')['protocol_sha256']==digest(ROOT/'protocol.json')
    assert read(ROOT/'training-complete.json')['all_six_reference128_gates_passed']
    old_order=read(Path('data/stage45-sft/training-order.json'))
    order=read(DATA/'order.json')
    assert order['indices']==old_order['indices'][:4096] and order['sample_ids']==old_order['sample_ids'][:4096]
    source=list(json_rows(Path('data/stage44-supervision/train.next_item.jsonl')))
    prefix=read(Path('reports/stage45/tokenization.json'))['prefix_ids']
    rows_reconstructed=0
    for arm in ARMS:
        mapping=read(Path('data/stage45-sft')/(arm+'.tokens.json'))
        rows=list(json_rows(DATA/(arm+'.ordered.jsonl')))
        assert len(rows)==4096
        for row,index in zip(rows,order['indices']):
            raw=source[index]
            tokens=prefix+[t for d in raw['history_doc_ids'][-20:] for t in mapping[d][:-1]]+[1]
            assert row['sample_id']==raw['sample_id']
            assert row['input_ids']==tokens+[0]*(96-len(tokens))
            assert row['attention_mask']==[1]*len(tokens)+[0]*(96-len(tokens))
            assert row['labels']==mapping[raw['target_doc_id']]
            rows_reconstructed+=1
    inputs=list(json_rows(Path('data/stage44-supervision/tuning.inputs.jsonl')))
    profiles={r['user_key']:r for r in json_rows(Path('data/stage44-supervision/profiles.jsonl'))}
    old_results=read(Path('reports/stage45/tuning-results.json'))
    assert not old_results['dev_evaluated']
    prediction_rows=paths=checkpoint_files=0
    for seed in SEEDS:
        for arm in ARMS:
            name=arm+'-'+str(seed); output=RUNS/name
            receipt=read(output/'training.json')
            assert receipt['optimizer_updates']==512 and receipt['samples']==4096
            verify_seen_order(receipt['observed_order'],4096)
            require_reference(receipt['log_history'],read(Path('runs/stage45')/name/'training.json')['log_history'])
            check_resources(receipt,receipt['elapsed_seconds'],protocol['resource_caps'])
            gate=read(output/'reference128-gate.json')
            assert gate['all_tensors_bitwise_equal'] and gate['native_loss_grad_lr_log_checks']==8
            assert gate['reference_checkpoint_sha256']==digest(Path('runs/stage45')/name/'final/model.safetensors')
            assert gate['new_checkpoint_sha256']==digest(output/'checkpoint-128/model.safetensors')
            for step in [128,512]:
                native=read(output/('checkpoint-'+str(step))/'trainer_state.json')
                assert native['global_step']==step
                cp_receipt=read(output/('checkpoint-'+str(step)+'-receipt.json'))
                for p,h in cp_receipt['files'].items(): assert digest(Path(p))==h,p; checkpoint_files+=1
            assert digest(output/'checkpoint-512/model.safetensors')==receipt['model_sha256']
            mapping=read(Path('data/stage45-sft')/(arm+'.tokens.json'))
            raw=read(output/'raw-user-decoding.json')
            for user,row in raw.items():
                assert len(row['doc_ids'])==len(set(row['doc_ids']))==10
                assert not set(row['doc_ids']).intersection(profiles.get(user,{}).get('seen_doc_ids',[]))
                assert set(row['doc_ids']).issubset(mapping)
                if not row['fallback']:
                    assert row['token_ids']==[mapping[d] for d in row['doc_ids']]
                    paths+=len(row['token_ids'])
            predictions=list(json_rows(output/'tuning.predictions.jsonl'))
            assert len(predictions)==len(inputs)==46352
            for pred,inp in zip(predictions,inputs):
                assert pred['qid']==inp['qid'] and pred['doc_ids']==raw[inp['user_key']]['doc_ids']
                prediction_rows+=1
            cost=read(output/'prediction-cost.json')
            assert cost['predictions_sha256']==digest(output/'tuning.predictions.jsonl')
            assert cost['neural_users']==2128 and cost['shared_fallback_users']==1443
            score=read(ROOT/(name+'.tuning.score.json'))
            assert score['events']==46352 and score['native512_slice_exact'] and score['native_slice_events']==512
            assert score['valid_slot_rate']==1 and score['duplicate_slot_rate']==0
            assert score['groups']['user:cold']==read(Path('reports/stage45')/(name+'.tuning.score.json'))['groups']['user:cold']
            assert score['conditional_diagnostic']['events']==1801
    result=read(ROOT/'tuning-results.json')
    assert not result['dev_evaluated'] and not result['rl_started'] and not result['significance_claim']
    assert 'torch' not in sys.modules and 'transformers' not in sys.modules
    save(target,{'status':'passed','reconstructed_training_token_rows':rows_reconstructed,
        'native_checkpoint_files_verified':checkpoint_files,'full_prediction_event_rows':prediction_rows,
        'unique_profile_neural_paths':paths,'reference128_runs':6,'native_scorer_slices':6,
        'native_scorer_slice_events_each':512,'cold_user_fallback_unchanged':True,
        'prior_assets_unchanged':399,'torch_loaded':False,'dev_evaluated':False,'rl_started':False})
    print(read(target),flush=True)


if __name__=='__main__': main()
