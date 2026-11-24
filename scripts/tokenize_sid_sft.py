"""Freeze actual tokenizer, full raw-token supervision and exact pilot ordering."""
import json
from pathlib import Path

import numpy as np
from transformers import AutoTokenizer

from gsearch.quality_protocol import digest, save
from gsearch.sid_sft import DATA, REPORT, BASE, load, input_tokens, fixed_features, json_rows


def main() -> None:
    if (REPORT/'tokenization.json').exists():
        raise FileExistsError('Preserve actual tokenizer/mappings')
    original={arm:load(DATA/(arm+'.sid.json')) for arm in ['content','shuffled']}
    vocabulary=sorted({t for tokens in original['content'].values() for t in tokens})
    tokenizer=AutoTokenizer.from_pretrained(BASE,local_files_only=True,trust_remote_code=False)
    added=tokenizer.add_tokens(vocabulary,special_tokens=False)
    assert added==len(vocabulary)
    assert all(tokenizer.encode(token,add_special_tokens=False)==[tokenizer.convert_tokens_to_ids(token)] for token in vocabulary)
    tokenizer.save_pretrained(DATA/'tokenizer')
    prefix=tokenizer.encode('recommend papers:',add_special_tokens=False)
    mappings={}
    for arm in ['content','shuffled']:
        mapping={doc:[tokenizer.convert_tokens_to_ids(t) for t in tokens]+[tokenizer.eos_token_id]
                 for doc,tokens in original[arm].items()}
        assert len({tuple(v) for v in mapping.values()})==9000
        assert len(set(map(len,mapping.values())))==1
        for doc,tokens in mapping.items():
            assert tokenizer.encode(''.join(original[arm][doc]),add_special_tokens=False)+[1]==tokens
        save(DATA/(arm+'.tokens.json'),mapping)
        mappings[arm]=mapping
    samples=list(json_rows(Path('data/stage44-supervision/train.next_item.jsonl')))
    order=np.random.default_rng(271828).permutation(len(samples)).tolist()
    save(DATA/'training-order.json',{'indices':order,'sample_ids':[samples[i]['sample_id'] for i in order]})
    totals={}
    for arm,mapping in mappings.items():
        path=DATA/(arm+'.train.tokens.jsonl')
        total=0; maximum=0
        with path.open('x',encoding='utf-8',newline='\n') as handle:
            for row in samples:
                inputs=input_tokens(row['history_doc_ids'],mapping,prefix)
                labels=mapping[row['target_doc_id']]
                features=fixed_features(inputs,labels)
                features['sample_id']=row['sample_id']
                handle.write(json.dumps(features,separators=(',',':'))+'\n')
                total+=len(labels);maximum=max(maximum,len(inputs))
        totals[arm]={'samples':len(samples),'supervised_tokens':total,'max_input_tokens':maximum,'sha256':digest(path)}
    assert totals['content']['supervised_tokens']==totals['shuffled']['supervised_tokens']
    save(REPORT/'tokenization.json',{'prefix_ids':prefix,'vocabulary':len(tokenizer),'added':added,
        'mapping_documents':9000,'eos':1,'pad_decoder_start':0,'max_target_tokens':len(next(iter(mappings['content'].values()))),
        'all_roundtrip_and_unique':True,'training_order_sha256':digest(DATA/'training-order.json'),'arms':totals,
        'tokenizer_files':{str(p):digest(p) for p in sorted((DATA/'tokenizer').iterdir()) if p.is_file()}})
    print({'tokenization':'passed','arms':totals,'added_tokens':added},flush=True)


if __name__=='__main__':
    main()
