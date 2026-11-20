"""Unit tests for native evaluation metrics."""

import pytest
import torch

from .metrics import (
    calculate_perplexity,
    calculate_token_accuracy,
)


def test_token_accuracy_perfect_prediction():
    logits = torch.tensor(
        [[[0.1, 0.9], [0.8, 0.2]]]
    )
    labels = torch.tensor([[1, 0]])

    assert calculate_token_accuracy(logits, labels) == 1.0


def test_token_accuracy_partial_prediction():
    logits = torch.tensor(
        [[[0.1, 0.9], [0.8, 0.2]]]
    )
    labels = torch.tensor([[1, 1]])

    assert calculate_token_accuracy(logits, labels) == 0.5


def test_token_accuracy_ignores_padding():
    logits = torch.tensor(
        [[[0.1, 0.9], [0.9, 0.1]]]
    )
    labels = torch.tensor([[1, -100]])

    assert calculate_token_accuracy(logits, labels) == 1.0


def test_perplexity_is_finite_for_valid_logits():
    logits = torch.tensor(
        [[[0.1, 0.9], [0.8, 0.2]]]
    )
    labels = torch.tensor([[1, 0]])

    result = calculate_perplexity(logits, labels)

    assert torch.isfinite(torch.tensor(result))
    assert result >= 1.0


def test_metrics_reject_mismatched_shapes():
    logits = torch.zeros(1, 3, 4)
    labels = torch.zeros(1, 2, dtype=torch.long)

    with pytest.raises(ValueError):
        calculate_token_accuracy(logits, labels)


def test_metrics_reject_non_finite_logits():
    logits = torch.tensor(
        [[[float("nan"), 1.0]]]
    )
    labels = torch.tensor([[1]])

    with pytest.raises(ValueError):
        calculate_perplexity(logits, labels)


def test_metrics_reject_invalid_token_id():
    logits = torch.zeros(1, 2, 3)
    labels = torch.tensor([[1, 5]])

    with pytest.raises(ValueError):
        calculate_token_accuracy(logits, labels)


def test_metrics_reject_empty_valid_labels():
    logits = torch.zeros(1, 2, 3)
    labels = torch.tensor([[-100, -100]])

    with pytest.raises(ValueError):
        calculate_perplexity(logits, labels)
