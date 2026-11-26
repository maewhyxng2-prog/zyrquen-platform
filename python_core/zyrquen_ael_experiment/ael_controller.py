"""Adaptive Learning Controller for ZYRQUEN AEL Experiment.

Controls the 5 adaptation levers strictly within safety bounds using evidence
from ExperienceAnalyzer (never loss-only tuning, never held-out inspection),
recording every before -> after transition, reason_code, and supporting evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Sequence

from zyrquen_ael_experiment.experience_analyzer import ExperienceAnalysis


REPLAY_RATIO_BOUNDS = (0.10, 0.80)
CONSOLIDATION_LAMBDA_BOUNDS = (0.001, 0.05)
RETRY_PRIORITY_BOUNDS = (0.0, 1.0)
LR_SCALE_BOUNDS = (0.50, 1.25)


def _clamp(val: float, bounds: tuple[float, float]) -> float:
    return max(bounds[0], min(bounds[1], float(val)))


@dataclass(frozen=True)
class AdjustmentRecord:
    round_idx: int
    variable: str
    before: Any
    after: Any
    reason_code: str
    evidence: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AELControlState:
    replay_ratio: float = 0.35
    consolidation_lambda: float = 0.01
    task_priority: Dict[str, float] = field(default_factory=dict)
    retry_priority: float = 0.70
    learning_rate_scale: float = 1.00

    def to_dict(self) -> Dict[str, Any]:
        return {
            "replay_ratio": round(self.replay_ratio, 4),
            "consolidation_lambda": round(self.consolidation_lambda, 6),
            "task_priority": {k: round(v, 4) for k, v in sorted(self.task_priority.items())},
            "retry_priority": round(self.retry_priority, 4),
            "learning_rate_scale": round(self.learning_rate_scale, 4),
        }


class AdaptiveLearningController:
    """Evidence-driven adaptive controller with bounded parameters and audit trail."""

    def __init__(
        self,
        families: Sequence[str],
        *,
        initial_replay_ratio: float = 0.35,
        initial_consolidation_lambda: float = 0.01,
        initial_retry_priority: float = 0.70,
        initial_lr_scale: float = 1.00,
    ) -> None:
        uniq = sorted({str(f) for f in families if str(f).strip()})
        uniform = (1.0 / len(uniq)) if uniq else 1.0
        init_prio = {f: round(uniform, 6) for f in uniq}
        if uniq:
            # Normalize exact sum == 1.0
            total = sum(init_prio.values())
            init_prio = {k: v / total for k, v in init_prio.items()}

        self.state = AELControlState(
            replay_ratio=_clamp(initial_replay_ratio, REPLAY_RATIO_BOUNDS),
            consolidation_lambda=_clamp(initial_consolidation_lambda, CONSOLIDATION_LAMBDA_BOUNDS),
            task_priority=init_prio,
            retry_priority=_clamp(initial_retry_priority, RETRY_PRIORITY_BOUNDS),
            learning_rate_scale=_clamp(initial_lr_scale, LR_SCALE_BOUNDS),
        )
        self.history: List[AdjustmentRecord] = []

    def update(self, analysis: ExperienceAnalysis) -> List[AdjustmentRecord]:
        if analysis.total_records <= 0:
            return []

        round_idx = int(analysis.round_idx)
        round_changes: List[AdjustmentRecord] = []

        # 1. replay_ratio [0.10, 0.80]
        old_replay = round(self.state.replay_ratio, 4)
        if analysis.regressing_families:
            severity = min(0.20, 0.08 + 0.05 * len(analysis.regressing_families))
            new_replay = _clamp(old_replay + severity, REPLAY_RATIO_BOUNDS)
            replay_reason = "REPLAY_INCREASE_ON_FAMILY_REGRESSION"
        elif analysis.weak_families and not analysis.regressing_families:
            new_replay = _clamp(old_replay - 0.05, REPLAY_RATIO_BOUNDS)
            replay_reason = "REPLAY_RELAX_FOR_NEW_WEAK_SKILLS"
        elif len(analysis.saturated_families) == len(analysis.family_signals) and analysis.family_signals:
            new_replay = _clamp(old_replay - 0.04, REPLAY_RATIO_BOUNDS)
            replay_reason = "REPLAY_RELAX_ALL_FAMILIES_STABLE"
        else:
            new_replay = old_replay
            replay_reason = "REPLAY_HOLD_BALANCED"

        new_replay = round(new_replay, 4)
        self.state.replay_ratio = new_replay
        round_changes.append(
            AdjustmentRecord(
                round_idx=round_idx,
                variable="replay_ratio",
                before=old_replay,
                after=new_replay,
                reason_code=replay_reason,
                evidence={
                    "regressing_families": list(analysis.regressing_families),
                    "weak_families": list(analysis.weak_families),
                    "overall_final_pass_rate": analysis.overall_final_pass_rate,
                },
            )
        )

        # 2. consolidation_lambda [0.001, 0.05]
        old_cons = round(self.state.consolidation_lambda, 6)
        high_prior_regressors = [
            f
            for f in analysis.regressing_families
            if analysis.family_signals[f].peak_final_pass >= 0.5
        ]
        if high_prior_regressors:
            new_cons = _clamp(old_cons * 1.5 + 0.004, CONSOLIDATION_LAMBDA_BOUNDS)
            cons_reason = "CONSOLIDATION_STRENGTHEN_PRIOR_HIGH_SKILL_REGRESSED"
        elif analysis.regressing_families:
            new_cons = _clamp(old_cons * 1.25 + 0.002, CONSOLIDATION_LAMBDA_BOUNDS)
            cons_reason = "CONSOLIDATION_STRENGTHEN_ON_REGRESSION"
        elif analysis.overall_final_pass_rate < 0.35 and analysis.weak_families:
            new_cons = _clamp(old_cons * 0.75, CONSOLIDATION_LAMBDA_BOUNDS)
            cons_reason = "CONSOLIDATION_LOOSEN_FOR_ACQUISITION"
        else:
            new_cons = old_cons
            cons_reason = "CONSOLIDATION_HOLD_STABLE"

        new_cons = round(new_cons, 6)
        self.state.consolidation_lambda = new_cons
        round_changes.append(
            AdjustmentRecord(
                round_idx=round_idx,
                variable="consolidation_lambda",
                before=old_cons,
                after=new_cons,
                reason_code=cons_reason,
                evidence={
                    "high_prior_regressors": high_prior_regressors,
                    "regressing_families": list(analysis.regressing_families),
                    "overall_final_pass_rate": analysis.overall_final_pass_rate,
                },
            )
        )

        # 3. task_priority (positive weights summing to 1.0)
        old_prio = {k: round(v, 4) for k, v in sorted(self.state.task_priority.items())}
        all_fams = sorted(set(self.state.task_priority.keys()) | set(analysis.family_signals.keys()))
        raw_weights: Dict[str, float] = {}
        priority_evidence: Dict[str, Any] = {}
        for fam in all_fams:
            base_w = float(self.state.task_priority.get(fam, 1.0 / max(len(all_fams), 1)))
            sig = analysis.family_signals.get(fam)
            if sig is None:
                raw_weights[fam] = max(0.05, base_w)
                continue
            mult = 1.0
            tags: List[str] = []
            if sig.regressing:
                mult += 0.70 + min(0.50, sig.regression_score)
                tags.append("regressing")
            if sig.persistent_fail_rate > 0.0:
                mult += 0.50 * sig.persistent_fail_rate
                tags.append("persistent_fail")
            if sig.recovered_pass_rate > 0.0:
                # Reward families that benefit from self-correction practice
                mult += 0.25 * sig.recovered_pass_rate
                tags.append("retry_recoverable")
            if sig.saturated:
                mult *= 0.55
                tags.append("saturated_downweight")
            raw_weights[fam] = max(0.02, base_w * mult)
            priority_evidence[fam] = {
                "final_pass_rate": sig.final_pass_rate,
                "persistent_fail_rate": sig.persistent_fail_rate,
                "regressing": sig.regressing,
                "saturated": sig.saturated,
                "tags": tags,
            }

        tot_w = sum(raw_weights.values()) or 1.0
        new_prio = {k: round(v / tot_w, 4) for k, v in sorted(raw_weights.items())}
        # Guarantee exact sum == 1.0 after 4-decimal rounding
        if new_prio:
            last_k = sorted(new_prio.keys())[-1]
            diff = round(1.0 - sum(new_prio.values()), 4)
            new_prio[last_k] = round(max(0.0001, new_prio[last_k] + diff), 4)

        self.state.task_priority = dict(new_prio)
        prio_reason = (
            "TASK_PRIORITY_SHIFT_TO_REGRESSING_AND_WEAK"
            if (analysis.regressing_families or analysis.weak_families)
            else "TASK_PRIORITY_REBALANCE_EVIDENCE"
        )
        round_changes.append(
            AdjustmentRecord(
                round_idx=round_idx,
                variable="task_priority",
                before=old_prio,
                after=dict(new_prio),
                reason_code=prio_reason,
                evidence=priority_evidence,
            )
        )

        # 4. retry_priority [0.0, 1.0]
        old_retry = round(self.state.retry_priority, 4)
        total_retries_spent = sum(s.retries_spent for s in analysis.family_signals.values())
        if total_retries_spent == 0:
            new_retry = old_retry
            retry_reason = "RETRY_PRIORITY_HOLD_NO_RETRIES_SPENT"
        elif analysis.overall_retry_yield >= 0.25:
            new_retry = _clamp(old_retry + 0.12, RETRY_PRIORITY_BOUNDS)
            retry_reason = "RETRY_PRIORITY_INCREASE_HIGH_YIELD"
        elif analysis.overall_retry_yield > 0.0:
            new_retry = _clamp(old_retry + 0.04, RETRY_PRIORITY_BOUNDS)
            retry_reason = "RETRY_PRIORITY_MODEST_YIELD"
        else:
            new_retry = _clamp(old_retry - 0.15, RETRY_PRIORITY_BOUNDS)
            retry_reason = "RETRY_PRIORITY_DECREASE_ZERO_YIELD_SAVE_BUDGET"

        new_retry = round(new_retry, 4)
        self.state.retry_priority = new_retry
        round_changes.append(
            AdjustmentRecord(
                round_idx=round_idx,
                variable="retry_priority",
                before=old_retry,
                after=new_retry,
                reason_code=retry_reason,
                evidence={
                    "overall_retry_yield": analysis.overall_retry_yield,
                    "overall_recovered_rate": analysis.overall_recovered_rate,
                    "retries_spent": total_retries_spent,
                },
            )
        )

        # 5. learning_rate_scale [0.50, 1.25]
        old_lr_scale = round(self.state.learning_rate_scale, 4)
        if analysis.syntax_error_rate >= 0.50 or len(analysis.regressing_families) >= 2:
            new_lr_scale = _clamp(old_lr_scale * 0.85, LR_SCALE_BOUNDS)
            lr_reason = "LR_SCALE_REDUCE_SYNTAX_INSTABILITY_OR_REGRESSION"
        elif analysis.regressing_families:
            new_lr_scale = _clamp(old_lr_scale * 0.92, LR_SCALE_BOUNDS)
            lr_reason = "LR_SCALE_DAMPEN_ON_REGRESSION"
        elif (
            not analysis.regressing_families
            and analysis.overall_final_pass_rate >= 0.50
            and analysis.syntax_error_rate < 0.25
        ):
            new_lr_scale = _clamp(old_lr_scale + 0.06, LR_SCALE_BOUNDS)
            lr_reason = "LR_SCALE_BOOST_STABLE_PROGRESS"
        else:
            new_lr_scale = old_lr_scale
            lr_reason = "LR_SCALE_HOLD_NOMINAL"

        new_lr_scale = round(new_lr_scale, 4)
        self.state.learning_rate_scale = new_lr_scale
        round_changes.append(
            AdjustmentRecord(
                round_idx=round_idx,
                variable="learning_rate_scale",
                before=old_lr_scale,
                after=new_lr_scale,
                reason_code=lr_reason,
                evidence={
                    "syntax_error_rate": analysis.syntax_error_rate,
                    "regressing_families": list(analysis.regressing_families),
                    "overall_final_pass_rate": analysis.overall_final_pass_rate,
                },
            )
        )

        self.history.extend(round_changes)
        return round_changes
