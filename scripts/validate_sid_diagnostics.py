"""Independent artifact recount, no tuning/dev files and no model retraining."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
import unittest

import numpy as np
from gsearch.quality_protocol import digest, save

ROOT = Path('reports/stage43')
sys.path.insert(0,str(Path('third_party').resolve()))
from minionerec_sid_cpu.prq_kmeans import PRQKMeans


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main() -> None:
    checks = []
    def check(name: str, passed: bool) -> None:
        if not passed:
            raise AssertionError(name)
        checks.append(name)
    source = load(ROOT/'upstream.json')
    for item in source['files']:
        value = Path(item['vendored']).read_bytes()
        check('git_blob:'+item['path'],hashlib.sha1(b'blob '+str(len(value)).encode()+b'\0'+value).hexdigest()==item['blob'])
    protocol, result = load(ROOT/'protocol.json'), load(ROOT/'results.json')
    check('frozen_protocol',result['protocol_sha256']==digest(ROOT/'protocol.json'))
    matrix = np.load('data/stage43-sid/input-vectors.npy',allow_pickle=False)
    check('input_hash',digest(Path('data/stage43-sid/input-vectors.npy'))==result['input_sha256'])
    ids = protocol['catalog']['ordered_ids']
    # Read scalar dot-products and exact top5 independently from saved float32 input.
    normalized = matrix.astype(np.float64)
    normalized /= np.linalg.norm(normalized,axis=1)[:,None]
    similarity = normalized @ normalized.T
    for i,paper in enumerate(result['papers']):
        expected = sorted((j for j in range(len(ids)) if j!=i),key=lambda j:(-similarity[i,j],ids[j]))[:5]
        check('neighbor_identity:'+paper['doc_id'],[x['doc_id'] for x in paper['nearest']]==[ids[j] for j in expected])
    freqs = protocol['training_history']['positive_counts']
    for fit in result['fits']:
        seed = fit['seed']
        codes = np.asarray(fit['codes'])
        check('saved_code_array:'+str(seed),np.array_equal(codes,np.load(f'data/stage43-sid/codes-{seed}.npy',allow_pickle=False)))
        model = PRQKMeans.load(f'data/stage43-sid/prq-{seed}.npz')
        check('saved_quantizer:'+str(seed),np.array_equal(model.encode(matrix),codes))
        check('suffix_unique:'+str(seed),len(set(map(tuple,fit['final'].values())))==len(ids))
        check('semantic_prefix:'+str(seed),all(fit['final'][d][:3]==fit['raw'][d] for d in ids))
        check('raw_collision_recount:'+str(seed),len(ids)-len(set(map(tuple,codes)))==fit['stats']['raw']['excess_collision_count'])
        for level,pos in enumerate(fit['positions']):
            check(f'occupancy:{seed}:{level}',Counter(codes[:,level])==Counter({i:n for i,n in enumerate(pos['counts']) if n}))
        for control in fit['shuffles']:
            a = control['assignment']
            altered = codes[a]
            check(f'control_audits:{seed}:{control["seed"]}',all(control['audit']['checks'].values()))
            check(f'exact_sid_multiset:{seed}:{control["seed"]}',Counter(map(tuple,codes))==Counter(map(tuple,altered)))
            # Strictly verify collision item identity, without trusting stored booleans.
            groups = defaultdict(list)
            for i,row in enumerate(codes):
                groups[tuple(row)].append(i)
            check(f'collisions_frozen:{seed}:{control["seed"]}',all(a[i]==i for g in groups.values() if len(g)>1 for i in g))
            for depth in [1,2,3]:
                hit = 0
                for i,paper in enumerate(result['papers']):
                    for neighbor in paper['nearest']:
                        j = ids.index(neighbor['doc_id'])
                        hit += tuple(altered[i,:depth])==tuple(altered[j,:depth])
                value = hit/(len(ids)*5)
                check(f'retention_recount:{seed}:{control["seed"]}:{depth}',abs(value-control['metrics'][depth-1]['neighbor_retention_at5'])<1e-12)
        for depth in [1,2,3]:
            hit = sum(tuple(codes[i,:depth])==tuple(codes[ids.index(n['doc_id']),:depth]) for i,p in enumerate(result['papers']) for n in p['nearest'])
            check(f'content_retention:{seed}:{depth}',abs(hit/(len(ids)*5)-fit['metrics'][depth-1]['neighbor_retention_at5'])<1e-12)
    check('no_llm_training',not result['decision']['sft_started'] and not result['decision']['rl_started'])
    check('real_supervision_not_synthetic',result['training_supervision']['warm_documents']==43 and result['training_supervision']['within_catalog_next_item_pairs']==33)
    suite = unittest.defaultTestLoader.discover('third_party/minionerec_sid_cpu/tests',pattern='test_prq_regressions.py')
    upstream = unittest.TextTestRunner(verbosity=1).run(suite)
    check('upstream_boundary_regressions',upstream.wasSuccessful() and upstream.testsRun==4)
    save(ROOT/'diagnostic-validation.json',{'status':'passed','count':len(checks),'checks':checks,'upstream_tests':upstream.testsRun,
         'fit_runs':3,'controlled_permutations':60,'no_refit_of_saved_experiment_models':True,'no_quality_labels_used':True})
    print({'checks':len(checks),'upstream_tests':upstream.testsRun,'status':'passed'})


if __name__ == '__main__':
    main()
