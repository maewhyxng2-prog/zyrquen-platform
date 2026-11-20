"""Native evaluation metrics for ZYRQUEN Ω∞."""

import math

import torch
import torch.nn.functional as F


def _validate_logits_and_labels(
    logits: torch.Tensor,
    labels: torch.Tensor,
    ignore_index: int = -100,
) -> tuple[torch.Tensor, torch.Tensor]:
    if not isinstance(logits, torch.Tensor):
        raise TypeError("logits must be a torch.Tensor")

    if not isinstance(labels, torch.Tensor):
        raise TypeError("labels must be a torch.Tensor")

    if logits.ndim != 3:
        raise ValueError("logits must have shape [batch, sequence, vocab]")

    if labels.ndim != 2:
        raise ValueError("labels must have shape [batch, sequence]")

    if logits.shape[:2] != labels.shape:
        raise ValueError("logits and labels dimensions do not match")

    if logits.shape[-1] <= 0:
        raise ValueError("vocabulary dimension must be positive")

    if not torch.isfinite(logits).all():
        raise ValueError("logits contain non-finite values")

    labels = labels.to(device=logits.device, dtype=torch.long)
    valid_mask = labels.ne(ignore_index)

    if not valid_mask.any():
        raise ValueError("no valid tokens available for evaluation")

    valid_labels = labels[valid_mask]

    if (valid_labels < 0).any() or (
        valid_labels >= logits.shape[-1]
    ).any():
        raise ValueError("labels contain token IDs outside vocabulary")

    return logits, labels


def calculate_token_accuracy(
    logits: torch.Tensor,
    labels: torch.Tensor,
    ignore_index: int = -100,
) -> float:
    """Calculate token-level accuracy, excluding ignored labels."""

    logits, labels = _validate_logits_and_labels(
        logits, labels, ignore_index
    )

    predictions = logits.argmax(dim=-1)
    valid_mask = labels.ne(ignore_index)

    correct = (predictions.eq(labels) & valid_mask).sum()
    total = valid_mask.sum()

    return (correct.float() / total).item()


def calculate_perplexity(
    logits: torch.Tensor,
    labels: torch.Tensor,
    ignore_index: int = -100,
) -> float:
    """Calculate token-level perplexity from model logits."""

    logits, labels = _validate_logits_and_labels(
        logits, labels, ignore_index
    )

    loss = F.cross_entropy(
        logits.float().reshape(-1, logits.shape[-1]),
        labels.reshape(-1),
        ignore_index=ignore_index,
        reduction="mean",
    )

    if not torch.isfinite(loss):
        raise ValueError("cross-entropy loss is non-finite")

    try:
        perplexity = math.exp(loss.item())
    except OverflowError:
        return float("inf")

    return perplexity
