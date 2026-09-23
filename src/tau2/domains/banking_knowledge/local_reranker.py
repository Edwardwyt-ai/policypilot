"""Local Qwen3 reranker adapter with lazy model loading."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence

import numpy as np


class PassageReranker(Protocol):
    """Minimal interface consumed by the hybrid retriever."""

    def score(self, query: str, documents: Sequence[str]) -> np.ndarray:
        """Return one relevance probability per document."""


class QwenLocalReranker:
    """Score query/passage pairs with a local Qwen3-Reranker checkpoint."""

    DEFAULT_INSTRUCTION = (
        "Given a banking policy query, rank passages that directly answer it "
        "and satisfy every explicit constraint."
    )
    _PREFIX = (
        "<|im_start|>system\nJudge whether the Document meets the requirements "
        "based on the Query and the Instruct provided. Note that the answer can "
        "only be \"yes\" or \"no\".<|im_end|>\n"
        "<|im_start|>user\n"
    )
    _SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"

    def __init__(
        self,
        model_path: Path,
        *,
        instruction: str = DEFAULT_INSTRUCTION,
        max_length: int = 1536,
        batch_size: int = 2,
        device: str | None = None,
    ) -> None:
        self.model_path = Path(model_path)
        self.instruction = instruction
        self.max_length = max_length
        self.batch_size = batch_size
        self.requested_device = device
        self._tokenizer = None
        self._model = None
        self._device = None
        self._yes_token_id = None
        self._no_token_id = None

    def _load(self) -> None:
        if self._model is not None:
            return
        if not self.model_path.exists():
            raise FileNotFoundError(f"Reranker model not found: {self.model_path}")

        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        device = self.requested_device or ("cuda" if torch.cuda.is_available() else "cpu")
        dtype = torch.float16 if device.startswith("cuda") else torch.float32
        tokenizer = AutoTokenizer.from_pretrained(
            self.model_path, padding_side="left", local_files_only=True
        )
        model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            dtype=dtype,
            local_files_only=True,
        ).to(device)
        model.eval()

        self._tokenizer = tokenizer
        self._model = model
        self._device = device
        self._yes_token_id = tokenizer.convert_tokens_to_ids("yes")
        self._no_token_id = tokenizer.convert_tokens_to_ids("no")

    def _format_pair(self, query: str, document: str) -> str:
        body = (
            f"<Instruct>: {self.instruction}\n"
            f"<Query>: {query}\n"
            f"<Document>: {document}"
        )
        return f"{self._PREFIX}{body}{self._SUFFIX}"

    def score(self, query: str, documents: Sequence[str]) -> np.ndarray:
        if not documents:
            return np.empty(0, dtype=np.float32)
        self._load()

        import torch

        assert self._tokenizer is not None
        assert self._model is not None
        assert self._device is not None
        assert self._yes_token_id is not None
        assert self._no_token_id is not None

        scores: list[float] = []
        formatted = [self._format_pair(query, document) for document in documents]
        with torch.inference_mode():
            for start in range(0, len(formatted), self.batch_size):
                encoded = self._tokenizer(
                    formatted[start : start + self.batch_size],
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                ).to(self._device)
                logits = self._model(**encoded).logits[:, -1, :]
                binary_logits = logits[
                    :, [self._no_token_id, self._yes_token_id]
                ].float()
                probabilities = torch.softmax(binary_logits, dim=-1)[:, 1]
                scores.extend(probabilities.cpu().tolist())

        result = np.asarray(scores, dtype=np.float32)
        if result.shape != (len(documents),) or not np.isfinite(result).all():
            raise ValueError("Reranker returned invalid relevance scores")
        return result
