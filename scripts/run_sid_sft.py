"""Locked local pilot: native Seq2SeqTrainer; prediction and scoring are separate."""
import argparse
import gc
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import time

os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
os.environ.setdefault('HF_HUB_OFFLINE','1')
os.environ.setdefault('TOKENIZERS_PARALLELISM','false')

import psutil
import torch
from transformers import Seq2SeqTrainer, Seq2SeqTrainingArguments, default_data_collator, enable_full_determinism

from gsearch.quality_protocol import digest, save
from gsearch.sid_sft import (DATA, REPORT, BASE, load, input_tokens, fresh_model,
    CatalogConstraint, decode_batch, OrderedExamples, verify_lock, json_rows)


def arguments(output: Path, seed: int, steps: int) -> Seq2SeqTrainingArguments:
    return Seq2SeqTrainingArguments(output_dir=str(output),max_steps=steps,per_device_train_batch_size=8,
        gradient_accumulation_steps=1,learning_rate=0.0005,weight_decay=0.01,
        adam_beta1=0.9,adam_beta2=0.999,adam_epsilon=1e-8,optim='adamw_torch',
        lr_scheduler_type='constant',warmup_steps=0,max_grad_norm=1.0,
        bf16=True,tf32=False,seed=seed,data_seed=271828,full_determinism=True,
        save_strategy='no',eval_strategy='no',logging_strategy='steps',logging_steps=16,
        report_to=[],disable_tqdm=True,dataloader_num_workers=0,dataloader_pin_memory=False,
        remove_unused_columns=False,save_safetensors=True)


def peak() -> dict:
    return {'gpu_allocated_bytes':torch.cuda.max_memory_allocated(),
            'gpu_reserved_bytes':torch.cuda.max_memory_reserved(),
            'process_peak_bytes':psutil.Process().memory_info().peak_wset}


def release() -> None:
    gc.collect();torch.cuda.empty_cache()


def preflight() -> None:
    if (REPORT/'preflight.json').exists() or (REPORT/'run-lock.json').exists():
        raise FileExistsError('Preflight already completed')
    token=load(REPORT/'tokenization.json');design=load(REPORT/'design.json')
    assert torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    checks=[]; costs=[]; initials={}
    profiles=list(json_rows(Path('data/stage44-supervision/profiles.jsonl')))
    chosen=sorted((p for p in profiles if p['history_doc_ids']),key=lambda p:(-len(p['history_doc_ids']),p['user_key']))[:8]
    for arm in ['content','shuffled']:
        enable_full_determinism(42)
        model,tokenizer,initial=fresh_model(42);initials[arm]=initial
        model=model.cuda().train();torch.cuda.reset_peak_memory_stats()
        mapping=load(DATA/(arm+'.tokens.json'))
        rows=[]
        for row in json_rows(DATA/(arm+'.train.tokens.jsonl')):
            rows.append({k:row[k] for k in ['input_ids','attention_mask','labels']})
            if len(rows)==32:break
        start=time.perf_counter();losses=[]
        # Dry backward only; no optimizer update, checkpoint or fitted state is retained.
        for index in range(4):
            model.zero_grad(set_to_none=True)
            batch={k:v.cuda() for k,v in default_data_collator(rows[index*8:(index+1)*8]).items()}
            with torch.autocast('cuda',dtype=torch.bfloat16):
                loss=model(**batch).loss
            assert torch.isfinite(loss)
            loss.backward();losses.append(float(loss.detach()))
            assert all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None)
        torch.cuda.synchronize()
        elapsed=time.perf_counter()-start
        model.zero_grad(set_to_none=True)
        constraint=CatalogConstraint(mapping,tokenizer)
        histories=[p['history_doc_ids'] for p in chosen];seen=[set(p['seen_doc_ids']) for p in chosen]
        decode_start=time.perf_counter()
        result=decode_batch(model,tokenizer,constraint,histories,seen,mapping,token['prefix_ids'])
        repeated=decode_batch(model,tokenizer,constraint,histories[:1],seen[:1],mapping,token['prefix_ids'])
        assert result[0]==repeated[0]
        # Explicit adversarial filter case: mask every previously returned result.
        masked=decode_batch(model,tokenizer,constraint,histories[:1],
            [seen[0]|set(result[0]['doc_ids'])],mapping,token['prefix_ids'])
        assert not set(masked[0]['doc_ids']).intersection(result[0]['doc_ids'])
        torch.cuda.synchronize()
        measured=peak();parameter_bytes=sum(p.numel()*p.element_size() for p in model.parameters())
        # Add two FP32 Adam moments and one parameter-sized temporary to dry-run peak.
        reserved_estimate=measured['gpu_reserved_bytes']+3*parameter_bytes
        passed=reserved_estimate<6.5*2**30 and measured['process_peak_bytes']<12*2**30
        costs.append({'arm':arm,'dry_backward_only_seconds':elapsed,'dry_losses':losses,
            'decode_10_requests_seconds':time.perf_counter()-decode_start,**measured,
            'parameter_bytes':parameter_bytes,'conservative_training_reserved_estimate_bytes':reserved_estimate,
            'estimated_six_runs_training_seconds':elapsed/4*128*6*2,
            'estimate_method':'dry forward/backward extrapolation x2 optimizer/startup allowance; not measured training',
            'passed':passed})
        assert passed and costs[-1]['estimated_six_runs_training_seconds']<3600
        checks.append({'arm':arm,'eos_unique_top10':True,'full_catalog_constraint':True,'seen_negative_and_positive_mask':True,
                       'repeat_identical':True,'adversarial_seen_filter':True,'raw_decodes':result})
        del model,constraint,batch,loss;release()
    assert initials['content']==initials['shuffled']
    save(DATA/'preflight-raw.json',checks)
    save(REPORT/'preflight.json',{'passed':True,'model_training_updates':0,'dry_backward_batches_per_arm':4,
        'scope':'discarded dry gradients, no optimizer steps or tuning labels; same fresh base in both arms',
        'initial_embedding_sha256':initials,'tokenizer_eos_beam_filter_passed':True,'costs':costs,
        'raw_trace_sha256':digest(DATA/'preflight-raw.json'),'gpu':torch.cuda.get_device_name(),
        'versions':{name:importlib.metadata.version(name) for name in ['torch','transformers','accelerate','safetensors']}})
    print({'preflight':'passed','costs':costs},flush=True)


def freeze() -> None:
    if (REPORT/'run-lock.json').exists():raise FileExistsError('Run already frozen')
    assert load(REPORT/'preflight.json')['passed']
    source=load(BASE/'source.json');tokens=load(REPORT/'tokenization.json')
    for row in source['files']:
        assert digest(BASE/row['file'])==row['sha256']
    files=[REPORT/'design.json',REPORT/'sid-results.json',REPORT/'tokenization.json',REPORT/'preflight.json',
           DATA/'training-order.json',DATA/'content.tokens.json',DATA/'shuffled.tokens.json',
           DATA/'content.train.tokens.jsonl',DATA/'shuffled.train.tokens.jsonl',BASE/'source.json',
           Path('gsearch/sid_sft.py'),Path('scripts/run_sid_sft.py'),Path('scripts/tokenize_sid_sft.py'),
           Path('scripts/prepare_sid_sft.py'),Path('scripts/baseline_sid_sft.py'),
           REPORT/'baseline-design.json',REPORT/'data-validation.json',Path('tests/test_sid_sft.py'),
           Path('gsearch/prefix_decoder.py')]
    files.extend(p for p in (DATA/'tokenizer').iterdir() if p.is_file())
    files.extend(BASE/r['file'] for r in source['files'])
    files.extend([Path('reports/stage44/evaluation-lock.json'),Path('data/stage44-supervision/build-receipt.json')])
    files.extend(Path('data/stage44-supervision')/name for name in ['profiles.jsonl','tuning.inputs.jsonl',
        'catalog.json','train.feedback.jsonl','popularity.json'])
    files.extend(p for p in Path('third_party/minionerec_sid_cpu').glob('*.py'))
    files.extend([Path('third_party/zerogr_prefix/tree.py'),Path('reports/stage7/upstream-audit.json')])
    lock=load(Path('reports/stage44/run-lock.template.json'))
    lock.update(template_only=False,base_model_revision=source['revision'],base_weights_sha256=digest(BASE/'model.safetensors'),
        tokenizer_sha256=hashlib.sha256(json.dumps(tokens['tokenizer_files'],sort_keys=True).encode()).hexdigest(),
        content_mapping_sha256=digest(DATA/'content.tokens.json'),shuffled_mapping_sha256=digest(DATA/'shuffled.tokens.json'),
        ordered_training_sample_ids_sha256=digest(DATA/'training-order.json'),optimizer_updates=128,effective_batch=8,
        seed_schedule=[42,2024,3407],precision='bf16',learning_rate=0.0005,checkpoint_steps=[128],
        optimizer={'name':'adamw_torch','beta1':0.9,'beta2':0.999,'eps':1e-8,'weight_decay':0.01,
                   'scheduler':'constant','warmup_steps':0,'max_grad_norm':1.0},
        input_target_token_id_contract={'labels':'token_ids','prompt_loss_mask':-100,'eos_required':True,
            'architecture':'encoder-decoder; no encoder prompt tokens in decoder labels','prefix_ids':tokens['prefix_ids'],
            'max_input_tokens':96,'target_tokens_including_eos':tokens['max_target_tokens']},
        resource_preflight_passed=True,real_tokenizer_and_decode_preflight_passed=True,frozen_before_training=True,
        preflight_sha256=digest(REPORT/'preflight.json'),files={str(p):digest(p) for p in sorted(files)},
        actual_training_samples_per_run=1024,total_training_pool=98887,
        actual_supervised_tokens_per_run=1024*tokens['max_target_tokens'],
        training_data_selection='first 1024 of frozen seed271828 permutation; native finite iterable stream, same all arms/seeds',
        stage='small_budget_pilot_not_full_training',descriptive_dev_planned=False,
        frozen_unix=time.time())
    save(REPORT/'run-lock.json',lock)
    verify_lock()
    print({'run_lock':'frozen','sha256':digest(REPORT/'run-lock.json')},flush=True)


def train() -> None:
    lock=verify_lock();ordering=load(DATA/'training-order.json');order=ordering['indices'][:1024]
    for seed in lock['seed_schedule']:
        hashes={}
        for arm in ['content','shuffled']:
            output=Path('runs/stage45')/(arm+'-'+str(seed))
            if output.exists():raise FileExistsError('Preserve prior pilot including failures: '+str(output))
            pool=list(json_rows(DATA/(arm+'.train.tokens.jsonl')))
            rows=[pool[i] for i in order];del pool
            assert [r['sample_id'] for r in rows]==ordering['sample_ids'][:1024]
            dataset=OrderedExamples(rows)
            enable_full_determinism(seed)
            model,tokenizer,initial=fresh_model(seed);hashes[arm]=initial
            trainer=Seq2SeqTrainer(model=model,args=arguments(output,seed,128),train_dataset=dataset,
                                   data_collator=default_data_collator,processing_class=tokenizer)
            torch.cuda.reset_peak_memory_stats();start=time.perf_counter()
            result=trainer.train()
            torch.cuda.synchronize();elapsed=time.perf_counter()-start
            assert trainer.state.global_step==128 and dataset.observed==list(range(1024))
            measured=peak()
            assert measured['gpu_reserved_bytes']<6.5*2**30 and measured['process_peak_bytes']<12*2**30
            trainer.save_model(str(output/'final'))
            save(output/'training.json',{'arm':arm,'seed':seed,'run_lock_sha256':digest(REPORT/'run-lock.json'),
                'initial_embedding_sha256':initial,'optimizer_updates':trainer.state.global_step,'samples':1024,
                'supervised_tokens':sum(len(r['labels']) for r in rows),'observed_exact_order':True,
                'elapsed_seconds':elapsed,**measured,'trainer_metrics':result.metrics,
                'log_history':trainer.state.log_history,'model_sha256':digest(output/'final/model.safetensors'),
                'completed_unix':time.time()})
            print({'completed':str(output),'seconds':elapsed,**measured},flush=True)
            del trainer,model,dataset,rows,result;release()
        assert hashes['content']==hashes['shuffled']
    save(REPORT/'training-complete.json',{'runs':6,'all_initializations_paired':True,'run_lock_sha256':digest(REPORT/'run-lock.json'),
        'runs_receipts':{str(p):digest(p) for p in sorted(Path('runs/stage45').glob('*/training.json'))}})


def predict() -> None:
    lock=verify_lock();token=load(REPORT/'tokenization.json')
    profiles={p['user_key']:p for p in json_rows(Path('data/stage44-supervision/profiles.jsonl'))}
    inputs=list(json_rows(Path('data/stage44-supervision/tuning.inputs.jsonl')))
    users=sorted({r['user_key'] for r in inputs})
    counts=load(Path('data/stage44-supervision/popularity.json'))['counts']
    catalog=set(load(DATA/'content.tokens.json'))
    fallback={user:sorted(catalog-set(profiles.get(user,{}).get('seen_doc_ids',[])),key=lambda d:(-counts.get(d,0),d))[:10]
              for user in users if not profiles.get(user,{}).get('eligible_train_positive_count',0)}
    active=[user for user in users if user not in fallback]
    for seed in lock['seed_schedule']:
        for arm in ['content','shuffled']:
            output=Path('runs/stage45')/(arm+'-'+str(seed));path=output/'tuning.predictions.jsonl'
            if path.exists():raise FileExistsError('Predictions already exist')
            from transformers import AutoModelForSeq2SeqLM,AutoTokenizer
            tokenizer=AutoTokenizer.from_pretrained(DATA/'tokenizer',local_files_only=True)
            enable_full_determinism(seed)
            model=AutoModelForSeq2SeqLM.from_pretrained(output/'final',local_files_only=True,attn_implementation='eager').cuda()
            mapping=load(DATA/(arm+'.tokens.json'));constraint=CatalogConstraint(mapping,tokenizer)
            predictions={u:{'doc_ids':d,'fallback':True} for u,d in fallback.items()};times=[]
            torch.cuda.reset_peak_memory_stats();started=time.perf_counter()
            for start in range(0,len(active),16):
                batch_users=active[start:start+16]
                histories=[profiles[u]['history_doc_ids'] for u in batch_users]
                seen=[set(profiles[u]['seen_doc_ids']) for u in batch_users]
                torch.cuda.synchronize();clock=time.perf_counter()
                batch=decode_batch(model,tokenizer,constraint,histories,seen,mapping,token['prefix_ids'])
                torch.cuda.synchronize();seconds=time.perf_counter()-clock
                times.append({'requests':len(batch_users),'seconds':seconds})
                for u,result in zip(batch_users,batch):predictions[u]=result|{'fallback':False}
                if start%256==0:print({'predict':arm,'seed':seed,'users':min(start+16,len(active)),'total':len(active)},flush=True)
                if time.perf_counter()-started>3600:raise TimeoutError('Evaluation resource gate')
            with path.open('x',encoding='utf-8',newline='\n') as handle:
                for row in inputs:
                    handle.write(json.dumps({'qid':row['qid'],'doc_ids':predictions[row['user_key']]['doc_ids']},separators=(',',':'))+'\n')
            save(output/'raw-user-decoding.json',predictions)
            save(output/'prediction-cost.json',{'unique_users':len(users),'neural_users':len(active),'shared_fallback_users':len(fallback),
                'events':len(inputs),'elapsed_seconds':time.perf_counter()-started,'batch_size':16,'batches':times,
                'neural_amortized_seconds_per_user':sum(t['seconds'] for t in times)/len(active),
                'cost_scope':'offline batched prediction, fixed-profile reuse; not interactive request p95 or production QPS',
                'predictions_sha256':digest(path),**peak()})
            del model,constraint;release()


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['tokenize','preflight','freeze','train','predict','pipeline'])
    args=parser.parse_args();torch.set_num_threads(4)
    if args.action in ['tokenize','pipeline']:
        from scripts.tokenize_sid_sft import main as tokenize
        tokenize()
    if args.action in ['preflight','pipeline']:preflight()
    if args.action in ['freeze','pipeline']:freeze()
    if args.action in ['train','pipeline']:train()
    if args.action in ['predict','pipeline']:predict()


if __name__=='__main__':
    main()
