#!/usr/bin/env python3
"""ZYRQUEN TPU Compatibility & Readiness Suite (`ชุด TPU`).

Runs safe, non-destructive verification across:
1. Colab TorchTPU / XLA / CUDA / CPU hardware & env probe.
2. Pure Python V2 continual-learning forward/backward/checkpoint smoke test.
3. TorchTPU/XLA device-resolver compatibility checks (without mutating existing checkpoints).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON_CORE = REPO_ROOT / "python_core"
for p in (str(PYTHON_CORE), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools.tpu_probe import detect_runtime_accelerator, format_runtime_report  # noqa: E402
from v2.zyrquen_v2_pure import (  # noqa: E402
    PureContinualTrainerV2,
    PureNativeTransformerLMV2,
    PureZyrquenV2Config,
)
from v2.zyrquen_v2_trainer import ByteTokenizer  # noqa: E402


def run_pure_native_smoke() -> Dict[str, Any]:
    tok = ByteTokenizer()
    cfg = PureZyrquenV2Config(
        vocab_size=258,
        d_model=8,
        n_heads=2,
        n_layers=1,
        d_ff=16,
        base_seq_len=8,
        max_seq_len=16,
        seed=7,
    )
    model = PureNativeTransformerLMV2(cfg)
    trainer = PureContinualTrainerV2(model, tok)
    texts = ["zyrquen tpu readiness smoke", "native continual learning"]
    stats = trainer.train_steps(texts, steps=2, batch_size=2, replay_ratio=0.0)
    with tempfile.TemporaryDirectory() as tmp:
        ckpt = Path(tmp) / "smoke.json.gz"
        _, sha = trainer.save_checkpoint(ckpt)
        reloaded = PureContinualTrainerV2.load_checkpoint(
            ckpt,
            tok,
            expected_sha256=sha,
            resume_optimizer=True,
            restore_continual_state=True,
        )
    return {
        "passed": reloaded.global_step == 2,
        "global_step": reloaded.global_step,
        "final_loss": stats["final_loss"],
        "sha256": sha,
    }


def run_torch_tpu_smoke(runtime_info: Dict[str, Any]) -> Dict[str, Any]:
    if not runtime_info.get("torch_version"):
        return {
            "executed": False,
            "reason": "PyTorch not installed; Pure Native V2 active.",
        }

    from v2.tpu_backend import is_tpu_device, resolve_torch_device, tpu_sync_step
    from v2.zyrquen_v2_model import NativeTransformerLMV2, ZyrquenV2Config
    from v2.zyrquen_v2_trainer import ContinualTrainerV2

    dev = resolve_torch_device()
    tok = ByteTokenizer()
    cfg = ZyrquenV2Config(
        vocab_size=258,
        d_model=16,
        n_heads=2,
        n_layers=1,
        d_ff=32,
        base_seq_len=16,
        max_seq_len=32,
    )
    model = NativeTransformerLMV2(cfg)
    trainer = ContinualTrainerV2(model, tok, device=dev)
    stats = trainer.train_steps(
        ["zyrquen torchtpu probe", "continual trainer verification"],
        steps=1,
        batch_size=2,
        replay_ratio=0.0,
    )
    tpu_sync_step(dev)
    return {
        "executed": True,
        "device": str(dev),
        "is_tpu": is_tpu_device(dev),
        "global_step": trainer.global_step,
        "final_loss": stats["final_loss"],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run ZYRQUEN TPU Compatibility & Readiness Suite.")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    args = parser.parse_args(argv)

    runtime_info = detect_runtime_accelerator()
    pure_res = run_pure_native_smoke()
    torch_res = run_torch_tpu_smoke(runtime_info)

    summary = {
        "runtime": runtime_info,
        "pure_native_v2_smoke": pure_res,
        "torch_trainer_smoke": torch_res,
        "all_ready": bool(pure_res["passed"]),
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(format_runtime_report(runtime_info))
        print(f"Pure Native V2 Smoke : passed={pure_res['passed']} | step={pure_res['global_step']} | loss={pure_res['final_loss']}")
        print(f"Torch/TPU Smoke      : {torch_res}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
