"""Seal/recheck the model-only review; never converts it to human annotation."""
from collections import Counter
import importlib.metadata as metadata
import json
from pathlib import Path

from gsearch.quality_protocol import digest, read_csv, save
from gsearch.showcase import verify_receipt
from scripts.assemble_model_review import ROOT, REPORTS, formal_state, load


GROUPS = ('code', 'docs', 'report', 'outputs', 'private_review')


def main() -> None:
    receipt = REPORTS/'final-validation.json'
    if receipt.exists():
        checked = verify_receipt(receipt, GROUPS)
        print(json.dumps({'sealed_review_verified': True, 'assets': checked,
                          'receipt_sha256': digest(receipt)}))
        return
    summary = load(REPORTS/'review-summary.json')
    result = load(ROOT/'judgments-model.json')
    tasks = load(ROOT/'blind-input.json')
    rows = result['judgments']
    original = {(q, c['annotation_id']): c['paper'] for q, t in tasks.items() for c in t['candidates']}
    assert len(rows) == len(original) == 155
    assert {(r['query_id'], r['annotation_id']) for r in rows} == set(original)
    for row in rows:
        paper = original[row['query_id'], row['annotation_id']]
        assert row['doc_id'] == paper['doc_id'] and row['version_key'] == paper['version_key']
        assert row['source_url'] == paper['source_url']
        assert row['evidence'] in paper['abstract'] and row['rationale'].strip()
        assert row['human'] is False and row['independent'] is False
        assert row['judgment_origin'] == 'model_blind_review'
        assert row['grade'] is None or (type(row['grade']) is int and row['grade'] in (0, 1, 2))
    counts = Counter('unknown' if r['grade'] is None else str(r['grade']) for r in rows)
    assert summary['counts'] == {k: counts[k] for k in ('2','1','0','unknown')}
    csv_rows = read_csv(ROOT/'judgments-model.csv')
    assert len(csv_rows) == len(rows)
    for a, b in zip(csv_rows, rows):
        assert a['annotation_id'] == b['annotation_id']
        assert a['grade'] == ('' if b['grade'] is None else str(b['grade']))
        assert a['judgment_origin'] == 'model_blind_review' and a['human'] == 'False'
    assert formal_state() == summary['formal_state']
    versions = {d.metadata['Name']: d.version for d in metadata.distributions()}
    assert versions == load(Path('reports/stage17/runtime-versions.json'))['installed_versions']
    assert summary['quality_metrics_computed'] is False and summary['algorithm_selection_performed'] is False
    files = ['scripts/prepare_model_review.py','scripts/assemble_model_review.py','scripts/verify_model_review_delivery.py']
    for name in files:
        compile(Path(name).read_text(encoding='utf-8'), name, 'exec')
    save(receipt, {'status': 'complete_model_assisted_review', 'human': False, 'independent': False,
        'queries': 9, 'pairs': 155, 'unique_candidate_abstracts': 101, 'context_abstracts': 15,
        'counts': summary['counts'], 'exact_evidence_and_pair_identity_verified': True,
        'csv_json_consistent': True, 'formal_state': summary['formal_state'],
        'cpu_packages_unchanged': len(versions), 'old_assets_unchanged': summary['old_assets_unchanged'],
        'stage25_assets_unchanged': summary['stage25_assets_unchanged'],
        'quality_metrics_computed': False, 'algorithm_selection_performed': False,
        'code': {p: digest(Path(p)) for p in files},
        'docs': {'docs/MODEL_BLIND_REVIEW_PROTOCOL.md': digest(Path('docs/MODEL_BLIND_REVIEW_PROTOCOL.md'))},
        'report': {'reports/阶段27_模型辅助盲审.md': digest(Path('reports/阶段27_模型辅助盲审.md'))},
        'outputs': {str(p): digest(p) for p in REPORTS.glob('*.json') if p != receipt},
        'private_review': {str(p): digest(p) for p in ROOT.iterdir() if p.is_file()},
        'mutable_human_database_excluded': True})
    print(json.dumps({'status': 'sealed', 'assets': verify_receipt(receipt, GROUPS),
        'counts': summary['counts'], 'receipt_sha256': digest(receipt)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
