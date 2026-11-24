"""Independent pretrained relevance and NLI scores; no claim labels at inference."""
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer


NLI_LABELS = {"contradiction": "CONTRADICT", "entailment": "SUPPORT", "neutral": "INSUFFICIENT"}


class PairClassifier:
    def __init__(self, model_path: Path, max_length: int = 256, batch_size: int = 16):
        if max_length < 32 or batch_size < 1:
            raise ValueError("Invalid classifier length/batch size")
        self.path = model_path
        self.max_length, self.batch_size = max_length, batch_size
        self.pairs_processed = 0
        self.forward_batches = 0
        self.padded_input_tokens = 0
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True, trust_remote_code=False)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = AutoModelForSequenceClassification.from_pretrained(
            model_path, local_files_only=True, trust_remote_code=False).to(self.device).eval()

    def logits(self, first: list[str], second: list[str], truncation: str = "longest_first") -> torch.Tensor:
        if len(first) != len(second):
            raise ValueError("Text pair lengths differ")
        self.pairs_processed += len(first)
        results = []
        for start in range(0, len(first), self.batch_size):
            encoded = self.tokenizer(first[start:start + self.batch_size], second[start:start + self.batch_size],
                                     padding=True, truncation=truncation, max_length=self.max_length,
                                     return_tensors="pt").to(self.device)
            self.forward_batches += 1
            self.padded_input_tokens += encoded["input_ids"].numel()
            with torch.inference_mode():
                results.append(self.model(**encoded).logits.float().cpu())
        return torch.cat(results) if results else torch.empty((0, self.model.config.num_labels))


class RelevanceModel(PairClassifier):
    def __init__(self, model_path: Path, max_length: int = 384, batch_size: int = 24):
        super().__init__(model_path, max_length, batch_size)
        if self.model.config.num_labels != 1:
            raise ValueError("Expected a single-logit relevance model")

    def score(self, query: str, passages: list[str]) -> list[float]:
        return self.logits([query] * len(passages), passages).flatten().tolist()


class NLIModel(PairClassifier):
    def __init__(self, model_path: Path, max_length: int = 256, batch_size: int = 16):
        super().__init__(model_path, max_length, batch_size)
        self.labels = []
        for index in range(self.model.config.num_labels):
            label = self.model.config.id2label[index].casefold()
            if label not in NLI_LABELS:
                raise ValueError(f"Unknown NLI label mapping: {self.model.config.id2label}")
            self.labels.append(NLI_LABELS[label])
        if set(self.labels) != set(NLI_LABELS.values()) or len(self.labels) != 3:
            raise ValueError("NLI model must have three distinct known labels")

    def probabilities(self, premises: list[str], claim: str) -> list[dict[str, float]]:
        # NLI is directional: the source text is the premise, the claim is the hypothesis.
        scores = self.logits(premises, [claim] * len(premises), truncation="only_first").softmax(dim=-1).tolist()
        return [dict(zip(self.labels, row)) for row in scores]
