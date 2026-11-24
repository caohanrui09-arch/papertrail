"""Freeze topic-specific assistant review before exposing it in a read-only UI."""
from collections import Counter
import hashlib
import json
from pathlib import Path
from gsearch.quality_protocol import digest,save

ROOT=Path('data/stage30-search-review')
TOPICS={'generative':'直接生成文档ID完成检索','cold':'内容特征与物品冷启动；高相关要求明确联系，严格零交互仍限摘要证据',
 'bias':'推荐曝光/缺失观测建模，或无偏/反事实离线评价；覆盖任一路可高相关，去偏训练不等于策略评价'}


def main() -> None:
 out=ROOT/'review.json'
 if out.exists():raise ValueError('Keep frozen review')
 docs=json.loads(Path('data/stage29-search-v2/documents.json').read_text(encoding='utf-8'))
 notes=json.loads((ROOT/'decisions.json').read_text(encoding='utf-8'))
 mapping={r['doc_id']:r for r in notes};assert len(mapping)==len(notes)==len(docs)==42
 rows=[]
 for p in docs:
  n=mapping[p['doc_id']];assert n['evidence'] in p['abstract'] and len(n['evidence'].split())<=25
  assert len(n['grades'])==3 and all(type(v)is int and v in (0,1,2) for v in n['grades'])
  for topic,grade in zip(TOPICS,n['grades']):
   rows.append({'topic':topic,'doc_id':p['doc_id'],'grade':grade,'reason':n['reason'],'evidence':n['evidence'],
    'abstract_sha256':hashlib.sha256(p['abstract'].encode()).hexdigest(),'version_key':p['version_key'],
    'origin':'model_review','human':False,'independent':False,'confidence':'uncalibrated',
    'limitations':'只审查原v1摘要；已见开发候选，非盲评；未核验全文结论。'})
 summary={topic:{str(k):sum(r['topic']==topic and r['grade']==k for r in rows) for k in (2,1,0)} for topic in TOPICS}
 save(out,{'rules':TOPICS,'reviewer':'current assistant','origin':'model_review','human':False,'independent':False,
  'catalog_sha256':digest(Path('data/stage29-search-v2/documents.json')),'summary':summary,'judgments':rows,
  'not_comparable_to_stage27_nine_distinct_query_rubrics':True})
 # The previous top10 pools are development diagnostics; do not select formulas with these labels.
 runs=json.loads(Path('data/stage29-search-v2/paired-diagnostic-reviewed.json').read_text())
 noise=[]
 for s in runs['scenarios']:
  for method in ['full_request_bm25','core_bm25','core_tfidf']:
   grades=[mapping[p['doc_id']]['grades'][list(TOPICS).index(s['topic'])] for p in s[method]]
   noise.append({'topic':s['topic'],'method':method,'returned':len(grades),'model_grade_counts':dict(Counter(grades))})
 save(Path('reports/stage30/review-summary.json'),{'catalog':42,'judgments':126,'summary':summary,
  'top10_noise_diagnostic':noise,'human_labels':0,'quality_improvement_claimed':False,'ranking_parameters_selected':False})
 print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
