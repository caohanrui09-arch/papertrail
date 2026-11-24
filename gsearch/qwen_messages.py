"""Format already parsed smolagents history for Qwen's native chat template.

No observations, tool calls or repairs are generated here. The framework still
owns execution. Invalid model JSON is kept unchanged and fails native parsing.
"""
from copy import deepcopy
import json


def native_history(messages: list) -> list[dict]:
    outputs = []
    for message in messages:
        item = deepcopy(message if isinstance(message, dict) else message.dict())
        role = item['role']
        if role == 'tool-call':
            # smolagents also emits a synthetic "Calling tools: [...]" message;
            # the immediately preceding assistant content already holds that call.
            continue
        content = item.get('content')
        text = content if isinstance(content, str) else '\n'.join(
            block['text'] for block in content or [] if block.get('type') == 'text')
        if role == 'assistant':
            payload = text.strip()
            if payload.startswith('<tool_call>'):
                payload = payload[len('<tool_call>'):].split('</tool_call>', 1)[0].strip()
            try:
                call = json.loads(payload)
            except (ValueError, TypeError):
                call = None
            if isinstance(call, dict) and set(call) == {'name', 'arguments'}:
                # Transformers stops before returning the closing marker. Supply
                # its delimiter in HISTORY only; do not alter generation/output.
                item['content'] = [{'type': 'text', 'text': '<tool_call>\n' + json.dumps(call, ensure_ascii=False) + '\n</tool_call>'}]
        elif role == 'tool-response':
            if text.startswith('Observation:\n'):
                text = text[len('Observation:\n'):]
            item['content'] = [{'type': 'text', 'text': text}]
        outputs.append(item)
    return outputs
