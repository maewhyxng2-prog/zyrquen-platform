from dataclasses import dataclass, field
from typing import Any, Literal

JobConclusion = Literal[
    "success",
    "failure",
    "cancelled",
    "skipped",
    "timed_out",
    "action_required",
    "neutral",
    "stale",
]


@dataclass(frozen=True)
class CIJob:
    job_id: str
    name: str
    status: str
    conclusion: str
    workflow: str = ""
    logs: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectionReport:
    total_jobs: int
    failed_jobs: list[CIJob]
    ignored_jobs: list[CIJob]
