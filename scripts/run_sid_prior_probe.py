"""Frozen512 probe, directly reusing stage47 native beam/CE adapters."""
import gc
import io
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
from gsearch.sid_prior_probe import ROOT,DATA,read,legacy_adapter,prior_nll


def main() -> None:
    if (ROOT/'execution.json').exists():raise FileExistsError('Preserve completed probe')
    protocol=read(ROOT/'protocol.json')
    for path,expected in protocol['files'].items():assert digest(Path(path))==expected,path
    stream=io.StringIO();suite=unittest.TestSuite()
    for pattern in ['test_sid_health_tensors.py','test_sid_health_precision.py']:
        suite.addTests(unittest.defaultTestLoader.discover('tests',pattern=pattern))
    tests=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (ROOT/'tensor-tests.log').write_text(stream.getvalue(),encoding='utf-8')
    assert tests.wasSuccessful() and tests.testsRun==12
    import transformers
    assert torch.__version__==protocol['versions']['torch'] and transformers.__version__==protocol['versions']['transformers']
    assert torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    torch.set_num_threads(4);torch.cuda.empty_cache()
    profiles=read(DATA/'profiles.json');prefixes=read(DATA/'prefixes.json');priors=read(DATA/'position-priors.json')
    prefix=read(Path('reports/stage45/tokenization.json'))['prefix_ids']
    tokenizer=AutoTokenizer.from_pretrained('data/stage45-sft/tokenizer',local_files_only=True,trust_remote_code=False)
    started=time.perf_counter();costs=[];requests=0;forward_samples=0
    for run in protocol['models']:
        output=DATA/run
        if any((output/name).exists() for name in ['history-probe.json','position-loss.json','receipt.json']):
            raise FileExistsError('Do not overwrite any attempt '+run)
        arm,seed=run.split('-');enable_full_determinism(int(seed))
        model_dir=Path('runs/stage48')/run/'checkpoint-512';weight_sha=digest(model_dir/'model.safetensors')
        model=AutoModelForSeq2SeqLM.from_pretrained(model_dir,local_files_only=True,trust_remote_code=False,
            attn_implementation='eager').eval().requires_grad_(False).cuda()
        before=parameter_fingerprint(model);mapping=read(Path('data/stage45-sft')/(arm+'.tokens.json'))
        constraint=CatalogConstraint(mapping,tokenizer);torch.cuda.reset_peak_memory_stats();clock=time.perf_counter()
        conditions={};batches=[]
        for condition in ['original','swapped']:
            results={}
            for start in range(0,32,16):
                rows=profiles[start:start+16];histories=[r[condition+'_history_doc_ids'] for r in rows]
                seen=[set(r['seen_doc_ids']) for r in rows];model.config.use_cache=True
                torch.cuda.synchronize();batch_start=time.perf_counter()
                decoded,trace=observed_decode(model,tokenizer,constraint,histories,seen,mapping,prefix)
                torch.cuda.synchronize();seconds=time.perf_counter()-batch_start
                for row,result in zip(rows,decoded):results[row['user_key']]=result
                batches.append({'condition':condition,'users':[r['user_key'] for r in rows],'seconds':seconds,**trace})
                requests+=len(rows);assert requests<=384
            conditions[condition]=results
        pairs=[]
        for row in profiles:
            user=row['user_key'];a=conditions['original'][user];b=conditions['swapped'][user]
            metrics=paired_rank_metrics(a['doc_ids'],b['doc_ids']);common=set(a['doc_ids'])&set(b['doc_ids'])
            aa=dict(zip(a['doc_ids'],a['sequence_scores']));bb=dict(zip(b['doc_ids'],b['sequence_scores']))
            metrics['common_doc_mean_abs_sequence_score_change']=sum(abs(aa[d]-bb[d]) for d in common)/len(common) if common else None
            metrics['newly_returned_donor_history_items']=len((set(b['doc_ids'])-set(a['doc_ids'])).intersection(row['swapped_history_doc_ids']))
            pairs.append({'user_key':user,'history_length':row['history_length'],'donor_user_key':row['donor_user_key'],**metrics})
        save(output/'history-probe.json',{'run':run,'model_steps':512,'conditions':conditions,'paired':pairs,'batches':batches})
        loss_rows=[];checks=[]
        adapted=legacy_adapter(priors[arm]['4096'])
        for start in range(0,32,8):
            rows=prefixes[start:start+8]
            features=[fixed_features(input_tokens(r['history_doc_ids'],mapping,prefix),mapping[r['target_doc_id']]) for r in rows]
            batch={k:v.cuda() for k,v in default_data_collator(features).items()}
            with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
                native=model(**batch,use_cache=False,return_dict=True)
                amp=F.cross_entropy(native.logits.reshape(-1,native.logits.shape[-1]),batch['labels'].reshape(-1),reduction='none').reshape(batch['labels'].shape)
            with torch.inference_mode():diagnostics=token_diagnostics(native.logits,batch['labels'],adapted)
            error=abs(float(amp.float().mean())-float(native.loss));assert error<1e-4
            fp32_mean=sum(p['full_vocab_nll'] for sample in diagnostics for p in sample)/(len(rows)*5)
            for index,(row,values) in enumerate(zip(rows,diagnostics)):
                for pos,value in enumerate(values):
                    expanded=priors[arm]['4096'][pos];token=value['target_token_id']
                    value['label4096_position_prior_nll']=value.pop('pilot_position_prior_nll')
                    assert abs(value['label4096_position_prior_nll']-prior_nll(expanded,token))<1e-12
                    value['label1024_position_prior_nll']=prior_nll(priors[arm]['1024'][pos],token)
                    predict=min(expanded['allowed_ids'],key=lambda t:(-expanded['label_counts'][str(t)],t))
                    value['label4096_prior_top1_correct']=predict==token
                    value['native_amp_full_vocab_nll']=float(amp[index,pos])
                    value['fp32_minus_native_amp_nll']=value['full_vocab_nll']-value['native_amp_full_vocab_nll']
                loss_rows.append({'sample_id':row['sample_id'],'exposure_group':row['exposure_group'],
                    'history_length':row['history_length'],'positions':values})
            checks.append({'samples':len(rows),'native_loss':float(native.loss),'native_loss_dtype':str(native.loss.dtype),
                'logits_dtype':str(native.logits.dtype),'native_amp_unreduced_mean':float(amp.float().mean()),
                'native_amp_abs_error':error,'fp32_unreduced_mean':fp32_mean,'fp32_minus_native_amp_mean':fp32_mean-float(native.loss)})
            forward_samples+=len(rows);assert forward_samples<=192
            del native,batch,diagnostics,amp
        torch.cuda.synchronize();after=parameter_fingerprint(model)
        assert before==after and weight_sha==digest(model_dir/'model.safetensors')
        assert all(not p.requires_grad and p.grad is None for p in model.parameters()) and not model.training
        save(output/'position-loss.json',{'run':run,'model_steps':512,'samples':loss_rows,'native_batch_checks':checks,
            'analysis_precision':'FP32 CE recomputation from BF16 logits; native AMP CE separately checked; priors source-only1024/4096'})
        cost={'run':run,'seconds':time.perf_counter()-clock,'beam_requests':64,'teacher_forced_samples':32,
            'gpu_allocated_peak_bytes':torch.cuda.max_memory_allocated(),'gpu_reserved_peak_bytes':torch.cuda.max_memory_reserved(),
            'process_peak_bytes':psutil.Process().memory_info().peak_wset,
            'in_memory_weights_before_sha256':before,'in_memory_weights_after_sha256':after,
            'digest_window':'complete A+B','checkpoint_sha256_unchanged':weight_sha,'all_gradients_none':True,'all_parameters_frozen':True}
        assert cost['gpu_reserved_peak_bytes']<2.5*2**30 and cost['process_peak_bytes']<6*2**30
        assert time.perf_counter()-started<1200
        save(output/'receipt.json',cost);costs.append(cost)
        print({'probe_completed':run,'requests':requests,'teacher_samples':forward_samples,'cost':cost},flush=True)
        del model,constraint;gc.collect();torch.cuda.empty_cache()
    assert requests==384 and forward_samples==192
    save(ROOT/'execution.json',{'status':'complete','protocol_sha256':digest(ROOT/'protocol.json'),
        'optimizer_updates':0,'beam_requests':requests,'successful_teacher_forced_samples':forward_samples,
        'additional_model_forward_samples':0,'reused128_inference_requests':0,'synthetic_precision_test_count':2,
        'costs':costs,'gpu':torch.cuda.get_device_name(),'wall_seconds':time.perf_counter()-started,'tensor_tests_passed':12})
    print({'probe':'complete','requests':requests,'teacher_samples':192,'optimizer_updates':0},flush=True)


if __name__=='__main__':main()
