"""Local blind-annotation interchange and strict provenance/completeness gates."""
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path

JUDGMENT_FIELDS = ['annotation_id','grade','annotator_id','judgment_origin','judged_at','rationale']


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def csv_text(value: object) -> str:
    text = str(value)
    # Display-only escaping; source JSON and original abstract bytes stay intact.
    return "'"+text if text.lstrip().startswith(('=', '+', '-', '@')) else text


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError('Missing or duplicate CSV columns')
        rows = list(reader)
    if any(None in r for r in rows):
        raise ValueError('Unexpected extra CSV fields')
    return rows


def aware_timestamp(value: str) -> None:
    try:
        stamp = datetime.fromisoformat(value.replace('Z','+00:00'))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError('Explicit timezone-aware timestamp required') from error
    if stamp.tzinfo is None:
        raise ValueError('Timestamp must include timezone')


def judgments(rows: list[dict], mapping: dict) -> dict:
    labels, encountered = {}, set()
    for row in rows:
        if set(row) != set(JUDGMENT_FIELDS):
            raise ValueError('Use exactly the declared judgment columns')
        ident = row['annotation_id']
        if ident not in mapping or ident in encountered:
            raise ValueError('Unknown or duplicate annotation ID')
        encountered.add(ident)
        if row['grade'] == '':
            if any(row[k] for k in JUDGMENT_FIELDS[2:]):
                raise ValueError('Metadata without a grade is ambiguous; keep untouched rows empty')
            continue
        if type(row['grade']) is not str or row['grade'] not in ('0','1','2'):
            raise ValueError('Grade must be exactly 0,1,2 or blank; missing is never zero')
        if row['judgment_origin'] != 'human' or not row['annotator_id'].strip() or not row['rationale'].strip():
            raise ValueError('Explicit human origin, annotator alias and rationale required')
        aware_timestamp(row['judged_at'])
        labels[ident] = {**row, 'grade': int(row['grade'])}
    return labels


def confirmations(rows: list[dict], queries: list[dict]) -> set[str]:
    by_id = {q['query_id']: q for q in queries}
    seen, confirmed = set(), set()
    expected = {'query_id','request','query_origin','confirmed','reviewer_id','reviewed_at','note'}
    for row in rows:
        if set(row) != expected or row['query_id'] not in by_id or row['query_id'] in seen:
            raise ValueError('Invalid query-review schema or ID')
        seen.add(row['query_id'])
        query = by_id[row['query_id']]
        if row['request'] != query['request'] or row['query_origin'] != query['query_origin']:
            raise ValueError('Draft edited; build a new query/pool version instead of relabeling source')
        if row['confirmed'] == '':
            continue
        if row['confirmed'] not in ('yes','no') or not row['reviewer_id'].strip():
            raise ValueError('Use yes/no and a human reviewer alias')
        aware_timestamp(row['reviewed_at'])
        if row['confirmed'] == 'yes': confirmed.add(row['query_id'])
    return confirmed


def coverage(queries: list[dict], mapping: dict, runs: dict, labels: dict, confirmed: set[str]) -> dict:
    lookup = {(m['query_id'],m['doc_id']):ident for ident,m in mapping.items()}
    methods = {}
    for method, results in runs.items():
        returned = sum(len(ids) for ids in results.values())
        judged = sum(lookup[(qid, doc)] in labels for qid, ids in results.items() for doc in ids)
        methods[method] = {'returned': returned, 'judged_returned': judged,
            'judged_returned_ratio': judged/returned if returned else None,
            'returned_slots_ratio_at10': returned/(10*len(queries)) if queries else None}
    complete = len(labels) == len(mapping) and len(confirmed) == len(queries)
    return {'queries':len(queries),'query_confirmed':len(confirmed),'pooled_pairs':len(mapping),
        'human_judged_pairs':len(labels),'pooled_judged_ratio':len(labels)/len(mapping) if mapping else None,
        'methods':methods,'quality_ready':complete,
        'quality_status':'ready' if complete else 'awaiting_human_query_confirmation_and_judgments',
        'ndcg_at10':None,'mrr_at10':None,'full_catalog_recall':None}


def import_label_studio(tasks: list[dict], mapping: dict, annotator_id: str, attest_human: bool) -> list[dict]:
    if not attest_human or not annotator_id.strip():
        raise ValueError('Human provenance declaration required; no automatic conversion of predictions')
    rows, seen = [], set()
    choices = {'0 不相关':'0','1 部分相关':'1','2 高度相关':'2'}
    for task in tasks:
        ident = task.get('data',{}).get('annotation_id')
        if ident not in mapping or ident in seen:
            raise ValueError('Unknown or duplicate imported task')
        seen.add(ident)
        if task.get('predictions'):
            raise ValueError('Predictions are not accepted as human labels')
        annotations = task.get('annotations',[])
        if not annotations: continue
        if len(annotations) != 1 or annotations[0].get('was_cancelled'):
            raise ValueError('Cancelled/multiple annotations require explicit review/adjudication')
        annotation = annotations[0]
        grade, rationale = None, None
        for result in annotation.get('result',[]):
            if result.get('from_name') == 'relevance' and result.get('type') == 'choices':
                value = result.get('value',{}).get('choices',[])
                if grade is not None or len(value) != 1 or value[0] not in choices:
                    raise ValueError('Invalid or duplicate relevance choice')
                grade = choices[value[0]]
            elif result.get('from_name') == 'rationale' and result.get('type') == 'textarea':
                value = result.get('value',{}).get('text',[])
                if rationale is not None or not value or any(not isinstance(v,str) for v in value):
                    raise ValueError('Invalid rationale')
                rationale = '\n'.join(value)
        if grade is None or rationale is None:
            raise ValueError('Incomplete annotation; not converted to zero')
        rows.append({'annotation_id':ident,'grade':grade,'annotator_id':annotator_id,
            'judgment_origin':'human','judged_at':annotation.get('created_at',''),'rationale':rationale})
    judgments(rows, mapping)
    return rows
