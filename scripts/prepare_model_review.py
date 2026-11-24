"""Snapshot only blinded inputs for assistant-only review; refuse replacement."""
import json
from pathlib import Path
from gsearch.quality_protocol import digest,save


def main():
    root=Path('data/stage27-model-review')
    if root.exists():raise ValueError('Preserve existing review version')
    source=Path('data/stage26-annotation/blind/tasks.json')
    data=json.loads(source.read_text(encoding='utf-8'))
    root.mkdir(parents=True)
    (root/'blind-input.json').write_bytes(source.read_bytes())
    papers={}
    for qid,task in data.items():
        for c in task['candidates']:
            doc=c['paper']['doc_id']
            if doc not in papers:papers[doc]={'paper':c['paper'],'queries':[]}
            papers[doc]['queries'].append(qid)
    save(root/'paper-reader.json',list(papers.values()))
    save(root/'input-manifest.json',{'origin':'model_blind_review','model':'gpt-6.1-sol','human':False,
        'source_sha256':digest(source),'pool_version':json.loads(Path('data/stage26-annotation/manifest.json').read_text())['pool_version'],
        'queries':len(data),'pairs':sum(len(t['candidates']) for t in data.values()),'unique_candidates':len(papers),
        'methods_ranks_scores_read':False,'reviewer_involved_in_system_design':True,
        'files':{p.name:digest(p) for p in root.iterdir() if p.is_file()}})
    print(json.dumps({'snapshot_prepared':True,'queries':len(data),'papers':len(papers),'origin':'model_blind_review'}))


if __name__=='__main__':main()
