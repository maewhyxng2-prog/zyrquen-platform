"""EventBus and single CentralScheduler coordinating time & event triggers."""

from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.core.workflow.orchestrator import CentralWorkflowOrchestrator


class EventBus:
    """Translates domain events into idempotent workflow runs."""

    def __init__(self, orchestrator: CentralWorkflowOrchestrator) -> None:
        self._orchestrator = orchestrator

    def emit(
        self,
        event_name: str,
        payload: dict[str, Any] | None = None,
        *,
        dedup_key: str | None = None,
        actor_id: str = "system:event_bus",
    ) -> list[str]:
        run_ids: list[str] = []
        matching = self._orchestrator.registry.find_by_event(event_name)
        for defn in matching:
            per_wf_dedup = f"{event_name}:{defn.workflow_key}:{dedup_key}" if dedup_key else None
            run = self._orchestrator.trigger_workflow(
                defn.workflow_key,
                version=defn.version,
                trigger_type="event",
                payload={"event_name": event_name, **(payload or {})},
                requested_by_user_id=None,
                actor_id=actor_id,
                dedup_key=per_wf_dedup,
                execute_async=True,
            )
            run_ids.append(run["id"])
        return run_ids


class CentralScheduler:
    """Single central scheduler loop for all periodic workflows (no duplicate cron runners)."""

    def __init__(
        self,
        orchestrator: CentralWorkflowOrchestrator,
        *,
        poll_interval_sec: float = 30.0,
    ) -> None:
        self._orchestrator = orchestrator
        self.poll_interval_sec = max(1.0, poll_interval_sec)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._tick_lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="zyrquen-central-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self.poll_interval_sec):
            try:
                self.run_due_schedules()
            except Exception:
                # Never crash background scheduler daemon
                pass

    def run_due_schedules(self, now: datetime | None = None) -> list[str]:
        now_dt = now or datetime.now(timezone.utc)
        triggered: list[str] = []
        with self._tick_lock:
            for defn in self._orchestrator.registry.list_scheduled():
                interval = defn.schedule_interval_sec
                if interval is None or interval <= 0:
                    continue
                last = self._orchestrator.store.get_scheduler_last_run(defn.workflow_key)
                if last is not None and (now_dt - last).total_seconds() < interval:
                    continue
                dedup_slot = int(now_dt.timestamp() // interval)
                dedup = f"sched:{defn.workflow_key}:{dedup_slot}"
                run = self._orchestrator.trigger_workflow(
                    defn.workflow_key,
                    version=defn.version,
                    trigger_type="schedule",
                    payload={"scheduled_slot": dedup_slot, "interval_sec": interval},
                    requested_by_user_id=None,
                    actor_id="system:central_scheduler",
                    dedup_key=dedup,
                    execute_async=True,
                )
                self._orchestrator.store.set_scheduler_last_run(defn.workflow_key, now_dt)
                triggered.append(run["id"])
        return triggered
