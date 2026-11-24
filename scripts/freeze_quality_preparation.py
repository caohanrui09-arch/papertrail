"""Freeze the label-free protocol, methods and blind pool; never invent qrels."""
import json
from pathlib import Path
from gsearch.quality_protocol import digest,save

PROJECT=Path(__file__).resolve().parents[1]
ROOT=PROJECT/'data/stage20-quality'
CODE=['gsearch/quality_protocol.py','gsearch/quality_retrieval.py','gsearch/human_quality.py',
    'scripts/prepare_quality_queries.py','scripts/build_quality_pool.py','scripts/audit_agent_failures.py',
    'scripts/freeze_quality_preparation.py','tests/test_quality_preparation.py',
    'third_party/beir_metrics_upstream/custom_metrics.py','docs/label_studio_relevance.xml']


def main() -> None:
    from gsearch.human_quality import load_state
    from gsearch.quality_protocol import coverage
    output=PROJECT/'reports/stage20/locked-before-judgments.json'
    if output.exists():raise ValueError('Already frozen; do not overwrite')
    queries,mapping,runs,labels,confirmed=load_state()
    if labels or confirmed:raise ValueError('This preparation freeze must precede human judgments/confirmation')
    protocol=['reports/stage20/evaluation-plan.json','reports/stage20/upstream-audit.json',
        'third_party/beir_metrics_upstream/LICENSE','third_party/beir_metrics_upstream/NOTICE.txt',
        'third_party/beir_metrics_upstream/SOURCE.md']
    save(output,{'status':'frozen_before_human_labels','code':{p:digest(PROJECT/p) for p in CODE},
        'protocol':{p:digest(PROJECT/p) for p in protocol},'pool_manifest_sha256':digest(ROOT/'pool-manifest.json'),
        'human_judgments_at_freeze':0,'human_query_confirmations_at_freeze':0,
        'selection':'predeclared methods and .7/.3 contextual weighting, not tuned with relevance labels'})
    save(PROJECT/'reports/stage20/annotation-status-at-preparation.json',coverage(queries,mapping,runs,labels,confirmed))
    print(json.dumps({'frozen_before_human_judgments':True,'draft_queries':len(queries),'blind_pairs':len(mapping),'judgments':0}))


if __name__=='__main__':main()
