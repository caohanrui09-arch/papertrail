"""Independent raw ranking recount, time/seen guards and source/runtime checks."""
from collections import defaultdict
import hashlib
import math
from pathlib import Path

import numpy as np
import pandas as pd

from gsearch.catalog_audit import digest, stamp
from gsearch.expansion_data import ORIGINAL, read
from gsearch.benchmark_expansion import events
from gsearch.benchmark_cold_fusion import ROOT, DATA, OLD_DATA, methods_for


def source_runtime() -> dict:
    import sklearn
    from sklearn.preprocessing import _data
    audit = read(ROOT / 'upstream-audit.json')
    raw = Path(_data.__file__).read_bytes().replace(b'\r\n', b'\n')
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    expected = next(r for r in audit['comparisons'] if r['repository'] == 'scikit-learn/scikit-learn')
    if sklearn.__version__ != expected['version'] or blob != expected['core_blob']:
        raise ValueError('Native normalization runtime differs from pinned upstream')
    return {'sklearn_version': sklearn.__version__, 'native_minmax_source_lf_git_blob': blob,
            'no_new_dependencies': True, 'pyterrier_wrapper_not_used': True}


def validate_outputs(model) -> tuple[dict, dict]:
    train = pd.read_csv(ORIGINAL / 'train.csv', dtype={'arxiv_id': str, 'user_id': str})
    global_likes = set(train.loc[train.rating == 1, 'arxiv_id'])
    counts = {}; users = {}
    for split in ('tuning', 'dev'):
        frame = events(split); receipts = read(OLD_DATA / f'10000-{split}-events.json')
        if len(frame) != len(receipts):
            raise ValueError('Incomplete original denominator')
        for row, receipt in zip(frame.itertuples(), receipts):
            if (row.user_id, row.arxiv_id, row.time) != (receipt['user_id'], receipt['arxiv_id'], receipt['time']):
                raise ValueError('Event receipt mismatch')
            if (row.arxiv_id not in global_likes) != receipt['cold_item_global']:
                raise ValueError('Global cold-item definition changed')
        for method, (mode, alpha) in methods_for(split).items():
            output = read(ROOT / f'{method}-{split}.json')
            path = DATA / f'{method}-{split}.npz'
            userpath = DATA / f'{method}-{split}-users.json'
            if digest(path) != output['predictions_sha256'] or digest(userpath) != output['users_sha256']:
                raise ValueError('Raw output drift')
            if digest(OLD_DATA / f'10000-{split}-events.json') != output['events_sha256']:
                raise ValueError('Original event receipt changed')
            with np.load(path, allow_pickle=False) as raw:
                predictions = raw['indices']
            if predictions.shape != (len(frame), 10) or predictions.dtype != np.int32:
                raise ValueError('Raw ranking schema changed')
            group_sums = defaultdict(lambda: np.zeros(4)); user_sums = defaultdict(lambda: np.zeros(4))
            relevant = defaultdict(list); used = set()
            for row, indices, receipt in zip(frame.itertuples(), predictions, receipts):
                if np.any((indices < -1) | (indices >= len(model.catalog))):
                    raise ValueError('Invalid document index')
                active = indices[indices >= 0].tolist()
                if len(set(active)) != len(active) or (len(active) < 10 and np.any(indices[len(active):] != -1)):
                    raise ValueError('Duplicates or nontrailing padding')
                ids = [model.catalog[i] for i in active]
                if set(ids) & model.sar.seen.get(row.user_id, set()):
                    raise ValueError('Train seen rating returned')
                when = row.at.to_pydatetime()
                if any(stamp(model.by_id[d]['available_at']) > when for d in ids):
                    raise ValueError('Unadmitted paper returned')
                target = model.position.get(row.arxiv_id)
                available = target is not None and model.available[target] <= when.timestamp() and row.arxiv_id not in model.sar.seen.get(row.user_id, set())
                if bool(available) != receipt['available_gold']:
                    raise ValueError('Gold availability changed')
                try:
                    rank = ids.index(row.arxiv_id) + 1
                except ValueError:
                    rank = 0
                values = np.array([1., float(rank > 0), 1 / math.log2(rank + 1) if rank else 0., 1 / rank if rank else 0.])
                uc = receipt['cold_user']; ic = receipt['cold_item_global']
                names = ['cold_item' if ic else 'warm_item',
                    f'{"cold" if uc else "warm"}_user__{"cold" if ic else "warm"}_item']
                if available:
                    names.append('eligible_cold_item' if ic else 'eligible_warm_item')
                for name in names:
                    group_sums[name] += values
                user_sums[row.user_id] += values; relevant[row.user_id].append(row.arxiv_id); used.update(active)
            userrows = read(userpath)
            if [r['user_id'] for r in userrows] != sorted(user_sums):
                raise ValueError('User denominator changed')
            for row in userrows:
                values = user_sums[row['user_id']]
                if row['relevant'] != sorted(relevant[row['user_id']]) or row['events'] != values[0]:
                    raise ValueError('Heldout relevance mismatch')
                for j, metric in enumerate(('recall', 'ndcg', 'mrr'), 1):
                    if abs(row[metric] - values[j] / values[0]) > 1e-12:
                        raise ValueError('User metric recount differs')
            for metric in ('recall', 'ndcg', 'mrr'):
                mean = sum(row[metric] for row in userrows) / len(userrows)
                if abs(mean - output['summary'][metric + '@10']) > 1e-12:
                    raise ValueError('Main macro metric recount differs')
            for name, expected in output['event_groups'].items():
                values = group_sums[name]
                if expected['events'] != values[0] or expected['hits'] != values[1]:
                    raise ValueError('Group denominator/hit recount differs')
                for j, metric in enumerate(('recall', 'ndcg', 'mrr'), 1):
                    if values[0] and abs(expected[metric] - values[j] / values[0]) > 1e-12:
                        raise ValueError('Group event-micro recount differs')
            for name, expected in output['user_groups'].items():
                subset = [r for r in userrows if r['cold_user'] == (name == 'cold_user')]
                if expected['users'] != len(subset):
                    raise ValueError('Cold-user count differs')
                for metric in ('recall', 'ndcg', 'mrr'):
                    if subset and abs(expected[metric] - sum(r[metric] for r in subset) / len(subset)) > 1e-12:
                        raise ValueError('User group macro recount differs')
            if output['summary']['catalog_coverage'] != len(used) / 10000:
                raise ValueError('Coverage recount differs')
            picks = sorted(range(len(frame)), key=lambda i: hashlib.sha256(
                ('stage15-verify:' + frame.at[i, 'user_id'] + ':' + frame.at[i, 'time']).encode()).hexdigest())[:16]
            for i in picks:
                row = frame.iloc[i]
                actual = model.rank_indices(row.user_id, row['at'].to_pydatetime(), mode, 10, alpha)
                np.testing.assert_array_equal(predictions[i, :len(actual)], actual)
            counts[f'{split}/{method}'] = {'events': len(frame), 'native_uncached_rank_replays': len(picks)}
            users[split, method] = userrows
        # Recount raw timing records independently; no per-request IDs leave local data/.
        latency = read(ROOT / f'latency-{split}.json')
        samples = read(DATA / f'latency-{split}.json')
        for method, stats in latency['methods'].items():
            values = [r['ms'] for r in samples if r['method'] == method]
            if len(values) != latency['requests'] * latency['passes']:
                raise ValueError('Latency requests missing')
            actual = {'mean_ms': float(np.mean(values)), 'median_ms': float(np.median(values)), 'p95_ms': float(np.quantile(values, .95))}
            if stats != actual:
                raise ValueError('Latency aggregate recount differs')
    return counts, users
