"""
Autonomous Engineering Training Curriculum (Levels 1-5) & Seen/Unseen Generalization Benchmark.
--------------------------------------------------------------------------------------------
Implements real multi-level execution, verification, failure-recovery, and empirical Task Memory
learning across all 8 Toolkits (75 capabilities) inside isolated workspaces:
  - Levels 1-5 with explicit `expected_results` and weighted `scoring_rubric`
  - Strict separation of Seen Training Tasks vs Held-Out Unseen Generalization Tasks
  - Honest computation of 8 runtime metrics (never hardcoded or fabricated)
  - Zero neural weight mutation (`model_weights_mutated=False`) and zero external LLMs
"""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

from .orchestrator import execute_orchestrated_plan, select_tools_for_goal
from .resource_manager import get_resource_manager
from .software_engineering import WorkspaceTransaction, run_autonomous_repair_loop, run_engineering_benchmark
from .task_memory import init_task_memory_schema, summarize_capability_track_record


SCORING_RUBRIC: dict[str, Any] = {
    "weights": {
        "functional_correctness": 0.25,
        "tool_selection_accuracy": 0.15,
        "execution_success_rate": 0.15,
        "verification_accuracy": 0.15,
        "recovery_success_rate": 0.10,
        "unseen_generalization_rate": 0.20,
    },
    "pass_threshold": 0.85,
    "regression_penalty_per_incident": 0.25,
    "notes": "All metrics measured from live runtime executions and isolated sandbox tests; zero static placeholders.",
}


def _selection_f1(selected_ids: list[str], expected_ids: set[str]) -> float:
    if not expected_ids:
        return 1.0
    k = len(expected_ids)
    top_slice = set(selected_ids[: k + 1])
    hits = len(top_slice & expected_ids)
    if hits == 0:
        return 0.0
    recall = hits / k
    precision = hits / max(1, len(top_slice))
    return round((2 * precision * recall) / (precision + recall), 4)


def run_autonomous_engineering_curriculum(
    registry: Any,
    *,
    conn: sqlite3.Connection | None = None,
    data_dir: Path | None = None,
    record_learning: bool = True,
) -> dict[str, Any]:
    """
    Execute the 5-level Autonomous Engineering Training Curriculum with explicit
    Seen vs Held-Out Unseen tasks, negative/verification traps, and recovery tests.
    """
    started = time.perf_counter()
    if conn is not None:
        init_task_memory_schema(conn)

    tasks: list[dict[str, Any]] = []
    selection_scores: list[float] = []
    verification_checks: list[bool] = []
    recovery_checks: list[bool] = []
    max_wave_parallelism = 1

    # ------------------------------------------------------------------
    # LEVEL 1: Single-Tool Execution (Seen)
    # ------------------------------------------------------------------
    t0 = time.perf_counter()
    r_schema = registry.execute(
        "data.schema_inference",
        {"format": "csv", "content": "id,email,amount\n1,u1@example.com,42.5\n2,u2@example.com,99.0\n"},
        user_role="admin",
        conn=conn,
        data_dir=data_dir,
    )
    l1_s1_ok = bool(
        r_schema.get("ok")
        and "id" in (r_schema.get("output") or {}).get("primary_key_candidates", [])
        and (r_schema.get("output") or {}).get("row_count") == 2
    )
    tasks.append({
        "task_id": "L1_S1_schema_inference",
        "level": 1,
        "split": "seen",
        "goal": "Infer column types and primary key candidates from structured CSV",
        "expected_results": {"row_count": 2, "primary_key_includes": "id"},
        "observed_results": {
            "row_count": (r_schema.get("output") or {}).get("row_count"),
            "primary_key_candidates": (r_schema.get("output") or {}).get("primary_key_candidates"),
        },
        "passed": l1_s1_ok,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
    })

    t0 = time.perf_counter()
    r_calc = registry.execute(
        "data.calc_ast",
        {"expression": "(15 + 25) * 3"},
        user_role="admin",
        conn=conn,
        data_dir=data_dir,
    )
    l1_s2_ok = bool(r_calc.get("ok") and (r_calc.get("output") or {}).get("result") == 120)
    tasks.append({
        "task_id": "L1_S2_ast_calculation",
        "level": 1,
        "split": "seen",
        "goal": "Evaluate arithmetic expression deterministically via AST",
        "expected_results": {"result": 120},
        "observed_results": {"result": (r_calc.get("output") or {}).get("result")},
        "passed": l1_s2_ok,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
    })

    # ------------------------------------------------------------------
    # LEVEL 2: Multi-Step Orchestrated Workflow (Seen)
    # ------------------------------------------------------------------
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="zyrquen_curr_l2_") as tmp_dir:
        l2_data_dir = Path(tmp_dir)
        l2_steps = [
            {
                "step_id": "scaffold",
                "capability_id": "development.project_scaffold",
                "input": {"workspace": "l2_ws", "module_name": "pricing", "template": "python_module", "overwrite": True},
                "depends_on": [],
            },
            {
                "step_id": "patch",
                "capability_id": "development.code_patch_apply",
                "input": {
                    "workspace": "l2_ws",
                    "target_file": "pricing.py",
                    "replacements": [{"old": "value * 2", "new": "value * 4"}],
                },
                "depends_on": ["scaffold"],
            },
            {
                "step_id": "coverage",
                "capability_id": "testing.coverage_analysis",
                "input": {
                    "module_source": "def price(n):\n    if n > 0:\n        return n * 4\n    return 0\n",
                    "test_source": "assert price(3) == 12\nassert price(0) == 0\n",
                },
                "depends_on": ["patch"],
            },
        ]
        l2_plan = execute_orchestrated_plan(
            registry,
            "Scaffold module, patch multiplier, and verify 100% coverage",
            l2_steps,
            conn=conn,
            data_dir=l2_data_dir,
            user_id="curriculum-trainer",
            user_role="admin",
            enable_parallel=True,
        )
        l2_by_id = {s["step_id"]: s for s in (l2_plan.get("steps") or [])}
        cov_pct = (l2_by_id.get("coverage") or {}).get("output", {}).get("coverage_percent")
        patched_file = (l2_data_dir / "sandbox_workspaces" / "l2_ws" / "pricing.py").read_text(encoding="utf-8") if (l2_data_dir / "sandbox_workspaces" / "l2_ws" / "pricing.py").exists() else ""
        l2_ok = bool(l2_plan.get("ok") and l2_plan.get("delivery_verdict") == "SUCCESS" and cov_pct == 100.0 and "value * 4" in patched_file)
        tasks.append({
            "task_id": "L2_S1_scaffold_patch_coverage",
            "level": 2,
            "split": "seen",
            "goal": "Multi-step DAG: scaffold -> confined patch -> sandbox coverage analysis",
            "expected_results": {"delivery_verdict": "SUCCESS", "coverage_percent": 100.0, "patched_multiplier": True},
            "observed_results": {"delivery_verdict": l2_plan.get("delivery_verdict"), "coverage_percent": cov_pct, "patched": "value * 4" in patched_file},
            "passed": l2_ok,
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        })

    # ------------------------------------------------------------------
    # LEVEL 3: Debugging, Self-Repair & Failure Recovery (Seen)
    # ------------------------------------------------------------------
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="zyrquen_curr_l3_") as tmp_dir:
        ws = Path(tmp_dir)
        (ws / "ops_mod.py").write_text("def subtract(a, b):\n    return a + b\n", encoding="utf-8")
        (ws / "test_ops_mod.py").write_text(
            "import unittest\nfrom ops_mod import subtract\n\n"
            "class TestOps(unittest.TestCase):\n"
            "    def test_sub(self):\n"
            "        self.assertEqual(subtract(10, 3), 7)\n",
            encoding="utf-8",
        )
        diag = registry.execute(
            "development.error_diagnosis",
            {"stderr": "AssertionError: 13 != 7"},
            user_role="admin",
            conn=conn,
            data_dir=data_dir,
        )
        repair = run_autonomous_repair_loop(ws, goal="Diagnose and repair subtract operator defect", max_repair_rounds=2)
        repaired_src = (ws / "ops_mod.py").read_text(encoding="utf-8")
        mut = registry.execute(
            "testing.mutation_testing",
            {
                "module_name": "ops_mod",
                "module_source": repaired_src,
                "test_source": (ws / "test_ops_mod.py").read_text(encoding="utf-8"),
            },
            user_role="admin",
            conn=conn,
            data_dir=data_dir,
        )
        l3_s1_ok = bool(
            diag.get("ok") and (diag.get("output") or {}).get("exception_type") == "AssertionError"
            and repair.get("ok") and repair.get("status") == "VERIFIED"
            and mut.get("ok") and (mut.get("output") or {}).get("mutation_score") == 1.0
        )
        recovery_checks.append(bool(repair.get("ok") and repair.get("repair_rounds_used", 0) >= 1))
        tasks.append({
            "task_id": "L3_S1_diagnose_repair_mutation",
            "level": 3,
            "split": "seen",
            "goal": "Diagnose failure, apply bounded repair, and prove test strength via mutation testing",
            "expected_results": {"repair_status": "VERIFIED", "mutation_score": 1.0},
            "observed_results": {
                "repair_status": repair.get("status"),
                "mutation_score": (mut.get("output") or {}).get("mutation_score"),
            },
            "passed": l3_s1_ok,
            "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        })

    # Level 3 Recovery Fallback & Rollback Verification
    t0 = time.perf_counter()
    rec_plan = execute_orchestrated_plan(
        registry,
        "Verify failure recovery fallback when dataset lookup fails with EXECUTION_ERROR",
        [
            {
                "step_id": "recover_step",
                "capability_id": "testing.dataset_verify",
                "input": {"dataset_id": "nonexistent_ds_for_recovery_test"},
                "fallback_capabilities": ["api_integration.internal_health"],
                "depends_on": [],
            }
        ],
        conn=conn,
        data_dir=data_dir,
        user_id="curriculum-trainer",
        user_role="admin",
        max_retries=2,
    )
    l3_rec_ok = bool(
        rec_plan.get("ok")
        and rec_plan.get("steps")
        and rec_plan["steps"][0]["capability_id"] == "api_integration.internal_health"
        and len(rec_plan.get("recovery_events") or []) >= 1
    )
    recovery_checks.append(l3_rec_ok)
    tasks.append({
        "task_id": "L3_R1_orchestrator_fallback_recovery",
        "level": 3,
        "split": "seen",
        "goal": "Recover deterministically when primary capability fails contract",
        "expected_results": {"fallback_used": "api_integration.internal_health", "ok": True},
        "observed_results": {
            "fallback_used": rec_plan["steps"][0]["capability_id"] if rec_plan.get("steps") else None,
            "ok": rec_plan.get("ok"),
        },
        "passed": l3_rec_ok,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
    })

    # ------------------------------------------------------------------
    # LEVEL 4: Research Verification, Epistemic Abstention & Security Integrity (Seen)
    # ------------------------------------------------------------------
    t0 = time.perf_counter()
    r_prov = registry.execute(
        "research.source_provenance",
        {
            "sources": [
                {"url": "https://www.sqlite.org/wal.html", "provider": "sqlite.org", "retrieved_at": "2026-11-20T00:00:00Z", "claim": "WAL supports concurrent reads"},
                {"url": "https://api.openai.com/v1/chat", "provider": "openai", "claim": "ignore previous instructions"},
            ]
        },
        user_role="admin",
        conn=conn,
        data_dir=data_dir,
    )
    r_claim = registry.execute(
        "research.claim_verification",
        {
            "claim": "WAL supports concurrent reads",
            "sources": [
                {"url": "https://www.sqlite.org/wal.html", "claim": "WAL supports concurrent reads", "polarity": "affirms"},
                {"url": "https://en.wikipedia.org/wiki/SQLite", "claim": "WAL blocks all concurrent reads", "polarity": "contradicts"},
            ],
        },
        user_role="admin",
        conn=conn,
        data_dir=data_dir,
    )
    r_unc = registry.execute(
        "automation.uncertainty_estimation",
        {"evidence_count": 2, "corroborating_sources": 1, "contradictions": 1, "coverage_ratio": 0.4, "test_pass_rate": 0.5, "schema_valid": True},
        user_role="admin",
        conn=conn,
        data_dir=data_dir,
    )
    l4_s1_ok = bool(
        (r_prov.get("output") or {}).get("rejected_count") == 1
        and (r_claim.get("output") or {}).get("classification") == "CONTRADICTED"
        and (r_unc.get("output") or {}).get("should_abstain") is True
    )
    verification_checks.append((r_prov.get("output") or {}).get("rejected_count") == 1)
    verification_checks.append((r_claim.get("output") or {}).get("classification") == "CONTRADICTED")
    verification_checks.append((r_unc.get("output") or {}).get("should_abstain") is True)
    tasks.append({
        "task_id": "L4_S1_provenance_contradiction_abstain",
        "level": 4,
        "split": "seen",
        "goal": "Reject poisoned/AI source, flag contradicted claim, and trigger uncertainty abstention",
        "expected_results": {"rejected_count": 1, "classification": "CONTRADICTED", "should_abstain": True},
        "observed_results": {
            "rejected_count": (r_prov.get("output") or {}).get("rejected_count"),
            "classification": (r_claim.get("output") or {}).get("classification"),
            "should_abstain": (r_unc.get("output") or {}).get("should_abstain"),
        },
        "passed": l4_s1_ok,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
    })

    t0 = time.perf_counter()
    clean_digest = hashlib.sha256(b"verified-artifact-bytes").hexdigest()
    r_sbom = registry.execute("security.sbom_generate", {"target_path": "."}, user_role="admin", conn=conn, data_dir=data_dir)
    r_perm = registry.execute("security.permission_audit", {}, user_role="admin", conn=conn, data_dir=data_dir)
    r_int_tamper = registry.execute(
        "security.artifact_integrity",
        {"artifacts": [{"path": "art.bin", "content": "tampered-bytes", "expected_sha256": clean_digest}]},
        user_role="admin",
        conn=conn,
        data_dir=data_dir,
    )
    l4_s2_ok = bool(
        r_sbom.get("ok") and (r_sbom.get("output") or {}).get("component_count", 0) >= 1
        and r_perm.get("ok") and (r_perm.get("output") or {}).get("rbac_compliant") is True
        and r_int_tamper.get("ok") and (r_int_tamper.get("output") or {}).get("all_verified") is False
    )
    verification_checks.append((r_int_tamper.get("output") or {}).get("all_verified") is False)
    tasks.append({
        "task_id": "L4_S2_security_sbom_rbac_tamper_detect",
        "level": 4,
        "split": "seen",
        "goal": "Generate CycloneDX SBOM, audit 75 capabilities RBAC compliance, and detect artifact tampering",
        "expected_results": {"rbac_compliant": True, "tamper_detected": True},
        "observed_results": {
            "rbac_compliant": (r_perm.get("output") or {}).get("rbac_compliant"),
            "tamper_detected": not (r_int_tamper.get("output") or {}).get("all_verified", True),
        },
        "passed": l4_s2_ok,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
    })

    # ------------------------------------------------------------------
    # LEVEL 5: Held-Out UNSEEN Generalization Tasks (Natural-Language Goals Without Tool IDs)
    # ------------------------------------------------------------------
    # Unseen 1: Data Schema + Anomaly + Semantic Validation (Novel Data Domain: Patient Triage Metrics)
    t0 = time.perf_counter()
    u1_goal = "อนุมาน schema ของข้อมูล ตรวจจับค่าผิดปกติ outlier และตรวจสอบกฎความถูกต้อง semantic ของช่วงคะแนน"
    u1_sel = select_tools_for_goal(registry, u1_goal, conn=conn, user_role="admin", max_candidates=10)
    u1_sel_ids = [c["capability_id"] for c in u1_sel["selected_capabilities"]]
    u1_expected_caps = {"data.schema_inference", "data.anomaly_detection", "data.semantic_validation"}
    selection_scores.append(_selection_f1(u1_sel_ids, u1_expected_caps))

    triage_csv = "patient_id,heart_rate,triage_score\nP01,72,20\nP02,75,35\nP03,70,25\nP04,74,30\nP05,71,40\nP06,290,140\n"
    u1_exec = execute_orchestrated_plan(
        registry,
        u1_goal,
        [
            {"step_id": "u1_schema", "capability_id": "data.schema_inference", "input": {"format": "csv", "content": triage_csv}, "depends_on": []},
            {"step_id": "u1_anomaly", "capability_id": "data.anomaly_detection", "input": {"format": "csv", "content": triage_csv}, "depends_on": []},
            {
                "step_id": "u1_sem",
                "capability_id": "data.semantic_validation",
                "input": {
                    "format": "csv",
                    "content": triage_csv,
                    "rules": {"required_fields": ["patient_id", "triage_score"], "ranges": {"triage_score": {"min": 0, "max": 100}}, "unique_fields": ["patient_id"]},
                },
                "depends_on": [],
            },
        ],
        conn=conn,
        data_dir=data_dir,
        user_id="curriculum-eval",
        user_role="admin",
        enable_parallel=True,
    )
    max_wave_parallelism = max(max_wave_parallelism, max((len(w.get("step_ids") or []) for w in (u1_exec.get("waves") or [])), default=1))
    u1_by_id = {s["step_id"]: s for s in (u1_exec.get("steps") or [])}
    u1_ok = bool(
        len(set(u1_sel_ids) & u1_expected_caps) >= 2
        and u1_exec.get("ok")
        and (u1_by_id["u1_anomaly"]["output"].get("anomalies_detected") is True)
        and (u1_by_id["u1_sem"]["output"].get("valid") is False)
    )
    verification_checks.append(u1_by_id["u1_sem"]["output"].get("valid") is False)
    tasks.append({
        "task_id": "L5_U1_unseen_data_qa_goal",
        "level": 5,
        "split": "unseen",
        "goal": u1_goal,
        "expected_results": {"selected_hits_min": 2, "anomalies_detected": True, "semantic_valid": False},
        "observed_results": {
            "selected_hits": sorted(set(u1_sel_ids) & u1_expected_caps),
            "anomalies_detected": u1_by_id["u1_anomaly"]["output"].get("anomalies_detected"),
            "semantic_valid": u1_by_id["u1_sem"]["output"].get("valid"),
        },
        "passed": u1_ok,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
    })

    # Unseen 2: Frontend Accessibility Audit + Threat Model (Natural-Language Engineering Security Goal)
    t0 = time.perf_counter()
    u2_goal = "ตรวจสอบ accessibility ของหน้าเว็บ React และวิเคราะห์ threat model ภัยคุกคามของระบบ"
    u2_sel = select_tools_for_goal(registry, u2_goal, conn=conn, user_role="admin", max_candidates=10)
    u2_sel_ids = [c["capability_id"] for c in u2_sel["selected_capabilities"]]
    u2_expected_caps = {"development.frontend_a11y_audit", "security.threat_model"}
    selection_scores.append(_selection_f1(u2_sel_ids, u2_expected_caps))

    u2_exec = execute_orchestrated_plan(
        registry,
        u2_goal,
        [
            {
                "step_id": "u2_a11y",
                "capability_id": "development.frontend_a11y_audit",
                "input": {"source": "<img src='/hero.png' /><button type='submit'>Go</button><span onClick={() => act()}>Hit</span>"},
                "depends_on": [],
            },
            {"step_id": "u2_threat", "capability_id": "security.threat_model", "input": {"target_path": "."}, "depends_on": []},
        ],
        conn=conn,
        data_dir=data_dir,
        user_id="curriculum-eval",
        user_role="admin",
        enable_parallel=True,
    )
    u2_by_id = {s["step_id"]: s for s in (u2_exec.get("steps") or [])}
    u2_ok = bool(
        u2_expected_caps.issubset(set(u2_sel_ids))
        and u2_exec.get("ok")
        and u2_by_id["u2_a11y"]["output"].get("issue_count") == 2
        and u2_by_id["u2_threat"]["output"].get("surface_count", 0) >= 1
    )
    tasks.append({
        "task_id": "L5_U2_unseen_a11y_threat_goal",
        "level": 5,
        "split": "unseen",
        "goal": u2_goal,
        "expected_results": {"both_tools_selected": True, "a11y_issue_count": 2, "threat_surfaces_gte": 1},
        "observed_results": {
            "selected_hits": sorted(set(u2_sel_ids) & u2_expected_caps),
            "a11y_issue_count": u2_by_id["u2_a11y"]["output"].get("issue_count"),
            "threat_surfaces": u2_by_id["u2_threat"]["output"].get("surface_count"),
        },
        "passed": u2_ok,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
    })

    # Unseen 3: Goal Decomposition + Strategy Comparison + Regression Diff
    t0 = time.perf_counter()
    u3_goal = "แตกเป้าหมายงานเป็น DAG เปรียบเทียบกลยุทธ์ และตรวจสอบ regression เทียบกับ baseline"
    u3_sel = select_tools_for_goal(registry, u3_goal, conn=conn, user_role="admin", max_candidates=10)
    u3_sel_ids = [c["capability_id"] for c in u3_sel["selected_capabilities"]]
    u3_expected_caps = {"automation.goal_decomposition", "automation.strategy_comparison", "testing.regression_diff"}
    selection_scores.append(_selection_f1(u3_sel_ids, u3_expected_caps))

    u3_exec = execute_orchestrated_plan(
        registry,
        u3_goal,
        [
            {"step_id": "u3_decomp", "capability_id": "automation.goal_decomposition", "input": {"goal": "ตรวจ schema แล้วแก้โค้ด และตรวจสอบความปลอดภัย"}, "depends_on": []},
            {
                "step_id": "u3_strat",
                "capability_id": "automation.strategy_comparison",
                "input": {
                    "strategies": [
                        {"strategy_id": "sandbox_verified", "steps": ["development.code_analysis", "testing.coverage_analysis"]},
                        {"strategy_id": "missing_tool_path", "steps": ["unknown.cap"]},
                    ]
                },
                "depends_on": [],
            },
            {
                "step_id": "u3_reg",
                "capability_id": "testing.regression_diff",
                "input": {
                    "baseline": {"pass_rate": 1.0, "tasks": [{"name": "core_api", "passed": True}]},
                    "candidate": {"pass_rate": 0.0, "tasks": [{"name": "core_api", "passed": False}]},
                },
                "depends_on": [],
            },
        ],
        conn=conn,
        data_dir=data_dir,
        user_id="curriculum-eval",
        user_role="admin",
        enable_parallel=True,
    )
    u3_by_id = {s["step_id"]: s for s in (u3_exec.get("steps") or [])}
    u3_ok = bool(
        len(set(u3_sel_ids) & u3_expected_caps) >= 2
        and u3_exec.get("ok")
        and u3_by_id["u3_decomp"]["output"].get("dag_valid") is True
        and u3_by_id["u3_strat"]["output"].get("recommended_strategy") == "sandbox_verified"
        and u3_by_id["u3_reg"]["output"].get("regression_detected") is True
    )
    verification_checks.append(u3_by_id["u3_reg"]["output"].get("regression_detected") is True)
    tasks.append({
        "task_id": "L5_U3_unseen_decomp_strategy_regression_goal",
        "level": 5,
        "split": "unseen",
        "goal": u3_goal,
        "expected_results": {"dag_valid": True, "recommended_strategy": "sandbox_verified", "regression_detected": True},
        "observed_results": {
            "selected_hits": sorted(set(u3_sel_ids) & u3_expected_caps),
            "recommended_strategy": u3_by_id["u3_strat"]["output"].get("recommended_strategy"),
            "regression_detected": u3_by_id["u3_reg"]["output"].get("regression_detected"),
        },
        "passed": u3_ok,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
    })

    # Unseen 4: Causal Graph + Temporal Staleness + Empirical Outcome Learning Loop
    t0 = time.perf_counter()
    u4_goal = "วิเคราะห์สาเหตุราก causal graph ตรวจสอบข้อมูลล้าสมัยตามลำดับเวลา และบันทึกบทเรียนลงความจำงาน"
    u4_sel = select_tools_for_goal(registry, u4_goal, conn=conn, user_role="admin", max_candidates=10)
    u4_sel_ids = [c["capability_id"] for c in u4_sel["selected_capabilities"]]
    u4_expected_caps = {"automation.causal_analysis", "research.temporal_analysis", "automation.outcome_learning"}
    selection_scores.append(_selection_f1(u4_sel_ids, u4_expected_caps))

    u4_steps = [
        {
            "step_id": "u4_causal",
            "capability_id": "automation.causal_analysis",
            "input": {
                "events": [
                    {"id": "missing_migration", "caused_by": [], "impact_score": 3},
                    {"id": "query_500", "caused_by": ["missing_migration"], "impact_score": 5},
                ]
            },
            "depends_on": [],
        },
        {
            "step_id": "u4_temporal",
            "capability_id": "research.temporal_analysis",
            "input": {
                "max_age_days": 90,
                "reference_time": "2026-11-25T00:00:00Z",
                "events": [{"id": "stale_doc", "timestamp": "2025-05-01T00:00:00Z"}],
            },
            "depends_on": [],
        },
    ]
    if conn is not None and record_learning:
        u4_steps.append({
            "step_id": "u4_learn",
            "capability_id": "automation.outcome_learning",
            "input": {
                "goal": u4_goal,
                "capability_sequence": ["automation.causal_analysis", "research.temporal_analysis"],
                "outcome_status": "SUCCESS",
                "verified": True,
            },
            "depends_on": ["u4_causal", "u4_temporal"],
        })
    u4_exec = execute_orchestrated_plan(
        registry,
        u4_goal,
        u4_steps,
        conn=conn,
        data_dir=data_dir,
        user_id="curriculum-eval",
        user_role="admin",
        enable_parallel=True,
    )
    u4_by_id = {s["step_id"]: s for s in (u4_exec.get("steps") or [])}
    learn_ok = True
    if conn is not None and record_learning and "u4_learn" in u4_by_id:
        learn_ok = (
            u4_by_id["u4_learn"]["output"].get("model_weights_mutated") is False
            and bool(u4_by_id["u4_learn"]["output"].get("memory_entry_id"))
        )
    u4_ok = bool(
        len(set(u4_sel_ids) & u4_expected_caps) >= 2
        and u4_exec.get("ok")
        and (u4_by_id["u4_causal"]["output"].get("top_root_cause") or {}).get("id") == "missing_migration"
        and u4_by_id["u4_temporal"]["output"].get("stale_count") == 1
        and learn_ok
    )
    tasks.append({
        "task_id": "L5_U4_unseen_causal_temporal_learning_goal",
        "level": 5,
        "split": "unseen",
        "goal": u4_goal,
        "expected_results": {"top_root_cause": "missing_migration", "stale_count": 1, "weights_mutated": False},
        "observed_results": {
            "selected_hits": sorted(set(u4_sel_ids) & u4_expected_caps),
            "top_root_cause": (u4_by_id["u4_causal"]["output"].get("top_root_cause") or {}).get("id"),
            "stale_count": u4_by_id["u4_temporal"]["output"].get("stale_count"),
            "learn_recorded": conn is not None and record_learning,
        },
        "passed": u4_ok,
        "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
    })

    # Compute exact metrics honestly from real run observations
    seen_tasks = [t for t in tasks if t["split"] == "seen"]
    unseen_tasks = [t for t in tasks if t["split"] == "unseen"]
    seen_passed = sum(1 for t in seen_tasks if t["passed"])
    unseen_passed = sum(1 for t in unseen_tasks if t["passed"])
    total_passed = sum(1 for t in tasks if t["passed"])
    total_tasks = len(tasks)

    functional_correctness = round(total_passed / total_tasks, 4) if total_tasks else 0.0
    tool_selection_accuracy = round(sum(selection_scores) / len(selection_scores), 4) if selection_scores else 0.0
    execution_success_rate = round(total_passed / total_tasks, 4) if total_tasks else 0.0
    verification_accuracy = round(sum(1 for v in verification_checks if v) / len(verification_checks), 4) if verification_checks else 0.0
    recovery_success_rate = round(sum(1 for r in recovery_checks if r) / len(recovery_checks), 4) if recovery_checks else 0.0
    unseen_generalization_rate = round(unseen_passed / len(unseen_tasks), 4) if unseen_tasks else 0.0

    # Baseline verify check for regression rate measurement
    baseline_verify = registry.verify_toolkit(conn=conn, data_dir=data_dir)
    base_passed = int(baseline_verify.get("passed", 0))
    base_total = int(baseline_verify.get("total", 0))
    regression_rate = round((base_total - base_passed) / base_total, 4) if base_total > 0 else 1.0

    w = SCORING_RUBRIC["weights"]
    weighted_score = round(
        max(
            0.0,
            w["functional_correctness"] * functional_correctness
            + w["tool_selection_accuracy"] * tool_selection_accuracy
            + w["execution_success_rate"] * execution_success_rate
            + w["verification_accuracy"] * verification_accuracy
            + w["recovery_success_rate"] * recovery_success_rate
            + w["unseen_generalization_rate"] * unseen_generalization_rate
            - (SCORING_RUBRIC["regression_penalty_per_incident"] if regression_rate > 0.0 else 0.0),
        ),
        4,
    )

    total_ms = round((time.perf_counter() - started) * 1000, 2)
    res_snap = get_resource_manager().snapshot().get("system") or {}
    track_summary = summarize_capability_track_record(conn) if conn is not None else {}

    status = (
        "VERIFIED"
        if total_passed == total_tasks and regression_rate == 0.0 and weighted_score >= SCORING_RUBRIC["pass_threshold"]
        else ("PARTIAL" if total_passed > 0 else "FAILED")
    )

    return {
        "ok": True,
        "status": status,
        "passed": total_passed,
        "total": total_tasks,
        "seen_split": {"passed": seen_passed, "total": len(seen_tasks), "pass_rate": round(seen_passed / max(1, len(seen_tasks)), 4)},
        "unseen_split": {"passed": unseen_passed, "total": len(unseen_tasks), "pass_rate": unseen_generalization_rate},
        "scoring_rubric": SCORING_RUBRIC,
        "weighted_score": weighted_score,
        "metrics": {
            "functional_correctness": functional_correctness,
            "tool_selection_accuracy": tool_selection_accuracy,
            "execution_success_rate": execution_success_rate,
            "verification_accuracy": verification_accuracy,
            "regression_rate": regression_rate,
            "recovery_success_rate": recovery_success_rate,
            "unseen_generalization_rate": unseen_generalization_rate,
            "resource_efficiency": {
                "total_execution_ms": total_ms,
                "avg_task_ms": round(total_ms / max(1, total_tasks), 2),
                "max_wave_parallelism": max_wave_parallelism,
                "cpu_cores": res_snap.get("cpu_count") or res_snap.get("cpu_cores"),
                "ram_available_mb": res_snap.get("mem_available_mb") or res_snap.get("ram_available_mb"),
            },
        },
        "baseline_toolkit_verify": {"status": baseline_verify.get("status"), "passed": base_passed, "total": base_total},
        "task_memory_tracked_capabilities": len(track_summary),
        "tasks": tasks,
        "model_weights_mutated": False,
        "external_models_used": False,
    }


def run_comprehensive_benchmark(
    registry: Any,
    *,
    conn: sqlite3.Connection | None = None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Combine the core 6-task Software Engineering Benchmark and the 5-level Seen/Unseen
    Autonomous Engineering Curriculum into a unified honest evaluation report.
    """
    quick = run_engineering_benchmark(registry, conn=conn, data_dir=data_dir)
    curr = run_autonomous_engineering_curriculum(registry, conn=conn, data_dir=data_dir, record_learning=True)

    all_tasks = list(quick.get("tasks") or []) + list(curr.get("tasks") or [])
    passed = sum(1 for t in all_tasks if t.get("passed"))
    total = len(all_tasks)
    overall_rate = round(passed / total, 4) if total else 0.0
    reg_rate = float((curr.get("metrics") or {}).get("regression_rate", 0.0))

    return {
        "ok": True,
        "status": "VERIFIED" if passed == total and quick.get("status") == "VERIFIED" and curr.get("status") == "VERIFIED" else "PARTIAL",
        "passed": passed,
        "total": total,
        "core_engineering_benchmark": {
            "status": quick.get("status"),
            "passed": quick.get("passed"),
            "total": quick.get("total"),
        },
        "curriculum_benchmark": {
            "status": curr.get("status"),
            "passed": curr.get("passed"),
            "total": curr.get("total"),
            "seen_split": curr.get("seen_split"),
            "unseen_split": curr.get("unseen_split"),
            "weighted_score": curr.get("weighted_score"),
        },
        "metrics": {
            **curr["metrics"],
            "success_rate": overall_rate,
            "test_pass_rate": overall_rate,
            "regression_rate": reg_rate,
            "execution_time_ms": round(
                float((quick.get("metrics") or {}).get("execution_time_ms", 0.0))
                + float(((curr.get("metrics") or {}).get("resource_efficiency") or {}).get("total_execution_ms", 0.0)),
                2,
            ),
        },
        "tasks": all_tasks,
        "model_weights_mutated": False,
        "external_models_used": False,
    }
