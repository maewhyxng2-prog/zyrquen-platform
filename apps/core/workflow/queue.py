"""Dual-lane ThreadPool task dispatcher isolating compute_heavy and control_ops workloads."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import threading
from typing import Callable, TypeVar

from apps.core.workflow.models import WorkflowValidationError

T = TypeVar("T")


class DualLaneTaskQueue:
    """Separates heavy training/evaluation from lightweight control/audit operations."""

    def __init__(self, *, control_workers: int = 2, compute_workers: int = 1) -> None:
        self._control = ThreadPoolExecutor(
            max_workers=max(1, control_workers),
            thread_name_prefix="zyrquen-wf-control",
        )
        self._compute = ThreadPoolExecutor(
            max_workers=max(1, compute_workers),
            thread_name_prefix="zyrquen-wf-compute",
        )
        self._lock = threading.Lock()
        self._active_runs: dict[str, Future] = {}

    def submit(self, run_id: str, lane: str, fn: Callable[..., T], *args, **kwargs) -> Future[T]:
        if lane == "compute_heavy":
            pool = self._compute
        elif lane == "control_ops":
            pool = self._control
        else:
            raise WorkflowValidationError(f"Unknown execution lane: {lane!r}")

        fut = pool.submit(fn, *args, **kwargs)
        with self._lock:
            self._active_runs[run_id] = fut

        def _cleanup(_f: Future) -> None:
            with self._lock:
                if self._active_runs.get(run_id) is fut:
                    self._active_runs.pop(run_id, None)

        fut.add_done_callback(_cleanup)
        return fut

    def is_run_active(self, run_id: str) -> bool:
        with self._lock:
            fut = self._active_runs.get(run_id)
            return fut is not None and not fut.done()

    def active_run_ids(self) -> list[str]:
        with self._lock:
            return [rid for rid, fut in self._active_runs.items() if not fut.done()]

    def shutdown(self, wait: bool = True) -> None:
        self._control.shutdown(wait=wait)
        self._compute.shutdown(wait=wait)
