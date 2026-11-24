"""Native Trainer budget comparison with exact 128-step reference gates."""
import argparse
import json
import os
from pathlib import Path
import time

os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')

import torch
from safetensors.torch import load_file
from transformers import Seq2SeqTrainer, TrainerCallback, default_data_collator, enable_full_determinism
from gsearch.quality_protocol import digest, save
from gsearch.sid_budget import ROOT, DATA, RUNS, SEEDS, ARMS, read, require_reference, verify_seen_order, check_resources
from gsearch.sid_sft import fresh_model, OrderedExamples, json_rows
from scripts.run_sid_sft import arguments, peak, release


def verified_protocol() -> dict:
    value = read(ROOT/'protocol.json')
    for name, expected in value['files'].items(): assert digest(Path(name)) == expected, name
    return value


class Checkpoints(TrainerCallback):
    def __init__(self, output: Path, protocol: dict, started: float):
        self.output, self.protocol, self.started = output, protocol, started
        self.gates = []

    def on_step_end(self, args, state, control, **kwargs):
        if state.global_step % 16 == 0:
            check_resources(peak(), time.perf_counter()-self.started, self.protocol['resource_caps'])
        control.should_save = state.global_step in [128,512]
        return control

    def on_save(self, args, state, control, **kwargs):
        step = state.global_step
        checkpoint = self.output / ('checkpoint-'+str(step))
        required = ['model.safetensors','optimizer.pt','scheduler.pt','rng_state.pth','trainer_state.json','training_args.bin']
        assert all((checkpoint/name).is_file() for name in required)
        assert read(checkpoint/'trainer_state.json')['global_step'] == step
        measured = peak(); elapsed = time.perf_counter()-self.started
        check_resources(measured, elapsed, self.protocol['resource_caps'])
        if step == 128:
            reference = Path('runs/stage45')/self.output.name
            old = load_file(str(reference/'final/model.safetensors'))
            new = load_file(str(checkpoint/'model.safetensors'))
            assert set(old) == set(new), 'Reference tensor keys changed'
            mismatch = [name for name in old if not torch.equal(old[name], new[name])]
            if mismatch:
                save(self.output/'reference-failure.json', {'status':'failed','step':128,
                    'mismatched_tensors':mismatch,'reason':'exact reproduction gate; no512 allowed'})
                raise RuntimeError('128 reference not bitwise reproduced')
            checks = require_reference(state.log_history, read(reference/'training.json')['log_history'])
            gate = {'status':'passed','step':128,'tensor_count':len(old),'all_tensors_bitwise_equal':True,
                'native_loss_grad_lr_log_checks':checks, 'reference_checkpoint_sha256':digest(reference/'final/model.safetensors'),
                'new_checkpoint_sha256':digest(checkpoint/'model.safetensors'), 'elapsed_seconds':elapsed, **measured}
            del old,new
            save(self.output/'reference128-gate.json', gate)
            self.gates.append(gate)
            if not (ROOT/'run-lock.json').exists():
                assert self.output.name == 'content-42'
                save(ROOT/'run-lock.json', {'frozen_before_first_step129':True,
                    'protocol_sha256':digest(ROOT/'protocol.json'), 'resource_and_reference_preflight_passed':True,
                    'preflight_gate_sha256':digest(self.output/'reference128-gate.json'),
                    'reference_model128_sha256':digest(checkpoint/'model.safetensors'),
                    'max_steps':512, 'batch':8, 'seeds':SEEDS, 'arms':ARMS,
                    'allowed_checkpoints':[128,512], 'no_dev_or_rl':True})
        save(self.output/('checkpoint-'+str(step)+'-receipt.json'), {'step':step,
            'protocol_sha256':digest(ROOT/'protocol.json'), 'files':{str(p):digest(p) for p in sorted(checkpoint.iterdir()) if p.is_file()}})
        print({'checkpoint':str(checkpoint), 'reference128_gate':step==128, 'seconds':elapsed, **measured}, flush=True)
        return control


def train() -> None:
    protocol = verified_protocol()
    assert not (ROOT/'training-complete.json').exists()
    assert torch.__version__ == '2.6.0+cu124'
    import transformers
    assert transformers.__version__ == '4.57.1'
    assert torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    ordering = read(DATA/'order.json')
    initializations = {}
    for seed in SEEDS:
        for arm in ARMS:
            output = RUNS/(arm+'-'+str(seed))
            if output.exists(): raise FileExistsError('Do not overwrite any prior attempt: '+str(output))
            rows = list(json_rows(DATA/(arm+'.ordered.jsonl')))
            assert [r['sample_id'] for r in rows] == ordering['sample_ids']
            dataset = OrderedExamples(rows)
            enable_full_determinism(seed)
            model, tokenizer, initial = fresh_model(seed)
            assert initial == read(Path('runs/stage45')/output.name/'training.json')['initial_embedding_sha256']
            initializations[output.name] = initial
            started = time.perf_counter(); callback = Checkpoints(output,protocol,started)
            trainer = Seq2SeqTrainer(model=model, args=arguments(output, seed, 512), train_dataset=dataset,
                data_collator=default_data_collator, processing_class=tokenizer, callbacks=[callback])
            torch.cuda.reset_peak_memory_stats()
            result = trainer.train()
            torch.cuda.synchronize(); elapsed = time.perf_counter()-started
            assert trainer.state.global_step == 512
            verify_seen_order(dataset.observed,4096)
            measured = peak(); check_resources(measured,elapsed,protocol['resource_caps'])
            assert read(output/'reference128-gate.json')['all_tensors_bitwise_equal']
            save(output/'training.json', {'arm':arm,'seed':seed,'optimizer_updates':512,'samples':4096,
                'supervised_tokens':20480,'initial_embedding_sha256':initial,'observed_exact_order':True,
                'observed_order':dataset.observed,'source_order_sha256':digest(DATA/'order.json'),
                'protocol_sha256':digest(ROOT/'protocol.json'),'run_lock_sha256':digest(ROOT/'run-lock.json'),
                'elapsed_seconds':elapsed,**measured,'trainer_metrics':result.metrics,
                'log_history':trainer.state.log_history,'model_sha256':digest(output/'checkpoint-512/model.safetensors')})
            print({'training_completed':output.name,'steps':512,'seconds':elapsed},flush=True)
            del trainer, model, dataset, rows, result, callback; release()
        assert initializations['content-'+str(seed)] == initializations['shuffled-'+str(seed)]
    save(ROOT/'training-complete.json', {'status':'passed','runs':6,'updates_per_run':512,
        'all_six_reference128_gates_passed':True,'initializations':initializations,
        'run_receipts':{str(p):digest(p) for p in sorted(RUNS.glob('*/training.json'))},
        'dev_evaluated':False,'rl_started':False})


def predict() -> None:
    verified_protocol()
    assert read(ROOT/'training-complete.json')['all_six_reference128_gates_passed']
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    from gsearch.sid_sft import CatalogConstraint, decode_batch
    profiles = {r['user_key']:r for r in json_rows(Path('data/stage44-supervision/profiles.jsonl'))}
    inputs = list(json_rows(Path('data/stage44-supervision/tuning.inputs.jsonl')))
    users = sorted({r['user_key'] for r in inputs})
    counts = read(Path('data/stage44-supervision/popularity.json'))['counts']
    catalog = set(read(Path('data/stage45-sft/content.tokens.json')))
    fallback = {u:sorted(catalog-set(profiles.get(u,{}).get('seen_doc_ids',[])),key=lambda d:(-counts.get(d,0),d))[:10]
        for u in users if not profiles.get(u,{}).get('eligible_train_positive_count',0)}
    active = [u for u in users if u not in fallback]
    prefix = read(Path('reports/stage45/tokenization.json'))['prefix_ids']
    for seed in SEEDS:
        for arm in ARMS:
            output = RUNS/(arm+'-'+str(seed)); path = output/'tuning.predictions.jsonl'
            if path.exists(): raise FileExistsError('Preserve predictions '+str(path))
            tokenizer = AutoTokenizer.from_pretrained('data/stage45-sft/tokenizer',local_files_only=True)
            enable_full_determinism(seed)
            model = AutoModelForSeq2SeqLM.from_pretrained(output/'checkpoint-512',local_files_only=True,attn_implementation='eager').cuda()
            mapping = read(Path('data/stage45-sft')/(arm+'.tokens.json'))
            constraint = CatalogConstraint(mapping,tokenizer)
            predictions = {u:{'doc_ids':v,'fallback':True} for u,v in fallback.items()}
            times=[]; torch.cuda.reset_peak_memory_stats(); started=time.perf_counter()
            for start in range(0,len(active),16):
                batch_users=active[start:start+16]
                torch.cuda.synchronize(); clock=time.perf_counter()
                batch=decode_batch(model,tokenizer,constraint,[profiles[u]['history_doc_ids'] for u in batch_users],
                    [set(profiles[u]['seen_doc_ids']) for u in batch_users],mapping,prefix)
                torch.cuda.synchronize()
                times.append({'requests':len(batch_users),'seconds':time.perf_counter()-clock})
                for u,r in zip(batch_users,batch): predictions[u]=r|{'fallback':False}
                if start%256==0: print({'predict':output.name,'users':min(start+16,len(active)),'total':len(active)},flush=True)
                if time.perf_counter()-started>900: raise TimeoutError('Prediction900s cap')
            with path.open('x',encoding='utf-8',newline='\n') as handle:
                for r in inputs: handle.write(json.dumps({'qid':r['qid'],'doc_ids':predictions[r['user_key']]['doc_ids']},separators=(',',':'))+'\n')
            save(output/'raw-user-decoding.json',predictions)
            save(output/'prediction-cost.json', {'unique_users':len(users),'neural_users':len(active),'shared_fallback_users':len(fallback),
                'events':len(inputs),'elapsed_seconds':time.perf_counter()-started,'batch_size':16,'batches':times,
                'neural_amortized_seconds_per_user':sum(r['seconds'] for r in times)/len(active), **peak(),
                'predictions_sha256':digest(path),'model_sha256':digest(output/'checkpoint-512/model.safetensors'),
                'scope':'offline batched profile reuse, not production QPS or interactive p95'})
            del model,constraint; release()


def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument('action',choices=['train','predict']); args=parser.parse_args()
    torch.set_num_threads(4)
    (train if args.action=='train' else predict)()


if __name__=='__main__': main()
