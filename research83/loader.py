"""Load the comparison model with the exact construction used for the 1.5B baseline.

`gsearch.unified_agent.load_model` hardcodes the 1.5B path. This module repeats the
same four lines with a parameterised path so no frozen module is edited.
"""
import torch
from gsearch.budget_model import BudgetedToolModel
from gsearch.qwen_messages import native_history


class NativeQwenToolModel(BudgetedToolModel):
    def _prepare_completion_args(self, messages: list, *args: object, **kwargs: object) -> dict:
        kwargs['custom_role_conversions'] = {'tool-call': 'assistant', 'tool-response': 'tool'}
        return super()._prepare_completion_args(native_history(messages), *args, **kwargs)


def load_model(model_id: str) -> object:
    torch.set_num_threads(4)
    return NativeQwenToolModel(model_id=model_id,
        device_map='cuda' if torch.cuda.is_available() else 'cpu',
        torch_dtype='bfloat16' if torch.cuda.is_available() else 'float32',
        model_kwargs={'local_files_only': True}, do_sample=False, max_new_tokens=160)
