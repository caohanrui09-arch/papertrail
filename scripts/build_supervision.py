"""Prepare local licensed supervision and complete heldout ledgers; fit no models."""
from collections import Counter
import json
from pathlib import Path
import time

import pandas as pd
import psutil

from gsearch.quality_protocol import save, digest
from gsearch.supervision import frame,build_train,evaluation_label,json_line

ROOT=Path('reports/stage44')
DATA=Path('data/stage44-supervision')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main() -> None:
    if (DATA/'build-receipt.json').exists() or (DATA/'train.next_item.jsonl').exists():
        raise FileExistsError('Do not overwrite prepared supervision; preserve failures in a new output version')
    start=time.perf_counter()
    protocol=load(ROOT/'protocol.json')
    catalog_path=Path(protocol['catalog']['path'])
    assert digest(catalog_path)==protocol['catalog']['sha256']
    source_path=Path(protocol['source_corpus']['path'])
    assert digest(source_path)==protocol['source_corpus']['sha256']
    all_meta={r['doc_id']:r for r in load(source_path)}
    catalog={r['doc_id']:r for r in load(catalog_path)}
    raw_files={}
    for row in catalog.values():
        p=Path(row['provenance']['raw_path'])
        raw_files[str(p)]=row['provenance']['raw_sha256']
    for name,expected in raw_files.items():
        assert digest(Path(name))==expected
    train_info=protocol['inputs']['train']
    train_path=Path(train_info['path'])
    assert digest(train_path)==train_info['sha256']
    train=frame(train_path,'train',train_info['sha256'])
    cutoff=pd.Timestamp(protocol['cutoffs']['train_exclusive'])
    assert train['at'].max()<cutoff
    with (DATA/'train.next_item.jsonl').open('x',encoding='utf-8') as samples,(DATA/'train.feedback.jsonl').open('x',encoding='utf-8') as feedback:
        profiles,train_counts,likes=build_train(train,catalog,protocol['history']['max_items'],samples,feedback)
    with (DATA/'profiles.jsonl').open('x',encoding='utf-8') as stream:
        for key in sorted(profiles):json_line(stream,profiles[key])
    train_data={'source_rows':len(train),'source_positive_events':int((train.rating==1).sum()),'users':len(profiles),
                'catalog':len(catalog),'counts':train_counts,'users_with_context':sum(p['eligible_train_positive_count']>0 for p in profiles.values()),
                'catalog_source_positive_counts':{d:int(likes[d]) for d in sorted(catalog)}}
    save(DATA/'training-stats.json',train_data)
    print({'train':train_counts,'profiles':len(profiles)},flush=True)
    del train
    heldout={}
    for source_split,output in [('tuning','tuning'),('dev','dev_descriptive')]:
        info=protocol['inputs'][source_split]
        assert digest(Path(info['path']))==info['sha256']
        data=frame(Path(info['path']),source_split,info['sha256'])
        boundary=pd.Timestamp(protocol['cutoffs']['tuning_exclusive'])
        assert data['at'].min()>=(cutoff if source_split=='tuning' else boundary)
        assert data['at'].max()<(boundary if source_split=='tuning' else pd.Timestamp(protocol['end_inclusive'])+pd.Timedelta(microseconds=1))
        positives=data[data.rating==1]
        reasons,ugroups,igroups=Counter(),Counter(),Counter()
        users=set()
        caps={}
        with (DATA/(output+'.inputs.jsonl')).open('x',encoding='utf-8') as inputs,(DATA/(output+'.labels.jsonl')).open('x',encoding='utf-8') as labels:
            for row in positives.itertuples(index=False):
                label=evaluation_label(row,profiles,catalog,all_meta,likes)
                json_line(inputs,{'qid':row.event_id,'user_key':row.user_key,'at':row.at.isoformat(),'profile_key':row.user_key})
                json_line(labels,label)
                reason=label['miss_reason'] or 'rankable'
                reasons[reason]+=1;ugroups[label['user_group']]+=1;igroups[label['item_group']]+=1
                users.add(row.user_key)
                if row.user_key not in caps:caps[row.user_key]=[0,0]
                caps[row.user_key][0]+=int(label['rankable']);caps[row.user_key][1]+=1
        heldout[output]={'source_rows':len(data),'positive_events_full_denominator':len(positives),'users':len(users),
            'target_reasons':dict(reasons),'user_event_groups':dict(ugroups),'item_event_groups':dict(igroups),
            'event_micro_rankable_ceiling':reasons['rankable']/len(positives),
            'user_macro_rankable_ceiling':sum(h/n for h,n in caps.values())/len(caps),
            'status':'previously_used_tuning' if source_split=='tuning' else 'previously_used_descriptive_dev_not_independent'}
        print({output:heldout[output]},flush=True)
    for path in DATA.glob('*.jsonl'):
        assert path.stat().st_size>0
    save(DATA/'build-receipt.json',{'protocol_sha256':digest(ROOT/'protocol.json'),
        'files':{str(p):digest(p) for p in DATA.iterdir() if p.is_file() and p.name!='build-receipt.json'},
        'inputs':protocol['inputs'],'raw_metadata_files':raw_files,'local_only':True,
        'code':{p:digest(Path(p)) for p in ['gsearch/supervision.py','scripts/build_supervision.py','scripts/prepare_supervision_protocol.py']}})
    save(ROOT/'coverage.json',{'scope':'data coverage and denominator audit only; no recommendation predictions or model fitting',
        'catalog':protocol['catalog'],'training':{k:v for k,v in train_data.items() if k!='catalog_source_positive_counts'},
        'heldout':heldout,'cost':{'wall_seconds':time.perf_counter()-start,'peak_working_set_bytes':psutil.Process().memory_info().peak_wset},
        'source_raw_metadata_files_verified':len(raw_files),'fresh_independent_period':False,
        'data_license':'CC BY-NC-ND4.0, transformed per-user data remains ignored local data/; no redistribution',
        'receipt_sha256':digest(DATA/'build-receipt.json'),'protocol_sha256':digest(ROOT/'protocol.json')})
    print({'finished':True,'seconds':time.perf_counter()-start,'receipt':digest(DATA/'build-receipt.json')})


if __name__=='__main__':
    main()
