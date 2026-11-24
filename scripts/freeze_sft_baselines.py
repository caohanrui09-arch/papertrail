"""Recreate or verify the pre-prediction stage45 baseline contract."""
import json
from pathlib import Path

from gsearch.quality_protocol import digest,save


def main() -> None:
    path=Path('reports/stage45/baseline-design.json')
    files=[Path('scripts/baseline_sid_sft.py'),Path('data/stage45-sft/content-tfidf.npz'),
           Path('data/stage45-sft/text-vocabulary.json'),Path('gsearch/paper_recommendation.py')]
    value={'frozen_before_quality_predictions':True,
        'history':'same last20 eligible training likes as neural; all training positive and negative seen mask',
        'sar_fit':'all eligible positive candidate feedback; official MIT Jaccard SAR; scoring pseudo-affinity uses same last20, cold-item zero',
        'content':'native sklearn linear cosine using frozen train-catalog TFIDF; mean last20 profile normalized',
        'zero_context':'identical frozen training popularity fallback','ties':'canonical doc ID',
        'inputs':'tuning inputs only; no labels','files':{str(p):digest(p) for p in files}}
    if path.exists():
        assert json.loads(path.read_text())==value
        print({'existing_baseline_contract_verified':True})
        return
    assert not list(Path('data/stage45-sft').glob('*.predictions.jsonl'))
    assert not Path('reports/stage45/run-lock.json').exists()
    save(path,value)
    print({'baseline_contract_frozen':True,'sha256':digest(path)})


if __name__=='__main__':main()
