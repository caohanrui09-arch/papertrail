"""Freeze unchanged source-selected samples and fair two-budget position priors."""
from collections import Counter
from pathlib import Path
import shutil
import subprocess
import sys

from gsearch.quality_protocol import digest,save
from gsearch.sid_prior_probe import ROOT,DATA,read,build_priors,rescore_reference


def main() -> None:
    if ROOT.exists() or DATA.exists():raise FileExistsError('Preserve existing stage50 material')
    subprocess.run([sys.executable,'-E','-s','-m','scripts.verify_sid_budget_changes'],check=True)
    ROOT.mkdir(parents=True);DATA.mkdir(parents=True)
    for name in ['profiles.json','prefixes.json']:
        shutil.copyfile(Path('data/stage47-health')/name,DATA/name)
        assert digest(DATA/name)==digest(Path('data/stage47-health')/name)
    order=read(Path('data/stage45-sft/training-order.json'))
    selected={1024:set(order['sample_ids'][:1024]),4096:set(order['sample_ids'][:4096])}
    counts={1024:Counter(),4096:Counter()}
    with Path('data/stage44-supervision/train.next_item.jsonl').open(encoding='utf-8') as handle:
        import json
        for line in handle:
            row=json.loads(line)
            for budget in [1024,4096]:
                if row['sample_id'] in selected[budget]:counts[budget][row['target_doc_id']]+=1
    assert sum(counts[1024].values())==1024 and sum(counts[4096].values())==4096
    priors={arm:{str(b):build_priors(read(Path('data/stage45-sft')/(arm+'.tokens.json')),counts[b]) for b in [1024,4096]}
            for arm in ['content','shuffled']}
    save(DATA/'position-priors.json',priors)
    metadata=[]
    for row in read(DATA/'prefixes.json'):
        doc=row['target_doc_id'];sid=row['sample_id']
        metadata.append({'sample_id':sid,'event_exposure':('first1024' if sid in selected[1024] else 'added1025to4096' if sid in selected[4096] else 'not_selected4096'),
            'target_paper_exposure':('first1024' if counts[1024][doc] else 'added1025to4096' if counts[4096][doc] else 'not_labelled4096'),
            'target_label_count1024':counts[1024][doc],'target_label_count4096':counts[4096][doc]})
    save(DATA/'prefix-exposure.json',metadata)
    runs=read(Path('reports/stage47/protocol.json'))['models']
    for run in runs:
        arm=run.split('-')[0];old=read(Path('data/stage47-health')/run/'position-loss.json')
        directory=DATA/run;directory.mkdir()
        save(directory/'reference128-rescored.json',{'run':run,'model_steps':128,
            'source_loss_sha256':digest(Path('data/stage47-health')/run/'position-loss.json'),
            'no_inference':True,'samples':[rescore_reference(r,priors[arm]['1024'],priors[arm]['4096']) for r in old['samples']]})
    files=[Path('reports/stage49/final-validation.json'),Path('reports/stage47/protocol.json'),
        Path('data/stage44-supervision/train.next_item.jsonl'),Path('data/stage45-sft/training-order.json'),
        Path('data/stage47-health/profiles.json'),Path('data/stage47-health/prefixes.json'),
        Path('gsearch/sid_health_probe.py'),Path('gsearch/sid_sft.py'),Path('gsearch/prefix_decoder.py'),
        Path('gsearch/sid_prior_probe.py'),Path('scripts/prepare_sid_prior_probe.py'),
        Path('scripts/run_sid_prior_probe.py'),Path('scripts/validate_sid_prior_probe.py'),Path('tests/test_sid_prior_probe.py'),
        Path('tests/test_sid_health_tensors.py'),Path('tests/test_sid_health_precision.py')]
    files.extend(p for p in DATA.rglob('*') if p.is_file())
    for arm in ['content','shuffled']:files.append(Path('data/stage45-sft')/(arm+'.tokens.json'))
    files.extend(p for p in Path('data/stage45-sft/tokenizer').iterdir() if p.is_file())
    for run in runs:
        files.extend(Path('runs/stage48')/run/'checkpoint-512'/name for name in ['model.safetensors','config.json','generation_config.json'])
        files.extend(Path('data/stage47-health')/run/name for name in ['history-probe.json','position-loss.json'])
    files.extend(Path('../.venv/Lib/site-packages')/p for p in ['transformers/generation/utils.py','transformers/models/t5/modeling_t5.py','torch/nn/functional.py'])
    protocol={'frozen_before_stage50_model_inference':True,'scope':'fixed512 source-only health probe; paired128 archive; not recommendation relevance evaluation',
        'prior_receipt_sha256':'24ee8b881aa9a037d8dbbd75d6a013d53e9d5c4b7384d9952376a048ef3d3f19',
        'models':runs,'checkpoint':'runs/stage48/{run}/checkpoint-512','optimizer_updates':0,
        'sampling':'exact byte copies of stage47 profiles32/prefixes32; no target/performance-driven reselection',
        'A':{'conditions':['original','swapped'],'same_length_receiver_seen_fixed':True,'beam':10,'batch':16,'requests':384,'precision':'BF16 autocast, FP32 weights','native_observer':'unchanged stage47 observed_decode; identity score-return'},
        'B':{'samples':192,'batch':8,'teacher_forcing':True,'labels':'unchanged token IDs incl EOS',
            'mean_check':'same AMP unreduced CE vs native AMP loss, abs1e-4',
            'diagnostics':'FP32 CE recompute from BF16 logits; original helper unchanged; legacy prior field renamed explicitly',
            'priors':'Laplace alpha1, same4096 prior for128 and512;1024 prior kept also; position-codebook conditional, not trie conditional',
            'old128':'prior-only CPU recomputation, original losses preserved; no old-model inference'},
        'resource_caps':{'gpu_reserved_gib':2.5,'process_peak_gib':6,'wall_seconds':1200},
        'versions':{'torch':'2.6.0+cu124','transformers':'4.57.1'},
        'forbidden':['optimizer/weight updates','full tuning/dev decoding','tuning/dev labels in probe inputs','new packages','website changes','RL'],
        'limits':['history-swap sensitivity does not prove preference understanding','marginal prior NLL is not a ranking baseline','same32 sampled endpoints do not represent all users','no full vocabulary logits retained'],
        'files':{str(p):digest(p) for p in sorted(set(files))}}
    assert digest(Path('reports/stage49/final-validation.json'))==protocol['prior_receipt_sha256']
    save(ROOT/'protocol.json',protocol)
    print({'protocol':'frozen','sha256':digest(ROOT/'protocol.json'),
           'prefix_event_exposure':dict(Counter(r['event_exposure'] for r in metadata)),
           'prefix_target_exposure':dict(Counter(r['target_paper_exposure'] for r in metadata))},flush=True)


if __name__=='__main__':main()
