"""Device resolution and synchronization helpers for ZYRQUEN V2.

Supports modern Colab TorchTPU (`torch.tpu` / `torch_tpu`), PyTorch XLA
(`torch_xla`), CUDA GPU, and CPU fallback without requiring external packages.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def _import_torch() -> Any:
    import torch

    return torch


def resolve_torch_device(
    explicit_device: Optional[Any] = None,
    *,
    prefer_tpu: bool = True,
) -> Any:
    torch = _import_torch()
    if explicit_device is not None:
        return (
            torch.device(explicit_device)
            if isinstance(explicit_device, str)
            else explicit_device
        )

    if prefer_tpu:
        # 1. Colab TorchTPU (PyTorch 2.14+ native torch.tpu)
        torch_tpu = getattr(torch, "tpu", None)
        if torch_tpu is not None and callable(getattr(torch_tpu, "is_available", None)):
            if torch_tpu.is_available():
                return torch.device("tpu")

        # 2. Standalone torch_tpu plugin if present
        try:
            import torch_tpu  # type: ignore  # noqa: F401

            if hasattr(torch, "tpu") and torch.tpu.is_available():
                return torch.device("tpu")
        except Exception:
            pass

        # 3. PyTorch XLA (legacy / PJRT TPU)
        try:
            import torch_xla.core.xla_model as xm  # type: ignore

            return xm.xla_device()
        except Exception:
            pass

    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def is_tpu_device(device: Any) -> bool:
    label = str(device).lower()
    return label.startswith("tpu") or label.startswith("xla")


def tpu_sync_step(device: Any) -> None:
    label = str(device).lower()
    if label.startswith("tpu"):
        torch = _import_torch()
        torch_tpu = getattr(torch, "tpu", None)
        if torch_tpu is not None and callable(getattr(torch_tpu, "synchronize", None)):
            torch_tpu.synchronize()
        return
    if label.startswith("xla"):
        try:
            import torch_xla.core.xla_model as xm  # type: ignore

            xm.mark_step()
        except Exception:
            pass


def state_dict_to_cpu(state: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in state.items():
        out[k] = v.detach().cpu() if hasattr(v, "detach") else v
    return out
