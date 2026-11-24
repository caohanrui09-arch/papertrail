"""Validate the unchanged source stream and freeze the 512-step design before updates."""
from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess
import sys

from gsearch.quality_protocol import digest, save
from gsearch.sid_budget import ROOT, DATA, SEEDS, ARMS, read


def rows(path):
    with Path(path).open(encoding='utf-8') as handle:
        for line in handle:
            if line.strip(): yield json.loads(line)


def main() -> None:
    if ROOT.exists() or DATA.exists(): raise FileExistsError('Preserve prior stage48 material')
    subprocess.run([sys.executable, '-E', '-s', '-m', 'scripts.verify_sid_health_probe'], check=True)
    assert shutil.disk_usage('.').free > 20*2**30, 'Need20GiB free for native checkpoints'
    ROOT.mkdir(parents=True); DATA.mkdir(parents=True)
    order = read(Path('data/stage45-sft/training-order.json'))
    indices = order['indices'][:4096]
    ids = order['sample_ids'][:4096]
    assert len(indices) == len(set(indices)) == len(set(ids)) == 4096
    source = list(rows('data/stage44-supervision/train.next_item.jsonl'))
    chosen = [source[i] for i in indices]
    assert [r['sample_id'] for r in chosen] == ids
    prefix = read(Path('reports/stage45/tokenization.json'))['prefix_ids']
    exposures = {}
    for arm in ARMS:
        mapping = read(Path('data/stage45-sft') / (arm+'.tokens.json'))
        wanted = set(indices)
        pool = {i:r for i,r in enumerate(rows(Path('data/stage45-sft') / (arm+'.train.tokens.jsonl'))) if i in wanted}
        output = DATA / (arm+'.ordered.jsonl')
        with output.open('x', encoding='utf-8', newline='\n') as handle:
            for index, sample in zip(indices, chosen):
                row = pool[index]
                inputs = prefix + [t for doc in sample['history_doc_ids'][-20:] for t in mapping[doc][:-1]] + [1]
                assert row['sample_id'] == sample['sample_id']
                assert row['input_ids'] == inputs + [0]*(96-len(inputs))
                assert row['attention_mask'] == [1]*len(inputs) + [0]*(96-len(inputs))
                assert row['labels'] == mapping[sample['target_doc_id']] and len(row['labels']) == 5
                handle.write(json.dumps(row, separators=(',', ':'))+'\n')
        del pool
    for count in [1024, 4096]:
        subset = chosen[:count]
        exposures[str(count)] = {'samples': count, 'users': len({r['user_key'] for r in subset}),
            'target_papers': len({r['target_doc_id'] for r in subset}),
            'history_papers': len({d for r in subset for d in r['history_doc_ids']}),
            'supervised_tokens': count*5}
    save(DATA/'order.json', {'indices': indices, 'sample_ids': ids, 'source_order_sha256': digest(Path('data/stage45-sft/training-order.json'))})
    save(ROOT/'data-validation.json', {'status':'passed', 'two_arm_raw_rows_reconstructed':8192,
        'same_first1024_as_stage45':True, 'exposure':exposures, 'no_holdout_used':True})
    files = [Path('gsearch/sid_budget.py'), Path('scripts/prepare_sid_budget.py'), Path('scripts/run_sid_budget.py'),
             Path('tests/test_sid_budget.py'), Path('reports/stage47/final-validation.json'),
             Path('scripts/score_sid_budget.py'), Path('scripts/validate_sid_budget.py')]
    files.extend(p for p in DATA.iterdir() if p.is_file())
    files.extend([ROOT/'data-validation.json', Path('data/stage44-supervision/train.next_item.jsonl'),
                  Path('gsearch/sid_scoring.py'),Path('gsearch/supervision.py'),Path('gsearch/supervision_evaluation.py')])
    old = read(Path('reports/stage45/run-lock.json'))
    paths = dict(old['files'])
    for run in [a+'-'+str(s) for s in SEEDS for a in ARMS]:
        for p in [Path('runs/stage45')/run/'final/model.safetensors', Path('runs/stage45')/run/'training.json']:
            paths[str(p)] = digest(p)
    for p in files: paths[str(p)] = digest(p)
    for p in [Path('../.venv/Lib/site-packages/transformers/trainer.py'),
              Path('../.venv/Lib/site-packages/transformers/trainer_callback.py')]: paths[str(p)] = digest(p)
    protocol = {'frozen_before_stage48_training':True, 'prior_receipt_sha256':digest(Path('reports/stage47/final-validation.json')),
        'reference_run_lock_sha256':digest(Path('reports/stage45/run-lock.json')),
        'arms':ARMS, 'seeds':SEEDS, 'max_steps':512, 'checkpoints':[128,512],
        'batch':8, 'samples':4096, 'supervised_tokens':20480, 'data_seed':271828,
        'training_arguments':'call unchanged scripts.run_sid_sft.arguments(output,seed,512); native checkpoint callback only',
        'reference_gate':'all saved128 tensors bitwise equal to old final; loss/grad_norm/lr at16..128 exactly equal; ignore epoch/runtime',
        'resource_caps':{'gpu_reserved_gib':6.5, 'process_peak_gib':12, 'per_run_training_seconds':900},
        'first128':'authorized gate stage; freeze actual512 lock only after first128 exact reproduction and measured resource pass',
        'comparison':'budget and exposure jointly grow; constant scheduler; same prefix order, no pure-step causal claim',
        'evaluation':{'split':'tuning only, previously used', 'events':46352, 'beam':10,
            'primary':'full-denominator user-macro NDCG@10', 'secondary':['Recall@10','cold/warm users and papers','coverage','cost'],
            'conditional1801':'diagnostic only', 'selection':'retain both arms/all seeds, no best-seed or checkpoint selection',
            'reference128_predictions':'reuse only after every128 tensor equality gate passes'},
        'dev_evaluation':False, 'rl':False, 'website_changed':False,
        'sources':[
            'https://github.com/huggingface/transformers/blob/v4.57.1/src/transformers/trainer.py',
            'https://github.com/huggingface/transformers/blob/v4.57.1/src/transformers/trainer_callback.py',
            'https://github.com/AkaliKong/MiniOneRec/blob/526306229326013a7ca46f5b2d8f55ea669aa159/sft.py'],
        'reuse':'HF native optimization/checkpoint/RNG; MiniOneRec reference only; unchanged prior SID/ZeroGR decode and scorer',
        'files':paths}
    save(ROOT/'protocol.json', protocol)
    print({'stage48':'design frozen', 'sha256':digest(ROOT/'protocol.json'), 'exposure':exposures}, flush=True)


if __name__ == '__main__': main()
