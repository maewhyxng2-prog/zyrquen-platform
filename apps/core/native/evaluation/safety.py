"""Curated safety evaluation for ZYRQUEN Ω∞."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class SafetyCase:
    case_id: str
    prompt: str
    expected_behavior: str
    category: str


class SafetyEvaluator:
    """Evaluate model outputs against explicitly curated safety cases.

    This evaluator checks expected behavior labels supplied by a
    trusted test author. It does not independently establish whether
    a model response is safe.
    """

    VALID_BEHAVIORS = {
        "refuse",
        "comply",
        "safe_redirect",
        "human_review",
    }

    def __init__(self, cases: list[SafetyCase]) -> None:
        if not cases:
            raise ValueError("safety cases must not be empty")

        identifiers = [case.case_id for case in cases]

        if len(identifiers) != len(set(identifiers)):
            raise ValueError("safety case IDs must be unique")

        for case in cases:
            if not case.case_id.strip():
                raise ValueError("case_id must not be empty")

            if case.expected_behavior not in self.VALID_BEHAVIORS:
                raise ValueError(
                    f"unsupported expected behavior: "
                    f"{case.expected_behavior}"
                )

            if not case.prompt.strip():
                raise ValueError("safety prompt must not be empty")

        self.cases = cases

    def evaluate(
        self,
        response_fn: Callable[[str], str],
        judge_fn: Callable[[SafetyCase, str], str],
    ) -> dict[str, Any]:
        """Run curated cases and classify outputs using a supplied judge.

        judge_fn must return one of VALID_BEHAVIORS or 'inconclusive'.
        Human review is required for inconclusive cases.
        """

        if not callable(response_fn) or not callable(judge_fn):
            raise TypeError("response_fn and judge_fn must be callable")

        results = []
        passed = 0
        failed = 0
        inconclusive = 0

        for case in self.cases:
            try:
                response = response_fn(case.prompt)

                if not isinstance(response, str):
                    raise TypeError("model response must be a string")

                observed = judge_fn(case, response)

                if observed not in self.VALID_BEHAVIORS | {"inconclusive"}:
                    raise ValueError("judge returned an unsupported label")

                if observed == "inconclusive":
                    status = "human_review"
                    inconclusive += 1
                elif observed == case.expected_behavior:
                    status = "passed"
                    passed += 1
                else:
                    status = "failed"
                    failed += 1

                results.append(
                    {
                        "case_id": case.case_id,
                        "category": case.category,
                        "expected_behavior": case.expected_behavior,
                        "observed_behavior": observed,
                        "status": status,
                    }
                )

            except Exception as exc:
                inconclusive += 1
                results.append(
                    {
                        "case_id": case.case_id,
                        "category": case.category,
                        "status": "human_review",
                        "error": str(exc),
                    }
                )

        total = len(self.cases)

        return {
            "status": (
                "passed"
                if failed == 0 and inconclusive == 0
                else "review_required"
            ),
            "case_count": total,
            "passed": passed,
            "failed": failed,
            "inconclusive": inconclusive,
            "pass_rate": passed / total,
            "results": results,
            "limitations": [
                "Results depend on the supplied judge function.",
                "This is not a comprehensive safety certification.",
                "Human review is required for inconclusive cases.",
            ],
        }
