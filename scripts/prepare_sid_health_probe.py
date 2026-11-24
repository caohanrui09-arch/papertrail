"""Freeze small source-only samples, counterfactuals and exact inference budget."""
from collections import Counter
from datetime import datetime
from pathlib import Path
import json

from gsearch.quality_protocol import digest,save
from gsearch.sid_health_data import select_profiles,select_prefixes
from gsearch.supervision import json_rows

ROOT=Path('reports/stage47');DATA=Path('data/stage47-health')


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main() -> None:
    ROOT.mkdir(parents=True,exist_ok=True);DATA.mkdir(parents=True,exist_ok=True)
    if (ROOT/'protocol.json').exists():raise FileExistsError('Probe already frozen')
    profiles=list(json_rows(Path('data/stage44-supervision/profiles.jsonl')))
    chosen=select_profiles(profiles)
    assert len(chosen)==32 and len({r['user_key'] for r in chosen})==32
    for length in [1,20]:
        group=[r for r in chosen if r['history_length']==length]
        assert Counter(tuple(r['original_history_doc_ids']) for r in group)==Counter(tuple(r['swapped_history_doc_ids']) for r in group)
    selected=set(read(Path('data/stage45-sft/training-order.json'))['sample_ids'][:1024])
    prefixes,pilot,pool=select_prefixes(json_rows(Path('data/stage44-supervision/train.next_item.jsonl')),selected)
    assert len(prefixes)==32 and len({r['sample_id'] for r in prefixes})==32 and sum(pilot.values())==1024
    for row in prefixes:
        assert all(datetime.fromisoformat(at)<datetime.fromisoformat(row['target_at']) for at in row['history_ats'])
    save(DATA/'profiles.json',chosen);save(DATA/'prefixes.json',prefixes)
    priors={}
    for arm in ['content','shuffled']:
        mapping=read(Path('data/stage45-sft')/(arm+'.tokens.json'))
        levels=[]
        for position in range(5):
            allowed=sorted({tokens[position] for tokens in mapping.values()})
            counts=Counter()
            for doc,n in pilot.items():counts[mapping[doc][position]]+=n
            assert sum(counts.values())==1024
            levels.append({'position':position,'allowed_ids':allowed,'pilot_counts':{str(t):counts[t] for t in allowed},
                           'alpha':1.0,'total':1024})
        priors[arm]=levels
    save(DATA/'position-priors.json',priors)
    model_runs=[a+'-'+str(s) for s in [42,2024,3407] for a in ['content','shuffled']]
    files=[Path('reports/stage46/final-validation.json'),Path('reports/stage46/next-step-decision.json'),
        Path('reports/stage45/run-lock.json'),Path('reports/stage45/tokenization.json'),
        Path('data/stage44-supervision/profiles.jsonl'),Path('data/stage44-supervision/train.next_item.jsonl'),
        Path('data/stage45-sft/training-order.json'),Path('gsearch/sid_sft.py'),Path('gsearch/prefix_decoder.py'),
        Path('gsearch/sid_health_data.py'),Path('gsearch/sid_health_probe.py'),
        Path('scripts/prepare_sid_health_probe.py'),Path('scripts/run_sid_health_probe.py'),
        Path('tests/test_sid_health_data.py'),Path('tests/test_sid_health_tensors.py'),
        DATA/'profiles.json',DATA/'prefixes.json',DATA/'position-priors.json']
    files.extend(Path('data/stage45-sft')/(a+'.tokens.json') for a in ['content','shuffled'])
    files.extend(p for p in Path('data/stage45-sft/tokenizer').iterdir() if p.is_file())
    for run in model_runs:
        final=Path('runs/stage45')/run/'final'
        files.extend([final/'model.safetensors',final/'config.json',final/'generation_config.json'])
    files.extend([Path('../.venv/Lib/site-packages/transformers/generation/utils.py'),
                  Path('../.venv/Lib/site-packages/transformers/models/t5/modeling_t5.py'),
                  Path('../.venv/Lib/site-packages/torch/nn/functional.py')])
    protocol={'frozen_before_model_inference':True,'scope':'source-only fixed-model health/sensitivity diagnostic, not new recommendation quality evaluation',
        'prior_stage46_sha256':'dbf11f3f9a9012b510b616211ecd4332af90b1b151052b8b0b2e4395f1ae2142',
        'models':model_runs,'optimizer_updates':0,
        'probe_A':{'profiles':32,'source_selection':'16each exact history lengths1 and20, fixed source hash; no tuning metadata/targets used',
            'assignment':'scipy.optimize.linear_sum_assignment; same-length one-to-one history permutation; no identical histories',
            'conditions':['original','swapped'],'receiver_seen_mask_unchanged':True,'history_length_and_global_histogram_unchanged':True,
            'batch':16,'beam':10,'max_new_tokens':5,'length_penalty':0.0,'sampling':False,'precision':'bf16 autocast; fp32 weights',
            'total_requests':384,'observer':'HF LogitsProcessor identity-return observer of intermediate input_ids and legal branch counts',
            'scores':'native output_scores/beam_indices/compute_transition_scores(normalize_logits=False); no custom beam implementation',
            'metrics':['Top10 Jaccard/set overlap','ordered-list equality','top1 equality','normalized footrule with missing rank11',
                       'added donor-history items','intermediate prefixes and native beam ancestry','latency'],
            'caveat':'swapped history and receiver seen mask can be counterfactually inconsistent; measure input sensitivity, not relevance or interest understanding'},
        'probe_B':{'samples':32,'selection':'8each pilot/nonpilot x exact history lengths1/20, fixed source sample hash',
            'histories':'strict-past sample prefixes, never full-cutoff profile','forward_sample_total':192,
            'positions':['semantic1','semantic2','semantic3','identity','eos'],
            'loss':'native torch.nn.functional.cross_entropy(reduction=none), compare mean with native model.loss',
            'diagnostics':['full-vocabulary NLL','position-codebook conditional NLL','position-codebook probability mass',
                           'full/codebook top1 accuracy','uniform-codebook NLL','Laplace(alpha1) pilot-position-prior NLL'],
            'caveat':'teacher forcing supplies true prior target tokens; codebook conditioning is not the seen-filtered trie; exposure strata are not randomized'},
        'resource_caps':{'gpu_reserved_gib':2.5,'process_peak_gib':6,'total_wall_seconds':1200},
        'versions':{'transformers':'4.57.1','torch':'2.6.0+cu124'},
        'sample_summary':{'A_lengths':dict(Counter(r['history_length'] for r in chosen)),
            'B_cells':dict(Counter(r['exposure_group']+':'+str(r['history_length']) for r in prefixes)),
            'B_users':len({r['user_key'] for r in prefixes})},
        'not_allowed':['optimizer steps','weight changes','tuning or dev target reads','full evaluation rerun','new dependencies','website changes'],
        'files':{str(path):digest(path) for path in sorted(files)}}
    assert digest(Path('reports/stage46/final-validation.json'))==protocol['prior_stage46_sha256']
    save(ROOT/'protocol.json',protocol)
    print({'protocol':'frozen','sample_summary':protocol['sample_summary'],'sha256':digest(ROOT/'protocol.json')},flush=True)


if __name__=='__main__':main()
