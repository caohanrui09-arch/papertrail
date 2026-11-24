"""Bounded official topic acquisition through pinned arxiv.py; resumable phases."""
from datetime import datetime
import argparse
import json
from pathlib import Path

from filelock import FileLock
from gsearch import metadata_fetch as mf
from gsearch.expansion_data import available_at
from gsearch.quality_protocol import digest, save

ROOT=Path('data/stage29-search-v2')
CACHE=Path('.cache/stage29')
AT='2025-02-23T05:28:26.401006+00:00'
TOPICS={
 'generative':{'query':'(abs:"generative retrieval" OR abs:"differentiable search index" OR abs:"document identifiers")', 'core':'generative retrieval document identifiers'},
 'cold':{'query':'(abs:"cold start" OR abs:"cold-start") AND (abs:recommendation OR abs:recommender) AND (abs:content OR abs:metadata)', 'core':'item cold start content features recommendation'},
 'bias':{'query':'(abs:exposure OR abs:propensity OR abs:counterfactual) AND (abs:recommendation OR abs:recommender)', 'core':'recommendation exposure bias counterfactual offline evaluation'}
}
ANCHORS=['2202.06991','2206.02743','1507.08439','1510.07025','1602.05352','1003.5956']


def load(p: Path) -> object:
 return json.loads(p.read_text(encoding='utf-8'))


def main() -> None:
 parser=argparse.ArgumentParser();parser.add_argument('--direct',action='store_true');parser.add_argument('--retry-transport',action='store_true');args=parser.parse_args()
 if (ROOT/'documents.json').exists():raise ValueError('Catalog frozen; preserve it')
 if not (ROOT/'plan.json').exists():
  save(ROOT/'plan.json',{'topics':TOPICS,'anchors':ANCHORS,'at':AT,'max_discovery_per_topic':12,
   'date_query':'submittedDate:[199001010000 TO 202502212359]','sort':'submittedDate descending',
   'admission':'Explicit official v1, available_at <= at, original title/abstract nonempty; no relevance-label filtering',
   'scope':'bounded retrospective development catalog, not historical complete source snapshot or independent test',
   'history':'two hash-selected v1 documents per discovery topic; label as synthetic content contexts; reserve same union of histories from every condition',
   'ranking':'native SQLite BM25 and TFIDF core query; fixed topic top10 then .7 query+.3 context rerank only those ten; no tuning',
   'old_corpus_sha256':digest(Path('data/stage13-expansion/documents.json'))})
 plan=load(ROOT/'plan.json');assert plan['topics']==TOPICS and plan['at']==AT
 package=mf.upstream();old_root=mf.ROOT
 for directory in [old_root,Path('.cache/stage13'),CACHE]:
  p=directory/'rate-limit.json'
  if p.exists() and datetime.fromisoformat(load(p)['retry_not_before'])>datetime.now().astimezone():
   print(json.dumps({'blocked':'official cooldown','file':str(p)}));return
 mf.ROOT=CACHE;CACHE.mkdir(parents=True,exist_ok=True)
 session=mf.RecordedSession('arxiv',3.1)
 if args.direct:session.trust_env=False
 client=package.Client(page_size=40,delay_seconds=3.1,num_retries=0);client._session=session
 def fetch(name: str,search: object) -> list:
  output=ROOT/'acquisition'/f'{name}.json'
  if output.exists():
   previous=load(output)
   if not previous['error']:return previous['records']
   if not args.retry_transport or 'ProxyError' not in previous['error']:raise ValueError('Prior failure retained; inspect before retry')
   output=ROOT/'acquisition'/f'{name}-transport-retry.json'
   if output.exists():
    previous=load(output)
    if previous['error']:raise ValueError('Transport retry already failed')
    return previous['records']
  before=len(session.receipts);records=[];error=None
  try:
   for result in client.results(search):
    records.append({**mf.record_api(result,session.receipts[-1]),'categories':list(result.categories),'primary_category':result.primary_category})
  except Exception as exc:error=type(exc).__name__+': '+str(exc)
  save(output,{'records':records,'error':error,'requests':session.receipts[before:]})
  print(json.dumps({'batch':name,'records':len(records),'error':error}),flush=True)
  if error:raise RuntimeError(error)
  return records
 try:
  with FileLock(str(CACHE/'acquisition.lock'),timeout=0):
   discoveries={}
   for topic,settings in TOPICS.items():
    discoveries[topic]=fetch('discover-'+topic,package.Search(query='('+settings['query']+') AND '+plan['date_query'],max_results=12,sort_by=package.SortCriterion.SubmittedDate,sort_order=package.SortOrder.Descending))
   ids=sorted(set(ANCHORS)|{r['doc_id'] for rows in discoveries.values() for r in rows})
   versions=fetch('explicit-v1',package.Search(id_list=[d+'v1' for d in ids],max_results=len(ids)))
   accepted=[];rejected=[]
   for row in versions:
    if row['doc_id'] not in ids or row['version']!=1:raise ValueError('Unexpected explicit version')
    if not row['title'].strip() or not row['abstract'].strip() or available_at(row['published_at'])>datetime.fromisoformat(AT):
     rejected.append({'doc_id':row['doc_id'],'reason':'empty text or v1 time proxy after query'});continue
    raw=Path(row['provenance']['raw_path']);assert digest(raw)==row['provenance']['raw_sha256']
    accepted.append({**row,'version_key':'arxiv:'+row['doc_id']+'v1','available_at':available_at(row['published_at']).isoformat(),
      'discovery_topics':[k for k,v in discoveries.items() if row['doc_id'] in {r['doc_id'] for r in v}],
      'anchor_check':row['doc_id'] in ANCHORS,'source_verified':True})
   assert len({r['doc_id'] for r in accepted})==len(accepted)
   save(ROOT/'documents.json',accepted)
   save(ROOT/'catalog-receipt.json',{'documents':len(accepted),'requested':len(ids),
    'missing':sorted(set(ids)-{r['doc_id'] for r in versions}),'rejected':rejected,
    'anchors_present':[d for d in ANCHORS if d in {r['doc_id'] for r in accepted}],
    'documents_sha256':digest(ROOT/'documents.json'),'plan_sha256':digest(ROOT/'plan.json')})
 finally:session.close();mf.ROOT=old_root


if __name__=='__main__':main()
