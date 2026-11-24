"""Tuning-only mechanism audit before defining a new cold-item fusion."""
from collections import Counter
import hashlib
from pathlib import Path

import numpy as np

from gsearch.benchmark_expansion import events
from gsearch.catalog_audit import digest
from gsearch.expansion_data import DATA as OLD_DATA, save
from gsearch.indexed_expansion import load
from gsearch.content_recommendation import sklearn_runtime

ROOT = Path('reports/stage15')
DATA = Path('data/stage15-cold-fusion')


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True); DATA.mkdir(parents=True, exist_ok=True)
    if (ROOT / 'tuning-mechanism-audit.json').exists():
        raise ValueError('Refuse to overwrite diagnostic')
    sklearn_runtime()
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        model = load(10000)
        f = events('tuning')
        content = np.load(OLD_DATA / '10000-content-tuning.npz', allow_pickle=False)['indices']
        hybrid = np.load(OLD_DATA / '10000-hybrid_a050-tuning.npz', allow_pickle=False)['indices']
        warm = set(model.sar.catalog)
        # Local annotations from the frozen event receipt retain the GLOBAL train-positive definition.
        from gsearch.expansion_data import read
        event_rows = read(OLD_DATA / '10000-tuning-events.json')
        if len(event_rows) != len(f):
            raise ValueError('Event receipt differs')
        counts = Counter(); cases = []
        cf_rank, content_rank, fused_rank, arbitrary_rank, zero_fraction = [], [], [], [], []
        for row in f.itertuples():
            if event_rows[row.Index]['user_id'] != row.user_id or event_rows[row.Index]['arxiv_id'] != row.arxiv_id:
                raise ValueError('Event order differs')
            if not event_rows[row.Index]['cold_item_global']:
                continue
            counts['all_global_cold_events'] += 1
            target = model.position.get(row.arxiv_id, -2)
            a = target in content[row.Index]
            b = target in hybrid[row.Index]
            counts['content_hits'] += a; counts['rrf_hits'] += b
            counts['content_only'] += a and not b; counts['rrf_only'] += b and not a
            counts['both'] += a and b
            if not a:
                continue
            at = row.at.to_pydatetime()
            eligible = model.eligible(row.user_id, at)
            cf, text = model.components(row.user_id)
            order_cf = np.argsort(-cf[eligible], kind='stable')
            order_text = np.argsort(-text[eligible], kind='stable')
            r_cf, r_text = np.empty(len(eligible)), np.empty(len(eligible))
            r_cf[order_cf] = np.arange(1, len(eligible) + 1)
            r_text[order_text] = np.arange(1, len(eligible) + 1)
            index = int(np.flatnonzero(eligible == target)[0])
            score = .5 / (60 + r_cf) + .5 / (60 + r_text)
            rank = int(np.flatnonzero(eligible[np.argsort(-score, kind='stable')] == target)[0]) + 1
            positive = int((cf[eligible] > 0).sum())
            zero_indices = eligible[cf[eligible] == 0]
            tie_position = int(np.flatnonzero(zero_indices == target)[0]) + 1
            assert cf[target] == 0 and model.catalog[target] not in warm
            assert r_cf[index] == positive + tie_position
            cf_rank.append(r_cf[index]); content_rank.append(r_text[index]); fused_rank.append(rank)
            arbitrary_rank.append(tie_position); zero_fraction.append(float((cf[eligible] == 0).mean()))
            cases.append({'user_id': row.user_id, 'doc_id': row.arxiv_id, 'time': row.time,
                'global_cold': True, 'cf_score': float(cf[target]), 'content_score': float(text[target]),
                'cf_rank': int(r_cf[index]), 'content_rank': int(r_text[index]), 'fused_rank': rank,
                'positive_cf_items': positive, 'zero_cf_tie_position_by_id': tie_position,
                'cf_contribution': float(.5 / (60 + r_cf[index])),
                'content_contribution': float(.5 / (60 + r_text[index])),
                'eligible_items': len(eligible), 'zero_cf_fraction': zero_fraction[-1]})
        save(DATA / 'tuning-cold-hit-cases.json', cases)
        def ranges(values: list) -> dict:
            return {'min': float(np.min(values)), 'median': float(np.median(values)), 'max': float(np.max(values))} if values else {}
        save(ROOT / 'tuning-mechanism-audit.json', {'split': 'tuning_only', 'counts': dict(counts),
            'on_content_cold_hits': {'cf_rank': ranges(cf_rank), 'content_rank': ranges(content_rank),
                'fused_rank': ranges(fused_rank), 'id_tie_position': ranges(arbitrary_rank), 'zero_cf_fraction': ranges(zero_fraction)},
            'identity_proof': 'zero-CF rank = count(strictly positive CF items) + target position among zero scores in base-ID order',
            'cases_sha256': digest(DATA / 'tuning-cold-hit-cases.json'),
            'source_predictions': {name: digest(OLD_DATA / name) for name in ('10000-content-tuning.npz', '10000-hybrid_a050-tuning.npz')},
            'no_dev_loaded': True, 'causality_limit': 'mechanism audit is conditional on tuning cold hits, not an independent quality test'})
        print(dict(counts))
        print({'cf_rank': ranges(cf_rank), 'content_rank': ranges(content_rank), 'fused_rank': ranges(fused_rank)})


if __name__ == '__main__':
    main()
