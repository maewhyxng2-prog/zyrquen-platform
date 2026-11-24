"""Self-Improvement Research Loop (P2).

Workflow:
  observe -> detect_gaps -> propose_hypothesis -> isolated_experiment
  -> promotion_gate (requires VERIFIED evidence + zero regression + Tier-2 human approval)
Never auto-mutates active weights.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .capability_benchmark import (
    BenchmarkEvidenceRecord,
    evaluate_capability_status,
)


@dataclass(frozen=True)
class ImprovementProposal:
    proposal_id: str
    subsystem: str
    current_status: str
    current_score: float
    target_score: float
    hypothesis: str
    requires_tier2_approval: bool = True


@dataclass
class ExperimentEvaluationResult:
    proposal_id: str
    status: str  # "APPROVED_FOR_PROMOTION" | "AWAITING_HUMAN_APPROVAL" | "REJECTED_REGRESSION" | "BLOCKED"
    measured_status: str
    candidate_score: float
    baseline_score: float
    model_weights_changed: bool = False
    reasons: list[str] = field(default_factory=list)


class SelfImprovementResearchLoop:
    def observe_and_detect_gaps(
        self,
        capability_matrix: dict[str, Any],
        target_threshold: float = 0.90,
    ) -> list[ImprovementProposal]:
        proposals: list[ImprovementProposal] = []
        subsystems = capability_matrix.get("subsystems", {})
        for idx, (name, entry) in enumerate(sorted(subsystems.items()), start=1):
            status = entry.get("status", "NOT_IMPLEMENTED")
            score = float(entry.get("score", 0.0))
            if status != "VERIFIED" or score < target_threshold:
                proposals.append(
                    ImprovementProposal(
                        proposal_id=f"hyp-{idx:03d}-{name}",
                        subsystem=name,
                        current_status=status,
                        current_score=score,
                        target_score=target_threshold,
                        hypothesis=(
                            f"Close capability gap on {name} (status={status}, score={score:.2f} -> target={target_threshold:.2f}) "
                            "using isolated dataset/architecture experiment under zero-regression gate."
                        ),
                    )
                )
        return proposals

    def evaluate_promotion_gate(
        self,
        *,
        proposal: ImprovementProposal,
        baseline_score: float,
        candidate_record: BenchmarkEvidenceRecord,
        human_approved: bool = False,
    ) -> ExperimentEvaluationResult:
        if candidate_record.subsystem != proposal.subsystem:
            raise ValueError("Candidate benchmark record subsystem does not match proposal")

        measured_status = evaluate_capability_status(candidate_record)
        if candidate_record.score < baseline_score or measured_status == "REGRESSION_FAILED":
            return ExperimentEvaluationResult(
                proposal_id=proposal.proposal_id,
                status="REJECTED_REGRESSION",
                measured_status="REGRESSION_FAILED",
                candidate_score=candidate_record.score,
                baseline_score=baseline_score,
                model_weights_changed=False,
                reasons=[
                    f"Regression detected: candidate {candidate_record.score:.4f} < baseline {baseline_score:.4f}"
                ],
            )

        if measured_status != "VERIFIED":
            return ExperimentEvaluationResult(
                proposal_id=proposal.proposal_id,
                status="BLOCKED",
                measured_status=measured_status,
                candidate_score=candidate_record.score,
                baseline_score=baseline_score,
                model_weights_changed=False,
                reasons=[
                    f"Candidate capability status is {measured_status}, not VERIFIED"
                ],
            )

        if not human_approved:
            return ExperimentEvaluationResult(
                proposal_id=proposal.proposal_id,
                status="AWAITING_HUMAN_APPROVAL",
                measured_status=measured_status,
                candidate_score=candidate_record.score,
                baseline_score=baseline_score,
                model_weights_changed=False,
                reasons=["Tier-2 human approval required before promotion"],
            )

        return ExperimentEvaluationResult(
            proposal_id=proposal.proposal_id,
            status="APPROVED_FOR_PROMOTION",
            measured_status="VERIFIED",
            candidate_score=candidate_record.score,
            baseline_score=baseline_score,
            model_weights_changed=False,
            reasons=["Zero-regression VERIFIED + Tier-2 human approval satisfied"],
        )
