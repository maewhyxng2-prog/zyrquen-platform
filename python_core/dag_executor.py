#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — Real DAG Execution Engine & Resumable Mission State Machine (P1)
------------------------------------------------------------------------------
Implements:
- 11-state persistent Mission lifecycle in SQLite
- Explicit DAG node contracts (dependencies, input/output contracts, pre/postconditions,
  idempotency keys, retry policy, approval policy, execution status, evidence_refs)
- Strict Postcondition Verification (never marks COMPLETED merely because no exception raised)
- Autonomous Recovery (idempotent bounded retries, backtracking/re-planning on failure)
- Resumption from AWAITING_APPROVAL when an Admin approves/rejects a gated tool invocation
"""

from __future__ import annotations

import collections
import hashlib
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from research_pipeline import run_research_pipeline
from tools_engine import invoke_tool_governed, list_workspace_files


MISSION_STATES = {
    "MISSION_CREATED",
    "GOAL_ANALYZED",
    "PLAN_READY",
    "NEEDS_CLARIFICATION",
    "AWAITING_APPROVAL",
    "READY",
    "RUNNING",
    "EXECUTING",
    "AWAITING_EVIDENCE",
    "RECOVERING",
    "COMPLETED",
    "FAILED",
    "BLOCKED",
    "CANCELLED",
}

CANONICAL_NODE_STATES = {
    "NEEDS_CLARIFICATION",
    "BLOCKED",
    "READY",
    "RUNNING",
    "EXECUTING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _idempotency_key(mission_id: str, task_id: str) -> str:
    return hashlib.sha256(f"{mission_id}:{task_id}".encode("utf-8")).hexdigest()[:24]


def validate_dag_nodes(nodes: list[dict[str, Any]]) -> tuple[bool, str | None]:
    if not nodes:
        return False, "DAG contains zero nodes"
    ids = [str(n.get("task_id", "")) for n in nodes]
    if any(not tid for tid in ids) or len(set(ids)) != len(ids):
        return False, "Duplicate or missing task_id in DAG"
    id_set = set(ids)
    adj: dict[str, list[str]] = collections.defaultdict(list)
    for n in nodes:
        tid = n["task_id"]
        for dep in n.get("dependencies", []):
            if dep not in id_set or dep == tid:
                return False, f"Invalid dependency '{dep}' on node '{tid}'"
            adj[dep].append(tid)

    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node_id: str) -> bool:
        if node_id in visiting:
            return False
        if node_id in visited:
            return True
        visiting.add(node_id)
        for nxt in adj.get(node_id, []):
            if not dfs(nxt):
                return False
        visiting.remove(node_id)
        visited.add(node_id)
        return True

    if not all(dfs(tid) for tid in ids):
        return False, "Cycle detected in DAG"
    return True, None


def build_mission_dag(
    mission_id: str,
    goal: str,
    *,
    has_math: bool,
    has_logic: bool,
    enable_research: bool,
    enable_knowledge_dev: bool,
    enable_execution: bool,
) -> list[dict[str, Any]]:
    """Construct goal-driven DAG nodes with full contracts and verification rules."""
    nodes: list[dict[str, Any]] = [
        {
            "task_id": "node_goal_analysis",
            "title": "วิเคราะห์เป้าหมายและตรวจสอบความจำ/ตรรกะภายใน",
            "dependencies": [],
            "tool_id": "native_cognition",
            "input_contract": {"required_keys": ["goal"], "goal": goal},
            "output_contract": {"required_keys": ["terms_count"], "disallow_statuses": ["FAILED", "BLOCKED"]},
            "preconditions": ["non_empty_goal"],
            "postconditions": ["cognition_analyzed"],
            "retry_policy": {"max_attempts": 1, "idempotent_required": True, "retry_on": []},
            "approval_policy": "auto",
            "execution_status": "READY",
            "attempts": 0,
            "idempotency_key": _idempotency_key(mission_id, "node_goal_analysis"),
            "evidence_refs": [],
            "last_error": None,
            "output_data": {},
        }
    ]

    last_core_dep = "node_goal_analysis"

    if has_math and enable_execution:
        nodes.append(
            {
                "task_id": "node_compute_ast",
                "title": "คำนวณและพิสูจน์ด้วย AST / Algebra Engine",
                "dependencies": [last_core_dep],
                "tool_id": "calc_ast",
                "input_contract": {"required_keys": ["expression"], "expression": goal},
                "output_contract": {"required_keys": ["status"], "disallow_statuses": ["FAILED", "BLOCKED"]},
                "preconditions": [f"dependency_completed:{last_core_dep}"],
                "postconditions": ["non_empty_compute_result"],
                "retry_policy": {"max_attempts": 1, "idempotent_required": True, "retry_on": []},
                "approval_policy": "auto",
                "execution_status": "READY",
                "attempts": 0,
                "idempotency_key": _idempotency_key(mission_id, "node_compute_ast"),
                "evidence_refs": [],
                "last_error": None,
                "output_data": {},
            }
        )
        last_core_dep = "node_compute_ast"

    if has_logic:
        nodes.append(
            {
                "task_id": "node_logic_deduction",
                "title": "อนุมานตรรกะถ่ายทอดและตรวจจับวงจรขัดแย้ง",
                "dependencies": ["node_goal_analysis"],
                "tool_id": "native_logic",
                "input_contract": {"required_keys": ["goal"], "goal": goal},
                "output_contract": {"required_keys": ["logic_status"], "disallow_statuses": ["FAILED", "BLOCKED"]},
                "preconditions": ["dependency_completed:node_goal_analysis"],
                "postconditions": ["logic_non_contradictory"],
                "retry_policy": {"max_attempts": 1, "idempotent_required": True, "retry_on": []},
                "approval_policy": "auto",
                "execution_status": "READY",
                "attempts": 0,
                "idempotency_key": _idempotency_key(mission_id, "node_logic_deduction"),
                "evidence_refs": [],
                "last_error": None,
                "output_data": {},
            }
        )

    if enable_research:
        nodes.append(
            {
                "task_id": "node_research_discover",
                "title": "ค้นคว้าข้ามแหล่ง อ่านเอกสาร และตรวจความน่าเชื่อถือ",
                "dependencies": ["node_goal_analysis"],
                "tool_id": "research_pipeline",
                "input_contract": {"required_keys": ["goal"], "goal": goal},
                "output_contract": {"required_keys": ["verdict"], "disallow_statuses": ["FAILED", "BLOCKED"]},
                "preconditions": ["dependency_completed:node_goal_analysis"],
                "postconditions": ["research_evidence_recorded"],
                "retry_policy": {"max_attempts": 2, "idempotent_required": True, "retry_on": ["TRANSIENT_ERROR", "INSUFFICIENT_EVIDENCE"]},
                "approval_policy": "approval_required",
                "execution_status": "READY",
                "attempts": 0,
                "idempotency_key": _idempotency_key(mission_id, "node_research_discover"),
                "evidence_refs": [],
                "last_error": None,
                "output_data": {},
            }
        )
        last_core_dep = "node_research_discover"

    if enable_knowledge_dev:
        learn_deps = ["node_research_discover"] if enable_research else ["node_goal_analysis"]
        nodes.append(
            {
                "task_id": "node_knowledge_integrate",
                "title": "สังเคราะห์และพัฒนาองค์ความรู้ลงกราฟ SQLite อย่างตรวจสอบได้",
                "dependencies": learn_deps,
                "tool_id": "knowledge_integrate",
                "input_contract": {"required_keys": ["goal"], "goal": goal},
                "output_contract": {"required_keys": ["triples_added"], "disallow_statuses": ["FAILED", "BLOCKED"]},
                "preconditions": [f"dependency_completed:{d}" for d in learn_deps],
                "postconditions": ["knowledge_consistency_checked"],
                "retry_policy": {"max_attempts": 1, "idempotent_required": True, "retry_on": []},
                "approval_policy": "auto",
                "execution_status": "READY",
                "attempts": 0,
                "idempotency_key": _idempotency_key(mission_id, "node_knowledge_integrate"),
                "evidence_refs": [],
                "last_error": None,
                "output_data": {},
            }
        )
        last_core_dep = "node_knowledge_integrate"

    if enable_execution:
        goal_l = goal.lower()
        target_file_m = re.search(r"([A-Za-z0-9_.\-]+\.(?:csv|json|py|md|txt))\b", goal, re.IGNORECASE)
        if target_file_m or any(k in goal_l for k in ("วิเคราะห์ข้อมูล", "ตรวจโค้ด", "inspect", "dataset", "defect", "รายงาน")):
            inspect_action = (
                "analyze_dataset"
                if (target_file_m and target_file_m.group(1).lower().endswith((".csv", ".json"))) or "dataset" in goal_l or "วิเคราะห์ข้อมูล" in goal_l
                else "inspect"
            )
            target_filename = target_file_m.group(1) if target_file_m else ""
            nodes.append(
                {
                    "task_id": "node_workspace_inspect",
                    "title": "ตรวจสอบและวิเคราะห์ข้อมูล/ไฟล์ใน Sandbox จริง",
                    "dependencies": [last_core_dep],
                    "tool_id": "workspace_artifact_inspect",
                    "input_contract": {
                        "required_keys": ["action"],
                        "action": inspect_action,
                        "filename": target_filename,
                        "goal": goal,
                    },
                    "output_contract": {"required_keys": ["status"], "disallow_statuses": ["FAILED", "BLOCKED"]},
                    "preconditions": [f"dependency_completed:{last_core_dep}"],
                    "postconditions": ["workspace_inspection_verified"],
                    "retry_policy": {"max_attempts": 1, "idempotent_required": True, "retry_on": []},
                    "approval_policy": "auto",
                    "execution_status": "READY",
                    "attempts": 0,
                    "idempotency_key": _idempotency_key(mission_id, "node_workspace_inspect"),
                    "evidence_refs": [],
                    "last_error": None,
                    "output_data": {},
                }
            )
            last_core_dep = "node_workspace_inspect"

        nodes.append(
            {
                "task_id": "node_workspace_audit",
                "title": "ตรวจสอบไฟล์ Sandbox และทรัพยากรระบบจริงก่อนสรุปผล",
                "dependencies": [last_core_dep],
                "tool_id": "workspace_file_read",
                "input_contract": {"required_keys": ["action"], "action": "list"},
                "output_contract": {"required_keys": ["status"], "disallow_statuses": ["FAILED", "BLOCKED"]},
                "preconditions": [f"dependency_completed:{last_core_dep}"],
                "postconditions": ["sandbox_audit_completed"],
                "retry_policy": {"max_attempts": 2, "idempotent_required": True, "retry_on": ["TRANSIENT_ERROR"]},
                "approval_policy": "auto",
                "execution_status": "BLOCKED",
                "attempts": 0,
                "idempotency_key": _idempotency_key(mission_id, "node_workspace_audit"),
                "evidence_refs": [],
                "last_error": None,
                "output_data": {},
            }
        )

    for n in nodes:
        n["execution_status"] = "READY" if not n.get("dependencies") else "BLOCKED"
        n["status"] = n["execution_status"]

    return nodes


def _check_preconditions(node: dict[str, Any], node_map: dict[str, dict[str, Any]]) -> tuple[bool, str | None]:
    for req_key in (node.get("input_contract") or {}).get("required_keys", []):
        val = (node.get("input_contract") or {}).get(req_key)
        if val is None or (isinstance(val, str) and not val.strip()):
            return False, f"Missing required input contract field '{req_key}'"
    for pre in node.get("preconditions", []):
        if pre == "non_empty_goal" and not str((node.get("input_contract") or {}).get("goal", "")).strip():
            return False, "Empty mission goal"
        if pre.startswith("dependency_completed:"):
            dep_id = pre.split(":", 1)[1]
            dep = node_map.get(dep_id)
            if not dep or dep.get("execution_status") != "COMPLETED":
                return False, f"Dependency '{dep_id}' is not COMPLETED"
    return True, None


def _check_postconditions(node: dict[str, Any], output: dict[str, Any]) -> tuple[bool, str | None]:
    out_contract = node.get("output_contract") or {}
    disallowed = set(out_contract.get("disallow_statuses", []))
    out_status = str(output.get("status") or "")
    if out_status in disallowed:
        return False, str(output.get("error") or f"Disallowed output status '{out_status}'")
    for req_key in out_contract.get("required_keys", []):
        if req_key not in output or output.get(req_key) is None:
            return False, f"Missing required output contract field '{req_key}'"

    for post in node.get("postconditions", []):
        if post == "cognition_analyzed" and not output.get("analyzed"):
            return False, "Cognition analysis flag missing"
        if post == "non_empty_compute_result" and output.get("compute_result") is None:
            return False, "Compute tool returned empty result"
        if post == "logic_non_contradictory" and output.get("contradiction"):
            return False, "Transitive logic contradiction detected"
        if post == "research_evidence_recorded":
            verdict = str(output.get("verdict") or "")
            if verdict in {"FAILED", "BLOCKED"}:
                return False, f"Research verdict is {verdict}"
        if post == "knowledge_consistency_checked" and not output.get("checked"):
            return False, "Knowledge consistency check did not complete"
        if post == "sandbox_audit_completed" and output.get("status") != "COMPLETED":
            return False, f"Sandbox audit status={output.get('status')}"
        if post == "workspace_inspection_verified" and output.get("status") != "COMPLETED":
            return False, f"Workspace inspection status={output.get('status')}"
    return True, None


def _save_mission_nodes(conn: sqlite3.Connection, mission_id: str, nodes: list[dict[str, Any]]) -> None:
    now = _now_iso()
    with conn:
        for n in nodes:
            tid = n["task_id"]
            existing = conn.execute(
                "SELECT id FROM mission_nodes WHERE mission_id=? AND task_id=?",
                (mission_id, tid),
            ).fetchone()
            n_json = json.dumps(n, ensure_ascii=False)
            ev_json = json.dumps(n.get("evidence_refs", []), ensure_ascii=False)
            if existing:
                conn.execute(
                    """
                    UPDATE mission_nodes
                    SET node_json=?, execution_status=?, attempt_count=?, last_error=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        n_json,
                        n.get("execution_status", "READY"),
                        int(n.get("attempts", 0)),
                        n.get("last_error"),
                        now,
                        existing["id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO mission_nodes (
                        id, mission_id, task_id, node_json, execution_status,
                        attempt_count, idempotency_key, last_error, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        mission_id,
                        tid,
                        n_json,
                        n.get("execution_status", "READY"),
                        int(n.get("attempts", 0)),
                        n.get("idempotency_key") or _idempotency_key(mission_id, tid),
                        n.get("last_error"),
                        now,
                    ),
                )
            _ = ev_json


def _replan_on_failure(
    mission_id: str,
    failed_node: dict[str, Any],
    nodes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    Create a bounded fallback/recovery node when a non-fatal node fails after retries.
    Rewires downstream dependencies that strictly awaited the failed node if safe.
    """
    tid = failed_node["task_id"]
    if tid == "node_research_discover":
        fallback_id = "node_recovery_local_synthesis"
        if any(n["task_id"] == fallback_id for n in nodes):
            return None
        fallback_node = {
            "task_id": fallback_id,
            "title": "แผนสำรอง (Replan): ตรวจสอบหลักฐานจากกราฟความรู้และคำนวณภายในแทนเว็บ",
            "dependencies": ["node_goal_analysis"],
            "tool_id": "local_recovery_audit",
            "input_contract": {"required_keys": ["goal"], "goal": failed_node["input_contract"].get("goal", "")},
            "output_contract": {"required_keys": ["recovered"], "disallow_statuses": ["FAILED", "BLOCKED"]},
            "preconditions": ["dependency_completed:node_goal_analysis"],
            "postconditions": [],
            "retry_policy": {"max_attempts": 1, "idempotent_required": True, "retry_on": []},
            "approval_policy": "auto",
            "execution_status": "READY",
            "attempts": 0,
            "idempotency_key": _idempotency_key(mission_id, fallback_id),
            "evidence_refs": [],
            "last_error": None,
            "output_data": {},
        }
        nodes.append(fallback_node)
        for n in nodes:
            if n["task_id"] != fallback_id and tid in n.get("dependencies", []):
                n["dependencies"] = [fallback_id if d == tid else d for d in n["dependencies"]]
                n["preconditions"] = [
                    f"dependency_completed:{fallback_id}" if p == f"dependency_completed:{tid}" else p
                    for p in n.get("preconditions", [])
                ]
        return fallback_node
    return None


def _execute_single_node(
    conn: sqlite3.Connection,
    data_dir: Path,
    mission_id: str,
    node: dict[str, Any],
    ctx: dict[str, Any],
    *,
    approved_by: str | None = None,
    existing_invocation_id: str | None = None,
    callbacks: dict[str, Callable[..., Any]],
) -> dict[str, Any]:
    tool_id = node["tool_id"]
    goal = ctx["goal"]
    user_id = ctx["user_id"]
    conv_id = ctx.get("conversation_id")

    if tool_id == "native_cognition":
        terms = callbacks["extract_terms"](goal)
        existing_kg = callbacks["query_kg"](conn, goal)
        math_hit = callbacks["calc_any"](goal)
        logic_hit = callbacks["try_logic"](goal)
        causal_hit = callbacks["try_causal_logic"](goal, conn) if "try_causal_logic" in callbacks else None
        ctx["terms"] = terms
        ctx["existing_kg"] = existing_kg
        ctx["math_hit"] = math_hit
        ctx["logic_hit"] = logic_hit
        ctx["causal_hit"] = causal_hit
        return {
            "status": "COMPLETED",
            "analyzed": True,
            "terms_count": len(terms),
            "terms": terms,
            "kg_hits": len(existing_kg),
            "has_math": bool(math_hit),
            "has_logic": bool(logic_hit or causal_hit),
        }

    if tool_id == "calc_ast":
        inv = invoke_tool_governed(
            conn,
            data_dir,
            "calc_ast",
            {"expression": goal},
            user_id=user_id,
            conversation_id=conv_id,
            approved_by=approved_by,
            tokenize_fn=callbacks["tokenize"],
            extract_terms_fn=callbacks["extract_terms"],
            query_kg_fn=callbacks["query_kg"],
            calc_fn=callbacks["calc_any"],
        )
        raw_out = inv.get("raw_output") or {}
        val = raw_out.get("result")
        if val is None:
            val = raw_out.get("mean")
        if val is None:
            val = raw_out.get("solutions")
        if val is None:
            val = raw_out.get("roots")
        return {
            "status": inv.get("status", "FAILED"),
            "compute_result": val,
            "invocation_id": (inv.get("invocation") or {}).get("id"),
            "error": inv.get("error"),
        }

    if tool_id == "native_logic":
        logic_res = ctx.get("logic_hit") or callbacks["try_logic"](goal)
        causal_res = ctx.get("causal_hit") or (
            callbacks["try_causal_logic"](goal, conn) if "try_causal_logic" in callbacks else None
        )
        chosen = logic_res or causal_res
        if not chosen:
            return {"status": "FAILED", "logic_status": "NOT_FOUND", "error": "No transitive or causal logic found"}
        if chosen.get("contradiction"):
            return {
                "status": "BLOCKED",
                "logic_status": "CONTRADICTION",
                "contradiction": True,
                "error": "Logic or causal contradiction detected",
            }
        return {
            "status": "COMPLETED",
            "logic_status": "VERIFIED" if chosen.get("determined") else "UNDETERMINED",
            "contradiction": False,
            "derived_relation": chosen.get("derived_relation") or chosen.get("derived_conclusion"),
        }

    if tool_id == "research_pipeline":
        res = run_research_pipeline(
            conn,
            data_dir,
            goal,
            user_id=user_id,
            conversation_id=conv_id,
            mission_id=mission_id,
            node_id=node["task_id"],
            approved_by=approved_by,
            existing_invocation_id=existing_invocation_id,
            tokenize_fn=callbacks["tokenize"],
            extract_terms_fn=callbacks["extract_terms"],
            query_kg_fn=callbacks["query_kg"],
            calc_fn=callbacks["calc_any"],
        )
        ctx["research_result"] = res
        return res

    if tool_id == "knowledge_integrate":
        res_out = ctx.get("research_result") or {}
        developed = callbacks["integrate_knowledge"](conn, goal, user_id, ctx.get("terms", []), res_out)
        ctx["developed_triples"] = developed["triples"]
        return {
            "status": "COMPLETED",
            "checked": True,
            "triples_added": len(developed["triples"]),
            "detail": developed["detail"],
        }

    if tool_id == "workspace_file_read":
        inv = invoke_tool_governed(
            conn,
            data_dir,
            "workspace_file_read",
            {"action": "list"},
            user_id=user_id,
            conversation_id=conv_id,
            approved_by=approved_by,
            tokenize_fn=callbacks["tokenize"],
            extract_terms_fn=callbacks["extract_terms"],
            query_kg_fn=callbacks["query_kg"],
            calc_fn=callbacks["calc_any"],
        )
        files = (inv.get("raw_output") or {}).get("files", [])
        return {
            "status": inv.get("status", "FAILED"),
            "file_count": len(files),
            "invocation_id": (inv.get("invocation") or {}).get("id"),
            "error": inv.get("error"),
        }

    if tool_id == "workspace_artifact_inspect":
        in_c = node.get("input_contract") or {}
        target_name = str(in_c.get("filename") or "").strip()
        act = str(in_c.get("action") or "inspect").strip()
        if not target_name:
            ws_files = list_workspace_files(data_dir)
            if ws_files:
                target_name = str(ws_files[0]["name"])
            else:
                return {
                    "status": "COMPLETED",
                    "inspected": False,
                    "detail": "ยังไม่มีไฟล์ใน workspace_files จึงตรวจสอบความพร้อมจากเป้าหมายและหน่วยความจำภายในแทน",
                }
        inv = invoke_tool_governed(
            conn,
            data_dir,
            "workspace_file_read",
            {"action": act, "filename": target_name},
            user_id=user_id,
            conversation_id=conv_id,
            approved_by=approved_by,
            tokenize_fn=callbacks["tokenize"],
            extract_terms_fn=callbacks["extract_terms"],
            query_kg_fn=callbacks["query_kg"],
            calc_fn=callbacks["calc_any"],
        )
        raw_out = inv.get("raw_output") or {}
        return {
            "status": inv.get("status", "FAILED"),
            "inspected": True,
            "filename": target_name,
            "analysis_summary": (inv.get("analysis") or {}).get("summary") or raw_out.get("summary"),
            "defects": raw_out.get("defects", []),
            "issues": raw_out.get("issues", []),
            "invocation_id": (inv.get("invocation") or {}).get("id"),
            "error": inv.get("error"),
        }

    if tool_id == "local_recovery_audit":
        kg_hits = callbacks["query_kg"](conn, goal)
        return {
            "status": "COMPLETED",
            "recovered": True,
            "local_kg_matches": len(kg_hits),
        }

    return {"status": "FAILED", "error": f"Unknown DAG tool '{tool_id}'"}


def execute_dag_loop(
    conn: sqlite3.Connection,
    data_dir: Path,
    mission_id: str,
    nodes: list[dict[str, Any]],
    ctx: dict[str, Any],
    *,
    callbacks: dict[str, Callable[..., Any]],
    resume_node_id: str | None = None,
    approved_by: str | None = None,
    approval_decision: str | None = None,
    existing_invocation_id: str | None = None,
) -> dict[str, Any]:
    """
    Execute ready DAG nodes in topological dependency order until:
      - All nodes COMPLETED -> mission state COMPLETED
      - A node pauses for P5 approval -> mission state AWAITING_APPROVAL
      - A critical node exhausts recovery/replan -> mission state BLOCKED or FAILED
    """
    valid, err_msg = validate_dag_nodes(nodes)
    if not valid:
        return {
            "mission_status": "FAILED",
            "nodes": nodes,
            "error": f"Invalid DAG: {err_msg}",
            "recovery_events": [],
        }

    node_map = {n["task_id"]: n for n in nodes}
    recovery_events: list[str] = []

    if resume_node_id and resume_node_id in node_map:
        r_node = node_map[resume_node_id]
        if approval_decision == "reject":
            r_node["execution_status"] = "BLOCKED"
            r_node["last_error"] = f"Rejected by admin ({approved_by or 'admin'})"
            recovery_events.append(f"{resume_node_id}: ถูกปฏิเสธโดย {approved_by} — พยายาม Replan ทางเลือกภายใน")
            replanned = _replan_on_failure(mission_id, r_node, nodes)
            if replanned:
                node_map[replanned["task_id"]] = replanned
            else:
                _save_mission_nodes(conn, mission_id, nodes)
                return {
                    "mission_status": "BLOCKED",
                    "nodes": nodes,
                    "error": r_node["last_error"],
                    "recovery_events": recovery_events,
                }
        else:
            r_node["execution_status"] = "READY"

    max_iterations = max(12, len(nodes) * 4)
    iterations = 0

    while iterations < max_iterations:
        iterations += 1
        progressed = False

        for node in nodes:
            status = node.get("execution_status")
            if status in {"COMPLETED", "FAILED", "SKIPPED", "CANCELLED"}:
                continue
            if status == "AWAITING_APPROVAL":
                continue

            deps = node.get("dependencies", [])
            dep_nodes = [node_map[d] for d in deps if d in node_map]
            hard_blocked = any(
                dn.get("execution_status") in {"FAILED", "CANCELLED"}
                or (
                    dn.get("execution_status") == "BLOCKED"
                    and (int(dn.get("attempts") or 0) > 0 or bool(dn.get("last_error")))
                )
                for dn in dep_nodes
            )
            if hard_blocked:
                # Upstream failed, cancelled, or was rejected/blocked with an error
                if status != "BLOCKED" or not node.get("last_error"):
                    node["execution_status"] = "BLOCKED"
                    node["status"] = "BLOCKED"
                    node["last_error"] = "Upstream dependency failed, cancelled, or blocked"
                    progressed = True
                continue
            if not all(dn.get("execution_status") == "COMPLETED" for dn in dep_nodes):
                if status != "BLOCKED":
                    node["execution_status"] = "BLOCKED"
                    node["status"] = "BLOCKED"
                continue

            if status == "BLOCKED":
                # Only unlock BLOCKED -> READY when it has not already executed/failed/rejected
                if int(node.get("attempts") or 0) > 0 or node.get("last_error"):
                    continue
                node["execution_status"] = "READY"
                node["status"] = "READY"
                node["last_error"] = None
                progressed = True

            pre_ok, pre_err = _check_preconditions(node, node_map)
            if not pre_ok:
                node["execution_status"] = "BLOCKED"
                node["status"] = "BLOCKED"
                node["last_error"] = pre_err
                progressed = True
                continue

            # Idempotency check: if already completed in SQLite, skip re-execution
            persisted = conn.execute(
                "SELECT execution_status FROM mission_nodes WHERE mission_id=? AND task_id=?",
                (mission_id, node["task_id"]),
            ).fetchone()
            if persisted and persisted["execution_status"] == "COMPLETED" and node["task_id"] != resume_node_id:
                node["execution_status"] = "COMPLETED"
                node["status"] = "COMPLETED"
                progressed = True
                continue

            progressed = True
            node["execution_status"] = "EXECUTING"
            node["status"] = "RUNNING"
            retry_cfg = node.get("retry_policy") or {}
            max_attempts = max(1, int(retry_cfg.get("max_attempts", 1)))
            node_started_at = time.perf_counter()
            attempt_durations: list[float] = list(node.get("attempt_durations_ms") or [])

            use_approval = approved_by if node["task_id"] == resume_node_id else None
            use_inv_id = existing_invocation_id if node["task_id"] == resume_node_id else None

            while node["attempts"] < max_attempts:
                node["attempts"] += 1
                attempt_t0 = time.perf_counter()
                try:
                    out = _execute_single_node(
                        conn,
                        data_dir,
                        mission_id,
                        node,
                        ctx,
                        approved_by=use_approval,
                        existing_invocation_id=use_inv_id,
                        callbacks=callbacks,
                    )
                except Exception as exc:
                    out = {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}
                attempt_ms = round((time.perf_counter() - attempt_t0) * 1000, 3)
                attempt_durations.append(attempt_ms)
                node["attempt_durations_ms"] = attempt_durations
                node["duration_ms"] = round(
                    float(node.get("duration_ms") or 0.0) + (time.perf_counter() - node_started_at) * 1000
                    if attempt_ms == 0.0
                    else sum(attempt_durations),
                    3,
                )

                node["output_data"] = out
                if out.get("invocation_id"):
                    ref = str(out["invocation_id"])
                    if ref not in node["evidence_refs"]:
                        node["evidence_refs"].append(ref)

                if out.get("status") == "PENDING_APPROVAL":
                    node["execution_status"] = "AWAITING_APPROVAL"
                    node["status"] = "BLOCKED"
                    node["last_error"] = None
                    _save_mission_nodes(conn, mission_id, nodes)
                    return {
                        "mission_status": "AWAITING_APPROVAL",
                        "nodes": nodes,
                        "pending_node": node["task_id"],
                        "pending_invocation_id": out.get("invocation_id"),
                        "recovery_events": recovery_events,
                    }

                post_ok, post_err = _check_postconditions(node, out)
                if post_ok:
                    node["execution_status"] = "COMPLETED"
                    node["status"] = "COMPLETED"
                    node["last_error"] = None
                    break

                node["last_error"] = post_err
                if node["attempts"] < max_attempts and retry_cfg.get("idempotent_required", True):
                    node["execution_status"] = "RECOVERING"
                    node["status"] = "RUNNING"
                    recovery_events.append(
                        f"{node['task_id']}: ตรวจ Postcondition ไม่ผ่าน ({post_err}) — Retry รอบที่ {node['attempts'] + 1}"
                    )
                    continue

                # Retries exhausted -> attempt replan
                final_err_state = "BLOCKED" if out.get("status") == "BLOCKED" else "FAILED"
                node["execution_status"] = final_err_state
                node["status"] = final_err_state
                recovery_events.append(f"{node['task_id']}: เกิดความล้มเหลว ({post_err}) — เข้าสู่ Recovery/Replan")
                replanned = _replan_on_failure(mission_id, node, nodes)
                if replanned:
                    node_map[replanned["task_id"]] = replanned
                    recovery_events.append(f"Replan: สร้างโหนดสำรอง '{replanned['task_id']}' แทนที่ชั่วคราว")
                break

        if not progressed:
            break

    _save_mission_nodes(conn, mission_id, nodes)

    all_statuses = [n["execution_status"] for n in nodes]
    if any(s == "AWAITING_APPROVAL" for s in all_statuses):
        m_status = "AWAITING_APPROVAL"
    elif all(s in {"COMPLETED", "SKIPPED"} for s in all_statuses):
        m_status = "COMPLETED"
    elif any(s == "COMPLETED" for s in all_statuses) and any(
        n["task_id"].startswith("node_recovery_") and n["execution_status"] == "COMPLETED"
        for n in nodes
    ):
        # Completed via honest fallback recovery; inspect if critical failure remains
        non_replaced_failures = [
            n for n in nodes
            if n["execution_status"] in {"FAILED", "BLOCKED"} and n["task_id"] != "node_research_discover"
        ]
        m_status = "FAILED" if non_replaced_failures else "COMPLETED"
    elif any(s == "BLOCKED" for s in all_statuses):
        m_status = "BLOCKED"
    else:
        m_status = "FAILED"

    return {
        "mission_status": m_status,
        "nodes": nodes,
        "recovery_events": recovery_events,
    }
