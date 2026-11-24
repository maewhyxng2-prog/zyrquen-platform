"""Reproducible Python Benchmark Runner for ZYRQUEN Ω∞ P1-1.

Measures real current capabilities across existing ZYRQUEN Core interfaces without:
- modifying model architecture, memory, tokenizer, or reasoning engine,
- calling external AI APIs or external pretrained weights, or
- treating mock outputs (e.g. legacy apps/core/evaluation/engine.py) as real model scores.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import math
import platform
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "tools"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from apps.core.intelligence import (  # noqa: E402
    ExecutionPolicy,
    IntelligenceRuntime,
    KnowledgeSystem,
    PermissionGate,
    ReasoningEngine,
    ToolRegistry,
)
from apps.core.intelligence.contract import ContractViolation, validate_result  # noqa: E402
from apps.core.intelligence.planning import PlanningEngine, PlanViolation  # noqa: E402
from apps.core.model_loader import NativeModelLoader  # noqa: E402
from apps.core.native.config import MAX_V10_PARAMETERS, ZyrquenConfig  # noqa: E402
from apps.core.native.dataset import (  # noqa: E402
    SCHEMA as DATASET_SCHEMA,
    verify_dataset_manifest,
)
from apps.core.native.evaluation import (  # noqa: E402
    EvaluationEngine,
    EvaluationEvidenceError,
    EvaluationNotConfiguredError,
    calculate_perplexity,
    calculate_token_accuracy,
)
from apps.core.native.sft import (  # noqa: E402
    IGNORE_INDEX,
    bind_ephemeral_slots,
    encode_sft_pair,
    encode_sft_prompt,
    restore_ephemeral_slots,
    train_slot_safe_tokenizer,
)
from apps.core.native.tokenizer import (  # noqa: E402
    SCHEMA_V2,
    SLOT_COUNT,
    ZyrquenTokenizer,
)
import audit_leakage_v10 as v10_audit  # noqa: E402

BENCHMARK_SCHEMA = "zyrquen.p1_1.baseline_report.v1"
FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures" / "p1_1_benchmark_fixtures.json"
LEGACY_GOLDEN_PATH = REPO_ROOT / "apps" / "core" / "evaluation" / "golden_dataset.json"
INFERENCE_ROUTER_PATH = REPO_ROOT / "apps" / "api" / "routers" / "inference.py"


@dataclass(frozen=True)
class BenchmarkCaseResult:
    case_id: str
    category: str
    description: str
    expected_polarity: str
    status: str  # PASS | FAIL | BLOCKED | UNAVAILABLE
    verification_status: str  # VERIFIED | UNVERIFIED | NOT_FOUND | UNAVAILABLE | BLOCKED
    confusion_outcome: str  # TP | TN | FP | FN | N/A
    failure_type: str | None = None
    sample_input: str | None = None
    expected: str | None = None
    actual: str | None = None
    detail: str = ""


def load_benchmark_fixtures(path: Path | None = None) -> dict[str, Any]:
    target = path or FIXTURES_PATH
    data = json.loads(target.read_text(encoding="utf-8"))
    if data.get("schema") != "zyrquen.p1_1.benchmark_fixtures.v1":
        raise ValueError(f"Unexpected benchmark fixture schema: {data.get('schema')!r}")
    return data


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _probe_environment() -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "torch_installed": importlib.util.find_spec("torch") is not None,
        "pydantic_installed": importlib.util.find_spec("pydantic") is not None,
        "pytest_installed": importlib.util.find_spec("pytest") is not None,
        "fastapi_installed": importlib.util.find_spec("fastapi") is not None,
        "git_repo_present": (REPO_ROOT / ".git").exists(),
    }


def _probe_model_state() -> dict[str, Any]:
    eval_status = EvaluationEngine().get_status()
    loader = NativeModelLoader()
    return {
        "evaluation_engine_status": eval_status,
        "model_loader_health": loader.health_state(),
        "model_version": loader.model_version,
        "is_trained": loader.is_trained,
        "inference_available": loader.is_ready(),
        "native_runtime_note": (
            "No trained checkpoint or PyTorch runtime configured; native Transformer weights are NOT evaluated."
        ),
    }


def _run_positive_cases(fx: dict[str, Any]) -> list[BenchmarkCaseResult]:
    results: list[BenchmarkCaseResult] = []
    pos = fx["positive_cases"]

    # 1. Direct 1-hop grounded lookup via KnowledgeSystem + ReasoningEngine
    k_spec = pos["knowledge_direct_lookup"]
    ks = KnowledgeSystem()
    ks.add_entity(k_spec["entity_a"], k_spec["entity_a_data"])
    ks.add_entity(k_spec["entity_b"], k_spec["entity_b_data"])
    ks.add_relation(k_spec["entity_a"], k_spec["entity_b"])
    res = ReasoningEngine(ks).deduce(context=k_spec["entity_a"], question=k_spec["question"])
    ok = (
        res["status"] == "lookup_only"
        and res["related_knowledge_found"] is True
        and k_spec["entity_b"] in res["reasoning_path"]
        and res["model_inference"] is False
    )
    results.append(
        BenchmarkCaseResult(
            case_id="pos_knowledge_direct_lookup",
            category="positive",
            description="KnowledgeSystem + ReasoningEngine 1-hop positive lookup",
            expected_polarity="positive",
            status="PASS" if ok else "FAIL",
            verification_status="VERIFIED" if ok else "UNVERIFIED",
            confusion_outcome="TP" if ok else "FN",
            failure_type=None if ok else "DIRECT_LOOKUP_FAILED",
            sample_input=k_spec["entity_a"],
            expected=k_spec["entity_b"],
            actual=json.dumps(res["reasoning_path"]),
            detail="Rule-based 1-hop lookup returned exact target entity.",
        )
    )

    # 2. PlanningEngine valid DAG topological ordering
    p_spec = pos["planning_valid_dag"]
    plan = PlanningEngine().build_plan(
        goal=p_spec["goal"],
        context={"phase": "p1_1"},
        steps=p_spec["steps"],
    )
    ok_plan = (
        plan["status"] == "valid_structure"
        and plan["step_order"] == ["bm_step_load_fixtures", "bm_step_run_checks", "bm_step_emit_report"]
    )
    results.append(
        BenchmarkCaseResult(
            case_id="pos_planning_valid_dag",
            category="positive",
            description="PlanningEngine topological ordering on valid DAG",
            expected_polarity="positive",
            status="PASS" if ok_plan else "FAIL",
            verification_status="VERIFIED" if ok_plan else "UNVERIFIED",
            confusion_outcome="TP" if ok_plan else "FN",
            failure_type=None if ok_plan else "PLAN_VALIDATION_FAILED",
            sample_input=p_spec["goal"],
            expected="valid_structure",
            actual=plan["status"],
            detail=f"step_order={plan['step_order']}",
        )
    )

    # 3. ToolRegistry + PermissionGate positive read-only authorization
    t_spec = pos["tool_read_only_auth"]
    reg = ToolRegistry()
    reg.register(t_spec["tool"])
    gate = PermissionGate(reg, ExecutionPolicy(allow_read_only=True, allow_side_effecting=False))
    auth = gate.authorize(t_spec["call"], set(t_spec["granted_permissions"]))
    ok_auth = auth["status"] == "authorized" and auth["execution_performed"] is False
    results.append(
        BenchmarkCaseResult(
            case_id="pos_tool_read_only_auth",
            category="positive",
            description="PermissionGate authorizes registered read_only tool with valid permission",
            expected_polarity="positive",
            status="PASS" if ok_auth else "FAIL",
            verification_status="VERIFIED" if ok_auth else "UNVERIFIED",
            confusion_outcome="TP" if ok_auth else "FN",
            failure_type=None if ok_auth else "TOOL_AUTH_FAILED",
            sample_input=t_spec["call"]["tool_name"],
            expected="authorized",
            actual=auth["status"],
            detail="Authorization succeeded cleanly without executing side effects.",
        )
    )

    # 4. EvaluationEngine.verify_dataset on isolated held-out SFT manifest
    with tempfile.TemporaryDirectory() as td:
        ds_dir = Path(td)
        rows = [
            {"input": "BM_P1_A -> BM_P1_B", "target": "BM_P1_B"},
            {"input": "BM_P1_C -> BM_P1_D", "target": "BM_P1_D"},
        ]
        train_p = ds_dir / "train.jsonl"
        val_p = ds_dir / "validation.jsonl"
        test_p = ds_dir / "test.jsonl"
        train_p.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
        val_p.write_text(json.dumps(rows[1]) + "\n", encoding="utf-8")
        test_p.write_text(json.dumps(rows[1]) + "\n", encoding="utf-8")
        h_tr = _sha256_bytes(train_p.read_bytes())
        h_va = _sha256_bytes(val_p.read_bytes())
        h_te = _sha256_bytes(test_p.read_bytes())
        manifest = {
            "schema": DATASET_SCHEMA,
            "version": "p1.1.test",
            "content_sha256": _sha256_text(h_tr + h_va + h_te),
            "files": {
                "train.jsonl": {"documents": 1, "sha256": h_tr},
                "validation.jsonl": {"documents": 1, "sha256": h_va},
                "test.jsonl": {"documents": 1, "sha256": h_te},
            },
        }
        (ds_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        verified_manifest = verify_dataset_manifest(ds_dir)
        ok_ds = verified_manifest.get("version") == "p1.1.test"

    results.append(
        BenchmarkCaseResult(
            case_id="pos_dataset_manifest_integrity",
            category="positive",
            description="Dataset manifest SHA-256 verification on isolated held-out SFT splits",
            expected_polarity="positive",
            status="PASS" if ok_ds else "FAIL",
            verification_status="VERIFIED" if ok_ds else "UNVERIFIED",
            confusion_outcome="TP" if ok_ds else "FN",
            failure_type=None if ok_ds else "DATASET_VERIFY_FAILED",
            expected="p1.1.test",
            actual=str(verified_manifest.get("version")),
            detail="Manifest and per-split SHA-256 digests verified.",
        )
    )

    return results


def _run_negative_abstention_cases(fx: dict[str, Any]) -> list[BenchmarkCaseResult]:
    results: list[BenchmarkCaseResult] = []
    neg = fx["negative_abstention_cases"]

    # 1. Ungrounded entity -> must abstain (`no_knowledge_found`)
    ug = neg["ungrounded_entity_query"]
    ks = KnowledgeSystem()
    ks.add_entity(ug["known_entity"], {"kind": "probe"})
    ans = ReasoningEngine(ks).deduce(context=ug["unknown_query_entity"], question=ug["question"])
    abstained = ans["status"] == "no_knowledge_found" and ans["related_knowledge_found"] is False
    results.append(
        BenchmarkCaseResult(
            case_id="neg_ungrounded_entity_abstention",
            category="negative_abstention",
            description="ReasoningEngine abstains cleanly on unknown entity without fabricating relations",
            expected_polarity="abstention",
            status="PASS" if abstained else "FAIL",
            verification_status="NOT_FOUND" if abstained else "UNVERIFIED",
            confusion_outcome="TN" if abstained else "FP",
            failure_type=None if abstained else "HALLUCINATED_RELATION",
            sample_input=ug["unknown_query_entity"],
            expected="no_knowledge_found",
            actual=ans["status"],
            detail="Abstained on unknown context key.",
        )
    )

    # 2. Reasoning contract blocks ungrounded model_inference=True claim
    from apps.core.intelligence.contract import validate_result

    fake_claim = {
        "context": "x",
        "question": "q",
        "related_knowledge_found": False,
        "reasoning_path": [],
        "status": "no_knowledge_found",
        "engine_type": "rule_based_scaffold",
        "model_inference": True,
    }
    rejected_claim = False
    try:
        validate_result(fake_claim, native_model_evidence=None)
    except ContractViolation:
        rejected_claim = True
    results.append(
        BenchmarkCaseResult(
            case_id="neg_reject_fabricated_inference_claim",
            category="negative_abstention",
            description="Reasoning contract rejects model_inference=True without native_model_evidence",
            expected_polarity="negative",
            status="PASS" if rejected_claim else "FAIL",
            verification_status="VERIFIED" if rejected_claim else "UNVERIFIED",
            confusion_outcome="TN" if rejected_claim else "FP",
            failure_type=None if rejected_claim else "FABRICATED_INFERENCE_ACCEPTED",
            expected="ContractViolation",
            actual="ContractViolation" if rejected_claim else "accepted",
            detail="Closed reasoning contract enforced anti-fabrication guard.",
        )
    )

    # 3. PermissionGate rejects unapproved side-effecting tool
    se = neg["side_effecting_tool_unapproved"]
    reg = ToolRegistry()
    reg.register(se["tool"])
    gate = PermissionGate(reg, ExecutionPolicy(allow_read_only=True, allow_side_effecting=True))
    decision = gate.authorize(se["call"], {"benchmark:publish"}, approval_granted=False)
    denied = decision["status"] == "denied" and "explicit_approval_required" in decision["reasons"]
    results.append(
        BenchmarkCaseResult(
            case_id="neg_deny_unapproved_side_effect_tool",
            category="negative_abstention",
            description="PermissionGate denies side_effecting tool without explicit approval",
            expected_polarity="negative",
            status="PASS" if denied else "FAIL",
            verification_status="BLOCKED" if denied else "UNVERIFIED",
            confusion_outcome="TN" if denied else "FP",
            failure_type=None if denied else "UNAPPROVED_TOOL_AUTHORIZED",
            sample_input=se["call"]["tool_name"],
            expected="denied",
            actual=decision["status"],
            detail=f"reasons={decision['reasons']}",
        )
    )

    # 4. EvaluationEngine rejects unconfigured/missing checkpoint and tampered metrics
    with tempfile.TemporaryDirectory() as td:
        eng = EvaluationEngine(Path(td))
        missing_rejected = False
        try:
            eng.evaluate("ZYRQUEN-Native-10.0.99", {"val_loss": 1.0})
        except EvaluationEvidenceError:
            missing_rejected = True
    results.append(
        BenchmarkCaseResult(
            case_id="neg_reject_missing_checkpoint_evidence",
            category="negative_abstention",
            description="Native EvaluationEngine rejects evaluation without verified checkpoint artifacts",
            expected_polarity="negative",
            status="PASS" if missing_rejected else "FAIL",
            verification_status="VERIFIED" if missing_rejected else "UNVERIFIED",
            confusion_outcome="TN" if missing_rejected else "FP",
            failure_type=None if missing_rejected else "MISSING_CHECKPOINT_ACCEPTED",
            expected="EvaluationEvidenceError",
            actual="EvaluationEvidenceError" if missing_rejected else "accepted",
            detail="Fail-closed checkpoint gate verified.",
        )
    )

    # 5. Evidence freshness / URL provenance / unverified claim rejection gap on KnowledgeSystem + ReasoningEngine
    uv = neg["unverified_evidence_metadata"]
    ks_uv = KnowledgeSystem()
    ks_uv.add_entity(uv["entity_id"], uv["metadata"])
    ks_uv.add_entity(uv["related_target"], {"kind": "claim_target"})
    ks_uv.add_relation(uv["entity_id"], uv["related_target"])
    uv_res = ReasoningEngine(ks_uv).deduce(context=uv["entity_id"], question=uv["question"])
    # Expected under Anti-Fabrication Policy: reject/flag STALE or invalid URL; actual: returns lookup_only blindly (FP!)
    properly_rejected = uv_res["status"] != "lookup_only"
    results.append(
        BenchmarkCaseResult(
            case_id="neg_reject_stale_invalid_url_evidence",
            category="negative_abstention",
            description="ReasoningEngine rejects STALE / invalid-URL / unverified entity metadata",
            expected_polarity="abstention",
            status="PASS" if properly_rejected else "FAIL",
            verification_status="UNVERIFIED",
            confusion_outcome="TN" if properly_rejected else "FP",
            failure_type=None if properly_rejected else "NO_PROVENANCE_OR_FRESHNESS_VALIDATION",
            sample_input=f"{uv['entity_id']} (url={uv['metadata']['source_url']}, freshness={uv['metadata']['freshness']})",
            expected="reject/abstain on STALE & invalid URL",
            actual=f"status={uv_res['status']}, path={uv_res['reasoning_path']}",
            detail=(
                "False Positive gap: KnowledgeSystem/ReasoningEngine returns relation blindly without "
                "checking URL validity, data freshness (STALE), or verified provenance."
            ),
        )
    )

    return results


def _run_math_logic_cases(fx: dict[str, Any]) -> list[BenchmarkCaseResult]:
    results: list[BenchmarkCaseResult] = []
    ml = fx["math_logic_cases"]

    # 1. Perplexity & token accuracy numeric math checks
    ppl = calculate_perplexity(ml["perplexity_loss"])
    acc = calculate_token_accuracy(ml["token_preds"], ml["token_targets"])
    math_ok = math.isclose(ppl, math.exp(ml["perplexity_loss"]), rel_tol=1e-9) and math.isclose(
        acc, ml["expected_token_accuracy"], rel_tol=1e-9
    )
    results.append(
        BenchmarkCaseResult(
            case_id="math_eval_metrics_exact",
            category="math_logic",
            description="Native evaluation perplexity and token accuracy numeric precision",
            expected_polarity="positive",
            status="PASS" if math_ok else "FAIL",
            verification_status="VERIFIED" if math_ok else "UNVERIFIED",
            confusion_outcome="TP" if math_ok else "FN",
            failure_type=None if math_ok else "METRIC_FORMULA_MISMATCH",
            expected=f"ppl={math.exp(ml['perplexity_loss']):.4f}, acc={ml['expected_token_accuracy']}",
            actual=f"ppl={ppl:.4f}, acc={acc}",
            detail="Deterministic metric helpers verified.",
        )
    )

    # 2. Parameter budget calculation <= 5,000,000
    cfg = ZyrquenConfig()
    params = cfg.validate_parameter_budget(MAX_V10_PARAMETERS)
    budget_ok = 0 < params <= MAX_V10_PARAMETERS
    results.append(
        BenchmarkCaseResult(
            case_id="math_model_parameter_budget",
            category="math_logic",
            description="ZyrquenConfig parameter count computation stays within 5M CPU budget",
            expected_polarity="positive",
            status="PASS" if budget_ok else "FAIL",
            verification_status="VERIFIED" if budget_ok else "UNVERIFIED",
            confusion_outcome="TP" if budget_ok else "FN",
            failure_type=None if budget_ok else "PARAMETER_BUDGET_ERROR",
            expected=f"<= {MAX_V10_PARAMETERS}",
            actual=str(params),
            detail="Decoder config parameter formula matches architectural limit.",
        )
    )

    # 3. PlanningEngine cyclic logic detection (negative logic check)
    cycle_rejected = False
    try:
        PlanningEngine().build_plan(
            goal=ml["cyclic_plan"]["goal"],
            context={},
            steps=ml["cyclic_plan"]["steps"],
        )
    except PlanViolation as exc:
        cycle_rejected = "cycle" in str(exc).lower()
    results.append(
        BenchmarkCaseResult(
            case_id="logic_detect_dependency_cycle",
            category="math_logic",
            description="PlanningEngine detects circular dependency cycle in DAG steps",
            expected_polarity="negative",
            status="PASS" if cycle_rejected else "FAIL",
            verification_status="VERIFIED" if cycle_rejected else "UNVERIFIED",
            confusion_outcome="TN" if cycle_rejected else "FP",
            failure_type=None if cycle_rejected else "CYCLE_NOT_DETECTED",
            expected="PlanViolation (dependency cycle)",
            actual="PlanViolation" if cycle_rejected else "accepted",
            detail="Kahn topological check caught A <-> B cycle.",
        )
    )

    # 4. Transitive order logic on ReasoningEngine (real core weakness!)
    tr = ml["transitive_order"]
    ks_ord = KnowledgeSystem()
    for fact in tr["facts"]:
        ks_ord.add_entity(fact["source"], {})
        ks_ord.add_entity(fact["target"], {})
        ks_ord.add_relation(fact["source"], fact["target"])
    ord_res = ReasoningEngine(ks_ord).deduce(
        context=tr["query_left"],
        question=f"Is {tr['query_left']} > {tr['query_right']}?",
    )
    # Also verify ground truth using reference verifier from audit_leakage_v10
    verifier_ok, verifier_ans = v10_audit._verify_order_dag(tr["facts"], tr["query_left"], tr["query_right"])
    transitive_solved = (
        verifier_ok
        and verifier_ans == tr["expected_answer"]
        and (
            tr["query_right"] in ord_res.get("reasoning_path", [])
            or ord_res.get("status") == tr["expected_answer"]
        )
    )
    results.append(
        BenchmarkCaseResult(
            case_id="logic_reasoning_transitive_order",
            category="math_logic",
            description="ReasoningEngine solves 2-step transitive ordering (X1 > X2 > X3 => X1 > X3)",
            expected_polarity="positive",
            status="PASS" if transitive_solved else "FAIL",
            verification_status="UNVERIFIED" if not transitive_solved else "VERIFIED",
            confusion_outcome="TP" if transitive_solved else "FN",
            failure_type=None if transitive_solved else "NO_TRANSITIVE_LOGIC_INFERENCE",
            sample_input=f"{tr['query_left']} > {tr['query_right']} given X1>X2, X2>X3",
            expected=f"relation={tr['expected_answer']} reaching {tr['query_right']}",
            actual=f"status={ord_res['status']}, path={ord_res['reasoning_path']}",
            detail=(
                "False Negative gap: ReasoningEngine performs 1-hop dict lookup only and cannot infer "
                "transitive closure or output ordering symbols."
            ),
        )
    )

    # 5. Arithmetic/logic computation via ReasoningEngine (real core weakness!)
    ar = ml["arithmetic_query"]
    ks_ar = KnowledgeSystem()
    ar_res = ReasoningEngine(ks_ar).deduce(context=ar["context"], question=ar["question"])
    ar_solved = ar["expected_answer"] in str(ar_res.get("reasoning_path", []))
    results.append(
        BenchmarkCaseResult(
            case_id="math_reasoning_arithmetic",
            category="math_logic",
            description="ReasoningEngine evaluates deterministic arithmetic expression (18 * 4 - 9 = 63)",
            expected_polarity="positive",
            status="PASS" if ar_solved else "FAIL",
            verification_status="UNVERIFIED" if not ar_solved else "VERIFIED",
            confusion_outcome="TP" if ar_solved else "FN",
            failure_type=None if ar_solved else "NO_ARITHMETIC_OR_CALCULATOR_EXECUTION",
            sample_input=ar["question"],
            expected=ar["expected_answer"],
            actual=f"status={ar_res['status']}, path={ar_res['reasoning_path']}",
            detail=(
                "False Negative gap: ReasoningEngine has model_inference=False and no calculator/logic execution."
            ),
        )
    )

    return results


def _run_graph_multi_hop_cases(fx: dict[str, Any]) -> list[BenchmarkCaseResult]:
    results: list[BenchmarkCaseResult] = []
    gm = fx["graph_multi_hop_cases"]
    nodes = gm["chain_nodes"]

    ks = KnowledgeSystem()
    for n in nodes:
        ks.add_entity(n, {"kind": "graph_node"})
    for src, dst in zip(nodes, nodes[1:]):
        ks.add_relation(src, dst)
    engine = ReasoningEngine(ks)

    # 1. 1-hop graph lookup
    r1 = engine.deduce(context=nodes[0], question=f"1-hop from {nodes[0]}")
    ok_1 = nodes[1] in r1["reasoning_path"]
    results.append(
        BenchmarkCaseResult(
            case_id="graph_1hop_lookup",
            category="graph_multi_hop",
            description="1-hop directed edge traversal via ReasoningEngine",
            expected_polarity="positive",
            status="PASS" if ok_1 else "FAIL",
            verification_status="VERIFIED" if ok_1 else "UNVERIFIED",
            confusion_outcome="TP" if ok_1 else "FN",
            failure_type=None if ok_1 else "ONE_HOP_FAILED",
            sample_input=f"{nodes[0]} -> ?",
            expected=nodes[1],
            actual=str(r1["reasoning_path"]),
        )
    )

    # 2. 2-hop graph traversal (exposes SINGLE_HOP_LOOKUP_ONLY weakness)
    r2 = engine.deduce(context=nodes[0], question=f"2-hop endpoint from {nodes[0]}")
    ok_2 = gm["two_hop_target"] in r2["reasoning_path"]
    results.append(
        BenchmarkCaseResult(
            case_id="graph_2hop_traversal",
            category="graph_multi_hop",
            description="2-hop directed path traversal (G0 -> G1 -> G2) via ReasoningEngine",
            expected_polarity="positive",
            status="PASS" if ok_2 else "FAIL",
            verification_status="UNVERIFIED" if not ok_2 else "VERIFIED",
            confusion_outcome="TP" if ok_2 else "FN",
            failure_type=None if ok_2 else "SINGLE_HOP_LOOKUP_ONLY",
            sample_input=f"2-hop from {nodes[0]}",
            expected=gm["two_hop_target"],
            actual=str(r2["reasoning_path"]),
            detail="ReasoningEngine returned only immediate 1-hop neighbor G1.",
        )
    )

    # 3. 3-hop graph traversal (exposes SINGLE_HOP_LOOKUP_ONLY weakness)
    r3 = engine.deduce(context=nodes[0], question=f"3-hop endpoint from {nodes[0]}")
    ok_3 = gm["three_hop_target"] in r3["reasoning_path"]
    results.append(
        BenchmarkCaseResult(
            case_id="graph_3hop_traversal",
            category="graph_multi_hop",
            description="3-hop directed path traversal (G0 -> G1 -> G2 -> G3) via ReasoningEngine",
            expected_polarity="positive",
            status="PASS" if ok_3 else "FAIL",
            verification_status="UNVERIFIED" if not ok_3 else "VERIFIED",
            confusion_outcome="TP" if ok_3 else "FN",
            failure_type=None if ok_3 else "SINGLE_HOP_LOOKUP_ONLY",
            sample_input=f"3-hop from {nodes[0]}",
            expected=gm["three_hop_target"],
            actual=str(r3["reasoning_path"]),
            detail="ReasoningEngine cannot compose multi-hop relational chains.",
        )
    )

    # 4. Diamond DAG multi-step plan ordering on PlanningEngine
    dp = gm["diamond_plan"]
    d_res = PlanningEngine().build_plan(goal=dp["goal"], context={}, steps=dp["steps"])
    ok_d = d_res["status"] == "valid_structure" and d_res["step_order"] == dp["expected_order"]
    results.append(
        BenchmarkCaseResult(
            case_id="graph_diamond_dag_order",
            category="graph_multi_hop",
            description="PlanningEngine resolves diamond dependency DAG order",
            expected_polarity="positive",
            status="PASS" if ok_d else "FAIL",
            verification_status="VERIFIED" if ok_d else "UNVERIFIED",
            confusion_outcome="TP" if ok_d else "FN",
            failure_type=None if ok_d else "DAG_ORDER_FAILED",
            expected=str(dp["expected_order"]),
            actual=str(d_res["step_order"]),
        )
    )

    # 5. Ephemeral slot generalization on novel domain entity names (BM_P1_G0 vs synthetic TE_E*)
    bp, bt, binding = bind_ephemeral_slots(
        gm["novel_domain_slot_prompt"],
        gm["novel_domain_slot_target"],
        permute_slots=False,
    )
    bound_novel = len(binding.surface_to_slot) >= 3 and restore_ephemeral_slots(bt or "", binding) == gm["novel_domain_slot_target"]
    results.append(
        BenchmarkCaseResult(
            case_id="graph_slot_generalization_novel_entities",
            category="graph_multi_hop",
            description="sft.bind_ephemeral_slots generalizes to unseen domain entity prefixes (BM_P1_*)",
            expected_polarity="positive",
            status="PASS" if bound_novel else "FAIL",
            verification_status="UNVERIFIED" if not bound_novel else "VERIFIED",
            confusion_outcome="TP" if bound_novel else "FN",
            failure_type=None if bound_novel else "ENTITY_REGEX_OVERFIT_TO_SYNTHETIC_PREFIXES",
            sample_input=gm["novel_domain_slot_prompt"],
            expected=">=3 entities bound to <slot_k>",
            actual=f"bound_count={len(binding.surface_to_slot)}, bound_prompt={bp!r}",
            detail=(
                "_V11_ENTITY_RE in apps/core/native/sft.py only matches synthetic prefixes "
                "(TR_E|VA_E|TE_E|UN_E|OO_E, node_*, etc.) and ignores general domain entities."
            ),
        )
    )

    return results


def _run_memory_retrieval_cases(fx: dict[str, Any], env: dict[str, Any]) -> list[BenchmarkCaseResult]:
    results: list[BenchmarkCaseResult] = []
    mem = fx["memory_retrieval_cases"]

    # 1. Exact ID memory retrieval
    ks = KnowledgeSystem()
    for item in mem["stored_facts"]:
        ks.add_entity(item["id"], item["data"])
    rel_src, rel_dst = mem["relation"]
    ks.add_relation(rel_src, rel_dst)
    exact_hit = ks.query_related(rel_src) == [rel_dst]
    results.append(
        BenchmarkCaseResult(
            case_id="mem_exact_entity_retrieval",
            category="memory_retrieval",
            description="KnowledgeSystem retrieves direct relation by exact entity_id",
            expected_polarity="positive",
            status="PASS" if exact_hit else "FAIL",
            verification_status="VERIFIED" if exact_hit else "UNVERIFIED",
            confusion_outcome="TP" if exact_hit else "FN",
            failure_type=None if exact_hit else "EXACT_MEMORY_LOOKUP_FAILED",
            sample_input=rel_src,
            expected=str([rel_dst]),
            actual=str(ks.query_related(rel_src)),
        )
    )

    # 2. Semantic / alias attribute retrieval (exposes EXACT_KEY_LOOKUP_ONLY)
    alias_hits = ks.query_related(mem["semantic_alias_query"])
    alias_ok = mem["expected_entity_id"] in alias_hits
    results.append(
        BenchmarkCaseResult(
            case_id="mem_semantic_alias_retrieval",
            category="memory_retrieval",
            description="KnowledgeSystem retrieves stored entity from Thai alias/attribute content",
            expected_polarity="positive",
            status="PASS" if alias_ok else "FAIL",
            verification_status="UNVERIFIED" if not alias_ok else "VERIFIED",
            confusion_outcome="TP" if alias_ok else "FN",
            failure_type=None if alias_ok else "EXACT_KEY_LOOKUP_ONLY_NO_SEMANTIC_RETRIEVAL",
            sample_input=mem["semantic_alias_query"],
            expected=mem["expected_entity_id"],
            actual=str(alias_hits),
            detail="KnowledgeSystem stores entities dict but query_related() only indexes graph[entity_id].",
        )
    )

    # 3. Cross-instance persistence check
    ks_new = KnowledgeSystem()
    persisted = ks_new.query_related(rel_src) == [rel_dst]
    results.append(
        BenchmarkCaseResult(
            case_id="mem_cross_instance_persistence",
            category="memory_retrieval",
            description="KnowledgeSystem persists knowledge across separate runtime instances",
            expected_polarity="positive",
            status="PASS" if persisted else "FAIL",
            verification_status="UNVERIFIED" if not persisted else "VERIFIED",
            confusion_outcome="TP" if persisted else "FN",
            failure_type=None if persisted else "IN_MEMORY_ONLY_NO_PERSISTENCE",
            sample_input=rel_src,
            expected=str([rel_dst]),
            actual=str(ks_new.query_related(rel_src)),
            detail="KnowledgeSystem state exists only in process RAM without disk/DB persistence.",
        )
    )

    # 4. ContextManager multi-turn recall probe (requires pydantic in current codebase)
    if not env["pydantic_installed"]:
        results.append(
            BenchmarkCaseResult(
                case_id="mem_context_manager_multi_turn",
                category="memory_retrieval",
                description="ConversationHistory / ContextManager multi-turn prompt assembly",
                expected_polarity="positive",
                status="BLOCKED",
                verification_status="BLOCKED",
                confusion_outcome="N/A",
                failure_type="PYDANTIC_NOT_INSTALLED",
                sample_input=mem["expected_recall_token"],
                expected=f"ContextManager prompt retains {mem['expected_recall_token']}",
                actual="ModuleNotFoundError: No module named 'pydantic'",
                detail="apps/core/conversation.py imports pydantic at module top level, blocking stdlib execution.",
            )
        )
    else:
        from apps.core.conversation import ContextManager  # pragma: no cover

        cm = ContextManager(max_turns=10, max_chars=6000)
        for t in mem["multi_turn_turns"][:-1]:
            cm.add_user(t["content"]) if t["role"] == "user" else cm.add_assistant(t["content"])
        built = cm.build_prompt(mem["multi_turn_turns"][-1]["content"])
        has_tok = mem["expected_recall_token"] in built
        results.append(
            BenchmarkCaseResult(
                case_id="mem_context_manager_multi_turn",
                category="memory_retrieval",
                description="ConversationHistory / ContextManager multi-turn prompt assembly",
                expected_polarity="positive",
                status="PASS" if has_tok else "FAIL",
                verification_status="VERIFIED" if has_tok else "UNVERIFIED",
                confusion_outcome="TP" if has_tok else "FN",
                failure_type=None if has_tok else "MULTI_TURN_RECALL_MISSING",
                actual=built,
            )
        )

    # 5. AST check: is ContextManager / ConversationHistory wired into apps/api/routers/inference.py?
    router_src = INFERENCE_ROUTER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(router_src)
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported_names.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name)
    context_wired = "ContextManager" in imported_names or "ConversationHistory" in imported_names
    results.append(
        BenchmarkCaseResult(
            case_id="mem_inference_router_context_wiring",
            category="memory_retrieval",
            description="Inference API router integrates ContextManager/ConversationHistory into prompt context",
            expected_polarity="positive",
            status="PASS" if context_wired else "FAIL",
            verification_status="UNVERIFIED" if not context_wired else "VERIFIED",
            confusion_outcome="TP" if context_wired else "FN",
            failure_type=None if context_wired else "CONTEXT_MANAGER_NOT_WIRED_TO_INFERENCE_ROUTER",
            sample_input="apps/api/routers/inference.py",
            expected="ContextManager or ConversationHistory wired",
            actual="not imported in inference.py",
            detail="Inference router sends single-turn request.prompt without prior conversation memory.",
        )
    )

    return results


def _run_tokenizer_scoring_cases(fx: dict[str, Any]) -> tuple[list[BenchmarkCaseResult], dict[str, Any]]:
    results: list[BenchmarkCaseResult] = []
    tk = fx["tokenizer_scoring_cases"]

    tok = ZyrquenTokenizer.train(
        tk["corpus"],
        vocab_size=tk["vocab_size"],
        version="p1.1-bench",
        schema=SCHEMA_V2,
    )

    # 1. Bilingual Thai + English + Mixed NFC lossless roundtrip
    en_ids = tok.encode(tk["eval_english"])
    th_ids = tok.encode(tk["eval_thai"])
    mix_ids = tok.encode(tk["eval_mixed"])
    rt_en = tok.decode(en_ids, skip_special=True) == tk["eval_english"]
    rt_th = tok.decode(th_ids, skip_special=True) == tk["eval_thai"]
    rt_mix = tok.decode(mix_ids, skip_special=True) == tk["eval_mixed"]
    rt_all = rt_en and rt_th and rt_mix

    en_cpt = round(len(tk["eval_english"]) / max(1, len(en_ids)), 4)
    th_cpt = round(len(tk["eval_thai"]) / max(1, len(th_ids)), 4)
    mix_cpt = round(len(tk["eval_mixed"]) / max(1, len(mix_ids)), 4)

    results.append(
        BenchmarkCaseResult(
            case_id="tok_bilingual_lossless_roundtrip",
            category="tokenizer_scoring",
            description="ZyrquenTokenizer v2 lossless encode/decode across English, Thai, and mixed slots",
            expected_polarity="positive",
            status="PASS" if rt_all else "FAIL",
            verification_status="VERIFIED" if rt_all else "UNVERIFIED",
            confusion_outcome="TP" if rt_all else "FN",
            failure_type=None if rt_all else "ROUNDTRIP_LOSS",
            expected="100% exact decode match",
            actual=f"en={rt_en}, th={rt_th}, mixed={rt_mix}",
            detail=f"vocab={tok.vocab_size}, en_cpt={en_cpt}, th_cpt={th_cpt}, mix_cpt={mix_cpt}",
        )
    )

    # 2. Atomic slot preservation (<slot_0>..<slot_31>)
    slot_ids = tok.encode("<slot_0> <slot_15> <slot_31>")
    atomic_ok = (
        SLOT_COUNT == 32
        and tok.slot_id(0) in slot_ids
        and tok.slot_id(15) in slot_ids
        and tok.slot_id(31) in slot_ids
        and tok.decode(slot_ids, skip_special=True) == "<slot_0> <slot_15> <slot_31>"
    )
    results.append(
        BenchmarkCaseResult(
            case_id="tok_atomic_slot_preservation",
            category="tokenizer_scoring",
            description="ZyrquenTokenizer v2 preserves atomic <slot_k> IDs without BPE fragmentation",
            expected_polarity="positive",
            status="PASS" if atomic_ok else "FAIL",
            verification_status="VERIFIED" if atomic_ok else "UNVERIFIED",
            confusion_outcome="TP" if atomic_ok else "FN",
            failure_type=None if atomic_ok else "ATOMIC_SLOT_BROKEN",
            expected="32 atomic slots intact",
            actual=f"slot_ids={slot_ids}",
        )
    )

    # 3. Thai token efficiency / budget warning check (256 max_seq_len capacity pressure)
    thai_fits_budget = len(th_ids) <= 250
    results.append(
        BenchmarkCaseResult(
            case_id="tok_thai_compression_scoring",
            category="tokenizer_scoring",
            description="Measure Thai vs English BPE compression ratio (chars/token) and 256-token budget fit",
            expected_polarity="positive",
            status="PASS" if thai_fits_budget else "FAIL",
            verification_status="VERIFIED" if thai_fits_budget else "UNVERIFIED",
            confusion_outcome="TP" if thai_fits_budget else "FN",
            failure_type=None if thai_fits_budget else "THAI_TOKEN_BUDGET_EXCEEDED",
            expected="<= 250 tokens for eval Thai prompt",
            actual=f"th_tokens={len(th_ids)} (cpt={th_cpt}), en_tokens={len(en_ids)} (cpt={en_cpt})",
            detail="Thai byte-level BPE falls back toward byte-level tokens when corpus lacks Thai merges.",
        )
    )

    # 4. Persistence SHA-256 fingerprint & tamper rejection
    with tempfile.TemporaryDirectory() as td:
        tok_path = Path(td) / "tokenizer.json"
        tok.save(tok_path)
        loaded = ZyrquenTokenizer.load(tok_path)
        fp_ok = loaded.fingerprint() == tok.fingerprint()
        tampered = json.loads(tok_path.read_text(encoding="utf-8"))
        tampered["vocab_size"] = tampered["vocab_size"] + 1
        tok_path.write_text(json.dumps(tampered), encoding="utf-8")
        tamper_rejected = False
        try:
            ZyrquenTokenizer.load(tok_path)
        except ValueError:
            tamper_rejected = True
    ok_persist = fp_ok and tamper_rejected
    results.append(
        BenchmarkCaseResult(
            case_id="tok_sha256_integrity_and_tamper_reject",
            category="tokenizer_scoring",
            description="Tokenizer save/load verifies SHA-256 fingerprint and rejects tampered artifacts",
            expected_polarity="positive",
            status="PASS" if ok_persist else "FAIL",
            verification_status="VERIFIED" if ok_persist else "UNVERIFIED",
            confusion_outcome="TP" if ok_persist else "FN",
            failure_type=None if ok_persist else "TOKENIZER_TAMPER_ACCEPTED",
            expected="fingerprint match & tamper ValueError",
            actual=f"fp_ok={fp_ok}, tamper_rejected={tamper_rejected}",
        )
    )

    # 5. SFT boundary & -100 label masking alignment
    prefix = encode_sft_prompt(tok, tk["sft_prompt"])
    x, y = encode_sft_pair(tok, tk["sft_prompt"], tk["sft_target"], max_seq_len=256)
    sft_ok = (
        len(x) == len(y)
        and prefix[0] == tok.bos_id
        and all(lbl == IGNORE_INDEX for lbl in y[: len(prefix) - 1])
        and y[-1] == tok.eos_id
    )
    results.append(
        BenchmarkCaseResult(
            case_id="tok_sft_boundary_masking",
            category="tokenizer_scoring",
            description="SFT prompt/target boundary aligns -100 prefix mask and EOS prediction target",
            expected_polarity="positive",
            status="PASS" if sft_ok else "FAIL",
            verification_status="VERIFIED" if sft_ok else "UNVERIFIED",
            confusion_outcome="TP" if sft_ok else "FN",
            failure_type=None if sft_ok else "SFT_ALIGNMENT_ERROR",
            expected="prefix masked -100, final label == eos_id",
            actual=f"len_x={len(x)}, prefix_len={len(prefix)}, last_y={y[-1]}",
        )
    )

    metrics = {
        "vocab_size": tok.vocab_size,
        "en_tokens": len(en_ids),
        "en_chars_per_token": en_cpt,
        "th_tokens": len(th_ids),
        "th_chars_per_token": th_cpt,
        "mixed_tokens": len(mix_ids),
        "mixed_chars_per_token": mix_cpt,
        "roundtrip_accuracy": 1.0 if rt_all else 0.0,
    }
    return results, metrics


def _build_synthetic_v10_dir(root: Path, *, inject_leakage: bool) -> Path:
    """Create a temporary v10-schema dataset exclusively to test audit_leakage_v10."""
    root.mkdir(parents=True, exist_ok=True)
    eval_e1 = "TR_E70001" if inject_leakage else "VA_E70001"
    test_e1 = "TR_E70001" if inject_leakage else "TE_E70001"

    def _row(ex_id: str, split: str, tpl: str, e1: str, e2: str, instr: str) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "example_id": ex_id,
            "split": split,
            "capability": "relational_generalization",
            "task_type": "relational_chain",
            "reasoning_operator": "exact_hop_path",
            "template_id": tpl,
            "instruction": instr,
            "input": f"{instr}\nFacts: {e1} linked_to {e2} | Query: {e1} hops=1 ?",
            "target": e2,
            "facts": [{"source": e1, "relation": "linked_to", "target": e2}],
            "query": {"relation": "linked_to", "source": e1, "hops": 1},
            "answer": e2,
            "unique_answer_verified": True,
            "metadata": {"hops": 1},
        }

    splits_data = {
        "train": [_row("tr_1", "train", "tpl_train_1", "TR_E70001", "TR_E70002", "Follow link for train split.")],
        "validation": [_row("va_1", "validation", "tpl_val_1", eval_e1, "VA_E70002", "Trace path for validation split.")],
        "test": [_row("te_1", "test", "tpl_test_1", test_e1, "TE_E70002", "Resolve chain for test split.")],
    }
    splits_meta: dict[str, Any] = {}
    files_meta: dict[str, Any] = {}
    hashes: list[str] = []
    for sp in ("train", "validation", "test"):
        fp = root / f"{sp}.jsonl"
        fp.write_text("\n".join(json.dumps(r) for r in splits_data[sp]) + "\n", encoding="utf-8")
        sha = _sha256_bytes(fp.read_bytes())
        hashes.append(sha)
        splits_meta[sp] = {"path": f"{sp}.jsonl", "sha256": sha, "count": len(splits_data[sp])}
        files_meta[f"{sp}.jsonl"] = {"path": f"{sp}.jsonl", "sha256": sha, "documents": len(splits_data[sp])}

    manifest = {
        "schema": DATASET_SCHEMA,
        "dataset": "nagi_v10",
        "version": "10.0.0",
        "content_sha256": _sha256_text("".join(hashes)),
        "splits": splits_meta,
        "files": files_meta,
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def _run_leakage_detection_cases(fx: dict[str, Any]) -> tuple[list[BenchmarkCaseResult], dict[str, Any]]:
    results: list[BenchmarkCaseResult] = []
    lk = fx["leakage_detection_cases"]

    # 1. Fixture isolation vs forbidden training prefixes and legacy golden_dataset.json
    fx_text = json.dumps(fx, ensure_ascii=False)
    golden_texts: list[str] = []
    if LEGACY_GOLDEN_PATH.is_file():
        for item in json.loads(LEGACY_GOLDEN_PATH.read_text(encoding="utf-8")):
            if isinstance(item, dict):
                golden_texts.append(str(item.get("prompt", "")))
                golden_texts.append(str(item.get("expected_response", "")))
    golden_overlap = [t for t in golden_texts if t and t in fx_text]

    # Check positive/negative/math/graph/memory/tokenizer sections do not contain training entity prefixes
    non_leak_sections = {
        k: v
        for k, v in fx.items()
        if k not in ("leakage_detection_cases", "forbidden_training_prefixes", "isolation_policy")
    }
    non_leak_blob = json.dumps(non_leak_sections, ensure_ascii=False)
    prefix_hits = [p for p in fx["forbidden_training_prefixes"] if p in non_leak_blob]
    iso_ok = not golden_overlap and not prefix_hits
    results.append(
        BenchmarkCaseResult(
            case_id="leak_fixture_isolation",
            category="leakage_detection",
            description="Held-out P1-1 fixtures have zero overlap with training prefixes or golden_dataset.json",
            expected_polarity="positive",
            status="PASS" if iso_ok else "FAIL",
            verification_status="VERIFIED" if iso_ok else "UNVERIFIED",
            confusion_outcome="TP" if iso_ok else "FN",
            failure_type=None if iso_ok else "FIXTURE_CONTAMINATION",
            expected="0 overlaps",
            actual=f"golden_overlap={golden_overlap}, prefix_hits={prefix_hits}",
        )
    )

    # 2. Tokenizer EL-05 slot-safe training vs raw unmasked leakage detection
    probe_ent = lk["probe_eval_entity"]
    tok_safe = train_slot_safe_tokenizer(
        lk["clean_train_records"],
        vocab_size=320,
        use_slots=True,
        forbidden_entities=[probe_ent],
    )
    safe_leaks = tok_safe.find_entity_leakage([probe_ent])

    # Deliberately contaminate a raw corpus with repeated eval entity so BPE merges learn it
    contaminated_corpus = [f"query {probe_ent} resolves to {probe_ent}" for _ in range(12)]
    tok_raw = ZyrquenTokenizer.train(contaminated_corpus, vocab_size=360, schema=SCHEMA_V2)
    raw_leaks = tok_raw.find_entity_leakage([probe_ent])
    bpe_leak_detected = len(safe_leaks) == 0 and probe_ent in raw_leaks
    results.append(
        BenchmarkCaseResult(
            case_id="leak_tokenizer_el05_detection",
            category="leakage_detection",
            description="ZyrquenTokenizer.find_entity_leakage passes on slot-safe corpus and catches BPE leakage",
            expected_polarity="positive",
            status="PASS" if bpe_leak_detected else "FAIL",
            verification_status="VERIFIED" if bpe_leak_detected else "UNVERIFIED",
            confusion_outcome="TP" if bpe_leak_detected else "FN",
            failure_type=None if bpe_leak_detected else "EL05_LEAK_DETECTION_FAILED",
            expected=f"safe_leaks=[], raw_leaks=[{probe_ent}]",
            actual=f"safe_leaks={safe_leaks}, raw_leaks={raw_leaks}",
        )
    )

    # 3. audit_leakage_v10 detects injected entity leakage (EL-01) and passes isolated set
    with tempfile.TemporaryDirectory() as td:
        clean_dir = _build_synthetic_v10_dir(Path(td) / "clean", inject_leakage=False)
        leaky_dir = _build_synthetic_v10_dir(Path(td) / "leaky", inject_leakage=True)
        clean_audit = v10_audit.run_audit(clean_dir)
        leaky_audit = v10_audit.run_audit(leaky_dir)

    clean_ok = clean_audit.get("overall_status") == "PASS"
    leaky_caught = (
        leaky_audit.get("overall_status") == "FAIL"
        and leaky_audit.get("gates", {}).get("EL-01", {}).get("passed") is False
    )
    audit_ok = clean_ok and leaky_caught
    results.append(
        BenchmarkCaseResult(
            case_id="leak_v10_entity_disjointness_gate",
            category="leakage_detection",
            description="audit_leakage_v10 passes clean isolated splits and fails when TR_E leaks into eval",
            expected_polarity="positive",
            status="PASS" if audit_ok else "FAIL",
            verification_status="VERIFIED" if audit_ok else "UNVERIFIED",
            confusion_outcome="TP" if audit_ok else "FN",
            failure_type=None if audit_ok else "V10_LEAK_GATE_FAILED",
            expected="clean=PASS, leaky=FAIL (EL-01)",
            actual=f"clean={clean_audit.get('overall_status')}, leaky={leaky_audit.get('overall_status')}",
        )
    )

    # 4. Zero-Mock audit: verify legacy mock in apps/core/evaluation/engine.py & golden_dataset.json are removed
    import apps.core.evaluation as core_eval_pkg

    legacy_engine_file_exists = (REPO_ROOT / "apps" / "core" / "evaluation" / "engine.py").exists()
    legacy_golden_file_exists = LEGACY_GOLDEN_PATH.exists()
    legacy_spec_exists = importlib.util.find_spec("apps.core.evaluation.engine") is not None
    legacy_symbol_exposed = hasattr(core_eval_pkg, "EvaluationEngine")
    legacy_mock_detected = (
        legacy_engine_file_exists
        or legacy_golden_file_exists
        or legacy_spec_exists
        or legacy_symbol_exposed
    )

    # Verify Native EvaluationEngine refuses None/mock calls without artifacts
    native_refuses_unconfigured = False
    try:
        EvaluationEngine().evaluate("ZYRQUEN-Native-10.0.0", {"val_loss": 1.0})
    except EvaluationNotConfiguredError:
        native_refuses_unconfigured = True

    zero_mock_ok = (not legacy_mock_detected) and native_refuses_unconfigured
    results.append(
        BenchmarkCaseResult(
            case_id="leak_legacy_mock_isolation_audit",
            category="leakage_detection",
            description="Zero-Mock audit: legacy mock engine/golden dataset removed and Native EvaluationEngine fails closed",
            expected_polarity="negative",
            status="PASS" if zero_mock_ok else "FAIL",
            verification_status="VERIFIED" if zero_mock_ok else "UNVERIFIED",
            confusion_outcome="TN" if zero_mock_ok else "FP",
            failure_type="LEGACY_MOCK_PRESENT" if legacy_mock_detected else (None if zero_mock_ok else "NATIVE_EVAL_NOT_FAIL_CLOSED"),
            sample_input="apps/core/evaluation/",
            expected="0 legacy mock engines/datasets and fail-closed native EvaluationEngine",
            actual=(
                f"engine_file={legacy_engine_file_exists}, golden_file={legacy_golden_file_exists}, "
                f"symbol_exposed={legacy_symbol_exposed}, native_fail_closed={native_refuses_unconfigured}"
            ),
            detail=(
                "Zero-Mock verified: legacy hardcoded metrics (15.5 / 0.85) removed from apps/core/evaluation/ "
                "and native EvaluationEngine requires verified checkpoint + dataset artifacts."
                if zero_mock_ok
                else "Legacy mock artifact detected in apps/core/evaluation/."
            ),
        )
    )

    leakage_summary = {
        "fixture_isolated": iso_ok,
        "golden_dataset_overlap": golden_overlap,
        "forbidden_prefix_hits": prefix_hits,
        "slot_safe_entity_leaks": safe_leaks,
        "raw_corpus_bpe_leaks_detected": raw_leaks,
        "v10_clean_audit_status": clean_audit.get("overall_status"),
        "v10_injected_leak_caught": leaky_caught,
        "legacy_mock_detected": legacy_mock_detected,
        "legacy_mock_removed": not legacy_mock_detected,
        "legacy_mock_isolated_from_scores": True,
        "mock_in_real_evaluation": 1 if legacy_mock_detected else 0,
    }
    return results, leakage_summary


def _run_native_model_inference_cases(env: dict[str, Any]) -> list[BenchmarkCaseResult]:
    results: list[BenchmarkCaseResult] = []
    eng = EvaluationEngine()
    status = eng.get_status()
    rt_contracts = IntelligenceRuntime().validate_contracts()

    # 1. Native model inference execution check (blocked when torch/checkpoint absent)
    results.append(
        BenchmarkCaseResult(
            case_id="native_model_sft_inference_probe",
            category="native_model_inference",
            description="Native ZyrquenModel greedy SFT inference benchmark readiness",
            expected_polarity="positive",
            status="BLOCKED" if not env["torch_installed"] or status["status"] == "not_configured" else "PASS",
            verification_status="BLOCKED",
            confusion_outcome="N/A",
            failure_type="TORCH_NOT_INSTALLED" if not env["torch_installed"] else "MODEL_NOT_CONFIGURED",
            expected="Loaded ZyrquenModel checkpoint + PyTorch CPU runtime",
            actual=f"torch_installed={env['torch_installed']}, eval_status={status['status']}",
            detail="Cannot evaluate real neural reasoning weights without torch and a trained checkpoint.",
        )
    )

    # 2. IntelligenceRuntime safe contract validation (confirms model_inference=False)
    contracts_ok = (
        rt_contracts["status"] == "contracts_validated"
        and rt_contracts["model_inference"] is False
        and rt_contracts["external_tools_called"] is False
        and rt_contracts["model_weights_changed"] is False
    )
    results.append(
        BenchmarkCaseResult(
            case_id="native_intelligence_contract_probe",
            category="native_model_inference",
            description="IntelligenceRuntime contract probe confirms zero fabricated inference/tool claims",
            expected_polarity="positive",
            status="PASS" if contracts_ok else "FAIL",
            verification_status="VERIFIED" if contracts_ok else "UNVERIFIED",
            confusion_outcome="TP" if contracts_ok else "FN",
            failure_type=None if contracts_ok else "CONTRACT_PROBE_FAILED",
            expected="contracts_validated, model_inference=False",
            actual=f"status={rt_contracts['status']}, model_inference={rt_contracts['model_inference']}",
        )
    )

    return results


def run_p1_1_benchmark(fixtures_path: Path | None = None) -> dict[str, Any]:
    fx = load_benchmark_fixtures(fixtures_path)
    env = _probe_environment()
    model_state = _probe_model_state()

    all_cases: list[BenchmarkCaseResult] = []
    all_cases.extend(_run_positive_cases(fx))
    all_cases.extend(_run_negative_abstention_cases(fx))
    all_cases.extend(_run_math_logic_cases(fx))
    all_cases.extend(_run_graph_multi_hop_cases(fx))
    all_cases.extend(_run_memory_retrieval_cases(fx, env))
    tok_cases, tok_metrics = _run_tokenizer_scoring_cases(fx)
    all_cases.extend(tok_cases)
    leak_cases, leakage_summary = _run_leakage_detection_cases(fx)
    all_cases.extend(leak_cases)
    all_cases.extend(_run_native_model_inference_cases(env))

    categories_order = (
        "positive",
        "negative_abstention",
        "math_logic",
        "graph_multi_hop",
        "memory_retrieval",
        "tokenizer_scoring",
        "leakage_detection",
        "native_model_inference",
    )
    category_scores: dict[str, dict[str, Any]] = {}
    for cat in categories_order:
        items = [c for c in all_cases if c.category == cat]
        passed = sum(1 for c in items if c.status == "PASS")
        failed = sum(1 for c in items if c.status == "FAIL")
        blocked = sum(1 for c in items if c.status == "BLOCKED")
        unavailable = sum(1 for c in items if c.status == "UNAVAILABLE")
        evaluable = passed + failed
        fp = sum(1 for c in items if c.confusion_outcome == "FP")
        fn = sum(1 for c in items if c.confusion_outcome == "FN")
        category_scores[cat] = {
            "total": len(items),
            "passed": passed,
            "failed": failed,
            "blocked": blocked,
            "unavailable": unavailable,
            "score_pct": round((passed / len(items)) * 100.0, 2) if items else 0.0,
            "evaluable_score_pct": round((passed / evaluable) * 100.0, 2) if evaluable else None,
            "false_positives": fp,
            "false_negatives": fn,
            "status": (
                "BLOCKED"
                if evaluable == 0 and blocked > 0
                else ("PASS" if failed == 0 and blocked == 0 else "PARTIAL_OR_GAP")
            ),
        }

    total = len(all_cases)
    passed_total = sum(1 for c in all_cases if c.status == "PASS")
    failed_total = sum(1 for c in all_cases if c.status == "FAIL")
    blocked_total = sum(1 for c in all_cases if c.status == "BLOCKED")
    unavailable_total = sum(1 for c in all_cases if c.status == "UNAVAILABLE")
    evaluable_total = passed_total + failed_total

    tp_total = sum(1 for c in all_cases if c.confusion_outcome == "TP")
    tn_total = sum(1 for c in all_cases if c.confusion_outcome == "TN")
    fp_total = sum(1 for c in all_cases if c.confusion_outcome == "FP")
    fn_total = sum(1 for c in all_cases if c.confusion_outcome == "FN")

    failures_and_gaps = [
        asdict(c) for c in all_cases if c.status in {"FAIL", "BLOCKED", "UNAVAILABLE"}
    ]

    limitations: list[str] = []
    if not env["torch_installed"]:
        limitations.append("PyTorch (torch) is not installed; ZyrquenModel forward pass / SFT evaluation is BLOCKED.")
    if not env["pydantic_installed"]:
        limitations.append("Pydantic is not installed; ContextManager / StreamingInferenceEngine imports are BLOCKED.")
    if not model_state["inference_available"]:
        limitations.append("No trained native checkpoint configured; all neural reasoning scores remain unmeasured.")
    if not env["git_repo_present"]:
        limitations.append("Workspace has no .git metadata; branch/HEAD tracking relies on file hashes.")

    deterministic_body = {
        "schema": BENCHMARK_SCHEMA,
        "fixture_schema": fx["schema"],
        "fixture_split": fx["fixture_split"],
        "environment": env,
        "model_state": model_state,
        "summary": {
            "total_cases": total,
            "passed": passed_total,
            "failed": failed_total,
            "blocked": blocked_total,
            "unavailable": unavailable_total,
            "pass_rate_pct": round((passed_total / total) * 100.0, 2) if total else 0.0,
            "evaluable_pass_rate_pct": round((passed_total / evaluable_total) * 100.0, 2) if evaluable_total else 0.0,
            "confusion_matrix": {
                "TP": tp_total,
                "TN": tn_total,
                "FP": fp_total,
                "FN": fn_total,
            },
        },
        "category_scores": category_scores,
        "tokenizer_metrics": tok_metrics,
        "leakage_detection": leakage_summary,
        "cases": [asdict(c) for c in all_cases],
        "failures_and_gaps": failures_and_gaps,
        "limitations": limitations,
    }
    canonical_json = json.dumps(deterministic_body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    baseline_digest = _sha256_text(canonical_json)

    return {
        **deterministic_body,
        "baseline_digest_sha256": baseline_digest,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def format_p1_1_markdown_report(report: dict[str, Any]) -> str:
    s = report["summary"]
    cm = s["confusion_matrix"]
    env = report["environment"]
    ms = report["model_state"]
    lines = [
        "# ZYRQUEN Ω∞ — P1-1 Baseline Benchmark Report",
        f"- Schema: `{report['schema']}`",
        f"- Baseline Digest (SHA-256): `{report['baseline_digest_sha256']}`",
        f"- Python: `{env['python_version']}` | torch: `{env['torch_installed']}` | pydantic: `{env['pydantic_installed']}` | pytest: `{env['pytest_installed']}`",
        f"- Model Version: `{ms['model_version']}` | Health: `{ms['model_loader_health']}` | Eval Status: `{ms['evaluation_engine_status']['status']}`",
        "",
        "## Overall Summary",
        f"- Total Cases: **{s['total_cases']}** | Passed: **{s['passed']}** | Failed: **{s['failed']}** | Blocked: **{s['blocked']}**",
        f"- Overall Pass Rate: **{s['pass_rate_pct']}%** (Evaluable-only: **{s['evaluable_pass_rate_pct']}%**)",
        f"- Confusion Matrix: `TP={cm['TP']}`, `TN={cm['TN']}`, `FP={cm['FP']}`, `FN={cm['FN']}`",
        "",
        "## Category Breakdown",
        "| Category | Total | Pass | Fail | Blocked | Score (%) | Evaluable (%) | FP | FN |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cat, info in report["category_scores"].items():
        ev = f"{info['evaluable_score_pct']}" if info["evaluable_score_pct"] is not None else "BLOCKED"
        lines.append(
            f"| `{cat}` | {info['total']} | {info['passed']} | {info['failed']} | {info['blocked']} | {info['score_pct']} | {ev} | {info['false_positives']} | {info['false_negatives']} |"
        )
    lines.extend(["", "## Failures & Blocked Gaps"])
    for item in report["failures_and_gaps"]:
        lines.append(
            f"- `[{item['status']} / {item['verification_status']}]` **{item['case_id']}** (`{item['failure_type']}`): "
            f"expected=`{item['expected']}` actual=`{item['actual']}`"
        )
    return "\n".join(lines)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run ZYRQUEN P1-1 Baseline Benchmark Suite.")
    parser.add_argument("--json", action="store_true", help="Output JSON report to stdout.")
    parser.add_argument("--output", type=str, default="", help="Optional path to write JSON report.")
    args = parser.parse_args()

    report = run_p1_1_benchmark()
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_p1_1_markdown_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
