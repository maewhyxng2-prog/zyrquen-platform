"""
Automation Toolkit for ZYRQUEN Tool Center.
Connects central workflow execution, task orchestration, process coordination,
and Intelligence-Core support (goal decomposition, causal analysis, strategy
comparison, uncertainty estimation, plan optimization, and empirical outcome learning).
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import zyrquen_core as zc

from ..contracts import CapabilitySpec, ToolkitManifest
from ..dependency_manager import ToolDependencyManager
from ..resource_manager import get_resource_manager
from ..task_memory import (
    analyze_failure_patterns,
    init_task_memory_schema,
    record_task_memory,
    summarize_capability_track_record,
)


def _handle_workflow_execute(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    group_id = str(payload.get("group_id") or "").strip()
    if not group_id:
        return {"ok": False, "status": "FAILED", "error": "group_id is required.", "output": {}}

    res = zc.handle_run_workflow({
        "group_id": group_id,
        "user_id": ctx.get("user_id") or "system",
        "approved_by": ctx.get("approved_by"),
        "dataset_id": payload.get("dataset_id"),
    })
    if not res.get("ok"):
        return {
            "ok": False,
            "status": "FAILED",
            "error": str(res.get("error") or "Workflow execution failed"),
            "output": res,
        }
    run_obj = res.get("run") or {}
    run_status = str(run_obj.get("status") or "COMPLETED")
    return {
        "ok": True,
        "status": run_status if run_status in {"COMPLETED", "PENDING_APPROVAL", "BLOCKED", "FAILED"} else "COMPLETED",
        "output": {"run": run_obj},
        "summary": f"เวิร์กโฟลว์ '{group_id}' สถานะ {run_status}: {run_obj.get('summary', '')}",
    }


def _handle_task_compose(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    goal = str(payload.get("goal") or "").strip()
    if not goal:
        return {"ok": False, "status": "FAILED", "error": "goal is required.", "output": {}}
    registry = ctx["registry"]
    plan = registry.compose_for_goal(
        goal,
        user_role=ctx.get("user_role") or "user",
        conn=ctx.get("conn"),
    )
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": plan,
        "summary": (
            f"ประกอบแผนงานจากคลังเครื่องมือ: เลือกใช้ {plan['reuse_existing_count']} ความสามารถพร้อมใช้ "
            f"จาก {len(plan['selected_toolkits'])} Toolkits"
        ),
    }


def _handle_workflow_status(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    conn = ctx.get("conn")
    if conn is None:
        return {"ok": False, "status": "BLOCKED", "error": "Database connection unavailable.", "output": {}}
    uid = ctx.get("user_id")
    is_admin = str(ctx.get("user_role") or "").lower() == "admin"
    limit = max(1, min(30, int(payload.get("limit") or 10)))

    if is_admin:
        runs = [
            dict(r)
            for r in conn.execute(
                "SELECT id, group_id, status, summary, created_at, updated_at FROM workflow_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        ]
        missions = [
            dict(r)
            for r in conn.execute(
                "SELECT id, goal, status, created_at, updated_at FROM autonomous_missions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        ]
    else:
        runs = [
            dict(r)
            for r in conn.execute(
                "SELECT id, group_id, status, summary, created_at, updated_at FROM workflow_runs WHERE triggered_by=? ORDER BY created_at DESC LIMIT ?",
                (uid, limit),
            ).fetchall()
        ]
        missions = [
            dict(r)
            for r in conn.execute(
                "SELECT id, goal, status, created_at, updated_at FROM autonomous_missions WHERE created_by=? ORDER BY created_at DESC LIMIT ?",
                (uid, limit),
            ).fetchall()
        ]

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "workflow_runs": runs,
            "autonomous_missions": missions,
            "run_count": len(runs),
            "mission_count": len(missions),
        },
        "summary": f"สถานะการประสานงาน: Workflow {len(runs)} รอบ, ภารกิจอัตโนมัติ {len(missions)} รายการ",
    }


_CLAUSE_SPLIT_RE = re.compile(
    r"(?:\s*(?:;|,|->|แล้ว(?:จึง)?|จากนั้น|และตรวจสอบ|และสร้าง|และวิเคราะห์|and\s+then|then\s+|,\s*and\s+|\band\b)\s*)",
    re.IGNORECASE,
)


def _infer_stage_order(clause: str, toolkit_id: str) -> int:
    low = clause.lower()
    if any(k in low for k in ("inspect", "analyze", "profile", "schema", "leakage", "discover", "inventory", "สำรวจ", "วิเคราะห์", "ตรวจรับ")):
        return 1
    if any(k in low for k in ("patch", "refactor", "scaffold", "implement", "transform", "resolve", "สร้าง", "แก้ไข", "แปลง")):
        return 2
    if any(k in low for k in ("verify", "test", "coverage", "mutation", "audit", "sbom", "threat", "assert", "regression", "ทดสอบ", "ทวนสอบ", "ปลอดภัย")):
        return 3
    if toolkit_id in {"data", "research"}:
        return 1
    if toolkit_id in {"development", "document"}:
        return 2
    if toolkit_id in {"testing", "security"}:
        return 3
    return 2


def _handle_goal_decomposition(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    goal = str(payload.get("goal") or "").strip()
    if not goal:
        return {"ok": False, "status": "FAILED", "error": "goal is required.", "output": {}}

    max_subtasks = max(1, min(12, int(payload.get("max_subtasks") or 8)))
    user_role = str(payload.get("user_role") or ctx.get("user_role") or "user")
    registry = ctx["registry"]
    conn = ctx.get("conn")

    raw_clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(goal) if c and c.strip()]
    if not raw_clauses:
        raw_clauses = [goal]

    subtasks: list[dict[str, Any]] = []
    seen_caps: set[str] = set()
    for idx, clause in enumerate(raw_clauses[:max_subtasks], start=1):
        comp = registry.compose_for_goal(clause, user_role=user_role, conn=conn)
        chosen = None
        for cand in comp.get("selected_capabilities") or []:
            if cand["capability_id"] not in seen_caps:
                chosen = cand
                break
        if chosen is None and (comp.get("selected_capabilities") or []):
            chosen = comp["selected_capabilities"][0]

        cap_id = chosen["capability_id"] if chosen else None
        tk_id = chosen["toolkit_id"] if chosen else "unmatched"
        if cap_id:
            seen_caps.add(cap_id)
        subtasks.append({
            "step_id": f"sub_{idx}",
            "subgoal": clause,
            "stage": _infer_stage_order(clause, tk_id),
            "capability_id": cap_id,
            "toolkit_id": tk_id,
            "selection_score": chosen.get("score", 0.0) if chosen else 0.0,
            "depends_on": [],
        })

    # Also supplement from full-goal composition if clauses left domain gaps
    full_comp = registry.compose_for_goal(goal, user_role=user_role, conn=conn)
    for cand in full_comp.get("selected_capabilities") or []:
        if len(subtasks) >= max_subtasks:
            break
        if cand["capability_id"] not in seen_caps:
            seen_caps.add(cand["capability_id"])
            subtasks.append({
                "step_id": f"sub_{len(subtasks) + 1}",
                "subgoal": cand["name"],
                "stage": _infer_stage_order(cand["name"], cand["toolkit_id"]),
                "capability_id": cand["capability_id"],
                "toolkit_id": cand["toolkit_id"],
                "selection_score": cand.get("score", 0.0),
                "depends_on": [],
            })

    # Wire deterministic stage dependencies (stage 2 depends on stage 1; stage 3 depends on stage 2 or 1)
    stage_steps: dict[int, list[str]] = {1: [], 2: [], 3: []}
    for st in subtasks:
        stage_steps.setdefault(st["stage"], []).append(st["step_id"])

    for st in subtasks:
        if st["stage"] == 2 and stage_steps[1]:
            st["depends_on"] = list(stage_steps[1])
        elif st["stage"] == 3:
            if stage_steps[2]:
                st["depends_on"] = list(stage_steps[2])
            elif stage_steps[1]:
                st["depends_on"] = list(stage_steps[1])

    dag_steps = [
        {"step_id": st["step_id"], "capability_id": st["capability_id"], "depends_on": st["depends_on"]}
        for st in subtasks
        if st["capability_id"]
    ]
    wave_plan = ToolDependencyManager().plan_execution_waves(dag_steps, registry=registry) if dag_steps else {"ok": True, "waves": []}
    matched_count = sum(1 for st in subtasks if st["capability_id"])

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "goal": goal,
            "subtask_count": len(subtasks),
            "matched_capability_count": matched_count,
            "subtasks": subtasks,
            "wave_count": len(wave_plan.get("waves") or []),
            "dag_valid": bool(wave_plan.get("ok")),
        },
        "summary": f"แตกเป้าหมายเป็น {len(subtasks)} งานย่อย (จับคู่เครื่องมือได้ {matched_count}/{len(subtasks)}, {len(wave_plan.get('waves') or [])} waves)",
    }


def _handle_causal_analysis(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    events = payload.get("events")
    use_task_memory = bool(payload.get("from_task_memory", False))

    if (not isinstance(events, list) or not events) and use_task_memory:
        conn = ctx.get("conn")
        if conn is None:
            return {"ok": False, "status": "BLOCKED", "error": "Database connection unavailable for task_memory lookup.", "output": {}}
        patterns = analyze_failure_patterns(conn, limit=15)
        events = [
            {
                "id": f"err_{idx + 1}",
                "label": f"{p['capability_id']}::{p['error_code']}",
                "caused_by": [],
                "impact_score": float(p.get("count") or 1),
            }
            for idx, p in enumerate(patterns)
        ]

    if not isinstance(events, list) or not events:
        return {"ok": False, "status": "FAILED", "error": "events array or from_task_memory=True is required.", "output": {}}

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[tuple[str, str]] = []
    indeg: dict[str, int] = {}
    children: dict[str, list[str]] = {}

    for idx, ev in enumerate(events):
        if not isinstance(ev, dict):
            continue
        eid = str(ev.get("id") or f"node_{idx + 1}").strip()
        if not eid:
            continue
        nodes[eid] = {
            "id": eid,
            "label": str(ev.get("label") or ev.get("description") or eid),
            "impact_score": float(ev.get("impact_score") or 1.0),
            "caused_by": [str(c).strip() for c in (ev.get("caused_by") or []) if str(c).strip()],
        }
        indeg.setdefault(eid, 0)
        children.setdefault(eid, [])

    for eid, node in nodes.items():
        for parent in node["caused_by"]:
            if parent in nodes and parent != eid:
                edges.append((parent, eid))
                indeg[eid] = indeg.get(eid, 0) + 1
                children.setdefault(parent, []).append(eid)

    # Detect cycles via Kahn's topological sweep
    q = [nid for nid, d in indeg.items() if d == 0]
    visited = 0
    temp_indeg = dict(indeg)
    while q:
        cur = q.pop(0)
        visited += 1
        for nxt in children.get(cur, []):
            temp_indeg[nxt] -= 1
            if temp_indeg[nxt] == 0:
                q.append(nxt)
    has_cycle = visited < len(nodes)

    def _downstream_reach(start: str) -> set[str]:
        seen: set[str] = set()
        stack = list(children.get(start, []))
        while stack:
            c = stack.pop()
            if c not in seen:
                seen.add(c)
                stack.extend(children.get(c, []))
        return seen

    root_causes: list[dict[str, Any]] = []
    for nid, node in nodes.items():
        if indeg.get(nid, 0) == 0:
            reach = _downstream_reach(nid)
            downstream_impact = node["impact_score"] + sum(nodes[r]["impact_score"] for r in reach)
            root_causes.append({
                "id": nid,
                "label": node["label"],
                "downstream_affected_count": len(reach),
                "total_causal_impact": round(downstream_impact, 3),
                "affected_nodes": sorted(reach),
            })
    root_causes.sort(key=lambda r: (-r["total_causal_impact"], -r["downstream_affected_count"], r["id"]))

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "has_cycle": has_cycle,
            "root_causes": root_causes,
            "top_root_cause": root_causes[0] if root_causes else None,
        },
        "summary": (
            f"วิเคราะห์ Causal Graph ({len(nodes)} โหนด, {len(edges)} ความเชื่อมโยง): "
            f"สาเหตุรากอันดับหนึ่ง '{root_causes[0]['id'] if root_causes else 'N/A'}'"
        ),
    }


def _handle_strategy_comparison(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    strategies = payload.get("strategies") or []
    if not isinstance(strategies, list) or len(strategies) < 1:
        return {"ok": False, "status": "FAILED", "error": "strategies array must be non-empty.", "output": {}}

    registry = ctx["registry"]
    conn = ctx.get("conn")
    track_records = summarize_capability_track_record(conn) if conn is not None else {}
    dep_mgr = ToolDependencyManager()

    risk_penalty_map = {
        "local_readonly": 0.0,
        "sandbox_io": 0.1,
        "governance": 0.2,
        "external_readonly": 0.3,
        "external_write": 0.45,
    }

    evaluated: list[dict[str, Any]] = []
    for idx, strat in enumerate(strategies[:10]):
        if not isinstance(strat, dict):
            continue
        sid = str(strat.get("strategy_id") or strat.get("name") or f"strategy-{idx + 1}")
        steps = strat.get("steps") or []
        estimated_cost = float(strat.get("estimated_cost") or 0.0)

        # Evaluate steps against actual Registry & Task Memory
        norm_steps = []
        risk_sum = 0.0
        ready_count = 0
        approval_steps = 0
        hist_scores: list[float] = []
        invalid_caps: list[str] = []

        for s_idx, step in enumerate(steps):
            if isinstance(step, str):
                cap_id = step
                step_obj = {"step_id": f"s_{s_idx}", "capability_id": cap_id, "depends_on": []}
            elif isinstance(step, dict):
                cap_id = str(step.get("capability_id") or "")
                step_obj = {
                    "step_id": str(step.get("step_id") or f"s_{s_idx}"),
                    "capability_id": cap_id,
                    "depends_on": list(step.get("depends_on") or []),
                }
            else:
                continue
            norm_steps.append(step_obj)
            spec = registry.get_spec(cap_id)
            if spec is None:
                invalid_caps.append(cap_id)
                risk_sum += 0.6
                continue
            if spec.lifecycle_status == "READY":
                ready_count += 1
            else:
                invalid_caps.append(f"{cap_id}({spec.lifecycle_status})")
                risk_sum += 0.5
            if spec.permission_mode == "approval_gate":
                approval_steps += 1
            risk_sum += risk_penalty_map.get(spec.risk_tier, 0.25)
            hist = track_records.get(cap_id)
            hist_scores.append(float(hist["success_rate"]) if hist else 1.0)

        wave_res = dep_mgr.plan_execution_waves(norm_steps, registry=registry) if norm_steps else {"ok": False, "waves": []}
        step_count = max(1, len(norm_steps))
        avg_hist = sum(hist_scores) / len(hist_scores) if hist_scores else 0.5
        avg_risk = min(1.0, risk_sum / step_count)
        wave_count = len(wave_res.get("waves") or []) if wave_res.get("ok") else step_count
        parallel_efficiency = round(step_count / max(1, wave_count), 3) if norm_steps else 0.0
        cost_penalty = min(0.3, estimated_cost / 100.0) if estimated_cost > 0 else 0.0

        feasibility = 1.0 if (wave_res.get("ok") and not invalid_caps) else 0.35
        composite_score = round(
            max(0.0, feasibility * (0.45 * avg_hist + 0.25 * (1.0 - avg_risk) + 0.2 * min(1.0, parallel_efficiency / 2.0) + 0.1 * (1.0 - cost_penalty))),
            4,
        )

        evaluated.append({
            "strategy_id": sid,
            "step_count": len(norm_steps),
            "ready_capabilities": ready_count,
            "invalid_or_unready": invalid_caps,
            "dag_valid": bool(wave_res.get("ok")),
            "wave_count": wave_count,
            "parallel_efficiency": parallel_efficiency,
            "approval_gated_steps": approval_steps,
            "avg_historical_success": round(avg_hist, 4),
            "risk_index": round(avg_risk, 4),
            "composite_score": composite_score,
        })

    evaluated.sort(key=lambda e: (-e["composite_score"], e["risk_index"], e["strategy_id"]))
    best = evaluated[0] if evaluated else None
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "compared_count": len(evaluated),
            "recommended_strategy": best["strategy_id"] if best else None,
            "ranking": evaluated,
        },
        "summary": (
            f"เปรียบเทียบ {len(evaluated)} กลยุทธ์: แนะนำ '{best['strategy_id']}' "
            f"(score={best['composite_score']}, risk={best['risk_index']})" if best else "ไม่มีกลยุทธ์ที่ประเมินได้"
        ),
    }


def _handle_uncertainty_estimation(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    evidence_count = max(0, int(payload.get("evidence_count") or 0))
    corroborating = max(0, int(payload.get("corroborating_sources") or 0))
    contradictions = max(0, int(payload.get("contradictions") or 0))
    coverage_ratio = float(payload.get("coverage_ratio") if payload.get("coverage_ratio") is not None else 0.5)
    test_pass_rate = float(payload.get("test_pass_rate") if payload.get("test_pass_rate") is not None else 0.5)
    schema_valid = bool(payload.get("schema_valid", True))
    abstain_threshold = float(payload.get("abstain_threshold") or 0.45)

    coverage_ratio = max(0.0, min(1.0, coverage_ratio))
    test_pass_rate = max(0.0, min(1.0, test_pass_rate))

    hist_rate = None
    cap_id = str(payload.get("capability_id") or "").strip()
    if cap_id and ctx.get("conn") is not None:
        tr = summarize_capability_track_record(ctx["conn"])
        if cap_id in tr:
            hist_rate = float(tr[cap_id]["success_rate"])

    # Calibrated epistemic score
    ev_factor = min(1.0, evidence_count / 3.0)
    corr_factor = min(1.0, corroborating / 2.0) if corroborating > 0 else (0.4 if evidence_count > 0 else 0.0)
    hist_component = hist_rate if hist_rate is not None else 0.75

    raw_conf = (
        0.25 * ev_factor
        + 0.20 * corr_factor
        + 0.20 * coverage_ratio
        + 0.25 * test_pass_rate
        + 0.10 * hist_component
    )
    risk_factors: list[str] = []
    if evidence_count == 0:
        risk_factors.append("missing_primary_evidence")
        raw_conf *= 0.45
    if contradictions > 0:
        penalty = min(0.6, contradictions * 0.25)
        raw_conf = max(0.0, raw_conf - penalty)
        risk_factors.append(f"contradictions_present={contradictions}")
    if not schema_valid:
        raw_conf *= 0.5
        risk_factors.append("schema_validation_failed")
    if test_pass_rate < 0.7:
        risk_factors.append(f"low_test_pass_rate={test_pass_rate}")
    if coverage_ratio < 0.5:
        risk_factors.append(f"low_coverage={coverage_ratio}")

    confidence = round(max(0.0, min(1.0, raw_conf)), 4)
    uncertainty = round(1.0 - confidence, 4)
    should_abstain = uncertainty > abstain_threshold or evidence_count == 0 or not schema_valid

    band = "HIGH_CONFIDENCE" if confidence >= 0.75 and not should_abstain else (
        "MODERATE_CAUTION" if not should_abstain else "ABSTAIN_LOW_CONFIDENCE"
    )
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "confidence": confidence,
            "uncertainty": uncertainty,
            "confidence_band": band,
            "should_abstain": should_abstain,
            "abstain_threshold": abstain_threshold,
            "historical_success_rate": hist_rate,
            "risk_factors": risk_factors,
        },
        "summary": (
            f"ประเมินความไม่แน่นอน: confidence={confidence}, uncertainty={uncertainty} ({band})"
        ),
    }


def _handle_plan_optimization(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    steps = payload.get("steps") or []
    if not isinstance(steps, list) or not steps:
        return {"ok": False, "status": "FAILED", "error": "steps array must be non-empty.", "output": {}}

    registry = ctx["registry"]
    res_mgr = get_resource_manager()
    dep_mgr = ToolDependencyManager()

    # 1. Deduplicate identical (capability_id, canonical_input) steps and remap downstream dependencies
    dedup_steps: list[dict[str, Any]] = []
    seen_sig: dict[tuple[str, str], str] = {}
    alias_map: dict[str, str] = {}
    removed_duplicates: list[dict[str, str]] = []

    for idx, raw in enumerate(steps):
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("step_id") or f"step_{idx + 1}")
        cid = str(raw.get("capability_id") or "")
        inp = dict(raw.get("input") or {})
        sig = (cid, json.dumps(inp, sort_keys=True, ensure_ascii=False))
        if sig in seen_sig and not raw.get("keep_duplicate"):
            canonical = seen_sig[sig]
            alias_map[sid] = canonical
            removed_duplicates.append({"removed_step_id": sid, "reused_step_id": canonical, "capability_id": cid})
            continue
        seen_sig[sig] = sid
        alias_map[sid] = sid
        dedup_steps.append({
            **raw,
            "step_id": sid,
            "capability_id": cid,
            "input": inp,
            "depends_on": [alias_map.get(d, d) for d in (raw.get("depends_on") or [])],
        })

    # Re-resolve any forward/renamed dependency refs and drop self-loops introduced by aliasing
    for st in dedup_steps:
        cleaned_deps: list[str] = []
        for d in st["depends_on"]:
            target = alias_map.get(d, d)
            if target != st["step_id"] and target not in cleaned_deps:
                cleaned_deps.append(target)
        st["depends_on"] = cleaned_deps

    wave_plan = dep_mgr.plan_execution_waves(dedup_steps, registry=registry)
    if not wave_plan.get("ok"):
        return {
            "ok": False,
            "status": "FAILED",
            "error": str(wave_plan.get("error") or "DAG dependency optimization failed"),
            "output": {"conflicts": wave_plan.get("conflicts", [])},
        }

    waves = wave_plan["waves"]
    max_width = max((len(w) for w in waves), default=1)
    admission = res_mgr.evaluate_admission(requested_workers=max_width)
    eff_workers = int(admission.get("effective_workers") or 1)

    # Split overly wide waves cleanly into resource-bounded batches without breaking dependencies
    bounded_waves: list[dict[str, Any]] = []
    for w_idx, w in enumerate(waves, start=1):
        ordered_w = sorted(w, key=lambda s: (-int(s.get("priority") or 0), s["step_id"]))
        for b_start in range(0, len(ordered_w), max(1, eff_workers)):
            chunk = ordered_w[b_start:b_start + max(1, eff_workers)]
            bounded_waves.append({
                "wave": len(bounded_waves) + 1,
                "source_topological_wave": w_idx,
                "parallel_workers": len(chunk),
                "step_ids": [s["step_id"] for s in chunk],
            })

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "original_step_count": len(steps),
            "optimized_step_count": len(dedup_steps),
            "duplicates_pruned": len(removed_duplicates),
            "removed_duplicates": removed_duplicates,
            "critical_path_waves": len(waves),
            "resource_bounded_batches": len(bounded_waves),
            "effective_max_workers": eff_workers,
            "optimized_steps": dedup_steps,
            "execution_schedule": bounded_waves,
        },
        "summary": (
            f"ปรับแผนงานสำเร็จ: {len(steps)} -> {len(dedup_steps)} ขั้นตอน "
            f"(ตัดซ้ำ {len(removed_duplicates)}, {len(waves)} waves, max_workers={eff_workers})"
        ),
    }


def _handle_outcome_learning(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    conn = ctx.get("conn")
    if conn is None:
        return {"ok": False, "status": "BLOCKED", "error": "Database connection unavailable.", "output": {}}

    goal = str(payload.get("goal") or "").strip()
    cap_seq = [str(c).strip() for c in (payload.get("capability_sequence") or []) if str(c).strip()]
    outcome_status = str(payload.get("outcome_status") or "").strip().upper()
    if not goal or not cap_seq or outcome_status not in {"SUCCESS", "PARTIAL_SUCCESS", "FAILED", "UNVERIFIED"}:
        return {
            "ok": False,
            "status": "FAILED",
            "error": "goal, non-empty capability_sequence, and valid outcome_status (SUCCESS|PARTIAL_SUCCESS|FAILED|UNVERIFIED) are required.",
            "output": {},
        }

    init_task_memory_schema(conn)
    registry = ctx["registry"]
    toolkit_ids = sorted({
        (registry.get_spec(cid).toolkit_id if registry.get_spec(cid) else cid.split(".")[0])
        for cid in cap_seq
    })
    entry_id = record_task_memory(
        conn,
        trace_id=str(payload.get("trace_id") or f"learn-{int(time.time() * 1000)}"),
        goal=goal,
        toolkit_ids=toolkit_ids,
        capability_sequence=cap_seq,
        outcome_status=outcome_status,
        error_code=str(payload.get("error_code")) if payload.get("error_code") else None,
        error_message=str(payload.get("error_message")) if payload.get("error_message") else None,
        recovery_action=str(payload.get("recovery_action")) if payload.get("recovery_action") else None,
        context_keys=[str(k) for k in (payload.get("context_keys") or [])],
        latency_ms=float(payload.get("latency_ms") or 0.0),
        verified=bool(payload.get("verified", outcome_status == "SUCCESS")),
    )
    track = summarize_capability_track_record(conn)
    failures = analyze_failure_patterns(conn, limit=5)

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "memory_entry_id": entry_id,
            "recorded_outcome": outcome_status,
            "capability_sequence": cap_seq,
            "updated_track_records": {cid: track.get(cid) for cid in cap_seq if cid in track},
            "recent_failure_patterns_count": len(failures),
            "model_weights_mutated": False,
            "external_models_used": False,
        },
        "summary": f"บันทึกผลประสบการณ์ '{outcome_status}' ({len(cap_seq)} เครื่องมือ) ลง Task Memory เรียบร้อยโดยไม่แก้ weight โมเดล",
    }


def register_automation_toolkit(registry: Any) -> None:
    manifest = ToolkitManifest(
        id="automation",
        name="Automation Toolkit",
        thai_name="ชุดเครื่องมืออัตโนมัติและการประสานงาน",
        version="1.2.0",
        description="รัน Workflow กลาง, ประกอบแผน, แตกเป้าหมาย, วิเคราะห์สาเหตุเชิงเหตุผล, เปรียบเทียบกลยุทธ์, ประเมินความไม่แน่นอน, ปรับแผน และเรียนรู้จากผลลัพธ์จริง",
        category="automation",
        dependencies=("python_core.zyrquen_core", "apps.core.workflow.governance"),
        default_permission="auto",
        lifecycle_status="READY",
        bound_modules=(
            "python_core/zyrquen_core.py",
            "python_core/dag_executor.py",
            "python_core/tool_center/orchestrator.py",
            "python_core/tool_center/task_memory.py",
            "apps/core/workflow/governance.py",
        ),
        documentation="ประสานงานผ่าน Workflow Engine กลางเพียงตัวเดียวและสนับสนุน Intelligence Core ในการวางแผน ตัดสินใจ และเรียนรู้จากผลลัพธ์จริง",
    )

    specs = [
        (
            CapabilitySpec(
                id="automation.workflow_execute",
                toolkit_id="automation",
                name="สั่งรัน Workflow Engine กลาง",
                version="1.0.0",
                description="สั่งดำเนินงานกลุ่ม Workflow ที่ลงทะเบียนใน ZYRQUEN (เช่น system_ops, data_quality, native_training ผ่าน Approval Gate)",
                input_schema={
                    "type": "object",
                    "required": ["group_id"],
                    "properties": {
                        "group_id": {"type": "string"},
                        "dataset_id": {"type": "string"},
                    },
                },
                output_schema={"type": "object", "required": ["run"]},
                dependencies=("python_core.zyrquen_core",),
                permission_mode="auto",
                risk_tier="governance",
                lifecycle_status="READY",
                bound_modules=("python_core/zyrquen_core.py",),
                documentation="ระบุ group_id เช่น 'system_ops', 'data_quality', 'knowledge_memory', 'security_governance', 'native_training'",
                example_input={"group_id": "system_ops"},
                keywords=("workflow", "automation", "schedule", "run", "อัตโนมัติ", "เวิร์กโฟลว์", "ประสานงาน"),
            ),
            _handle_workflow_execute,
        ),
        (
            CapabilitySpec(
                id="automation.task_compose",
                toolkit_id="automation",
                name="ประกอบงานอัตโนมัติจาก Tool Center (Orchestration Composer)",
                version="1.0.0",
                description="วิเคราะห์เป้าหมายเพื่อจับคู่และเลือกใช้เครื่องมือที่มีอยู่แล้วใน Tool Center โดยไม่สร้างซ้ำ",
                input_schema={
                    "type": "object",
                    "required": ["goal"],
                    "properties": {"goal": {"type": "string"}},
                },
                output_schema={"type": "object", "required": ["selected_capabilities", "selected_toolkits", "reuse_existing_count"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/registry.py",),
                documentation="ส่ง goal เพื่อค้นหา Toolkit และความสามารถที่พร้อมใช้งานจริง",
                example_input={"goal": "วิเคราะห์ข้อมูล CSV ตรวจความปลอดภัยและสร้างเอกสารสรุป"},
                keywords=("orchestrate", "compose", "plan", "task", "วางแผน", "จัดลำดับ", "ประกอบงาน"),
            ),
            _handle_task_compose,
        ),
        (
            CapabilitySpec(
                id="automation.workflow_status",
                toolkit_id="automation",
                name="ติดตามสถานะ Workflow และภารกิจ (Process Coordination)",
                version="1.0.0",
                description="ดึงสถานะล่าสุดของ Workflow Runs และ Autonomous Missions ตามสิทธิ์ผู้ใช้งาน",
                input_schema={
                    "type": "object",
                    "required": [],
                    "properties": {"limit": {"type": "integer"}},
                },
                output_schema={"type": "object", "required": ["workflow_runs", "autonomous_missions"]},
                dependencies=("python_core.zyrquen_core",),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/zyrquen_core.py",),
                documentation="แสดงรายการ Workflow และ Mission ล่าสุดที่ผู้ใช้มีสิทธิ์เข้าถึง",
                example_input={"limit": 10},
                keywords=("status", "monitor", "coordination", "workflow", "สถานะ", "ติดตาม"),
            ),
            _handle_workflow_status,
        ),
        (
            CapabilitySpec(
                id="automation.goal_decomposition",
                toolkit_id="automation",
                name="แตกเป้าหมายซับซ้อนเป็นงานย่อยแบบ DAG (Goal Decomposition)",
                version="1.0.0",
                description="แยกเป้าหมายภาษาธรรมชาติเป็นงานย่อย จับคู่กับความสามารถพร้อมใช้ใน Tool Center และจัดลำดับ Dependency",
                input_schema={
                    "type": "object",
                    "required": ["goal"],
                    "properties": {
                        "goal": {"type": "string"},
                        "max_subtasks": {"type": "integer"},
                    },
                },
                output_schema={"type": "object", "required": ["subtask_count", "matched_capability_count", "subtasks", "dag_valid"]},
                dependencies=("python_core.tool_center.dependency_manager",),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/automation.py",),
                documentation="แตกเป้าหมายหลายขั้นตอนออกเป็น DAG พร้อม wave order",
                example_input={"goal": "ตรวจสอบ schema ของชุดข้อมูล แล้วแก้บั๊กในโค้ด และตรวจสอบความปลอดภัย"},
                keywords=("decompose", "subtask", "goal", "dag", "plan", "แตกเป้าหมาย", "วางแผน"),
            ),
            _handle_goal_decomposition,
        ),
        (
            CapabilitySpec(
                id="automation.causal_analysis",
                toolkit_id="automation",
                name="วิเคราะห์สายเหตุและผลกระทบ (Causal Graph Analysis)",
                version="1.0.0",
                description="สร้างกราฟความสัมพันธ์เชิงเหตุผลจากเหตุการณ์หรือ Task Memory เพื่อระบุสาเหตุรากและโหนดปลายทางที่ได้รับผลกระทบ",
                input_schema={
                    "type": "object",
                    "required": [],
                    "properties": {
                        "events": {"type": "array"},
                        "from_task_memory": {"type": "boolean"},
                    },
                },
                output_schema={"type": "object", "required": ["node_count", "edge_count", "has_cycle", "root_causes"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/automation.py",),
                documentation="วิเคราะห์ root cause และผลกระทบต่อเนื่องจาก event causal DAG",
                example_input={"events": [{"id": "db_lock", "caused_by": [], "impact_score": 2}, {"id": "api_fail", "caused_by": ["db_lock"], "impact_score": 5}]},
                keywords=("causal", "root_cause", "graph", "impact", "สาเหตุ", "ผลกระทบ"),
            ),
            _handle_causal_analysis,
        ),
        (
            CapabilitySpec(
                id="automation.strategy_comparison",
                toolkit_id="automation",
                name="เปรียบเทียบและจัดอันดับกลยุทธ์ดำเนินการ (Strategy Comparison)",
                version="1.0.0",
                description="ประเมินกลยุทธ์ทางเลือกโดยเทียบประวัติความสำเร็จจาก Task Memory, ความเสี่ยง, สถานะพร้อมใช้ และความเป็นไปได้เชิงขนาน",
                input_schema={
                    "type": "object",
                    "required": ["strategies"],
                    "properties": {"strategies": {"type": "array"}},
                },
                output_schema={"type": "object", "required": ["compared_count", "recommended_strategy", "ranking"]},
                dependencies=("python_core.tool_center.task_memory",),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/automation.py",),
                documentation="จัดอันดับกลยุทธ์ที่ปลอดภัยและมีประสิทธิภาพสูงสุดจากหลักฐานจริง",
                example_input={
                    "strategies": [
                        {"strategy_id": "fast_readonly", "steps": ["development.code_analysis", "security.native_policy_audit"]},
                        {"strategy_id": "unknown_path", "steps": ["missing.tool"]},
                    ]
                },
                keywords=("strategy", "compare", "tradeoff", "rank", "กลยุทธ์", "เปรียบเทียบ"),
            ),
            _handle_strategy_comparison,
        ),
        (
            CapabilitySpec(
                id="automation.uncertainty_estimation",
                toolkit_id="automation",
                name="ประเมินความมั่นใจและสัญญาณ Abstain (Uncertainty Estimation)",
                version="1.0.0",
                description="คำนวณระดับความมั่นใจ ความไม่แน่นอน และเกณฑ์ควรระงับการตัดสินใจจากจำนวนหลักฐาน ความสอดคล้อง ผลทดสอบ และความครอบคลุม",
                input_schema={
                    "type": "object",
                    "required": [],
                    "properties": {
                        "evidence_count": {"type": "integer"},
                        "corroborating_sources": {"type": "integer"},
                        "contradictions": {"type": "integer"},
                        "coverage_ratio": {"type": "number"},
                        "test_pass_rate": {"type": "number"},
                        "schema_valid": {"type": "boolean"},
                        "abstain_threshold": {"type": "number"},
                        "capability_id": {"type": "string"},
                    },
                },
                output_schema={"type": "object", "required": ["confidence", "uncertainty", "confidence_band", "should_abstain"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/automation.py",),
                documentation="ให้คะแนนความมั่นใจเชิงคณิตศาสตร์และแจ้ง should_abstain เมื่อหลักฐานไม่เพียงพอ",
                example_input={"evidence_count": 3, "corroborating_sources": 2, "contradictions": 0, "coverage_ratio": 0.9, "test_pass_rate": 1.0},
                keywords=("uncertainty", "confidence", "abstain", "calibration", "ความมั่นใจ", "ความไม่แน่นอน"),
            ),
            _handle_uncertainty_estimation,
        ),
        (
            CapabilitySpec(
                id="automation.plan_optimization",
                toolkit_id="automation",
                name="ปรับแต่ง DAG และจำกัดทรัพยากรแผนงาน (Plan Optimization)",
                version="1.0.0",
                description="ตัดขั้นตอนที่ซ้ำซ้อน, จัดลำดับ Topological Waves, และแบ่ง Batch ตามขีดจำกัด Resource Manager จริง",
                input_schema={
                    "type": "object",
                    "required": ["steps"],
                    "properties": {"steps": {"type": "array"}},
                },
                output_schema={"type": "object", "required": ["original_step_count", "optimized_step_count", "duplicates_pruned", "execution_schedule"]},
                dependencies=("python_core.tool_center.dependency_manager", "python_core.tool_center.resource_manager"),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/automation.py",),
                documentation="ลดความซ้ำซ้อนและปรับตารางรันให้เหมาะกับ CPU/RAM ปัจจุบัน",
                example_input={
                    "steps": [
                        {"step_id": "a", "capability_id": "data.calc_ast", "input": {"expression": "2+2"}, "depends_on": []},
                        {"step_id": "b", "capability_id": "data.calc_ast", "input": {"expression": "2+2"}, "depends_on": []},
                    ]
                },
                keywords=("optimize", "schedule", "parallel", "deduplicate", "resource", "ปรับแผน"),
            ),
            _handle_plan_optimization,
        ),
        (
            CapabilitySpec(
                id="automation.outcome_learning",
                toolkit_id="automation",
                name="บันทึกบทเรียนและปรับคะแนนประสบการณ์ (Outcome Learning)",
                version="1.0.0",
                description="บันทึกผลสำเร็จ/ล้มเหลวของแผนงานลง Task Memory เพื่อใช้ปรับปรุงการเลือกเครื่องมือรอบถัดไป (ไม่แก้ weight โมเดล)",
                input_schema={
                    "type": "object",
                    "required": ["goal", "capability_sequence", "outcome_status"],
                    "properties": {
                        "goal": {"type": "string"},
                        "capability_sequence": {"type": "array"},
                        "outcome_status": {"type": "string", "enum": ["SUCCESS", "PARTIAL_SUCCESS", "FAILED", "UNVERIFIED"]},
                        "error_code": {"type": "string"},
                        "error_message": {"type": "string"},
                        "recovery_action": {"type": "string"},
                        "latency_ms": {"type": "number"},
                        "verified": {"type": "boolean"},
                    },
                },
                output_schema={"type": "object", "required": ["memory_entry_id", "recorded_outcome", "model_weights_mutated", "external_models_used"]},
                dependencies=("python_core.tool_center.task_memory",),
                permission_mode="auto",
                risk_tier="governance",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/task_memory.py", "python_core/tool_center/toolkits/automation.py"),
                documentation="เก็บผลลัพธ์จริงลง SQLite task_memory_entries เพื่อเพิ่มความแม่นยำในการเลือกเครื่องมือ",
                example_input={"goal": "Verify code safety", "capability_sequence": ["security.native_policy_audit"], "outcome_status": "SUCCESS"},
                keywords=("learn", "memory", "feedback", "outcome", "track_record", "เรียนรู้", "บทเรียน"),
            ),
            _handle_outcome_learning,
        ),
    ]

    registry.register_toolkit(manifest, specs)
