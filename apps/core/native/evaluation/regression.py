"""Model regression comparison for ZYRQUEN Ω∞."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RegressionThresholds:
    max_perplexity_increase: float = 0.05
    max_accuracy_drop: float = 0.01


class RegressionEvaluator:
    """Compare current evaluation metrics with a trusted baseline."""

    def __init__(
        self,
        thresholds: RegressionThresholds | None = None,
    ) -> None:
        self.thresholds = thresholds or RegressionThresholds()

        if self.thresholds.max_perplexity_increase < 0:
            raise ValueError("max_perplexity_increase must be non-negative")

        if not 0 <= self.thresholds.max_accuracy_drop <= 1:
            raise ValueError("max_accuracy_drop must be between 0 and 1")

    def compare(
        self,
        baseline: dict[str, Any],
        current: dict[str, Any],
    ) -> dict[str, Any]:
        """Return regression status and metric-by-metric comparisons."""

        required = ("perplexity", "token_accuracy")

        for name, report in (
            ("baseline", baseline),
            ("current", current),
        ):
            if not isinstance(report, dict):
                raise TypeError(f"{name} must be a dictionary")

            metrics = report.get("metrics", report)

            if not isinstance(metrics, dict):
                raise ValueError(f"{name} metrics must be a dictionary")

            for metric in required:
                value = metrics.get(metric)

                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or value < 0
                    or value == float("inf")
                    or value != value
                ):
                    raise ValueError(
                        f"{name} has an invalid {metric} value"
                    )

        baseline_metrics = baseline.get("metrics", baseline)
        current_metrics = current.get("metrics", current)

        baseline_ppl = float(baseline_metrics["perplexity"])
        current_ppl = float(current_metrics["perplexity"])

        baseline_accuracy = float(
            baseline_metrics["token_accuracy"]
        )
        current_accuracy = float(
            current_metrics["token_accuracy"]
        )

        if baseline_ppl <= 0 or current_ppl <= 0:
            raise ValueError("perplexity must be greater than zero")

        if not 0 <= baseline_accuracy <= 1:
            raise ValueError("baseline token_accuracy must be between 0 and 1")

        if not 0 <= current_accuracy <= 1:
            raise ValueError("current token_accuracy must be between 0 and 1")

        ppl_increase = (
            (current_ppl - baseline_ppl) / baseline_ppl
        )

        accuracy_drop = baseline_accuracy - current_accuracy

        checks = {
            "perplexity": {
                "baseline": baseline_ppl,
                "current": current_ppl,
                "relative_increase": ppl_increase,
                "passed": (
                    ppl_increase
                    <= self.thresholds.max_perplexity_increase
                ),
            },
            "token_accuracy": {
                "baseline": baseline_accuracy,
                "current": current_accuracy,
                "absolute_drop": accuracy_drop,
                "passed": (
                    accuracy_drop
                    <= self.thresholds.max_accuracy_drop
                ),
            },
        }

        passed = all(item["passed"] for item in checks.values())

        return {
            "status": "passed" if passed else "regression_detected",
            "passed": passed,
            "checks": checks,
            "thresholds": {
                "max_perplexity_increase": (
                    self.thresholds.max_perplexity_increase
                ),
                "max_accuracy_drop": (
                    self.thresholds.max_accuracy_drop
                ),
            },
      }
