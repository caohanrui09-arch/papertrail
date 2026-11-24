"""SSE framing on the installed Starlette StreamingResponse and a single-writer log."""
import asyncio
import json
from pathlib import Path
import time


def available(path: Path, offset: int = 0):
    """Read only complete newline-terminated records, never a partial UTF-8 write."""
    rows=[]
    if not path.exists():return rows,offset
    with path.open('rb') as handle:
        handle.seek(offset)
        while True:
            line=handle.readline()
            if not line or not line.endswith(b'\n'):break
            row=json.loads(line)
            if not isinstance(row.get('id'),int) or row['id']<1:
                raise ValueError('Invalid event identity')
            rows.append(row)
            offset=handle.tell()
    return rows,offset


def frame(kind: str, payload: dict, ident: int | None = None):
    prefix=f'id: {ident}\n' if ident is not None else ''
    return prefix+f'event: {kind}\ndata: '+json.dumps(payload,ensure_ascii=False)+'\n\n'


async def stream(path: Path, after: int, process, snapshot):
    offset=0;seen=0;cursor=after;heartbeat=time.monotonic()
    yield 'retry: 1000\n\n'
    while True:
        rows,offset=available(path,offset)
        for row in rows:
            if row['id']!=seen+1:
                yield frame('stream_error',{'error':'Event log sequence is not contiguous'})
                return
            seen=row['id']
            if row['id']>cursor:
                cursor=row['id']
                yield frame('record',row,row['id'])
        if process.poll() is not None:
            # Drain once more after process exit, since final writes may follow the prior read.
            rows,offset=available(path,offset)
            for row in rows:
                if row['id']!=seen+1:
                    yield frame('stream_error',{'error':'Event log sequence is not contiguous'})
                    return
                seen=row['id']
                if row['id']>cursor:
                    cursor=row['id']
                    yield frame('record',row,row['id'])
            state=snapshot()
            yield frame('job_state',{'status':state['status'],'exit_code':state['exit_code'],
                'last_event_id':seen,'observability_errors':(state.get('result') or {}).get('observability_errors',0)})
            return
        if time.monotonic()-heartbeat>10:
            yield ': keep-alive\n\n'
            heartbeat=time.monotonic()
        await asyncio.sleep(.1)
