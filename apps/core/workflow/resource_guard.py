"""CPU thread resource guard for ZYRQUEN Workflow Engine (pure Python stdlib)."""

from __future__ import annotations

import os

MAX_CPU_THREADS = 2


def enforce_cpu_thread_cap(max_threads: int = MAX_CPU_THREADS) -> int:
    """Cap BLAS/OpenMP thread environment variables to prevent CPU oversubscription."""
    cap = max(1, int(max_threads))
    cap_str = str(cap)
    for var in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "TORCH_NUM_THREADS",
    ):
        os.environ.setdefault(var, cap_str)
    return cap
