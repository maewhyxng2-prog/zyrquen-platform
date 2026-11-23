#!/usr/bin/env python3
"""
ZYRQUEN Native Model v11 — Guessing Floor & Native Evaluation Runner

Supports:
  1. Step-0 Random-Weights Guessing Floor Baseline (`--random-init`):
       - Instantiates a fresh native `ZyrquenModel(ZyrquenConfig())` from random
         weights ONLY (`seed=1337` default, zero external pretrained weights/APIs).
       - Saves an ephemeral Step-0 checkpoint inside an isolated temporary
         directory (zero mutation to `registry.json` or historical V7-V10 files).
       - Runs real greedy generation via `EvaluationEngine.evaluate_native_model`
         AND computes teacher-forced Cross-Entropy Loss / Perplexity / Token
         Accuracy across `validation`, `unseen`, `ood` (plus optional `train`
         diagnostic) to establish the quantitative Step-0 Guessing Floor.
       - Emits honest `zyrquen.v11.evaluation_report.v1` with `overall_status="FAIL"`
         (untrained model has no capability) and checks `exact_match < 0.05` on
         `unseen` and `ood` (`guessing_floor_verified`).
  2. Trained Native Checkpoint Evaluation (`--run-inference --model-version ...`):
       - Verifies checkpoint + dataset + leakage audit + tokenizer SHA-256.
       - Executes real PyTorch native inference via `EvaluationEngine`.
       - Optionally compares against a saved Step-0 Guessing Floor report
         (`--baseline-report`) and `ModelRegistry` active baseline.

Safety:
  - Fails closed (`BLOCKED`, exit 3) if PyTorch or dataset/tokenizer is missing.
  - Zero fabricated scores, zero external models, zero V7-V10 modifications.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
TOOLS_DIR = PROJECT_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from apps.core.native.checkpoint import VersionedCheckpointManager  # noqa: E402
from apps.core.native.config import MAX_V10_PARAMETERS, ZyrquenConfig  # noqa: E402
from apps.core.native.dataset import (  # noqa: E402
    SCHEMA as MANIFEST_SCHEMA,
    V11_SPLITS,
    detect_dataset_format,
    load_sft_split,
    verify_dataset_manifest,
)
from apps.core.native.evaluation import (  # noqa: E402
    EvaluationEngine,
    EvaluationError as NativeEvaluationError,
    EvaluationNotConfiguredError,
)
from apps.core.native.registry import ModelRegistry, RegistryError  # noqa: E402
from apps.core.native.sft import (  # noqa: E402
    IGNORE_INDEX,
    SFT_SEP,
    bind_ephemeral_slots,
    encode_sft_pair,
)
from apps.core.native.tokenizer import ZyrquenTokenizer  # noqa: E402
from audit_leakage_v11 import CAPABILITIES, run_audit  # noqa: E402

DEFAULT_DATASET_DIR = PROJECT_ROOT / "data" / "nagi_v11"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eval" / "nagi_v11"
EVAL_REPORT_SCHEMA = "zyrquen.v11.evaluation_report.v1"
REQUIRED_EVAL_SPLITS: tuple[str, ...] = ("validation", "unseen", "ood")


class EvaluationRunnerError(RuntimeError):
    """Raised when V11 dataset, tokenizer, or checkpoint verification fails."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_dataset_and_tokenizer(
    dataset_dir: Path,
    tokenizer_path: Path | None,
) -> tuple[dict[str, Any], Path, ZyrquenTokenizer]:
    if dataset_dir.is_symlink() or not dataset_dir.is_dir():
        raise EvaluationRunnerError(f"Dataset directory missing or symlinked: {dataset_dir}")

    manifest = verify_dataset_manifest(dataset_dir, require_schema=True)
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("dataset") != "nagi_v11":
        raise EvaluationRunnerError("Dataset manifest is not valid nagi_v11.")
    if detect_dataset_format(dataset_dir) != "sft":
        raise EvaluationRunnerError("nagi_v11 dataset must be in 'sft' format.")

    tok_candidate = tokenizer_path if tokenizer_path is not None else (dataset_dir / "tokenizer.json")
    if tok_candidate.is_symlink() or not tok_candidate.is_file():
        raise EvaluationNotConfiguredError(
            f"Tokenizer not found at {tok_candidate}. Run gen_nagi_v11.py --train-tokenizer or pass --tokenizer-path."
        )
    tok = ZyrquenTokenizer.load(tok_candidate)

    files_meta = manifest.get("files") or {}
    split_details = {
        sp: {
            "documents": (files_meta.get(f"{sp}.jsonl") or {}).get("documents"),
            "sha256": (files_meta.get(f"{sp}.jsonl") or {}).get("sha256"),
            "integrity": "PASS",
        }
        for sp in V11_SPLITS
    }
    dataset_summary = {
        "dataset_dir": str(dataset_dir),
        "dataset_version": manifest.get("version"),
        "manifest_sha256": _sha256_file(dataset_dir / "manifest.json"),
        "content_sha256": manifest.get("content_sha256"),
        "dataset_integrity": "PASS",
        "splits": split_details,
    }
    return dataset_summary, tok_candidate, tok


def _compute_teacher_forced_metrics(
    *,
    ckpt_path: Path,
    dataset_dir: Path,
    tok: ZyrquenTokenizer,
    splits: tuple[str, ...],
    max_examples: int | None,
    device: str = "cpu",
) -> dict[str, Any]:
    """Compute exact teacher-forced NLL, perplexity, and token accuracy over SFT targets."""
    import torch
    import torch.nn.functional as F
    from apps.core.native.model import ZyrquenModel
    from apps.core.native.registry import _safe_torch_load

    state = _safe_torch_load(str(ckpt_path))
    cfg = ZyrquenConfig.from_dict(state["model_config"])
    model = ZyrquenModel(cfg)
    model.load_state_dict(state["model"])
    model.to(device)
    model.eval()
    sep = str(state.get("sep") or SFT_SEP)

    per_split: dict[str, dict[str, float]] = {}
    total_nll = 0.0
    total_tokens = 0
    total_tok_correct = 0

    with torch.no_grad():
        for sp in splits:
            rows = list(load_sft_split(dataset_dir, sp))
            if max_examples is not None and max_examples > 0:
                rows = rows[:max_examples]
            sp_nll = 0.0
            sp_tokens = 0
            sp_correct = 0
            for row in rows:
                bp, bt, _ = bind_ephemeral_slots(str(row["input"]), str(row["target"]), permute_slots=False)
                assert bt is not None
                x_ids, y_ids = encode_sft_pair(tok, bp, bt, max_seq_len=cfg.max_seq_len, sep=sep)
                x_tensor = torch.tensor([x_ids], dtype=torch.long, device=device)
                y_tensor = torch.tensor([y_ids], dtype=torch.long, device=device)
                logits, _ = model(x_tensor)
                loss_sum = F.cross_entropy(
                    logits.view(-1, logits.size(-1)),
                    y_tensor.view(-1),
                    ignore_index=IGNORE_INDEX,
                    reduction="sum",
                )
                valid_mask = y_tensor.view(-1) != IGNORE_INDEX
                n_tok = int(valid_mask.sum().item())
                preds = logits.view(-1, logits.size(-1)).argmax(dim=-1)
                n_corr = int(((preds == y_tensor.view(-1)) & valid_mask).sum().item())

                sp_nll += float(loss_sum.item())
                sp_tokens += n_tok
                sp_correct += n_corr

            mean_loss = (sp_nll / sp_tokens) if sp_tokens else float("nan")
            ppl = math.exp(min(mean_loss, 20.0)) if sp_tokens and math.isfinite(mean_loss) else float("nan")
            tok_acc = (sp_correct / sp_tokens) if sp_tokens else 0.0
            per_split[sp] = {
                "loss": round(mean_loss, 6),
                "perplexity": round(ppl, 4),
                "token_acc": round(tok_acc, 6),
                "target_tokens": float(sp_tokens),
            }
            if sp != "train":
                total_nll += sp_nll
                total_tokens += sp_tokens
                total_tok_correct += sp_correct

    agg_loss = (total_nll / total_tokens) if total_tokens else float("nan")
    agg_ppl = math.exp(min(agg_loss, 20.0)) if total_tokens and math.isfinite(agg_loss) else float("nan")
    agg_tok_acc = (total_tok_correct / total_tokens) if total_tokens else 0.0
    return {
        "eval_loss": round(agg_loss, 6),
        "eval_perplexity": round(agg_ppl, 4),
        "teacher_forced_token_acc": round(agg_tok_acc, 6),
        "per_split": per_split,
    }


def run_random_init_baseline(
    *,
    dataset_dir: Path,
    dataset_summary: dict[str, Any],
    tok_path: Path,
    tok: ZyrquenTokenizer,
    splits: tuple[str, ...],
    seed: int,
    max_seq_len: int,
    n_layers: int,
    n_heads: int,
    d_model: int,
    d_ff: int,
    max_examples: int | None,
    max_new_tokens: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        import torch
        from apps.core.native.model import ZyrquenModel
        from apps.core.workflow.resource_guard import MAX_CPU_THREADS, enforce_cpu_thread_cap
    except ModuleNotFoundError as exc:
        raise EvaluationNotConfiguredError(
            "PyTorch runtime is not installed; random-init native Guessing Floor evaluation cannot execute."
        ) from exc

    enforce_cpu_thread_cap(MAX_CPU_THREADS, torch_mod=torch)
    torch.manual_seed(seed)

    cfg = ZyrquenConfig(
        vocab_size=tok.vocab_size,
        max_seq_len=max_seq_len,
        n_layers=n_layers,
        n_heads=n_heads,
        d_model=d_model,
        d_ff=d_ff,
        dropout=0.0,
    )
    cfg.validate_parameter_budget(MAX_V10_PARAMETERS)
    model = ZyrquenModel(cfg)
    model.eval()
    actual_params = sum(p.numel() for p in model.parameters())
    model_ver = f"v11-step0-random-seed{seed}"

    with tempfile.TemporaryDirectory(prefix="zyrquen_v11_step0_") as tmp_dir_str:
        ckpt_dir = Path(tmp_dir_str)
        vcm = VersionedCheckpointManager(ckpt_dir)
        state = {
            "model": {k: v.detach().cpu() for k, v in model.state_dict().items()},
            "model_config": cfg.to_dict(),
            "tokenizer_sha256": tok.fingerprint(),
            "sep": SFT_SEP,
            "init_mode": "random_init_step_0",
            "seed": seed,
            "step": 0,
            "parameter_count": actual_params,
        }
        ver_entry = vcm.save_versioned(
            step=0,
            state=state,
            model_version=model_ver,
            dataset_version=str(dataset_summary["dataset_version"]),
            dataset_content_hash=str(dataset_summary["content_sha256"]),
            config=cfg.to_dict(),
            tokenizer_sha256=tok.fingerprint(),
        )
        ckpt_path = ckpt_dir / ver_entry["checkpoint_file"]

        engine = EvaluationEngine(checkpoint_dir=ckpt_dir)
        inf_result = engine.evaluate_native_model(
            model_ver,
            dataset_dir=dataset_dir,
            tokenizer_path=tok_path,
            splits=splits,
            max_examples=max_examples,
            max_new_tokens=max_new_tokens,
            use_slots=True,
            device="cpu",
            capability_pass_threshold=0.5,
        )
        tf_metrics = _compute_teacher_forced_metrics(
            ckpt_path=ckpt_path,
            dataset_dir=dataset_dir,
            tok=tok,
            splits=splits,
            max_examples=max_examples,
            device="cpu",
        )

    checkpoint_info = {
        "model_version": model_ver,
        "checkpoint_sha256": ver_entry["checkpoint_sha256"],
        "verified": True,
        "ephemeral": True,
        "init_mode": "random_init_step_0",
        "seed": seed,
        "step": 0,
        "parameter_count": actual_params,
        "model_config": cfg.to_dict(),
    }
    return inf_result, tf_metrics, checkpoint_info


def _build_baseline_comparison(
    baseline_report_path: Path | None,
    current_metrics: dict[str, float],
    *,
    vocab_size: int,
    is_random_init: bool,
    registry_root: Path | None,
    model_version: str | None,
    inference_result: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    if is_random_init:
        vocab_guess_loss = round(math.log(max(2, vocab_size)), 6)
        comparisons.append(
            {
                "baseline": f"theoretical_uniform_random_vocab_{vocab_size}",
                "theoretical_uniform_loss": vocab_guess_loss,
                "observed_val_loss": current_metrics.get("val_loss"),
                "zero_regression": True,
                "note": "Step-0 random-init Guessing Floor reference baseline (pre-training).",
            }
        )
        return comparisons

    if baseline_report_path and baseline_report_path.is_file():
        base_doc = json.loads(baseline_report_path.read_text(encoding="utf-8"))
        base_m = base_doc.get("metrics") or {}
        deltas: dict[str, dict[str, float]] = {}
        regressed: list[str] = []
        for k in ("val_loss", "eval_loss", "unseen_exact_match", "ood_exact_match", "eos_hit_rate"):
            bv = base_m.get(k)
            cv = current_metrics.get(k)
            if isinstance(bv, (int, float)) and isinstance(cv, (int, float)):
                d = round(float(cv) - float(bv), 6)
                deltas[k] = {"step0_floor": float(bv), "candidate": float(cv), "delta": d}
                if k.endswith("loss") and d > 0.01:
                    regressed.append(k)
                elif not k.endswith("loss") and d < -0.01:
                    regressed.append(k)
        comparisons.append(
            {
                "baseline": str(baseline_report_path.name),
                "baseline_type": "step_0_random_init_guessing_floor",
                "metric_deltas": deltas,
                "regressed_metrics": regressed,
                "zero_regression": len(regressed) == 0,
            }
        )

    if registry_root and model_version and inference_result:
        reg = ModelRegistry(registry_root)
        active = reg.active_version()
        if active and active != model_version:
            cmp_res = reg.compare_versions(active, model_version)
            comparisons.append(cmp_res)

    if not comparisons:
        comparisons.append(
            {
                "baseline": "none_registered",
                "zero_regression": True,
                "note": "First V11 checkpoint evaluation; no prior V11 active model.",
            }
        )
    return comparisons


def build_v11_report(
    *,
    dataset_dir: Path,
    experiment_id: str,
    dataset_summary: dict[str, Any] | None,
    leakage_audit_status: str,
    leakage_audit_detail: dict[str, Any] | None,
    tokenizer_info: dict[str, Any] | None,
    checkpoint_info: dict[str, Any] | None,
    inference_result: dict[str, Any] | None,
    tf_metrics: dict[str, Any] | None,
    inference_status: str,
    inference_executed: bool,
    is_random_init: bool,
    regression_comparison: list[dict[str, Any]],
    error: str | None,
) -> dict[str, Any]:
    integrity_status = dataset_summary["dataset_integrity"] if dataset_summary else "FAIL"
    stop_criteria: list[str] = []

    if inference_status == "BLOCKED":
        overall_status = "BLOCKED"
        capability_eval = {cap: {"status": "NOT RUN", "score": 0.0} for cap in CAPABILITIES}
        splits_out: dict[str, Any] = {}
        metrics_out: dict[str, float] = {}
        if error:
            stop_criteria.append(f"blocked:{error}")
    elif error is not None or integrity_status != "PASS" or leakage_audit_status != "PASS":
        overall_status = "FAILED"
        capability_eval = {cap: {"status": "NOT RUN", "score": 0.0} for cap in CAPABILITIES}
        splits_out = {}
        metrics_out = {}
        stop_criteria.append(f"failed:{error or 'dataset_or_audit_failed'}")
    elif inference_result is not None and inference_executed and inference_status == "PASS":
        raw_caps = dict(inference_result.get("capability_evaluation") or {})
        capability_eval = {}
        for cap in CAPABILITIES:
            entry = dict(raw_caps.get(cap) or {"status": "NOT RUN", "accuracy": 0.0})
            if "exact_match" not in entry and "accuracy" in entry:
                entry["exact_match"] = entry["accuracy"]
            if "score" not in entry and "accuracy" in entry:
                entry["score"] = entry["accuracy"]
            capability_eval[cap] = entry

        splits_out = dict(inference_result.get("splits") or {})
        metrics_out = {
            str(k): float(v)
            for k, v in (inference_result.get("metrics") or {}).items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        if tf_metrics:
            metrics_out["eval_loss"] = float(tf_metrics["eval_loss"])
            metrics_out["eval_perplexity"] = float(tf_metrics["eval_perplexity"])
            metrics_out["teacher_forced_token_acc"] = float(tf_metrics["teacher_forced_token_acc"])
            for sp, sp_tf in (tf_metrics.get("per_split") or {}).items():
                key_prefix = "val" if sp == "validation" else sp
                metrics_out[f"{key_prefix}_loss"] = float(sp_tf["loss"])
                metrics_out[f"{key_prefix}_perplexity"] = float(sp_tf["perplexity"])
                metrics_out[f"{key_prefix}_token_acc"] = float(sp_tf["token_acc"])
                if sp in splits_out:
                    splits_out[sp]["loss"] = float(sp_tf["loss"])
                    splits_out[sp]["perplexity"] = float(sp_tf["perplexity"])
                    splits_out[sp]["teacher_forced_token_acc"] = float(sp_tf["token_acc"])

        unseen_em = float((splits_out.get("unseen") or {}).get("exact_match", 1.0))
        ood_em = float((splits_out.get("ood") or {}).get("exact_match", 1.0))
        guessing_floor_ok = unseen_em < 0.05 and ood_em < 0.05
        metrics_out["guessing_floor_verified"] = 1.0 if guessing_floor_ok else 0.0

        all_caps_pass = all(
            isinstance(capability_eval.get(c), dict) and capability_eval[c].get("status") == "PASS"
            for c in CAPABILITIES
        )
        zero_reg = all(bool(item.get("zero_regression")) for item in regression_comparison)

        if is_random_init:
            # Honest verdict: untrained Step-0 random weights must report FAIL on intelligence,
            # while verifying Guessing Floor (< 0.05 exact match on unseen/ood).
            overall_status = "FAIL"
            stop_criteria.append("untrained_random_weights_baseline")
            if not guessing_floor_ok:
                stop_criteria.append("guessing_floor_exceeded_0.05_suspect_leakage")
        else:
            if not all_caps_pass:
                stop_criteria.append("capability_threshold_failed")
            if not zero_reg:
                stop_criteria.append("regression_detected")
            overall_status = "PASS" if (all_caps_pass and zero_reg) else "FAIL"
    else:
        overall_status = "NOT RUN"
        capability_eval = {cap: {"status": "NOT RUN", "score": 0.0} for cap in CAPABILITIES}
        splits_out = {}
        metrics_out = {}

    if is_random_init and inference_executed:
        guessing_floor_status = (
            "PASS" if metrics_out.get("guessing_floor_verified", 0.0) == 1.0 else "FAIL"
        )
    else:
        guessing_floor_status = "NOT_APPLICABLE"

    criteria = {
        "dataset_integrity": {"status": integrity_status},
        "leakage_audit": {"status": leakage_audit_status},
        "native_inference": {"status": inference_status},
        "guessing_floor_sanity": {"status": guessing_floor_status},
        "all_capabilities_evaluated": {
            "status": (
                "PASS"
                if overall_status == "PASS"
                else ("FAIL" if inference_executed else inference_status)
            )
        },
        "zero_regression": {
            "status": (
                "PASS"
                if all(bool(r.get("zero_regression")) for r in regression_comparison)
                else "FAIL"
            )
        },
    }

    return {
        "schema_version": "1.0",
        "report_schema": EVAL_REPORT_SCHEMA,
        "project": "ZYRQUEN Ω∞",
        "experiment": "Native Model v11",
        "experiment_id": experiment_id,
        "baseline_type": (
            "step_0_random_init_guessing_floor" if is_random_init else "trained_checkpoint_eval"
        ),
        "created_at": utc_now(),
        "dataset_dir": str(dataset_dir),
        "dataset_manifest_sha256": dataset_summary.get("manifest_sha256") if dataset_summary else None,
        "dataset_content_sha256": dataset_summary.get("content_sha256") if dataset_summary else None,
        "tokenizer": tokenizer_info,
        "overall_status": overall_status,
        "status": overall_status,
        "dataset_integrity": integrity_status,
        "leakage_audit_status": leakage_audit_status,
        "leakage_audit": leakage_audit_detail,
        "inference_status": inference_status,
        "inference_executed": inference_executed,
        "splits": splits_out,
        "capability_evaluation": capability_eval,
        "metrics": metrics_out,
        "regression_comparison": regression_comparison,
        "acceptance_assessment": {
            "criteria": criteria,
            "stop_criteria_triggered": stop_criteria,
        },
        "checkpoint": checkpoint_info,
        "dataset": dataset_summary,
        "error": error,
        "notes": [
            "Native ZyrquenModel only — zero external pretrained weights or external AI APIs.",
            "No production ModelRegistry or historical V7-V10 files were modified.",
        ],
    }


def write_report_file(
    report: dict[str, Any],
    output_path: Path,
    *,
    allow_overwrite: bool = False,
) -> Path:
    if output_path.is_symlink():
        raise EvaluationRunnerError(f"Report path cannot be a symlink: {output_path}")
    parent = output_path.parent
    if parent.is_symlink():
        raise EvaluationRunnerError(f"Report parent directory cannot be a symlink: {parent}")
    parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not allow_overwrite:
        raise EvaluationRunnerError(
            f"Refusing to overwrite existing report without --overwrite: {output_path}"
        )

    payload = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".v11_eval_", suffix=".tmp", dir=parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, output_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return output_path


def write_report(report: dict[str, Any], output_dir: Path, prefix: str = "v11_evaluation") -> Path:
    if output_dir.is_symlink():
        raise EvaluationRunnerError("Output directory cannot be a symlink.")
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    out_path = output_dir / f"{prefix}_{ts}.json"
    return write_report_file(report, out_path, allow_overwrite=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ZYRQUEN v11 Step-0 Random-Weights Guessing Floor & Native Evaluation Runner"
    )
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--output-file",
        type=Path,
        default=None,
        help="Optional exact file path to write JSON report (e.g., artifacts/baselines/random_init_baseline.json).",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--tokenizer-path", type=Path, default=None)
    parser.add_argument("--experiment-id", type=str, default="p11-step0-guessing-floor")
    parser.add_argument(
        "--random-init",
        action="store_true",
        help="Evaluate a fresh Step-0 random-initialized V11-Tier0-Default model to measure Guessing Floor.",
    )
    parser.add_argument("--run-inference", action="store_true")
    parser.add_argument("--checkpoint-dir", type=Path, default=None)
    parser.add_argument("--registry-root", type=Path, default=None)
    parser.add_argument("--model-version", type=str, default=None)
    parser.add_argument("--baseline-report", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--max-seq-len", type=int, default=256)
    parser.add_argument("--n-layers", type=int, default=4)
    parser.add_argument("--n-heads", type=int, default=4)
    parser.add_argument("--d-model", type=int, default=256)
    parser.add_argument("--d-ff", type=int, default=704)
    parser.add_argument("--max-examples", type=int, default=None)
    parser.add_argument("--max-new-tokens", type=int, default=64)
    parser.add_argument("--include-train-diagnostic", action="store_true")
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_dir = args.dataset_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    tok_path_arg = args.tokenizer_path.expanduser().resolve() if args.tokenizer_path else None
    ckpt_dir_arg = args.checkpoint_dir.expanduser().resolve() if args.checkpoint_dir else None
    reg_root_arg = args.registry_root.expanduser().resolve() if args.registry_root else None
    baseline_arg = args.baseline_report.expanduser().resolve() if args.baseline_report else None

    if args.random_init and (ckpt_dir_arg or args.model_version):
        print("Error: --random-init cannot be combined with --checkpoint-dir or --model-version.", file=sys.stderr)
        return 2

    eval_splits: tuple[str, ...] = (
        ("train", "validation", "unseen", "ood")
        if args.include_train_diagnostic
        else REQUIRED_EVAL_SPLITS
    )

    dataset_summary: dict[str, Any] | None = None
    leakage_audit_status = "NOT RUN"
    leakage_audit_detail: dict[str, Any] | None = None
    tokenizer_info: dict[str, Any] | None = None
    checkpoint_info: dict[str, Any] | None = None
    inference_result: dict[str, Any] | None = None
    tf_metrics: dict[str, Any] | None = None
    inference_status = "NOT RUN"
    inference_executed = False
    error: str | None = None
    regression_cmp: list[dict[str, Any]] = []

    try:
        dataset_summary, resolved_tok_path, tok = verify_dataset_and_tokenizer(
            dataset_dir, tok_path_arg
        )
        tokenizer_info = {
            "path": str(resolved_tok_path),
            "vocab_size": tok.vocab_size,
            "sha256": tok.fingerprint(),
            "schema": tok.schema,
        }

        audit_res = run_audit(
            dataset_dir,
            tokenizer_path=resolved_tok_path,
            max_seq_len=args.max_seq_len,
            require_tokenizer=True,
            strict=True,
        )
        leakage_audit_status = str(audit_res.get("overall_status", "FAIL"))
        leakage_audit_detail = {
            "status": leakage_audit_status,
            "total_examples": audit_res.get("total_examples"),
            "split_counts": audit_res.get("split_counts"),
            "gates_passed": {
                k: bool(v.get("passed")) for k, v in (audit_res.get("gates") or {}).items()
            },
        }
        if leakage_audit_status != "PASS":
            failed_gates = [
                k for k, v in (audit_res.get("gates") or {}).items() if not v.get("passed")
            ]
            raise EvaluationRunnerError(f"Dataset/leakage audit failed: {failed_gates}")

        if args.random_init:
            inference_result, tf_metrics, checkpoint_info = run_random_init_baseline(
                dataset_dir=dataset_dir,
                dataset_summary=dataset_summary,
                tok_path=resolved_tok_path,
                tok=tok,
                splits=eval_splits,
                seed=args.seed,
                max_seq_len=args.max_seq_len,
                n_layers=args.n_layers,
                n_heads=args.n_heads,
                d_model=args.d_model,
                d_ff=args.d_ff,
                max_examples=args.max_examples,
                max_new_tokens=args.max_new_tokens,
            )
            inference_status = str(inference_result.get("inference_status") or "PASS")
            inference_executed = inference_status == "PASS"
        elif args.run_inference:
            if (not ckpt_dir_arg and not reg_root_arg) or not args.model_version:
                raise EvaluationNotConfiguredError(
                    "--run-inference requires --model-version and --checkpoint-dir or --registry-root"
                )
            engine = EvaluationEngine(checkpoint_dir=ckpt_dir_arg, registry_root=reg_root_arg)
            ckpt_meta = engine.verify_checkpoint_version(args.model_version)
            inference_result = engine.evaluate_native_model(
                args.model_version,
                dataset_dir=dataset_dir,
                tokenizer_path=resolved_tok_path,
                splits=eval_splits,
                max_examples=args.max_examples,
                max_new_tokens=args.max_new_tokens,
                use_slots=True,
                device="cpu",
            )
            inference_status = str(inference_result.get("inference_status") or "PASS")
            inference_executed = inference_status == "PASS"
            resolved_ckpt = (
                (ckpt_dir_arg / str(ckpt_meta["checkpoint_file"]))
                if ckpt_dir_arg
                else (reg_root_arg / str(ckpt_meta["checkpoint_file"]))
            )
            tf_metrics = _compute_teacher_forced_metrics(
                ckpt_path=resolved_ckpt,
                dataset_dir=dataset_dir,
                tok=tok,
                splits=eval_splits,
                max_examples=args.max_examples,
                device="cpu",
            )
            checkpoint_info = {
                "model_version": args.model_version,
                "checkpoint_sha256": ckpt_meta.get("checkpoint_sha256"),
                "verified": True,
                "ephemeral": False,
                "init_mode": "trained_checkpoint",
            }
    except EvaluationNotConfiguredError as exc:
        inference_status = "BLOCKED"
        error = str(exc)
    except (EvaluationRunnerError, NativeEvaluationError, RegistryError, OSError, ValueError) as exc:
        if args.random_init or args.run_inference:
            inference_status = "FAIL"
        error = str(exc)

    prelim_metrics: dict[str, float] = {}
    if inference_result and isinstance(inference_result.get("metrics"), dict):
        prelim_metrics.update(
            {
                k: float(v)
                for k, v in inference_result["metrics"].items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            }
        )
    if tf_metrics:
        prelim_metrics["eval_loss"] = float(tf_metrics["eval_loss"])
        val_tf = (tf_metrics.get("per_split") or {}).get("validation")
        if val_tf:
            prelim_metrics["val_loss"] = float(val_tf["loss"])

    regression_cmp = _build_baseline_comparison(
        baseline_arg,
        prelim_metrics,
        vocab_size=int((tokenizer_info or {}).get("vocab_size") or 2048),
        is_random_init=args.random_init,
        registry_root=reg_root_arg,
        model_version=args.model_version,
        inference_result=inference_result,
    )

    report = build_v11_report(
        dataset_dir=dataset_dir,
        experiment_id=args.experiment_id,
        dataset_summary=dataset_summary,
        leakage_audit_status=leakage_audit_status,
        leakage_audit_detail=leakage_audit_detail,
        tokenizer_info=tokenizer_info,
        checkpoint_info=checkpoint_info,
        inference_result=inference_result,
        tf_metrics=tf_metrics,
        inference_status=inference_status,
        inference_executed=inference_executed,
        is_random_init=args.random_init,
        regression_comparison=regression_cmp,
        error=error,
    )

    if not args.no_write_report:
        if args.output_file is not None:
            if report["overall_status"] == "BLOCKED":
                print(
                    f"Skipping write to {args.output_file} because evaluation is BLOCKED (no metrics fabricated)."
                )
            else:
                out_path = write_report_file(
                    report,
                    args.output_file.expanduser().resolve(),
                    allow_overwrite=args.overwrite,
                )
                print(f"Report: {out_path}")
        else:
            prefix = "v11_step0_guessing_floor" if args.random_init else "v11_evaluation"
            out_path = write_report(report, output_dir, prefix=prefix)
            print(f"Report: {out_path}")

    print(f"Dataset integrity: {report['dataset_integrity']}")
    print(f"Leakage audit: {report['leakage_audit_status']}")
    print(f"Inference: {report['inference_status']} (executed={report['inference_executed']})")
    print(f"Overall status: {report['overall_status']}")
    if report["metrics"]:
        print(
            "Metrics summary:",
            json.dumps(
                {
                    k: report["metrics"][k]
                    for k in (
                        "exact_match",
                        "validation_exact_match",
                        "unseen_exact_match",
                        "ood_exact_match",
                        "eos_hit_rate",
                        "eval_loss",
                        "eval_perplexity",
                        "val_loss",
                        "unseen_loss",
                        "ood_loss",
                        "teacher_forced_token_acc",
                        "guessing_floor_verified",
                    )
                    if k in report["metrics"]
                },
                ensure_ascii=False,
            ),
        )
    if error:
        print(f"Reason: {error}")

    if report["overall_status"] == "BLOCKED":
        return 3
    if args.random_init:
        floor_ok = (
            inference_executed
            and leakage_audit_status == "PASS"
            and report["metrics"].get("guessing_floor_verified") == 1.0
        )
        return 0 if floor_ok else 1
    return 0 if report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
