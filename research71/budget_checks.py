"""Exercise confirmed-query rejection and unchanged native billing in a separate session."""
import json
from pathlib import Path
from research70.observability import EventJournal
from research71.clients import ObservedCustomClient

ROOT=Path(__file__).resolve().parents[1]


def main():
    base=ROOT/'data/stage71-custom/budget-check';base.mkdir(exist_ok=False)
    task=json.loads((ROOT/'data/stage19-unified/benchmark/evaluation-tasks.json').read_text())[0]
    task={**task,'id':'custom-budget-fixture','task_kind':'custom','query':'confirmed-query'}
    log=EventJournal(base/'events.jsonl');log.context_for(task['id'],'fixture',0)
    client=ObservedCustomClient(task,8802,observer=log)
    try:
        try:client.call('search_papers',query='silently rewritten',k=3)
        except ValueError as error:assert 'confirmed' in str(error)
        else:raise AssertionError('Query rewriting should be rejected')
        assert client.snapshot()['attempts']==0
        try:client.call('search_papers',query='confirmed-query',k=None)
        except ValueError:pass
        else:raise AssertionError('null k should be rejected')
        for _ in range(5):
            try:client.call('read_paper',doc_id='not-returned')
            except ValueError:pass
            else:raise AssertionError('Unreturned paper should be rejected')
        try:client.call('read_paper',doc_id='not-returned')
        except ValueError as error:assert 'Six-attempt' in str(error)
        else:raise AssertionError('Seventh execution must be rejected')
        final=client.snapshot();assert final['attempts']==len(final['trace'])==6
        assert final['trace'][0]['arguments']['k'] is None
        rows=[json.loads(line) for line in log.path.read_text(encoding='utf8').splitlines()]
        assert [e['payload'] for e in rows if e['kind']=='tool_returned']==final['trace']
        assert sum(e['kind']=='tool_rejected' for e in rows)==2
        report={'status':'passed','query_rewrite_rejected_before_gateway':True,'null_k_rejected_and_billed_without_repair':True,
                'native_execution_budget':6,'seventh_attempt_rejected':True,'observation_trace_exact':True,'model_jobs_started':0}
        (ROOT/'reports/stage71/budget-validation.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report))
    finally:client.close();log.handle.close()


if __name__=='__main__':main()
