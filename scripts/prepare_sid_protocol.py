"""Freeze retrospective, label-free structure diagnostics before fitting."""
from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path

from gsearch.paper_identity import canonical_id
from gsearch.quality_protocol import save, digest

ROOT = Path('reports/stage43')


def main() -> None:
    target = ROOT/'protocol.json'
    if target.exists():
        raise FileExistsError('Protocol already frozen')
    docs = json.loads(Path('deploy/stage41/catalog/documents.json').read_text(encoding='utf-8'))
    config = json.loads(Path('deploy/stage41/catalog/config.json').read_text(encoding='utf-8'))
    ids = sorted(r['doc_id'] for r in docs)
    train = Path('data/stage9-recommendation/train.csv')
    original = json.loads(Path('reports/stage9/plan.json').read_text(encoding='utf-8'))
    assert digest(train) == original['state']['data']['train.csv']
    freq, histories = Counter(), defaultdict(list)
    latest = None
    with train.open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            at = datetime.fromisoformat(row['time'])
            latest = max(latest, at) if latest else at
            if float(row['rating']) > 0:
                doc = canonical_id(row['arxiv_id'])
                if doc in ids:
                    freq[doc] += 1
                    histories[row['user_id']].append((at,doc))
    transition_count = sum(max(0,len(v)-1) for v in histories.values())
    for r in docs:
        assert r['version'] == 1 and datetime.fromisoformat(r['available_at']) <= datetime.fromisoformat(config['at'])
    for item in json.loads((ROOT/'upstream.json').read_text(encoding='utf-8'))['files']:
        b = Path(item['vendored']).read_bytes()
        assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest() == item['blob']
    save(target, {
        'frozen_before_fit':True, 'scope':'retrospective transductive structure diagnostic; no user-outcome or generative-model evaluation',
        'catalog':{'path':'deploy/stage41/catalog/documents.json','sha256':digest(Path('deploy/stage41/catalog/documents.json')),
                   'config_sha256':digest(Path('deploy/stage41/catalog/config.json')),'at':config['at'],'documents':len(ids),'ordered_ids':ids},
        'input':{'type':'existing_title_abstract_tfidf','params':config['params'],'conversion':'dense float32; upstream normalizes',
                 'scope':'educational CPU variant, not Qwen embeddings or a paper reproduction'},
        'quantizer':{'codebook_sizes':[16,16,16],'top_k':2,'beta':15.0,'n_iter':30,'batch_size':162,'eps':1e-10},
        'fit_seeds':[42,2024,3407], 'shuffle_seeds':list(range(20)),
        'shuffle':{'policy':'freeze every collided raw-SID group; derange singleton item-to-complete-SID assignment within train-frequency bucket; freeze buckets smaller than two',
                   'buckets':[[0,0],[1,1],[2,2],[3,5],[6,20],[21,None]],
                   'preserve':['exact raw and final SID multisets','codebooks','vocabulary','all trie prefix sets','collision membership','input vectors','item identities','frequency bucket SID multiset']},
        'metrics':{'depths':[1,2,3],'neighbors':5,'ranking_ties':'descending cosine then ascending canonical doc ID; self excluded',
                   'primary':'mean fraction of each paper TF-IDF top5 neighbors sharing its SID prefix',
                   'secondary':['pair-weighted within-prefix cosine','eligible within-prefix neighbor count','code utilization and entropy','raw/final collision statistics'],
                   'interpretation':'alignment with the same input representation; no relevance qrels, Recall, NDCG, significance, CTR or cold-start quality claim'},
        'training_history':{'path':str(train),'sha256':digest(train),'max_timestamp':latest.isoformat(),
                            'positive_counts':{doc:freq[doc] for doc in ids},'warm_documents':sum(freq[d]>0 for d in ids),
                            'within_catalog_positive_events':sum(freq.values()),'users_with_positive_history':len(histories),
                            'within_catalog_next_item_pairs':transition_count},
        'training_gate':{'launch_sft':False,'launch_rl':False,
                         'rule':'Structure signal permits only SFT feasibility planning; require adequate chronological train/tuning supervision, frozen equal-budget arms, resource gate and real constrained tokenization before training; RL only after reliable SFT and decoding.',
                         'exploratory_counts_not_training_labels':True},
        'budgets':{'seconds_per_fit':60,'peak_process_gib':2,'new_dependencies':0},
        'upstream_sha256':digest(ROOT/'upstream.json')})
    print({'protocol':str(target),'warm':sum(freq[d]>0 for d in ids),'positive_events':sum(freq.values()),'next_item_pairs':transition_count})


if __name__ == '__main__':
    main()
