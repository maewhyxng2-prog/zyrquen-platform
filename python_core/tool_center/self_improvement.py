"""
Autonomous Self-Improvement Governance for ZYRQUEN Tool Center.
----------------------------------------------------------------
Workflow:
  1. Analyze real runtime failures in `task_memory_entries` and capability gaps
     (`memory_learning.detect_capability_gaps` + `ToolCenterRegistry` gaps).
  2. Propose concrete hypothesis & sandbox test probe (never mutates model weights
     or repository source code automatically).
  3. Execute trial inside Isolated Sandbox (`sandbox.py`) + run baseline
     Regression Check (`registry.verify_toolkit()`).
  4. Compare before/after metrics honestly and persist proposal in SQLite
     `improvement_proposals` requiring Admin P5 Approval before adoption.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

import memory_learning as ml

from .sandbox import run_python_sandbox
from .task_memory import analyze_failure_patterns, init_task_memory_schema


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def init_self_improvement_schema(conn: sqlite3.Connection) -> None:
    init_task_memory_schema(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS improvement_proposals (
            id TEXT PRIMARY KEY,
            target_area TEXT NOT NULL,
            gap_code TEXT NOT NULL,
            hypothesis TEXT NOT NULL,
            proposed_change_json TEXT NOT NULL,
            sandbox_result_json TEXT NOT NULL,
            baseline_metrics_json TEXT NOT NULL,
            candidate_metrics_json TEXT NOT NULL,
            regression_detected INTEGER NOT NULL DEFAULT 0,
            improved INTEGER NOT NULL DEFAULT 0,
            approval_status TEXT NOT NULL CHECK(approval_status IN ('PENDING_APPROVAL', 'APPROVED', 'REJECTED')),
            approved_by TEXT,
            decision_reason TEXT,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            reviewed_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_imp_proposals_status
            ON improvement_proposals (approval_status, created_at DESC);
        """
    )


def run_self_improvement_evaluation(
    conn: sqlite3.Connection,
    registry: Any,
    *,
    data_dir: Path | None = None,
    user_id: str = "system",
    sandbox_probe_code: str | None = None,
) -> dict[str, Any]:
    """
    Observe real failures & capability gaps -> test candidate validation in isolated
    sandbox -> run toolkit regression check -> compare before/after -> queue for Admin P5 approval.
    Strictly forbids modifying model weights or production code without approval.
    """
    init_self_improvement_schema(conn)

    failure_patterns = analyze_failure_patterns(conn, limit=5)
    core_gaps = ml.detect_capability_gaps(conn)

    # Identify top target honestly from real runtime evidence
    if failure_patterns:
        top = failure_patterns[0]
        target_area = str(top["capability_id"])
        gap_code = f"RECURRING_{top['error_code']}"
        hypothesis = (
            f"ลดข้อผิดพลาด '{top['error_code']}' บนความสามารถ '{target_area}' "
            f"(พบ {top['count']} ครั้ง เช่น '{str(top['sample_goal'])[:60]}') "
            f"ด้วยการตรวจ Contract & Recovery Pre-check ใน Sandbox ก่อนปรับใช้"
        )
    elif core_gaps:
        g = core_gaps[0]
        target_area = str(g.get("target") or "native_core")
        gap_code = str(g.get("gap_code") or g.get("gap_type") or "CAPABILITY_GAP")
        hypothesis = f"อุดช่องว่างระบบ '{gap_code}': {g.get('detail')}"
    else:
        target_area = "tool_center.orchestrator"
        gap_code = "PROACTIVE_REGRESSION_CHECK"
        hypothesis = "ตรวจสอบ Regression และ Readiness ของชุดเครื่องมือทั้งหมดใน Sandbox เพื่อยืนยันเสถียรภาพ"

    # 1. Baseline Regression Benchmark before candidate trial
    baseline_rep = registry.verify_toolkit(conn=conn, data_dir=data_dir)
    baseline_passed = int(baseline_rep.get("passed", 0))
    baseline_total = int(baseline_rep.get("total", 0))
    baseline_score = round(baseline_passed / baseline_total, 4) if baseline_total > 0 else 0.0

    # 2. Run Candidate Trial strictly inside Isolated Sandbox
    trial_source = sandbox_probe_code or (
        "def validate_candidate_guard(payload):\n"
        "    if not isinstance(payload, dict):\n"
        "        return {'ok': False, 'reason': 'payload_must_be_dict'}\n"
        "    return {'ok': True, 'checked_keys': sorted(payload.keys())}\n\n"
        "assert validate_candidate_guard({'goal': 'test'})['ok'] is True\n"
        "assert validate_candidate_guard('bad')['ok'] is False\n"
        "print('SANDBOX_TRIAL_PASS')\n"
    )
    sandbox_res = run_python_sandbox(trial_source, timeout_s=3.0)
    sandbox_ok = bool(sandbox_res.get("ok"))

    # 3. Post-trial Regression Check (ensure baseline still passes 100%, zero regressions)
    after_rep = registry.verify_toolkit(conn=conn, data_dir=data_dir)
    after_passed = int(after_rep.get("passed", 0))
    after_total = int(after_rep.get("total", 0))
    after_score = round(after_passed / after_total, 4) if after_total > 0 else 0.0

    regression_detected = after_score < baseline_score or after_passed < baseline_passed
    improved = sandbox_ok and not regression_detected and after_passed == after_total

    baseline_metrics = {
        "toolkit_passed": baseline_passed,
        "toolkit_total": baseline_total,
        "score": baseline_score,
        "failure_patterns_count": len(failure_patterns),
    }
    candidate_metrics = {
        "toolkit_passed": after_passed,
        "toolkit_total": after_total,
        "score": after_score,
        "sandbox_passed": sandbox_ok,
        "sandbox_duration_ms": sandbox_res.get("duration_ms"),
        "score_delta": round(after_score - baseline_score, 4),
    }
    proposed_change = {
        "target_area": target_area,
        "gap_code": gap_code,
        "weight_mutation_blocked": True,
        "requires_admin_approval": True,
        "sample_failure_patterns": failure_patterns[:3],
        "core_gaps": core_gaps[:3],
    }

    proposal_id = str(uuid.uuid4())
    now = _now_iso()
    with conn:
        conn.execute(
            """
            INSERT INTO improvement_proposals (
                id, target_area, gap_code, hypothesis, proposed_change_json,
                sandbox_result_json, baseline_metrics_json, candidate_metrics_json,
                regression_detected, improved, approval_status, approved_by,
                decision_reason, created_by, created_at, reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_APPROVAL', NULL, NULL, ?, ?, NULL)
            """,
            (
                proposal_id,
                target_area,
                gap_code,
                hypothesis,
                json.dumps(proposed_change, ensure_ascii=False),
                json.dumps(sandbox_res, ensure_ascii=False),
                json.dumps(baseline_metrics, ensure_ascii=False),
                json.dumps(candidate_metrics, ensure_ascii=False),
                1 if regression_detected else 0,
                1 if improved else 0,
                user_id,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO audit_logs (id, actor_id, actor_email, action, target, outcome, details_json, created_at)
            VALUES (?, ?, ?, 'SELF_IMPROVEMENT_PROPOSED', ?, 'PENDING_APPROVAL', ?, ?)
            """,
            (
                str(uuid.uuid4()),
                user_id,
                user_id,
                proposal_id,
                json.dumps({"target_area": target_area, "improved": improved, "regression_detected": regression_detected}),
                now,
            ),
        )

    proposal_row = dict(conn.execute("SELECT * FROM improvement_proposals WHERE id=?", (proposal_id,)).fetchone())
    return {
        "ok": True,
        "proposal": proposal_row,
        "baseline_metrics": baseline_metrics,
        "candidate_metrics": candidate_metrics,
        "sandbox_result": sandbox_res,
        "improved": improved,
        "regression_detected": regression_detected,
        "approval_required": True,
        "model_weights_mutated": False,
        "external_models_used": False,
    }


def decide_improvement_proposal(
    conn: sqlite3.Connection,
    *,
    proposal_id: str,
    decision: str,
    admin_email: str,
    admin_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    init_self_improvement_schema(conn)
    row = conn.execute("SELECT * FROM improvement_proposals WHERE id=?", (proposal_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "Improvement proposal not found."}
    if row["approval_status"] != "PENDING_APPROVAL":
        return {"ok": False, "error": f"Proposal already {row['approval_status']}."}
    if decision not in {"approve", "reject"}:
        return {"ok": False, "error": "Decision must be 'approve' or 'reject'."}
    if decision == "approve" and int(row["regression_detected"]) == 1:
        return {"ok": False, "error": "Cannot approve proposal with detected regression."}

    new_status = "APPROVED" if decision == "approve" else "REJECTED"
    now = _now_iso()
    with conn:
        conn.execute(
            """
            UPDATE improvement_proposals
            SET approval_status=?, approved_by=?, decision_reason=?, reviewed_at=?
            WHERE id=?
            """,
            (new_status, admin_email, reason, now, proposal_id),
        )
        conn.execute(
            """
            INSERT INTO audit_logs (id, actor_id, actor_email, action, target, outcome, details_json, created_at)
            VALUES (?, ?, ?, 'SELF_IMPROVEMENT_DECIDE', ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                admin_id,
                admin_email,
                proposal_id,
                new_status,
                json.dumps({"reason": reason}),
                now,
            ),
        )

    updated = dict(conn.execute("SELECT * FROM improvement_proposals WHERE id=?", (proposal_id,)).fetchone())
    return {
        "ok": True,
        "proposal": updated,
        "status": new_status,
        "model_weights_mutated": False,
    }
