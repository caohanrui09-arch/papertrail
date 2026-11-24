"""Stage45 adapters: immutable raw SID tokens, native HF trainer/beam and ZeroGR tree."""
import hashlib
import json
from pathlib import Path
import subprocess

import torch
from torch.utils.data import IterableDataset
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, default_data_collator, set_seed

from .prefix_decoder import upstream_tree_class
from .quality_protocol import digest

DATA=Path('data/stage45-sft')
REPORT=Path('reports/stage45')
BASE=Path('.cache/models/t5-small')


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def json_rows(path: Path):
    """Stream already-validated JSONL without importing the pandas-only data runtime."""
    with path.open(encoding='utf-8') as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def input_tokens(history: list[str], mapping: dict, prefix: list[int], limit: int=96) -> list[int]:
    result=prefix+[token for doc in history[-20:] for token in mapping[doc][:-1]]+[1]
    if len(result)>limit:
        raise ValueError('Frozen history exceeds encoder limit; no silent truncation')
    return result


def fixed_features(inputs: list[int], labels: list[int], limit: int=96) -> dict:
    if len(inputs)>limit or not labels or labels[-1]!=1 or 0 in labels or -100 in labels:
        raise ValueError('Invalid raw input/label contract')
    return {'input_ids':inputs+[0]*(limit-len(inputs)),
            'attention_mask':[1]*len(inputs)+[0]*(limit-len(inputs)), 'labels':labels}


class OrderedExamples(IterableDataset):
    """An exact finite stream; HF owns batching/optimization, no hidden reshuffle."""
    def __init__(self, rows: list[dict]):
        self.rows=rows
        self.observed: list[int]=[]

    def __iter__(self):
        for index,row in enumerate(self.rows):
            self.observed.append(index)
            yield {k:row[k] for k in ['input_ids','attention_mask','labels']}

    def __len__(self) -> int:
        return len(self.rows)


def fresh_model(seed: int):
    set_seed(seed)
    tokenizer=AutoTokenizer.from_pretrained(DATA/'tokenizer',local_files_only=True,trust_remote_code=False)
    model=AutoModelForSeq2SeqLM.from_pretrained(BASE,local_files_only=True,trust_remote_code=False,attn_implementation='eager')
    model.resize_token_embeddings(len(tokenizer),mean_resizing=False)
    model.config.use_cache=False
    # Record added-row initialization as well as pretrained weight-file hashes.
    initial=hashlib.sha256(model.get_input_embeddings().weight.detach().numpy().tobytes()).hexdigest()
    return model,tokenizer,initial


class CatalogConstraint:
    """Seen filtering over the unchanged upstream tree, before beam ranking."""
    def __init__(self, mapping: dict, tokenizer: object):
        cls=upstream_tree_class()
        self.tree=cls(start_id=0,end_id=1,tokenizer=tokenizer)
        for doc,tokens in sorted(mapping.items()):
            self.tree.set(tokens,doc)
        self.descendants={}
        def visit(node: int) -> set[str]:
            members=set(self.tree.node2doc.get(node,[]))
            for child in self.tree.node_list[node].values():
                members.update(visit(child))
            self.descendants[node]=frozenset(members)
            return members
        visit(self.tree.root)
        self.seen: list[set[str]]=[]

    def allowed(self, batch_id: int, sequence: torch.Tensor) -> list[int]:
        path=sequence.tolist()
        if not path or path[0]!=0:
            raise ValueError('Decoder start token missing')
        node=self.tree.root
        for token in path[1:]:
            if token not in self.tree.node_list[node]:
                raise ValueError('Illegal decoder prefix')
            node=self.tree.node_list[node][token]
        children=self.tree.node_list[node]
        if not children and path[-1]==1:
            return [1]
        result=[token for token,child in children.items() if not self.descendants[child].issubset(self.seen[batch_id])]
        if not result:
            raise ValueError('No eligible continuation')
        return result


def decode_batch(model, tokenizer, constraint: CatalogConstraint, histories: list[list[str]],
                 seen: list[set[str]], mapping: dict, prefix: list[int]) -> list[dict]:
    if any(len(mapping)-len(s.intersection(mapping))<10 for s in seen):
        raise ValueError('Fewer than ten available unseen candidates')
    constraint.seen=seen
    rows=[fixed_features(input_tokens(h,mapping,prefix),[1]) for h in histories]
    batch=default_data_collator(rows)
    batch.pop('labels')
    batch={k:v.to(model.device) for k,v in batch.items()}
    maximum=max(map(len,mapping.values()))
    model.eval(); model.config.use_cache=True
    with torch.inference_mode(), torch.autocast('cuda',dtype=torch.bfloat16):
        output=model.generate(**batch,num_beams=10,num_return_sequences=10,max_new_tokens=maximum,
            do_sample=False,length_penalty=0.0,early_stopping=True,
            prefix_allowed_tokens_fn=constraint.allowed,renormalize_logits=False,
            return_dict_in_generate=True,output_scores=False)
    sequences=output.sequences.cpu().tolist()
    results=[]
    for index in range(len(histories)):
        docs=[]; paths=[]
        for sequence in sequences[index*10:(index+1)*10]:
            tokens=sequence[1:]
            if 1 not in tokens:
                raise ValueError('Beam did not emit EOS')
            end=tokens.index(1)+1
            if any(t!=0 for t in tokens[end:]):
                raise ValueError('Unexpected tokens after EOS')
            tokens=tokens[:end]
            identities=constraint.tree.get(tokens)
            if identities is None or len(identities)!=1:
                raise ValueError('Output not uniquely reversible')
            doc=identities[0]
            if doc in seen[index] or doc in docs or tokens!=mapping[doc]:
                raise ValueError('Seen/duplicate/incorrect SID')
            docs.append(doc); paths.append(tokens)
        if len(docs)!=10:
            raise ValueError('Incomplete Top10')
        results.append({'doc_ids':docs,'token_ids':paths})
    return results


def verify_lock() -> dict:
    lock=load(REPORT/'run-lock.json')
    # Reuse the sealed evaluator in its original pandas runtime, without installing
    # pandas into the unrelated shared CUDA environment.
    command="from pathlib import Path; import json; from gsearch.quality_protocol import digest; from gsearch.supervision_evaluation import locked_run; locked_run(json.loads(Path('reports/stage45/run-lock.json').read_text()),digest(Path('reports/stage44/protocol.json')),digest(Path('data/stage44-supervision/catalog.json')),digest(Path('reports/stage44/evaluation-addendum.json')))"
    subprocess.run([str(Path('.cache/stage17/runtime/Scripts/python.exe').resolve()),'-E','-s','-c',command],check=True,capture_output=True,text=True)
    for path,expected in lock['files'].items():
        if digest(Path(path))!=expected:
            raise ValueError('Frozen run asset changed: '+path)
    return lock
