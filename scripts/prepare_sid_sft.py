"""Stage45: train-only text SID adaptation; upstream quantizer, no model fitting."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import psutil
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize
from threadpoolctl import threadpool_limits

from gsearch.quality_protocol import digest, save
from scripts.run_sid_diagnostics import shuffled_assignment, assert_control

sys.path.insert(0, str(Path('third_party').resolve()))
from minionerec_sid_cpu.prq_kmeans import PRQKMeans
from minionerec_sid_cpu.sid_common import build_indexes

REPORT = Path('reports/stage45')
DATA = Path('data/stage45-sft')


def main() -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    if (REPORT/'sid-results.json').exists():
        raise FileExistsError('Preserve frozen SID fit')
    config = {
        'frozen_before_sid_fit': True,
        'catalog_sha256': digest(Path('data/stage44-supervision/catalog.json')),
        'protocol_sha256': digest(Path('reports/stage44/protocol.json')),
        'representation': 'train-time catalog title+original v1 abstract; TFIDF+SVD128+L2, not pretrained embedding reproduction',
        'tfidf': {'max_features':12000, 'min_df':2, 'ngram_range':[1,2], 'sublinear_tf':True, 'dtype':'float32'},
        'svd': {'n_components':128, 'n_iter':5, 'random_state':42},
        'quantizer': {'codebook_sizes':[64,64,64], 'top_k':2, 'beta':15.0, 'n_iter':10, 'batch_size':256, 'seed':42},
        'shuffle_seed':2024, 'shuffle_rule':'stage44 frozen: collision groups fixed; singleton derangement within training frequency buckets',
        'structure_probe':{'documents':512,'seed':19,'neighbors':5,'scope':'input-space consistency only, not relevance or recommendation quality'},
        'pilot':{'optimizer_updates':128,'effective_batch':8,'seed_schedule':[42,2024,3407],
                 'sample_order_seed':271828,'checkpoints':[128],'learning_rate':0.0005,
                 'precision':'bf16','optimizer':'adamw_torch','weight_decay':0.01,'scheduler':'constant',
                 'max_input_tokens':96,'beam':10,'length_penalty':0.0,'evaluation_split':'tuning only',
                 'preflight_updates':4,'resource_limit_reserved_gib':6.5,'resource_limit_process_gib':12,
                 'six_runs_training_limit_seconds':3600,'evaluation_limit_seconds':3600},
        'model':{'path':'.cache/models/t5-small','revision':'df1b051c49625cf57a3d0d8d3863ed4d13564fe4',
                 'reason':'existing Apache2 safetensors base; local resource pilot, not official Qwen reproduction'},
        'no_holdout_labels_in_sid_or_training':True,
    }
    save(REPORT/'design.json',config)
    start=time.perf_counter()
    rows=json.loads(Path('data/stage44-supervision/catalog.json').read_text(encoding='utf-8'))
    by_id={r['doc_id']:r for r in rows}; ids=sorted(by_id)
    stats=json.loads(Path('data/stage44-supervision/training-stats.json').read_text(encoding='utf-8'))
    # Original pre-cutoff counts are the predeclared intervention strata.
    frequencies=[stats['catalog_source_positive_counts'].get(d,0) for d in ids]
    with threadpool_limits(limits=2):
        vectorizer=TfidfVectorizer(max_features=12000,min_df=2,ngram_range=(1,2),sublinear_tf=True,dtype=np.float32)
        sparse=vectorizer.fit_transform([by_id[d]['title']+'\n'+by_id[d]['abstract'] for d in ids])
        svd=TruncatedSVD(**config['svd'])
        matrix=normalize(svd.fit_transform(sparse)).astype(np.float32)
        assert np.isfinite(matrix).all() and np.all(np.linalg.norm(matrix,axis=1)>0)
        np.savez_compressed(DATA/'text-state.npz',components=svd.components_,idf=vectorizer.idf_)
        save(DATA/'text-vocabulary.json',{'vocabulary':{k:int(v) for k,v in vectorizer.vocabulary_.items()},'ids':ids})
        np.save(DATA/'input-vectors.npy',matrix,allow_pickle=False)
        np.save(DATA/'content-tfidf-data.npy',sparse.data,allow_pickle=False)
        from scipy.sparse import save_npz
        save_npz(DATA/'content-tfidf.npz',sparse)
        fit=time.perf_counter()
        model=PRQKMeans(**config['quantizer']).fit(matrix)
        codes=model.encode(matrix)
        model.save(DATA/'prq.npz')
        assert np.array_equal(PRQKMeans.load(DATA/'prq.npz').encode(matrix),codes)
        raw,final,collision=build_indexes(ids,codes,model.capacities,collision_policy='append')
        assignment=shuffled_assignment(codes,frequencies,config['shuffle_seed'])
        audit=assert_control(codes,raw,final,ids,assignment,frequencies)
        other={d:final[ids[int(assignment[i])]] for i,d in enumerate(ids)}
        assert all(len(final[d])==len(other[d]) for d in ids)
        save(DATA/'content.sid.json',final); save(DATA/'shuffled.sid.json',other)
        save(DATA/'assignment.json',{'ids':ids,'assignment':assignment.tolist(),'frequencies':frequencies})
        np.save(DATA/'codes.npy',codes,allow_pickle=False)
        probes=np.random.default_rng(19).choice(len(ids),512,replace=False)
        similarities=matrix[probes]@matrix.T
        similarities[np.arange(len(probes)),probes]=-np.inf
        nearest=np.argsort(-similarities,axis=1,kind='stable')[:,:5]
        structure=[]
        for depth in [1,2,3]:
            structure.append({'depth':depth,'content':float((codes[probes,None,:depth]==codes[nearest,:depth]).all(axis=2).mean()),
                              'shuffled':float((codes[assignment[probes],None,:depth]==codes[assignment[nearest],:depth]).all(axis=2).mean())})
        terms=vectorizer.get_feature_names_out(); groups=[]
        for code in sorted(set(codes[:,0])):
            pos=np.flatnonzero(codes[:,0]==code)
            weights=np.asarray(sparse[pos].sum(axis=0)).ravel()
            top=sorted(range(len(terms)),key=lambda j:(-weights[j],terms[j]))[:8]
            groups.append({'code':int(code),'count':len(pos),'terms':[str(terms[j]) for j in top],
                           'examples':[{'doc_id':ids[j],'title':by_id[ids[j]]['title']} for j in pos[:3]]})
    output={'design_sha256':digest(REPORT/'design.json'),'documents':len(ids),'tfidf_shape':list(sparse.shape),
            'vector_shape':list(matrix.shape),'svd_explained_variance':float(svd.explained_variance_ratio_.sum()),
            'collision':collision,'control':audit,'structure':structure,'groups':groups,
            'fit_and_diagnostics_seconds':time.perf_counter()-fit,'total_seconds':time.perf_counter()-start,
            'peak_process_bytes':psutil.Process().memory_info().peak_wset,
            'files':{str(p):digest(p) for p in sorted(DATA.iterdir()) if p.is_file()}}
    save(REPORT/'sid-results.json',output)
    print({k:output[k] for k in ['documents','vector_shape','total_seconds','peak_process_bytes','structure']},flush=True)


if __name__=='__main__':
    main()
