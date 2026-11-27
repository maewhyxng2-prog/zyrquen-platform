"""Tier-2 HMAC Approval Gate & Governance for ZYRQUEN Workflow Engine (pure stdlib)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


class ApprovalViolationError(PermissionError):
    """Raised when a Tier-2 Approval Gate ticket is missing, unapproved, expired, forged, or already consumed."""

    error_code = "approval_violation"


@dataclass(frozen=True)
class WorkflowStepSpec:
    step_key: str
    handler_key: str
    description: str = ""
    tier: str = "tier1_auto"
    action_type: str = ""
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    lane: str = "control_ops"
    max_attempts: int = 2
    estimated_params: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_key": self.step_key,
            "handler_key": self.handler_key,
            "description": self.description,
            "tier": self.tier,
            "action_type": self.action_type,
            "depends_on": list(self.depends_on),
            "lane": self.lane,
            "max_attempts": self.max_attempts,
            "estimated_params": self.estimated_params,
        }


def _scope_matches(approval_scope: str, expected_scope: str) -> bool:
    clean_actual = str(approval_scope or "").strip()
    clean_expected = str(expected_scope or "").strip()
    if not clean_expected:
        return True
    if not clean_actual:
        return False
    if clean_actual == clean_expected:
        return True
    prefix = clean_expected.split(":", 1)[0] + ":"
    if clean_actual in {f"{prefix}*", f"{prefix}all", "*"}:
        return True
    return False


class WorkflowGovernance:
    """Signs, validates, and consumes Tier-2 Approval Gate tickets backed by WorkflowStore."""

    def __init__(
        self,
        store: Any,
        *,
        secret: str | None = None,
        approval_secret: str | None = None,
    ) -> None:
        self.store = store
        effective_secret = approval_secret if approval_secret is not None else secret
        raw_secret = (effective_secret or "").strip()
        self._has_explicit_secret = bool(raw_secret)
        self._secret = raw_secret if raw_secret else secrets.token_hex(32)

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
        canonical = "|".join(
            [
                str(approval_id),
                str(run_id),
                str(step_key),
                str(action_type),
                str(scope),
                str(expires_at),
            ]
        )
        return hmac.new(
            self._secret.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def ensure_pending_approval(
        self,
        *,
        run_id: str,
        step: WorkflowStepSpec,
        requested_by_user_id: str | None = None,
        scope: str = "",
        ttl_seconds: int = 3600,
    ) -> dict[str, Any]:
        existing = self.store.find_approval_for_step(run_id=run_id, step_key=step.step_key)
        if existing is not None:
            return existing

        approval_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(seconds=max(60, int(ttl_seconds)))).isoformat()
        action_type = step.action_type or step.handler_key or step.step_key
        approval = self.store.create_approval(
            approval_id=approval_id,
            run_id=str(run_id),
            step_key=step.step_key,
            action_type=action_type,
            scope=str(scope or ""),
            requested_by_user_id=requested_by_user_id,
            status="pending",
            expires_at=expires_at,
            created_at=now.isoformat(),
        )
        self.store.append_audit_log(
            run_id=str(run_id),
            step_key=step.step_key,
            actor_id=str(requested_by_user_id or "system"),
            event_type="approval_requested",
            resource=f"approval:{approval_id}",
            decision="PENDING",
            details={"action_type": action_type, "scope": scope},
        )
        return approval

    def decide_approval(
        self,
        approval_id: str,
        *,
        approve: bool,
        approver_user_id: str,
        approver_role: str,
        reason: str = "",
    ) -> dict[str, Any]:
        if str(approver_role or "").strip().lower() != "admin":
            raise ApprovalViolationError("Only administrators may decide Tier-2 workflow approvals.")

        approval = self.store.get_approval(approval_id)
        if approval is None:
            raise ApprovalViolationError(f"Approval request not found: {approval_id}")
        if approval.get("status") != "pending":
            raise ApprovalViolationError(
                f"Approval {approval_id} is already {approval.get('status')!r} and cannot be re-decided."
            )

        now = datetime.now(timezone.utc)
        try:
            expires_at = datetime.fromisoformat(str(approval["expires_at"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ApprovalViolationError(
                f"Approval {approval_id} has invalid expiration timestamp."
            ) from exc
        if expires_at <= now:
            raise ApprovalViolationError(f"Approval {approval_id} has expired.")

        if not approve:
            updated = self.store.update_approval(
                approval_id,
                status="rejected",
                approved_by_user_id=str(approver_user_id),
                signature_hmac=None,
                reason=str(reason or ""),
            )
            self.store.append_audit_log(
                run_id=approval["run_id"],
                step_key=approval["step_key"],
                actor_id=str(approver_user_id),
                event_type="approval_decided",
                resource=f"approval:{approval_id}",
                decision="REJECTED",
                details={"reason": reason, "action_type": approval.get("action_type")},
            )
            return updated

        signature = self._compute_signature(
            approval_id=approval["id"],
            run_id=approval["run_id"],
            step_key=approval["step_key"],
            action_type=approval["action_type"],
            scope=approval["scope"],
            expires_at=approval["expires_at"],
        )
        updated = self.store.update_approval(
            approval_id,
            status="approved",
            approved_by_user_id=str(approver_user_id),
            signature_hmac=signature,
            reason=str(reason or ""),
        )
        self.store.append_audit_log(
            run_id=approval["run_id"],
            step_key=approval["step_key"],
            actor_id=str(approver_user_id),
            event_type="approval_decided",
            resource=f"approval:{approval_id}",
            decision="APPROVED",
            details={
                "reason": reason,
                "action_type": approval.get("action_type"),
                "scope": approval.get("scope"),
            },
        )
        return updated

    def verify_approval_readonly(
        self,
        approval_id: str,
        *,
        expected_action_type: str | None = None,
        expected_scope: str | None = None,
    ) -> dict[str, Any]:
        clean_id = str(approval_id or "").strip()
        if not clean_id:
            raise ApprovalViolationError("Approval Gate ticket ID is required.")
        approval = self.store.get_approval(clean_id)
        if approval is None:
            raise ApprovalViolationError(f"Approval request not found: {clean_id}")
        if expected_action_type and approval.get("action_type") != expected_action_type:
            raise ApprovalViolationError(
                f"Approval {clean_id} action_type={approval.get('action_type')!r} "
                f"does not match required {expected_action_type!r}."
            )
        if approval.get("status") != "approved":
            raise ApprovalViolationError(
                f"Approval {clean_id} is not in 'approved' state (status={approval.get('status')!r})."
            )
        if expected_scope and not _scope_matches(str(approval.get("scope") or ""), expected_scope):
            raise ApprovalViolationError(
                f"Approval {clean_id} scope={approval.get('scope')!r} does not authorize {expected_scope!r}."
            )
        try:
            expires_at = datetime.fromisoformat(str(approval["expires_at"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ApprovalViolationError(
                f"Approval {clean_id} has invalid expiration timestamp."
            ) from exc
        if expires_at <= datetime.now(timezone.utc):
            raise ApprovalViolationError(f"Approval {clean_id} has expired.")

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
            raise ApprovalViolationError(f"Approval HMAC signature invalid for {clean_id}.")
        return approval

    def verify_and_consume_by_id(
        self,
        approval_id: str,
        *,
        expected_action_type: str | None = None,
        expected_scope: str | None = None,
    ) -> dict[str, Any]:
        approval = self.verify_approval_readonly(
            approval_id,
            expected_action_type=expected_action_type,
            expected_scope=expected_scope,
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        consumed = self.store.consume_approval(approval["id"], consumed_at=now_iso)
        if consumed is None:
            raise ApprovalViolationError(
                f"Approval {approval['id']} could not be consumed (already used or modified)."
            )
        self.store.append_audit_log(
            run_id=consumed["run_id"],
            step_key=consumed["step_key"],
            actor_id=str(consumed.get("approved_by_user_id") or "system"),
            event_type="approval_consumed",
            resource=f"approval:{consumed['id']}",
            decision="CONSUMED",
            details={
                "action_type": consumed.get("action_type"),
                "scope": consumed.get("scope"),
            },
        )
        return consumed

    def requires_human_approval(self, step: Any) -> bool:
        tier = str(getattr(step, "tier", "") or "").strip().lower()
        if tier in {"tier2", "tier_2", "tier2_approval", "tier_2_approval", "human", "manual"} or tier.startswith("tier2"):
            return True
        return bool(getattr(step, "requires_paid_gpu", False))

    def verify_and_consume(
        self,
        run_id: str,
        step: Any,
        *,
        expected_scope: str | None = None,
    ) -> dict[str, Any] | None:
        step_key = str(getattr(step, "step_key", "") or "")
        action_type = getattr(step, "action_type", None)
        candidates: list[dict[str, Any]] = []
        if hasattr(self.store, "list_approvals"):
            for row in self.store.list_approvals(limit=200):
                if str(row.get("run_id") or "") != str(run_id):
                    continue
                if step_key and str(row.get("step_key") or "") != step_key:
                    continue
                if str(row.get("status") or "") != "approved":
                    continue
                candidates.append(row)

        if not candidates:
            # No ticket requested yet: the orchestrator creates the pending approval and pauses.
            # Tampered, expired, out-of-scope and consumed tickets still raise below.
            return None

        last_exc: Exception | None = None
        for row in candidates:
            aid = str(row.get("id") or "")
            if not aid:
                continue
            try:
                return self.verify_and_consume_by_id(
                    aid,
                    expected_action_type=action_type,
                    expected_scope=expected_scope,
                )
            except ApprovalViolationError as exc:
                last_exc = exc
                continue

        if last_exc is not None:
            raise last_exc
        raise ApprovalViolationError(
            f"Approval validation failed for run_id={run_id!r}, step_key={step_key!r}."
        )

    def has_valid_approval(
        self,
        run_id: str,
        *,
        action_type: str | None = None,
        step_key: str | None = None,
    ) -> bool:
        candidates: list[dict[str, Any]] = []
        if hasattr(self.store, "list_approvals"):
            all_rows = self.store.list_approvals(limit=200)
            for row in all_rows:
                if str(row.get("run_id") or "") != str(run_id):
                    continue
                if step_key and str(row.get("step_key") or "") != str(step_key):
                    continue
                if action_type and str(row.get("action_type") or "") != str(action_type):
                    continue
                candidates.append(row)

        for row in candidates:
            aid = row.get("id")
            if not aid:
                continue
            try:
                self.verify_approval_readonly(
                    str(aid),
                    expected_action_type=action_type,
                )
                return True
            except ApprovalViolationError:
                continue
        return False
