"""Read-only diagnosis of the first frozen teacher-forcing batch; retain outputs."""
import os
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
os.environ.setdefault('HF_HUB_OFFLINE','1')
import json
from pathlib import Path

import torch
from torch.nn import functional as F
from transformers import AutoModelForSeq2SeqLM,default_data_collator,enable_full_determinism

from gsearch.quality_protocol import save,digest
from gsearch.sid_sft import input_tokens,fixed_features
from gsearch.sid_health_probe import token_diagnostics


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def main() -> None:
    output=Path('data/stage47-health/content-42/loss-diagnostic-first8.json')
    if output.exists():raise FileExistsError('Keep numerical diagnostic')
    enable_full_determinism(42);torch.set_num_threads(4)
    model=AutoModelForSeq2SeqLM.from_pretrained('runs/stage45/content-42/final',local_files_only=True,
        trust_remote_code=False,attn_implementation='eager').eval().requires_grad_(False).cuda()
    rows=read('data/stage47-health/prefixes.json')[:8]
    mapping=read('data/stage45-sft/content.tokens.json');prefix=read('reports/stage45/tokenization.json')['prefix_ids']
    priors=read('data/stage47-health/position-priors.json')['content']
    features=[fixed_features(input_tokens(r['history_doc_ids'],mapping,prefix),mapping[r['target_doc_id']]) for r in rows]
    batch={k:v.cuda() for k,v in default_data_collator(features).items()}
    with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
        native=model(**batch,use_cache=False,return_dict=True)
        direct_amp=F.cross_entropy(native.logits.reshape(-1,native.logits.shape[-1]),batch['labels'].reshape(-1))
    with torch.inference_mode():
        direct_fp32=F.cross_entropy(native.logits.float().reshape(-1,native.logits.shape[-1]),batch['labels'].reshape(-1))
        diagnostics=token_diagnostics(native.logits,batch['labels'],priors)
    full_mean=sum(p['full_vocab_nll'] for r in diagnostics for p in r)/40
    raw={'native_loss':float(native.loss),'native_loss_dtype':str(native.loss.dtype),'logits_dtype':str(native.logits.dtype),
        'direct_amp_ce':float(direct_amp),'direct_fp32_ce':float(direct_fp32),'diagnostic_mean':full_mean,
        'native_shape':list(native.logits.shape),'label_shape':list(batch['labels'].shape),
        'native_loss_rounded_to_bf16':float(torch.tensor(full_mean).to(torch.bfloat16)),
        'samples':[{'sample_id':r['sample_id'],'exposure_group':r['exposure_group'],'history_length':r['history_length'],
                    'positions':d} for r,d in zip(rows,diagnostics)],'additional_read_only_forward_samples':8,
        'model_file_sha256':digest(Path('runs/stage45/content-42/final/model.safetensors'))}
    save(output,raw)
    print({k:v for k,v in raw.items() if k!='samples'},flush=True)


if __name__=='__main__':main()
