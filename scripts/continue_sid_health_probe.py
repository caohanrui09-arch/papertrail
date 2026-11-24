"""Continue the identical frozen probe; align native-loss checks to native AMP."""
import gc
import io
import json
import os
from pathlib import Path
import time
import unittest

os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
os.environ.setdefault('HF_HUB_OFFLINE','1')
os.environ.setdefault('TOKENIZERS_PARALLELISM','false')

import psutil
import torch
from torch.nn import functional as F
from transformers import AutoModelForSeq2SeqLM,AutoTokenizer,default_data_collator,enable_full_determinism

from gsearch.quality_protocol import digest,save
from gsearch.sid_sft import CatalogConstraint,input_tokens,fixed_features
from gsearch.sid_health_probe import observed_decode,token_diagnostics,paired_rank_metrics,parameter_fingerprint

ROOT=Path('reports/stage47');DATA=Path('data/stage47-health')


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def main() -> None:
    if (ROOT/'execution.json').exists():raise FileExistsError('Preserve completed probe')
    protocol=read(ROOT/'protocol.json');lock=read(ROOT/'continuation-lock.json')
    assert lock['original_protocol_sha256']==digest(ROOT/'protocol.json')
    for path,expected in (protocol['files']|lock['files']).items():assert digest(Path(path))==expected,path
    stream=io.StringIO();suite=unittest.TestSuite()
    for pattern in ['test_sid_health_tensors.py','test_sid_health_precision.py']:
        suite.addTests(unittest.defaultTestLoader.discover('tests',pattern=pattern))
    tests=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (ROOT/'continued-tensor-tests.log').write_text(stream.getvalue(),encoding='utf-8')
    assert tests.wasSuccessful() and tests.testsRun==12
    import transformers
    assert torch.__version__==protocol['versions']['torch'] and transformers.__version__==protocol['versions']['transformers']
    assert torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    torch.set_num_threads(4);torch.cuda.empty_cache()
    profiles=read(DATA/'profiles.json');prefixes=read(DATA/'prefixes.json');priors=read(DATA/'position-priors.json')
    prefix=read('reports/stage45/tokenization.json')['prefix_ids']
    tokenizer=AutoTokenizer.from_pretrained('data/stage45-sft/tokenizer',local_files_only=True,trust_remote_code=False)
    starts=time.perf_counter();costs=[];new_requests=0;reused_requests=0;forward_samples=0
    for run in protocol['models']:
        output=DATA/run;output.mkdir(exist_ok=True)
        if (output/'position-loss.json').exists() or (output/'receipt.json').exists():raise FileExistsError('Do not overwrite teacher forcing or receipts')
        arm,seed_text=run.split('-');enable_full_determinism(int(seed_text))
        model_dir=Path('runs/stage45')/run/'final';weight_sha=digest(model_dir/'model.safetensors')
        model=AutoModelForSeq2SeqLM.from_pretrained(model_dir,local_files_only=True,trust_remote_code=False,
            attn_implementation='eager').eval().requires_grad_(False).cuda()
        before=parameter_fingerprint(model);mapping=read(Path('data/stage45-sft')/(arm+'.tokens.json'))
        constraint=CatalogConstraint(mapping,tokenizer)
        torch.cuda.reset_peak_memory_stats();clock=time.perf_counter()
        history_path=output/'history-probe.json';reused=history_path.exists()
        if reused:
            assert str(history_path) in lock['reused_history_files']
            assert digest(history_path)==lock['reused_history_files'][str(history_path)]
            history=read(history_path);reused_requests+=64
            print({'run':run,'reused_prior_beam_requests':64},flush=True)
        else:
            conditions={};batches=[]
            for condition in ['original','swapped']:
                results={}
                for start in range(0,32,16):
                    rows=profiles[start:start+16];histories=[r[condition+'_history_doc_ids'] for r in rows]
                    seen=[set(r['seen_doc_ids']) for r in rows];model.config.use_cache=True
                    torch.cuda.synchronize();batch_clock=time.perf_counter()
                    decoded,trace=observed_decode(model,tokenizer,constraint,histories,seen,mapping,prefix)
                    torch.cuda.synchronize();seconds=time.perf_counter()-batch_clock
                    for row,result in zip(rows,decoded):results[row['user_key']]=result
                    batches.append({'condition':condition,'users':[r['user_key'] for r in rows],'seconds':seconds,**trace})
                    new_requests+=len(rows)
                    assert new_requests+reused_requests<=384
                    print({'run':run,'condition':condition,'completed_users':start+16,
                           'new_beam_requests':new_requests,'reused':reused_requests},flush=True)
                conditions[condition]=results
            pairs=[]
            for row in profiles:
                user=row['user_key'];a=conditions['original'][user];b=conditions['swapped'][user]
                metrics=paired_rank_metrics(a['doc_ids'],b['doc_ids']);common=set(a['doc_ids'])&set(b['doc_ids'])
                aa=dict(zip(a['doc_ids'],a['sequence_scores']));bb=dict(zip(b['doc_ids'],b['sequence_scores']))
                metrics['common_doc_mean_abs_sequence_score_change']=sum(abs(aa[d]-bb[d]) for d in common)/len(common) if common else None
                metrics['newly_returned_donor_history_items']=len((set(b['doc_ids'])-set(a['doc_ids'])).intersection(row['swapped_history_doc_ids']))
                pairs.append({'user_key':user,'history_length':row['history_length'],'donor_user_key':row['donor_user_key'],**metrics})
            history={'run':run,'conditions':conditions,'paired':pairs,'batches':batches}
            save(history_path,history)
        loss_rows=[];batch_checks=[]
        for start in range(0,32,8):
            rows=prefixes[start:start+8]
            features=[fixed_features(input_tokens(r['history_doc_ids'],mapping,prefix),mapping[r['target_doc_id']]) for r in rows]
            batch={k:v.cuda() for k,v in default_data_collator(features).items()}
            with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
                native=model(**batch,use_cache=False,return_dict=True)
                amp_unreduced=F.cross_entropy(native.logits.reshape(-1,native.logits.shape[-1]),batch['labels'].reshape(-1),reduction='none').reshape(batch['labels'].shape)
            with torch.inference_mode():diagnostics=token_diagnostics(native.logits,batch['labels'],priors[arm])
            amp_mean=float(amp_unreduced.float().mean());native_error=abs(amp_mean-float(native.loss))
            assert native_error<1e-4
            fp32_mean=sum(p['full_vocab_nll'] for sample in diagnostics for p in sample)/(len(rows)*5)
            for index,(row,values) in enumerate(zip(rows,diagnostics)):
                for position,value in enumerate(values):
                    value['native_amp_full_vocab_nll']=float(amp_unreduced[index,position])
                    value['fp32_minus_native_amp_nll']=value['full_vocab_nll']-value['native_amp_full_vocab_nll']
                loss_rows.append({'sample_id':row['sample_id'],'exposure_group':row['exposure_group'],
                                  'history_length':row['history_length'],'positions':values})
            batch_checks.append({'samples':len(rows),'native_loss':float(native.loss),'native_loss_dtype':str(native.loss.dtype),
                'logits_dtype':str(native.logits.dtype),'native_amp_unreduced_mean':amp_mean,
                'native_amp_abs_error':native_error,'fp32_unreduced_mean':fp32_mean,
                'fp32_minus_native_amp_mean':fp32_mean-float(native.loss)})
            forward_samples+=len(rows);assert forward_samples<=192
            del native,batch,diagnostics,amp_unreduced
        torch.cuda.synchronize();after=parameter_fingerprint(model)
        assert before==after and weight_sha==digest(model_dir/'model.safetensors')
        assert all(p.grad is None and not p.requires_grad for p in model.parameters()) and not model.training
        save(output/'position-loss.json',{'run':run,'samples':loss_rows,'native_batch_checks':batch_checks,
             'analysis_precision':'FP32 CE recomputation from BF16-forward logits; native AMP CE recorded separately'})
        cost={'run':run,'continuation_seconds':time.perf_counter()-clock,'beam_requests_total_for_run':64,
            'reused_beam_requests':64 if reused else 0,'teacher_forced_successful_samples':32,
            'gpu_allocated_peak_bytes':torch.cuda.max_memory_allocated(),'gpu_reserved_peak_bytes':torch.cuda.max_memory_reserved(),
            'process_peak_bytes':psutil.Process().memory_info().peak_wset,
            'in_memory_weights_before_sha256':before,'in_memory_weights_after_sha256':after,
            'digest_window':'continuation B only; A from preserved verified checkpoint attempt' if reused else 'A and B',
            'checkpoint_sha256_unchanged':weight_sha,'all_gradients_none':True,'all_parameters_frozen':True}
        assert cost['gpu_reserved_peak_bytes']<2.5*2**30 and cost['process_peak_bytes']<6*2**30
        assert time.perf_counter()-starts<1200
        save(output/'receipt.json',cost);costs.append(cost)
        del model,constraint;gc.collect();torch.cuda.empty_cache()
    assert new_requests+reused_requests==384 and forward_samples==192
    save(ROOT/'execution.json',{'status':'complete','protocol_sha256':digest(ROOT/'protocol.json'),
        'continuation_lock_sha256':digest(ROOT/'continuation-lock.json'),'optimizer_updates':0,
        'beam_requests':384,'new_beam_requests_in_continuation':new_requests,'reused_beam_requests':reused_requests,
        'successful_teacher_forced_samples':forward_samples,'numerical_diagnostic_forward_samples':lock['numerical_diagnostic_forward_samples'],
        'interrupted_first_attempt_teacher_samples_upper_bound':lock['interrupted_teacher_samples_upper_bound'],
        'teacher_forward_attempt_samples_upper_bound':forward_samples+lock['numerical_diagnostic_forward_samples']+lock['interrupted_teacher_samples_upper_bound'],
        'costs':costs,'gpu':torch.cuda.get_device_name(),'continuation_wall_seconds':time.perf_counter()-starts,'tensor_tests_passed':tests.testsRun})
    print({'probe':'complete','beam_requests':384,'successful_teacher_samples':192,'optimizer_updates':0},flush=True)


if __name__=='__main__':main()
