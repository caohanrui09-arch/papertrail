"""Bounded cold-fusion trial: tuning -> frozen choice -> descriptive dev."""
import argparse
import hashlib
from pathlib import Path
import time

import numpy as np

from .catalog_audit import digest
from .expansion_data import DATA as OLD_DATA, ROOT as OLD_ROOT, read, save
from .expansion_recommendation import signature
from .content_recommendation import sklearn_runtime
from .benchmark_expansion import events, check_plan as original_check
from .cold_fusion import load

ROOT = Path('reports/stage15')
DATA = Path('data/stage15-cold-fusion')
ALPHAS = (.25, .5, .75)
CODE = ('gsearch/cold_fusion.py', 'gsearch/benchmark_cold_fusion.py', 'scripts/audit_cold_fusion.py', 'tests/test_cold_fusion.py')


def history() -> None:
    from scripts.benchmark_indexed_expansion import frozen_history
    frozen_history()
    receipt = read(Path('reports/stage14/final-validation.json'))
    for group in ('outputs', 'code', 'data', 'report'):
        for path, expected in receipt[group].items():
            if digest(Path(path)) != expected:
                raise ValueError('Frozen stage14 changed: ' + path)
    original_check()


def state() -> dict:
    return {'code': {p: digest(Path(p)) for p in CODE},
        'stage14_receipt_sha256': digest(Path('reports/stage14/final-validation.json')),
        'stage13_plan_sha256': digest(OLD_ROOT / 'evaluation-plan.json'),
        'source_audit_sha256': digest(ROOT / 'upstream-audit.json'),
        'tuning_mechanism_sha256': digest(ROOT / 'tuning-mechanism-audit.json')}


def check_plan() -> dict:
    plan = read(ROOT / 'evaluation-plan.json')
    if plan['state'] != state():
        raise ValueError('Frozen cold-fusion protocol drift')
    return plan


def methods_for(split: str) -> dict:
    methods = {'content': ('content', 0.), 'rrf': ('hybrid', .5)}
    if split == 'tuning':
        for alpha in ALPHAS:
            tag = str(round(alpha * 100))
            methods['gated_a' + tag] = ('cold_aware', alpha)
            methods['plain_a' + tag] = ('score_blend', alpha)
    else:
        lock = read(ROOT / 'locked-before-dev.json')
        if lock['plan_sha256'] != digest(ROOT / 'evaluation-plan.json') or any(
            digest(ROOT / name) != expected for name, expected in lock['tuning_outputs'].items()):
            raise ValueError('Selection lock drift')
        methods.update({'gated': ('cold_aware', lock['diagnostic_alpha']),
                        'plain': ('score_blend', lock['diagnostic_alpha'])})
    return methods


def summarize(predictions: np.ndarray, frame, receipts: list[dict]) -> tuple[dict, list[dict]]:
    catalog = read(OLD_DATA / 'catalog-10000.json')
    # Catalog file stores tier IDs; order used by the model is always lexical base-ID.
    if isinstance(catalog, dict):
        catalog = catalog['doc_ids']
    position = {d: i for i, d in enumerate(sorted(catalog))}
    target = np.array([position.get(d, -2) for d in frame.arxiv_id], dtype=np.int32)
    equal = predictions == target[:, None]
    rank = np.where(equal.any(axis=1), equal.argmax(axis=1) + 1, 0)
    values = {'recall': (rank > 0).astype(float),
        'ndcg': np.divide(1, np.log2(rank + 1), out=np.zeros(len(rank)), where=rank > 0),
        'mrr': np.divide(1, rank, out=np.zeros(len(rank)), where=rank > 0)}
    cold_user = np.array([r['cold_user'] for r in receipts], dtype=bool)
    cold_item = np.array([r['cold_item_global'] for r in receipts], dtype=bool)
    available = np.array([r['available_gold'] for r in receipts], dtype=bool)
    rows = []
    for user, group in frame.groupby('user_id', sort=True):
        ix = group.index.to_numpy()
        rows.append({'user_id': user, 'relevant': sorted(group.arxiv_id.tolist()), 'events': len(ix),
            'cold_user': bool(cold_user[ix[0]]), **{m: float(v[ix].mean()) for m, v in values.items()}})
    user_groups = {}
    for cold in (False, True):
        subset = [r for r in rows if r['cold_user'] == cold]
        user_groups['cold_user' if cold else 'warm_user'] = {'users': len(subset),
            **{m: float(np.mean([r[m] for r in subset])) if subset else None for m in values}}
    groups = {}
    masks = {'warm_item': ~cold_item, 'cold_item': cold_item,
             'eligible_warm_item': ~cold_item & available, 'eligible_cold_item': cold_item & available}
    for uc in (False, True):
        for ic in (False, True):
            masks[f'{"cold" if uc else "warm"}_user__{"cold" if ic else "warm"}_item'] = (cold_user == uc) & (cold_item == ic)
    for name, mask in masks.items():
        groups[name] = {'events': int(mask.sum()), 'hits': int((rank[mask] > 0).sum()),
            **{m: float(v[mask].mean()) if mask.any() else None for m, v in values.items()}}
    return {'summary': {m + '@10': float(np.mean([r[m] for r in rows])) for m in values} | {
                'users': len(rows), 'positive_events': len(frame), 'catalog_coverage': len(set(predictions[predictions >= 0].tolist())) / 10000},
            'user_groups': user_groups, 'event_groups': groups,
            'metric_note': 'main metrics user-macro over singleton events; item/cross groups event-micro; all original positives retained'}, rows


def measure_latency(model, split: str, methods: dict) -> dict:
    frame = events(split)
    size = 128 if split == 'tuning' else 256
    picks = sorted(range(len(frame)), key=lambda i: hashlib.sha256(
        ('stage15-latency:' + frame.at[i, 'user_id'] + ':' + frame.at[i, 'time']).encode()).hexdigest())[:size]
    names = [name for name in methods if not name.startswith('plain')]
    if split == 'dev':
        names.append('plain')
    samples = {name: [] for name in names}; raw = []
    for name in names:
        mode, alpha = methods[name]; row = frame.iloc[picks[0]]
        model.rank_indices(row.user_id, row['at'].to_pydatetime(), mode, 10, alpha)
    for repeat in range(2):
        for j, i in enumerate(picks):
            row = frame.iloc[i]; at = row['at'].to_pydatetime()
            order = names[j % len(names):] + names[:j % len(names)]
            if repeat:
                order = order[::-1]
            for name in order:
                mode, alpha = methods[name]
                t = time.perf_counter_ns(); model.rank_indices(row.user_id, at, mode, 10, alpha)
                ms = (time.perf_counter_ns() - t) / 1e6
                samples[name].append(ms)
                raw.append({'pass': repeat, 'request': j, 'event_index': i, 'method': name, 'ms': ms})
    save(DATA / f'latency-{split}.json', raw)
    return {'requests': size, 'passes': 2, 'batch': 1, 'score_cache': False, 'rank_cache': False,
        'methods': {name: {'mean_ms': float(np.mean(v)), 'median_ms': float(np.median(v)),
                          'p95_ms': float(np.quantile(v, .95))} for name, v in samples.items()}}


def evaluate(split: str) -> None:
    check_plan(); methods = methods_for(split)
    if any((ROOT / f'{name}-{split}.json').exists() for name in methods):
        raise ValueError('Refuse to overwrite evaluations')
    sklearn_runtime()
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        model = load(); expected = read(OLD_ROOT / 'resource-10000.json')['model_signature']
        if signature(model) != expected:
            raise ValueError('Original model fit changed')
        frame = events(split); n = len(frame)
        receipts = read(OLD_DATA / f'10000-{split}-events.json')
        if len(receipts) != n or any(r['user_id'] != f.user_id or r['arxiv_id'] != f.arxiv_id or r['time'] != f.time
                                     for r, f in zip(receipts, frame.itertuples())):
            raise ValueError('Original event identity/order changed')
        arrays = {name: np.full((n, 10), -1, dtype=np.int32) for name in methods}
        groups = list(frame.groupby('user_id', sort=True)); cache = {}
        started = time.perf_counter()
        for number, (user, group) in enumerate(groups):
            if number % 64 == 0:
                users = [u for u, _ in groups[number:number + 64]]
                cf, text = model.batch_components(users)
                cache = {u: (cf[i], text[i]) for i, u in enumerate(users)}
            previous, daily, eligible = None, {}, None
            for row in group.itertuples():
                if row.at.date() != previous:
                    at = row.at.to_pydatetime(); eligible = model.eligible(user, at)
                    daily = {name: model.rank_indices(user, at, mode, 10, alpha,
                        components=cache[user], eligible_indices=eligible) for name, (mode, alpha) in methods.items()}
                    previous = row.at.date()
                target = model.position.get(row.arxiv_id, -2)
                if bool(target in eligible) != receipts[row.Index]['available_gold']:
                    raise ValueError('Eligibility denominator changed')
                if (user not in model.user2row) != receipts[row.Index]['cold_user']:
                    raise ValueError('User coldness changed')
                for name, hits in daily.items():
                    arrays[name][row.Index, :len(hits)] = hits
            if (number + 1) % 1000 == 0:
                print({'phase': split, 'users': number + 1}, flush=True)
        quality_seconds = time.perf_counter() - started
        # Strong references: the unchanged controls must reproduce every original event ranking.
        for name, old_method in (('content', 'content'), ('rrf', 'hybrid_a050' if split == 'tuning' else 'hybrid')):
            with np.load(OLD_DATA / f'10000-{old_method}-{split}.npz', allow_pickle=False) as old:
                np.testing.assert_array_equal(arrays[name], old['indices'])
        for name, predictions in arrays.items():
            result, users = summarize(predictions, frame, receipts)
            raw = DATA / f'{name}-{split}.npz'; np.savez_compressed(raw, indices=predictions)
            user_path = DATA / f'{name}-{split}-users.json'; save(user_path, users)
            result.update({'method': name, 'split': split, 'mode_and_alpha': list(methods[name]),
                'predictions_sha256': digest(raw), 'users_sha256': digest(user_path),
                'events_sha256': digest(OLD_DATA / f'10000-{split}-events.json'),
                'plan_sha256': digest(ROOT / 'evaluation-plan.json'), 'model_signature': expected,
                'quality_replay_seconds_all_methods': quality_seconds,
                'cost_note': 'offline scorer batches64 users/daily reuse; service latency is measured separately without scores/ranks cached'})
            save(ROOT / f'{name}-{split}.json', result)
            print({'split': split, 'method': name, **result['summary']}, flush=True)
        save(ROOT / f'latency-{split}.json', measure_latency(model, split, methods))
        if signature(model) != expected:
            raise ValueError('Inference mutated model')


def acceptance(candidate: dict, content: dict, cost: dict, base_cost: dict) -> dict:
    checks = {}
    for metric in ('recall', 'ndcg'):
        checks['overall_' + metric] = candidate['summary'][metric + '@10'] >= content['summary'][metric + '@10'] - 1e-15
        checks['cold_item_' + metric] = candidate['event_groups']['cold_item'][metric] >= content['event_groups']['cold_item'][metric] - 1e-15
        checks['warm_item_' + metric] = candidate['event_groups']['warm_item'][metric] >= .95 * content['event_groups']['warm_item'][metric] - 1e-15
        checks['warm_user_' + metric] = candidate['user_groups']['warm_user'][metric] >= .95 * content['user_groups']['warm_user'][metric] - 1e-15
    for metric in ('mean_ms', 'p95_ms'):
        checks[metric] = cost[metric] <= 1.5 * base_cost[metric]
    return {'passed': all(checks.values()), 'checks': checks}


def lock() -> None:
    check_plan()
    path = ROOT / 'locked-before-dev.json'
    if path.exists():
        raise ValueError('Selection already frozen')
    content = read(ROOT / 'content-tuning.json'); costs = read(ROOT / 'latency-tuning.json')['methods']
    candidates = {f'gated_a{round(a * 100)}': read(ROOT / f'gated_a{round(a * 100)}-tuning.json') for a in ALPHAS}
    checks = {name: acceptance(r, content, costs[name], costs['content']) for name, r in candidates.items()}
    eligible = [name for name, r in checks.items() if r['passed']]
    def key(name):
        s = candidates[name]['summary']
        return s['ndcg@10'], s['recall@10'], s['mrr@10'], -candidates[name]['mode_and_alpha'][1]
    # If no candidate passes, freeze a diagnostic candidate before dev and retain content serving.
    chosen = max(eligible or list(candidates), key=key)
    output = {'selected_for_research': chosen, 'diagnostic_alpha': candidates[chosen]['mode_and_alpha'][1],
        'passes_tuning_acceptance': bool(eligible), 'acceptance_by_candidate': checks,
        'quality_selection': 'feasible candidates by user-macro NDCG/Recall/MRR, then smaller alpha; otherwise best diagnostic candidate only',
        'serving_choice_after_tuning': 'content', 'no_default_switch': True,
        'dev_methods': ['content', 'rrf', 'gated', 'plain'],
        'plan_sha256': digest(ROOT / 'evaluation-plan.json'),
        'tuning_outputs': {p.name: digest(p) for p in sorted(ROOT.glob('*-tuning.json'))}}
    save(path, output); print(output, flush=True)


def main() -> None:
    p = argparse.ArgumentParser(); p.add_argument('--phase', choices=('plan', 'tuning', 'lock', 'dev'), required=True)
    args = p.parse_args(); ROOT.mkdir(parents=True, exist_ok=True); DATA.mkdir(parents=True, exist_ok=True)
    if args.phase == 'plan':
        if (ROOT / 'evaluation-plan.json').exists():
            raise ValueError('Plan already exists')
        history()
        save(ROOT / 'evaluation-plan.json', {'state': state(), 'client_date': '2026-10-27', 'tier': 10000,
            'alphas': list(ALPHAS), 'original_rrf_alpha': .5, 'rrf_constant': 60,
            'formula': 'z_cf=minmax(cf on eligible); z_text=minmax(text on eligible); score=(alpha*support*z_cf+(1-alpha)*z_text)/(alpha*support+1-alpha); support=item in frozen SAR vocabulary',
            'ablation': 'plain score blend uses same normalization/alpha but no support renormalization',
            'zero_score': 'a warm item with zero CF score is supported; do not turn score0 into a missing-branch label',
            'causality': 'same frozen train/profile/vocabulary/v1/as-of/seen; extrema only current eligible; no future-feedback update',
            'metrics': 'same full positive-event denominator; main user-macro Recall/NDCG/MRR; item and cross groups event-micro; eligible subsets diagnostic only',
            'acceptance': {'overall_recall_and_ndcg': '>=content point estimates', 'global_cold_item_recall_and_ndcg': '>=content',
                'warm_item_and_warm_user_recall_and_ndcg': '>=95% of content', 'latency_mean_and_p95': '<=1.5x content paired same run',
                'interpretation': 'predeclared engineering point guards, not statistical non-inferiority tests'},
            'latency': 'fixed hash128 tuning/256 dev requests; two passes; rotate/reverse methods; CPU single numerical thread; no score or ranking cache',
            'selection': 'only 3 gated alphas compete on tuning; matched plain variants are ablation only; lock all code/data/choice before dev',
            'failure_policy': 'if no candidate passes tuning, keep content and freeze only the best diagnostic alpha for descriptive dev',
            'serving_policy': 'content remains default; this trial does not switch production/old Agent defaults',
            'dev': 'reused descriptive only; one frozen diagnostic alpha, no new parameter selection',
            'confidence': '10000 paired user bootstrap for main deltas; no independent test/generalization claim'})
    elif args.phase == 'lock':
        lock()
    else:
        evaluate(args.phase)


if __name__ == '__main__':
    main()
