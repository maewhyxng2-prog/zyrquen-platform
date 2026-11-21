import math
from typing import Sequence


def calculate_perplexity(loss: float) -> float:
    if isinstance(loss, bool) or not isinstance(loss, (int, float)):
        raise ValueError("loss must be a finite non-negative number")
    loss_value = float(loss)
    if not math.isfinite(loss_value) or loss_value < 0.0:
        raise ValueError("loss must be a finite non-negative number")
    return math.exp(min(loss_value, 50.0))


def calculate_token_accuracy(preds: Sequence[int], targets: Sequence[int]) -> float:
    if not targets or len(preds) != len(targets):
        raise ValueError("preds and targets must be non-empty and of equal length")
    matches = sum(1 for pred, target in zip(preds, targets) if pred == target)
    return matches / len(targets)

