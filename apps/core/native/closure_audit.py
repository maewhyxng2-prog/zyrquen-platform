"""V10 Final Closure Audit service (Contracts 1-5 + V10-A/B/C/D -> V11 Gate).

All verification statuses are computed dynamically from live repository symbols,
runtime capabilities, evaluation report artifacts, and model registry state.
Never fabricates PASS for unrun, missing, or blocked runtime verification.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.core.native import train as train_mod
from apps.core.native.checkpoint import VersionedCheckpointManager
from apps.core.native.config import (
    MAX_V10_PARAMETERS,
    NATIVE_MODEL_TYPE,
    ZyrquenConfig,
)
from apps.core.native.dataset import SCHEMA as DATASET_SCHEMA
from apps.core.native.evaluation import EvaluationEngine
from apps.core.native.registry import (
    FROZEN_BASELINE_NAMES,
    PROMOTABLE_LIFECYCLE_STATES,
    V10_VERSIONING_CONTRACT,
    ModelRegistry,
    RegistryError,
    _validate_evaluation_evidence_record,
    is_v10_model_version,
)
from apps.core.native.sft import (
    IGNORE_INDEX,
    SFT_FORMAT_VERSION,
    SFT_SEP,
    bind_ephemeral_slots,
    encode_sft_pair,
    encode_sft_prompt,
    restore_ephemeral_slots,
)
from apps.core.native.tokenizer import (
    BASE_VOCAB,
    SCHEMA_V2 as TOKENIZER_SCHEMA_V2,
    SLOT_COUNT,
    SLOT_TOKENS,
    ZyrquenTokenizer,
)
from apps.core.training.orchestrator import (
    MAX_CPU_MODEL_PARAMETERS,
    TrainingOrchestrator,
)
from apps.core.workflow import CentralWorkflowOrchestrator, WORKFLOW_GROUPS
from apps.core.workflow.governance import WorkflowGovernance
from apps.core.workflow.handlers.groups import (
    _V10_EXPECTED_CAPABILITIES,
    _V10_REPORT_SCHEMA,
    handle_evaluation_gate,
    handle_training_execute,
)

CLOSURE_AUDIT_SCHEMA = "zyrquen.v10.closure_audit.v1"

_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]


def _check_contract_1() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    passed = True
    summary = ""
    try:
        cfg_default = ZyrquenConfig()
        default_params = cfg_default.validate_parameter_budget(MAX_V10_PARAMETERS)
        cfg_4096 = ZyrquenConfig(vocab_size=4096, d_ff=704)
        vocab4096_params = cfg_4096.validate_parameter_budget(MAX_V10_PARAMETERS)

        model_type_ok = cfg_default.model_type == NATIVE_MODEL_TYPE == "zyrquen-decoder"
        seq_ok = cfg_default.max_seq_len <= 256
        budget_ok = default_params <= MAX_V10_PARAMETERS and vocab4096_params <= MAX_V10_PARAMETERS
        passed = bool(model_type_ok and seq_ok and budget_ok)

        checks.extend([
            {"label": "model_type", "passed": model_type_ok, "detail": cfg_default.model_type},
            {
                "label": "default_params",
                "passed": default_params <= MAX_V10_PARAMETERS,
                "detail": f"{default_params:,} / {MAX_V10_PARAMETERS:,}",
            },
            {
                "label": "vocab_4096_params",
                "passed": vocab4096_params <= MAX_V10_PARAMETERS,
                "detail": f"{vocab4096_params:,} / {MAX_V10_PARAMETERS:,}",
            },
            {"label": "max_seq_len", "passed": seq_ok, "detail": f"<= 256 (default={cfg_default.max_seq_len})"},
        ])
        summary = (
            f"{NATIVE_MODEL_TYPE} verified at {default_params:,} params "
            f"(4096-vocab: {vocab4096_params:,} <= {MAX_V10_PARAMETERS:,})"
        )
    except Exception as exc:
        passed = False
        summary = f"Contract 1 verification failed: {exc}"

    return {
        "id": "C1",
        "code": "CONTRACT-1",
        "title": "Model Architecture & 5M CPU Budget",
        "stage": "V10-A",
        "status": "STATIC PASS" if passed else "FAILED",
        "anchor": "apps/core/native/config.py::ZyrquenConfig",
        "summary": summary,
        "checks": checks,
    }


def _check_contract_2() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    passed = True
    summary = ""
    try:
        tok = ZyrquenTokenizer(schema=TOKENIZER_SCHEMA_V2)
        schema_ok = tok.schema == "zyrquen.tokenizer.v2"
        slot_count_ok = SLOT_COUNT == 32 and len(SLOT_TOKENS) == 32
        atomic_ok = bool(tok.supports_atomic_slots and tok.n_special == 36 and tok.byte_offset == 36)
        slot_ids_ok = tok.slot_id(0) == 4 and tok.slot_id(31) == 35
        encoded = tok.encode("<slot_0> <slot_31>")
        encode_ok = encoded[0] == 4 and encoded[-1] == 35 and tok.decode(encoded, skip_special=True) == "<slot_0> <slot_31>"
        passed = bool(schema_ok and slot_count_ok and atomic_ok and slot_ids_ok and encode_ok and BASE_VOCAB == 260)
        checks.extend([
            {"label": "tokenizer_schema", "passed": schema_ok, "detail": tok.schema},
            {"label": "atomic_slots", "passed": slot_count_ok and slot_ids_ok, "detail": "32 slots (IDs 4..35)"},
            {"label": "roundtrip_encode", "passed": encode_ok, "detail": "preserves <slot_0>..<slot_31>"},
        ])
        summary = f"{TOKENIZER_SCHEMA_V2} atomic slots (IDs 4..35, n_special={tok.n_special}) verified"
    except Exception as exc:
        passed = False
        summary = f"Contract 2 verification failed: {exc}"

    return {
        "id": "C2",
        "code": "CONTRACT-2",
        "title": "Slot-Safe Native Tokenizer",
        "stage": "V10-A",
        "status": "STATIC PASS" if passed else "FAILED",
        "anchor": "apps/core/native/tokenizer.py::ZyrquenTokenizer",
        "summary": summary,
        "checks": checks,
    }


def _check_contract_3() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    passed = True
    summary = ""
    try:
        tok = ZyrquenTokenizer(schema=TOKENIZER_SCHEMA_V2)
        bp, bt, binding = bind_ephemeral_slots("Go TE_E500 -> TE_E501", "TE_E501")
        restored = restore_ephemeral_slots(f"Ans: {bt}", binding)
        slot_roundtrip_ok = (bp == "Go <slot_0> -> <slot_1>" and bt == "<slot_1>" and restored == "Ans: TE_E501")

        prefix = encode_sft_prompt(tok, bp)
        x, y = encode_sft_pair(tok, bp, bt or "<slot_1>", max_seq_len=128)
        mask_ok = (
            len(x) == len(y)
            and prefix[0] == tok.bos_id
            and all(lbl == IGNORE_INDEX for lbl in y[: len(prefix) - 1])
            and y[-1] == tok.eos_id
        )
        const_ok = SFT_FORMAT_VERSION == "zyrquen.sft.v1" and IGNORE_INDEX == -100 and bool(SFT_SEP)
        passed = bool(slot_roundtrip_ok and mask_ok and const_ok)
        checks.extend([
            {"label": "sft_format", "passed": const_ok, "detail": f"{SFT_FORMAT_VERSION} (IGNORE_INDEX={IGNORE_INDEX})"},
            {"label": "ephemeral_slots", "passed": slot_roundtrip_ok, "detail": "bind/restore round-trip"},
            {"label": "causal_masking", "passed": mask_ok, "detail": "prefix masked to -100, EOS aligned"},
        ])
        summary = f"{SFT_FORMAT_VERSION} boundary, -100 masking, and ephemeral slot round-trip verified"
    except Exception as exc:
        passed = False
        summary = f"Contract 3 verification failed: {exc}"

    return {
        "id": "C3",
        "code": "CONTRACT-3",
        "title": "SFT Alignment & Ephemeral Slots",
        "stage": "V10-A",
        "status": "STATIC PASS" if passed else "FAILED",
        "anchor": "apps/core/native/sft.py::encode_sft_pair",
        "summary": summary,
        "checks": checks,
    }


def _check_contract_4(repo_root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    try:
        gen_exists = (repo_root / "tools" / "gen_nagi_v10.py").is_file()
        audit_exists = (repo_root / "tools" / "audit_leakage_v10.py").is_file()
        schema_ok = DATASET_SCHEMA == "zyrquen.dataset-manifest.v1"
        orch_budget_ok = MAX_CPU_MODEL_PARAMETERS == 5_000_000 and hasattr(TrainingOrchestrator, "prepare")

        passed = bool(gen_exists and audit_exists and schema_ok and orch_budget_ok)
        checks.extend([
            {"label": "dataset_schema", "passed": schema_ok, "detail": DATASET_SCHEMA},
            {"label": "v10_data_tools", "passed": gen_exists and audit_exists, "detail": "gen_nagi_v10.py + audit_leakage_v10.py"},
            {"label": "orchestrator_prepare", "passed": orch_budget_ok, "detail": f"CPU cap {MAX_CPU_MODEL_PARAMETERS:,}"},
        ])
        summary = (
            f"{DATASET_SCHEMA}, v10 leakage audit tooling, and TrainingOrchestrator.prepare verified"
        )
    except Exception as exc:
        passed = False
        summary = f"Contract 4 verification failed: {exc}"

    return {
        "id": "C4",
        "code": "CONTRACT-4",
        "title": "Unified Dataset, Leakage Gate & Prepare Budget",
        "stage": "V10-A",
        "status": "STATIC PASS" if passed else "FAILED",
        "anchor": "apps/core/training/orchestrator.py::TrainingOrchestrator",
        "summary": summary,
        "checks": checks,
    }


def _verify_streaming_sft_parity(repo_root: Path) -> tuple[bool, str]:
    streaming_path = repo_root / "apps" / "core" / "streaming.py"
    if not streaming_path.is_file():
        return False, "apps/core/streaming.py missing"

    if importlib.util.find_spec("pydantic") is not None:
        try:
            from apps.core import streaming as streaming_mod  # noqa: PLC0415

            has_encode = callable(getattr(streaming_mod, "_encode_prompt", None))
            has_dec = hasattr(streaming_mod, "_IncrementalTokenDecoder")
            has_sft = getattr(streaming_mod, "SFT_FORMAT_VERSION", None) == SFT_FORMAT_VERSION
            ok = bool(has_encode and has_dec and has_sft)
            return ok, "streaming._encode_prompt & SFT_FORMAT_VERSION runtime verified" if ok else "streaming parity check failed"
        except Exception as exc:
            return False, f"streaming import error: {exc}"

    # Pure-stdlib AST verification when optional pydantic is absent in test environment
    try:
        tree = ast.parse(streaming_path.read_text(encoding="utf-8"))
        defs = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        src = streaming_path.read_text(encoding="utf-8")
        ok = (
            "_encode_prompt" in defs
            and "_IncrementalTokenDecoder" in defs
            and "SFT_FORMAT_VERSION" in src
            and "bind_ephemeral_slots" in src
        )
        return ok, "streaming.py AST parity verified (SFT_FORMAT_VERSION + bind_ephemeral_slots)"
    except Exception as exc:
        return False, f"streaming AST check failed: {exc}"


def _check_contract_5(repo_root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    try:
        src_train = inspect.getsource(train_mod.train)
        src_sft = inspect.getsource(train_mod.train_sft)
        train_finite_ok = 0 < src_train.find("math.isfinite(total_loss)") < src_train.find("optimizer.step()")
        sft_finite_ok = 0 < src_sft.find("math.isfinite(total_loss)") < src_sft.find("optimizer.step()")
        ckpt_ok = hasattr(VersionedCheckpointManager, "verify_version") and hasattr(VersionedCheckpointManager, "save_versioned")
        reg_ok = (
            hasattr(ModelRegistry, "register")
            and hasattr(ModelRegistry, "attach_evaluation_evidence")
            and hasattr(ModelRegistry, "reserve_next_v10_version")
            and {"v7", "v8", "v9"}.issubset(FROZEN_BASELINE_NAMES)
        )
        contract_ok = (
            V10_VERSIONING_CONTRACT.target_major == 10
            and V10_VERSIONING_CONTRACT.prefix == "ZYRQUEN-Native-10."
            and V10_VERSIONING_CONTRACT.matches("ZYRQUEN-Native-10.0.0")
            and not V10_VERSIONING_CONTRACT.matches("ZYRQUEN-Native-0.1.0")
        )
        streaming_ok, streaming_detail = _verify_streaming_sft_parity(repo_root)

        passed = bool(train_finite_ok and sft_finite_ok and ckpt_ok and reg_ok and contract_ok and streaming_ok)
        checks.extend([
            {"label": "isfinite_guard", "passed": train_finite_ok and sft_finite_ok, "detail": "loss finiteness verified before optimizer.step()"},
            {"label": "versioned_ckpt", "passed": ckpt_ok, "detail": "tokenizer_sha256 manifest verification"},
            {"label": "registry_integrity", "passed": reg_ok, "detail": "FROZEN_BASELINE_NAMES (v7, v8, v9) protected"},
            {"label": "v10_versioning_contract", "passed": contract_ok, "detail": f"{V10_VERSIONING_CONTRACT.schema} ({V10_VERSIONING_CONTRACT.initial_version})"},
            {"label": "streaming_parity", "passed": streaming_ok, "detail": streaming_detail},
        ])
        summary = "Versioned checkpoints, V10 canonical versioning contract, NaN/Inf optimizer guards, ModelRegistry protection, and streaming SFT parity verified"
    except Exception as exc:
        passed = False
        summary = f"Contract 5 verification failed: {exc}"

    return {
        "id": "C5",
        "code": "CONTRACT-5",
        "title": "Versioned Checkpoint, Streaming Parity & Registry Integrity",
        "stage": "V10-A",
        "status": "STATIC PASS" if passed else "FAILED",
        "anchor": "apps/core/native/registry.py::ModelRegistry",
        "summary": summary,
        "checks": checks,
    }


def _inspect_eval_report(eval_report_path: str | Path | None) -> dict[str, Any]:
    if not eval_report_path:
        return {"configured": False, "passed": False, "overall_status": None, "inference_status": None, "model_version": None, "reason": "EVAL_REPORT_NOT_CONFIGURED"}

    path = Path(eval_report_path)
    if path.is_symlink() or not path.is_file():
        return {"configured": True, "passed": False, "overall_status": "FAILED", "inference_status": None, "model_version": None, "reason": "EVAL_REPORT_INVALID_PATH"}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"configured": True, "passed": False, "overall_status": "FAILED", "inference_status": None, "model_version": None, "reason": "EVAL_REPORT_UNREADABLE"}

    if not isinstance(data, dict):
        return {"configured": True, "passed": False, "overall_status": "FAILED", "inference_status": None, "model_version": None, "reason": "EVAL_REPORT_INVALID_SCHEMA"}

    report_schema = data.get("report_schema") or data.get("schema")
    overall = str(data.get("overall_status", "")).strip().upper() or "NOT RUN"
    inference = str(data.get("inference_status", "")).strip().upper() or "NOT RUN"
    dataset_ok = str(data.get("dataset_integrity", "")).strip().upper() == "PASS"
    leakage_ok = str(data.get("leakage_audit_status", "")).strip().upper() == "PASS"

    ckpt_meta = data.get("checkpoint")
    eval_model_version: str | None = None
    if isinstance(ckpt_meta, dict) and ckpt_meta.get("model_version") is not None:
        eval_model_version = str(ckpt_meta.get("model_version")).strip() or None
    elif data.get("model_version") is not None:
        eval_model_version = str(data.get("model_version")).strip() or None
    version_ok = eval_model_version is None or is_v10_model_version(eval_model_version)

    # Zero-regression check if comparison entries are present
    reg_entries = data.get("regression_comparison")
    regression_ok = True
    if isinstance(reg_entries, list) and reg_entries:
        regression_ok = all(isinstance(item, dict) and item.get("zero_regression") is True for item in reg_entries)

    passed = (
        report_schema == _V10_REPORT_SCHEMA
        and overall == "PASS"
        and inference == "PASS"
        and dataset_ok
        and leakage_ok
        and regression_ok
        and version_ok
    )
    reason = None
    if not passed:
        if report_schema != _V10_REPORT_SCHEMA:
            reason = "EVAL_REPORT_SCHEMA_MISMATCH"
        elif overall == "BLOCKED" or inference == "BLOCKED":
            reason = "EVAL_INFERENCE_BLOCKED"
        elif not version_ok:
            reason = "EVAL_REPORT_NON_V10_MODEL"
        elif not regression_ok:
            reason = "EVAL_REGRESSION_FAILED"
        elif overall in {"FAIL", "FAILED"}:
            reason = "EVAL_FAILED"
        else:
            reason = "EVAL_NOT_PASSED"

    return {
        "configured": True,
        "passed": passed,
        "report_schema": report_schema,
        "model_version": eval_model_version,
        "overall_status": overall,
        "inference_status": inference,
        "dataset_integrity": data.get("dataset_integrity"),
        "leakage_audit_status": data.get("leakage_audit_status"),
        "reason": reason,
    }


def _inspect_registry(registry_root: str | Path | None) -> dict[str, Any]:
    if not registry_root:
        return {
            "configured": False,
            "active_version": None,
            "active_v10_version": None,
            "registered_count": 0,
            "registered_v10_count": 0,
            "ignored_legacy_versions": [],
            "verified_v10_count": 0,
            "verified_v10_versions": [],
            "reason": "MODEL_REGISTRY_NOT_CONFIGURED",
        }

    path = Path(registry_root)
    if path.is_symlink() or not path.is_dir():
        return {
            "configured": True,
            "active_version": None,
            "active_v10_version": None,
            "registered_count": 0,
            "registered_v10_count": 0,
            "ignored_legacy_versions": [],
            "verified_v10_count": 0,
            "verified_v10_versions": [],
            "reason": "MODEL_REGISTRY_UNAVAILABLE",
        }

    try:
        reg = ModelRegistry(path)
        active = reg.active_version()
        versions = reg.list_versions()
    except RegistryError:
        return {
            "configured": True,
            "active_version": None,
            "active_v10_version": None,
            "registered_count": 0,
            "registered_v10_count": 0,
            "ignored_legacy_versions": [],
            "verified_v10_count": 0,
            "verified_v10_versions": [],
            "reason": "MODEL_REGISTRY_UNREADABLE",
        }

    verified_v10_versions: list[str] = []
    registered_v10_versions: list[str] = []
    ignored_legacy_versions: list[str] = []
    for rec in versions:
        if not isinstance(rec, dict):
            continue
        version_name = str(rec.get("version") or "")
        if not is_v10_model_version(version_name):
            if version_name:
                ignored_legacy_versions.append(version_name)
            continue
        registered_v10_versions.append(version_name)
        if rec.get("lifecycle_status") not in PROMOTABLE_LIFECYCLE_STATES:
            continue
        ev = rec.get("evaluation_evidence")
        try:
            _validate_evaluation_evidence_record(ev, version_name)
            if not reg.verify(version_name):
                continue
        except RegistryError:
            continue
        verified_v10_versions.append(version_name)

    verified_v10_count = len(verified_v10_versions)
    active_v10 = active if is_v10_model_version(active) else None
    return {
        "configured": True,
        "active_version": active,
        "active_v10_version": active_v10,
        "registered_count": len(versions),
        "registered_v10_count": len(registered_v10_versions),
        "ignored_legacy_versions": ignored_legacy_versions,
        "verified_v10_count": verified_v10_count,
        "verified_v10_versions": verified_v10_versions,
        "reason": None if verified_v10_count > 0 else "TRAINED_V10_MODEL_UNAVAILABLE",
    }


def build_v10_closure_audit(
    *,
    repo_root: str | Path | None = None,
    eval_report_path: str | Path | None = None,
    registry_root: str | Path | None = None,
    dataset_dir: str | Path | None = None,
    tokenizer_path: str | Path | None = None,
    runtime_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute honest, non-fabricated V10 closure audit and V11 readiness gate."""
    root = Path(repo_root) if repo_root else _DEFAULT_REPO_ROOT

    resolved_eval_path = eval_report_path if eval_report_path is not None else os.getenv("ZYRQUEN_EVAL_REPORT_PATH", "").strip()
    resolved_registry_root = registry_root if registry_root is not None else os.getenv("ZYRQUEN_MODEL_REGISTRY_ROOT", "").strip()
    resolved_dataset_dir = dataset_dir if dataset_dir is not None else os.getenv("ZYRQUEN_DATASET_DIR", "").strip()
    resolved_tokenizer_path = tokenizer_path if tokenizer_path is not None else os.getenv("ZYRQUEN_TOKENIZER_PATH", "").strip()

    if runtime_health is None:
        try:
            from apps.core.runtime import runtime  # noqa: PLC0415

            runtime_health = runtime.get_health_status()
        except Exception:
            runtime_health = {
                "runtime_status": "unavailable",
                "native_model_loaded": False,
                "is_trained": False,
                "model_version": None,
            }

    contracts = [
        _check_contract_1(),
        _check_contract_2(),
        _check_contract_3(),
        _check_contract_4(root),
        _check_contract_5(root),
    ]
    contracts_passed_count = sum(1 for c in contracts if c["status"] == "STATIC PASS")
    contracts_total = len(contracts)
    v10a_passed = contracts_passed_count == contracts_total

    # V10-B verification: Workflow Engine + Governance + Anti-False-PASS Eval Gate
    try:
        workflow_groups_ok = len(WORKFLOW_GROUPS) == 8
        eval_gate_ok = (
            callable(handle_evaluation_gate)
            and _V10_REPORT_SCHEMA == "zyrquen.v10.evaluation_report.v1"
            and len(_V10_EXPECTED_CAPABILITIES) == 6
        )
        gov_ok = hasattr(WorkflowGovernance, "verify_and_consume_by_id") and hasattr(CentralWorkflowOrchestrator, "trigger_workflow")
        v10b_ok = bool(workflow_groups_ok and eval_gate_ok and gov_ok)
        v10b_summary = (
            f"{len(WORKFLOW_GROUPS)} workflow groups, Tier-2 HMAC governance, and anti-False-PASS gate ({_V10_REPORT_SCHEMA}) implemented"
        )
    except Exception as exc:
        v10b_ok = False
        v10b_summary = f"V10-B workflow/governance check failed: {exc}"

    # V10-C verification: Training Hook, EvaluationEngine, and v10 CLI suite
    torch_installed = importlib.util.find_spec("torch") is not None
    try:
        eval_engine_status = EvaluationEngine().get_status()
        eval_wired = bool(eval_engine_status.get("native_inference_evaluation_wired"))
        cli_files = ("train_nagi_v10.py", "eval_nagi_v10.py", "diagnose_nagi_v10.py", "compare_nagi_v10.py", "v10_summary.md")
        cli_ok = all((root / "tools" / name).is_file() for name in cli_files)
        v10c_ok = bool(callable(handle_training_execute) and eval_wired and cli_ok)
        v10c_summary = (
            "Native SFT training hook, EvaluationEngine native inference wiring, and v10 CLI suite implemented"
        )
    except Exception as exc:
        v10c_ok = False
        v10c_summary = f"V10-C integration hook check failed: {exc}"

    # V10-D Runtime Closure Gate: real torch + trained model/registry + passing V10 evaluation report
    eval_info = _inspect_eval_report(resolved_eval_path or None)
    registry_info = _inspect_registry(resolved_registry_root or None)

    native_loaded = bool(runtime_health.get("native_model_loaded"))
    is_trained = bool(runtime_health.get("is_trained"))
    runtime_model_ver = runtime_health.get("model_version")
    is_trained_v10 = is_trained and (
        runtime_model_ver is None or is_v10_model_version(runtime_model_ver)
    )
    dataset_configured = bool(resolved_dataset_dir and Path(resolved_dataset_dir).is_dir())
    tokenizer_configured = bool(resolved_tokenizer_path and Path(resolved_tokenizer_path).is_file())

    eval_report_version = eval_info.get("model_version")
    eval_registry_mismatch = bool(
        eval_info.get("passed")
        and eval_report_version is not None
        and registry_info.get("configured")
        and eval_report_version not in (registry_info.get("verified_v10_versions") or [])
    )

    blockers: list[str] = []
    if not torch_installed:
        blockers.append("TORCH_NOT_INSTALLED")
    if not dataset_configured:
        blockers.append("DATASET_DIR_NOT_CONFIGURED")
    if not tokenizer_configured:
        blockers.append("TOKENIZER_NOT_CONFIGURED")
    if eval_info.get("reason"):
        blockers.append(str(eval_info["reason"]))
    if eval_registry_mismatch:
        blockers.append("EVAL_REPORT_MODEL_VERSION_UNVERIFIED")
    if registry_info.get("reason"):
        blockers.append(str(registry_info["reason"]))
    if not is_trained_v10 and registry_info.get("verified_v10_count", 0) == 0:
        if "TRAINED_V10_MODEL_UNAVAILABLE" not in blockers:
            blockers.append("TRAINED_V10_MODEL_UNAVAILABLE")

    if not v10a_passed or not v10b_ok or not v10c_ok:
        v10d_status = "FAILED"
        v10d_summary = "Static V10-A/B/C integration checks failed before runtime closure."
    elif not torch_installed:
        v10d_status = "BLOCKED"
        v10d_summary = "Runtime training and native inference evaluation are blocked: PyTorch (torch) is not installed in this environment."
    elif eval_info.get("overall_status") == "BLOCKED" or eval_info.get("inference_status") == "BLOCKED":
        v10d_status = "BLOCKED"
        v10d_summary = "Configured V10 evaluation report reports BLOCKED status."
    elif (
        eval_info.get("overall_status") in {"FAIL", "FAILED"}
        or eval_registry_mismatch
        or eval_info.get("reason") in {
            "EVAL_REPORT_INVALID_PATH",
            "EVAL_REPORT_UNREADABLE",
            "EVAL_REPORT_INVALID_SCHEMA",
            "EVAL_REPORT_NON_V10_MODEL",
            "EVAL_REGRESSION_FAILED",
            "EVAL_FAILED",
        }
    ):
        v10d_status = "FAILED"
        v10d_summary = (
            "Configured V10 evaluation report targets an unverified model version."
            if eval_registry_mismatch
            else f"V10 evaluation artifact failed verification ({eval_info.get('reason')})."
        )
    elif eval_info.get("passed") and (is_trained_v10 or registry_info.get("verified_v10_count", 0) > 0):
        v10d_status = "PASS"
        v10d_summary = "Verified V10 trained model, registry evidence, and passing native evaluation report confirmed."
        blockers = []
    else:
        v10d_status = "NOT RUN"
        v10d_summary = "PyTorch is available, but verified V10 runtime training and passing evaluation report have not completed."

    static_status = "STATIC PASS" if (v10a_passed and v10b_ok and v10c_ok) else "FAILED"
    if static_status != "STATIC PASS":
        overall_status = "FAILED"
    elif v10d_status == "PASS":
        overall_status = "PASS"
    else:
        overall_status = v10d_status

    v11_unlocked = overall_status == "PASS"
    if v11_unlocked:
        v11_summary = "V10 Final Closure Gate passed with verified runtime training and evaluation evidence. V11 is authorized for execution."
    else:
        v11_summary = (
            f"V11 remains LOCKED until V10-D runtime closure passes "
            f"(current status: {overall_status}). Static V10-A contracts: {contracts_passed_count}/{contracts_total}."
        )

    stages = [
        {
            "id": "V10-A",
            "title": "Integration & Architecture Contracts 1-5",
            "status": "STATIC PASS" if v10a_passed else "FAILED",
            "summary": f"{contracts_passed_count}/{contracts_total} static contracts verified.",
            "blockers": [],
        },
        {
            "id": "V10-B",
            "title": "Workflow Engine, Eval Gate & Security Governance",
            "status": "IMPLEMENTED" if v10b_ok else "FAILED",
            "summary": v10b_summary,
            "blockers": [],
        },
        {
            "id": "V10-C",
            "title": "Native Training Hook, Inference & Evaluation CLI",
            "status": "IMPLEMENTED" if v10c_ok else "FAILED",
            "summary": v10c_summary,
            "blockers": [] if torch_installed else ["TORCH_NOT_INSTALLED"],
        },
        {
            "id": "V10-D",
            "title": "Final Runtime Training, Native Eval & Closure Gate",
            "status": v10d_status,
            "summary": v10d_summary,
            "blockers": blockers,
        },
    ]

    active_v10_model = registry_info.get("active_v10_version") or (
        runtime_model_ver if is_v10_model_version(runtime_model_ver) else None
    )

    return {
        "schema": CLOSURE_AUDIT_SCHEMA,
        "versioning_contract": V10_VERSIONING_CONTRACT.schema,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall_status,
        "static_status": static_status,
        "runtime_status": v10d_status,
        "contracts_passed_count": contracts_passed_count,
        "contracts_total": contracts_total,
        "v11_gate": {
            "target_version": "V11",
            "unlocked": v11_unlocked,
            "status": "READY" if v11_unlocked else "LOCKED",
            "prerequisite_summary": v11_summary,
        },
        "runtime_environment": {
            "torch_installed": torch_installed,
            "native_runtime_status": str(runtime_health.get("runtime_status", "unavailable")),
            "native_model_loaded": native_loaded,
            "is_trained": is_trained,
            "active_model_version": registry_info.get("active_version") or runtime_model_ver,
            "active_v10_model_version": active_v10_model,
            "eval_report_configured": bool(eval_info.get("configured")),
            "eval_report_status": eval_info.get("overall_status"),
            "eval_report_model_version": eval_report_version,
            "registry_configured": bool(registry_info.get("configured")),
            "verified_v10_models": int(registry_info.get("verified_v10_count", 0)),
            "verified_v10_versions": list(registry_info.get("verified_v10_versions") or []),
            "ignored_legacy_versions": list(registry_info.get("ignored_legacy_versions") or []),
            "dataset_configured": dataset_configured,
            "tokenizer_configured": tokenizer_configured,
        },
        "blockers": blockers,
        "contracts": contracts,
        "stages": stages,
    }
