#!/usr/bin/env python3
"""Colab TPU / TorchTPU / PJRT / PyTorch runtime probe for ZYRQUEN.

Detects modern Colab TorchTPU (PyTorch 2.14+ / v5e-1 TPU / v6e-1 TPU),
legacy XLA (COLAB_TPU_ADDR / torch_xla), CUDA GPU, or CPU fallback without
installing extra packages or crashing when torch/torch_xla are absent.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _probe_tpu_device_nodes() -> List[str]:
    dev_dir = Path("/dev")
    if not dev_dir.is_dir():
        return []
    nodes: List[str] = []
    for pattern in ("accel*", "vfio/*"):
        for match in sorted(dev_dir.glob(pattern)):
            nodes.append(str(match))
    return nodes


def detect_runtime_accelerator() -> Dict[str, Any]:
    tpu_addr = os.environ.get("COLAB_TPU_ADDR") or os.environ.get("TPU_NAME") or None
    pjrt_device = os.environ.get("PJRT_DEVICE") or None
    tpu_type = os.environ.get("TPU_ACCELERATOR_TYPE") or os.environ.get("ACCELERATOR_TYPE") or None
    device_nodes = _probe_tpu_device_nodes()

    torch_version: Optional[str] = None
    accelerator: Optional[str] = None
    device_count = 0
    backend_detail = "python-stdlib"
    xla_available = False

    try:
        import torch  # type: ignore

        torch_version = str(getattr(torch, "__version__", "unknown"))
        # TorchTPU / PyTorch 2.14+ or XLA check
        torch_tpu = getattr(torch, "tpu", None)
        if torch_tpu is not None and callable(getattr(torch_tpu, "is_available", None)):
            if torch_tpu.is_available():
                accelerator = "TPU"
                device_count = int(torch_tpu.device_count()) if callable(getattr(torch_tpu, "device_count", None)) else 1
                backend_detail = "torch.tpu"
                xla_available = True

        if accelerator is None:
            try:
                import torch_xla.runtime as xr  # type: ignore

                count = int(xr.global_device_count())
                if count > 0:
                    accelerator = "TPU"
                    device_count = count
                    backend_detail = f"torch_xla.runtime ({xr.device_type()})"
                    xla_available = True
            except Exception:
                try:
                    import torch_xla.core.xla_model as xm  # type: ignore

                    dev = xm.xla_device()
                    if "xla" in str(dev).lower() or "tpu" in str(dev).lower():
                        accelerator = "TPU"
                        device_count = 1
                        backend_detail = f"torch_xla.xla_model ({dev})"
                        xla_available = True
                except Exception:
                    pass

        if accelerator is None and torch.cuda.is_available():
            accelerator = "GPU"
            device_count = int(torch.cuda.device_count())
            backend_detail = f"cuda ({torch.cuda.get_device_name(0)})"
        elif accelerator is None:
            backend_detail = "torch-cpu"
    except ImportError:
        torch_version = None

    if accelerator is None and (pjrt_device == "TPU" or tpu_addr or device_nodes):
        accelerator = "TPU"
        device_count = max(1, len(device_nodes))
        backend_detail = "env/device-node"

    return {
        "python_version": sys.version.split()[0],
        "torch_version": torch_version,
        "accelerator": accelerator,
        "device_count": device_count,
        "tpu_address": tpu_addr,
        "pjrt_device": pjrt_device,
        "tpu_accelerator_type": tpu_type,
        "tpu_device_nodes": device_nodes,
        "xla_or_torchtpu_ready": xla_available,
        "backend_detail": backend_detail,
        "pure_native_v2_ready": True,
        "pure_native_v2_note": (
            "PureNativeTransformerLMV2 runs in Pure Python CPU and can continue "
            "training checkpoints regardless of TPU/GPU allocation."
        ),
    }


def format_runtime_report(info: Dict[str, Any]) -> str:
    lines = [
        "=== ZYRQUEN Runtime / TPU Diagnostic ===",
        f"Python          : {info['python_version']}",
        f"PyTorch         : {info['torch_version'] or 'not installed (Pure Python mode)'}",
        f"Accelerator     : {info['accelerator']}",
        f"Device count    : {info['device_count']}",
        f"TPU address     : {info['tpu_address']}",
        f"PJRT_DEVICE     : {info['pjrt_device']}",
        f"TPU type        : {info['tpu_accelerator_type']}",
        f"Backend         : {info['backend_detail']}",
        f"Pure Native V2  : ready={info['pure_native_v2_ready']} (CPU Pure Python)",
    ]
    if info["accelerator"] is None and info["torch_version"] and "+cpu" in info["torch_version"]:
        lines.append(
            "Hint            : Colab returned CPU PyTorch without TPU allocation. "
            "Check Runtime -> Change runtime type -> v5e-1 TPU / v6e-1 TPU, or continue "
            "PureNativeTransformerLMV2 training directly on CPU."
        )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect Colab TPU / TorchTPU / GPU / CPU runtime status.")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args(argv)

    info = detect_runtime_accelerator()
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print(format_runtime_report(info))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
