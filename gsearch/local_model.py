"""Small adapter for Qwen native tool tags; smolagents still owns execution."""
import json

from smolagents import TransformersModel
from smolagents.models import ChatMessage, get_tool_call_from_text


class LocalToolModel(TransformersModel):
    def __init__(self, *args: object, **kwargs: object):
        super().__init__(*args, **kwargs)
        self.model.generation_config.temperature = 1.0
        self.model.generation_config.top_p = 1.0
        self.model.generation_config.top_k = 50

    def make_stopping_criteria(self, stop_sequences: list[str], tokenizer: object) -> object:
        from transformers import StoppingCriteria, StoppingCriteriaList

        class StopOnMarker(StoppingCriteria):
            def __init__(self) -> None:
                self.generated = ""

            def __call__(self, input_ids: object, scores: object, **kwargs: object) -> bool:
                self.generated += tokenizer.decode(input_ids[0][-1:], skip_special_tokens=False)
                # A token may contain BOTH the marker and a trailing newline.
                return any(marker in self.generated for marker in stop_sequences)

        return StoppingCriteriaList([StopOnMarker()])

    def _prepare_completion_args(self, *args: object, **kwargs: object) -> dict:
        import torch
        result = super()._prepare_completion_args(*args, **kwargs)
        # There is exactly one unpadded conversation in TransformersModel.
        # Its parent adapter discards apply_chat_template's attention mask.
        result["attention_mask"] = torch.ones_like(result["inputs"])
        return result

    def generate(self, messages: list, stop_sequences: list[str] | None = None, **kwargs: object) -> ChatMessage:
        # Stop after ONE native call, before a small model starts inventing observations.
        stops = [*(stop_sequences or []), "</tool_call>", "</tool_call>\n"]
        response = super().generate(messages, stop_sequences=stops, **kwargs)
        if response.content:
            for stop in stop_sequences or []:
                response.content = response.content.split(stop, 1)[0]
        return response

    def parse_tool_calls(self, message: ChatMessage) -> ChatMessage:
        if message.content and "<tool_call>" in message.content:
            payload = message.content.split("<tool_call>", 1)[1].split("</tool_call>", 1)[0].strip()
            call = json.loads(payload)
            if not isinstance(call, dict) or set(call) != {"name", "arguments"}:
                raise ValueError("Expected one native tool call with name and arguments")
            message.tool_calls = [get_tool_call_from_text(json.dumps(call), "name", "arguments")]
            return message
        return super().parse_tool_calls(message)
