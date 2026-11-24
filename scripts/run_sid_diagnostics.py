"""Call unchanged MiniOneRec PRQ and audit a fixed, label-free mapping intervention."""
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
import psutil
from sklearn.feature_extraction.text import TfidfVectorizer
from threadpoolctl import threadpool_limits

from gsearch.quality_protocol import digest, save

ROOT = Path('reports/stage43')
DATA = Path('data/stage43-sid')
sys.path.insert(0,str(Path('third_party').resolve()))
from minionerec_sid_cpu.prq_kmeans import PRQKMeans
from minionerec_sid_cpu.sid_common import build_indexes


def bucket(frequency: int) -> int:
    for index,(low,high) in enumerate([(0,0),(1,1),(2,2),(3,5),(6,20),(21,None)]):
        if frequency >= low and (high is None or frequency <= high):
            return index
    raise ValueError('Invalid frequency')


def shuffled_assignment(codes: np.ndarray, frequencies: list[int], seed: int) -> np.ndarray:
    """Only adapt the experimental mapping; quantization is upstream code."""
    counts = Counter(map(tuple,codes))
    strata = defaultdict(list)
    for i,code in enumerate(codes):
        if counts[tuple(code)] == 1:
            strata[bucket(frequencies[i])].append(i)
    result = np.arange(len(codes))
    rng = np.random.default_rng(seed)
    for indices in strata.values():
        if len(indices) < 2:
            continue
        indices = np.array(indices,dtype=int)
        for _ in range(100):
            candidate = rng.permutation(indices)
            if np.all(candidate != indices):
                break
        else:
            candidate = np.roll(indices,1)
        result[indices] = candidate
    return result


def structure_metrics(codes: np.ndarray, cosine: np.ndarray, neighbors: np.ndarray) -> list[dict]:
    result = []
    for depth in [1,2,3]:
        same = (codes[:,None,:depth] == codes[None,:,:depth]).all(axis=2)
        np.fill_diagonal(same,False)
        directed_pairs = int(same.sum())
        neighbor_counts = same.sum(axis=1)
        result.append({'depth':depth,'neighbor_retention_at5':float(same[np.arange(len(codes))[:,None],neighbors].mean()),
            'pair_mean_cosine':float(cosine[same].mean()) if directed_pairs else None,
            'unordered_pairs':directed_pairs//2,'mean_other_candidates':float(neighbor_counts.mean()),
            'singleton_documents':int(np.count_nonzero(neighbor_counts == 0)),
            'candidate_fraction':float(neighbor_counts.mean()/(len(codes)-1))})
    return result


def assert_control(codes: np.ndarray, raw: dict, final: dict, ids: list[str], assignment: np.ndarray, frequencies: list[int]) -> dict:
    altered = codes[assignment]
    mapped_raw = {d:raw[ids[int(assignment[i])]] for i,d in enumerate(ids)}
    mapped_final = {d:final[ids[int(assignment[i])]] for i,d in enumerate(ids)}
    checks = {'permutation':sorted(assignment.tolist()) == list(range(len(ids))),
              'raw_multiset':Counter(map(tuple,codes)) == Counter(map(tuple,altered)),
              'final_multiset':Counter(map(tuple,final.values())) == Counter(map(tuple,mapped_final.values())),
              'vocabulary':{t for v in raw.values() for t in v} == {t for v in mapped_raw.values() for t in v},
              'frequency_bucket':all(bucket(frequencies[i]) == bucket(frequencies[int(assignment[i])]) for i in range(len(ids)))}
    original_collision = defaultdict(set)
    altered_collision = defaultdict(set)
    for i,d in enumerate(ids):
        original_collision[tuple(codes[i])].add(d)
        altered_collision[tuple(altered[i])].add(d)
    checks['collision_membership'] = {k:v for k,v in original_collision.items() if len(v)>1} == {k:v for k,v in altered_collision.items() if len(v)>1}
    for depth in [1,2,3]:
        checks['trie_depth_'+str(depth)] = {tuple(c[:depth]) for c in codes} == {tuple(c[:depth]) for c in altered}
        for b in range(6):
            positions = [i for i,f in enumerate(frequencies) if bucket(f)==b]
            checks[f'bucket_{b}_depth_{depth}'] = Counter(tuple(codes[i,:depth]) for i in positions) == Counter(tuple(altered[i,:depth]) for i in positions)
    if not all(checks.values()):
        raise AssertionError(checks)
    return {'checks':checks,'changed_documents':int(np.count_nonzero(assignment != np.arange(len(ids)))),
            'frozen_documents':int(np.count_nonzero(assignment == np.arange(len(ids))))}


def main() -> None:
    if (ROOT/'results.json').exists():
        raise FileExistsError('Results already frozen; do not refit or select a new configuration')
    DATA.mkdir(parents=True,exist_ok=True)
    protocol = json.loads((ROOT/'protocol.json').read_text(encoding='utf-8'))
    catalog_path = Path(protocol['catalog']['path'])
    assert digest(catalog_path) == protocol['catalog']['sha256']
    assert digest(ROOT/'upstream.json') == protocol['upstream_sha256']
    assert digest(Path(protocol['training_history']['path'])) == protocol['training_history']['sha256']
    rows = {r['doc_id']:r for r in json.loads(catalog_path.read_text(encoding='utf-8'))}
    ids = protocol['catalog']['ordered_ids']
    verified = set()
    for row in rows.values():
        path = catalog_path.parent/row['provenance']['raw_file']
        if path not in verified:
            assert digest(path) == row['provenance']['raw_sha256']
            verified.add(path)
    params = protocol['input']['params'] | {'ngram_range':tuple(protocol['input']['params']['ngram_range'])}
    started = time.perf_counter()
    with threadpool_limits(limits=1):
        vectorizer = TfidfVectorizer(**params)
        sparse = vectorizer.fit_transform([rows[d]['title']+'\n'+rows[d]['abstract'] for d in ids])
        matrix = np.asarray(sparse.toarray(),dtype=np.float32)
        features = vectorizer.get_feature_names_out()
        assert np.isfinite(matrix).all() and np.all(np.linalg.norm(matrix,axis=1)>0)
        np.save(DATA/'input-vectors.npy',matrix,allow_pickle=False)
        save(DATA/'vectorizer.json',{'vocabulary':{k:int(v) for k,v in vectorizer.vocabulary_.items()},'idf':vectorizer.idf_.tolist(),'params':protocol['input']['params'],'ordered_ids':ids})
        cosine = (sparse @ sparse.T).toarray()
        ranked = cosine.copy()
        np.fill_diagonal(ranked,-np.inf)
        neighbors = np.argsort(-ranked,axis=1,kind='stable')[:,:5]
        frequencies = [protocol['training_history']['positive_counts'][d] for d in ids]
        fits = []
        for seed in protocol['fit_seeds']:
            start = time.perf_counter()
            model = PRQKMeans(seed=seed,**protocol['quantizer']).fit(matrix)
            codes = model.encode(matrix)
            seconds = time.perf_counter()-start
            assert seconds <= protocol['budgets']['seconds_per_fit']
            raw,final,stats = build_indexes(ids,codes,model.capacities,collision_policy='append')
            model_path = DATA/f'prq-{seed}.npz'
            model.save(model_path)
            assert np.array_equal(PRQKMeans.load(model_path).encode(matrix),codes)
            assert np.array_equal(model.encode(matrix[::-1])[::-1],codes)
            shard_model = PRQKMeans.load(model_path)
            shard_model.batch_size = 17
            assert np.array_equal(shard_model.encode(matrix),codes)
            np.save(DATA/f'codes-{seed}.npy',codes,allow_pickle=False)
            save(DATA/f'index-{seed}.json',{'raw':raw,'final':final,'stats':stats})
            groups = []
            for code in sorted(set(codes[:,0])):
                positions = np.flatnonzero(codes[:,0]==code)
                summed = np.asarray(sparse[positions].sum(axis=0)).ravel()
                terms = sorted(range(len(features)),key=lambda i:(-summed[i],features[i]))
                groups.append({'code':int(code),'documents':len(positions),'terms':[str(features[i]) for i in terms[:6] if summed[i]>0]})
            controls = []
            for shuffle_seed in protocol['shuffle_seeds']:
                assignment = shuffled_assignment(codes,frequencies,shuffle_seed)
                audit = assert_control(codes,raw,final,ids,assignment,frequencies)
                controls.append({'seed':shuffle_seed,'assignment':assignment.tolist(),
                                 'metrics':structure_metrics(codes[assignment],cosine,neighbors),'audit':audit})
            positions = [{**p,'counts':np.bincount(codes[:,p['position']],minlength=p['capacity']).tolist()} for p in stats['semantic_positions']]
            fits.append({'seed':seed,'seconds_fit_and_encode':seconds,'model_sha256':digest(model_path),
                         'codes':codes.tolist(),'raw':raw,'final':final,'stats':stats,'positions':positions,
                         'first_prefix_groups':groups,'metrics':structure_metrics(codes,cosine,neighbors),'shuffles':controls})
            print({'seed':seed,'seconds':round(seconds,3),'raw_collision_excess':stats['raw']['excess_collision_count'],
                   'final_unique':stats['final']['unique_sids'],'changed_default':controls[0]['audit']['changed_documents']},flush=True)
    papers = [{k:rows[d][k] for k in ['doc_id','title','version','version_key','source_url','published_at']} |
              {'train_likes':frequencies[i],'nearest':[{'doc_id':ids[j],'cosine':float(cosine[i,j])} for j in neighbors[i]]} for i,d in enumerate(ids)]
    summary = []
    for fit in fits:
        for metric in fit['metrics']:
            values = [c['metrics'][metric['depth']-1]['neighbor_retention_at5'] for c in fit['shuffles']]
            summary.append({'fit_seed':fit['seed'],'depth':metric['depth'],'content':metric['neighbor_retention_at5'],
                            'shuffled_mean':float(np.mean(values)),'shuffled_min':min(values),'shuffled_max':max(values),
                            'difference':metric['neighbor_retention_at5']-float(np.mean(values))})
    peak = getattr(psutil.Process().memory_info(),'peak_wset',psutil.Process().memory_info().rss)
    assert peak < protocol['budgets']['peak_process_gib']*1024**3
    result = {'scope':protocol['scope'],'protocol_sha256':digest(ROOT/'protocol.json'),'catalog_sha256':protocol['catalog']['sha256'],
              'catalog_at':protocol['catalog']['at'],'papers':papers,'fits':fits,'summary':summary,
              'input_shape':list(matrix.shape),'input_sha256':digest(DATA/'input-vectors.npy'),'input_kind':protocol['input']['type'],
              'cost':{'wall_seconds':time.perf_counter()-started,'peak_process_bytes':peak,'peak_kind':'Windows peak working set' if os.name=='nt' else 'current RSS, not full-run peak'},
              'training_supervision':{k:v for k,v in protocol['training_history'].items() if k not in ['positive_counts','path']},
              'decision':{'sft_started':False,'rl_started':False,'status':'structure_diagnostics_only',
                          'reason':'Only '+str(protocol['training_history']['within_catalog_next_item_pairs'])+' in-catalog train-period positive next-item pairs; no separately frozen chronological tuning set for these 162 items. Structural retention uses the input representation and is not recommendation quality.',
                          'next_gate':'Prepare a sufficiently supervised chronological dataset and equal-budget SFT protocol; verify real tokenization and constrained decoding before any RL.'}}
    save(ROOT/'results.json',result)
    print({'input_shape':matrix.shape,'wall_seconds':result['cost']['wall_seconds'],'peak_mib':peak/1024**2,
           'summary':summary,'sft_started':False,'rl_started':False})


if __name__ == '__main__':
    main()
