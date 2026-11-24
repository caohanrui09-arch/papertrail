"""Stage92 (restored): two-step follow-up over the quotes read in the task.

Step 1 selects 1-2 read quotes; step 2 writes the answer from them. Citations are
fixed by step 1. Stage93's stricter selector and full-abstract candidates caused 8/8
refusals, so this version is the best measured one.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.cache/decoder-deps'))

MODEL_DIR = ROOT / '.cache/models/Qwen2.5-1.5B-Instruct'
REFUSAL = '无法从已读摘要确定'


def quote_catalog(papers: list[dict]) -> list[dict]:
    items = []
    for paper in papers:
        for index, quote in enumerate(paper.get('quotes') or []):
            items.append({'doc_id': paper['doc_id'], 'quote_index': index, 'text': quote.get('text', '')})
    return items


def select_schema(papers: list[dict]) -> dict:
    ids = sorted({paper['doc_id'] for paper in papers})
    maximum = max((len(paper.get('quotes') or []) for paper in papers), default=1) - 1
    return {'type': 'object', 'properties': {
        'picks': {'type': 'array', 'maxItems': 2, 'items': {
            'type': 'object',
            'properties': {'doc_id': {'enum': ids}, 'quote_index': {'type': 'integer', 'minimum': 0, 'maximum': max(maximum, 0)}},
            'required': ['doc_id', 'quote_index'], 'additionalProperties': False}},
        'insufficient': {'type': 'boolean'}},
        'required': ['picks', 'insufficient'], 'additionalProperties': False}


def answer_schema() -> dict:
    return {'type': 'object', 'properties': {'answer': {'type': 'string'}},
            'required': ['answer'], 'additionalProperties': False}


def select_messages(question: str, papers: list[dict]) -> list[dict]:
    lines = []
    for item in quote_catalog(papers):
        lines.append(f"[{item['doc_id']}] ({item['quote_index']}) {item['text']}")
    system = ('你是证据筛选器。下面是从论文里读到的原文句子。'
              '选出最能直接回答问题的 1–2 句；如果这些句子都回答不了，把 insufficient 设为 true 且 picks 为空。'
              '输出 JSON {"picks":[{"doc_id":...,"quote_index":...}],"insufficient":false}。')
    user = f"问题：{question}\n\n候选原文：\n" + "\n".join(lines)
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]


def answer_messages(question: str, picks: list[dict]) -> list[dict]:
    evidence = "\n".join(f"[{pick['doc_id']}] {pick.get('text') or pick.get('quote')}" for pick in picks)
    system = ('只根据下面选出的原文句子，用 2–3 句中文直接回答问题：先给结论，再给依据。'
              '不要复述问题，不要加入原文没有的信息。输出 JSON {"answer": string}。')
    user = f"问题：{question}\n\n原文句子：\n{evidence}"
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]


def resolve(papers: list[dict], picks: list[dict]) -> tuple[list[dict], str | None]:
    by_id = {paper['doc_id']: paper for paper in papers}
    resolved, seen = [], set()
    for pick in picks:
        if not isinstance(pick, dict) or set(pick) != {'doc_id', 'quote_index'}:
            return [], 'pick must contain exactly doc_id and quote_index'
        doc, index = pick['doc_id'], pick['quote_index']
        if doc not in by_id:
            return [], f'{doc} was not read in this task'
        quotes = by_id[doc].get('quotes') or []
        if type(index) is not int or not 0 <= index < len(quotes):
            return [], f'quote_index out of range for {doc}'
        key = (doc, index)
        if key in seen:
            continue
        seen.add(key)
        resolved.append({'doc_id': doc, 'version_key': by_id[doc].get('version_key'),
                         'title': by_id[doc].get('title'), 'source_url': by_id[doc].get('source_url'),
                         'quote': quotes[index].get('text'), 'quote_index': index,
                         'source_verified': True, 'retrieved_by': 'read_paper'})
    return resolved, None


def validate_picks(papers: list[dict], picks: list[dict]) -> bool:
    allowed = {(paper['doc_id'], index) for paper in papers for index in range(len(paper.get('quotes') or []))}
    return bool(picks) and all((pick.get('doc_id'), pick.get('quote_index')) in allowed for pick in picks)


def validate_answer(value: object) -> tuple[str | None, str | None]:
    if not isinstance(value, dict) or set(value) != {'answer'}:
        return None, 'Answer must contain exactly answer'
    answer = value.get('answer')
    if not isinstance(answer, str) or not answer.strip():
        return None, 'Answer must be a nonempty string'
    return answer.strip(), None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    spec = json.loads(Path(args.input).read_text(encoding='utf8'))
    question, papers = spec['question'], spec['papers']
    result = {'question': question, 'complete': False, 'answer': None, 'citations': [],
              'error': None, 'seconds': None, 'mode': 'two-step', 'steps': {},
              'model': 'Qwen2.5-1.5B-Instruct'}
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from lmformatenforcer import JsonSchemaParser
        from lmformatenforcer.integrations.transformers import build_transformers_prefix_allowed_tokens_fn

        tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR))
        model = AutoModelForCausalLM.from_pretrained(str(MODEL_DIR),
            torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
            device_map='cuda' if torch.cuda.is_available() else 'cpu')

        def generate(messages: list[dict], schema: dict, tokens: int) -> str:
            prefix = build_transformers_prefix_allowed_tokens_fn(tokenizer, JsonSchemaParser(schema))
            prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = tokenizer(prompt, return_tensors='pt').to(model.device)
            with torch.no_grad():
                out = model.generate(**inputs, max_new_tokens=tokens, do_sample=False, prefix_allowed_tokens_fn=prefix)
            return tokenizer.decode(out[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True)

        user_picks = spec.get('picks') or None
        result['steps']['user_picked'] = bool(user_picks)
        if user_picks:
            resolved, error = resolve(papers, user_picks)
            if error:
                result['error'] = error
            else:
                result['mode'] = 'answer-only'
                result['steps']['picks'] = user_picks
                raw_answer = generate(answer_messages(question, resolved), answer_schema(), 200)
                result['steps']['answer_raw'] = raw_answer
                answer, error = validate_answer(json.loads(raw_answer))
                if error:
                    result['error'] = error
                else:
                    result.update(complete=True, answer=answer, citations=resolved)
        else:
            raw_select = generate(select_messages(question, papers), select_schema(papers), 64)
            result['steps']['select_raw'] = raw_select
            selection = json.loads(raw_select)
            picks = selection.get('picks') or []
            insufficient = bool(selection.get('insufficient'))
            result['steps']['picks'] = picks
            result['steps']['insufficient'] = insufficient

            if insufficient or not picks:
                if not insufficient:
                    result['error'] = 'Selection returned no picks without marking insufficient'
                else:
                    result.update(complete=True, answer=REFUSAL, citations=[], refusal=True)
            else:
                resolved, error = resolve(papers, picks)
                if error:
                    result['error'] = error
                else:
                    raw_answer = generate(answer_messages(question, resolved), answer_schema(), 200)
                    result['steps']['answer_raw'] = raw_answer
                    answer, error = validate_answer(json.loads(raw_answer))
                    if error:
                        result['error'] = error
                    else:
                        result.update(complete=True, answer=answer, citations=resolved)
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
    result['seconds'] = round(time.perf_counter() - started, 2)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
