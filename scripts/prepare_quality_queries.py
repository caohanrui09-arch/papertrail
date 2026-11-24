"""Assistant-authored drafts, never represented as collected human requests."""
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / 'data/stage20-quality'
AT = '2025-02-23T05:28:26.401006+00:00'

# Each family has a topic query, a query-conditioned recommendation and a
# combined reading need. No title, relevance label or retriever output is used.
DRAFTS = [
 ('generative_retrieval', '生成式文档检索', [
  'How can a sequence-to-sequence model retrieve documents by generating document identifiers, and how does it compare with lexical retrieval?',
  'Based on the supplied reading history, recommend papers about generative document retrieval, especially how document identifiers are constructed.',
  'I want to study generative retrieval. Find papers on generating document identifiers and prioritize connections to the supplied reading history.']),
 ('semantic_ids', '推荐中的语义标识与码本', [
  'How are semantic item identifiers or codebooks learned for generative recommendation, and what happens when new items arrive?',
  'Recommend research on semantic identifiers for recommendation that connects to the supplied history and discusses item representations.',
  'Find work on learned semantic identifiers for recommendation and suggest reading that connects these methods to my supplied history.']),
 ('cold_start', '无交互论文与冷启动推荐', [
  'Which methods recommend new items that have no interaction history using their text or content features?',
  'Using the supplied history, recommend work on combining collaborative and content signals for cold-start items without suppressing new items.',
  'Find studies of item cold start and content-based recommendation, then prioritize papers that complement the supplied reading history.']),
 ('feedback_bias', '隐式反馈、曝光偏差与反事实评价', [
  'How can recommendation models learn from implicit feedback while accounting for exposure bias and missing negative feedback?',
  'Recommend work on unbiased or counterfactual recommendation evaluation that is connected to the supplied reading history.',
  'Find papers about exposure bias in recommendation and suggest related reading using the supplied history; I care about offline evaluation assumptions.']),
 ('tool_agents', '工具Agent的预算与调度评价', [
  'How should tool-using language-model agents be evaluated under limits on tool calls, latency and token usage?',
  'Recommend papers about reliable tool calling and efficient agent planning that relate to the supplied history.',
  'Find work comparing language-model agent planning with fixed tool workflows, and prioritize connections to the supplied reading history.']),
 ('grounded_retrieval', '检索增强与可追溯引用', [
  'How can retrieval-augmented systems produce citations that actually support an answer, and how is citation quality evaluated?',
  'Based on the supplied history, recommend research on evidence retrieval and citation-grounded language-model answers.',
  'Find methods for retrieval-augmented generation with verifiable citations, then identify useful connections to the supplied reading history.']),
 ('temporal_updates', '时序目录、增量索引与兴趣漂移', [
  'How can a search or recommendation index incorporate newly published items over time without retraining the entire model?',
  'Recommend work on temporal recommendation, evolving interests or incremental retrieval indexes that complements the supplied history.',
  'Find research on incremental indexing and changing user interests; use the supplied history to prioritize papers on time-aware retrieval or recommendation.']),
 ('efficient_ranking', '检索排序的蒸馏与资源成本', [
  'How can distillation reduce the inference cost of retrieval or ranking models while retaining useful ranking quality?',
  'Using the supplied history, recommend research on efficient ranking, model distillation or compact retrieval representations.',
  'Find studies that compare retrieval quality with latency or memory cost, and suggest connections to efficient ranking topics in the supplied history.'])]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def main() -> None:
    if ROOT.exists(): raise ValueError('Query preparation exists; preserve prior version')
    documents = PROJECT/'data/stage13-expansion/documents.json'
    training = PROJECT/'data/stage9-recommendation/train.csv'
    records = json.loads(documents.read_text(encoding='utf-8'))
    available = {r['doc_id']: r for r in records if datetime.fromisoformat(r['available_at']) <= datetime.fromisoformat(AT)}
    likes: dict[str, set[str]] = {}
    with training.open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            if float(row['rating']) == 1 and row['arxiv_id'] in available:
                likes.setdefault(row['user_id'], set()).add(row['arxiv_id'])
    hash_key = lambda text: hashlib.sha256(('stage20-draft-v1:'+text).encode()).hexdigest()
    users = sorted((u for u, ds in likes.items() if len(ds) >= 5), key=hash_key)
    tuning_families = set(sorted((f[0] for f in DRAFTS), key=hash_key)[:3])
    queries, profiles, reviews = [], {}, []
    for index, (family, topic_zh, requests) in enumerate(DRAFTS):
        user = users[index]
        history = sorted(likes[user], key=hash_key)[:5]
        profile_id = 'context-'+hash_key(user)[:16]
        profiles[profile_id] = {'user_id': user, 'history_doc_ids': history,
            'origin': 'five hash-selected genuine training likes used as a synthetic scenario context; not a human self-reported research need',
            'all_training_positive_and_negative_seen_still_filtered': True}
        for j, text in enumerate(requests):
            qid = f'q20-{index*3+j+1:03d}'
            split = 'tuning' if family in tuning_families else 'evaluation'
            query = {'query_id': qid, 'intent': ('topic','recommend','mixed')[j], 'topic_family': family,
                'topic_zh': topic_zh, 'request': text, 'query_origin': 'assistant_draft',
                'human_authored': False, 'human_confirmed_at_creation': False,
                'source_context': 'User requested generative search/recommendation and Agent algorithm project; individual requests authored by assistant, not collected from users',
                'split': split, 'profile_id': profile_id, 'at': AT}
            queries.append(query)
            reviews.append({'query_id': qid, 'request': text, 'query_origin': 'assistant_draft',
                'confirmed': '', 'reviewer_id': '', 'reviewed_at': '', 'note': ''})
    save(ROOT/'inputs/queries.json', queries)
    save(ROOT/'evaluator/profiles-private.json', profiles)
    fields = ['query_id','request','query_origin','confirmed','reviewer_id','reviewed_at','note']
    write_csv(ROOT/'templates/query-review.csv', fields, reviews)
    write_csv(ROOT/'work/query-review.csv', fields, reviews)
    write_csv(ROOT/'templates/real-query-intake.csv', ['request_id','request','intent','requester_alias','received_at','language','consent_to_local_research'], [])
    plan = {'status': 'prepared_without_human_queries_or_judgments', 'assistant_draft_queries':24,
        'human_authored_queries':0, 'initial_human_judgments':0, 'requests_per_intent':8,
        'split_rule':'hash-selected 3 entire topic families for tuning9; remaining families evaluation15; no family/user across splits',
        'at':AT, 'catalog':10000, 'methods':['bm25','query_tfidf','personalized_query_tfidf'],
        'personalized_formula':'native L2 normalize(.7*query_vector+.3*L2(sum of same five displayed training-liked document vectors))); query-only fallback if history has no support; zero query signal returns no content results',
        'profile_context':'exactly five displayed training likes, identical across methods; not the full user profile; all train positive/negative seen filtered',
        'k':10, 'pool':'union of three top10 results, no positive-label filtering; deterministic blind order; no predictions supplied',
        'timing':'3 paired rounds; method order rotated by query/round; first snapshot build and one-time model loading separately recorded; no serving QPS claim',
        'metrics':{'ndcg':'native sklearn ndcg_score, gains 2**grade-1, ideal over fully judged pooled candidates; unreturned slots padded with zero-gain dummies',
            'mrr':'native BEIR mrr at10, grade>=1 relevant, upstream 5-decimal rounding',
            'recall':'not computed: judgments only cover candidate pool, outside-pool relevant papers unknown',
            'coverage':'pooled judgments, per-method judged returned@10, returned slots@10, query confirmation; unjudged never silently becomes grade0'},
        'human_gate':'No quality scores until target-split query confirmation and complete explicitly human judgments. Human origin is a declaration, not identity authentication. Tuning score/freeze required before evaluation.',
        'grade_rubric':{'0':'does not meet explicit need','1':'partly meets need or a necessary constraint is not established','2':'directly addresses core need and relevant constraints; history only contextual, never overrides explicit topic'},
        'frozen_inputs':{str(p.relative_to(PROJECT)):digest(p) for p in [documents,training,ROOT/'inputs/queries.json',ROOT/'evaluator/profiles-private.json']}}
    save(PROJECT/'reports/stage20/evaluation-plan.json', plan)
    print(json.dumps({'assistant_draft_queries':24,'human_queries':0,'tuning':9,'evaluation':15,'human_judgments':0}))


if __name__ == '__main__': main()
