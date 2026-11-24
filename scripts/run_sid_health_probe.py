"""Execute only the frozen384 beam requests and192 teacher-forced samples."""
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
from transformers import AutoModelForSeq2SeqLM,AutoTokenizer,default_data_collator,enable_full_determinism

from gsearch.quality_protocol import digest,save
from gsearch.sid_sft import CatalogConstraint,input_tokens,fixed_features
from gsearch.sid_health_probe import observed_decode,token_diagnostics,paired_rank_metrics,parameter_fingerprint

ROOT=Path('reports/stage47');DATA=Path('data/stage47-health')


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main() -> None:
    if (ROOT/'execution.json').exists():raise FileExistsError('Preserve completed probe')
    protocol=read(ROOT/'protocol.json')
    for path,expected in protocol['files'].items():assert digest(Path(path))==expected,path
    stream=io.StringIO()
    tests=unittest.TextTestRunner(stream=stream,verbosity=2).run(
        unittest.defaultTestLoader.discover('tests',pattern='test_sid_health_tensors.py'))
    (ROOT/'tensor-tests.log').write_text(stream.getvalue(),encoding='utf-8')
    assert tests.wasSuccessful() and tests.testsRun>=8
    assert torch.__version__==protocol['versions']['torch']
    import transformers
    assert transformers.__version__==protocol['versions']['transformers']
    assert torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    torch.set_num_threads(4)
    profiles=read(DATA/'profiles.json');prefixes=read(DATA/'prefixes.json');priors=read(DATA/'position-priors.json')
    prefix=read(Path('reports/stage45/tokenization.json'))['prefix_ids']
    tokenizer=AutoTokenizer.from_pretrained('data/stage45-sft/tokenizer',local_files_only=True,trust_remote_code=False)
    starts=time.perf_counter();costs=[];requests=0;forward_samples=0
    for run in protocol['models']:
        arm,seed_text=run.split('-');seed=int(seed_text);output=DATA/run
        if output.exists():raise FileExistsError('Keep prior partial probe: '+run)
        output.mkdir()
        enable_full_determinism(seed)
        model_dir=Path('runs/stage45')/run/'final';weight_sha=digest(model_dir/'model.safetensors')
        model=AutoModelForSeq2SeqLM.from_pretrained(model_dir,local_files_only=True,trust_remote_code=False,
                                                   attn_implementation='eager').eval().requires_grad_(False).cuda()
        assert all(not p.requires_grad for p in model.parameters()) and not model.training
        before=parameter_fingerprint(model)
        mapping=read(Path('data/stage45-sft')/(arm+'.tokens.json'))
        constraint=CatalogConstraint(mapping,tokenizer)
        torch.cuda.reset_peak_memory_stats();clock=time.perf_counter()
        conditions={};batches=[]
        for condition in ['original','swapped']:
            results={}
            for start in range(0,32,16):
                rows=profiles[start:start+16]
                histories=[row[condition+'_history_doc_ids'] for row in rows]
                seen=[set(row['seen_doc_ids']) for row in rows]
                model.config.use_cache=True
                torch.cuda.synchronize();batch_clock=time.perf_counter()
                decoded,trace=observed_decode(model,tokenizer,constraint,histories,seen,mapping,prefix)
                torch.cuda.synchronize();seconds=time.perf_counter()-batch_clock
                for row,result in zip(rows,decoded):results[row['user_key']]=result
                batches.append({'condition':condition,'users':[r['user_key'] for r in rows],
                                'seconds':seconds,**trace})
                requests+=len(rows)
                assert requests<=384
                print({'run':run,'condition':condition,'completed_users':start+16,'beam_requests':requests},flush=True)
            conditions[condition]=results
        pairs=[]
        for row in profiles:
            user=row['user_key'];a=conditions['original'][user];b=conditions['swapped'][user]
            metrics=paired_rank_metrics(a['doc_ids'],b['doc_ids'])
            common=set(a['doc_ids'])&set(b['doc_ids'])
            aa=dict(zip(a['doc_ids'],a['sequence_scores']));bb=dict(zip(b['doc_ids'],b['sequence_scores']))
            metrics['common_doc_mean_abs_sequence_score_change']=sum(abs(aa[d]-bb[d]) for d in common)/len(common) if common else None
            new=set(b['doc_ids'])-set(a['doc_ids'])
            metrics['newly_returned_donor_history_items']=len(new.intersection(row['swapped_history_doc_ids']))
            pairs.append({'user_key':user,'history_length':row['history_length'],'donor_user_key':row['donor_user_key'],**metrics})
        save(output/'history-probe.json',{'run':run,'conditions':conditions,'paired':pairs,'batches':batches})
        loss_rows=[];batch_checks=[]
        for start in range(0,32,8):
            rows=prefixes[start:start+8]
            features=[fixed_features(input_tokens(row['history_doc_ids'],mapping,prefix),mapping[row['target_doc_id']]) for row in rows]
            batch={k:v.cuda() for k,v in default_data_collator(features).items()}
            with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
                native=model(**batch,use_cache=False,return_dict=True)
            with torch.inference_mode():diagnostics=token_diagnostics(native.logits,batch['labels'],priors[arm])
            full_mean=sum(p['full_vocab_nll'] for sample in diagnostics for p in sample)/(len(rows)*5)
            error=abs(full_mean-float(native.loss))
            assert error<1e-4
            batch_checks.append({'samples':len(rows),'native_loss':float(native.loss),'unreduced_mean':full_mean,'abs_error':error})
            for row,values in zip(rows,diagnostics):
                loss_rows.append({'sample_id':row['sample_id'],'exposure_group':row['exposure_group'],
                                  'history_length':row['history_length'],'positions':values})
            forward_samples+=len(rows)
            assert forward_samples<=192
            del native,batch,diagnostics
        torch.cuda.synchronize();after=parameter_fingerprint(model)
        assert before==after and weight_sha==digest(model_dir/'model.safetensors')
        assert all(p.grad is None and not p.requires_grad for p in model.parameters()) and not model.training
        save(output/'position-loss.json',{'run':run,'samples':loss_rows,'native_batch_checks':batch_checks})
        cost={'run':run,'seconds':time.perf_counter()-clock,'beam_requests':64,'teacher_forced_samples':32,
            'gpu_allocated_peak_bytes':torch.cuda.max_memory_allocated(),
            'gpu_reserved_peak_bytes':torch.cuda.max_memory_reserved(),
            'process_peak_bytes':psutil.Process().memory_info().peak_wset,
            'in_memory_weights_before_sha256':before,'in_memory_weights_after_sha256':after,
            'checkpoint_sha256_unchanged':weight_sha,'all_gradients_none':True,'all_parameters_frozen':True}
        assert cost['gpu_reserved_peak_bytes']<2.5*2**30 and cost['process_peak_bytes']<6*2**30
        assert time.perf_counter()-starts<1200
        save(output/'receipt.json',cost);costs.append(cost)
        del model,constraint;gc.collect();torch.cuda.empty_cache()
    assert requests==384 and forward_samples==192
    save(ROOT/'execution.json',{'status':'complete','protocol_sha256':digest(ROOT/'protocol.json'),
        'beam_requests':requests,'teacher_forced_samples':forward_samples,'optimizer_updates':0,'costs':costs,
        'gpu':torch.cuda.get_device_name(),'wall_seconds':time.perf_counter()-starts,'tensor_tests_passed':tests.testsRun})
    print({'probe':'complete','beam_requests':requests,'teacher_forced_samples':forward_samples,'seconds':time.perf_counter()-starts},flush=True)


if __name__=='__main__':main()
