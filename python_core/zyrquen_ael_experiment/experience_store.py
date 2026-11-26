"""Experience Store for ZYRQUEN Adaptive Experience-driven Learning (AEL).

Records sandbox execution evidence exclusively for train/validation splits
(fail-closed rejection if any held-out/unseen split is passed) and maintains
per-task-family trajectories for ExperienceAnalyzer.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ERROR_TYPES = (
    "passed",
    "SyntaxError",
    "NameError",
    "TypeError",
    "AssertionError",
    "timeout",
    "other",
)

FORBIDDEN_FEEDBACK_SPLITS = frozenset({"heldout", "held_out", "unseen", "test"})


@dataclass(frozen=True)
class SandboxExperienceRecord:
    round_idx: int
    split: str  # "train" | "val"
    task_id: str
    task_family: str
    first_attempt_passed: bool
    passed: bool
    recovered_on_retry: bool
    attempts_used: int
    retries_used: int
    first_error_type: str
    final_error_type: str
    info: str
    raw_output: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FamilyExperienceStats:
    task_family: str
    rounds_observed: int = 0
    total_attempts: int = 0
    first_pass_history: List[float] = field(default_factory=list)
    final_pass_history: List[float] = field(default_factory=list)
    peak_final_pass: float = 0.0
    total_recovered: int = 0
    total_retries: int = 0
    total_persistent_fail: int = 0
    error_counts: Dict[str, int] = field(
        default_factory=lambda: {k: 0 for k in ERROR_TYPES if k != "passed"}
    )


class ExperienceStore:
    """Append-only experience ledger for train and validation sandbox runs."""

    def __init__(self, persist_path: Optional[Path] = None) -> None:
        self.persist_path = Path(persist_path) if persist_path is not None else None
        self._records: List[SandboxExperienceRecord] = []
        self._by_round: Dict[int, List[SandboxExperienceRecord]] = defaultdict(list)

    @staticmethod
    def validate_feedback_split(split: str) -> str:
        norm = str(split or "").strip().lower()
        if norm in FORBIDDEN_FEEDBACK_SPLITS or norm not in {"train", "val", "validation"}:
            raise ValueError(
                f"BLOCKED: AEL ExperienceStore cannot ingest split={split!r}; "
                "only 'train' and 'val' are permitted (held-out isolation enforced)."
            )
        return "val" if norm == "validation" else norm

    def add_round_records(
        self,
        round_idx: int,
        records: Iterable[SandboxExperienceRecord],
    ) -> int:
        added = 0
        for rec in records:
            clean_split = self.validate_feedback_split(rec.split)
            clean_rec = SandboxExperienceRecord(
                round_idx=int(round_idx),
                split=clean_split,
                task_id=rec.task_id,
                task_family=rec.task_family,
                first_attempt_passed=bool(rec.first_attempt_passed),
                passed=bool(rec.passed),
                recovered_on_retry=bool(rec.recovered_on_retry),
                attempts_used=int(rec.attempts_used),
                retries_used=int(rec.retries_used),
                first_error_type=str(rec.first_error_type),
                final_error_type=str(rec.final_error_type),
                info=str(rec.info),
                raw_output=str(rec.raw_output),
            )
            self._records.append(clean_rec)
            self._by_round[int(round_idx)].append(clean_rec)
            added += 1

        if self.persist_path is not None:
            self.save(self.persist_path)
        return added

    def all_records(self) -> List[SandboxExperienceRecord]:
        return list(self._records)

    def round_records(self, round_idx: int) -> List[SandboxExperienceRecord]:
        return list(self._by_round.get(int(round_idx), []))

    def latest_round_index(self) -> Optional[int]:
        if not self._by_round:
            return None
        return max(self._by_round.keys())

    def build_family_stats(self) -> Dict[str, FamilyExperienceStats]:
        stats_map: Dict[str, FamilyExperienceStats] = {}
        for r_idx in sorted(self._by_round.keys()):
            round_recs = self._by_round[r_idx]
            per_fam: Dict[str, List[SandboxExperienceRecord]] = defaultdict(list)
            for rec in round_recs:
                per_fam[rec.task_family].append(rec)

            for fam, items in per_fam.items():
                st = stats_map.get(fam)
                if st is None:
                    st = FamilyExperienceStats(task_family=fam)
                    stats_map[fam] = st

                n = len(items)
                first_ok = sum(1 for x in items if x.first_attempt_passed)
                final_ok = sum(1 for x in items if x.passed)
                recov = sum(1 for x in items if x.recovered_on_retry)
                retries = sum(x.retries_used for x in items)
                pfail = sum(1 for x in items if not x.passed)

                first_rate = first_ok / n if n else 0.0
                final_rate = final_ok / n if n else 0.0

                st.rounds_observed += 1
                st.total_attempts += n
                st.first_pass_history.append(round(first_rate, 4))
                st.final_pass_history.append(round(final_rate, 4))
                if final_rate > st.peak_final_pass:
                    st.peak_final_pass = round(final_rate, 4)
                st.total_recovered += recov
                st.total_retries += retries
                st.total_persistent_fail += pfail
                for item in items:
                    if not item.passed and item.final_error_type in st.error_counts:
                        st.error_counts[item.final_error_type] += 1
                    elif not item.first_attempt_passed and item.first_error_type in st.error_counts:
                        st.error_counts[item.first_error_type] += 1

        return stats_map

    def save(self, path: Optional[Path] = None) -> Path:
        target = Path(path) if path is not None else self.persist_path
        if target is None:
            raise ValueError("No persist_path provided for ExperienceStore.save()")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "total_records": len(self._records),
            "rounds": sorted(self._by_round.keys()),
            "records": [r.to_dict() for r in self._records],
        }
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return target
