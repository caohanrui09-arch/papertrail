"""Stage88: grammar-constrained decoding for the native tool-call envelope.

The state machine already knows which tools are legal and what their arguments look
like. We publish that as a JSON schema and let lm-format-enforcer (MIT) mask the
logits so the model can only produce a valid `{"name": ..., "arguments": {...}}`.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPS = ROOT / '.cache/decoder-deps'
if str(DEPS) not in sys.path:
    sys.path.insert(0, str(DEPS))

from gsearch.budget_model import BudgetedToolModel
from gsearch.qwen_messages import native_history
from gsearch.schema_isolation import IsolatedActionState

ARGUMENT_SCHEMAS = {
    'search_papers': {'type': 'object',
        'properties': {'query': {'type': 'string'}, 'k': {'type': 'integer', 'minimum': 1, 'maximum': 3}},
        'required': ['query', 'k'], 'additionalProperties': False},
    'recommend_papers': {'type': 'object',
        'properties': {'k': {'type': 'integer', 'minimum': 1, 'maximum': 3}},
        'required': ['k'], 'additionalProperties': False},
    'read_paper': {'type': 'object',
        'properties': {'doc_id': {'type': 'string'}},
        'required': ['doc_id'], 'additionalProperties': False},
}

STATE = {'schema': None}


def build_schema(allowed: list[str], answer_schema: dict) -> dict | None:
    if not allowed:
        return None
    shapes = []
    for name in allowed:
        if name == 'final_answer':
            shapes.append({'type': 'object', 'properties': {'answer': answer_schema},
                           'required': ['answer'], 'additionalProperties': False})
        else:
            shapes.append(ARGUMENT_SCHEMAS[name])
    arguments = shapes[0] if len(shapes) == 1 else {'anyOf': shapes}
    return {'type': 'object',
            'properties': {'name': {'enum': list(allowed)}, 'arguments': arguments},
            'required': ['name', 'arguments'], 'additionalProperties': False}


class ConstrainedActionState(IsolatedActionState):
    """Publishes the current decoding schema on every refresh."""

    def refresh(self, agent: object, all_tools: dict) -> None:
        super().refresh(agent, all_tools)
        STATE['schema'] = build_schema(self.legal(), all_tools['final_answer'].inputs['answer'])


class ConstrainedToolModel(BudgetedToolModel):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._prefix_cache: dict[str, object] = {}

    def _prepare_completion_args(self, messages: list, *args: object, **kwargs: object) -> dict:
        kwargs['custom_role_conversions'] = {'tool-call': 'assistant', 'tool-response': 'tool'}
        prepared = super()._prepare_completion_args(native_history(messages), *args, **kwargs)
        prepared.pop('prefix_allowed_tokens_fn', None)
        schema = STATE.get('schema')
        if not schema:
            return prepared
        key = json.dumps(schema, sort_keys=True)
        if key not in self._prefix_cache:
            try:
                from lmformatenforcer import JsonSchemaParser
                from lmformatenforcer.integrations.transformers import build_transformers_prefix_allowed_tokens_fn
                parser = JsonSchemaParser(schema)
                self._prefix_cache[key] = build_transformers_prefix_allowed_tokens_fn(self.tokenizer, parser)
            except Exception as error:  # unsupported schema shape -> keep the run honest
                print('constraint fallback:', type(error).__name__, str(error)[:140], flush=True)
                self._prefix_cache[key] = None
        prefix = self._prefix_cache[key]
        if prefix is not None:
            prepared['prefix_allowed_tokens_fn'] = prefix
        return prepared

    def generate(self, *args: object, **kwargs: object) -> object:
        response = super().generate(*args, **kwargs)
        # The prefix function is not JSON-serialisable and can be cyclic; strip it from
        # the retained raw completion metadata so step logs stay serialisable.
        raw = getattr(response, 'raw', None)
        if isinstance(raw, dict):
            raw.pop('prefix_allowed_tokens_fn', None)
            completion = raw.get('completion_kwargs')
            if isinstance(completion, dict):
                completion.pop('prefix_allowed_tokens_fn', None)
        return response


def load_model(model_id: str) -> object:
    import torch
    torch.set_num_threads(4)
    return ConstrainedToolModel(model_id=model_id,
        device_map='cuda' if torch.cuda.is_available() else 'cpu',
        torch_dtype='bfloat16' if torch.cuda.is_available() else 'float32',
        model_kwargs={'local_files_only': True}, do_sample=False, max_new_tokens=160)
