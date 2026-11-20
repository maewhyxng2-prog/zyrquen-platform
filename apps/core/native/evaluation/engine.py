"""Evaluation orchestration for ZYRQUEN Ω∞ native models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import torch

from .metrics import (
    calculate_perplexity,
    calculate_token_accuracy,
)


@dataclass
class EvaluationResult:
    status: str
    model_version: str
    evaluated_at: str
    sample_count: int
    token_count: int
    metrics: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvaluationEngine:
    """Evaluate a native model against an explicitly supplied dataset."""

    def __init__(
        self,
        model: torch.nn.Module,
        model_version: str,
        device: str | torch.device = "cpu",
    ) -> None:
        if not isinstance(model, torch.nn.Module):
            raise TypeError("model must be a torch.nn.Module")

        if not model_version or not model_version.strip():
            raise ValueError("model_version must not be empty")

        self.model = model
        self.model_version = model_version
        self.device = torch.device(device)

    @torch.inference_mode()
    def evaluate(
        self,
        batches: list[dict[str, torch.Tensor]],
        *,
        input_key: str = "input_ids",
        label_key: str = "labels",
        ignore_index: int = -100,
        metadata: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        if not batches:
            raise ValueError("evaluation dataset is empty")

        was_training = self.model.training
        self.model.to(self.device)
        self.model.eval()

        total_correct = 0
        total_tokens = 0
        total_loss = 0.0
        sample_count = 0

        try:
            for batch in batches:
                if input_key not in batch or label_key not in batch:
                    raise ValueError(
                        f"each batch must contain {input_key!r} "
                        f"and {label_key!r}"
                    )

                input_ids = batch[input_key].to(self.device)
                labels = batch[label_key].to(
                    self.device, dtype=torch.long
                )

                output = self.model(input_ids)

                logits = (
                    output.logits
                    if hasattr(output, "logits")
                    else output
                )

                if not isinstance(logits, torch.Tensor):
                    raise TypeError("model output must contain logits")

                if logits.shape[:2] != labels.shape:
                    raise ValueError(
                        "model logits and labels must have matching "
                        "batch and sequence dimensions"
                    )

                valid_mask = labels.ne(ignore_index)
                token_count = int(valid_mask.sum().item())

                if token_count == 0:
                    continue

                accuracy = calculate_token_accuracy(
                    logits, labels, ignore_index
                )
                perplexity = calculate_perplexity(
                    logits, labels, ignore_index
                )

                batch_loss = torch.nn.functional.cross_entropy(
                    logits.float().reshape(-1, logits.shape[-1]),
                    labels.reshape(-1),
                    ignore_index=ignore_index,
                    reduction="sum",
                ).item()

                total_correct += round(accuracy * token_count)
                total_tokens += token_count

                if perplexity != float("inf"):
                    total_loss += batch_loss
                else:
                    total_loss = float("inf")

                sample_count += int(input_ids.shape[0])

            if total_tokens == 0:
                raise ValueError(
                    "evaluation dataset contains no valid tokens"
                )

            mean_loss = total_loss / total_tokens
            perplexity = (
                float("inf")
                if mean_loss == float("inf")
                else float(torch.exp(torch.tensor(mean_loss)).item())
            )

            return EvaluationResult(
                status="completed",
                model_version=self.model_version,
                evaluated_at=datetime.now(timezone.utc).isoformat(),
                sample_count=sample_count,
                token_count=total_tokens,
                metrics={
                    "token_accuracy": total_correct / total_tokens,
                    "perplexity": perplexity,
                    "cross_entropy": mean_loss,
                },
                metadata=metadata or {},
            )

        finally:
            self.model.train(was_training)
