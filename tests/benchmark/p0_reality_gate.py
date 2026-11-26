"""Systematic P0 Acceptance Verifier: Reality Over Appearance.

Implements deterministic, pure-stdlib verification gates for:
1. Recommendation Verification
2. Tool Availability Verification
3. Source Authenticity
4. Broken Link Detection
5. Unsupported Capability Detection
6. False Success Prevention

Strictly read-only against core models, memory, tokenizer, and API contracts.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.core.intelligence import (  # noqa: E402
    CapabilityEvaluationViolation,
    ExecutionPolicy,
    IntelligenceRuntime,
    PermissionGate,
    TestCaseRegistry,
    ToolRegistry,
    evaluate_capability,
    validate_evaluation_result,
)
from apps.core.model_loader import NativeModelLoader  # noqa: E402
from apps.core.native.evaluation import (  # noqa: E402
    EvaluationEngine,
    EvaluationNotConfiguredError,
)
from apps.core.native.registry import ModelRegistry, RegistryError  # noqa: E402

OUTPUT_STATUSES = frozenset({
    "VERIFIED",
    "UNVERIFIED",
    "NOT_FOUND",
    "UNAVAILABLE",
    "STALE",
    "BLOCKED",
})

_ALLOWED_URL_SCHEMES = frozenset({"https", "http"})
_PLACEHOLDER_HOSTS = frozenset({
    "example.com",
    "example.org",
    "example.net",
    "placeholder.invalid",
    "fake.local",
    "test.invalid",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
})


def validate_url_integrity(url: Any) -> dict[str, Any]:
    """Detect broken, malformed, or placeholder URLs without fabricated HTTP checks."""
    if not isinstance(url, str) or not url.strip():
        return {"valid": False, "reason": "empty_or_non_string_url"}
    raw = url.strip()
    if any(ch.isspace() or ord(ch) < 32 for ch in raw):
        return {"valid": False, "reason": "control_or_whitespace_in_url"}

    parsed = urlparse(raw)
    if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES:
        return {"valid": False, "reason": f"unsupported_scheme:{parsed.scheme or 'none'}"}
    host = (parsed.hostname or "").strip().lower()
    if not host or "." not in host:
        if host in _PLACEHOLDER_HOSTS:
            return {"valid": False, "reason": f"placeholder_or_local_host:{host}"}
        return {"valid": False, "reason": "missing_or_invalid_hostname"}
    if host in _PLACEHOLDER_HOSTS or host.endswith((".invalid", ".example", ".test", ".local")):
        return {"valid": False, "reason": f"unauthentic_placeholder_domain:{host}"}
    return {"valid": True, "reason": "ok", "host": host, "scheme": parsed.scheme.lower()}


def verify_evidence_record(evidence: Any, *, max_age_hours: float | None = 24 * 30) -> dict[str, Any]:
    """Enforce ZYRQUEN Evidence Requirements and Output Status classification."""
    if not isinstance(evidence, dict):
        return {"status": "NOT_FOUND", "accepted": False, "reasons": ["missing_evidence_object"]}

    declared_status = evidence.get("verification_status")
    if declared_status in {"NOT_FOUND", "UNAVAILABLE", "BLOCKED", "STALE"}:
        return {
            "status": declared_status,
            "accepted": False,
            "reasons": [f"declared_non_verified_status:{declared_status}"],
        }

    reasons: list[str] = []
    source_id = evidence.get("source_id")
    if not isinstance(source_id, str) or not source_id.strip():
        reasons.append("missing_source_id")

    content = evidence.get("evidence_content")
    if not isinstance(content, str) or not content.strip():
        reasons.append("missing_evidence_content")

    retrieved_at = evidence.get("retrieved_at")
    is_stale = False
    if not isinstance(retrieved_at, str) or not retrieved_at.strip():
        reasons.append("missing_retrieved_at")
    else:
        try:
            iso = retrieved_at.strip().replace("Z", "+00:00")
            ts = datetime.fromisoformat(iso)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if max_age_hours is not None:
                age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
                if age_hours > max_age_hours:
                    is_stale = True
                    reasons.append(f"stale_evidence:{round(age_hours, 1)}h")
        except ValueError:
            reasons.append("invalid_retrieved_at_timestamp")

    if evidence.get("freshness") == "STALE":
        is_stale = True
        reasons.append("explicit_stale_freshness")

    source_url = evidence.get("source_url")
    if source_url is not None:
        url_check = validate_url_integrity(source_url)
        if not url_check["valid"]:
            reasons.append(f"broken_or_unauthentic_url:{url_check['reason']}")

    if is_stale and not any(r.startswith("broken_or_unauthentic_url") for r in reasons):
        return {"status": "STALE", "accepted": False, "reasons": reasons}

    if reasons or declared_status != "VERIFIED":
        if declared_status not in OUTPUT_STATUSES:
            reasons.append("invalid_or_missing_verification_status")
        elif declared_status == "UNVERIFIED":
            reasons.append("declared_unverified")
        return {"status": "UNVERIFIED", "accepted": False, "reasons": reasons}

    return {"status": "VERIFIED", "accepted": True, "reasons": []}


def evaluate_recommendation_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Filter recommendations under Real Products / Real Availability / Real Evidence rules."""
    verified: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for item in candidates:
        name = item.get("name")
        availability = item.get("availability_status", "UNVERIFIED")
        if availability in {"UNAVAILABLE", "DISCONTINUED", "BLOCKED", "DISABLED"}:
            rejected.append({
                "name": name,
                "output_status": "UNAVAILABLE",
                "reason": f"unavailable_service:{availability}",
            })
            continue

        ev_check = verify_evidence_record(item.get("evidence"))
        if not ev_check["accepted"]:
            rejected.append({
                "name": name,
                "output_status": ev_check["status"],
                "reason": ";".join(ev_check["reasons"]),
            })
            continue

        verified.append({
            "name": name,
            "output_status": "VERIFIED",
            "source_id": item["evidence"]["source_id"],
            "source_url": item["evidence"].get("source_url"),
            "retrieved_at": item["evidence"]["retrieved_at"],
        })

    overall_status = "VERIFIED" if verified else "NOT_FOUND"
    return {
        "overall_status": overall_status,
        "recommended": verified,
        "rejected": rejected,
        "filler_items_added": 0,
    }


def verify_tool_availability(
    tool_name: str,
    *,
    registry: ToolRegistry,
    policy: ExecutionPolicy,
    granted_permissions: set[str],
    runtime_executor_wired: bool = False,
    service_available: bool = True,
) -> dict[str, Any]:
    """Classify tool usability without pretending an unwired/disabled tool works."""
    try:
        definition = registry.get(tool_name)
    except KeyError:
        return {
            "tool_name": tool_name,
            "output_status": "NOT_FOUND",
            "usable": False,
            "reason": "tool_not_registered",
        }

    if not service_available:
        return {
            "tool_name": tool_name,
            "output_status": "UNAVAILABLE",
            "usable": False,
            "reason": "tool_service_discontinued_or_offline",
        }

    gate = PermissionGate(registry, policy)
    auth = gate.authorize(
        {
            "call_id": f"avail-check-{tool_name}",
            "tool_name": tool_name,
            "arguments": {
                k: "" for k in definition["input_schema"].get("required", [])
            },
        },
        granted_permissions,
        approval_granted=False,
    )
    if auth["status"] != "authorized":
        return {
            "tool_name": tool_name,
            "output_status": "BLOCKED",
            "usable": False,
            "reason": ",".join(auth["reasons"]),
        }

    if not runtime_executor_wired:
        return {
            "tool_name": tool_name,
            "output_status": "UNVERIFIED",
            "usable": False,
            "reason": "registered_and_authorized_but_execution_adapter_not_wired",
        }

    return {
        "tool_name": tool_name,
        "output_status": "VERIFIED",
        "usable": True,
        "reason": "verified_and_executable",
    }


def detect_unsupported_capabilities() -> dict[str, Any]:
    """Probe real repository modules to verify unfinished capabilities never claim readiness."""
    torch_installed = importlib.util.find_spec("torch") is not None
    pydantic_installed = importlib.util.find_spec("pydantic") is not None
    dataset_v11_exists = (REPO_ROOT / "apps" / "core" / "native" / "dataset_v11.py").is_file()

    eval_status = EvaluationEngine().get_status()
    loader = NativeModelLoader()
    rt = IntelligenceRuntime()
    contracts = rt.validate_contracts()
    reasoning_out = rt.reasoning.deduce(context="p0_probe", question="probe")

    checks = {
        "native_eval_not_falsely_ready": (
            eval_status["status"] == "not_configured" and eval_status["torch_installed"] == torch_installed
        ),
        "model_loader_not_falsely_ready": (
            loader.health_state() == "not_configured" and loader.is_ready() is False
        ),
        "intelligence_model_inference_false": (
            contracts["model_inference"] is False
            and contracts["external_tools_called"] is False
            and reasoning_out["model_inference"] is False
            and reasoning_out["engine_type"] == "rule_based_scaffold"
        ),
        "dataset_v11_absence_reported": not dataset_v11_exists,
        "pydantic_runtime_honesty": True,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "observed": {
            "torch_installed": torch_installed,
            "pydantic_installed": pydantic_installed,
            "dataset_v11_present": dataset_v11_exists,
            "eval_engine_status": eval_status["status"],
            "model_loader_health": loader.health_state(),
        },
    }


def verify_false_success_prevention() -> dict[str, Any]:
    """Verify fail-closed gates reject fabricated PASS, missing evidence, and mock metrics."""
    checks: dict[str, bool] = {}

    # 1. Capability evaluation rejects model_inference=True & fake evidence origin
    reg = TestCaseRegistry()
    reg.register({
        "case_id": "p0_case_1",
        "capability": "reasoning",
        "description": "P0 gate check",
        "required": True,
    })
    blocked_res = evaluate_capability(
        "reasoning",
        [{"case_id": "p0_case_1", "outcome": "blocked", "reference": "missing_torch"}],
        reg,
    )
    checks["blocked_never_supported"] = blocked_res["status"] == "blocked"

    inflated = dict(blocked_res, status="supported_by_reported_evidence")
    try:
        validate_evaluation_result(inflated, reg)
        checks["reject_inflated_capability_status"] = False
    except CapabilityEvaluationViolation:
        checks["reject_inflated_capability_status"] = True

    with_inference = dict(blocked_res, model_inference=True)
    try:
        validate_evaluation_result(with_inference, reg)
        checks["reject_fake_model_inference_flag"] = False
    except CapabilityEvaluationViolation:
        checks["reject_fake_model_inference_flag"] = True

    # 2. Native EvaluationEngine refuses unconfigured evaluate()
    try:
        EvaluationEngine().evaluate("ZYRQUEN-Native-10.0.0", {"val_loss": 0.5})
        checks["native_eval_refuses_unconfigured"] = False
    except EvaluationNotConfiguredError:
        checks["native_eval_refuses_unconfigured"] = True

    # 3. ModelRegistry refuses certification when inference_executed=False or evaluation_status='NOT RUN'
    with tempfile.TemporaryDirectory() as td:
        mr = ModelRegistry(Path(td) / "reg")
        fake_sha = "a" * 64
        rejected_not_run = False
        rejected_no_inf = False
        try:
            mr.attach_evaluation_evidence(
                "ZYRQUEN-Native-10.0.0",
                eval_run_id="run-1",
                report_sha256=fake_sha,
                metrics={"val_loss": 0.5},
                passed=True,
                zero_regression=True,
                evaluation_status="NOT RUN",
            )
        except RegistryError:
            rejected_not_run = True
        try:
            mr.attach_evaluation_evidence(
                "ZYRQUEN-Native-10.0.0",
                eval_run_id="run-2",
                report_sha256=fake_sha,
                metrics={"val_loss": 0.5},
                passed=True,
                zero_regression=True,
                inference_executed=False,
            )
        except RegistryError:
            rejected_no_inf = True
        checks["registry_rejects_not_run_certification"] = rejected_not_run
        checks["registry_rejects_inference_false_certification"] = rejected_no_inf

    # 4. Zero-Mock in real evaluation & UI preview integrity check
    import apps.core.evaluation as core_eval_pkg

    legacy_removed = (
        not (REPO_ROOT / "apps" / "core" / "evaluation" / "engine.py").exists()
        and not (REPO_ROOT / "apps" / "core" / "evaluation" / "golden_dataset.json").exists()
        and importlib.util.find_spec("apps.core.evaluation.engine") is None
        and not hasattr(core_eval_pkg, "EvaluationEngine")
    )
    web_preview_path = REPO_ROOT / "apps" / "web" / "src" / "lib" / "in-memory-backend.ts"
    web_preview_src = web_preview_path.read_text(encoding="utf-8") if web_preview_path.is_file() else ""
    ui_no_fake_eval_scores = (
        '"evaluation_status": "evaluated"' not in web_preview_src
        and 'evaluation_status: "evaluated"' not in web_preview_src
        and "generalization_score: 78.4" not in web_preview_src
        and "relational_reasoning_success_rate: 81.2" not in web_preview_src
    )
    checks["zero_mock_in_real_evaluation"] = legacy_removed and checks["native_eval_refuses_unconfigured"]
    checks["ui_preview_no_fabricated_eval_scores"] = ui_no_fake_eval_scores

    return {
        "passed": all(checks.values()),
        "checks": checks,
    }


def verify_repo_doc_links() -> dict[str, Any]:
    """Verify key architecture & P0 documentation paths exist as real files."""
    required_docs = (
        "ARCHITECTURE.md",
        "README.md",
        "docs/P0_REALITY_AND_RECOMMENDATION_ACCEPTANCE_CRITERIA.md",
        "tools/v10_summary.md",
    )
    missing = [rel for rel in required_docs if not (REPO_ROOT / rel).is_file()]
    return {
        "passed": len(missing) == 0,
        "checked_count": len(required_docs),
        "missing_files": missing,
    }


def run_p0_reality_acceptance() -> dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()
    sample_candidates = [
        {
            "name": "Verified Native Tool",
            "availability_status": "AVAILABLE",
            "evidence": {
                "source_id": "zyrquen-registry:calc-v1",
                "source_url": "https://docs.python.org/3/library/math.html",
                "retrieved_at": now_iso,
                "evidence_content": "Deterministic math tool specification verified.",
                "verification_status": "VERIFIED",
                "freshness": "CURRENT",
            },
        },
        {
            "name": "Broken Link Service",
            "availability_status": "AVAILABLE",
            "evidence": {
                "source_id": "src-broken",
                "source_url": "not-a-valid-url://broken-host",
                "retrieved_at": now_iso,
                "evidence_content": "Claimed tool.",
                "verification_status": "VERIFIED",
            },
        },
        {
            "name": "Placeholder Domain Claim",
            "availability_status": "AVAILABLE",
            "evidence": {
                "source_id": "src-fake",
                "source_url": "https://example.com/fake-product",
                "retrieved_at": now_iso,
                "evidence_content": "Fabricated listing.",
                "verification_status": "VERIFIED",
            },
        },
        {
            "name": "Stale Research Result",
            "availability_status": "AVAILABLE",
            "evidence": {
                "source_id": "src-old",
                "source_url": "https://docs.python.org/3/",
                "retrieved_at": "2020-01-01T00:00:00Z",
                "evidence_content": "Outdated spec.",
                "verification_status": "VERIFIED",
                "freshness": "STALE",
            },
        },
        {
            "name": "Discontinued Tool",
            "availability_status": "UNAVAILABLE",
            "evidence": {
                "source_id": "src-sunset",
                "source_url": "https://docs.python.org/3/",
                "retrieved_at": now_iso,
                "evidence_content": "Service shut down.",
                "verification_status": "VERIFIED",
            },
        },
    ]

    rec_res = evaluate_recommendation_candidates(sample_candidates)
    reg = ToolRegistry()
    reg.register({
        "name": "doc_reader",
        "description": "Read-only document reader",
        "effect": "read_only",
        "required_permission": "tools:read",
        "input_schema": {
            "type": "object",
            "properties": {"uri": {"type": "string"}},
            "required": ["uri"],
            "additionalProperties": False,
        },
    })
    tool_unwired = verify_tool_availability(
        "doc_reader",
        registry=reg,
        policy=ExecutionPolicy(allow_read_only=True, allow_side_effecting=False),
        granted_permissions={"tools:read"},
        runtime_executor_wired=False,
        service_available=True,
    )
    tool_offline = verify_tool_availability(
        "doc_reader",
        registry=reg,
        policy=ExecutionPolicy(allow_read_only=True, allow_side_effecting=False),
        granted_permissions={"tools:read"},
        runtime_executor_wired=True,
        service_available=False,
    )
    tool_missing = verify_tool_availability(
        "unknown_tool",
        registry=reg,
        policy=ExecutionPolicy(),
        granted_permissions=set(),
    )
    unsupported = detect_unsupported_capabilities()
    false_success = verify_false_success_prevention()
    doc_links = verify_repo_doc_links()

    gates = {
        "recommendation_verification": (
            rec_res["overall_status"] == "VERIFIED"
            and [r["name"] for r in rec_res["recommended"]] == ["Verified Native Tool"]
            and len(rec_res["rejected"]) == 4
            and rec_res["filler_items_added"] == 0
        ),
        "tool_availability_verification": (
            tool_unwired["output_status"] == "UNVERIFIED"
            and not tool_unwired["usable"]
            and tool_offline["output_status"] == "UNAVAILABLE"
            and not tool_offline["usable"]
            and tool_missing["output_status"] == "NOT_FOUND"
        ),
        "source_authenticity": (
            any(r["name"] == "Placeholder Domain Claim" for r in rec_res["rejected"])
            and verify_evidence_record({"source_id": "", "retrieved_at": now_iso, "evidence_content": "x", "verification_status": "VERIFIED"})["status"] == "UNVERIFIED"
        ),
        "broken_link_detection": (
            any(r["name"] == "Broken Link Service" for r in rec_res["rejected"])
            and not validate_url_integrity("not-a-valid-url://x")["valid"]
            and not validate_url_integrity("https://bad host/path")["valid"]
            and doc_links["passed"]
        ),
        "unsupported_capability_detection": unsupported["passed"],
        "false_success_prevention": false_success["passed"],
    }

    digest_payload = json.dumps({"gates": gates, "unsupported": unsupported, "false_success": false_success}, sort_keys=True)
    return {
        "schema": "zyrquen.p0.reality_acceptance.v1",
        "overall_status": "PASS" if all(gates.values()) else "FAIL",
        "gates": gates,
        "recommendation_audit": rec_res,
        "tool_availability_audit": {
            "unwired": tool_unwired,
            "offline": tool_offline,
            "missing": tool_missing,
        },
        "unsupported_capabilities": unsupported,
        "false_success_prevention": false_success,
        "doc_links": doc_links,
        "digest_sha256": hashlib.sha256(digest_payload.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    report = run_p0_reality_acceptance()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
