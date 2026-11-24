"""Seal/recheck the offline coverage diagnosis and unchanged historical assets."""
from collections import Counter
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import re

import numpy as np

from gsearch.quality_protocol import digest, save
from gsearch.showcase import verify_receipt
from scripts.assemble_model_review import formal_state
from scripts.audit_topic_coverage import ANCHORS, ROOT, REPORT, load

GROUPS = ('code','report','outputs','private_diagnostic')


def main() -> None:
    receipt = REPORT/'final-validation.json'
    if receipt.exists():
        print(json.dumps({'verified_existing':True,'assets':verify_receipt(receipt,GROUPS),
                          'receipt_sha256':digest(receipt)}))
        return
    manifest = load(ROOT/'input-manifest.json')
    for name, expected in manifest['files'].items():assert digest(Path(name)) == expected, name
    source = load('data/stage13-expansion/documents.json')
    source_map = {p['doc_id']:p for p in source}
    summary = load(REPORT/'corpus-profile-summary.json')
    screen = load(ROOT/'screening-papers.json')
    assert summary['catalog'] == len(source) == 10000
    assert summary['screened_union'] == len(screen) == 91
    for row in screen:assert row['paper'] == source_map[row['paper']['doc_id']]
    new = load(ROOT/'screening-new-reader.json')
    notes = []
    for path in sorted(ROOT.glob('abstract-notes-*.json')):notes.extend(load(path))
    assert len(notes) == len(new) == 61
    assert len({n['doc_id'] for n in notes}) == 61
    assert {n['doc_id'] for n in notes} == {r['paper']['doc_id'] for r in new}
    for note in notes:
        assert note['finding'].strip() and note['core_support'] == []
        if 'evidence' in note:assert note['evidence'] in source_map[note['doc_id']]['abstract']
    prior = load('data/stage27-model-review/judgments-model.json')['judgments']
    old_ids = {r['paper']['doc_id'] for r in screen if r['already_read_stage27']}
    assert len(old_ids) == 30 and old_ids <= {r['doc_id'] for r in prior}
    assert all(r['grade'] != 2 for r in prior if r['doc_id'] in old_ids)
    anchors = load(ROOT/'reference-membership.json')
    external = load(ROOT/'external-reference-checks.json')['references']
    assert len(anchors) == len(external) == len(ANCHORS) == 6
    assert {r['doc_id'] for r in external} == {a[0] for a in ANCHORS}
    for anchor in anchors:
        assert anchor['doc_id'] not in source_map and anchor['in_frozen_catalog'] is False
        assert anchor['published_before_query'] is True and not any(anchor['seen_by_query'].values())
        check = next(e for e in external if e['doc_id'] == anchor['doc_id'])
        assert anchor['title'] == check['title'] and anchor['v1_date'] == check['v1_date']
        assert anchor['official_v1_url'] == check['url']
    profiles = load(ROOT/'profile-provenance.json')
    assert len(profiles) == 9 and all(r['hash_reproduction_passed'] for r in profiles)
    assert sum(bool(r['shown_history_ids']) for r in profiles) == 6
    runs = load('data/stage26-annotation/evaluator/runs.json')
    replay = load(ROOT/'retrieval-replay.json')
    assert replay['parameters_changed'] is False and replay['quality_metrics_computed'] is False
    decompositions = 0
    share = {}
    for q in replay['queries']:
        for method,response in q['methods'].items():
            assert [r['doc_id'] for r in response['papers']] == runs[method][q['query_id']]
        for row in q['mixed_score_decomposition']:
            assert np.isclose(row['score'],row['actual_query_contribution']+row['actual_history_contribution'],rtol=1e-9,atol=1e-12)
            decompositions += 1
        if q['intent']!='topic':
            share[q['query_id']] = float(np.mean([r['history_score_fraction'] for r in q['mixed_score_decomposition']]))
    assert len(replay['queries']) == 9 and decompositions == 90
    old = {}
    for stage, groups in {
        20:('code','vendor','outputs','private_data','docs','report'),
        23:('code','browser_assets','docs','outputs','report','private_validation'),
        24:('code','browser_assets','docs','report','outputs','private_validation'),
        26:('code','browser_assets','docs','report','outputs','private_pool','private_validation'),
        27:('code','docs','report','outputs','private_review'),
    }.items():old[str(stage)] = verify_receipt(Path(f'reports/stage{stage}/final-validation.json'),groups)
    previous = load('reports/stage25/validation.json')['assets']
    assert all(digest(Path(p)) == expected for p,expected in previous.items())
    before = load('data/stage27-model-review/formal-baseline.json')
    current = formal_state()
    assert current == {k:before[k] for k in current}
    versions = {d.metadata['Name']:d.version for d in metadata.distributions()}
    assert versions == load('reports/stage17/runtime-versions.json')['installed_versions']
    report = Path('reports/阶段28_目录覆盖与画像配对溯源.md')
    links = [v for v in re.findall(r'\]\(([^)]+)\)',report.read_text(encoding='utf-8')) if '://' not in v]
    for value in links:
        target = (report.parent/value).resolve()
        assert target.exists() or target == receipt.resolve(), value
    code = ['scripts/audit_topic_coverage.py','scripts/replay_topic_diagnostic.py','scripts/verify_topic_diagnostic.py']
    for name in code:compile(Path(name).read_text(encoding='utf-8'),name,'exec')
    save(REPORT/'diagnostic-validation.json',{'status':'passed','screened_abstracts':91,'new_abstract_notes':61,
        'hash_reproduced_profile_assignments':9,'native_top10_replays_matching':27,
        'score_decompositions_verified':90,'top10_mean_history_score_share':share,
        'anchors_absent':6,'old_assets_unchanged':old,'stage25_assets_unchanged':len(previous),
        'formal_state':current,'unchanged_cpu_packages':len(versions),'local_report_links':len(links),
        'human_quality_metrics_computed':False,'new_catalog_or_profiles_created':False})
    save(receipt,{'status':'complete_offline_coverage_and_profile_diagnostic',
        'code':{name:digest(Path(name)) for name in code},'report':{str(report):digest(report)},
        'outputs':{str(p):digest(p) for p in REPORT.glob('*.json') if p!=receipt},
        'private_diagnostic':{str(p):digest(p) for p in ROOT.iterdir() if p.is_file()},
        'no_human_labels_created':True,'no_algorithm_selection':True,'original_catalog_unchanged':True,
        'mutable_stores_excluded':True})
    print(json.dumps({'status':'sealed','assets':verify_receipt(receipt,GROUPS),
        'replays':27,'decompositions':90,'receipt_sha256':digest(receipt)},ensure_ascii=False))


if __name__ == '__main__':main()
