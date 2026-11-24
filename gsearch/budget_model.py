"""Hard cumulative local-generation budgets, including retries and fallback calls."""
from dataclasses import dataclass

from .bundle_session import BundleBudget
from .local_model import LocalToolModel


@dataclass
class GenerationMeter:
    budget: BundleBudget
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    denied_calls: int = 0

    def reserve_input(self, tokens: int) -> int:
        if (self.calls >= self.budget.max_steps or self.input_tokens + tokens > self.budget.input_tokens
                or self.output_tokens >= self.budget.output_tokens):
            self.denied_calls += 1
            raise ValueError("Cumulative LLM input/output/call budget exhausted")
        self.calls += 1
        self.input_tokens += tokens
        return min(160, self.budget.output_tokens - self.output_tokens)

    def record_output(self, tokens: int) -> None:
        if tokens < 0 or self.output_tokens + tokens > self.budget.output_tokens:
            raise ValueError("Generator exceeded its reserved output-token budget")
        self.output_tokens += tokens


class BudgetedToolModel(LocalToolModel):
    def reset_budget(self, budget: BundleBudget) -> None:
        self.meter = GenerationMeter(budget)

    def _prepare_completion_args(self, *args: object, **kwargs: object) -> dict:
        result = super()._prepare_completion_args(*args, **kwargs)
        result["max_new_tokens"] = self.meter.reserve_input(result["inputs"].shape[1])
        return result

    def generate(self, *args: object, **kwargs: object) -> object:
        response = super().generate(*args, **kwargs)
        self.meter.record_output(response.token_usage.output_tokens)
        return response
