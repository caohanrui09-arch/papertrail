"""Independent source reconstruction of every history, profile and heldout label."""
from bisect import bisect_left
from collections import Counter,defaultdict
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from gsearch.quality_protocol import digest,save
from gsearch.supervision import frame,json_rows

ROOT=Path('reports/stage44')
DATA=Path('data/stage44-supervision')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main() -> None:
    checks=[]
    def check(name: str, ok: bool) -> None:
        if not ok:raise AssertionError(name)
        checks.append(name)
    protocol=load(ROOT/'protocol.json');receipt=load(DATA/'build-receipt.json')
    check('protocol_unchanged',receipt['protocol_sha256']==digest(ROOT/'protocol.json'))
    check('addendum_refers_to_protocol',load(ROOT/'evaluation-addendum.json')['protocol_sha256']==digest(ROOT/'protocol.json'))
    for name,expected in receipt['files'].items():check('artifact:'+name,digest(Path(name))==expected)
    for name,expected in receipt['code'].items():check('build_code:'+name,digest(Path(name))==expected)
    for name,info in protocol['inputs'].items():check('source:'+name,digest(Path(info['path']))==info['sha256'])
    catalog={r['doc_id']:r for r in load(DATA/'catalog.json')}
    check('training_time_catalog',len(catalog)==9000 and all(pd.Timestamp(r['available_at'])<pd.Timestamp(protocol['cutoffs']['train_exclusive']) for r in catalog.values()))
    check('v1_identity',all(r['version']==1 and r['version_key']=='arxiv:'+d+'v1' and r['source_url']=='https://arxiv.org/abs/'+d+'v1' for d,r in catalog.items()))
    profiles={p['user_key']:p for p in json_rows(DATA/'profiles.jsonl')}
    info=protocol['inputs']['train'];source=frame(Path(info['path']),'train',info['sha256'])
    candidate=source[source.doc_id.isin(catalog)].copy()
    avail={d:pd.Timestamp(r['available_at']).value for d,r in catalog.items()}
    positive=candidate[(candidate.rating==1)&(candidate['at'].map(lambda t:t.value)>=candidate.doc_id.map(avail))]
    seq=defaultdict(list)
    target={}
    for row in positive.itertuples(index=False):
        record=(row.at.value,row.doc_id,row.event_id,row.at.isoformat(),int(row.source_row))
        seq[row.user_key].append(record)
        target[row.event_id]=(row.user_key,record)
    for values in seq.values():values.sort(key=lambda x:(x[0],x[1]))
    expected_samples={r[2] for values in seq.values() for r in values if r[0]>values[0][0]}
    observed=set()
    for sample in json_rows(DATA/'train.next_item.jsonl'):
        ident=sample['sample_id']
        if ident in observed or ident not in expected_samples:raise AssertionError('duplicate/unexpected supervised target')
        observed.add(ident)
        key,record=target[ident]
        values=seq[key]
        n=bisect_left([v[0] for v in values],record[0])
        expected=values[max(0,n-20):n]
        if not (sample['user_key']==key and sample['target_doc_id']==record[1]
                and sample['target_version_key']==catalog[record[1]]['version_key']
                and sample['source_row']==record[4] and sample['target_at']==record[3]
                and sample['history_doc_ids']==[r[1] for r in expected]
                and sample['history_ats']==[r[3] for r in expected]
                and sample['history_event_ids']==[r[2] for r in expected]
                and sample['target_doc_id'] not in sample['history_doc_ids']):
            raise AssertionError('Supervision/history does not match strict source prefix: '+ident)
    check('every_train_prefix_reconstructed',observed==expected_samples)
    source_counts=source.groupby('user_key').size().to_dict()
    source_seen=candidate.groupby('user_key').doc_id.agg(set).to_dict()
    check('train_profiles_cover_exact_source_users',set(profiles)==set(source_counts))
    for key,profile in profiles.items():
        values=seq.get(key,[]);last=values[-20:]
        if not (profile['history_doc_ids']==[r[1] for r in last] and profile['history_ats']==[r[3] for r in last]
                and profile['history_event_ids']==[r[2] for r in last]
                and profile['eligible_train_positive_count']==len(values)
                and set(profile['seen_doc_ids'])==source_seen.get(key,set())
                and profile['source_train_events']==source_counts[key]):
            raise AssertionError('Frozen profile does not match training only: '+key)
    check('all_train_profiles_reconstructed',True)
    expected_feedback={r.event_id:(r.user_key,r.doc_id,int(r.rating),r.at.isoformat(),int(r.source_row),avail[r.doc_id]<=r.at.value) for r in candidate.itertuples(index=False)}
    feedback_count=0
    for r in json_rows(DATA/'train.feedback.jsonl'):
        got=(r['user_key'],r['doc_id'],r['rating'],r['at'],r['source_row'],r['available_at_event'])
        if r['event_id'] not in expected_feedback or got!=expected_feedback.pop(r['event_id']):
            raise AssertionError('Train feedback mismatch')
        feedback_count+=1
    check('all_candidate_feedback_reconstructed',not expected_feedback)
    train_counts=Counter(source.loc[source.rating==1,'doc_id'])
    del source,candidate,positive
    heldout={}
    coverage=load(ROOT/'coverage.json')
    for split,out in [('tuning','tuning'),('dev','dev_descriptive')]:
        info=protocol['inputs'][split]
        src=frame(Path(info['path']),split,info['sha256'])
        pos=src[src.rating==1]
        expected={r.event_id:r for r in pos.itertuples(index=False)}
        labels={r['qid']:r for r in json_rows(DATA/(out+'.labels.jsonl'))}
        inputs=list(json_rows(DATA/(out+'.inputs.jsonl')))
        check(out+':complete_positive_denominator',len(labels)==len(pos) and set(labels)==set(expected))
        check(out+':inputs_complete_and_unlabeled',len(inputs)==len(expected) and len({r['qid'] for r in inputs})==len(expected) and all(set(r)=={'qid','user_key','profile_key','at'} for r in inputs))
        for row in inputs:
            raw=expected[row['qid']]
            if row['user_key']!=raw.user_key or row['profile_key']!=raw.user_key or row['at']!=raw.at.isoformat():
                raise AssertionError('Input/source mismatch')
        reasons,source_groups=Counter(),Counter()
        for qid,label in labels.items():
            row=expected[qid]
            profile=profiles.get(row.user_key,{'history_doc_ids':[],'seen_doc_ids':[],'eligible_train_positive_count':0})
            reason='outside_frozen_catalog' if row.doc_id not in catalog else 'not_yet_available' if avail[row.doc_id]>row.at.value else 'masked_train_seen' if row.doc_id in profile['seen_doc_ids'] else None
            group='cold' if profile['eligible_train_positive_count']==0 else 'sparse' if profile['eligible_train_positive_count']<5 else 'warm'
            if not (label['user_key']==row.user_key and label['target_doc_id']==row.doc_id and label['at']==row.at.isoformat()
                    and label['source_row']==row.source_row and label['miss_reason']==reason and label['rankable']==(reason is None)
                    and label['target_train_positive_count']==train_counts[row.doc_id] and label['user_group']==group):
                raise AssertionError('Evaluation/source mismatch')
            reasons[reason or 'rankable']+=1
            source_groups['new_source_user' if row.user_key not in profiles else 'existing_no_catalog_context' if group=='cold' else 'existing_catalog_context']+=1
        check(out+':coverage_recount',dict(reasons)==coverage['heldout'][out]['target_reasons'])
        heldout[out]={'positive_events':len(pos),'all_inputs_without_targets':True,'source_user_event_groups':dict(source_groups)}
    test=subprocess.run([sys.executable,'-E','-s','-m','unittest','discover','-s','tests','-p','test_supervision.py','-v'],capture_output=True,text=True)
    (ROOT/'tests.log').write_text(test.stdout+test.stderr,encoding='utf-8')
    check('synthetic_boundary_and_scorer_tests',test.returncode==0 and 'Ran 20 tests' in test.stderr)
    save(ROOT/'validation.json',{'status':'passed','checks':checks,'check_count':len(checks),
        'train_samples_reconstructed':len(observed),'profiles_reconstructed':len(profiles),'candidate_feedback_reconstructed':feedback_count,
        'heldout_reconstructed':heldout,'synthetic_tests':20,'model_training_started':False,'real_quality_predictions_evaluated':False})
    print({'status':'passed','checks':len(checks),'training_samples':len(observed),'profiles':len(profiles),'heldout':heldout})


if __name__=='__main__':
    main()
