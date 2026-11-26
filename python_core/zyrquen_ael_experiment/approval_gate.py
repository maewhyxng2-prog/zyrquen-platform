"""Fail-closed Approval Gate for ZYRQUEN AEL Experiment.

Verifies held-out execution performance, SHA-256 checkpoint integrity, zero data
leakage, non-regression on validation/retention, and strict equal-budget compliance.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

_PYTHON_CORE = Path(__file__).resolve().parent.parent
if str(_PYTHON_CORE) not in sys.path:
    sys.path.insert(0, str(_PYTHON_CORE))

from v2.zyrquen_v2_trainer import ApprovalGate, EvalReport, GateDecision  # noqa: E402


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class AELApprovalGate:
    """Fail-closed gate checking checkpoint SHA-256, held-out, regression, and budget parity."""

    def __init__(
        self,
        *,
        min_unseen_gain: float = 0.01,
        max_regression_drop: float = 0.05,
        require_non_zero_unseen: bool = True,
    ) -> None:
        self._inner = ApprovalGate(
            min_unseen_gain=min_unseen_gain,
            max_regression_drop=max_regression_drop,
            require_non_zero_unseen=require_non_zero_unseen,
        )

    def verify_and_record(
        self,
        *,
        checkpoint_path: Path,
        expected_sha256: str,
        baseline_heldout: EvalReport,
        candidate_heldout: EvalReport,
        baseline_val: EvalReport,
        candidate_val: EvalReport,
        leakage_count: int,
        within_budget: bool,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        ckpt = Path(checkpoint_path)
        if not ckpt.is_file():
            decision = GateDecision(
                approved=False,
                reason=f"BLOCKED: checkpoint file missing at {ckpt}",
                baseline_unseen=baseline_heldout.exec_pass_rate,
                candidate_unseen=candidate_heldout.exec_pass_rate,
                baseline_regression=baseline_val.exec_pass_rate,
                candidate_regression=candidate_val.exec_pass_rate,
                leakage_count=leakage_count,
            )
            actual_sha = ""
        else:
            actual_sha = compute_sha256(ckpt)
            if actual_sha != expected_sha256:
                decision = GateDecision(
                    approved=False,
                    reason=(
                        f"BLOCKED: SHA-256 mismatch ({actual_sha[:12]} != {expected_sha256[:12]})"
                    ),
                    baseline_unseen=baseline_heldout.exec_pass_rate,
                    candidate_unseen=candidate_heldout.exec_pass_rate,
                    baseline_regression=baseline_val.exec_pass_rate,
                    candidate_regression=candidate_val.exec_pass_rate,
                    leakage_count=leakage_count,
                )
            elif not within_budget:
                decision = GateDecision(
                    approved=False,
                    reason="BLOCKED: candidate exceeded agreed ComputeBudget",
                    baseline_unseen=baseline_heldout.exec_pass_rate,
                    candidate_unseen=candidate_heldout.exec_pass_rate,
                    baseline_regression=baseline_val.exec_pass_rate,
                    candidate_regression=candidate_val.exec_pass_rate,
                    leakage_count=leakage_count,
                )
            else:
                decision = self._inner.evaluate(
                    baseline_heldout,
                    candidate_heldout,
                    baseline_val,
                    candidate_val,
                    leakage_count=leakage_count,
                )

        record_path = ckpt.with_suffix(".approval.json")
        payload: Dict[str, Any] = {
            "status": "APPROVED" if decision.approved else "REJECTED_BY_GATE",
            "approved": bool(decision.approved),
            "approved_checkpoint": str(ckpt) if decision.approved else None,
            "candidate_checkpoint": str(ckpt),
            "sha256": actual_sha,
            "expected_sha256": expected_sha256,
            "within_budget": bool(within_budget),
            "decision": asdict(decision),
            "metadata": dict(metadata),
        }
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        payload["approval_record_path"] = str(record_path)
        return payload
