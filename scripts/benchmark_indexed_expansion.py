"""Exact replay and paired uncached latency; no model/quality parameter selection."""
import gc
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

from gsearch.catalog_audit import digest, stamp
from gsearch.expansion_data import DATA as OLD_DATA, ROOT as OLD_ROOT, read, save
from gsearch.expansion_recommendation import load, signature
from gsearch.indexed_expansion import IndexedExpansionRecommender
from gsearch.benchmark_expansion import events, FUSIONS, check_plan
from gsearch.content_recommendation import sklearn_runtime

ROOT = Path('reports/stage14')
DATA = Path('data/stage14-indexed')
CODE = ('gsearch/indexed_expansion.py', 'scripts/benchmark_indexed_expansion.py', 'tests/test_indexed_expansion.py')


def frozen_history():
    from scripts.make_stage13_report import historical
    historical()
    receipt = read(OLD_ROOT / 'final-validation.json')
    for root, field in ((OLD_ROOT, 'outputs'), (OLD_DATA, 'data_assets'), (Path('.'), 'code_assets')):
        for name, expected in receipt[field].items():
            if digest(root / name) != expected:
                raise ValueError('Historical stage13 asset changed: ' + name)
    check_plan()


def freeze():
    plan = {'client_date': '2026-10-27', 'tier': 10000,
        'scope': 'eligibility filtering only; original score functions, ranks, ties, alpha, training and text unchanged',
        'quality_gate': 'all 46352 tuning and 49533 dev positive-event Top10 arrays exactly identical for every stage13 method',
        'latency': {'requests': 256, 'passes': 2, 'batch': 1, 'numerical_threads': 1,
            'score_cache': False, 'rank_cache': False, 'ordering': 'rotate methods per request, alternate original/indexed order per request and pass',
            'sample': 'same stage13-latency SHA256(user,time) selection, no success/rank/label-based filtering',
            'excludes': 'model loading, fit, sparse seen-index construction and original-abstract reading; measured separately'},
        'repetitions': 'fixed two full paired passes, do not stop/select by favorable timing',
        'no_quality_selection': True, 'dev': 'reused descriptive replay; equality check is not new independent test',
        'code': {p: digest(Path(p)) for p in CODE},
        'upstream_audit_sha256': digest(ROOT / 'upstream-audit.json'),
        'stage13_final_receipt_sha256': digest(OLD_ROOT / 'final-validation.json'),
        'stage13_plan_sha256': digest(OLD_ROOT / 'evaluation-plan.json')}
    if (ROOT / 'evaluation-plan.json').exists():
        if read(ROOT / 'evaluation-plan.json') != plan:
            raise ValueError('Stage14 plan/code drift; preserve prior runs')
    else:
        save(ROOT / 'evaluation-plan.json', plan)
    return plan


def replay(model):
    locked = read(OLD_ROOT / 'locked-before-dev.json')['tiers']['10000']['alpha']
    all_results = {}
    for split in ('tuning', 'dev'):
        f = events(split)
        methods = {'popular': ('popular', .5), 'sar': ('sar', .5), 'content': ('content', .5)}
        methods.update({name: ('hybrid', alpha) for name, alpha in FUSIONS.items()} if split == 'tuning' else {'hybrid': ('hybrid', locked)})
        predictions = {name: np.full((len(f), 10), -1, dtype=np.int32) for name in methods}
        groups = list(f.groupby('user_id', sort=True))
        cache = {}
        for number, (user, group) in enumerate(groups):
            if number % 64 == 0:
                users = [u for u, _ in groups[number:number + 64]]
                cf, text = model.batch_components(users)
                cache = {u: (cf[i], text[i]) for i, u in enumerate(users)}
            # Daily caching is only for equality replay, never for service timing.
            previous_day, daily = None, None
            for row in group.itertuples():
                if row.at.date() != previous_day:
                    eligible = model.eligible(user, row.at.to_pydatetime())
                    daily = {name: model.rank_indices(user, row.at.to_pydatetime(), mode, 10, alpha,
                             components=cache[user], eligible_indices=eligible)
                             for name, (mode, alpha) in methods.items()}
                    previous_day = row.at.date()
                for name, hits in daily.items():
                    predictions[name][row.Index, :len(hits)] = hits
            if (number + 1) % 1000 == 0:
                print(json.dumps({'phase': 'exact_replay', 'split': split, 'users': number + 1}), flush=True)
        for name, actual in predictions.items():
            old_path = OLD_DATA / f'10000-{name}-{split}.npz'
            with np.load(old_path, allow_pickle=False) as old:
                equal = np.array_equal(actual, old['indices'])
                changed = int(np.count_nonzero(np.any(actual != old['indices'], axis=1)))
            if not equal:
                raise ValueError(f'Ranking changed: {split}/{name}, events={changed}')
            new_path = DATA / old_path.name
            np.savez_compressed(new_path, indices=actual)
            all_results[f'{split}/{name}'] = {'events': len(f), 'changed_events': changed,
                'exact_order_including_padding': equal, 'original_sha256': digest(old_path),
                'new_sha256': digest(new_path), 'array_sha256': hashlib.sha256(actual.tobytes()).hexdigest()}
        print(json.dumps({'phase': 'replay_complete', 'split': split, 'events': len(f)}), flush=True)
    return all_results


def factor_boundaries(original, fast):
    # Exhaust all user-specific static membership factors and every time threshold.
    seen_users = 0
    for user, seen in original.sar.seen.items():
        expected = np.array([i for i, doc in enumerate(original.catalog) if doc in seen], dtype=np.int32)
        actual = fast._seen_positions.get(user, np.array([], dtype=np.int32))
        np.testing.assert_array_equal(np.sort(actual), expected)
        seen_users += 1
    times = {original.cutoff.timestamp()}
    for available in np.unique(original.available):
        if available >= original.cutoff.timestamp():
            # Real source timestamps have microsecond resolution; test both sides and exact equality.
            times.update((available - .000001, available, available + .000001))
    from datetime import datetime, timezone
    for at in sorted(times):
        if at < original.cutoff.timestamp():
            continue
        when = datetime.fromtimestamp(at, tz=timezone.utc)
        np.testing.assert_array_equal(original.eligible('__stage14_no_train_history__', when),
                                      fast.eligible('__stage14_no_train_history__', when))
    return {'all_train_seen_users_checked': seen_users, 'distinct_time_boundaries_checked': len(times),
            'candidate_checks_per_factor': len(original.catalog), 'composition': 'available AND NOT train-seen'}


def timings(original, fast):
    f = events('dev')
    picks = sorted(range(len(f)), key=lambda i: hashlib.sha256(
        ('stage13-latency:' + f.at[i, 'user_id'] + ':' + f.at[i, 'time']).encode()).hexdigest())[:256]
    alpha = read(OLD_ROOT / 'locked-before-dev.json')['tiers']['10000']['alpha']
    methods = ('popular', 'sar', 'content', 'hybrid')
    values = {method: {'original': [], 'indexed': []} for method in (*methods, 'eligibility')}
    private_rows = []
    for engine in (original, fast):
        for method in methods:
            engine.rank_indices(f.iloc[picks[0]].user_id, f.iloc[picks[0]]['at'].to_pydatetime(), method, 10, alpha)
    for repeat in range(2):
        for j, i in enumerate(picks):
            row = f.iloc[i]
            at = row['at'].to_pydatetime()
            order = methods[j % 4:] + methods[:j % 4] + ('eligibility',)
            for method in order:
                engines = (('original', original), ('indexed', fast))
                if (j + repeat) % 2:
                    engines = engines[::-1]
                outputs = {}
                for name, engine in engines:
                    t = time.perf_counter_ns()
                    result = engine.eligible(row.user_id, at) if method == 'eligibility' else engine.rank_indices(row.user_id, at, method, 10, alpha)
                    elapsed = (time.perf_counter_ns() - t) / 1e6
                    values[method][name].append(elapsed)
                    outputs[name] = result
                    private_rows.append({'pass': repeat, 'request': j, 'event_index': i, 'method': method, 'engine': name, 'ms': elapsed})
                np.testing.assert_array_equal(outputs['original'], outputs['indexed'])
            if (j + 1) % 64 == 0:
                print(json.dumps({'phase': 'latency', 'pass': repeat, 'requests': j + 1}), flush=True)
    save(DATA / 'paired-latency-requests.json', private_rows)
    def summary(v):
        return {'mean_ms': float(np.mean(v)), 'median_ms': float(np.median(v)), 'p95_ms': float(np.quantile(v, .95))}
    return {method: {'original': summary(v['original']), 'indexed': summary(v['indexed']),
                     'mean_speedup': float(np.mean(v['original']) / np.mean(v['indexed'])),
                     'paired_mean_delta_ms': float(np.mean(np.array(v['indexed']) - v['original']))}
            for method, v in values.items()}


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    if (ROOT / 'benchmark.json').exists():
        raise ValueError('Refuse to overwrite completed measurements')
    frozen_history()
    plan = freeze()
    sklearn_runtime()
    from threadpoolctl import threadpool_limits, threadpool_info
    import psutil
    with threadpool_limits(limits=1):
        start = time.perf_counter()
        original = load(10000)
        load_seconds = time.perf_counter() - start
        expected = read(OLD_ROOT / 'resource-10000.json')['model_signature']
        if signature(original) != expected:
            raise ValueError('Fitted model drift')
        gc.collect()
        process = psutil.Process()
        before_rss = process.memory_info().rss
        fast = IndexedExpansionRecommender(original)
        after_rss = process.memory_info().rss
        index_cost = dict(fast.index_stats)
        index_cost.update({'observed_rss_delta_bytes': after_rss - before_rss,
            'python_container_and_array_object_bytes': sys.getsizeof(fast._seen_positions) + sum(sys.getsizeof(x) for x in fast._seen_positions.values()),
            'loading_and_original_fit_seconds': load_seconds,
            'rss_note': 'same-process point difference, not peak allocation or isolated-process estimate; object count excludes shared user string keys'})
        boundaries = factor_boundaries(original, fast)
        print(json.dumps({'phase': 'factor_boundaries_complete', **boundaries}), flush=True)
        latency = timings(original, fast)
        equal = replay(fast)
        if signature(original) != expected or signature(fast) != expected:
            raise ValueError('Inference mutated original model')
        save(ROOT / 'benchmark.json', {'plan_sha256': digest(ROOT / 'evaluation-plan.json'),
            'index_cost': index_cost, 'factor_boundaries': boundaries, 'exact_replay': equal,
            'paired_uncached_latency': latency, 'threadpools': threadpool_info(),
            'model_signature_unchanged': True, 'original_receipt_sha256': plan['stage13_final_receipt_sha256'],
            'runtime': {'numpy': np.__version__, 'python': sys.version}, 'quality_change': 'zero; every ranking identical'})
    frozen_history()
    print(json.dumps({'phase': 'complete', 'rankings_exact': len(equal), 'history_unchanged': True}), flush=True)


if __name__ == '__main__':
    main()
