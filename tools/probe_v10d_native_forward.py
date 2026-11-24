#!/usr/bin/env python3
"""Read-only CPU forward probe for the V10 native model and real SFT samples.

This probe performs no backward pass, optimizer step, checkpoint write, registry
mutation, workflow approval, or training. It validates model construction and
teacher-forced forward/loss computation only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.core.native.config import MAX_V10_PARAMETERS, ZyrquenConfig
from apps.core.native.dataset import load_sft_split
from apps.core.native.model import ZyrquenModel
from apps.core.native.sft import build_sft_pairs, collate_sft_batch
from apps.core.native.tokenizer import SCHEMA_V2, ZyrquenTokenizer
from apps.core.workflow.resource_guard import (
    RAM_HARD_LIMIT_GB,
    check_torch_cpu_runtime,
    enforce_cpu_thread_cap,
    read_process_rss_bytes,
)

SCHEMA = "zyrquen.v10d.native_forward_probe.v1"


def _state_fingerprint(model: Any) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        digest.update(name.encode("utf-8"))
        digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def run_probe(
    *,
    dataset_dir: Path,
    tokenizer_path: Path,
    batch_size: int = 4,
    cpu_threads: int = 2,
) -> dict[str, Any]:
    if batch_size < 1 or batch_size > 4:
        raise ValueError("batch_size must be within 1..4")
    if cpu_threads < 1 or cpu_threads > 2:
        raise ValueError("cpu_threads must be within 1..2")
    if dataset_dir.is_symlink() or not dataset_dir.is_dir():
        raise FileNotFoundError(f"dataset directory missing or symlinked: {dataset_dir}")
    if tokenizer_path.is_symlink() or not tokenizer_path.is_file():
        raise FileNotFoundError(f"tokenizer missing or symlinked: {tokenizer_path}")

    import torch

    runtime = check_torch_cpu_runtime()
    if not runtime.get("available") or runtime.get("cuda_available"):
        raise RuntimeError(f"CPU-only PyTorch runtime unavailable: {runtime}")
    enforce_cpu_thread_cap(cpu_threads, torch_mod=torch)

    tokenizer = ZyrquenTokenizer.load(tokenizer_path)
    if tokenizer.schema != SCHEMA_V2 or not tokenizer.supports_atomic_slots:
        raise ValueError("V10 requires tokenizer schema V2 with atomic slots")

    train_rows = list(load_sft_split(dataset_dir, "train"))[:batch_size]
    val_rows = list(load_sft_split(dataset_dir, "validation"))[:batch_size]
    if len(train_rows) != batch_size or not val_rows:
        raise ValueError("insufficient real train/validation records for forward probe")

    train_pairs = build_sft_pairs(train_rows, tokenizer, max_seq_len=256, use_slots=True)
    val_pairs = build_sft_pairs(val_rows, tokenizer, max_seq_len=256, use_slots=True)
    x_rows, y_rows = collate_sft_batch(
        val_pairs, pad_id=tokenizer.pad_id, max_seq_len=256
    )
    x = torch.tensor(x_rows, dtype=torch.long, device="cpu")
    y = torch.tensor(y_rows, dtype=torch.long, device="cpu")

    config = ZyrquenConfig(
        vocab_size=tokenizer.vocab_size,
        max_seq_len=256,
        n_layers=4,
        n_heads=4,
        d_model=256,
        d_ff=704,
        dropout=0.0,
        tie_embeddings=True,
    )
    params = config.validate_parameter_budget(MAX_V10_PARAMETERS)
    model = ZyrquenModel(config).to("cpu")
    model.eval()
    before = _state_fingerprint(model)
    rss_before = read_process_rss_bytes() / (1024 ** 3)

    with torch.inference_mode():
        logits, loss = model(x, y)

    after = _state_fingerprint(model)
    rss_after = read_process_rss_bytes() / (1024 ** 3)
    finite_logits = bool(torch.isfinite(logits).all().item())
    finite_loss = bool(loss is not None and torch.isfinite(loss).item())
    unchanged = before == after
    within_ram = 0 < rss_after < RAM_HARD_LIMIT_GB

    checks = {
        "cpu_runtime": True,
        "tokenizer_v2_atomic_slots": True,
        "real_sft_samples_loaded": len(train_pairs) == batch_size and len(val_pairs) == batch_size,
        "model_parameter_budget": params <= MAX_V10_PARAMETERS,
        "logits_shape": list(logits.shape) == [batch_size, x.shape[1], tokenizer.vocab_size],
        "finite_logits": finite_logits,
        "finite_teacher_forced_loss": finite_loss,
        "inference_mode_no_grad": not logits.requires_grad and not loss.requires_grad,
        "weights_unchanged": unchanged,
        "ram_below_hard_limit": within_ram,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "schema": SCHEMA,
        "overall_status": "PASS" if not failed else "FAIL",
        "checks": checks,
        "failed_checks": failed,
        "runtime": {
            "torch_version": str(torch.__version__),
            "device": "cpu",
            "cpu_threads": int(torch.get_num_threads()),
            "cuda_available": bool(torch.cuda.is_available()),
        },
        "model": {
            "type": config.model_type,
            "initialization": "random_native_initialization",
            "parameters": int(model.num_parameters()),
            "config": config.to_dict(),
            "weights_sha256_before": before,
            "weights_sha256_after": after,
        },
        "data": {
            "dataset_dir": str(dataset_dir),
            "tokenizer_path": str(tokenizer_path),
            "tokenizer_fingerprint": tokenizer.fingerprint(),
            "train_probe_examples": len(train_pairs),
            "validation_probe_examples": len(val_pairs),
            "batch_shape": list(x.shape),
            "target_supervised_tokens": int((y != -100).sum().item()),
        },
        "resources": {
            "rss_before_gb": round(rss_before, 4),
            "rss_after_gb": round(rss_after, 4),
            "ram_hard_limit_gb": RAM_HARD_LIMIT_GB,
        },
        "training_invoked": False,
        "backward_invoked": False,
        "optimizer_step_invoked": False,
        "checkpoint_written": False,
        "registry_modified": False,
        "approval_consumed": False,
        "scope_note": "Forward-only random-initialized model probe; not training, not a trained-model capability evaluation, and not Tier-2 authorization.",
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Read-only V10-D native CPU forward probe.")
    parser.add_argument("--dataset-dir", type=Path, default=ROOT / "artifacts" / "v10d_closure" / "data" / "nagi_v10")
    parser.add_argument("--tokenizer-path", type=Path, default=ROOT / "artifacts" / "v10d_closure" / "tokenizer" / "tokenizer.json")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--cpu-threads", type=int, default=2)
    args = parser.parse_args()
    try:
        result = run_probe(
            dataset_dir=args.dataset_dir,
            tokenizer_path=args.tokenizer_path,
            batch_size=args.batch_size,
            cpu_threads=args.cpu_threads,
        )
    except Exception as exc:
        result = {
            "schema": SCHEMA,
            "overall_status": "BLOCKED",
            "error": f"{type(exc).__name__}: {exc}",
            "training_invoked": False,
            "backward_invoked": False,
            "optimizer_step_invoked": False,
            "checkpoint_written": False,
            "registry_modified": False,
            "approval_consumed": False,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("overall_status") == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
