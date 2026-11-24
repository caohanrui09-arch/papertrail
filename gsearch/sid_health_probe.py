"""Thin read-only adapters around native HF beam outputs and PyTorch token CE."""
import hashlib
import math

import torch
from torch.nn import functional as F
from transformers import LogitsProcessor,default_data_collator

from .sid_sft import fixed_features,input_tokens

POSITIONS=['semantic1','semantic2','semantic3','identity','eos']


class BeamObserver(LogitsProcessor):
    """Observe current beams; return the exact same score object, unmodified."""
    def __init__(self):
        self.steps=[]

    def __call__(self,input_ids: torch.Tensor,scores: torch.Tensor) -> torch.Tensor:
        self.steps.append({'prefixes':input_ids.detach().cpu().tolist(),
                           'finite_branch_counts':torch.isfinite(scores).sum(-1).cpu().tolist()})
        return scores


def paired_rank_metrics(original: list[str],swapped: list[str]) -> dict:
    if len(original)!=10 or len(swapped)!=10 or len(set(original))!=10 or len(set(swapped))!=10:
        raise ValueError('Unique Top10 lists required')
    a=set(original);b=set(swapped);shared=a&b
    ar={d:i+1 for i,d in enumerate(original)};br={d:i+1 for i,d in enumerate(swapped)}
    distance=sum(abs(ar.get(d,11)-br.get(d,11)) for d in a|b)/110
    return {'shared_items':len(shared),'overlap_fraction':len(shared)/10,'jaccard':len(shared)/len(a|b),
            'ordered_equal':original==swapped,'top1_equal':original[0]==swapped[0],
            'footrule_missing_rank11_div110':distance}


def parameter_fingerprint(model) -> str:
    result=hashlib.sha256()
    for name,parameter in model.named_parameters():
        result.update(name.encode());result.update(parameter.detach().cpu().contiguous().numpy().tobytes())
    return result.hexdigest()


def observed_decode(model,tokenizer,constraint,histories: list[list[str]],seen: list[set[str]],
                    mapping: dict,prefix: list[int]) -> tuple[list[dict],dict]:
    if any(len(mapping)-len(s.intersection(mapping))<10 for s in seen):
        raise ValueError('Insufficient unseen candidates')
    constraint.seen=seen
    features=[fixed_features(input_tokens(h,mapping,prefix),[1]) for h in histories]
    batch=default_data_collator(features);batch.pop('labels')
    batch={k:v.to(model.device) for k,v in batch.items()}
    observer=BeamObserver()
    with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
        output=model.generate(**batch,num_beams=10,num_return_sequences=10,max_new_tokens=5,
            do_sample=False,length_penalty=0.0,early_stopping=True,prefix_allowed_tokens_fn=constraint.allowed,
            renormalize_logits=False,return_dict_in_generate=True,output_scores=True,logits_processor=[observer])
    transitions=model.compute_transition_scores(output.sequences,output.scores,output.beam_indices,normalize_logits=False)
    score_error=(transitions.sum(-1)-output.sequences_scores).abs().max().item()
    if score_error>1e-4:raise ValueError('Native transition/sequence score mismatch')
    if len(observer.steps)!=5 or len(output.scores)!=5:raise ValueError('Incomplete beam trace')
    sequences=output.sequences.cpu().tolist();ancestry=output.beam_indices.cpu().tolist()
    transition_values=transitions.cpu().tolist();scores=output.sequences_scores.cpu().tolist()
    all_prefixes_legal=0
    for step_index,step in enumerate(observer.steps):
        for row_index,path in enumerate(step['prefixes']):
            if len(path)!=step_index+1 or path[0]!=0:raise ValueError('Wrong observed decoder prefix')
            node=constraint.tree.root
            for token in path[1:]:
                if token not in constraint.tree.node_list[node]:raise ValueError('Observed invalid prefix')
                node=constraint.tree.node_list[node][token]
            receiver=row_index//10
            allowed=[t for t,child in constraint.tree.node_list[node].items()
                     if not constraint.descendants[child].issubset(seen[receiver])]
            if step['finite_branch_counts'][row_index]!=len(allowed):
                raise ValueError('Observer score mask differs from native legal tree branches')
            all_prefixes_legal+=1
    results=[]
    for receiver in range(len(histories)):
        docs=[];paths=[];indices=[];values=[];native_scores=[]
        for row in range(receiver*10,(receiver+1)*10):
            sequence=sequences[row]
            if len(sequence)!=6 or sequence[0]!=0 or sequence[-1]!=1:raise ValueError('Incomplete EOS output')
            tokens=sequence[1:];ids=constraint.tree.get(tokens)
            if ids is None or len(ids)!=1:raise ValueError('SID not reversible')
            doc=ids[0]
            if tokens!=mapping[doc] or doc in seen[receiver] or doc in docs:raise ValueError('Bad returned candidate')
            if len(ancestry[row])!=5:raise ValueError('Wrong native beam ancestry length')
            for step_index,parent in enumerate(ancestry[row]):
                if not receiver*10<=parent<(receiver+1)*10:raise ValueError('Beam crossed receiving profile')
                if observer.steps[step_index]['prefixes'][parent]!=sequence[:step_index+1]:
                    raise ValueError('Native ancestry does not reconstruct selected prefix')
            docs.append(doc);paths.append(tokens);indices.append(ancestry[row]);values.append(transition_values[row]);native_scores.append(scores[row])
        results.append({'doc_ids':docs,'token_ids':paths,'beam_indices':indices,
                        'transition_scores':values,'sequence_scores':native_scores})
    return results,{'steps':observer.steps,'max_transition_sum_error':score_error,
                    'all_observed_prefixes_legal':all_prefixes_legal,
                    'native_scores_output':True,'full_vocabulary_scores_not_persisted':True}


def token_diagnostics(logits: torch.Tensor,labels: torch.Tensor,priors: list[dict]) -> list[list[dict]]:
    logits=logits.float()
    full_loss=F.cross_entropy(logits.reshape(-1,logits.shape[-1]),labels.reshape(-1),reduction='none').reshape(labels.shape)
    output=[[] for _ in range(len(labels))]
    for position,prior in enumerate(priors):
        allowed=torch.tensor(prior['allowed_ids'],device=logits.device,dtype=torch.long)
        matches=allowed[None,:]==labels[:,position,None]
        if not torch.all(matches.sum(-1)==1):raise ValueError('Target outside position codebook')
        local_targets=matches.long().argmax(-1)
        scores=logits[:,position,:];local=scores[:,allowed]
        local_loss=F.cross_entropy(local,local_targets,reduction='none')
        log_mass=torch.logsumexp(local,dim=-1)-torch.logsumexp(scores,dim=-1)
        if not torch.allclose(full_loss[:,position],local_loss-log_mass,atol=1e-5,rtol=1e-5):
            raise ValueError('NLL decomposition mismatch')
        for index in range(len(labels)):
            target=int(labels[index,position]);count=prior['pilot_counts'][str(target)]
            output[index].append({'position':POSITIONS[position],
                'target_token_id':target,'full_vocab_nll':float(full_loss[index,position]),
                'position_conditional_nll':float(local_loss[index]),'position_mass':float(log_mass[index].exp()),
                'full_vocab_top1_correct':bool(scores[index].argmax()==labels[index,position]),
                'position_top1_correct':bool(local[index].argmax()==local_targets[index]),
                'uniform_position_nll':math.log(len(allowed)),
                'pilot_position_prior_nll':math.log(prior['total']+len(allowed)*prior['alpha'])-math.log(count+prior['alpha'])})
    return output
