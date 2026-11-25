"""Summarise the filled human-label sheet.

Usage: python -m scripts.score_labels [path]
Prints per-kind support / relevance / citation / refusal rates with counts.
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'data/annotation/labels_v98.csv'


def rate(values: list[int], threshold: int = 1) -> str:
    if not values:
        return 'n/a'
    hit = sum(1 for v in values if v >= threshold)
    return f'{hit}/{len(values)} ({100 * hit / len(values):.0f}%)'


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    rows = list(csv.DictReader(path.open(encoding='utf-8-sig')))
    filled = [r for r in rows if (r.get('support_0_2') or '').strip()]
    print(f'rows: {len(rows)}  filled: {len(filled)}  file: {path.relative_to(ROOT)}')
    if not filled:
        print('no labels yet; fill support_0_2 / relevance_0_2 / citation_ok_Y_N / refusal_ok_Y_N_NA')
        return

    by_kind: dict[str, list[dict]] = {}
    for row in filled:
        by_kind.setdefault(row['kind'], []).append(row)

    summary = {}
    for kind, group in sorted(by_kind.items()):
        support = [int(r['support_0_2']) for r in group if (r.get('support_0_2') or '').strip().isdigit()]
        relevance = [int(r['relevance_0_2']) for r in group if (r.get('relevance_0_2') or '').strip().isdigit()]
        citations = [r['citation_ok_Y_N'].strip().upper() for r in group if (r.get('citation_ok_Y_N') or '').strip()]
        refusals = [r['refusal_ok_Y_N_NA'].strip().upper() for r in group if (r.get('refusal_ok_Y_N_NA') or '').strip()]
        decided = [r for r in refusals if r in ('Y', 'N')]
        block = {
            'n': len(group),
            'support_ge1': rate(support, 1),
            'support_eq2': rate(support, 2),
            'relevance_ge1': rate(relevance, 1),
            'citation_ok': f"{citations.count('Y')}/{len(citations)}" if citations else 'n/a',
            'refusal_ok': f"{sum(1 for r in decided if r == 'Y')}/{len(decided)}" if decided else 'n/a',
        }
        summary[kind] = block
        print(json.dumps({kind: block}, ensure_ascii=False))
    print(json.dumps({'summary': summary}, ensure_ascii=False))


if __name__ == '__main__':
    main()
