"""Native budget and event framing checks, no model run or synthetic rankings."""
import json
from pathlib import Path
import time
import urllib.request
from research70.observability import EventJournal,ObservedClient
from research70.event_stream import available,frame

ROOT=Path(__file__).resolve().parents[1]


def main():
    base=ROOT/'data/stage70-instrumentation';base.mkdir(exist_ok=False)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(120):
        try:
            with opener.open('http://127.0.0.1:8802/health',timeout=2) as response:
                if json.load(response)['status']=='ready':break
        except OSError:pass
        time.sleep(.5)
    else:raise RuntimeError('Lab not ready')
    task=json.loads((ROOT/'data/stage19-unified/benchmark/evaluation-tasks.json').read_text())[0]
    journal=EventJournal(base/'events.jsonl');journal.context_for(task['id'],'instrumentation_budget',0)
    client=ObservedClient(task,8802,observer=journal)
    errors=[]
    for _ in range(7):
        try:client.call('read_paper',doc_id='not-returned')
        except ValueError as error:errors.append(str(error))
    snapshot=client.snapshot();client.close();journal.handle.close()
    rows,_=available(base/'events.jsonl')
    tools=[e['payload'] for e in rows if e['kind']=='tool_returned']
    assert tools==snapshot['trace']
    assert snapshot['attempts']==len(tools)==6 and len(errors)==7
    assert sum(e['kind']=='tool_rejected' for e in rows)==1
    assert [e['id'] for e in rows]==list(range(1,len(rows)+1))
    partial=base/'partial.jsonl';record=(json.dumps({'id':1,'value':'原文'},ensure_ascii=False)+'\n').encode()
    partial.write_bytes(record[:-4]);assert available(partial)==([],0)
    with partial.open('ab') as handle:handle.write(record[-4:])
    assert available(partial)[0]==[{'id':1,'value':'原文'}]
    packet=frame('record',{'text':'a\nb\nevent: false'},1)
    assert packet.count('\ndata: ')==1 and packet.count('\nevent: ')==1
    result={'status':'passed','native_attempts':6,'gateway_rejection_separate':1,'tool_entries_exact':True,
            'contiguous_event_ids':True,'partial_utf8_line_not_delivered':True,'sse_payload_newlines_escaped':True,'journal_errors':journal.errors}
    (ROOT/'reports/stage70/instrumentation-validation.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(result))


if __name__=='__main__':main()
