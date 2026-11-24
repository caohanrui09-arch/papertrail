"""Freeze candidate/time/evaluation rules before preparing supervised histories."""
from collections import Counter
from datetime import datetime
import json
from pathlib import Path

from gsearch.expansion_data import available_at
from gsearch.quality_protocol import digest, save

ROOT=Path('reports/stage44')
DATA=Path('data/stage44-supervision')


def main() -> None:
    if (ROOT/'protocol.json').exists() or DATA.exists():
        raise FileExistsError('Do not overwrite a frozen supervision release')
    old=json.loads(Path('reports/stage9/plan.json').read_text(encoding='utf-8'))
    corpus_receipt=json.loads(Path('reports/stage13/corpus-receipt.json').read_text(encoding='utf-8'))
    audit=json.loads(Path('data/stage9-recommendation/audit.json').read_text(encoding='utf-8'))
    source=json.loads(Path('.cache/scholar-inbox-source/source.json').read_text(encoding='utf-8'))
    assert source['revision']=='92b0fac32110b1243081476f69607cf51aa71ad4'
    assert digest(Path('.cache/scholar-inbox-source/data/rated_papers.csv'))==source['files']['data/rated_papers.csv']['sha256']
    inputs={}
    for split in ['train','tuning','dev']:
        path=Path('data/stage9-recommendation')/(split+'.csv')
        assert digest(path)==old['state']['data'][split+'.csv']
        inputs[split]={'path':str(path),'sha256':digest(path)}
    corpus=Path('data/stage13-expansion/documents.json')
    assert digest(corpus)==corpus_receipt['documents_sha256']
    records=json.loads(corpus.read_text(encoding='utf-8'))
    cutoff=datetime.fromisoformat(audit['cutoffs']['train_exclusive'])
    chosen=[]
    for r in records:
        if r['version']!=1 or r['version_key']!='arxiv:'+r['doc_id']+'v1' or r['source_url']!='https://arxiv.org/abs/'+r['doc_id']+'v1':
            raise ValueError('Original explicit v1 metadata required')
        if available_at(r['published_at']).isoformat()!=r['available_at']:
            raise ValueError('Existing availability assumption changed')
        if datetime.fromisoformat(r['available_at'])<cutoff:
            chosen.append(r)
    chosen.sort(key=lambda r:r['doc_id'])
    if len(chosen)!=len({r['doc_id'] for r in chosen}):
        raise ValueError('Duplicate catalog identity')
    # New chronological supervision uses a fixed training-time catalog; new papers
    # after cutoff are explicitly outside it and stay in heldout denominators.
    DATA.mkdir(parents=True)
    save(DATA/'catalog.json',chosen)
    plan={
        'frozen_before_supervision_build':True,
        'scope':'local retrospective noncommercial next-positive-paper prediction; training/evaluation inputs separate from labels',
        'inputs':inputs,'source_corpus':{'path':str(corpus),'sha256':digest(corpus)},
        'source_snapshot':source['revision'],'data_license':'CC BY-NC-ND 4.0; derived per-user data must stay local',
        'catalog':{'path':str(DATA/'catalog.json'),'sha256':digest(DATA/'catalog.json'),'documents':len(chosen),
                   'cohorts':dict(Counter(r['cohort'] for r in chosen)),
                   'selection':'all and only records of frozen 10000 v1 corpus with available_at < train_exclusive; no heldout feedback',
                   'frozen_at':cutoff.isoformat(),'dynamic_admission':False,
                   'new_after_cutoff':'not added; future likes remain in denominator, including 1000 future-cold papers'},
        'cutoffs':audit['cutoffs'],'end_inclusive':'2025-02-23T05:28:26.401006+00:00',
        'timestamp_assumption':'Source feedback timezone unspecified; UTC parsing is an ordering convention. arXiv submission-day end plus24h is an availability proxy, not proven historical ingest.',
        'history':{'max_items':20,'positive_only':True,'min_training_items':1,'same_timestamp':'batch: no event at equal time enters another target history',
                   'positive_eligibility':'candidate doc with available_at <= that positive feedback time',
                   'training':'bounded prefix of earlier eligible train positives; all candidate train ratings tracked for seen filtering',
                   'evaluation':'frozen training-cutoff profile, no tuning/dev positives or dislikes update histories or masks',
                   'seen_mask':'all pre-cutoff candidate ratings, likes and dislikes, even feedback earlier than availability proxy'},
        'samples':{'target':'real positive rating only; no generated preferences','canonicalization':'existing canonical_id; reject canonical user-item duplicate pairs',
                   'training_exclusions':['negative rating','target outside catalog','feedback before availability proxy','no strictly earlier eligible positive history'],
                   'evaluation':'retain EVERY original positive event; never filter targets by catalog, seen status, user history or metadata'},
        'evaluation':{'k':10,'beam_size':10,'length_penalty':0.0,'sampling':False,'candidate_order':'canonical doc ID for non-model score ties',
                      'primary':'user-macro NDCG@10: average singleton-event NDCG within user, then users',
                      'secondary':['user-macro Recall@10','user-macro MRR@10','event-micro metrics','user/item cold groups','valid and duplicate slot rates','latency and peak memory'],
                      'full_denominator':True,'unrankable_targets':'count as misses; labels report reason and attainable ceiling',
                      'invalid_predictions':'keep slot positions, invalid or seen IDs become None; never compress rankings; duplicates consume slots',
                      'completeness':'exactly one row per expected qid, no extra/missing/duplicate qids; absent predictions are errors, explicit empty predictions count as misses',
                      'known_holdout_status':'tuning and dev have already informed prior research; dev_descriptive is not a fresh independent test'},
        'groups':{'user':'cold:0 eligible train likes; sparse:1-4; warm:>=5, measured before history truncation',
                  'item':'no_train_like versus trainliked from original pre-cutoff feedback; outside catalog is reported separately'},
        'comparison':{'baselines':['training-popularity','frozen-content','SAR'],
                      'sft_arms':['content-SID','within-training-frequency shuffled-SID'],
                      'sequence_task_only':True,'initial_no_auxiliary_sid_text_tasks':True,
                      'must_match':['base model weight and tokenizer hashes','candidate/text versions','training event IDs and order','batch and optimizer update count','seed schedule','supervised token counts','decoding budget','history and filters'],
                      'sid_fit':'fit vocabulary/vectorizer/quantizer using only fixed training-time catalog and train feedback; cannot reuse 162-paper lab SID mapping',
                      'mapping':'persist unique reversible complete token-ID sequences, including any identity suffix, and check collisions/prefix legality',
                      'shuffling':'freeze collision groups; derange singleton mappings within original training-frequency buckets; preserve complete SID multiset, vocabulary and trie',
                      'run_lock_required_before_fit':True,'training_config_and_hardware_gate':'not yet frozen; separate preflight required before any model training'},
        'selection':{'split':'tuning','order':['user-macro NDCG@10','Recall@10','MRR@10'],
                     'tie_break':'earlier optimizer step, then predeclared simpler baseline; no test-based checkpoint choice',
                     'paired_mapping_study':'evaluate both frozen arms; do not drop weaker arm based on tuning',
                     'dev':'evaluate once after selected checkpoint/config lock; report as descriptive regardless of score'},
        'gates':{'model_training_started':False,'rl_started':False,'fresh_independent_test_available':False,
                 'next':'after data validation, freeze exact training run + resource and real tokenization/decoding checks; reliable SFT before RL'},
        'reuse_sources_sha256':digest(ROOT/'sources.json')}
    save(ROOT/'protocol.json',plan)
    print({'catalog':len(chosen),'cohorts':plan['catalog']['cohorts'],'cutoffs':plan['cutoffs'],'protocol_sha256':digest(ROOT/'protocol.json')})


if __name__=='__main__':
    main()
