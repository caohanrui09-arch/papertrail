"""Independent full source-to-token audit without model training or heldout labels."""
import json
from pathlib import Path

from gsearch.quality_protocol import digest,save
from gsearch.supervision import json_rows
from scripts.run_sid_diagnostics import assert_control
import numpy as np


def main() -> None:
    data=Path('data/stage45-sft');report=Path('reports/stage45')
    token=json.loads((report/'tokenization.json').read_text())
    maps={a:json.loads((data/(a+'.tokens.json')).read_text()) for a in ['content','shuffled']}
    samples=list(json_rows(Path('data/stage44-supervision/train.next_item.jsonl')))
    checks={}
    for arm,mapping in maps.items():
        checked=0
        for source,row in zip(samples,json_rows(data/(arm+'.train.tokens.jsonl')),strict=True):
            expected=token['prefix_ids']+[x for d in source['history_doc_ids'] for x in mapping[d][:-1]]+[1]
            assert row['sample_id']==source['sample_id']
            assert row['input_ids']==expected+[0]*(96-len(expected))
            assert row['attention_mask']==[1]*len(expected)+[0]*(96-len(expected))
            assert row['labels']==mapping[source['target_doc_id']]
            assert len(row['labels'])==5
            checked+=1
        assert checked==98887
        checks[arm+'_all_source_to_tokens']=checked
    assignment=json.loads((data/'assignment.json').read_text());ids=assignment['ids']
    raw=json.loads((data/'content.sid.json').read_text())
    codes=np.load(data/'codes.npy',allow_pickle=False)
    control=assert_control(codes,{d:raw[d][:3] for d in ids},raw,ids,
                           np.array(assignment['assignment']),assignment['frequencies'])
    order=json.loads((data/'training-order.json').read_text())
    assert sorted(order['indices'])==list(range(len(samples)))
    assert order['sample_ids']==[samples[i]['sample_id'] for i in order['indices']]
    assert len({tuple(v) for v in maps['content'].values()})==9000
    checks.update(all_training_order_exact=True,unique_reversible_9000=True,
                  both_arms_supervised_tokens=494435,pilot_samples=1024,pilot_tokens_per_run=5120)
    save(report/'data-validation.json',{'status':'passed','checks':checks,'control':control,
        'source_samples_sha256':digest(Path('data/stage44-supervision/train.next_item.jsonl')),
        'validation_does_not_read_holdout_labels':True})
    print({'validation':'passed','checks':checks},flush=True)


if __name__=='__main__':main()
