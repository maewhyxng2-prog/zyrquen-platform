"""
Tool Intelligence, Selection & Controlled Parallel Orchestrator for ZYRQUEN.
----------------------------------------------------------------------------
Coordinates all 10 background support systems without duplicating core engines:
  1. Tool Intelligence & Selection (intent + dependency + role + Task Memory + risk)
  2. Tool Dependency Manager (cycles, SemVer constraints, topological waves)
  3. Context Manager (minimal scoped payload, secret redaction, footprint telemetry)
  4. Failure Recovery (error taxonomy, bounded idempotent retries, safe fallback, checkpointing)
  5. Task Memory (historical success/latency boosts + recording verified lessons)
  6. Controlled Parallel Execution (ThreadPoolExecutor per wave within ResourceManager cap)
  7. Isolated Sandbox Execution (via testing.sandbox_run / sandbox.py)
  8. Quality Assurance Engine (independent verification & 4-state verdict)
  9. Resource & Workload Manager (RAM/Disk/CPU admission & slot budgets)
 10. Observability & Idempotency (trace IDs, per-step duration, deduplication)
"""

from __future__ import annotations

import concurrent.futures
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .context_manager import ContextManager
from .contracts import evaluate_capability_permission
from .dependency_manager import ToolDependencyManager
from .quality_assurance import aggregate_plan_verdict, verify_capability_delivery
from .recovery import (
    build_step_idempotency_key,
    classify_error,
    init_orchestration_schema,
    recommend_recovery,
)
from .resource_manager import ResourceManager, get_resource_manager
from .task_memory import (
    init_task_memory_schema,
    record_task_memory,
    retrieve_relevant_memories,
    summarize_capability_track_record,
)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _db_file_path(conn: sqlite3.Connection | None) -> str | None:
    if conn is None:
        return None
    try:
        rows = conn.execute("PRAGMA database_list").fetchall()
        for r in rows:
            name = r["name"] if isinstance(r, sqlite3.Row) else r[1]
            fpath = r["file"] if isinstance(r, sqlite3.Row) else r[2]
            if name == "main" and fpath:
                return str(fpath)
    except Exception:
        return None
    return None


_GOAL_INTENT_EXPANSIONS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("ซ่อมบั๊ก", "แก้บั๊ก", "แก้ไขโค้ด", "แพตช์", "patch", "edit file"), ("patch", "replace", "diff", "sandbox")),
    (("สร้างโปรเจกต์", "ขึ้นโครง", "scaffold", "boilerplate", "template"), ("scaffold", "template", "module")),
    (("รีแฟกเตอร์", "เปลี่ยนชื่อฟังก์ชัน", "refactor", "rename symbol"), ("refactor", "rename", "ast")),
    (("วินิจฉัย", "สาเหตุ error", "traceback", "stack trace", "diagnose"), ("diagnose", "traceback", "error")),
    (("ความเข้ากันได้", "compatibility", "conflict", "เวอร์ชันขัดกัน"), ("compatibility", "conflict", "version")),
    (("ไมเกรชัน", "alembic", "migration", "schema db"), ("migration", "alembic", "schema")),
    (("สร้าง api", "endpoint", "rest route", "fastapi", "express"), ("endpoint", "rest", "route", "api")),
    (("การเข้าถึง", "accessibility", "a11y", "alt text", "aria", "หน้าเว็บ"), ("a11y", "accessibility", "alt", "role")),
    (("อนุมาน schema", "infer schema", "ชนิดคอลัมน์", "primary key"), ("schema", "infer", "columns")),
    (("ข้อมูลซ้ำ", "แถวซ้ำ", "deduplicate", "duplicate rows", "near duplicate"), ("duplicate", "dedup", "jaccard")),
    (("ผิดปกติ", "ค่าผิดปกติ", "outlier", "anomaly", "iqr"), ("anomaly", "outlier", "iqr")),
    (("กฎความถูกต้อง", "semantic", "domain rule", "range check"), ("semantic", "rules", "constraints")),
    (("สายข้อมูล", "ที่มาข้อมูล", "lineage", "provenance dataset"), ("lineage", "dataset", "origin")),
    (("เทียบชุดข้อมูล", "version compare", "drift", "data diff"), ("compare", "version", "drift")),
    (("แหล่งที่มา", "provenance", "ความน่าเชื่อถือ", "credit", "authoritative"), ("provenance", "authority", "credibility")),
    (("ทวนสอบข้ออ้าง", "fact check", "verify claim", "claim verification"), ("claim", "verify", "corroborate")),
    (("ลำดับเวลา", "ล้าสมัย", "temporal", "chronological", "stale"), ("temporal", "timestamp", "stale")),
    (("ช่องว่างความรู้", "ไม่รู้เรื่อง", "knowledge gap", "missing knowledge"), ("gap", "missing", "knowledge")),
    (("ความขัดแย้ง", "ข้อมูลแย้งกัน", "contradict", "resolve conflict"), ("contradiction", "conflict", "resolve")),
    (("ครอบคลุม", "line coverage", "coverage", "uncovered"), ("coverage", "trace", "lines")),
    (("กลายพันธุ์", "mutation test", "mutant", "test strength"), ("mutation", "mutant", "quality")),
    (("สุ่มทดสอบ", "property based", "invariant", "fuzz", "counterexample"), ("property", "invariant", "seed")),
    (("ความเร็ว", "ประสิทธิภาพ", "หน่วยความจำ", "latency", "memory profile", "tracemalloc"), ("performance", "profile", "latency", "memory")),
    (("ถดถอย", "regression", "baseline compare"), ("regression", "baseline", "compare")),
    (("สาเหตุราก", "root cause", "จัดกลุ่ม error", "failure cluster"), ("root_cause", "failure", "cluster")),
    (("sbom", "รายการแพ็กเกจความปลอดภัย", "cyclonedx", "bill of materials"), ("sbom", "cyclonedx", "inventory")),
    (("สัญญาอนุญาต", "license", "gpl", "mit", "copyleft"), ("license", "compliance", "copyleft")),
    (("ภัยคุกคาม", "threat model", "stride", "attack surface"), ("threat", "stride", "surface")),
    (("ตรวจสิทธิ์", "rbac audit", "permission matrix", "misconfig"), ("permission", "rbac", "audit")),
    (("ความสมบูรณ์ไฟล์", "tamper", "sha256 artifact", "artifact integrity"), ("integrity", "sha256", "artifact", "tamper")),
    (("แตกเป้าหมาย", "แยกงานย่อย", "decompose", "subtask"), ("decompose", "subtask", "dag")),
    (("เหตุและผล", "causal", "สาเหตุต่อเนื่อง", "impact graph"), ("causal", "root_cause", "graph")),
    (("เปรียบเทียบกลยุทธ์", "strategy compare", "เลือกแผน", "tradeoff"), ("strategy", "compare", "rank")),
    (("ความไม่แน่นอน", "ความมั่นใจ", "uncertainty", "abstain", "confidence"), ("uncertainty", "confidence", "abstain")),
    (("ปรับแผน", "ลดซ้ำ", "parallel schedule", "optimize plan"), ("optimize", "parallel", "deduplicate")),
    (("บันทึกบทเรียน", "เรียนรู้ผล", "outcome learning", "task memory feedback"), ("learn", "memory", "outcome")),
)


def _expand_goal_terms(lowered_goal: str) -> tuple[list[str], set[str]]:
    tokens = re.findall(r"[A-Za-z0-9_.\-]+|[\u0E00-\u0E7F]{2,}", lowered_goal)
    expanded: set[str] = set()
    for triggers, additions in _GOAL_INTENT_EXPANSIONS:
        if any(t in lowered_goal for t in triggers):
            expanded.update(additions)
    return [t for t in tokens if len(t) >= 2], expanded


def select_tools_for_goal(
    registry: Any,
    goal: str,
    *,
    conn: sqlite3.Connection | None = None,
    user_role: str = "user",
    max_candidates: int = 8,
    dependency_manager: ToolDependencyManager | None = None,
    resource_manager: ResourceManager | None = None,
) -> dict[str, Any]:
    """
    Intelligent, deterministic Tool Selection combining:
      - Bilingual intent & keyword alignment with the goal (across all 75 capabilities)
      - Role permission & lifecycle gating (READY only in primary plan)
      - Tool Dependency Manager checks
      - Task Memory empirical success rates & failure lessons
      - Resource Manager headroom check
    Never chooses tools randomly.
    """
    dep_mgr = dependency_manager or ToolDependencyManager()
    res_mgr = resource_manager or get_resource_manager()

    clean_goal = str(goal or "").strip()
    lowered = clean_goal.lower()
    tokens, expanded_terms = _expand_goal_terms(lowered)

    track_records: dict[str, dict[str, Any]] = {}
    memory_context: dict[str, Any] = {"matches": [], "episodic_matches": [], "success_examples": [], "failure_lessons": []}
    if conn is not None:
        track_records = summarize_capability_track_record(conn)
        memory_context = retrieve_relevant_memories(conn, clean_goal, limit=6)

    # Boost capabilities that succeeded in similar past Task Memory entries, penalize recent unrecovered failures
    memory_boosted_caps: set[str] = set()
    for ex in memory_context.get("success_examples", []):
        try:
            for cid in json.loads(ex.get("capability_sequence_json") or "[]"):
                memory_boosted_caps.add(cid)
        except Exception:
            pass
    memory_penalized_caps: set[str] = set()
    for fail_ex in memory_context.get("failure_lessons", []):
        try:
            for cid in json.loads(fail_ex.get("capability_sequence_json") or "[]"):
                memory_penalized_caps.add(cid)
        except Exception:
            pass

    selected_ready: list[dict[str, Any]] = []
    in_dev_candidates: list[dict[str, Any]] = []
    blocked_candidates: list[dict[str, Any]] = []
    selected_toolkits: set[str] = set()

    for cid in registry.list_capability_ids():
        spec = registry.get_spec(cid)
        if spec is None:
            continue

        cap_id_low = spec.id.lower()
        haystack = " ".join([
            cap_id_low,
            spec.toolkit_id.lower(),
            spec.name.lower(),
            spec.description.lower(),
            " ".join(spec.keywords).lower(),
        ])
        keyword_hits: list[str] = []
        raw_score = 0.0
        for kw in spec.keywords:
            kw_low = kw.lower()
            if kw_low in lowered:
                raw_score += 3.5
                keyword_hits.append(kw)
            elif kw_low in expanded_terms:
                raw_score += 2.5
                keyword_hits.append(f"intent:{kw}")
        for tok in tokens:
            if tok in haystack:
                raw_score += 1.0
        for exp in expanded_terms:
            if exp in cap_id_low:
                raw_score += 2.0

        if raw_score <= 0:
            continue

        if cid in memory_boosted_caps:
            raw_score += 2.0
        if cid in memory_penalized_caps:
            raw_score = max(0.5, raw_score - 1.0)

        dep_check = dep_mgr.check_capability(registry, cid)
        perm = evaluate_capability_permission(spec, user_role)
        hist = track_records.get(cid) or {"runs": 0, "success_rate": 1.0, "avg_latency_ms": 0.0}
        # Weight empirical track record as Task Memory accumulates real outcomes
        hist_multiplier = (0.4 + 0.6 * hist["success_rate"]) if hist["runs"] >= 1 else 1.0
        final_score = round(raw_score * hist_multiplier, 3)

        rationale: list[str] = []
        if keyword_hits:
            rationale.append(f"keyword_match={','.join(keyword_hits[:4])}")
        if cid in memory_boosted_caps:
            rationale.append("proven_in_task_memory")
        if cid in memory_penalized_caps:
            rationale.append("prior_failure_caution")
        if hist["runs"] > 0:
            rationale.append(f"success_rate={hist['success_rate']} ({hist['runs']} runs)")
        if not dep_check["ok"]:
            rationale.append(f"dependency_issue={','.join(dep_check['missing'])}")
        if not perm["allowed"]:
            rationale.append(f"permission_blocked={perm['reason']}")

        entry = {
            "capability_id": spec.id,
            "toolkit_id": spec.toolkit_id,
            "name": spec.name,
            "version": spec.version,
            "lifecycle_status": spec.lifecycle_status,
            "score": final_score,
            "permission": perm,
            "dependency_ok": dep_check["ok"],
            "dependency_check": dep_check,
            "track_record": hist,
            "selection_rationale": rationale,
            "example_input": spec.example_input,
        }

        if spec.lifecycle_status == "IN_DEVELOPMENT":
            in_dev_candidates.append(entry)
        elif spec.lifecycle_status == "DEPRECATED":
            continue
        elif not dep_check["ok"] or not perm["allowed"]:
            blocked_candidates.append(entry)
        else:
            selected_ready.append(entry)
            selected_toolkits.add(spec.toolkit_id)

    selected_ready.sort(key=lambda x: (-x["score"], x["capability_id"]))
    in_dev_candidates.sort(key=lambda x: (-x["score"], x["capability_id"]))
    blocked_candidates.sort(key=lambda x: (-x["score"], x["capability_id"]))

    admission = res_mgr.evaluate_admission(requested_workers=min(4, max(1, len(selected_ready))))
    return {
        "ok": True,
        "goal": clean_goal,
        "principle": "Build Once -> Register Once -> Reuse Everywhere",
        "selected_toolkits": sorted(selected_toolkits),
        "selected_capabilities": selected_ready[:max_candidates],
        "reuse_existing_count": len(selected_ready),
        "in_development_candidates": in_dev_candidates,
        "blocked_candidates": blocked_candidates,
        "task_memory_hints": {
            "success_examples_count": len(memory_context["success_examples"]),
            "failure_lessons_count": len(memory_context["failure_lessons"]),
            "episodic_matches_count": len(memory_context["episodic_matches"]),
        },
        "resource_admission": admission,
        "duplicate_creation_blocked": len(selected_ready) > 0,
    }


def execute_orchestrated_plan(
    registry: Any,
    goal: str,
    steps: list[dict[str, Any]],
    *,
    conn: sqlite3.Connection | None = None,
    data_dir: Path | None = None,
    user_id: str = "system",
    user_role: str = "user",
    shared_context: dict[str, Any] | None = None,
    idempotency_scope: str | None = None,
    enable_parallel: bool = True,
    max_retries: int = 2,
    dependency_manager: ToolDependencyManager | None = None,
    resource_manager: ResourceManager | None = None,
    context_manager: ContextManager | None = None,
) -> dict[str, Any]:
    """
    Execute a multi-step DAG through the full Background Support Architecture:
      DependencyManager -> ResourceManager -> ContextManager -> Parallel/Sequential
      Execution -> Failure Recovery -> QualityAssuranceEngine -> TaskMemory & Trace.
    """
    started_all = time.perf_counter()
    dep_mgr = dependency_manager or ToolDependencyManager()
    res_mgr = resource_manager or get_resource_manager()
    ctx_mgr = context_manager or ContextManager()

    if conn is not None:
        init_orchestration_schema(conn)
        init_task_memory_schema(conn)

    # 1. Dependency & Cycle/Version Conflict Check
    wave_plan = dep_mgr.plan_execution_waves(steps, registry=registry)
    if not wave_plan["ok"]:
        return {
            "ok": False,
            "status": "FAILED",
            "delivery_verdict": "FAILED",
            "error_code": "VERSION_CONFLICT" if wave_plan.get("conflicts") else "DEPENDENCY_MISSING",
            "error": wave_plan.get("error"),
            "conflicts": wave_plan.get("conflicts", []),
            "external_models_used": False,
        }

    waves: list[list[dict[str, Any]]] = wave_plan["waves"]
    max_wave_width = max((len(w) for w in waves), default=1)
    admission = res_mgr.evaluate_admission(requested_workers=max_wave_width if enable_parallel else 1)
    if not admission["allowed"]:
        return {
            "ok": False,
            "status": "FAILED",
            "delivery_verdict": "FAILED",
            "error_code": admission.get("error_code") or "RESOURCE_LIMIT",
            "error": admission.get("reason"),
            "system": admission.get("system"),
            "external_models_used": False,
        }

    run_id = str(uuid.uuid4())
    scope = str(idempotency_scope or run_id)
    now = _now_iso()

    # Check run-level idempotency if idempotency_scope was explicitly supplied
    if conn is not None and idempotency_scope:
        prev_run = conn.execute(
            "SELECT * FROM orchestration_runs WHERE idempotency_key=? AND status IN ('SUCCESS', 'PARTIAL_SUCCESS')",
            (idempotency_scope,),
        ).fetchone()
        if prev_run:
            prev_steps = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM orchestration_steps WHERE run_id=? ORDER BY rowid ASC",
                    (prev_run["id"],),
                ).fetchall()
            ]
            return {
                "ok": True,
                "run_id": prev_run["id"],
                "idempotent_replay": True,
                "status": prev_run["status"],
                "delivery_verdict": prev_run["status"],
                "goal": prev_run["goal"],
                "steps": prev_steps,
                "qa_summary": json.loads(prev_run["qa_summary_json"] or "{}"),
                "recovery_events": json.loads(prev_run["recovery_events_json"] or "[]"),
                "external_models_used": False,
            }

    if conn is not None:
        with conn:
            conn.execute(
                """
                INSERT INTO orchestration_runs (
                    id, idempotency_key, goal, user_id, status, plan_json,
                    context_summary_json, qa_summary_json, recovery_events_json,
                    total_latency_ms, external_models_used, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'RUNNING', ?, '{}', '{}', '[]', 0, 0, ?, ?)
                """,
                (run_id, idempotency_scope, str(goal)[:500], user_id, json.dumps(steps, ensure_ascii=False), now, now),
            )

    db_path = _db_file_path(conn)
    step_outputs: dict[str, dict[str, Any]] = {}
    step_records: list[dict[str, Any]] = []
    recovery_events: list[str] = []
    context_footprints: list[dict[str, Any]] = []
    upstream_failed = False

    def _run_one_step(step: dict[str, Any], *, use_separate_conn: bool) -> dict[str, Any]:
        sid = step["step_id"]
        cid = str(step["capability_id"])
        raw_input = dict(step.get("input") or {})
        spec = registry.get_spec(cid)

        # Merge upstream output keys explicitly referenced in `input_from` or shared_context
        step_shared = dict(shared_context or {})
        step_shared.setdefault("goal", goal)
        for dep_id in step.get("depends_on", []):
            if dep_id in step_outputs and isinstance(step_outputs[dep_id].get("output"), dict):
                for k, v in step_outputs[dep_id]["output"].items():
                    step_shared.setdefault(k, v)

        if spec is not None:
            ctx_res = ctx_mgr.build_scoped_input(spec, raw_input, shared_context=step_shared)
            scoped_input = ctx_res["scoped_input"]
            footprint = ctx_res["footprint"]
        else:
            scoped_input = raw_input
            footprint = {"capability_id": cid, "scoped_keys": sorted(raw_input.keys()), "payload_bytes": 0}

        idem_key = build_step_idempotency_key(scope, sid, cid, scoped_input)

        # Idempotent skip if step already succeeded within this idempotency scope
        if conn is not None and not use_separate_conn and idempotency_scope:
            prev_step = conn.execute(
                "SELECT * FROM orchestration_steps WHERE idempotency_key=? AND status='SUCCESS' ORDER BY rowid DESC LIMIT 1",
                (idem_key,),
            ).fetchone()
            if prev_step:
                return {
                    "step_id": sid,
                    "idempotency_key": idem_key,
                    "capability_id": cid,
                    "capability_version": prev_step["capability_version"],
                    "toolkit_id": spec.toolkit_id if spec else "unknown",
                    "status": "SUCCESS",
                    "idempotent_replay": True,
                    "attempts": int(prev_step["attempts"]),
                    "error_code": None,
                    "error": None,
                    "recovery_action": "idempotent_cache_hit",
                    "footprint": footprint,
                    "output": json.loads(prev_step["output_json"] or "{}"),
                    "qa": json.loads(prev_step["qa_json"] or "{}"),
                    "latency_ms": float(prev_step["latency_ms"] or 0.0),
                }

        worker_conn = None
        if use_separate_conn and db_path:
            worker_conn = sqlite3.connect(db_path, timeout=15.0)
            worker_conn.row_factory = sqlite3.Row
        exec_conn = worker_conn if use_separate_conn else conn

        attempts = 0
        max_try = max(1, min(int(step.get("max_retries", max_retries)), 3))
        fallback_list = list(step.get("fallback_capabilities") or [])
        active_cid = cid
        active_spec = spec
        last_res: dict[str, Any] = {}
        last_qa: dict[str, Any] = {}
        last_err_code: str | None = None
        last_err_msg: str | None = None
        rec_action_taken: str | None = None
        step_t0 = time.perf_counter()

        try:
            while attempts < max_try:
                attempts += 1
                last_res = registry.execute(
                    active_cid,
                    scoped_input,
                    user_id=user_id,
                    user_role=user_role,
                    conn=exec_conn,
                    data_dir=data_dir,
                    approved_by=step.get("approved_by"),
                )
                active_spec = registry.get_spec(active_cid)
                last_qa = verify_capability_delivery(active_spec, last_res, data_dir=data_dir)
                if last_qa["verdict"] in {"SUCCESS", "PARTIAL_SUCCESS"} or last_res.get("status") == "PENDING_APPROVAL":
                    break

                last_err_code, last_err_msg = classify_error(
                    last_res,
                    default_msg="; ".join(last_qa.get("blockers") or ["QA failed"]),
                )
                if last_qa["verdict"] == "FAILED" and last_res.get("ok"):
                    last_err_code = "QA_FAILED"

                rec = recommend_recovery(
                    last_err_code,
                    capability_id=active_cid,
                    attempt=attempts,
                    max_attempts=max_try,
                    registry=registry,
                    fallback_candidates=fallback_list,
                )
                if rec["strategy"] == "retry":
                    rec_action_taken = rec["reason"]
                    time.sleep(float(rec.get("backoff_s") or 0.05))
                    continue
                if rec["strategy"] == "fallback_capability":
                    active_cid = rec["fallback_capability_id"]
                    active_spec = registry.get_spec(active_cid)
                    if active_spec is not None:
                        scoped_input = ctx_mgr.build_scoped_input(
                            active_spec, raw_input, shared_context=step_shared
                        )["scoped_input"]
                    rec_action_taken = rec["reason"]
                    continue
                rec_action_taken = rec["reason"]
                break
        finally:
            if worker_conn is not None:
                worker_conn.close()

        step_latency = round((time.perf_counter() - step_t0) * 1000, 2)
        verdict = (
            "PENDING_APPROVAL"
            if last_res.get("status") == "PENDING_APPROVAL"
            else last_qa.get("verdict", "FAILED")
        )
        return {
            "step_id": sid,
            "idempotency_key": idem_key,
            "capability_id": active_cid,
            "capability_version": active_spec.version if active_spec else "0.0.0",
            "toolkit_id": active_spec.toolkit_id if active_spec else "unknown",
            "status": verdict,
            "attempts": attempts,
            "error_code": None if verdict in {"SUCCESS", "PARTIAL_SUCCESS", "PENDING_APPROVAL"} else last_err_code,
            "error": None if verdict in {"SUCCESS", "PARTIAL_SUCCESS", "PENDING_APPROVAL"} else last_err_msg,
            "recovery_action": rec_action_taken,
            "footprint": footprint,
            "output": last_res.get("output") if isinstance(last_res.get("output"), dict) else {},
            "qa": last_qa,
            "latency_ms": step_latency,
        }

    effective_workers = int(admission.get("effective_workers") or 1)
    wave_summaries: list[dict[str, Any]] = []

    for wave_idx, wave in enumerate(waves, start=1):
        # Skip downstream wave if a required dependency step failed or is awaiting approval
        blocked_wave_steps: list[dict[str, Any]] = []
        runnable_steps: list[dict[str, Any]] = []
        for s in wave:
            dep_broken = any(
                step_outputs.get(d, {}).get("status") in {"FAILED", "UNVERIFIED", "PENDING_APPROVAL", "BLOCKED"}
                for d in s.get("depends_on", [])
            )
            if dep_broken:
                blocked_wave_steps.append(s)
            else:
                runnable_steps.append(s)

        for bs in blocked_wave_steps:
            rec = {
                "step_id": bs["step_id"],
                "idempotency_key": build_step_idempotency_key(scope, bs["step_id"], bs["capability_id"], bs.get("input") or {}),
                "capability_id": bs["capability_id"],
                "capability_version": (registry.get_spec(bs["capability_id"]).version if registry.get_spec(bs["capability_id"]) else "0.0.0"),
                "toolkit_id": (registry.get_spec(bs["capability_id"]).toolkit_id if registry.get_spec(bs["capability_id"]) else "unknown"),
                "status": "BLOCKED",
                "attempts": 0,
                "error_code": "DEPENDENCY_MISSING",
                "error": "Skipped because upstream dependency did not reach verified completion.",
                "recovery_action": None,
                "footprint": {"capability_id": bs["capability_id"], "scoped_keys": [], "payload_bytes": 0},
                "output": {},
                "qa": {"verdict": "FAILED", "passed": False, "checks": [], "warnings": [], "blockers": ["Upstream dependency not verified"]},
                "latency_ms": 0.0,
            }
            step_outputs[bs["step_id"]] = rec
            step_records.append(rec)

        run_parallel = (
            enable_parallel
            and len(runnable_steps) > 1
            and effective_workers > 1
            and (db_path is not None or conn is None)
            and res_mgr.acquire_slot(1)
        )
        wave_mode = "parallel" if run_parallel else "sequential"
        wave_results: list[dict[str, Any]] = []

        if run_parallel:
            try:
                workers = min(effective_workers, len(runnable_steps))
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(_run_one_step, s, use_separate_conn=True) for s in runnable_steps]
                    for fut in concurrent.futures.as_completed(futures, timeout=float(admission.get("timeout_s") or 8.0)):
                        wave_results.append(fut.result())
            finally:
                res_mgr.release_slot(1)
        else:
            for s in runnable_steps:
                wave_results.append(_run_one_step(s, use_separate_conn=False))

        # Preserve deterministic ordering matching wave definition
        by_sid = {r["step_id"]: r for r in wave_results}
        for s in runnable_steps:
            rec = by_sid[s["step_id"]]
            step_outputs[rec["step_id"]] = rec
            step_records.append(rec)
            context_footprints.append(rec["footprint"])
            if rec.get("recovery_action"):
                recovery_events.append(f"{rec['step_id']}: {rec['recovery_action']}")
            if rec["status"] in {"FAILED", "UNVERIFIED", "BLOCKED"}:
                upstream_failed = True

        wave_summaries.append({
            "wave": wave_idx,
            "mode": wave_mode,
            "step_ids": [s["step_id"] for s in wave],
        })

    overall_verdict = (
        "PENDING_APPROVAL"
        if any(s["status"] == "PENDING_APPROVAL" for s in step_records)
        else aggregate_plan_verdict(step_records)
    )
    total_latency_ms = round((time.perf_counter() - started_all) * 1000, 2)
    qa_summary = {
        "delivery_verdict": overall_verdict,
        "steps_total": len(step_records),
        "steps_verified": sum(1 for s in step_records if s["status"] == "SUCCESS"),
        "steps_partial": sum(1 for s in step_records if s["status"] == "PARTIAL_SUCCESS"),
        "steps_failed": sum(1 for s in step_records if s["status"] in {"FAILED", "BLOCKED"}),
        "steps_pending_approval": sum(1 for s in step_records if s["status"] == "PENDING_APPROVAL"),
    }

    if conn is not None:
        with conn:
            for s in step_records:
                db_status = s["status"] if s["status"] in {"SUCCESS", "PARTIAL_SUCCESS", "FAILED", "UNVERIFIED", "PENDING_APPROVAL", "BLOCKED"} else "FAILED"
                conn.execute(
                    """
                    INSERT INTO orchestration_steps (
                        id, run_id, step_id, idempotency_key, capability_id, capability_version,
                        status, attempts, error_code, error_message, recovery_action,
                        context_footprint_json, output_json, qa_json, latency_ms, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        run_id,
                        s["step_id"],
                        s["idempotency_key"],
                        s["capability_id"],
                        s["capability_version"],
                        db_status,
                        int(s["attempts"]),
                        s.get("error_code"),
                        s.get("error"),
                        s.get("recovery_action"),
                        json.dumps(s["footprint"], ensure_ascii=False),
                        json.dumps(s["output"], ensure_ascii=False),
                        json.dumps(s["qa"], ensure_ascii=False),
                        float(s["latency_ms"]),
                        _now_iso(),
                    ),
                )
            conn.execute(
                """
                UPDATE orchestration_runs
                SET status=?, context_summary_json=?, qa_summary_json=?,
                    recovery_events_json=?, total_latency_ms=?, updated_at=?
                WHERE id=?
                """,
                (
                    overall_verdict if overall_verdict in {"SUCCESS", "PARTIAL_SUCCESS", "FAILED", "UNVERIFIED", "PENDING_APPROVAL"} else "FAILED",
                    json.dumps(context_footprints, ensure_ascii=False),
                    json.dumps(qa_summary, ensure_ascii=False),
                    json.dumps(recovery_events, ensure_ascii=False),
                    total_latency_ms,
                    _now_iso(),
                    run_id,
                ),
            )

        first_err_step = next((s for s in step_records if s.get("error_code")), None)
        mem_outcome = overall_verdict if overall_verdict in {"SUCCESS", "PARTIAL_SUCCESS", "FAILED", "UNVERIFIED"} else "UNVERIFIED"
        record_task_memory(
            conn,
            trace_id=run_id,
            goal=goal,
            toolkit_ids=[s["toolkit_id"] for s in step_records],
            capability_sequence=[s["capability_id"] for s in step_records],
            outcome_status=mem_outcome,
            error_code=first_err_step.get("error_code") if first_err_step else None,
            error_message=first_err_step.get("error") if first_err_step else None,
            recovery_action="; ".join(recovery_events) if recovery_events else None,
            context_keys=sorted({k for fp in context_footprints for k in fp.get("scoped_keys", [])}),
            latency_ms=total_latency_ms,
            verified=(overall_verdict == "SUCCESS"),
        )

    return {
        "ok": overall_verdict in {"SUCCESS", "PARTIAL_SUCCESS", "PENDING_APPROVAL"},
        "run_id": run_id,
        "goal": goal,
        "status": overall_verdict,
        "delivery_verdict": overall_verdict,
        "waves": wave_summaries,
        "steps": step_records,
        "qa_summary": qa_summary,
        "recovery_events": recovery_events,
        "context_footprints": context_footprints,
        "total_latency_ms": total_latency_ms,
        "telemetry": {
            "waves_count": len(wave_summaries),
            "recovery_count": len(recovery_events),
            "memory_recorded": conn is not None,
            "avg_step_latency_ms": round(
                sum(float(s.get("latency_ms") or 0.0) for s in step_records) / max(1, len(step_records)),
                2,
            ),
        },
        "external_models_used": False,
        "upstream_failed": upstream_failed,
    }
