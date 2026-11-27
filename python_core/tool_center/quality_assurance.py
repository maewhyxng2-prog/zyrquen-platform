"""
Quality Assurance Engine for ZYRQUEN Tool Center.
------------------------------------------------
Independently verifies tool outputs before delivery. Never assumes a tool
succeeded merely because no exception was raised. Strictly separates final
states: SUCCESS | PARTIAL_SUCCESS | FAILED | UNVERIFIED.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .contracts import CapabilitySpec, validate_capability_output

_SECRET_LEAK_RE = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]{16,}\b|\bAIza[0-9A-Za-z_-]{20,}\b|\bghp_[0-9A-Za-z]{20,}\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)


def verify_capability_delivery(
    spec: CapabilitySpec | None,
    result: dict[str, Any],
    *,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Independently verify execution result before returning it to Studio/Agents.
    Checks:
      1. Execution flags & external_models_used == False
      2. Declared output_schema compliance
      3. Secret leak / traversal check on serialized output
      4. Artifact existence on disk when output claims a file was saved
      5. Honest classification into SUCCESS / PARTIAL_SUCCESS / FAILED / UNVERIFIED
    """
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    blockers: list[str] = []

    if not isinstance(result, dict):
        return {
            "verdict": "FAILED",
            "passed": False,
            "checks": [{"check": "result_structure", "passed": False, "detail": "Result is not a dict"}],
            "warnings": [],
            "blockers": ["Invalid execution result type."],
        }

    # 1. Policy: zero external models
    ext_used = bool(result.get("external_models_used", False))
    checks.append({
        "check": "native_only_policy",
        "passed": not ext_used,
        "detail": "external_models_used must be False",
    })
    if ext_used:
        blockers.append("External model usage detected in capability result.")

    status = str(result.get("status") or "").upper()
    if spec and spec.lifecycle_status == "IN_DEVELOPMENT":
        return {
            "verdict": "UNVERIFIED",
            "passed": False,
            "checks": checks + [{"check": "lifecycle_readiness", "passed": False, "detail": "Capability is IN_DEVELOPMENT"}],
            "warnings": [],
            "blockers": [f"Capability '{spec.id}' is IN_DEVELOPMENT and cannot be certified SUCCESS."],
        }

    if status == "PENDING_APPROVAL":
        return {
            "verdict": "UNVERIFIED",
            "passed": True,
            "checks": checks + [{"check": "approval_gate", "passed": True, "detail": "Awaiting Admin P5 Approval"}],
            "warnings": ["Waiting for Admin approval before final verification."],
            "blockers": [],
        }

    if not result.get("ok") or status in {"FAILED", "BLOCKED", "REJECTED"}:
        return {
            "verdict": "FAILED",
            "passed": False,
            "checks": checks + [{"check": "execution_status", "passed": False, "detail": f"status={status}"}],
            "warnings": [],
            "blockers": [str(result.get("error") or f"Capability ended with status={status}")],
        }

    output = result.get("output") if isinstance(result.get("output"), dict) else {}

    # 2. Output Schema Contract
    if spec is not None:
        valid_out, err_out = validate_capability_output(spec, output)
        checks.append({
            "check": "output_schema_contract",
            "passed": valid_out,
            "detail": err_out or "Matches declared output_schema",
        })
        if not valid_out:
            blockers.append(str(err_out))
    else:
        checks.append({"check": "output_schema_contract", "passed": bool(output), "detail": "Output present"})

    # 3. Output hygiene (no secret material leaked in output payload)
    serialized = json.dumps(output, ensure_ascii=False)
    has_secret = bool(_SECRET_LEAK_RE.search(serialized))
    checks.append({
        "check": "output_secret_hygiene",
        "passed": not has_secret,
        "detail": "No raw secret tokens detected in output" if not has_secret else "Potential secret pattern detected in output",
    })
    if has_secret:
        blockers.append("Output rejected by QA: secret-like token detected in payload.")

    # 4. File / artifact existence verification if claimed written
    claimed_file = None
    if isinstance(output.get("file"), dict):
        claimed_file = output["file"].get("name") or output["file"].get("path")
    elif isinstance(output.get("saved_file"), dict):
        claimed_file = output["saved_file"].get("name") or output["saved_file"].get("path")
    elif output.get("saved_file"):
        claimed_file = output.get("saved_file")
    if claimed_file and data_dir is not None:
        ws_file = (Path(data_dir) / "workspace_files" / Path(str(claimed_file)).name).resolve()
        ws_root = (Path(data_dir) / "workspace_files").resolve()
        exists_ok = ws_file.is_relative_to(ws_root) and ws_file.exists() and ws_file.stat().st_size > 0
        checks.append({
            "check": "artifact_disk_verification",
            "passed": exists_ok,
            "detail": f"Verified non-empty artifact '{ws_file.name}'" if exists_ok else f"Claimed artifact '{claimed_file}' missing or empty on disk",
        })
        if not exists_ok:
            blockers.append(f"Artifact verification failed for '{claimed_file}'.")

    # 4b. Multi-file sandbox workspace disk verification (for app_builder / real_build_runner / project_scaffold)
    ws_name = str(output.get("workspace") or "").strip()
    claimed_files = output.get("files")
    if (
        ws_name
        and isinstance(claimed_files, list)
        and claimed_files
        and data_dir is not None
        and not output.get("dry_run")
        and not output.get("rolled_back")
    ):
        sb_root = (Path(data_dir) / "sandbox_workspaces" / ws_name).resolve()
        missing_ws_files: list[str] = []
        for rel_item in claimed_files:
            rel_s = str(rel_item or "").strip().lstrip("/")
            if not rel_s or ".." in Path(rel_s).parts:
                missing_ws_files.append(str(rel_item))
                continue
            target_f = (sb_root / rel_s).resolve()
            if not target_f.is_relative_to(sb_root) or not target_f.is_file():
                missing_ws_files.append(rel_s)
        ws_files_ok = len(missing_ws_files) == 0
        checks.append({
            "check": "workspace_multifile_disk_verification",
            "passed": ws_files_ok,
            "detail": (
                f"Verified {len(claimed_files)} files in sandbox_workspaces/{ws_name}"
                if ws_files_ok
                else f"Missing workspace files on disk: {', '.join(missing_ws_files[:5])}"
            ),
        })
        if not ws_files_ok:
            blockers.append(f"Multi-file workspace verification failed: {missing_ws_files[:5]}")

    # 4c. Real Build & Test Gate: never certify app build/runner unless build + lint + tests actually passed
    if spec and spec.id in {"development.app_builder", "development.real_build_runner"} and not output.get("dry_run"):
        b_ok = output.get("build_passed") is True
        l_ok = output.get("lint_passed") is True
        t_ok = output.get("tests_passed") is True
        t_run = int(output.get("tests_run") or 0) > 0
        v_ok = output.get("verified") is True
        gate_ok = b_ok and l_ok and t_ok and t_run and v_ok
        checks.append({
            "check": "real_build_and_test_gate",
            "passed": gate_ok,
            "detail": (
                f"build={b_ok}, lint={l_ok}, tests={t_ok}, tests_run={int(output.get('tests_run') or 0)}, verified={v_ok}"
            ),
        })
        if not gate_ok:
            blockers.append(
                "Build/Lint/Test gate failed: app delivery cannot be certified VERIFIED without passing real build and unit tests."
            )

    # 5. Domain-specific warnings (e.g. uncorroborated or unverified claims)
    if output.get("verdict") in {"INSUFFICIENT_EVIDENCE", "CONFLICTING_SOURCES"}:
        warnings.append(f"Research evidence returned honest non-verified verdict: {output.get('verdict')}")
    if spec and spec.id == "testing.sandbox_run" and not output.get("sandbox_isolated", True):
        blockers.append("Sandbox isolation flag missing.")

    if blockers:
        verdict = "FAILED"
        passed = False
    elif warnings:
        verdict = "PARTIAL_SUCCESS"
        passed = True
    else:
        verdict = "SUCCESS"
        passed = True

    return {
        "verdict": verdict,
        "passed": passed,
        "checks": checks,
        "warnings": warnings,
        "blockers": blockers,
    }


def aggregate_plan_verdict(step_records: list[dict[str, Any]]) -> str:
    if not step_records:
        return "UNVERIFIED"
    verdicts = [str((s.get("qa") or {}).get("verdict") or s.get("status") or "UNVERIFIED") for s in step_records]
    if any(v == "PENDING_APPROVAL" for v in verdicts):
        return "UNVERIFIED"
    if all(v == "SUCCESS" for v in verdicts):
        return "SUCCESS"
    if any(v in {"SUCCESS", "PARTIAL_SUCCESS"} for v in verdicts):
        return "PARTIAL_SUCCESS"
    if any(v == "UNVERIFIED" for v in verdicts) and not any(v == "FAILED" for v in verdicts):
        return "UNVERIFIED"
    return "FAILED"
