"""26-query adapter over original BlindPool/AnnotationStore, not a new label engine."""
from pathlib import Path

from gsearch.annotation_store import BlindPool,AnnotationStore
from research73.common import DATA,read,digest


class EvaluationPool(BlindPool):
    def __init__(self):
        self.root=DATA;manifest=read(DATA/'manifest.json')
        for name,h in manifest['immutable_assets'].items():
            path=(DATA/name).resolve()
            if not path.is_relative_to(DATA.resolve()) or digest(path)!=h:raise ValueError('Evaluation blind pool changed')
        self.version=manifest['pool_version'];self.tasks=read(DATA/'blind/tasks.json');self.pairs=manifest['pairs']
        if len(self.tasks)!=26:raise ValueError('Expected exactly26 frozen materials')


class EvaluationStore(AnnotationStore):
    def workspace(self,owner: str) -> dict:
        value=super().workspace(owner);value['total_queries']=len(self.pool.tasks);value['split']='stage73-materials'
        value['scope']='本轮复用材料与控制；非独立真人需求测试。未标注、草稿、跳过不视为不相关。'
        return value


class ExportStore:
    """Read an unchanged native export without importing records into the human DB."""
    def __init__(self,path: Path,pool: EvaluationPool):
        value=read(path)
        if value.get('pool_version')!=pool.version:raise ValueError('Export belongs to another frozen pool')
        self.pool=pool;self.details={}
        for detail in value['queries']:
            qid=detail['query']['query_id']
            if qid in self.details or detail['query']!=pool.task(qid)['query']:raise ValueError('Export query changed or repeated')
            expected={c['annotation_id']:c['paper'] for c in pool.task(qid)['candidates']}
            received={c['annotation_id']:c['paper'] for c in detail['candidates']}
            if expected!=received or len(received)!=len(detail['candidates']):raise ValueError('Export candidate pool changed')
            review=detail['review'].get('value') or {}
            for c in detail['candidates']:
                record=c['record'].get('value') or {}
                c['valid_submission']=bool(review.get('status')=='approve' and record.get('status')=='submitted' and
                    record.get('review_revision')==detail['review']['revision'] and type(record.get('grade')) is int and record['grade'] in (0,1,2) and
                    record.get('query_hash')==detail['query']['query_hash'])
            self.details[qid]=detail
        if set(self.details)!=set(pool.tasks):raise ValueError('Native export must preserve all query records, including unjudged ones')

    def detail(self,owner: str,qid: str) -> dict:return self.details[qid]
