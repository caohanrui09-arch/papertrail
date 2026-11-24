"""Exact stage13 ranking with a train-only sparse seen index and native NumPy masks.

Only for the frozen model/catalog/history snapshot; construct a new adapter after
any history or catalog update. No component scores or rankings are cached.
"""
import argparse
import json
from pathlib import Path
import time

import numpy as np

from .catalog_audit import stamp
from .expansion_recommendation import ExpansionRecommender, load as original_load


class IndexedExpansionRecommender(ExpansionRecommender):
    def __init__(self, model: ExpansionRecommender):
        # Share the already fitted, frozen arrays; do not duplicate SAR or refit.
        self.__dict__.update(model.__dict__)
        started = time.perf_counter()
        self._seen_positions = {}
        for user, seen in self.sar.seen.items():
            positions = np.fromiter((self.position[d] for d in seen if d in self.position), dtype=np.int32)
            positions.flags.writeable = False
            if len(positions):
                self._seen_positions[user] = positions
        self.index_stats = {
            'users_with_catalog_seen': len(self._seen_positions),
            'positions': sum(len(x) for x in self._seen_positions.values()),
            'array_payload_bytes': sum(x.nbytes for x in self._seen_positions.values()),
            'build_seconds': time.perf_counter() - started,
            'contract': 'frozen catalog and train history; rebuild after any update',
        }

    def eligible(self, user: str, at: object) -> np.ndarray:
        when = stamp(at)
        if when is None or when < self.cutoff:
            raise ValueError('Request must be at/after frozen history cutoff')
        mask = self.available <= when.timestamp()
        seen = self._seen_positions.get(user)
        if seen is not None:
            mask[seen] = False
        return np.flatnonzero(mask).astype(np.int32, copy=False)


def load(tier: int = 10000) -> IndexedExpansionRecommender:
    return IndexedExpansionRecommender(original_load(tier))


def main() -> None:
    from .expansion_data import ROOT, read, save
    from .expansion_discovery import ExpansionSession, make_tools
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tier', type=int, choices=(1000, 5000, 10000), default=10000)
    p.add_argument('--user', required=True)
    p.add_argument('--at', required=True)
    p.add_argument('--method', choices=('popular', 'sar', 'content', 'hybrid'), default='hybrid')
    p.add_argument('--k', type=int, default=3)
    p.add_argument('--read-top1', action='store_true')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if not a.output.resolve().is_relative_to(Path('data').resolve()):
        raise ValueError('Per-user outputs must stay in ignored local data/')
    model = load(a.tier)
    alpha = read(ROOT / 'locked-before-dev.json')['tiers'][str(a.tier)]['alpha']
    session = ExpansionSession(model, a.user, a.at, a.method, alpha)
    tools = {tool.name: tool for tool in make_tools(session)}
    recommendation = tools['recommend_papers'](k=a.k)
    original = tools['read_paper'](doc_id=recommendation['papers'][0]['doc_id']) if a.read_top1 and recommendation['papers'] else None
    save(a.output, {'recommendation': recommendation, 'original_version_abstract': original,
                    'trace': session.trace, 'index_stats': model.index_stats})
    print(json.dumps({'output': str(a.output), 'source_verified': original['source_verified'] if original else None}))


if __name__ == '__main__':
    main()
