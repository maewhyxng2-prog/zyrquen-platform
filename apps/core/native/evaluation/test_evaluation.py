"""Tests for ZYRQUEN Ω∞ evaluation components."""

import pytest
import torch
from torch import nn

from .benchmark import BenchmarkCase, BenchmarkDataset
from .engine import EvaluationEngine
from .metrics import (
    calculate_perplexity,
    calculate_token_accuracy,
)
from .regression import RegressionEvaluator, RegressionThresholds
from .safety import SafetyCase, SafetyEvaluator


def test_token_accuracy():
    logits = torch.tensor(
        [[[0.1, 0.9], [0.8, 0.2]]]
    )
    labels = torch.tensor([[1, 0]])

    assert calculate_token_accuracy(logits, labels) == 1.0


def test_token_accuracy_ignores_padding():
    logits = torch.tensor(
        [[[0.1, 0.9], [0.9, 0.1]]]
    )
    labels = torch.tensor([[1, -100]])

    assert calculate_token_accuracy(logits, labels) == 1.0


def test_perplexity_is_positive():
    logits = torch.tensor(
        [[[0.1, 0.9], [0.8, 0.2]]]
    )
    labels = torch.tensor([[1, 0]])

    result = calculate_perplexity(logits, labels)

    assert result >= 1.0


def test_metrics_reject_invalid_dimensions():
    with pytest.raises(ValueError):
        calculate_token_accuracy(
            torch.zeros(2, 3),
            torch.zeros(2, 3, dtype=torch.long),
        )


def test_metrics_reject_empty_valid_labels():
    logits = torch.zeros(1, 2, 3)
    labels = torch.full((1, 2), -100)

    with pytest.raises(ValueError):
        calculate_perplexity(logits, labels)


def test_benchmark_dataset_summary():
    dataset = BenchmarkDataset(
        [
            BenchmarkCase(
                case_id="case-001",
                input_ids=[1, 2],
                labels=[2, 3],
                language="en",
            )
        ]
    )

    summary = dataset.summary()

    assert summary["case_count"] == 1
    assert summary["languages"]["en"] == 1
    assert len(summary["sha256"]) == 64


def test_benchmark_rejects_duplicate_ids():
    case = BenchmarkCase(
        case_id="duplicate",
        input_ids=[1],
        labels=[2],
    )

    with pytest.raises(ValueError):
        BenchmarkDataset([case, case])


def test_regression_passes_when_metrics_improve():
    evaluator = RegressionEvaluator()

    result = evaluator.compare(
        {
            "perplexity": 2.0,
            "token_accuracy": 0.80,
        },
        {
            "perplexity": 1.9,
            "token_accuracy": 0.82,
        },
    )

    assert result["passed"] is True
    assert result["status"] == "passed"


def test_regression_detects_accuracy_drop():
    evaluator = RegressionEvaluator(
        RegressionThresholds(max_accuracy_drop=0.01)
    )

    result = evaluator.compare(
        {
            "perplexity": 2.0,
            "token_accuracy": 0.90,
        },
        {
            "perplexity": 2.0,
            "token_accuracy": 0.85,
        },
    )

    assert result["passed"] is False
    assert result["status"] == "regression_detected"


def test_safety_evaluator_passes_matching_behavior():
    cases = [
        SafetyCase(
            case_id="safety-001",
            prompt="Test prompt",
            expected_behavior="refuse",
            category="test",
        )
    ]

    evaluator = SafetyEvaluator(cases)

    result = evaluator.evaluate(
        response_fn=lambda prompt: "I cannot help with that.",
        judge_fn=lambda case, response: "refuse",
    )

    assert result["status"] == "passed"
    assert result["passed"] == 1


class DummyModel(nn.Module):
    def forward(self, input_ids):
        batch, sequence = input_ids.shape
        logits = torch.zeros(batch, sequence, 4)
        logits.scatter_(
            2,
            input_ids.unsqueeze(-1),
            5.0,
        )
        return logits


def test_evaluation_engine_runs():
    model = DummyModel()

    engine = EvaluationEngine(
        model=model,
        model_version="test-v1",
    )

    batches = [
        {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "labels": torch.tensor([[1, 2, 3]]),
        }
    ]

    result = engine.evaluate(batches)

    assert result.status == "completed"
    assert result.sample_count == 1
    assert result.token_count == 3
    assert result.metrics["token_accuracy"] == 1.0
    assert result.metrics["perplexity"] >= 1.0


def test_evaluation_engine_rejects_empty_dataset():
    engine = EvaluationEngine(
        model=DummyModel(),
        model_version="test-v1",
    )

    with pytest.raises(ValueError):
        engine.evaluate([])
