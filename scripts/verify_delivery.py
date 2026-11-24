"""Read-only verification of the existing offline delivery, without rerunning tuning."""
import argparse
import json
from pathlib import Path

from gsearch.showcase import preflight, verify_receipt


def verify(full: bool = False, demo: dict | None = None) -> dict:
    result = preflight()
    if full:
        from gsearch.benchmark_cold_fusion import history, check_plan
        history(); check_plan()
        result['stage15_sealed_assets_checked'] = verify_receipt(Path('reports/stage15/final-validation.json'), ('outputs', 'code', 'data', 'report'))
        from scripts.validate_expansion import validate_corpus
        from scripts.validate_cold_fusion import validate_outputs, source_runtime
        from gsearch.cold_fusion import load
        from gsearch.expansion_recommendation import signature
        from threadpoolctl import threadpool_limits
        with threadpool_limits(limits=1):
            result['source_runtime'] = source_runtime()
            source = validate_corpus()
            result['official_v1_records_reparsed'] = source['verified_records']
            model = load(); before = signature(model)
            checked, _ = validate_outputs(model)
            if demo is not None:
                from gsearch.showcase import verify_demo
                from gsearch.expansion_data import read
                alpha = read(Path('reports/stage15/locked-before-dev.json'))['diagnostic_alpha']
                result['demo_originals_reparsed_and_rankings_replayed'] = verify_demo(model, demo, alpha)
            if signature(model) != before:
                raise ValueError('Read-only verification mutated model')
            result['raw_outputs_rescored'] = len(checked)
            result['event_method_rankings_rescored'] = sum(r['events'] for r in checked.values())
            result['historical_stages3_15_unchanged'] = True
    result['verification_mode'] = 'full_read_only' if full else 'preflight'
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--full', action='store_true')
    args = p.parse_args(); print(json.dumps(verify(args.full), ensure_ascii=False))


if __name__ == '__main__':
    main()
