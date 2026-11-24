"""Supported-branch score fusion using native sklearn minmax_scale.

The branch-support adapter is project-specific. Native scorers, normalization,
as-of/seen filtering, tie ordering and original-v1 reading are reused unchanged.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from .indexed_expansion import IndexedExpansionRecommender
from .expansion_recommendation import load as original_load


class ColdAwareRecommender(IndexedExpansionRecommender):
    def __init__(self, model):
        super().__init__(model)
        self._cf_supported = np.zeros(len(self.catalog), dtype=bool)
        self._cf_supported[self.warm_positions] = True

    def fused_scores(self, cf: np.ndarray, text: np.ndarray, eligible: np.ndarray,
                     alpha: float, gated: bool = True) -> np.ndarray:
        from sklearn.preprocessing import minmax_scale
        if not 0 <= alpha < 1:
            raise ValueError('Fusion alpha must be in [0,1) so the content branch remains available')
        if not len(eligible):
            return np.array([], dtype=float)
        # Normalize only current available, unseen documents. Future items cannot change extrema.
        a = minmax_scale(cf[eligible], copy=True)
        b = minmax_scale(text[eligible], copy=True)
        support = self._cf_supported[eligible]
        scores = alpha * a + (1 - alpha) * b
        if gated:
            # Missing CF support is defined by training vocabulary, not by a zero score.
            # Equivalent to dividing by alpha*support + (1-alpha); avoid round-off for cold items.
            scores[~support] = b[~support]
        if not np.isfinite(scores).all():
            raise ValueError('Nonfinite fusion scores')
        return scores

    def rank_indices(self, user: str, at: object, method: str, k: int = 10, alpha: float = .5,
                     components: tuple[np.ndarray, np.ndarray] | None = None,
                     eligible_indices: np.ndarray | None = None) -> np.ndarray:
        if method not in ('cold_aware', 'score_blend'):
            return super().rank_indices(user, at, method, k, alpha, components, eligible_indices)
        if not 0 <= alpha < 1 or not 1 <= k <= 100:
            raise ValueError('Invalid alpha/K')
        if alpha == 0 or user not in self.user2row or user in self.zero_profile_users:
            return super().rank_indices(user, at, 'content', k, 0, components, eligible_indices)
        eligible = self.eligible(user, at) if eligible_indices is None else eligible_indices
        cf, text = self.components(user) if components is None else components
        scores = self.fused_scores(cf, text, eligible, alpha, gated=method == 'cold_aware')
        return eligible[np.argsort(-scores, kind='stable')[:k]]


def load() -> ColdAwareRecommender:
    return ColdAwareRecommender(original_load(10000))


def main() -> None:
    from .expansion_data import read, save
    from .expansion_discovery import ExpansionSession, make_tools
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--user', required=True); p.add_argument('--at', required=True)
    p.add_argument('--method', choices=('recommended', 'content', 'hybrid', 'cold_aware', 'score_blend'), default='recommended')
    p.add_argument('--k', type=int, default=3); p.add_argument('--read-top1', action='store_true')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if not args.output.resolve().is_relative_to(Path('data').resolve()):
        raise ValueError('Per-user outputs must stay in ignored local data/')
    lock = read(Path('reports/stage15/locked-before-dev.json'))
    # Research selection and default serving are separate: repeated dev is not independent evidence.
    method = 'content' if args.method == 'recommended' else args.method
    alpha = .5 if method == 'hybrid' else lock['diagnostic_alpha']
    model = load(); session = ExpansionSession(model, args.user, args.at, method, alpha)
    tools = {tool.name: tool for tool in make_tools(session)}
    recommendation = tools['recommend_papers'](k=args.k)
    original = tools['read_paper'](doc_id=recommendation['papers'][0]['doc_id']) if args.read_top1 and recommendation['papers'] else None
    save(args.output, {'recommendation': recommendation, 'original_version_abstract': original,
                       'trace': session.trace, 'selection': lock, 'explicit_experimental_override': args.method != 'recommended'})
    print(json.dumps({'output': str(args.output), 'method': method, 'source_verified': bool(original and original['source_verified'])}))


if __name__ == '__main__':
    main()
