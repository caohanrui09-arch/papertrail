"""Full-label diagnostic joins after source-only acquisition and fixed sampling rules."""
import argparse
from collections import Counter,defaultdict
from datetime import timezone
import heapq
import json
from pathlib import Path

import pandas as pd

from gsearch.catalog_audit import CACHE,DATA,REPORT,SOURCE,LIGHT,SAMPLE_GROUPS,SAMPLE_N,SEED,arrow,digest,read,reason,sample_key,sample_stratum,stamp

ORIGINAL=Path('data/stage9-recommendation')
STRATA=('old_trainliked_text_pre_cutoff','old_no_trainlike_text_pre_cutoff','old_updated_after_cutoff','new_between_cutoff_and_log_end')

def save(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=lambda v:v.isoformat()),encoding='utf-8')

def freeze() -> None:
    path=REPORT/'plan.json'
    if path.exists():
        raise ValueError('Audit protocol exists; do not overwrite')
    cutoff=read(ORIGINAL/'audit.json')['cutoffs']['train_exclusive']
    times=pd.read_csv(ORIGINAL/'dev.csv',usecols=['time'])['time']
    end=pd.to_datetime(times,format='mixed',utc=True).max().isoformat()
    plan={'source_sha256':digest(SOURCE),'layout_sha256':digest(CACHE/'layout.json'),
          'feedback':{s:digest(ORIGINAL/(s+'.csv')) for s in ('train','tuning','dev')},
          'cutoff':cutoff,'log_end':end,'sample_groups':list(SAMPLE_GROUPS),'sample_n_per_stratum':SAMPLE_N,'seed':SEED,
          'sampler':'Within four source row groups, six smallest SHA256(seed:paper_id) per fixed date/train-like stratum; no future ratings used',
          'scope':'All source IDs and lightweight dates scanned independently of future labels; future feedback joined only for diagnostic attribution',
          'time_caveat':'naive source dates and source feedback timezone unspecified; normalized UTC for bookkeeping, not proven public announcement or historical ingestion time',
          'cold_item':'no train positive anywhere; additionally report no train feedback versus negative-only',
          'cold_user':'report both no global train positive and no current1781-catalog train positive, plus no training feedback',
          'unchanged_dev':'already used; no new model/ranking selection in this audit',
          'future_contrast':'same as-of source/version eligibility and train history for every method; outside-catalog positives retained',
          'source_code':{str(p):digest(p) for p in (Path('gsearch/catalog_audit.py'),Path('scripts/read_catalog_audit.py'),Path(__file__))}}
    save(path,plan)
    print(json.dumps({'frozen':True,'end':end,'cutoff':cutoff}),flush=True)

def build() -> None:
    if (REPORT/'coverage-aggregate.json').exists():
        raise ValueError('Refuse to overwrite completed audit')
    plan=read(REPORT/'plan.json')
    if plan['source_sha256']!=digest(SOURCE) or any(digest(ORIGINAL/(s+'.csv'))!=v for s,v in plan['feedback'].items()):
        raise ValueError('Fixed source or feedback changed')
    cutoff,end=stamp(plan['cutoff']),stamp(plan['log_end'])
    train=pd.read_csv(ORIGINAL/'train.csv',dtype={'user_id':str,'arxiv_id':str})
    likes=set(train.loc[train.rating==1,'arxiv_id'])
    all_items=set(train.arxiv_id)
    all_users=set(train.user_id)
    liked_users=set(train.loc[train.rating==1,'user_id'])
    catalog=set(read(Path('data/stage11-content/catalog.json')))
    original_catalog=set(read(ORIGINAL/'catalog.json'))
    catalog_users=set(train.loc[(train.rating==1)&train.arxiv_id.isin(catalog),'user_id'])
    futures={s:pd.read_csv(ORIGINAL/(s+'.csv'),dtype={'user_id':str,'arxiv_id':str}) for s in ('tuning','dev')}
    feedback_ids=set(train.arxiv_id)
    for f in futures.values():
        feedback_ids.update(f.arxiv_id)
    arrow()
    import pyarrow.parquet as pq
    layout=read(CACHE/'layout.json')
    metadata={}
    samples={s:[] for s in STRATA}
    sample_populations=Counter()
    expansion=Counter()
    parts={}
    snapshots={name:stamp(t) for name,t in [('train_cutoff',plan['cutoff']),('tuning_end',read(ORIGINAL/'audit.json')['cutoffs']['tuning_exclusive']),('log_end',plan['log_end'])]}
    source_rows=0
    for group in layout['groups']:
        i=group['index']
        path=CACHE/'light'/f'group-{i:05d}.parquet'
        receipt=read(path.with_suffix('.json'))
        if receipt['sha256']!=digest(path) or receipt['source_revision']!='cee894837962fede5612cccf2a4c7cacf49b4c3a':
            raise ValueError('Source part changed')
        parts[path.name]=digest(path)
        table=pq.read_table(path)
        for row in table.to_pylist():
            source_rows+=1
            doc=row['paper_id']
            first,latest=stamp(row['first_version_date']),stamp(row['latest_version_date'])
            if doc in feedback_ids:
                if doc in metadata:
                    raise ValueError('Duplicate source ID')
                metadata[doc]=row
            if first is None:
                expansion['missing_first_date']+=1
                continue
            if latest is not None and latest<first:
                expansion['latest_before_first']+=1
            for name,t in snapshots.items():
                if first<t:
                    expansion[name+'_first_date_only']+=1
                    if latest is not None and first<=latest<t:
                        expansion[name+'_latest_text_date_proxy']+=1
            if first<cutoff:
                kind='trainliked' if doc in likes else 'no_trainlike'
                expansion['old_'+kind]+=1
                if latest is not None and first<=latest<cutoff:
                    expansion['old_'+kind+'_latest_pre_cutoff']+=1
                elif latest is not None and latest>=cutoff:
                    expansion['old_'+kind+'_updated_after_cutoff']+=1
            elif first<=end:
                expansion['new_during_logged_window']+=1
                if latest is not None and first<=latest<=end:
                    expansion['new_latest_pre_log_end']+=1
            if i in SAMPLE_GROUPS:
                stratum=sample_stratum(row,cutoff,end,likes)
                if stratum:
                    sample_populations[stratum]+=1
                    candidate={**row,'row_group':i,'stratum':stratum,'selection_sha256':sample_key(doc)}
                    sample=samples[stratum]
                    sample.append(candidate)
                    sample.sort(key=lambda r:r['selection_sha256'])
                    del sample[SAMPLE_N:]
        print(json.dumps({'source_groups_done':i+1,'source_rows':source_rows,'joined_feedback_papers':len(metadata)}),flush=True)
    if source_rows!=layout['rows'] or any(len(samples[s])!=SAMPLE_N for s in STRATA):
        raise ValueError('Source scan or fixed sample incomplete')
    save(DATA/'feedback-paper-dates.json',list(metadata.values()))
    save(DATA/'sample-plan.json',{'plan_sha256':digest(REPORT/'plan.json'),'future_labels_used':False,
         'sampling_note':'bounded four source groups, purposive strata; not a probability sample of all arXiv',
         'stratum_population_in_four_groups':dict(sample_populations),'samples':[r for s in STRATA for r in samples[s]]})
    summary={}
    for split,frame in futures.items():
        positives=frame[frame.rating==1].copy()
        user_ids=set(positives.user_id)
        counts=Counter()
        distinct=defaultdict(set)
        cross=Counter()
        version_flags=Counter()
        output=[]
        for row in positives.itertuples(index=False):
            doc,user=row.arxiv_id,row.user_id
            meta=metadata.get(doc)
            event=stamp(row.time)
            cause=reason(doc,meta,event,cutoff,likes,catalog,original_catalog)
            item_cold=doc not in likes
            user_cold=user not in catalog_users
            counts[cause]+=1
            distinct[cause].add(doc)
            cross[('cold_user' if user_cold else 'warm_user')+'__'+('cold_item' if item_cold else 'warm_item')]+=1
            latest=stamp(meta.get('latest_version_date')) if meta else None
            first=stamp(meta.get('first_version_date')) if meta else None
            if latest is None:
                flag='latest_date_unknown'
            elif latest>event:
                flag='snapshot_latest_after_feedback'
            else:
                flag='snapshot_latest_not_after_feedback_proxy_only'
            version_flags[flag]+=1
            output.append({'user_id':user,'arxiv_id':doc,'time':row.time,'reason':cause,
                 'cold_user_current_catalog':user_cold,'cold_user_global_likes':user not in liked_users,
                 'cold_item_no_trainlike':item_cold,'cold_item_no_train_feedback':doc not in all_items,
                 'source_first_version_date':first,'source_latest_version_date':latest,'text_time_flag':flag})
        save(DATA/(split+'-attribution.json'),output)
        def users(group: set[str]) -> int:
            return len(user_ids-group)
        summary[split]={'likes':len(positives),'unique_liked_papers':positives.arxiv_id.nunique(),'users_with_future_likes':len(user_ids),
             'causes':{k:{'like_events':v,'event_fraction':v/len(positives),'unique_papers':len(distinct[k])} for k,v in counts.items()},
             'users':{'cold_no_current_catalog_like':users(catalog_users),'warm_current_catalog_like':len(user_ids&catalog_users),
                      'cold_no_global_train_like':users(liked_users),'no_train_feedback':users(all_users)},
             'items':{'cold_like_events_no_trainlike':sum(positives.arxiv_id.map(lambda d:d not in likes)),
                      'cold_like_events_no_train_feedback':sum(positives.arxiv_id.map(lambda d:d not in all_items)),
                      'cold_unique_no_trainlike':len(set(positives.arxiv_id)-likes)},
             'event_cross_user_item_cold':dict(cross),'snapshot_text_time_flags':dict(version_flags),
             'snapshot_metadata_matching_unique_papers':len(set(positives.arxiv_id)&metadata.keys())}
        if sum(counts.values())!=len(positives) or sum(cross.values())!=len(positives):
            raise ValueError('Diagnostic partition incomplete')
    save(REPORT/'coverage-aggregate.json',{'plan_sha256':digest(REPORT/'plan.json'),'source_rows':source_rows,
        'train_positive_items':len(likes),'train_all_rated_items':len(all_items),'train_like_users':len(liked_users),
        'current_catalog_like_users':len(catalog_users),'expansion_date_counts':dict(expansion),'splits':summary,
        'source_parts_sha256':parts,'sample_plan_sha256':digest(DATA/'sample-plan.json'),
        'note':'future labels diagnostic only; no expanded production catalog selected; date counts do not prove historical text availability'})
    print(json.dumps({'splits':summary,'expansion_date_counts':dict(expansion)}),flush=True)

def main() -> None:
    p=argparse.ArgumentParser()
    p.add_argument('--phase',choices=('freeze','build'),required=True)
    args=p.parse_args()
    (freeze if args.phase=='freeze' else build)()

if __name__=='__main__':
    main()
