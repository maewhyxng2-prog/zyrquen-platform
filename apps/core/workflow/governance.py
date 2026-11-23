"""2-Tier Permission Policy and HMAC-SHA256 Single-Use Approval Gate."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from apps.core.workflow.models import ApprovalViolationError, WorkflowStepSpec
from apps.core.workflow.store import WorkflowStore


TIER2_GATED_ACTIONS = frozenset(
    {
        "training.execute",
        "compute.paid_gpu",
        "model.stage",
        "model.promote",
        "model.rollback",
        "architecture.modify",
        "data.delete",
        "git.push",
        "git.merge_main",
        "deploy.production",
    }
)


class WorkflowGovernance:
    def __init__(self, store: WorkflowStore, *, secret: str | None = None) -> None:
        self.store = store
        env_secret = (secret if secret is not None else os.getenv("ZYRQUEN_APPROVAL_SECRET", "")).strip()
        if env_secret:
            self._secret = env_secret.encode("utf-8")
        else:
            # In-memory ephemeral fallback for local/dev tests; production startup checks env var
            self._secret = secrets.token_bytes(32)

    def requires_human_approval(self, step: WorkflowStepSpec) -> bool:
        return (
            step.tier == "tier2_approval"
            or step.action_type in TIER2_GATED_ACTIONS
            or step.requires_paid_gpu
        )

    def _compute_signature(
        self,
        *,
        approval_id: str,
        run_id: str,
        step_key: str,
        action_type: str,
        scope: str,
        expires_at: str,
    ) -> str:
        msg = f"{approval_id}|{run_id}|{step_key}|{action_type}|{scope}|{expires_at}".encode("utf-8")
        return hmac.new(self._secret, msg, hashlib.sha256).hexdigest()

    def ensure_pending_approval(
        self,
        *,
        run_id: str,
        step: WorkflowStepSpec,
        requested_by_user_id: str | None,
        scope: str,
        ttl_minutes: int = 120,
        reason: str = "",
    ) -> dict[str, Any]:
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat()
        return self.store.create_approval_request(
            run_id=run_id,
            step_key=step.step_key,
            action_type=step.action_type,
            scope=scope,
            requested_by_user_id=requested_by_user_id,
            expires_at=expires_at,
            reason=reason or step.description,
        )

    def decide_approval(
        self,
        approval_id: str,
        *,
        approve: bool,
        approver_user_id: str,
        approver_role: str,
        reason: str = "",
    ) -> dict[str, Any]:
        if approver_role != "admin":
            raise ApprovalViolationError("Only admin users can approve or reject Tier-2 gates.")

        rec = self.store.get_approval(approval_id)
        if rec is None:
            raise ApprovalViolationError(f"Approval request not found: {approval_id}")
        if rec["status"] != "pending":
            raise ApprovalViolationError(
                f"Approval {approval_id} is already finalized with status={rec['status']}"
            )
        if datetime.fromisoformat(rec["expires_at"]) <= datetime.now(timezone.utc):
            self.store.set_approval_decision(
                approval_id,
                status="expired",
                approved_by_user_id=approver_user_id,
                signature_hmac=None,
                reason="Expired before decision",
            )
            raise ApprovalViolationError(f"Approval request {approval_id} has expired.")

        if not approve:
            updated = self.store.set_approval_decision(
                approval_id,
                status="rejected",
                approved_by_user_id=approver_user_id,
                signature_hmac=None,
                reason=reason,
            )
            if updated is None:
                raise ApprovalViolationError("Failed to record rejection atomically.")
            return updated

        sig = self._compute_signature(
            approval_id=rec["id"],
            run_id=rec["run_id"],
            step_key=rec["step_key"],
            action_type=rec["action_type"],
            scope=rec["scope"],
            expires_at=rec["expires_at"],
        )
        updated = self.store.set_approval_decision(
            approval_id,
            status="approved",
            approved_by_user_id=approver_user_id,
            signature_hmac=sig,
            reason=reason,
        )
        if updated is None:
            raise ApprovalViolationError("Approval state changed concurrently.")
        return updated

    def has_valid_approval(
        self,
        run_id: str,
        *,
        action_type: str = "compute.paid_gpu",
        scope: str | None = None,
    ) -> bool:
        """Read-only verification of an active HMAC-signed admin approval (does not consume)."""
        now = datetime.now(timezone.utc)
        for approval in self.store.list_approvals(status="approved", limit=100):
            if approval.get("run_id") != run_id or approval.get("action_type") != action_type:
                continue
            if scope is not None and approval.get("scope") != scope:
                continue
            try:
                if datetime.fromisoformat(approval["expires_at"]) <= now:
                    continue
            except (KeyError, ValueError, TypeError):
                continue
            expected_sig = self._compute_signature(
                approval_id=approval["id"],
                run_id=approval["run_id"],
                step_key=approval["step_key"],
                action_type=approval["action_type"],
                scope=approval["scope"],
                expires_at=approval["expires_at"],
            )
            provided_sig = str(approval.get("signature_hmac") or "")
            if provided_sig and hmac.compare_digest(expected_sig, provided_sig):
                return True
        return False

    def verify_and_consume(
        self,
        run_id: str,
        step: WorkflowStepSpec,
        *,
        expected_scope: str | None = None,
    ) -> dict[str, Any] | None:
        """Verify HMAC signature, action/scope binding, expiry, and consume an approved token atomically."""
        if not self.requires_human_approval(step):
            return None

        candidates = [
            a
            for a in self.store.list_approvals(status="approved", limit=100)
            if a["run_id"] == run_id and a["step_key"] == step.step_key
        ]
        if not candidates:
            return None

        approval = candidates[0]
        if approval.get("action_type") != step.action_type:
            raise ApprovalViolationError(
                f"Approval {approval['id']} action_type={approval.get('action_type')!r} "
                f"does not match step action_type={step.action_type!r}."
            )
        if expected_scope is not None and approval.get("scope") != expected_scope:
            raise ApprovalViolationError(
                f"Approval {approval['id']} scope={approval.get('scope')!r} "
                f"does not match required scope={expected_scope!r}."
            )
        if datetime.fromisoformat(approval["expires_at"]) <= datetime.now(timezone.utc):
            raise ApprovalViolationError(f"Approval {approval['id']} has expired.")

        expected_sig = self._compute_signature(
            approval_id=approval["id"],
            run_id=approval["run_id"],
            step_key=approval["step_key"],
            action_type=approval["action_type"],
            scope=approval["scope"],
            expires_at=approval["expires_at"],
        )
        provided_sig = str(approval.get("signature_hmac") or "")
        if not provided_sig or not hmac.compare_digest(expected_sig, provided_sig):
            raise ApprovalViolationError(f"Approval HMAC signature invalid for {approval['id']}.")

        if not self.store.mark_approval_consumed(approval["id"]):
            raise ApprovalViolationError(f"Approval {approval['id']} was already consumed.")

        return self.store.get_approval(approval["id"])

    def verify_and_consume_by_id(
        self,
        approval_id: str,
        *,
        expected_action_type: str = "training.execute",
        expected_run_id: str | None = None,
        expected_step_key: str | None = None,
        expected_scope: str | None = None,
        expected_model_version: str | None = None,
    ) -> dict[str, Any]:
        """Verify HMAC signature, expiry, bindings, and consume an explicit approval_id."""
        approval = self.store.get_approval(approval_id)
        if approval is None:
            raise ApprovalViolationError(f"Approval request not found: {approval_id}")
        if approval.get("action_type") != expected_action_type:
            raise ApprovalViolationError(
                f"Approval {approval_id} action_type={approval.get('action_type')!r} "
                f"does not match required {expected_action_type!r}."
            )
        if expected_run_id is not None and approval.get("run_id") != expected_run_id:
            raise ApprovalViolationError(
                f"Approval {approval_id} run_id={approval.get('run_id')!r} "
                f"does not match required {expected_run_id!r}."
            )
        if expected_step_key is not None and approval.get("step_key") != expected_step_key:
            raise ApprovalViolationError(
                f"Approval {approval_id} step_key={approval.get('step_key')!r} "
                f"does not match required {expected_step_key!r}."
            )
        if expected_scope is not None and approval.get("scope") != expected_scope:
            raise ApprovalViolationError(
                f"Approval {approval_id} scope={approval.get('scope')!r} "
                f"does not match required {expected_scope!r}."
            )
        if expected_model_version is not None:
            required_model_scope = f"model:{expected_model_version}"
            if approval.get("scope") != required_model_scope:
                raise ApprovalViolationError(
                    f"Approval {approval_id} scope={approval.get('scope')!r} "
                    f"does not match required model scope {required_model_scope!r}."
                )
        if approval.get("status") != "approved":
            raise ApprovalViolationError(
                f"Approval {approval_id} is not in 'approved' state (status={approval.get('status')!r})."
            )
        if datetime.fromisoformat(approval["expires_at"]) <= datetime.now(timezone.utc):
            raise ApprovalViolationError(f"Approval {approval_id} has expired.")

        expected_sig = self._compute_signature(
            approval_id=approval["id"],
            run_id=approval["run_id"],
            step_key=approval["step_key"],
            action_type=approval["action_type"],
            scope=approval["scope"],
            expires_at=approval["expires_at"],
        )
        provided_sig = str(approval.get("signature_hmac") or "")
        if not provided_sig or not hmac.compare_digest(expected_sig, provided_sig):
            raise ApprovalViolationError(f"Approval HMAC signature invalid for {approval_id}.")

        if not self.store.mark_approval_consumed(approval_id):
            raise ApprovalViolationError(f"Approval {approval_id} was already consumed.")

        consumed = self.store.get_approval(approval_id)
        assert consumed is not None
        return consumed
