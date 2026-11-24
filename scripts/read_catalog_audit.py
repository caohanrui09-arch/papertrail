"""Reuse Arrow+HfFileSystem for fixed lightweight columns and four bounded text groups."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import json
from pathlib import Path
import time

from gsearch.catalog_audit import CACHE,DATA,REPORT,SOURCE,LIGHT,TEXT,SAMPLE_GROUPS,CountedFile,arrow,digest,read

def main() -> None:
    p=argparse.ArgumentParser()
    p.add_argument('--phase',choices=('layout','light','sample'),required=True)
    args=p.parse_args()
    arrow()
    import pyarrow.parquet as pq
    import pyarrow.compute as pc
    import pyarrow as pa
    from huggingface_hub import HfFileSystem
    source=read(SOURCE)
    expected='cee894837962fede5612cccf2a4c7cacf49b4c3a'
    if source['repo_revision']!=expected:
        raise ValueError('Source revision drift')
    path=source['path']
    fs=HfFileSystem(token=False)
    info=fs.info(path)
    if info['size']!=source['file_info']['size'] or info['lfs']['sha256']!=source['file_info']['lfs']['sha256']:
        raise ValueError('Source file identity drift')
    CACHE.mkdir(parents=True,exist_ok=True)
    if args.phase=='layout':
        if (CACHE/'layout.json').exists():
            print('Layout already cached; not overwritten',flush=True)
            return
        with fs.open(path,'rb',cache_type='none') as raw:
            count=CountedFile(raw)
            f=pq.ParquetFile(count,pre_buffer=False)
            groups=[]
            for i in range(f.num_row_groups):
                g=f.metadata.row_group(i)
                columns={g.column(j).path_in_schema:g.column(j).total_compressed_size for j in range(g.num_columns)}
                groups.append({'index':i,'rows':g.num_rows,'compressed_bytes':columns})
            layout={'revision':expected,'source_file_size':info['size'],'source_lfs_sha256':info['lfs']['sha256'],
                    'rows':f.metadata.num_rows,'schema':str(f.schema_arrow),'groups':groups,
                    'footer_returned_bytes':count.returned_bytes,'license':'CC0 descriptive metadata only'}
        (CACHE/'layout.json').write_text(json.dumps(layout,indent=2),encoding='utf-8')
        print(json.dumps({'groups':len(groups),'rows':layout['rows'],'light_compressed_bytes':sum(sum(g['compressed_bytes'][c] for c in LIGHT) for g in groups),
              'four_text_groups_compressed_bytes':sum(sum(g['compressed_bytes'][c] for c in TEXT) for g in groups if g['index'] in SAMPLE_GROUPS)}),flush=True)
        return
    plan=read(REPORT/'plan.json')
    if plan['source_sha256']!=digest(SOURCE) or plan['sample_groups']!=list(SAMPLE_GROUPS):
        raise ValueError('Acquisition plan drift')
    layout=read(CACHE/'layout.json')
    group_ids=list(range(len(layout['groups']))) if args.phase=='light' else list(SAMPLE_GROUPS)
    columns=list(LIGHT if args.phase=='light' else TEXT)
    wanted=None if args.phase=='light' else {r['paper_id'] for r in read(DATA/'sample-plan.json')['samples']}
    folder=CACHE/args.phase
    folder.mkdir(parents=True,exist_ok=True)
    start=time.perf_counter()
    def process(index: int) -> dict:
        dest=folder/f'group-{index:05d}.parquet'
        receipt=dest.with_suffix('.json')
        if receipt.exists():
            r=read(receipt)
            if digest(dest)!=r['sha256']:
                raise ValueError('Cached source part changed')
            return {'index':index,'cached':True,**r}
        t=time.perf_counter()
        with fs.open(path,'rb',cache_type='none') as raw:
            count=CountedFile(raw)
            file=pq.ParquetFile(count,pre_buffer=False)
            table=file.read_row_group(index,columns=columns,use_threads=False)
            if wanted is not None:
                table=table.filter(pc.is_in(table['paper_id'],value_set=pa.array(sorted(wanted))))
            payload=count.returned_bytes
            calls=count.read_calls
        pq.write_table(table,dest,compression='zstd')
        r={'rows':table.num_rows,'columns':columns,'source_revision':expected,'sha256':digest(dest),
           'seconds':time.perf_counter()-t,'arrow_returned_bytes':payload,'file_read_calls':calls,
           'retrieved_at':datetime.now(timezone.utc).isoformat(),'row_group':index,
           'note':'Counted file read bytes; excludes HTTP/TLS overhead and Hub metadata API. No fulltext.'}
        receipt.write_text(json.dumps(r,indent=2),encoding='utf-8')
        return {'index':index,'cached':False,**r}
    results=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks={pool.submit(process,i):i for i in group_ids}
        for task in as_completed(tasks):
            try:
                results.append(task.result())
                print(json.dumps({'phase':args.phase,'group':tasks[task],'done':len(results),'total':len(group_ids)}),flush=True)
            except Exception as exc:
                error={'phase':args.phase,'group':tasks[task],'error':type(exc).__name__+': '+str(exc),
                       'at':datetime.now(timezone.utc).isoformat()}
                (folder/f'error-{tasks[task]}-{time.time_ns()}.json').write_text(json.dumps(error,indent=2),encoding='utf-8')
                print(json.dumps(error),flush=True)
    complete=len(results)==len(group_ids)
    receipt={'phase':args.phase,'complete':complete,'parts':sorted(results,key=lambda r:r['index']),
             'wall_seconds_this_invocation':time.perf_counter()-start,'workers':4,
             'new_arrow_returned_bytes':sum(r['arrow_returned_bytes'] for r in results if not r['cached']),
             'new_file_read_calls':sum(r['file_read_calls'] for r in results if not r['cached'])}
    out=CACHE/(args.phase+'-run-'+str(time.time_ns())+'.json')
    out.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in receipt.items() if k!='parts'}),flush=True)
    if not complete:
        raise RuntimeError('Incomplete source scan; preserve parts and resume')

if __name__=='__main__':
    main()
