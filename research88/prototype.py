"""Prototype: force the tool-call JSON envelope with lm-format-enforcer.

Runs Qwen2.5-0.5B on CPU for a few tokens and checks that the output is a single
JSON object with `name` and `arguments`, never a bare `{"citations": ...}`.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.cache/decoder-deps'))

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from lmformatenforcer import JsonSchemaParser
from lmformatenforcer.integrations.transformers import build_transformers_prefix_allowed_tokens_fn

MODEL = ROOT / '.cache/models/Qwen2.5-0.5B-Instruct'
SCHEMA = {
    'type': 'object',
    'properties': {
        'name': {'enum': ['final_answer']},
        'arguments': {
            'type': 'object',
            'properties': {'answer': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}},
            'required': ['answer'],
            'additionalProperties': False,
        },
    },
    'required': ['name', 'arguments'],
    'additionalProperties': False,
}


def main() -> None:
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL))
    model = AutoModelForCausalLM.from_pretrained(str(MODEL), torch_dtype=torch.float32)
    parser = JsonSchemaParser(SCHEMA)
    prefix = build_transformers_prefix_allowed_tokens_fn(tokenizer, parser)
    messages = [
        {'role': 'system', 'content': 'You are a tool-calling agent. Output exactly one JSON tool call with keys name and arguments.'},
        {'role': 'user', 'content': 'No papers were returned. Finish the task.'},
    ]
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors='pt')
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=40, do_sample=False, prefix_allowed_tokens_fn=prefix)
    text = tokenizer.decode(out[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True)
    print('RAW:', repr(text))
    try:
        value = json.loads(text)
        print('PARSED:', value)
        print('ENVELOPE_OK:', set(value) == {'name', 'arguments'})
    except ValueError as error:
        print('NOT_JSON:', error)


if __name__ == '__main__':
    main()
