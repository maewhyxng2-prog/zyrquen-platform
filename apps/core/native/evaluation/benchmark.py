"""Golden benchmark dataset handling for ZYRQUEN Ω∞."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    input_ids: list[int]
    labels: list[int]
    language: str = "unknown"
    category: str = "general"


class BenchmarkDataset:
    """Load and validate explicitly curated benchmark cases."""

    def __init__(self, cases: list[BenchmarkCase]) -> None:
        if not cases:
            raise ValueError("benchmark dataset must not be empty")

        case_ids = [case.case_id for case in cases]

        if len(case_ids) != len(set(case_ids)):
            raise ValueError("benchmark case IDs must be unique")

        self.cases = cases

    @classmethod
    def load(cls, path: str | Path) -> "BenchmarkDataset":
        dataset_path = Path(path)

        if not dataset_path.is_file():
            raise FileNotFoundError(
                f"benchmark dataset not found: {dataset_path}"
            )

        with dataset_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)

        if not isinstance(payload, dict):
            raise ValueError("benchmark root must be a JSON object")

        if payload.get("format_version") != 1:
            raise ValueError("unsupported benchmark format_version")

        raw_cases = payload.get("cases")

        if not isinstance(raw_cases, list):
            raise ValueError("benchmark cases must be a list")

        cases = []

        for item in raw_cases:
            if not isinstance(item, dict):
                raise ValueError("each benchmark case must be an object")

            case_id = item.get("case_id")
            input_ids = item.get("input_ids")
            labels = item.get("labels")

            if not isinstance(case_id, str) or not case_id.strip():
                raise ValueError("case_id must be a non-empty string")

            if not isinstance(input_ids, list) or not input_ids:
                raise ValueError(
                    f"{case_id}: input_ids must be a non-empty list"
                )

            if not isinstance(labels, list) or not labels:
                raise ValueError(
                    f"{case_id}: labels must be a non-empty list"
                )

            if len(input_ids) != len(labels):
                raise ValueError(
                    f"{case_id}: input_ids and labels lengths differ"
                )

            if any(
                not isinstance(token, int) or isinstance(token, bool)
                or token < 0
                for token in input_ids
            ):
                raise ValueError(
                    f"{case_id}: input_ids must contain non-negative integers"
                )

            if any(
                not isinstance(token, int) or isinstance(token, bool)
                or token < -100
                for token in labels
            ):
                raise ValueError(
                    f"{case_id}: labels contain invalid token IDs"
                )

            cases.append(
                BenchmarkCase(
                    case_id=case_id,
                    input_ids=input_ids,
                    labels=labels,
                    language=str(item.get("language", "unknown")),
                    category=str(item.get("category", "general")),
                )
            )

        return cls(cases)

    def sha256(self) -> str:
        """Return a deterministic digest of the benchmark cases."""

        serialized = json.dumps(
            [
                {
                    "case_id": case.case_id,
                    "input_ids": case.input_ids,
                    "labels": case.labels,
                    "language": case.language,
                    "category": case.category,
                }
                for case in self.cases
            ],
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        return hashlib.sha256(serialized).hexdigest()

    def summary(self) -> dict[str, Any]:
        languages: dict[str, int] = {}
        categories: dict[str, int] = {}

        for case in self.cases:
            languages[case.language] = (
                languages.get(case.language, 0) + 1
            )
            categories[case.category] = (
                categories.get(case.category, 0) + 1
            )

        return {
            "case_count": len(self.cases),
            "languages": languages,
            "categories": categories,
            "sha256": self.sha256(),
                       }
