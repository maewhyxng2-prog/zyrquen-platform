"""Experience Analyzer for ZYRQUEN Adaptive Experience-driven Learning (AEL).

Analyzes ONLY real sandbox execution evidence stored in ExperienceStore
(never touches loss-only metrics or held-out tasks) and produces per-family
and global signals for AdaptiveLearningController.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from zyrquen_ael_experiment.experience_store import (
    ERROR_TYPES,
    ExperienceStore,
    SandboxExperienceRecord,
)


@dataclass(frozen=True)
class FamilySignal:
    task_family: str
    sample_count: int
    first_pass_rate: float
    final_pass_rate: float
    recovered_pass_rate: float
    persistent_fail_rate: float
    prior_mean_final_pass: float
    peak_final_pass: float
    regression_score: float  # positive means drop vs prior/peak
    regressing: bool
    saturated: bool
    retry_yield: float
    retries_spent: int
    syntax_error_rate: float
    error_breakdown: Dict[str, int]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExperienceAnalysis:
    round_idx: int
    total_records: int
    overall_first_pass_rate: float
    overall_final_pass_rate: float
    overall_recovered_rate: float
    overall_persistent_fail_rate: float
    overall_retry_yield: float
    syntax_error_rate: float
    overall_error_breakdown: Dict[str, int]
    regressing_families: List[str] = field(default_factory=list)
    weak_families: List[str] = field(default_factory=list)
    saturated_families: List[str] = field(default_factory=list)
    family_signals: Dict[str, FamilySignal] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "round_idx": self.round_idx,
            "total_records": self.total_records,
            "overall_first_pass_rate": self.overall_first_pass_rate,
            "overall_final_pass_rate": self.overall_final_pass_rate,
            "overall_recovered_rate": self.overall_recovered_rate,
            "overall_persistent_fail_rate": self.overall_persistent_fail_rate,
            "overall_retry_yield": self.overall_retry_yield,
            "syntax_error_rate": self.syntax_error_rate,
            "overall_error_breakdown": dict(self.overall_error_breakdown),
            "regressing_families": list(self.regressing_families),
            "weak_families": list(self.weak_families),
            "saturated_families": list(self.saturated_families),
            "family_signals": {k: v.to_dict() for k, v in self.family_signals.items()},
        }


class ExperienceAnalyzer:
    """Computes evidence-based execution, regression, and retry-yield signals."""

    def __init__(
        self,
        *,
        regression_drop_threshold: float = 0.05,
        saturation_threshold: float = 0.85,
        weak_threshold: float = 0.40,
    ) -> None:
        self.regression_drop_threshold = float(regression_drop_threshold)
        self.saturation_threshold = float(saturation_threshold)
        self.weak_threshold = float(weak_threshold)

    def analyze(self, store: ExperienceStore, round_idx: int | None = None) -> ExperienceAnalysis:
        target_round = round_idx if round_idx is not None else store.latest_round_index()
        if target_round is None:
            return ExperienceAnalysis(
                round_idx=0,
                total_records=0,
                overall_first_pass_rate=0.0,
                overall_final_pass_rate=0.0,
                overall_recovered_rate=0.0,
                overall_persistent_fail_rate=0.0,
                overall_retry_yield=0.0,
                syntax_error_rate=0.0,
                overall_error_breakdown={k: 0 for k in ERROR_TYPES},
            )

        current_records: List[SandboxExperienceRecord] = store.round_records(target_round)
        for rec in current_records:
            ExperienceStore.validate_feedback_split(rec.split)

        if not current_records:
            return ExperienceAnalysis(
                round_idx=int(target_round),
                total_records=0,
                overall_first_pass_rate=0.0,
                overall_final_pass_rate=0.0,
                overall_recovered_rate=0.0,
                overall_persistent_fail_rate=0.0,
                overall_retry_yield=0.0,
                syntax_error_rate=0.0,
                overall_error_breakdown={k: 0 for k in ERROR_TYPES},
            )

        family_stats = store.build_family_stats()
        by_family: Dict[str, List[SandboxExperienceRecord]] = {}
        for rec in current_records:
            by_family.setdefault(rec.task_family, []).append(rec)

        family_signals: Dict[str, FamilySignal] = {}
        regressing_families: List[str] = []
        weak_families: List[str] = []
        saturated_families: List[str] = []

        for fam, items in sorted(by_family.items()):
            n = len(items)
            first_ok = sum(1 for x in items if x.first_attempt_passed)
            final_ok = sum(1 for x in items if x.passed)
            recov = sum(1 for x in items if x.recovered_on_retry)
            pfail = sum(1 for x in items if not x.passed)
            retries_spent = sum(x.retries_used for x in items)

            first_rate = first_ok / n
            final_rate = final_ok / n
            recov_rate = recov / n
            pfail_rate = pfail / n
            retry_yield = (recov / retries_spent) if retries_spent > 0 else 0.0

            err_bd = {k: 0 for k in ERROR_TYPES}
            syntax_errs = 0
            for x in items:
                err_key = x.final_error_type if x.final_error_type in err_bd else "other"
                if x.passed:
                    err_bd["passed"] += 1
                else:
                    err_bd[err_key] += 1
                if (not x.first_attempt_passed and x.first_error_type == "SyntaxError") or (
                    not x.passed and x.final_error_type == "SyntaxError"
                ):
                    syntax_errs += 1

            st = family_stats.get(fam)
            prior_hist = st.final_pass_history[:-1] if st and len(st.final_pass_history) > 1 else []
            prior_mean = (sum(prior_hist) / len(prior_hist)) if prior_hist else final_rate
            prior_peak = max(prior_hist) if prior_hist else final_rate
            ref_baseline = max(prior_mean, prior_peak)
            regression_score = max(0.0, ref_baseline - final_rate)
            is_regressing = bool(prior_hist) and (regression_score >= self.regression_drop_threshold)

            is_saturated = (
                final_rate >= self.saturation_threshold
                and first_rate >= self.saturation_threshold
                and not is_regressing
            )
            is_weak = (final_rate <= self.weak_threshold) or (pfail_rate >= 0.5)

            if is_regressing:
                regressing_families.append(fam)
            if is_weak:
                weak_families.append(fam)
            if is_saturated:
                saturated_families.append(fam)

            family_signals[fam] = FamilySignal(
                task_family=fam,
                sample_count=n,
                first_pass_rate=round(first_rate, 4),
                final_pass_rate=round(final_rate, 4),
                recovered_pass_rate=round(recov_rate, 4),
                persistent_fail_rate=round(pfail_rate, 4),
                prior_mean_final_pass=round(prior_mean, 4),
                peak_final_pass=round(prior_peak, 4),
                regression_score=round(regression_score, 4),
                regressing=is_regressing,
                saturated=is_saturated,
                retry_yield=round(retry_yield, 4),
                retries_spent=retries_spent,
                syntax_error_rate=round(syntax_errs / n, 4),
                error_breakdown=err_bd,
            )

        total_n = len(current_records)
        tot_first = sum(1 for x in current_records if x.first_attempt_passed)
        tot_final = sum(1 for x in current_records if x.passed)
        tot_recov = sum(1 for x in current_records if x.recovered_on_retry)
        tot_pfail = sum(1 for x in current_records if not x.passed)
        tot_retries = sum(x.retries_used for x in current_records)
        tot_syntax = sum(
            1
            for x in current_records
            if (not x.first_attempt_passed and x.first_error_type == "SyntaxError")
            or (not x.passed and x.final_error_type == "SyntaxError")
        )
        overall_bd = {k: 0 for k in ERROR_TYPES}
        for x in current_records:
            if x.passed:
                overall_bd["passed"] += 1
            else:
                key = x.final_error_type if x.final_error_type in overall_bd else "other"
                overall_bd[key] += 1

        return ExperienceAnalysis(
            round_idx=int(target_round),
            total_records=total_n,
            overall_first_pass_rate=round(tot_first / total_n, 4),
            overall_final_pass_rate=round(tot_final / total_n, 4),
            overall_recovered_rate=round(tot_recov / total_n, 4),
            overall_persistent_fail_rate=round(tot_pfail / total_n, 4),
            overall_retry_yield=round((tot_recov / tot_retries) if tot_retries > 0 else 0.0, 4),
            syntax_error_rate=round(tot_syntax / total_n, 4),
            overall_error_breakdown=overall_bd,
            regressing_families=sorted(regressing_families),
            weak_families=sorted(weak_families),
            saturated_families=sorted(saturated_families),
            family_signals=family_signals,
        )
