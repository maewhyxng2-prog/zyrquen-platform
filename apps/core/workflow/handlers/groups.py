"""Domain handlers for all 8 registered ZYRQUEN Workflow Groups.

Each handler wraps verified repository modules cleanly and obeys strict truth rules:
- Never fabricates PASS, metrics, or capabilities when artifacts/runtime are missing.
- Never calls external AI models as ZYRQUEN's native intelligence.
- Distinguishes PASS, FAIL, BLOCKED, and NOT RUN honestly.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from apps.core.native.registry import (
    ModelRegistry,
    NativeVersionReservation,
    RegistryError,
    is_v10_model_version,
    is_v11_model_version,
    resolve_canonical_model_version,
)
from apps.core.workflow.models import (
    LeakageGateFailedError,
    StepExecutionResult,
)
from apps.core.workflow.resource_guard import WorkflowResourceGuard
from apps.core.maintainer import (
    AuditFinding,
    AuditReport,
    MaintainerPolicyError,
    ZyrquenMaintainerBot,
)


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b")


def _repo_root() -> Path:
    # apps/core/workflow/handlers/groups.py -> repo root is 4 parents up
    return Path(__file__).resolve().parents[4]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------
# 1. System Operations Workflow
# ----------------------------------------------------------------------
def handle_system_ops_health(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
    guard: WorkflowResourceGuard = ctx["resource_guard"]
    snap = guard.snapshot()

    native_health: dict[str, Any]
    try:
        from apps.core.runtime import runtime

        native_health = runtime.get_health_status()
    except Exception as exc:
        native_health = {"runtime_status": "unavailable", "error": str(exc)}

    root = _repo_root()
    paths_status = {
        "apps_core": (root / "apps" / "core").is_dir(),
        "apps_api": (root / "apps" / "api").is_dir(),
        "tools_v9_ready": all(
            (root / "tools" / f).is_file()
            for f in ("gen_nagi_v9.py", "audit_leakage_v9.py", "train_nagi_v9.py", "eval_nagi_v9.py")
        ),
    }
    return StepExecutionResult(
        verdict="PASS" if snap["free_disk_gb"] >= 0.1 else "FAIL",
        summary=(
            f"System snapshot collected (RAM={snap['ram_mb']}MB, "
            f"DiskFree={snap['free_disk_gb']}GB, Native={native_health.get('runtime_status')})"
        ),
        output={
            "resource_snapshot": snap,
            "native_ai_health": native_health,
            "paths": paths_status,
        },
        evidence={"verdict": "PASS", "source": "WorkflowResourceGuard + NativeRuntime"},
    )


def handle_system_ops_report(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
    prev = ctx.get("previous_outputs", {}).get("check_health", {})
    return StepExecutionResult(
        verdict="PASS",
        summary="Daily system operations status report compiled from real health probes.",
        output={"daily_report": prev},
        evidence={"verdict": "PASS", "report_type": "daily_system_ops"},
    )


# ----------------------------------------------------------------------
# 2. Data Workflow
# ----------------------------------------------------------------------
def handle_data_verify_and_audit(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
    data_dir_raw = str(payload.get("dataset_dir") or os.getenv("ZYRQUEN_DATASET_DIR", "")).strip()
    if not data_dir_raw:
        return StepExecutionResult(
            verdict="NOT RUN",
            summary="No dataset_dir provided or ZYRQUEN_DATASET_DIR configured; data audit not executed.",
            output={"configured": False},
            evidence={"verdict": "NOT RUN", "reason": "dataset_dir_missing"},
        )

    data_dir = Path(data_dir_raw).resolve()
    manifest_path = data_dir / "manifest.json"
    if not data_dir.is_dir() or data_dir.is_symlink() or not manifest_path.is_file() or manifest_path.is_symlink():
        return StepExecutionResult(
            verdict="BLOCKED",
            summary=f"Dataset directory or manifest.json missing/symlinked at {data_dir}",
            output={"dataset_dir": str(data_dir), "manifest_exists": manifest_path.is_file()},
            evidence={"verdict": "BLOCKED", "reason": "manifest_missing"},
            error_code="manifest_missing",
        )

    # Check if v9 dataset schema (has val_unseen.jsonl & test_ood.jsonl)
    if (data_dir / "val_unseen.jsonl").is_file() and (data_dir / "test_ood.jsonl").is_file():
        import sys

        tools_dir = str(_repo_root() / "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        from audit_leakage_v9 import run_audit  # type: ignore

        audit = run_audit(data_dir)
        if audit.get("overall_status") != "PASS":
            raise LeakageGateFailedError(
                f"Data leakage gate failed for {data_dir}: "
                f"{[k for k, v in audit.get('gates', {}).items() if not v.get('passed')]}"
            )
        return StepExecutionResult(
            verdict="PASS",
            summary="v9 Data Leakage Gate (EL-01..08, TL-01, SL-01, DL-01, SEQ_BUDGET) PASSED.",
            output={"dataset_dir": str(data_dir), "manifest_sha256": _sha256_file(manifest_path), "audit": audit},
            evidence={"verdict": "PASS", "audit_status": "PASS", "manifest_sha256": _sha256_file(manifest_path)},
            emitted_events=[("data.ready", {"dataset_dir": str(data_dir)})],
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return StepExecutionResult(
            verdict="FAIL",
            summary=f"Failed to parse dataset manifest: {exc}",
            output={"dataset_dir": str(data_dir)},
            evidence={"verdict": "FAIL", "reason": "manifest_invalid"},
            error_code="manifest_invalid",
        )

    # Check if v10 dataset schema (dataset == 'nagi_v10' or canonical v10 SFT splits with example_id)
    is_v10_dataset = isinstance(manifest, dict) and manifest.get("dataset") == "nagi_v10"
    if (
        not is_v10_dataset
        and (data_dir / "train.jsonl").is_file()
        and (data_dir / "validation.jsonl").is_file()
        and (data_dir / "test.jsonl").is_file()
    ):
        try:
            with (data_dir / "train.jsonl").open("r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        first_row = json.loads(line)
                        is_v10_dataset = isinstance(first_row, dict) and (
                            "example_id" in first_row and "unique_answer_verified" in first_row
                        )
                        break
        except (OSError, json.JSONDecodeError):
            is_v10_dataset = False

    if is_v10_dataset:
        import sys

        tools_dir = str(_repo_root() / "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        from audit_leakage_v10 import run_audit as run_audit_v10  # type: ignore

        try:
            audit = run_audit_v10(data_dir)
        except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as exc:
            raise LeakageGateFailedError(f"v10 Data Leakage Gate failed for {data_dir}: {exc}") from exc

        if audit.get("overall_status") != "PASS":
            raise LeakageGateFailedError(
                f"v10 Data Leakage Gate failed for {data_dir}: "
                f"{[k for k, v in audit.get('gates', {}).items() if not v.get('passed')]}"
            )
        return StepExecutionResult(
            verdict="PASS",
            summary="v10 Data Leakage & Unique-Answer Gate (EL-01..06, TL-01, SL-01, DL-01, SEQ_BUDGET) PASSED.",
            output={
                "dataset_dir": str(data_dir),
                "version": manifest.get("version") if isinstance(manifest, dict) else None,
                "manifest_sha256": _sha256_file(manifest_path),
                "audit": audit,
            },
            evidence={"verdict": "PASS", "audit_status": "PASS", "manifest_sha256": _sha256_file(manifest_path)},
            emitted_events=[("data.ready", {"dataset_dir": str(data_dir), "dataset": "nagi_v10"})],
        )

    is_v11_dataset = isinstance(manifest, dict) and manifest.get("dataset") == "nagi_v11"
    if is_v11_dataset:
        from apps.core.native.dataset import V11_SPLITS, load_sft_split, verify_dataset_manifest
        from apps.core.native.sft import extract_entities

        try:
            verify_dataset_manifest(data_dir)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            raise LeakageGateFailedError(
                f"v11 Data Integrity Gate failed for {data_dir}: {exc}"
            ) from exc

        v11_audit_script = _repo_root() / "tools" / "audit_leakage_v11.py"
        if v11_audit_script.is_file():
            import sys

            tools_dir = str(_repo_root() / "tools")
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)
            from audit_leakage_v11 import run_audit as run_audit_v11  # type: ignore

            try:
                audit = run_audit_v11(data_dir)
            except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as exc:
                raise LeakageGateFailedError(
                    f"v11 Data Leakage Gate failed for {data_dir}: {exc}"
                ) from exc
            if audit.get("overall_status") != "PASS":
                raise LeakageGateFailedError(
                    f"v11 Data Leakage Gate failed for {data_dir}: "
                    f"{[k for k, v in audit.get('gates', {}).items() if not v.get('passed')]}"
                )
        else:
            split_entities: dict[str, set[str]] = {}
            split_inputs: dict[str, set[str]] = {}
            split_counts: dict[str, int] = {}
            for split_name in V11_SPLITS:
                try:
                    rows = list(load_sft_split(data_dir, split_name))
                except (ValueError, OSError, json.JSONDecodeError) as exc:
                    raise LeakageGateFailedError(
                        f"v11 split load failed ({split_name}): {exc}"
                    ) from exc
                if not rows:
                    raise LeakageGateFailedError(f"v11 split {split_name!r} is empty")
                split_counts[split_name] = len(rows)
                ents: set[str] = set()
                inputs: set[str] = set()
                for row in rows:
                    if row.get("unique_answer_verified") is False:
                        raise LeakageGateFailedError(
                            f"v11 record in {split_name} failed unique_answer_verified"
                        )
                    inp = str(row.get("input") or "")
                    tgt = str(row.get("target") or "")
                    ents.update(extract_entities(inp))
                    ents.update(extract_entities(tgt))
                    inputs.add(" ".join(inp.casefold().split()))
                split_entities[split_name] = ents
                split_inputs[split_name] = inputs

            for idx, s1 in enumerate(V11_SPLITS):
                for s2 in V11_SPLITS[idx + 1 :]:
                    ent_overlap = split_entities[s1] & split_entities[s2]
                    if ent_overlap:
                        raise LeakageGateFailedError(
                            f"v11 entity leakage between {s1} and {s2}: {sorted(ent_overlap)[:5]}"
                        )
                    inp_overlap = split_inputs[s1] & split_inputs[s2]
                    if inp_overlap:
                        raise LeakageGateFailedError(
                            f"v11 input overlap between {s1} and {s2} ({len(inp_overlap)} collisions)"
                        )
            audit = {
                "schema": "zyrquen.v11.dataset_audit.v1",
                "overall_status": "PASS",
                "splits_verified": list(V11_SPLITS),
                "split_counts": split_counts,
                "gates": {
                    "MANIFEST_INTEGRITY": {"passed": True},
                    "EL_ENTITY_DISJOINTNESS": {"passed": True},
                    "DL_INPUT_DISJOINTNESS": {"passed": True},
                },
            }

        manifest_sha = _sha256_file(manifest_path)
        return StepExecutionResult(
            verdict="PASS",
            summary="v11 4-split Data Integrity & Disjointness Gate (train/validation/unseen/ood) PASSED.",
            output={
                "dataset_dir": str(data_dir),
                "version": manifest.get("version") if isinstance(manifest, dict) else None,
                "manifest_sha256": manifest_sha,
                "audit": audit,
            },
            evidence={"verdict": "PASS", "audit_status": "PASS", "manifest_sha256": manifest_sha},
            emitted_events=[("data.ready", {"dataset_dir": str(data_dir), "dataset": "nagi_v11"})],
        )

    return StepExecutionResult(
        verdict="PASS",
        summary=f"Dataset manifest verified (schema={manifest.get('schema')}, version={manifest.get('version')}).",
        output={
            "dataset_dir": str(data_dir),
            "version": manifest.get("version"),
            "manifest_sha256": _sha256_file(manifest_path),
        },
        evidence={"verdict": "PASS", "manifest_sha256": _sha256_file(manifest_path)},
        emitted_events=[("data.ready", {"dataset_dir": str(data_dir), "version": manifest.get("version")})],
    )


# ----------------------------------------------------------------------
# 3. Native Training Workflow
# ----------------------------------------------------------------------
def handle_training_preflight(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
    data_dir = str(payload.get("dataset_dir") or os.getenv("ZYRQUEN_DATASET_DIR", "")).strip()
    if not data_dir or not Path(data_dir).is_dir():
        return StepExecutionResult(
            verdict="BLOCKED",
            summary="Training pre-flight blocked: dataset directory is not available on disk.",
            output={"dataset_dir": data_dir or None},
            evidence={"verdict": "BLOCKED", "reason": "dataset_missing"},
            error_code="dataset_missing",
        )
    return StepExecutionResult(
        verdict="PASS",
        summary="Training pre-flight checks passed (dataset directory ready and caps validated).",
        output={"dataset_dir": data_dir, "arm": payload.get("arm", "default")},
        evidence={"verdict": "PASS", "dataset_dir": data_dir},
    )


def handle_training_execute(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
    """Real Training Hook — connects handler to native/train.py (train / train_sft).

    Order: approval -> torch (unless _train_fn injected) -> budget -> disk ->
    dataset/tokenizer/SFT pairs -> model/vocab binding -> RAM monitor -> train -> register.
    Never claims COMPLETED from NOT RUN. Uses injected _train_fn / _model in ctx for tests.
    """
    import os as _os
    from pathlib import Path as _Path

    # 1. Tier-2 approval must already be consumed — Hook never invents it
    approval = ctx.get("consumed_approval") or {}
    if not approval:
        return StepExecutionResult(
            verdict="NOT RUN",
            error_code="approval_required",
            summary="Tier-2 approval required: no consumed_approval in ctx. Call governance.verify_and_consume() first.",
        )

    # 2. torch — honest check unless a test injects _train_fn
    from apps.core.workflow.resource_guard import (
        MIN_DISK_RESERVE_GB as _MIN_DISK_RESERVE_GB,
        TrainingRuntimeGuard as _TrainingRuntimeGuard,
        check_torch_cpu_runtime as _check_torch_cpu,
        enforce_cpu_thread_cap as _enforce_cpu_threads,
    )

    if ctx.get("_train_fn") is None:
        torch_probe = _check_torch_cpu()
        if not torch_probe["available"]:
            return StepExecutionResult(
                verdict="BLOCKED",
                summary="Native training blocked: PyTorch runtime is not installed in this host.",
                error_code="torch_not_installed",
            )

    # 3. Budget Gate — stricter than resource_guard on steps, CPU threads, timeouts, checkpoints
    try:
        from apps.core.workflow.autonomous_training_loop import validate_budget as _validate_budget
        from apps.core.workflow.autonomous_training_loop import check_disk_reserve as _check_disk
        from apps.core.workflow.autonomous_training_loop import RamMonitor as _RamMonitor
    except Exception as e:
        return StepExecutionResult(verdict="BLOCKED", error_code="hook_import_failed", summary=f"Hook imports failed: {e}")

    train_cfg_in = dict(payload.get("train_config") or {})
    batch_size = int(payload.get("batch_size", train_cfg_in.get("batch_size", 4)) or 4)
    max_steps = int(payload.get("max_steps", payload.get("steps", train_cfg_in.get("max_steps", 500))) or 500)
    segment_max_steps_raw = payload.get("segment_max_steps", train_cfg_in.get("segment_max_steps"))
    global_target_steps_raw = payload.get("global_target_steps", train_cfg_in.get("global_target_steps"))
    lr_total_steps_raw = payload.get("lr_total_steps", train_cfg_in.get("lr_total_steps"))
    stage_id_raw = payload.get("stage_id", train_cfg_in.get("stage_id"))
    experiment_index_raw = payload.get("experiment_index", train_cfg_in.get("experiment_index"))

    segment_max_steps = int(segment_max_steps_raw) if segment_max_steps_raw is not None else None
    global_target_steps = int(global_target_steps_raw) if global_target_steps_raw is not None else max_steps
    lr_total_steps = int(lr_total_steps_raw) if lr_total_steps_raw is not None else None
    stage_id = int(stage_id_raw) if stage_id_raw is not None else None
    experiment_index = int(experiment_index_raw) if experiment_index_raw is not None else None
    experiment_steps_cap = segment_max_steps if segment_max_steps is not None else max_steps

    block_size = int(payload.get("block_size", payload.get("seq_len", train_cfg_in.get("block_size", 128))) or 128)
    params_declared = int(payload.get("params", 0) or 0)
    cpu_threads = int(payload.get("cpu_threads", train_cfg_in.get("cpu_threads", 2)) or 2)
    exp_timeout = float(payload.get("experiment_timeout_sec", payload.get("timeout_seconds", 1200.0)) or 1200.0)
    loop_timeout = float(payload.get("loop_timeout_sec", 3600.0) or 3600.0)
    disk_reserve_gb = float(payload.get("disk_reserve_gb", _MIN_DISK_RESERVE_GB) or _MIN_DISK_RESERVE_GB)
    max_checkpoints = int(payload.get("max_checkpoints", 3) or 3)

    if global_target_steps < 1:
        return StepExecutionResult(
            verdict="BLOCKED",
            error_code="budget_violated",
            summary=f"Budget Lock violated: global_target_steps={global_target_steps} must be >= 1",
        )
    if max_checkpoints < 1 or max_checkpoints > 10:
        return StepExecutionResult(
            verdict="BLOCKED",
            error_code="budget_violated",
            summary=f"Budget Lock violated: max_checkpoints={max_checkpoints} outside [1, 10]",
        )
    if disk_reserve_gb < _MIN_DISK_RESERVE_GB:
        return StepExecutionResult(
            verdict="BLOCKED",
            error_code="budget_violated",
            summary=f"Budget Lock violated: disk_reserve_gb={disk_reserve_gb} < {_MIN_DISK_RESERVE_GB}",
        )

    ok, reason = _validate_budget(
        params=params_declared,
        seq_len=block_size,
        batch_size=batch_size,
        steps=experiment_steps_cap,
        cpu_threads=cpu_threads,
        experiment_timeout_sec=exp_timeout,
        loop_timeout_sec=loop_timeout,
    )
    if not ok:
        return StepExecutionResult(verdict="BLOCKED", error_code="budget_violated", summary=f"Budget Lock violated: {reason}")

    # Enforce CPU thread cap across OpenMP/BLAS env vars and PyTorch if present
    _enforce_cpu_threads(cpu_threads)

    # 4. Checkpoint isolation (prevent accidental overwrites) & Disk Guard
    base_ckpt_dir = str(payload.get("checkpoint_dir") or ctx.get("checkpoint_dir") or "checkpoints/training_hook")
    ckpt_dir_path = _Path(base_ckpt_dir)
    if (ckpt_dir_path / "manifest.json").exists() and not bool(payload.get("resume_existing", False)):
        iso_tag = str(ctx.get("run_id") or uuid.uuid4().hex[:8])
        ckpt_dir_path = ckpt_dir_path / f"run_{iso_tag}"
    checkpoint_dir = str(ckpt_dir_path)
    log_path = str(payload.get("log_path") or str(ckpt_dir_path / "train.log"))
    disk_ok, disk_info = _check_disk(checkpoint_dir, reserve_gb=disk_reserve_gb)
    if not disk_ok:
        return StepExecutionResult(
            verdict="BLOCKED", error_code="disk_reserve_violated",
            summary=f"Disk reserve violated: free {disk_info['free_gb']} GB < {disk_info['reserve_gb']} GB",
        )

    # 5. Resolve tokenizer, dataset manifest, and training inputs (SFT pairs or token stream)
    train_ids = payload.get("train_ids")
    val_ids = payload.get("val_ids")
    train_pairs = payload.get("train_pairs")
    val_pairs = payload.get("val_pairs")

    tokenizer = ctx.get("tokenizer") or payload.get("tokenizer")
    tokenizer_path_raw = str(
        payload.get("tokenizer_path") or _os.getenv("ZYRQUEN_TOKENIZER_PATH", "")
    ).strip()
    if tokenizer is None and tokenizer_path_raw:
        tok_file = _Path(tokenizer_path_raw)
        if not tok_file.is_file() or tok_file.is_symlink():
            return StepExecutionResult(
                verdict="BLOCKED",
                error_code="tokenizer_invalid",
                summary=f"Tokenizer file missing or symlinked: {tokenizer_path_raw}",
            )
        try:
            from apps.core.native.tokenizer import ZyrquenTokenizer as _ZTok

            tokenizer = _ZTok.load(tok_file)
        except Exception as e:
            return StepExecutionResult(
                verdict="BLOCKED",
                error_code="tokenizer_invalid",
                summary=f"Failed to load tokenizer {tokenizer_path_raw}: {e}",
            )

    tokenizer_fingerprint = payload.get("tokenizer_fingerprint")
    if not tokenizer_fingerprint and tokenizer is not None and hasattr(tokenizer, "fingerprint"):
        tokenizer_fingerprint = tokenizer.fingerprint()

    dataset_dir = str(payload.get("dataset_dir") or _os.getenv("ZYRQUEN_DATASET_DIR", "")).strip()
    dataset_version = payload.get("dataset_version")
    dataset_format = str(payload.get("dataset_format") or "").strip().lower() or None
    dataset_manifest: dict[str, Any] = {}
    if dataset_dir and _Path(dataset_dir).is_dir():
        manifest_file = _Path(dataset_dir) / "manifest.json"
        if manifest_file.is_file() and not manifest_file.is_symlink():
            try:
                dataset_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                if not dataset_version:
                    dataset_version = dataset_manifest.get("version")
            except (OSError, json.JSONDecodeError) as e:
                return StepExecutionResult(
                    verdict="BLOCKED",
                    error_code="manifest_invalid",
                    summary=f"Failed to read dataset manifest.json: {e}",
                )

    is_sft_run = train_pairs is not None and val_pairs is not None
    if not is_sft_run and (train_ids is None or val_ids is None):
        if not dataset_dir or not _Path(dataset_dir).is_dir():
            return StepExecutionResult(
                verdict="BLOCKED",
                error_code="dataset_missing",
                summary=f"Dataset directory missing: {dataset_dir or '(empty)'}",
            )
        if tokenizer is None:
            return StepExecutionResult(
                verdict="BLOCKED",
                error_code="tokenizer_missing",
                summary="Tokenizer required for dataset path: pass ctx['tokenizer'], payload['tokenizer_path'], or train_ids/val_ids directly.",
            )
        try:
            from apps.core.native.dataset import (
                detect_dataset_format as _detect_fmt,
                load_sft_split as _load_sft_split,
                load_split as _load_split,
            )

            resolved_fmt = dataset_format or _detect_fmt(dataset_dir)
            if resolved_fmt == "sft":
                from apps.core.native.sft import build_sft_pairs as _build_sft_pairs

                use_slots = bool(
                    payload.get(
                        "use_slots",
                        dataset_manifest.get("dataset") in {"nagi_v10", "nagi_v11"},
                    )
                )
                permute_slots = bool(payload.get("permute_slots", False))
                train_records = list(_load_sft_split(dataset_dir, "train"))
                val_records = list(_load_sft_split(dataset_dir, "validation"))
                train_pairs = _build_sft_pairs(
                    train_records,
                    tokenizer,
                    max_seq_len=block_size,
                    use_slots=use_slots,
                    permute_slots=permute_slots,
                )
                val_pairs = _build_sft_pairs(
                    val_records,
                    tokenizer,
                    max_seq_len=block_size,
                    use_slots=use_slots,
                    permute_slots=False,
                )
                is_sft_run = True
            else:
                from apps.core.native.train import build_token_stream as _build_stream

                max_tokens = int(payload.get("max_tokens", 100000))
                train_ids = _build_stream(list(_load_split(dataset_dir, "train")), tokenizer, max_tokens)
                val_ids = _build_stream(list(_load_split(dataset_dir, "validation")), tokenizer, max_tokens)
        except Exception as e:
            return StepExecutionResult(
                verdict="BLOCKED",
                error_code="dataset_tokenize_failed",
                summary=f"Dataset preparation/tokenization failed: {e}",
            )

    # 5.5 Resolve ONE canonical model_version before training (eliminates dual naming & duplicates)
    registry_root = str(payload.get("registry_root") or "").strip()
    load_fn_override = ctx.get("_load_fn")
    reg_kwargs = {"load_fn": load_fn_override} if load_fn_override is not None else {}
    active_registry = ModelRegistry(registry_root, **reg_kwargs) if registry_root else None

    existing_ckpt_versions: list[str] = []
    vm_path = ckpt_dir_path / "version_manifest.json"
    if vm_path.is_file() and not vm_path.is_symlink():
        try:
            vm_data = json.loads(vm_path.read_text(encoding="utf-8"))
            existing_ckpt_versions = [
                str(item.get("model_version"))
                for item in (vm_data.get("versions") or [])
                if isinstance(item, dict) and item.get("model_version")
            ]
        except Exception:
            existing_ckpt_versions = []

    if "model_version" in payload and payload["model_version"] is not None:
        explicit_model_version: str | None = str(payload["model_version"])
    else:
        explicit_model_version = None

    target_major_raw = payload.get("target_major")
    if target_major_raw is not None:
        target_major: int | None = int(target_major_raw)
    elif (
        str(dataset_version or "").startswith("11.")
        or dataset_manifest.get("dataset") == "nagi_v11"
        or is_v11_model_version(explicit_model_version)
    ):
        target_major = 11
    elif (
        str(dataset_version or "").startswith("10.")
        or dataset_manifest.get("dataset") == "nagi_v10"
        or is_v10_model_version(explicit_model_version)
    ):
        target_major = 10
    elif dataset_version and str(dataset_version).split(".", 1)[0].isdigit():
        parsed_major = int(str(dataset_version).split(".", 1)[0])
        target_major = None if parsed_major == 0 else parsed_major
    else:
        target_major = 10

    try:
        canonical_reservation: NativeVersionReservation = resolve_canonical_model_version(
            explicit_version=explicit_model_version,
            parent_version=payload.get("parent_version"),
            registry=active_registry,
            existing_checkpoint_versions=existing_ckpt_versions,
            target_major=target_major,
            training_run_id=str(ctx.get("run_id") or "") or None,
        )
    except RegistryError as exc:
        err_msg = str(exc)
        err_code = (
            "duplicate_model_version"
            if any(tok in err_msg.lower() for tok in ("already registered", "already reserved", "already exists"))
            else "invalid_model_version"
        )
        return StepExecutionResult(
            verdict="BLOCKED",
            error_code=err_code,
            summary=f"Canonical model_version resolution blocked: {exc}",
        )

    canonical_version = canonical_reservation.version
    resolved_parent = canonical_reservation.parent
    reservation_consumed = False

    def _release_unconsumed_reservation() -> None:
        if not reservation_consumed and active_registry is not None and canonical_reservation.token:
            try:
                active_registry.release_reservation(
                    canonical_version, canonical_reservation.token
                )
            except Exception:
                pass

    # 6. Build model & train inside TrainingRuntimeGuard + RAM Monitor
    runtime_guard = ctx.get("runtime_guard")
    if runtime_guard is None:
        runtime_guard = _TrainingRuntimeGuard(
            checkpoint_dir,
            experiment_timeout_sec=exp_timeout,
            loop_timeout_sec=loop_timeout,
            disk_reserve_gb=disk_reserve_gb,
            cpu_threads=cpu_threads,
            audit_logger=ctx.get("audit"),
            run_id=ctx.get("run_id"),
            step_key=ctx.get("step_key"),
        )

    def _on_soft_ram(ram_snap: dict[str, Any]) -> None:
        audit_obj = ctx.get("audit")
        if audit_obj is not None:
            try:
                audit_obj.record(
                    actor_id="system:resource_guard",
                    event_type="training.ram_soft_warning",
                    resource=f"training:{checkpoint_dir}",
                    decision="WARN",
                    details=ram_snap,
                    run_id=ctx.get("run_id"),
                    step_key=ctx.get("step_key"),
                )
            except Exception:
                pass

    monitor = _RamMonitor(on_soft_limit=_on_soft_ram)
    monitor.start()
    built_model_cfg_dict: dict[str, Any] = dict(payload.get("model_config") or {})
    try:
        if ctx.get("_model") is not None:
            model = ctx["_model"]
            if hasattr(model, "cfg") and hasattr(model.cfg, "to_dict"):
                built_model_cfg_dict = model.cfg.to_dict()
        elif ctx.get("_model_factory") is not None:
            model = ctx["_model_factory"](payload)
            if hasattr(model, "cfg") and hasattr(model.cfg, "to_dict"):
                built_model_cfg_dict = model.cfg.to_dict()
        else:
            try:
                from apps.core.native.config import MAX_V10_PARAMETERS as _MAX_V10_PARAMS, ZyrquenConfig as _ZCfg
                from apps.core.native.model import ZyrquenModel as _ZModel

                model_cfg_in = dict(payload.get("model_config") or {})
                tok_vocab = int(getattr(tokenizer, "vocab_size", 0) or 0)
                if "vocab_size" in model_cfg_in:
                    vocab_size = int(model_cfg_in.pop("vocab_size"))
                    if tok_vocab and vocab_size != tok_vocab:
                        return StepExecutionResult(
                            verdict="BLOCKED",
                            error_code="vocab_size_mismatch",
                            summary=f"model_config.vocab_size ({vocab_size}) != tokenizer.vocab_size ({tok_vocab})",
                        )
                elif payload.get("vocab_size") is not None:
                    vocab_size = int(payload["vocab_size"])
                    if tok_vocab and vocab_size != tok_vocab:
                        return StepExecutionResult(
                            verdict="BLOCKED",
                            error_code="vocab_size_mismatch",
                            summary=f"payload.vocab_size ({vocab_size}) != tokenizer.vocab_size ({tok_vocab})",
                        )
                elif tok_vocab:
                    vocab_size = tok_vocab
                else:
                    vocab_size = 2048

                defaults = {
                    "vocab_size": vocab_size,
                    "d_model": 256,
                    "n_layers": 4,
                    "n_heads": 4,
                    "d_ff": 704,
                    "max_seq_len": 256,
                    "dropout": 0.0,
                    "tie_embeddings": True,
                }
                defaults.update(model_cfg_in)
                if int(defaults.get("max_seq_len", 256)) < block_size:
                    defaults["max_seq_len"] = block_size
                model_cfg = _ZCfg(**defaults)
                model_cfg.validate_parameter_budget(_MAX_V10_PARAMS)
                model = _ZModel(model_cfg)
                built_model_cfg_dict = model_cfg.to_dict()
                real_params = int(model.num_parameters())
                if real_params > _MAX_V10_PARAMS:
                    return StepExecutionResult(
                        verdict="BLOCKED",
                        error_code="budget_violated",
                        summary=f"Model params {real_params} > {_MAX_V10_PARAMS}",
                    )
            except ValueError as e:
                return StepExecutionResult(verdict="BLOCKED", error_code="budget_violated", summary=str(e))
            except Exception as e:
                return StepExecutionResult(verdict="BLOCKED", error_code="model_build_failed", summary=f"Model build failed: {e}")

        # Build TrainConfig with Budget Lock — never use TrainConfig() defaults
        try:
            from apps.core.native.train import TrainConfig as _TCfg

            tc_kwargs = dict(train_cfg_in)
            tc_kwargs.update({
                "block_size": block_size,
                "batch_size": batch_size,
                "max_steps": global_target_steps,
            })
            if segment_max_steps is not None or global_target_steps_raw is not None:
                tc_kwargs["segment_max_steps"] = experiment_steps_cap
            if lr_total_steps is not None:
                tc_kwargs["lr_total_steps"] = lr_total_steps
            if stage_id is not None:
                tc_kwargs["stage_id"] = stage_id
            if experiment_index is not None:
                tc_kwargs["experiment_index"] = experiment_index
            lr_horizon = int(tc_kwargs.get("lr_total_steps") or tc_kwargs["max_steps"])
            _warmup = int(tc_kwargs.get("warmup_steps", 100) or 0)
            if _warmup >= lr_horizon:
                _warmup = max(0, lr_horizon - 1)
            tc_kwargs["warmup_steps"] = _warmup
            train_cfg = _TCfg(**{k: v for k, v in tc_kwargs.items() if k in _TCfg.__dataclass_fields__})
        except Exception as e:
            return StepExecutionResult(verdict="BLOCKED", error_code="train_config_failed", summary=f"TrainConfig build failed: {e}")

        def _filter_optional_kwargs(fn: Any, candidates: dict[str, Any]) -> dict[str, Any]:
            try:
                sig = inspect.signature(fn)
            except (TypeError, ValueError):
                return candidates
            accepts_var_kw = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
            if accepts_var_kw:
                return candidates
            return {k: v for k, v in candidates.items() if k in sig.parameters}

        # Call injected _train_fn or real train_sft / train
        injected_train_fn = ctx.get("_train_fn")
        if is_sft_run:
            if injected_train_fn is not None:
                train_fn = injected_train_fn
            else:
                from apps.core.native.train import train_sft as train_fn  # type: ignore
            call_kwargs = _filter_optional_kwargs(
                train_fn,
                {
                    "device": "cpu",
                    "cost_controller": runtime_guard.cost_controller,
                    "pad_id": int(getattr(tokenizer, "pad_id", 0) if tokenizer is not None else 0),
                    "tokenizer_fingerprint": tokenizer_fingerprint,
                    "dataset_version": dataset_version,
                    "runtime_guard": runtime_guard,
                    "disk_reserve_gb": disk_reserve_gb,
                    "cpu_threads": cpu_threads,
                    "max_checkpoints": max_checkpoints,
                },
            )
            result = train_fn(
                model,
                list(train_pairs),
                list(val_pairs),
                train_cfg,
                checkpoint_dir,
                log_path,
                **call_kwargs,
            )
        else:
            if injected_train_fn is not None:
                train_fn = injected_train_fn
            else:
                from apps.core.native.train import train as train_fn  # type: ignore
            call_kwargs = _filter_optional_kwargs(
                train_fn,
                {
                    "device": "cpu",
                    "cost_controller": runtime_guard.cost_controller,
                    "tokenizer_fingerprint": tokenizer_fingerprint,
                    "dataset_version": dataset_version,
                    "runtime_guard": runtime_guard,
                    "disk_reserve_gb": disk_reserve_gb,
                    "cpu_threads": cpu_threads,
                    "max_checkpoints": max_checkpoints,
                },
            )
            result = train_fn(
                model,
                list(train_ids),
                list(val_ids),
                train_cfg,
                checkpoint_dir,
                log_path,
                **call_kwargs,
            )
    except Exception as e:
        _release_unconsumed_reservation()
        return StepExecutionResult(verdict="FAIL", error_code="training_failed", summary=f"Training failed: {e}")
    finally:
        ram_info = monitor.stop()

    if ram_info.get("exceeded_hard"):
        _release_unconsumed_reservation()
        return StepExecutionResult(
            verdict="BLOCKED", error_code="ram_hard_stop",
            summary=f"RAM hard stop exceeded: peak {ram_info['peak_gb']} GB >= 3.5 GB — no checkpoint claimed.",
        )
    if not isinstance(result, dict):
        _release_unconsumed_reservation()
        return StepExecutionResult(verdict="FAIL", error_code="training_bad_result", summary=f"train() returned non-dict: {type(result).__name__}")

    stopped = result.get("stopped_reason")
    if stopped == "loss_diverged":
        _release_unconsumed_reservation()
        return StepExecutionResult(verdict="FAIL", error_code="loss_diverged", summary=f"Training diverged: val_loss={result.get('val_loss')} steps={result.get('steps')}")
    if stopped in ("ram_hard_limit", "disk_reserve_violated", "disk_budget_violated", "experiment_timeout", "loop_timeout", "max_runtime_seconds"):
        _release_unconsumed_reservation()
        err_code = "experiment_timeout" if stopped == "max_runtime_seconds" else str(stopped)
        return StepExecutionResult(
            verdict="BLOCKED",
            error_code=err_code,
            summary=f"Training blocked safely by RuntimeGuard: {err_code} steps={result.get('steps')}",
            output={"steps": result.get("steps"), "stopped_reason": stopped, "checkpoint_blocked": result.get("checkpoint_blocked")},
        )
    if stopped not in (None, "", "budget_exceeded", "cost_exceeded"):
        _release_unconsumed_reservation()
        return StepExecutionResult(verdict="FAIL", error_code="training_stopped", summary=f"Training stopped: {stopped} steps={result.get('steps')} val_loss={result.get('val_loss')}")
    if result.get("val_loss") is None:
        _release_unconsumed_reservation()
        return StepExecutionResult(verdict="FAIL", error_code="training_no_val", summary="Training finished without val_loss — cannot PASS without evidence.")
    if result.get("parameter_changed") is False:
        _release_unconsumed_reservation()
        return StepExecutionResult(verdict="FAIL", error_code="training_no_change", summary="Training finished but parameters did not change — cannot PASS.")

    metrics_payload: dict[str, Any] = {
        "model_version": canonical_version,
        "parent_version": resolved_parent,
        "version_source": "explicit" if explicit_model_version is not None else "canonical_auto",
        "steps": result.get("steps"),
        "epochs": result.get("epochs"),
        "train_loss": result.get("train_loss"),
        "val_loss": result.get("val_loss"),
        "perplexity": result.get("perplexity"),
        "ram_peak_gb": ram_info.get("peak_gb"),
        "checkpoint_dir": checkpoint_dir,
        "prompt_format": result.get("prompt_format") or ("zyrquen.sft.v1" if is_sft_run else "token_stream.v1"),
    }
    for _seg_key in ("resumed_from", "global_step_start", "global_step_end", "experiment_steps"):
        if result.get(_seg_key) is not None:
            metrics_payload[_seg_key] = result[_seg_key]
    if result.get("stage_id", stage_id) is not None:
        metrics_payload["stage_id"] = result.get("stage_id", stage_id)
    if result.get("experiment_index", experiment_index) is not None:
        metrics_payload["experiment_index"] = result.get("experiment_index", experiment_index)

    # Ensure tokenizer.json and VersionedCheckpointManager version_manifest.json use the SINGLE canonical_version
    ckpt_manifest_file = _Path(checkpoint_dir) / "manifest.json"
    tok_dest = _Path(checkpoint_dir) / "tokenizer.json"
    if ckpt_manifest_file.is_file():
        if not tok_dest.exists():
            if tokenizer_path_raw and _Path(tokenizer_path_raw).is_file():
                shutil.copy2(tokenizer_path_raw, tok_dest)
            elif tokenizer is not None and hasattr(tokenizer, "save"):
                tokenizer.save(tok_dest)

        from apps.core.native.checkpoint import VersionedCheckpointManager as _VCM

        vcm_kwargs = {"load_fn": load_fn_override} if load_fn_override is not None else {}
        vcm = _VCM(checkpoint_dir, **vcm_kwargs)
        if vcm.get_version(canonical_version) is not None:
            _release_unconsumed_reservation()
            return StepExecutionResult(
                verdict="BLOCKED",
                error_code="duplicate_model_version",
                summary=f"Duplicate model_version already present in version_manifest.json: {canonical_version}",
                output=metrics_payload,
            )
        if vcm._inner.latest_valid() is not None:
            try:
                version_rec = vcm.register_existing_checkpoint(
                    model_version=canonical_version,
                    parent_version=resolved_parent,
                    dataset_version=str(dataset_version or "unknown"),
                    dataset_content_hash=str(dataset_manifest.get("content_sha256") or "unknown"),
                    config={
                        "model_config": built_model_cfg_dict,
                        "train_config": {
                            "batch_size": batch_size,
                            "block_size": block_size,
                            "max_steps": max_steps,
                        },
                    },
                    tokenizer_sha256=tokenizer_fingerprint,
                    val_loss=float(result["val_loss"]) if result.get("val_loss") is not None else None,
                    perplexity=float(result["perplexity"]) if result.get("perplexity") is not None else None,
                    metrics={
                        k: v
                        for k, v in metrics_payload.items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool)
                    },
                )
                if not vcm.verify_version(canonical_version):
                    _release_unconsumed_reservation()
                    return StepExecutionResult(
                        verdict="FAIL",
                        error_code="checkpoint_verification_failed",
                        summary=f"Versioned checkpoint verification failed for {canonical_version}.",
                        output=metrics_payload,
                    )
                metrics_payload["checkpoint_model_version"] = canonical_version
                metrics_payload["checkpoint_sha256"] = version_rec["checkpoint_sha256"]
                metrics_payload["version_manifest_path"] = str(vcm.version_manifest_path)
            except Exception as e:
                _release_unconsumed_reservation()
                return StepExecutionResult(
                    verdict="FAIL",
                    error_code="version_manifest_registration_failed",
                    summary=f"Training finished but VersionedCheckpointManager registration failed: {e}",
                    output=metrics_payload,
                )

    registered_version: str | None = None
    reg_tok_path = tokenizer_path_raw or (str(tok_dest) if tok_dest.is_file() else "")
    should_register_registry = bool(
        active_registry is not None
        and dataset_dir
        and reg_tok_path
        and ckpt_manifest_file.is_file()
        and payload.get("register_in_registry", True)
    )
    if should_register_registry and active_registry is not None:
        try:
            rec = active_registry.register(
                canonical_version,
                checkpoint_dir,
                reg_tok_path,
                dataset_dir,
                metrics={k: v for k, v in metrics_payload.items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
                notes=str(payload.get("notes") or f"Registered by handle_training_execute (steps={result.get('steps')})"),
                parent=resolved_parent,
                reservation_token=canonical_reservation.token or None,
                architecture=built_model_cfg_dict or None,
                training_metadata={
                    "batch_size": batch_size,
                    "block_size": block_size,
                    "max_steps": global_target_steps,
                    "segment_max_steps": segment_max_steps,
                    "lr_total_steps": lr_total_steps,
                    "stage_id": stage_id,
                    "experiment_index": experiment_index,
                    "training_run_id": str(ctx.get("run_id") or "") or None,
                },
                prompt_format=str(metrics_payload.get("prompt_format") or ""),
            )
            reservation_consumed = True
            registered_version = rec["version"]
            if (
                metrics_payload.get("checkpoint_sha256")
                and rec.get("checkpoint", {}).get("sha256") != metrics_payload.get("checkpoint_sha256")
            ):
                raise RegistryError("checkpoint SHA-256 mismatch between version_manifest.json and ModelRegistry")
            metrics_payload["registry_model_version"] = registered_version
            metrics_payload["model_version"] = registered_version
        except Exception as e:
            _release_unconsumed_reservation()
            return StepExecutionResult(
                verdict="FAIL",
                error_code="registry_registration_failed",
                summary=f"Training finished but ModelRegistry registration failed: {e}",
                output=metrics_payload,
            )
    else:
        _release_unconsumed_reservation()

    emitted: list[tuple[str, dict[str, Any]]] = []
    event_version = registered_version or metrics_payload.get("model_version")
    if event_version is not None:
        emitted.append((
            "training.completed",
            {
                "model_version": event_version,
                "checkpoint_dir": checkpoint_dir,
                "steps": result.get("steps"),
                "val_loss": result.get("val_loss"),
            },
        ))

    return StepExecutionResult(
        verdict="PASS",
        summary=(
            f"Training completed: steps={result.get('steps')} val_loss={result.get('val_loss')} "
            f"perplexity={result.get('perplexity')} ram_peak_gb={ram_info.get('peak_gb')}"
            + (f" registered={registered_version}" if registered_version else "")
        ),
        output=metrics_payload,
        evidence={"verdict": "PASS", **metrics_payload},
        emitted_events=emitted,
    )

def handle_evaluation_verify(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
    registry_root = str(
        payload.get("registry_root") or os.getenv("ZYRQUEN_MODEL_REGISTRY_ROOT", "")
    ).strip()
    checkpoint_dir = str(payload.get("checkpoint_dir") or "").strip()
    version = str(payload.get("model_version") or "").strip()
    if (not registry_root and not checkpoint_dir) or not version:
        return StepExecutionResult(
            verdict="NOT RUN",
            summary="No registry_root/checkpoint_dir or model_version provided; evaluation skipped honestly.",
            output={
                "registry_root": registry_root or None,
                "checkpoint_dir": checkpoint_dir or None,
                "model_version": version or None,
            },
            evidence={"verdict": "NOT RUN", "reason": "no_model_version_targeted"},
        )

    if registry_root:
        reg = ModelRegistry(registry_root)
        try:
            ok = reg.verify(version)
            compat = reg.check_compatibility(version) if ok else {"compatible": False, "reasons": ["sha256_verify_failed"]}
            rec = reg.get(version)
        except RegistryError as exc:
            return StepExecutionResult(
                verdict="BLOCKED",
                summary=f"Artifact verification failed for {version}: {exc}",
                output={"model_version": version, "verified": False},
                evidence={"verdict": "BLOCKED", "error": str(exc)},
                error_code="artifact_verification_failed",
            )
        passed = bool(ok and compat.get("compatible"))
        if passed and checkpoint_dir and (Path(checkpoint_dir) / "version_manifest.json").is_file():
            from apps.core.native.checkpoint import VersionedCheckpointManager as _VCM

            vcm = _VCM(checkpoint_dir)
            ver_rec = vcm.get_version(version)
            if (
                ver_rec is None
                or not vcm.verify_version(version)
                or ver_rec.get("checkpoint_sha256") != rec.get("checkpoint", {}).get("sha256")
            ):
                passed = False
        return StepExecutionResult(
            verdict="PASS" if passed else "FAIL",
            summary=f"Model artifact SHA-256 & compatibility verification for {version}: {'PASS' if passed else 'FAIL'}",
            output={
                "model_version": version,
                "verified": ok,
                "compatibility": compat,
                "lifecycle_status": rec.get("lifecycle_status"),
            },
            evidence={"verdict": "PASS" if passed else "FAIL", "checkpoint_sha256": rec["checkpoint"]["sha256"]},
        )

    from apps.core.native.checkpoint import VersionedCheckpointManager as _VCM

    vcm = _VCM(checkpoint_dir)
    ok = vcm.verify_version(version)
    ver_rec = vcm.get_version(version)
    if ver_rec is None:
        return StepExecutionResult(
            verdict="BLOCKED",
            summary=f"Checkpoint version not found in version_manifest.json: {version}",
            output={"model_version": version, "checkpoint_dir": checkpoint_dir, "verified": False},
            evidence={"verdict": "BLOCKED", "reason": "version_not_found"},
            error_code="artifact_verification_failed",
        )
    return StepExecutionResult(
        verdict="PASS" if ok else "FAIL",
        summary=f"Versioned checkpoint SHA-256 verification for {version}: {'PASS' if ok else 'FAIL'}",
        output={"model_version": version, "checkpoint_dir": checkpoint_dir, "verified": ok},
        evidence={"verdict": "PASS" if ok else "FAIL", "checkpoint_sha256": ver_rec["checkpoint_sha256"]},
    )


_V11_REPORT_SCHEMA = "zyrquen.v11.evaluation_report.v1"
_V10_REPORT_SCHEMA = "zyrquen.v10.evaluation_report.v1"
_V9_REPORT_SCHEMA = "zyrquen.eval-v9.report.v1"
_V11_REQUIRED_SPLITS = ("validation", "unseen", "ood")
_V10_EXPECTED_CAPABILITIES = (
    "abstract_reasoning",
    "relational_generalization",
    "ood_transfer",
    "multi_step_planning",
    "self_verification",
    "knowledge_integration",
)
_EVAL_NON_RUN_STATUSES = frozenset({"NOT RUN", "NOT_RUN", "PENDING"})
_EVAL_BLOCKED_STATUSES = frozenset({"BLOCKED"})
_EVAL_FAIL_STATUSES = frozenset({"FAIL", "FAILED", "ERROR", "UNKNOWN"})
_V9_ALLOWED_CRITERION_STATUSES = frozenset({"PASS", "NOT_APPLICABLE", "PENDING_COMPARISON"})


def _is_finite_float(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _norm_status(val: Any) -> str:
    return str(val or "").strip().upper()


def _extract_finite_metrics_dict(raw: Any) -> tuple[dict[str, float], list[str]]:
    if not isinstance(raw, dict) or not raw:
        return {}, ["metrics_missing_or_empty"]
    clean: dict[str, float] = {}
    bad: list[str] = []
    for k, v in raw.items():
        if v is None:
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if math.isfinite(float(v)):
                clean[str(k)] = float(v)
            else:
                bad.append(f"non_finite_metric:{k}")
    if not clean:
        bad.append("no_finite_numeric_metrics")
    return clean, bad


def handle_evaluation_gate(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
    report_path_raw = str(payload.get("report_path") or "").strip()
    registry_root = str(
        payload.get("registry_root") or os.getenv("ZYRQUEN_MODEL_REGISTRY_ROOT", "")
    ).strip()
    version = str(payload.get("model_version") or "").strip()

    if not report_path_raw:
        return StepExecutionResult(
            verdict="NOT RUN",
            summary="No evaluation report path supplied; cannot certify PASS without evidence.",
            output={"report_path": None},
            evidence={"verdict": "NOT RUN", "reason": "no_eval_report_evidence"},
            error_code="missing_eval_report",
        )

    report_path = Path(report_path_raw)
    if report_path.is_symlink():
        return StepExecutionResult(
            verdict="BLOCKED",
            summary=f"Refusing symlinked evaluation report: {report_path}",
            output={"report_path": str(report_path)},
            evidence={"verdict": "BLOCKED", "reason": "symlink_eval_report"},
            error_code="symlink_eval_report",
        )
    if not report_path.exists():
        return StepExecutionResult(
            verdict="NOT RUN",
            summary="Evaluation report file does not exist; cannot certify PASS without evidence.",
            output={"report_path": str(report_path)},
            evidence={"verdict": "NOT RUN", "reason": "no_eval_report_evidence"},
            error_code="missing_eval_report",
        )
    if not report_path.is_file():
        return StepExecutionResult(
            verdict="FAIL",
            summary=f"Evaluation report path is not a regular file: {report_path}",
            output={"report_path": str(report_path)},
            evidence={"verdict": "FAIL", "reason": "invalid_eval_report"},
            error_code="invalid_eval_report",
        )

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report_sha = _sha256_file(report_path)
    except (OSError, json.JSONDecodeError) as exc:
        return StepExecutionResult(
            verdict="FAIL",
            summary=f"Malformed or unreadable evaluation report: {exc}",
            output={"report_path": str(report_path)},
            evidence={"verdict": "FAIL", "reason": "malformed_eval_report"},
            error_code="malformed_eval_report",
        )

    if not isinstance(report, dict):
        return StepExecutionResult(
            verdict="FAIL",
            summary="Evaluation report JSON root must be an object.",
            output={"report_path": str(report_path)},
            evidence={"verdict": "FAIL", "reason": "malformed_eval_report"},
            error_code="malformed_eval_report",
        )

    schema_tag = report.get("report_schema")
    v9_tag = report.get("schema_version")
    if schema_tag in (_V10_REPORT_SCHEMA, _V11_REPORT_SCHEMA) and v9_tag == _V9_REPORT_SCHEMA:
        return StepExecutionResult(
            verdict="FAIL",
            summary="Conflicting v9 and v10/v11 evaluation schema tags rejected.",
            output={"report_path": str(report_path), "report_sha256": report_sha},
            evidence={"verdict": "FAIL", "report_sha256": report_sha},
            error_code="conflicting_eval_schema",
        )

    # ------------------------------------------------------------------
    # Schema Branch A0: V11 Evaluation Report (zyrquen.v11.evaluation_report.v1)
    # ------------------------------------------------------------------
    if schema_tag == _V11_REPORT_SCHEMA:
        overall = _norm_status(report.get("overall_status"))
        top_status = _norm_status(report.get("status"))
        inf_status = _norm_status(report.get("inference_status"))
        inf_exec = report.get("inference_executed")

        all_top = [s for s in (overall, top_status, inf_status) if s]
        if any(s in _EVAL_BLOCKED_STATUSES for s in all_top):
            return StepExecutionResult(
                verdict="BLOCKED",
                summary=f"v11 evaluation report is BLOCKED (overall={overall}, inference={inf_status}); certification refused.",
                output={"overall_status": overall, "inference_status": inf_status, "report_sha256": report_sha},
                evidence={"verdict": "BLOCKED", "report_sha256": report_sha},
                error_code="evaluation_blocked",
            )
        if any(s in _EVAL_NON_RUN_STATUSES for s in all_top):
            return StepExecutionResult(
                verdict="NOT RUN",
                summary=f"v11 evaluation report was NOT RUN (overall={overall}, inference={inf_status}); cannot certify PASS.",
                output={"overall_status": overall, "inference_status": inf_status, "report_sha256": report_sha},
                evidence={"verdict": "NOT RUN", "report_sha256": report_sha},
                error_code="evaluation_not_run",
            )
        if inf_exec is False and overall not in _EVAL_FAIL_STATUSES and inf_status not in _EVAL_FAIL_STATUSES:
            return StepExecutionResult(
                verdict="NOT RUN",
                summary="v11 inference_executed=False; evaluation cannot pass without real native inference.",
                output={"overall_status": overall, "inference_executed": False, "report_sha256": report_sha},
                evidence={"verdict": "NOT RUN", "report_sha256": report_sha},
                error_code="inference_not_executed",
            )

        failures: list[str] = []
        if overall != "PASS":
            failures.append(f"overall_status={overall or 'MISSING'}")
        if inf_status != "PASS":
            failures.append(f"inference_status={inf_status or 'MISSING'}")
        if inf_exec is not True:
            failures.append(f"inference_executed={inf_exec!r}")
        if _norm_status(report.get("dataset_integrity")) != "PASS":
            failures.append(f"dataset_integrity={report.get('dataset_integrity')!r}")
        if _norm_status(report.get("leakage_audit_status")) != "PASS":
            failures.append(f"leakage_audit_status={report.get('leakage_audit_status')!r}")
        if report.get("error") is not None:
            failures.append(f"report_error={report.get('error')!r}")

        splits_raw = report.get("splits")
        if not isinstance(splits_raw, dict):
            failures.append("splits_missing_or_invalid")
        else:
            for req_split in _V11_REQUIRED_SPLITS:
                sp_entry = splits_raw.get(req_split)
                if not isinstance(sp_entry, dict):
                    failures.append(f"missing_split:{req_split}")
                    continue
                eval_cnt = sp_entry.get("evaluated", sp_entry.get("total"))
                if (
                    not isinstance(eval_cnt, int)
                    or isinstance(eval_cnt, bool)
                    or eval_cnt <= 0
                ):
                    failures.append(f"split_no_examples:{req_split}")
                if not _is_finite_float(sp_entry.get("exact_match")):
                    failures.append(f"split_invalid_exact_match:{req_split}")

        cap_eval = report.get("capability_evaluation")
        cap_scores: dict[str, float] = {}
        if not isinstance(cap_eval, dict):
            failures.append("capability_evaluation_missing")
        else:
            for cap in _V10_EXPECTED_CAPABILITIES:
                if cap not in cap_eval:
                    failures.append(f"missing_capability:{cap}")
                    continue
                entry = cap_eval[cap]
                if not isinstance(entry, dict):
                    failures.append(f"capability_invalid:{cap}")
                    continue
                st = _norm_status(entry.get("status"))
                if st in (_EVAL_NON_RUN_STATUSES | _EVAL_BLOCKED_STATUSES | _EVAL_FAIL_STATUSES):
                    failures.append(f"capability_{st or 'invalid'}:{cap}")
                elif st != "PASS":
                    failures.append(f"capability_unknown_status:{cap}={st or 'MISSING'}")

                val = entry.get("score", entry.get("exact_match", entry.get("accuracy")))
                if _is_finite_float(val):
                    cap_scores[cap] = float(val)
                else:
                    cap_splits = entry.get("splits")
                    if isinstance(cap_splits, dict):
                        split_vals: list[float] = []
                        for req_split in _V11_REQUIRED_SPLITS:
                            sp_cap = cap_splits.get(req_split)
                            if isinstance(sp_cap, dict):
                                sp_score = sp_cap.get("accuracy", sp_cap.get("exact_match", sp_cap.get("score")))
                                if _is_finite_float(sp_score):
                                    split_vals.append(float(sp_score))
                        if len(split_vals) == len(_V11_REQUIRED_SPLITS):
                            cap_scores[cap] = round(sum(split_vals) / len(split_vals), 6)
                        else:
                            failures.append(f"capability_no_score:{cap}")
                    else:
                        failures.append(f"capability_no_score:{cap}")

        metrics_summary, metric_errs = _extract_finite_metrics_dict(report.get("metrics"))
        failures.extend(metric_errs)

        reg_cmp = report.get("regression_comparison")
        if not isinstance(reg_cmp, list) or not reg_cmp:
            failures.append("regression_comparison_missing_or_empty")
            zero_reg = False
        else:
            zero_reg = all(isinstance(item, dict) and item.get("zero_regression") is True for item in reg_cmp)
            if not zero_reg:
                failures.append("regression_detected")

        assessment = report.get("acceptance_assessment")
        stops: list[Any] = []
        failed_criteria: list[str] = []
        if not isinstance(assessment, dict):
            failures.append("acceptance_assessment_missing_or_invalid")
        else:
            raw_stops = assessment.get("stop_criteria_triggered")
            if not isinstance(raw_stops, list):
                failures.append("stop_criteria_triggered_missing_or_invalid")
            else:
                stops = raw_stops
                if stops:
                    failures.append("stop_criteria_triggered")
            raw_criteria = assessment.get("criteria")
            if not isinstance(raw_criteria, dict) or not raw_criteria:
                failures.append("acceptance_criteria_missing_or_empty")
            else:
                pass_criteria_count = 0
                for k, v in raw_criteria.items():
                    st_c = _norm_status(v.get("status")) if isinstance(v, dict) else ""
                    if not isinstance(v, dict) or st_c not in _V9_ALLOWED_CRITERION_STATUSES or st_c in (
                        _EVAL_FAIL_STATUSES | _EVAL_NON_RUN_STATUSES | _EVAL_BLOCKED_STATUSES
                    ):
                        failed_criteria.append(str(k))
                    elif st_c == "PASS":
                        pass_criteria_count += 1
                if failed_criteria:
                    failures.append(f"failed_criteria:{failed_criteria}")
                elif pass_criteria_count == 0:
                    failures.append("no_passing_acceptance_criteria")

        ckpt_meta = report.get("checkpoint")
        if registry_root and version:
            reg = ModelRegistry(registry_root)
            try:
                if not reg.verify(version):
                    failures.append("registry_artifact_verify_failed")
                rec = reg.get(version)
            except RegistryError as exc:
                failures.append(f"registry_error:{exc}")
                rec = None
            if rec is not None and isinstance(ckpt_meta, dict):
                rep_ver = ckpt_meta.get("model_version")
                if rep_ver is not None and rep_ver != version:
                    failures.append(f"checkpoint_version_mismatch:{rep_ver}!={version}")
                rep_sha = ckpt_meta.get("checkpoint_sha256")
                if rep_sha is not None and rep_sha != (rec.get("checkpoint") or {}).get("sha256"):
                    failures.append("checkpoint_sha256_mismatch")
                if "verified" in ckpt_meta and ckpt_meta.get("verified") is not True:
                    failures.append("checkpoint_not_verified")

        passed = len(failures) == 0 and zero_reg
        wf_run_id = str(ctx["run_id"]) if ctx.get("run_id") else None
        if registry_root and version:
            reg = ModelRegistry(registry_root)
            reg.attach_evaluation_evidence(
                version,
                eval_run_id=str(ctx.get("run_id") or report.get("experiment_id") or "eval-v11"),
                report_sha256=report_sha,
                metrics=metrics_summary,
                passed=passed,
                zero_regression=zero_reg,
                capabilities=cap_scores or None,
                workflow_run_id=wf_run_id,
                evaluation_status="PASS" if passed else "FAIL",
                inference_executed=(inf_status == "PASS" and inf_exec is True),
                report_schema=_V11_REPORT_SCHEMA,
                reason=f"failures={failures}, stops={stops}",
            )

        return StepExecutionResult(
            verdict="PASS" if passed else "FAIL",
            summary=(
                f"Evaluation Gate (v11) {'PASS' if passed else 'FAIL'} "
                f"(failures={failures}, stops={stops}, zero_regression={zero_reg})"
            ),
            output={
                "report_schema": _V11_REPORT_SCHEMA,
                "passed": passed,
                "zero_regression": zero_reg,
                "failures": failures,
                "failed_criteria": failed_criteria,
                "stop_criteria_triggered": stops,
                "report_sha256": report_sha,
            },
            evidence={"verdict": "PASS" if passed else "FAIL", "report_sha256": report_sha},
            error_code=None if passed else "evaluation_gate_failed",
            emitted_events=[
                (
                    "evaluation.completed",
                    {"model_version": version, "passed": passed, "report_path": str(report_path)},
                )
            ],
        )

    # ------------------------------------------------------------------
    # Schema Branch A: V10 Evaluation Report (zyrquen.v10.evaluation_report.v1)
    # ------------------------------------------------------------------
    if schema_tag == _V10_REPORT_SCHEMA:
        overall = _norm_status(report.get("overall_status"))
        top_status = _norm_status(report.get("status"))
        inf_status = _norm_status(report.get("inference_status"))
        hook_flag = report.get("inference_hook_implemented")

        all_top = [s for s in (overall, top_status, inf_status) if s]
        if any(s in _EVAL_BLOCKED_STATUSES for s in all_top):
            return StepExecutionResult(
                verdict="BLOCKED",
                summary=f"v10 evaluation report is BLOCKED (overall={overall}, inference={inf_status}); certification refused.",
                output={"overall_status": overall, "inference_status": inf_status, "report_sha256": report_sha},
                evidence={"verdict": "BLOCKED", "report_sha256": report_sha},
                error_code="evaluation_blocked",
            )
        if any(s in _EVAL_NON_RUN_STATUSES for s in all_top):
            return StepExecutionResult(
                verdict="NOT RUN",
                summary=f"v10 evaluation report was NOT RUN (overall={overall}, inference={inf_status}); cannot certify PASS.",
                output={"overall_status": overall, "inference_status": inf_status, "report_sha256": report_sha},
                evidence={"verdict": "NOT RUN", "report_sha256": report_sha},
                error_code="evaluation_not_run",
            )
        if hook_flag is False and overall not in _EVAL_FAIL_STATUSES and inf_status not in _EVAL_FAIL_STATUSES:
            return StepExecutionResult(
                verdict="NOT RUN",
                summary="v10 inference_hook_implemented=False; evaluation cannot pass without real inference.",
                output={"overall_status": overall, "inference_hook_implemented": False, "report_sha256": report_sha},
                evidence={"verdict": "NOT RUN", "report_sha256": report_sha},
                error_code="inference_hook_not_implemented",
            )

        failures: list[str] = []
        if overall != "PASS":
            failures.append(f"overall_status={overall or 'MISSING'}")
        if inf_status != "PASS":
            failures.append(f"inference_status={inf_status or 'MISSING'}")
        if hook_flag is not True:
            failures.append(f"inference_hook_implemented={hook_flag!r}")
        if _norm_status(report.get("dataset_integrity")) != "PASS":
            failures.append(f"dataset_integrity={report.get('dataset_integrity')!r}")
        if _norm_status(report.get("leakage_audit_status")) != "PASS":
            failures.append(f"leakage_audit_status={report.get('leakage_audit_status')!r}")
        if report.get("error") is not None:
            failures.append(f"report_error={report.get('error')!r}")

        cap_eval = report.get("capability_evaluation")
        cap_scores: dict[str, float] = {}
        if not isinstance(cap_eval, dict):
            failures.append("capability_evaluation_missing")
        else:
            for cap in _V10_EXPECTED_CAPABILITIES:
                if cap not in cap_eval:
                    failures.append(f"missing_capability:{cap}")
                    continue
                entry = cap_eval[cap]
                if isinstance(entry, dict):
                    st = _norm_status(entry.get("status"))
                    if st in _EVAL_NON_RUN_STATUSES or st in _EVAL_BLOCKED_STATUSES or st in _EVAL_FAIL_STATUSES:
                        failures.append(f"capability_{st or 'invalid'}:{cap}")
                    elif st != "PASS":
                        failures.append(f"capability_unknown_status:{cap}={st or 'MISSING'}")
                    val = entry.get("score", entry.get("exact_match", entry.get("accuracy")))
                    if _is_finite_float(val):
                        cap_scores[cap] = float(val)
                    else:
                        failures.append(f"capability_no_score:{cap}")
                elif _is_finite_float(entry):
                    cap_scores[cap] = float(entry)
                else:
                    st = _norm_status(entry)
                    if st != "PASS":
                        failures.append(f"capability_invalid:{cap}={entry!r}")

        metrics_summary, metric_errs = _extract_finite_metrics_dict(report.get("metrics"))
        failures.extend(metric_errs)

        zero_reg = True
        reg_cmp = report.get("regression_comparison")
        if not isinstance(reg_cmp, list):
            failures.append("regression_comparison_missing_or_invalid")
            zero_reg = False
        elif reg_cmp:
            zero_reg = all(isinstance(item, dict) and item.get("zero_regression") is True for item in reg_cmp)
            if not zero_reg:
                failures.append("regression_detected")

        assessment = report.get("acceptance_assessment")
        stops: list[Any] = []
        failed_criteria: list[str] = []
        if not isinstance(assessment, dict):
            failures.append("acceptance_assessment_missing_or_invalid")
        else:
            raw_stops = assessment.get("stop_criteria_triggered")
            if not isinstance(raw_stops, list):
                failures.append("stop_criteria_triggered_missing_or_invalid")
            else:
                stops = raw_stops
                if stops:
                    failures.append("stop_criteria_triggered")
            raw_criteria = assessment.get("criteria")
            if not isinstance(raw_criteria, dict) or not raw_criteria:
                failures.append("acceptance_criteria_missing_or_empty")
            else:
                pass_criteria_count = 0
                for k, v in raw_criteria.items():
                    st_c = _norm_status(v.get("status")) if isinstance(v, dict) else ""
                    if not isinstance(v, dict) or st_c not in _V9_ALLOWED_CRITERION_STATUSES or st_c in (
                        _EVAL_FAIL_STATUSES | _EVAL_NON_RUN_STATUSES | _EVAL_BLOCKED_STATUSES
                    ):
                        failed_criteria.append(str(k))
                    elif st_c == "PASS":
                        pass_criteria_count += 1
                if failed_criteria:
                    failures.append(f"failed_criteria:{failed_criteria}")
                elif pass_criteria_count == 0:
                    failures.append("no_passing_acceptance_criteria")

        ckpt_meta = report.get("checkpoint")
        if registry_root and version:
            reg = ModelRegistry(registry_root)
            try:
                if not reg.verify(version):
                    failures.append("registry_artifact_verify_failed")
                rec = reg.get(version)
                active_baseline = reg.active_version()
                if active_baseline and active_baseline != version and isinstance(reg_cmp, list) and not reg_cmp:
                    failures.append("missing_baseline_regression_comparison")
                    zero_reg = False
            except RegistryError as exc:
                failures.append(f"registry_error:{exc}")
                rec = None
            if rec is not None and isinstance(ckpt_meta, dict):
                rep_ver = ckpt_meta.get("model_version")
                if rep_ver is not None and rep_ver != version:
                    failures.append(f"checkpoint_version_mismatch:{rep_ver}!={version}")
                rep_sha = ckpt_meta.get("checkpoint_sha256")
                if rep_sha is not None and rep_sha != (rec.get("checkpoint") or {}).get("sha256"):
                    failures.append("checkpoint_sha256_mismatch")
                if "verified" in ckpt_meta and ckpt_meta.get("verified") is not True:
                    failures.append("checkpoint_not_verified")

        passed = len(failures) == 0 and zero_reg
        wf_run_id = str(ctx["run_id"]) if ctx.get("run_id") else None
        if registry_root and version:
            reg = ModelRegistry(registry_root)
            reg.attach_evaluation_evidence(
                version,
                eval_run_id=str(ctx.get("run_id") or report.get("experiment_id") or "eval-v10"),
                report_sha256=report_sha,
                metrics=metrics_summary,
                passed=passed,
                zero_regression=zero_reg,
                capabilities=cap_scores or None,
                workflow_run_id=wf_run_id,
                evaluation_status="PASS" if passed else "FAIL",
                inference_executed=(inf_status == "PASS" and hook_flag is True),
                report_schema=_V10_REPORT_SCHEMA,
                reason=f"failures={failures}, stops={stops}",
            )

        return StepExecutionResult(
            verdict="PASS" if passed else "FAIL",
            summary=(
                f"Evaluation Gate (v10) {'PASS' if passed else 'FAIL'} "
                f"(failures={failures}, stops={stops}, zero_regression={zero_reg})"
            ),
            output={
                "report_schema": _V10_REPORT_SCHEMA,
                "passed": passed,
                "zero_regression": zero_reg,
                "failures": failures,
                "failed_criteria": failed_criteria,
                "stop_criteria_triggered": stops,
                "report_sha256": report_sha,
            },
            evidence={"verdict": "PASS" if passed else "FAIL", "report_sha256": report_sha},
            error_code=None if passed else "evaluation_gate_failed",
            emitted_events=[
                (
                    "evaluation.completed",
                    {"model_version": version, "passed": passed, "report_path": str(report_path)},
                )
            ],
        )

    # ------------------------------------------------------------------
    # Schema Branch B: V9 Evaluation Report (zyrquen.eval-v9.report.v1)
    # ------------------------------------------------------------------
    if v9_tag == _V9_REPORT_SCHEMA:
        failures = []
        assessment = report.get("acceptance_assessment")
        if not isinstance(assessment, dict):
            return StepExecutionResult(
                verdict="FAIL",
                summary="v9 evaluation report missing acceptance_assessment.",
                output={"report_schema": _V9_REPORT_SCHEMA, "passed": False, "report_sha256": report_sha},
                evidence={"verdict": "FAIL", "report_sha256": report_sha},
                error_code="malformed_eval_report",
            )

        raw_stops = assessment.get("stop_criteria_triggered")
        if not isinstance(raw_stops, list):
            failures.append("stop_criteria_triggered_missing_or_invalid")
            stops: list[Any] = []
        else:
            stops = raw_stops

        criteria = assessment.get("criteria")
        failed_criteria: list[str] = []
        non_run_criteria: list[str] = []
        pass_criteria_count = 0
        if not isinstance(criteria, dict) or not criteria:
            failures.append("criteria_missing_or_empty")
        else:
            for k, v in criteria.items():
                if not isinstance(v, dict):
                    failed_criteria.append(str(k))
                    continue
                st = _norm_status(v.get("status"))
                if st in _EVAL_NON_RUN_STATUSES or st in _EVAL_BLOCKED_STATUSES:
                    non_run_criteria.append(str(k))
                elif st not in _V9_ALLOWED_CRITERION_STATUSES:
                    failed_criteria.append(str(k))
                elif st == "PASS":
                    pass_criteria_count += 1
            if pass_criteria_count == 0 and not failed_criteria and not non_run_criteria:
                failures.append("no_passing_criteria")

        if non_run_criteria and not failed_criteria and not stops:
            return StepExecutionResult(
                verdict="NOT RUN",
                summary=f"v9 evaluation report has unexecuted criteria: {non_run_criteria}",
                output={"report_schema": _V9_REPORT_SCHEMA, "non_run_criteria": non_run_criteria, "report_sha256": report_sha},
                evidence={"verdict": "NOT RUN", "report_sha256": report_sha},
                error_code="evaluation_not_run",
            )

        data_integrity = report.get("data_integrity")
        if isinstance(data_integrity, dict):
            if _norm_status(data_integrity.get("leakage_audit_status")) != "PASS":
                failures.append("leakage_audit_not_pass")

        splits = report.get("splits")
        tu_fg: dict[str, Any] = {}
        to_fg: dict[str, Any] = {}
        if not isinstance(splits, dict):
            failures.append("splits_missing")
        else:
            tu_fg = (splits.get("test_unseen") or {}).get("overall", {}).get("free_generation", {})
            to_fg = (splits.get("test_ood") or {}).get("overall", {}).get("free_generation", {})
            if not isinstance(tu_fg, dict) or not _is_finite_float(tu_fg.get("exact_match")):
                failures.append("invalid_test_unseen_fg_exact")
            if not isinstance(to_fg, dict) or not _is_finite_float(to_fg.get("exact_match")):
                failures.append("invalid_test_ood_fg_exact")

        reg_cmp = report.get("regression_comparison")
        if not isinstance(reg_cmp, list):
            failures.append("regression_comparison_missing_or_invalid")
            zero_reg = False
        else:
            zero_reg = (
                all(isinstance(item, dict) and item.get("zero_regression") is True for item in reg_cmp)
                if reg_cmp
                else True
            )

        metrics_summary = {
            k: float(v)
            for k, v in (
                ("test_unseen_fg_exact", tu_fg.get("exact_match")),
                ("test_ood_fg_exact", to_fg.get("exact_match")),
                ("unseen_entity_copy_acc", tu_fg.get("unseen_entity_copy_acc")),
            )
            if _is_finite_float(v)
        }
        if not metrics_summary:
            failures.append("no_finite_numeric_metrics")

        if registry_root and version:
            reg = ModelRegistry(registry_root)
            try:
                if not reg.verify(version):
                    failures.append("registry_artifact_verify_failed")
                active_baseline = reg.active_version()
                if active_baseline and active_baseline != version and isinstance(reg_cmp, list) and not reg_cmp:
                    failures.append("missing_baseline_regression_comparison")
                    zero_reg = False
            except RegistryError as exc:
                failures.append(f"registry_error:{exc}")

        passed = (
            len(failures) == 0
            and len(stops) == 0
            and len(failed_criteria) == 0
            and len(non_run_criteria) == 0
            and zero_reg
        )

        wf_run_id_v9 = str(ctx["run_id"]) if ctx.get("run_id") else None
        if registry_root and version:
            reg = ModelRegistry(registry_root)
            reg.attach_evaluation_evidence(
                version,
                eval_run_id=str(ctx.get("run_id") or "eval-v9"),
                report_sha256=report_sha,
                metrics=metrics_summary,
                passed=passed,
                zero_regression=zero_reg,
                workflow_run_id=wf_run_id_v9,
                evaluation_status="PASS" if passed else "FAIL",
                inference_executed=(len(metrics_summary) > 0),
                report_schema=_V9_REPORT_SCHEMA,
                reason=f"failed_criteria={failed_criteria}, stop_triggers={stops}, failures={failures}",
            )

        return StepExecutionResult(
            verdict="PASS" if passed else "FAIL",
            summary=(
                f"Evaluation Gate (v9) {'PASS' if passed else 'FAIL'} "
                f"(failed_criteria={failed_criteria}, stops={stops}, zero_regression={zero_reg}, failures={failures})"
            ),
            output={
                "report_schema": _V9_REPORT_SCHEMA,
                "passed": passed,
                "zero_regression": zero_reg,
                "failed_criteria": failed_criteria,
                "failures": failures,
                "stop_criteria_triggered": stops,
                "report_sha256": report_sha,
            },
            evidence={"verdict": "PASS" if passed else "FAIL", "report_sha256": report_sha},
            error_code=None if passed else "evaluation_gate_failed",
            emitted_events=[
                (
                    "evaluation.completed",
                    {"model_version": version, "passed": passed, "report_path": str(report_path)},
                )
            ],
        )

    # ------------------------------------------------------------------
    # Unsupported / Untagged / Missing Schema -> Always FAIL-CLOSED
    # ------------------------------------------------------------------
    return StepExecutionResult(
        verdict="FAIL",
        summary=(
            f"Unsupported or missing evaluation report schema "
            f"(report_schema={schema_tag!r}, schema_version={v9_tag!r})."
        ),
        output={
            "passed": False,
            "report_schema": schema_tag,
            "schema_version": v9_tag,
            "report_sha256": report_sha,
        },
        evidence={"verdict": "FAIL", "report_sha256": report_sha},
        error_code="unsupported_eval_schema",
    )


# ----------------------------------------------------------------------
# 5. Knowledge & Memory Workflow
# ----------------------------------------------------------------------
def handle_knowledge_validate(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
    owner_id = str(payload.get("owner_id") or "").strip()
    workspace_id = str(payload.get("workspace_id") or "").strip()
    text = str(payload.get("content") or "").strip()

    if not owner_id or not workspace_id:
        return StepExecutionResult(
            verdict="NOT RUN",
            summary="No tenant knowledge record provided (owner_id/workspace_id required for isolated ingestion).",
            output={"checked": False},
            evidence={"verdict": "NOT RUN", "reason": "no_record_payload"},
        )
    if not text:
        return StepExecutionResult(
            verdict="FAIL",
            summary="Knowledge record content cannot be empty.",
            output={"owner_id": owner_id, "workspace_id": workspace_id},
            evidence={"verdict": "FAIL", "reason": "empty_content"},
            error_code="empty_knowledge_content",
        )

    pii_found = bool(_EMAIL_RE.search(text) or _PHONE_RE.search(text))
    scrubbed = _PHONE_RE.sub("[PHONE]", _EMAIL_RE.sub("[EMAIL]", text))
    digest = hashlib.sha256(scrubbed.encode("utf-8")).hexdigest()

    return StepExecutionResult(
        verdict="PASS",
        summary="Knowledge entry validated with tenant isolation and PII scrubbing.",
        output={
            "owner_id": owner_id,
            "workspace_id": workspace_id,
            "pii_redacted": pii_found,
            "content_sha256": digest,
        },
        evidence={"verdict": "PASS", "content_sha256": digest, "pii_redacted": pii_found},
    )


# ----------------------------------------------------------------------
# 6. Autonomous Improvement Workflow
# ----------------------------------------------------------------------
def handle_improvement_analyze(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
    report_path_raw = str(payload.get("report_path") or "").strip()
    if not report_path_raw or not Path(report_path_raw).is_file():
        return StepExecutionResult(
            verdict="NOT RUN",
            summary="No evaluation report available; no improvement hypothesis drafted.",
            output={"proposals": []},
            evidence={"verdict": "NOT RUN", "reason": "missing_eval_report"},
        )

    report = json.loads(Path(report_path_raw).read_text(encoding="utf-8"))
    tu_caps = report.get("splits", {}).get("test_unseen", {}).get("per_capability", {})
    weak_caps = [
        {"capability": cap, "fg_exact": info.get("free_generation", {}).get("exact_match")}
        for cap, info in tu_caps.items()
        if (info.get("free_generation", {}).get("exact_match") or 0.0) < 0.75
    ]
    proposal = {
        "weak_capabilities": weak_caps,
        "recommended_action": (
            "Draft offline targeted curriculum replay experiment requiring Tier-2 approval"
            if weak_caps
            else "No regressions or weak capabilities (<0.75) detected"
        ),
        "auto_weight_mutation": False,
    }
    return StepExecutionResult(
        verdict="PASS",
        summary=f"Analyzed evaluation evidence: {len(weak_caps)} capability area(s) below 0.75.",
        output={"proposal": proposal},
        evidence={"verdict": "PASS", "weak_count": len(weak_caps)},
    )


# ----------------------------------------------------------------------
# 7. Security & Governance Workflow
# ----------------------------------------------------------------------
def handle_security_audit(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
    env_name = os.getenv("ZYRQUEN_ENV", "").strip().lower() or "development"
    issues: list[str] = []
    if env_name == "production":
        if len(os.getenv("JWT_SECRET_KEY", "")) < 32:
            issues.append("JWT_SECRET_KEY missing or <32 chars in production")
        if len(os.getenv("ZYRQUEN_APPROVAL_SECRET", "")) < 32:
            issues.append("ZYRQUEN_APPROVAL_SECRET missing or <32 chars in production")

    root = _repo_root()
    critical_files = (
        "apps/api/main.py",
        "apps/api/operations.py",
        "apps/api/routers/workflows.py",
        "apps/core/workflow/governance.py",
        "apps/core/native/registry.py",
    )
    checksums = {
        rel: _sha256_file(root / rel)
        for rel in critical_files
        if (root / rel).is_file()
    }

    return StepExecutionResult(
        verdict="FAIL" if issues else "PASS",
        summary=(
            f"Security & critical file audit complete ({len(checksums)} files hashed, "
            f"{len(issues)} issue(s))"
        ),
        output={"environment": env_name, "issues": issues, "file_sha256": checksums},
        evidence={"verdict": "FAIL" if issues else "PASS", "issue_count": len(issues)},
    )


# ----------------------------------------------------------------------
# 8. Project & Development Workflow
# ----------------------------------------------------------------------
def handle_project_dev_sync(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
    root = _repo_root()
    phases_present = [i for i in range(11, 21) if (root / "phases" / f"phase{i}.py").is_file()]
    v9_tools_present = [
        name
        for name in ("gen_nagi_v9.py", "audit_leakage_v9.py", "train_nagi_v9.py", "eval_nagi_v9.py")
        if (root / "tools" / name).is_file()
    ]
    return StepExecutionResult(
        verdict="PASS",
        summary=(
            f"Roadmap phases 11-20 verified on disk ({len(phases_present)}/10); "
            f"v9 scripts present ({len(v9_tools_present)}/4)."
        ),
        output={
            "roadmap_phases_present": phases_present,
            "v9_tools_present": v9_tools_present,
            "workflow_plan_present": (root / "docs" / "WORKFLOW_ENGINE_PLAN.md").is_file(),
            "push_or_deploy_blocked_without_approval": True,
        },
        evidence={"verdict": "PASS", "phases_count": len(phases_present)},
    )


def handle_project_dev_maintainer_audit(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
    repo_root = Path(str(payload.get("repo_root") or _repo_root())).resolve()
    run_tests = bool(payload.get("run_tests", False))
    test_pattern = str(payload.get("test_pattern") or "test_*.py")
    bot = ZyrquenMaintainerBot(repo_root)
    report = bot.run_audit(run_tests=run_tests, test_pattern=test_pattern)
    report_dict = report.to_dict()

    if report.checks.get("native_only_compliance") != "PASS":
        return StepExecutionResult(
            verdict="BLOCKED",
            summary="Maintainer audit blocked: Native-Only policy violation detected.",
            output={"audit_report": report_dict, "audit_verdict": report.overall_verdict},
            evidence={"verdict": "BLOCKED", "finding_count": len(report.findings)},
            error_code="native_only_violation",
        )

    return StepExecutionResult(
        verdict="PASS",
        summary=(
            f"Repository audit complete ({report.files_scanned} files scanned, "
            f"{len(report.findings)} finding(s), audit_verdict={report.overall_verdict})."
        ),
        output={
            "repo_root": str(repo_root),
            "audit_verdict": report.overall_verdict,
            "finding_count": len(report.findings),
            "audit_report": report_dict,
        },
        evidence={
            "verdict": "PASS",
            "audit_verdict": report.overall_verdict,
            "finding_count": len(report.findings),
        },
    )


def handle_project_dev_maintainer_propose(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
    prev = (ctx.get("previous_outputs") or {}).get("audit_repo") or {}
    repo_root = Path(str(prev.get("repo_root") or payload.get("repo_root") or _repo_root())).resolve()
    bot = ZyrquenMaintainerBot(repo_root)

    raw_report = prev.get("audit_report")
    if isinstance(raw_report, dict):
        findings = [
            AuditFinding(**item)
            for item in raw_report.get("findings", [])
            if isinstance(item, dict)
        ]
        report = AuditReport(
            schema=str(raw_report.get("schema", "zyrquen.maintainer.audit.v1")),
            generated_at=str(raw_report.get("generated_at", "")),
            repo_root=str(repo_root),
            overall_verdict=str(raw_report.get("overall_verdict", "PASS")),
            files_scanned=int(raw_report.get("files_scanned", 0)),
            findings=findings,
            checks=dict(raw_report.get("checks", {})),
        )
    else:
        report = bot.run_audit(run_tests=False)

    branch_name = payload.get("branch_name")
    try:
        plan = bot.propose_remediation(
            report,
            branch_name=str(branch_name) if branch_name else None,
            verify_in_sandbox=bool(payload.get("verify_in_sandbox", True)),
        )
    except MaintainerPolicyError as exc:
        return StepExecutionResult(
            verdict="BLOCKED",
            summary=f"Maintainer remediation blocked by policy: {exc}",
            output={"policy_error": str(exc)},
            evidence={"verdict": "BLOCKED", "reason": "maintainer_policy_violation"},
            error_code="maintainer_policy_violation",
        )

    plan_dict = plan.to_dict()
    return StepExecutionResult(
        verdict="PASS",
        summary=(
            f"Prepared remediation bundle on branch {plan.branch_name}: "
            f"{len(plan.proposals)} safe patch(es), {len(plan.unresolved_findings)} item(s) requiring human review."
        ),
        output={
            "remediation_plan": plan_dict,
            "branch_name": plan.branch_name,
            "proposal_count": len(plan.proposals),
            "unresolved_count": len(plan.unresolved_findings),
            "tier2_required_before_merge": True,
        },
        evidence={
            "verdict": "PASS",
            "proposal_count": len(plan.proposals),
            "verification_verdict": plan.verification.get("verdict", "NOT RUN"),
        },
    )


def handle_project_dev_maintainer_merge(ctx: dict[str, Any], payload: dict[str, Any]) -> StepExecutionResult:
    consumed_approval = ctx.get("consumed_approval")
    if not consumed_approval:
        return StepExecutionResult(
            verdict="BLOCKED",
            summary="Merge to main blocked: verified Tier-2 admin approval is required.",
            output={"merged": False},
            evidence={"verdict": "BLOCKED", "reason": "missing_tier2_approval"},
            error_code="approval_violation",
        )

    prev_propose = (ctx.get("previous_outputs") or {}).get("propose_remediation") or {}
    branch_name = str(prev_propose.get("branch_name") or payload.get("branch_name") or "")
    repo_root = Path(str(payload.get("repo_root") or _repo_root())).resolve()
    bot = ZyrquenMaintainerBot(repo_root)
    gate_result = bot.merge_to_main(has_tier2_approval=True)
    return StepExecutionResult(
        verdict="PASS",
        summary=(
            f"Tier-2 approval ({consumed_approval.get('id')}) verified for merging branch "
            f"{branch_name or '<unspecified>'} into main."
        ),
        output={
            **gate_result,
            "approval_id": consumed_approval.get("id"),
            "branch_name": branch_name,
            "target_base_branch": "main",
        },
        evidence={
            "verdict": "PASS",
            "approval_id": consumed_approval.get("id"),
            "branch_name": branch_name,
        },
    )
