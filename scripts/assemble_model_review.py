"""Validate and package assistant judgments without writing human annotation stores."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3

from gsearch.quality_protocol import csv_text, digest, save, write_csv
from gsearch.showcase import verify_receipt

ROOT = Path('data/stage27-model-review')
REPORTS = Path('reports/stage27')
LIMIT = '仅判断冻结v1原摘要；未核查全文。置信度是模型自评，未经校准。'


def load(path: Path) -> object:
    return json.loads(path.read_text(encoding='utf-8'))


def formal_state() -> dict:
    path = Path('data/stage26-annotation/work/annotations.sqlite3').resolve()
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as db:
        records = db.execute("SELECT * FROM annotation_records WHERE owner NOT LIKE 'verification:%' ORDER BY owner,pool,qid,kind,item").fetchall()
        audit = db.execute("SELECT * FROM annotation_audit WHERE owner NOT LIKE 'verification:%' ORDER BY event").fetchall()
    raw = json.dumps([records, audit], ensure_ascii=False).encode()
    return {'formal_records': len(records), 'formal_audit_events': len(audit),
            'logical_sha256': hashlib.sha256(raw).hexdigest()}


def main() -> None:
    receipt = REPORTS/'final-validation.json'
    if receipt.exists() or (ROOT/'judgments-model.json').exists():
        raise ValueError('Preserve the existing review; use a new version')
    manifest = load(ROOT/'input-manifest.json')
    for name, expected in manifest['files'].items():
        assert digest(ROOT/name) == expected, name
    assert digest(Path('data/stage26-annotation/blind/tasks.json')) == manifest['source_sha256']
    tasks = load(ROOT/'blind-input.json')
    papers = {x['paper']['doc_id']: x for x in load(ROOT/'paper-reader.json')}
    forbidden = {'method', 'rank', 'score', 'user_id'}
    def check_projection(value: object) -> None:
        if isinstance(value, dict):
            assert not forbidden.intersection(value), 'Unblinded metadata'
            for item in value.values(): check_projection(item)
        elif isinstance(value, list):
            for item in value: check_projection(item)
    check_projection(tasks)
    decisions = {}
    note_paths = sorted(ROOT.glob('decisions-*.json'))
    for path in note_paths:
        for entry in load(path):
            doc = entry['doc_id']
            assert doc in papers and doc not in decisions, doc
            assert set(entry.get('query_overrides', {})) <= set(papers[doc]['queries']), doc
            decisions[doc] = entry
    assert decisions.keys() == papers.keys() and len(papers) == 101
    context_notes = {x['doc_id']: x['observation'] for x in load(ROOT/'context-notes.json')}
    contexts = {p['doc_id']: p for task in tasks.values() for p in task['context']}
    assert context_notes.keys() == contexts.keys() and len(contexts) == 15
    rows, query_suggestions, context_audit = [], [], []
    for doc, paper in contexts.items():
        context_audit.append({'doc_id': doc, 'version_key': paper['version_key'],
            'abstract_sha256': hashlib.sha256(paper['abstract'].encode()).hexdigest(),
            'source_url': paper['source_url'], 'observation': context_notes[doc],
            'query_ids': [q for q, t in tasks.items() if any(p['doc_id'] == doc for p in t['context'])]})
    for qid, task in tasks.items():
        query = task['query']
        query_suggestions.append({'query_id': qid, 'query_hash': query['query_hash'],
            'origin': 'model_blind_review', 'human': False,
            'suggestion': 'clarify_context' if task['context'] else 'usable_as_draft',
            'note': ('核心主题可读，但5篇预设阅读历史与该主题不一致；需说明这是有意跨主题需求还是更换画像后另建池。'
                     if task['context'] else '核心要求和偏好可区分；仍是助手拟定需求，不能代替真人意图确认。')})
        for candidate in task['candidates']:
            paper = candidate['paper']; doc = paper['doc_id']
            assert paper == papers[doc]['paper'] and qid in papers[doc]['queries']
            base = decisions[doc]
            decision = base | base.get('query_overrides', {}).get(qid, {})
            grade = decision['grade']; evidence = decision['evidence']
            assert grade is None or (type(grade) is int and grade in (0, 1, 2)), doc
            assert decision['confidence'] in ('high', 'medium', 'low'), doc
            assert evidence and evidence in paper['abstract'] and len(evidence.split()) <= 25, (doc, evidence)
            assert decision['rationale'].strip(), doc
            assert paper['source_verified'] is True, doc
            rows.append({'annotation_id': candidate['annotation_id'], 'query_id': qid,
                'query_hash': query['query_hash'], 'doc_id': doc, 'version_key': paper['version_key'],
                'title': paper['title'], 'source_url': paper['source_url'], 'grade': grade,
                'rationale': decision['rationale'], 'evidence': evidence,
                'confidence': decision['confidence'], 'limitations': LIMIT,
                'abstract_sha256': hashlib.sha256(paper['abstract'].encode()).hexdigest(),
                'judgment_origin': 'model_blind_review', 'human': False, 'independent': False,
                'model': manifest['model'], 'review_date': '2026-10-29', 'pool_version': manifest['pool_version']})
    assert len(rows) == 155 and len({r['annotation_id'] for r in rows}) == 155
    expected = {(q, c['annotation_id']) for q, t in tasks.items() for c in t['candidates']}
    assert expected == {(r['query_id'], r['annotation_id']) for r in rows}
    before = load(ROOT/'formal-baseline.json')
    current = formal_state()
    assert current == {k: before[k] for k in current}, 'Formal annotations changed'
    old = {}
    for stage, groups in {
        20: ('code', 'vendor', 'outputs', 'private_data', 'docs', 'report'),
        23: ('code', 'browser_assets', 'docs', 'outputs', 'report', 'private_validation'),
        24: ('code', 'browser_assets', 'docs', 'report', 'outputs', 'private_validation'),
        26: ('code', 'browser_assets', 'docs', 'report', 'outputs', 'private_pool', 'private_validation')
    }.items():
        # Hash-only integrity checks; evaluator per-candidate contents are never parsed.
        old[str(stage)] = verify_receipt(Path(f'reports/stage{stage}/final-validation.json'), groups)
    previous = load(Path('reports/stage25/validation.json'))
    assert all(digest(Path(p)) == expected for p, expected in previous['assets'].items())
    def counts(items: list[dict]) -> dict:
        counter = Counter('unknown' if r['grade'] is None else str(r['grade']) for r in items)
        return {key: counter[key] for key in ('2', '1', '0', 'unknown')}
    summary = {'origin': 'model_blind_review', 'human': False, 'independent': False,
        'queries': len(tasks), 'pairs_reviewed': len(rows), 'unique_candidates_read': len(papers),
        'context_papers_read': len(contexts), 'counts': counts(rows),
        'per_query': {q: counts([r for r in rows if r['query_id'] == q]) for q in tasks},
        'confidence': dict(Counter(r['confidence'] for r in rows)),
        'query_suggestions': query_suggestions, 'formal_state': current,
        'quality_metrics_computed': False, 'algorithm_selection_performed': False,
        'methods_ranks_scores_parsed': False, 'old_assets_unchanged': old,
        'stage25_assets_unchanged': len(previous['assets'])}
    save(ROOT/'judgments-model.json', {'provenance': manifest, 'judgments': rows})
    save(ROOT/'context-audit.json', context_audit)
    save(ROOT/'query-suggestions-model.json', query_suggestions)
    save(REPORTS/'review-summary.json', summary)
    fields = ['query_id','annotation_id','doc_id','version_key','title','grade','rationale','evidence',
              'confidence','source_url','judgment_origin','human','limitations']
    write_csv(ROOT/'judgments-model.csv', fields,
        [{k: csv_text('' if r[k] is None else r[k]) for k in fields} for r in rows])
    lines = ['# 模型辅助盲审逐项结果', '',
        '仅对冻结v1摘要判断；已隐藏逐候选方法、排名和分数。当前助手参与系统设计，非独立真人评价。',
        '等级：2高度相关，1部分相关，0明确不符，空白无法可靠判断。模型置信度未经校准。', '']
    for qid, task in tasks.items():
        lines += [f'## {qid}：{task["query"]["required_focus_zh"]}', '', task['query']['request_zh'], '',
                  next(s['note'] for s in query_suggestions if s['query_id'] == qid), '']
        for r in [r for r in rows if r['query_id'] == qid]:
            label = '无法判断' if r['grade'] is None else str(r['grade'])
            lines += [f'### {r["doc_id"]} · 等级{label} · {r["confidence"]}', '',
                f'[{r["title"]}]({r["source_url"]})；{r["version_key"]}；{r["annotation_id"]}', '',
                r['rationale'], '', f'摘要证据：{r["evidence"]}', '']
    (ROOT/'模型盲审逐项结果.md').write_text('\n'.join(lines), encoding='utf-8')
    assert formal_state() == current
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
