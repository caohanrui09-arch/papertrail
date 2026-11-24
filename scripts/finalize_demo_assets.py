"""Assemble curated final resume and refresh only the new stage52 asset receipt."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    bundle=ROOT/'deploy/stage52'
    evidence=json.loads((bundle/'evidence-data.json').read_text(encoding='utf-8'))
    content=(ROOT/'docs/RESUME_FINAL_V52.md').read_bytes()
    target=bundle/'experiment-artifacts/resume-final.md'
    target.write_bytes(content)
    evidence['downloads']['resume'].update(filename=target.name,label='统一简历与面试证据',sha256=hashlib.sha256(content).hexdigest())
    raw=(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    (bundle/'evidence-data.json').write_bytes(raw)
    receipt={'sha256':hashlib.sha256(raw).hexdigest(),'downloads':{k:v['sha256'] for k,v in evidence['downloads'].items()}}
    (bundle/'evidence-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    notice=bundle/'web/open-source.txt'
    marker='\n\nSTAGE52 EVIDENCE DELIVERY\n'
    old=notice.read_text(encoding='utf-8').split(marker)[0]
    notice.write_text(old+marker+'Existing Preact/HTM and native SVG; no new dependency. Evidence downloads contain selected aggregate reports and resume only. Current web catalog:162; offline SFT:9000; current budget design closed. Full reuse review: reports/stage52/THIRD_PARTY_NOTICES.md (local project). Existing data/source restrictions remain applicable.\n',encoding='utf-8')
    print({'resume':target.name,'evidence_sha256':receipt['sha256']})

if __name__=='__main__':main()
