from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional

try:
    from .models import (
        AuditEntry,
        BackupSource,
        RestoreTarget,
        RunRecord,
        SAFE_ENTITY_ID_RE,
        SAFE_RUN_ID_RE,
        SecurityPolicies,
        StepRecord,
        WorkerNode,
        utc_now_iso,
    )
except ImportError:
    from models import (
        AuditEntry,
        BackupSource,
        RestoreTarget,
        RunRecord,
        SAFE_ENTITY_ID_RE,
        SAFE_RUN_ID_RE,
        SecurityPolicies,
        StepRecord,
        WorkerNode,
        utc_now_iso,
    )


class EvidenceStore:
    """Persists runs, evidence reports, backups, targets, workers, policies, and audit logs on disk."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.runs_dir = self.data_dir / "runs"
        self.backups_vault_dir = self.data_dir / "backups_vault"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.backups_vault_dir.mkdir(parents=True, exist_ok=True)
        self._backups_file = self.data_dir / "backups.json"
        self._targets_file = self.data_dir / "targets.json"
        self._workers_file = self.data_dir / "workers.json"
        self._policies_file = self.data_dir / "policies.json"
        self._audit_file = self.data_dir / "audit.jsonl"
        self._assistant_file = self.data_dir / "assistant_history.json"
        self._lock = threading.Lock()
        self._runs: Dict[str, RunRecord] = {}
        self._backups: Dict[str, BackupSource] = {}
        self._targets: Dict[str, RestoreTarget] = {}
        self._workers: Dict[str, WorkerNode] = {}
        self._policies = SecurityPolicies()
        self._assistant_history: List[Dict[str, Any]] = []
        self._load_existing()

    def _run_file(self, run_id: str) -> Path:
        if not SAFE_RUN_ID_RE.match(run_id):
            raise ValueError(f"Invalid run_id: {run_id!r}")
        return self.runs_dir / f"{run_id}.json"

    @staticmethod
    def _atomic_write_json(path: Path, payload: Any) -> None:
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp_path.replace(path)

    def _load_existing(self) -> None:
        for p in sorted(self.runs_dir.glob("*.json")):
            raw = json.loads(p.read_text(encoding="utf-8"))
            steps = [StepRecord(**s) for s in raw.get("steps", [])]
            rec = RunRecord(
                run_id=raw["run_id"],
                source_name=raw["source_name"],
                backup_format=raw["backup_format"],
                backup_uri=raw["backup_uri"],
                target_dbname=raw["target_dbname"],
                min_total_rows=int(raw.get("min_total_rows", 0)),
                required_tables=list(raw.get("required_tables", [])),
                expected_sha256=raw.get("expected_sha256"),
                status=raw["status"],
                started_at=raw["started_at"],
                isolation_mode=raw.get("isolation_mode", "isolated_db"),
                drop_after_verify=bool(raw.get("drop_after_verify", True)),
                finished_at=raw.get("finished_at"),
                duration_sec=raw.get("duration_sec"),
                steps=steps,
                discrepancies=list(raw.get("discrepancies", [])),
                report=raw.get("report"),
                priority=str(raw.get("priority", "normal")),
                worker_id=str(raw.get("worker_id", "worker-local-01")),
                operator=str(raw.get("operator", "system")),
                attempt=int(raw.get("attempt", 1)),
                max_retries=int(raw.get("max_retries", 1)),
                parent_run_id=raw.get("parent_run_id"),
                timeout_sec=float(raw.get("timeout_sec", 120.0)),
                logs_tail=list(raw.get("logs_tail", [])),
                cancel_requested=bool(raw.get("cancel_requested", False)),
                backup_source_id=raw.get("backup_source_id"),
                target_id=raw.get("target_id"),
            )
            self._runs[rec.run_id] = rec

        if self._backups_file.exists():
            raw_b = json.loads(self._backups_file.read_text(encoding="utf-8"))
            for item in raw_b:
                obj = BackupSource(**item)
                self._backups[obj.id] = obj

        if self._targets_file.exists():
            raw_t = json.loads(self._targets_file.read_text(encoding="utf-8"))
            for item in raw_t:
                obj = RestoreTarget(**item)
                self._targets[obj.id] = obj
        else:
            self._seed_default_targets()

        if self._workers_file.exists():
            raw_w = json.loads(self._workers_file.read_text(encoding="utf-8"))
            for item in raw_w:
                obj = WorkerNode(**item)
                self._workers[obj.id] = obj
        else:
            self._seed_default_workers()

        if self._policies_file.exists():
            raw_p = json.loads(self._policies_file.read_text(encoding="utf-8"))
            self._policies = SecurityPolicies(**raw_p)

        if self._assistant_file.exists():
            raw_a = json.loads(self._assistant_file.read_text(encoding="utf-8"))
            if isinstance(raw_a, list):
                self._assistant_history = raw_a[-100:]

    def _seed_default_targets(self) -> None:
        t1 = RestoreTarget(
            id="target-sqlite-sandbox",
            name="SQLite Isolated Sandbox (Local)",
            engine="sqlite",
            isolation_mode="sqlite_sandbox",
            target_dbname="rp_verify_sqlite_sandbox",
            host="127.0.0.1",
            port=0,
            user="sandbox",
            drop_after_verify=True,
        )
        t2 = RestoreTarget(
            id="target-pg-isolated",
            name="PostgreSQL Ephemeral DB (Isolated)",
            engine="postgresql",
            isolation_mode="isolated_db",
            target_dbname="rp_verify_pg_isolated",
            host="127.0.0.1",
            port=5432,
            user="restoreproof_user",
            drop_after_verify=True,
        )
        self._targets[t1.id] = t1
        self._targets[t2.id] = t2
        self._atomic_write_json(
            self._targets_file, [t.to_dict() for t in self._targets.values()]
        )

    def _seed_default_workers(self) -> None:
        w1 = WorkerNode(
            id="worker-local-01",
            name="Local Isolated Worker #1",
            endpoint="local://python3-sandbox",
            isolation_modes=["sqlite_sandbox", "archive_sandbox", "isolated_db"],
            max_concurrent=2,
            status="ONLINE",
            last_heartbeat=utc_now_iso(),
        )
        self._workers[w1.id] = w1
        self._atomic_write_json(
            self._workers_file, [w.to_dict() for w in self._workers.values()]
        )

    def save(self, record: RunRecord) -> None:
        with self._lock:
            target = self._run_file(record.run_id)
            self._runs[record.run_id] = record
            self._atomic_write_json(target, record.to_dict())

    def get(self, run_id: str) -> Optional[RunRecord]:
        if not SAFE_RUN_ID_RE.match(run_id):
            return None
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(
        self,
        status_filter: Optional[str] = None,
        priority_filter: Optional[str] = None,
        limit: int = 20,
    ) -> List[RunRecord]:
        with self._lock:
            items = list(self._runs.values())
        items.sort(key=lambda r: r.started_at, reverse=True)
        if status_filter:
            items = [r for r in items if r.status == status_filter]
        if priority_filter:
            items = [r for r in items if r.priority == priority_filter]
        return items[: max(1, min(limit, 200))]

    def save_backup(self, backup: BackupSource) -> BackupSource:
        if not SAFE_ENTITY_ID_RE.match(backup.id):
            raise ValueError(f"Invalid backup id: {backup.id!r}")
        with self._lock:
            self._backups[backup.id] = backup
            self._atomic_write_json(
                self._backups_file, [b.to_dict() for b in self._backups.values()]
            )
        return backup

    def get_backup(self, backup_id: str) -> Optional[BackupSource]:
        if not SAFE_ENTITY_ID_RE.match(backup_id):
            return None
        with self._lock:
            return self._backups.get(backup_id)

    def list_backups(self) -> List[BackupSource]:
        with self._lock:
            items = list(self._backups.values())
        items.sort(key=lambda b: b.created_at, reverse=True)
        return items

    def delete_backup(self, backup_id: str) -> bool:
        if not SAFE_ENTITY_ID_RE.match(backup_id):
            return False
        with self._lock:
            if backup_id not in self._backups:
                return False
            self._backups.pop(backup_id)
            self._atomic_write_json(
                self._backups_file, [b.to_dict() for b in self._backups.values()]
            )
            return True

    def save_target(self, target: RestoreTarget) -> RestoreTarget:
        if not SAFE_ENTITY_ID_RE.match(target.id):
            raise ValueError(f"Invalid target id: {target.id!r}")
        with self._lock:
            self._targets[target.id] = target
            self._atomic_write_json(
                self._targets_file, [t.to_dict() for t in self._targets.values()]
            )
        return target

    def get_target(self, target_id: str) -> Optional[RestoreTarget]:
        if not SAFE_ENTITY_ID_RE.match(target_id):
            return None
        with self._lock:
            return self._targets.get(target_id)

    def list_targets(self) -> List[RestoreTarget]:
        with self._lock:
            return list(self._targets.values())

    def delete_target(self, target_id: str) -> bool:
        if not SAFE_ENTITY_ID_RE.match(target_id):
            return False
        with self._lock:
            if target_id not in self._targets:
                return False
            self._targets.pop(target_id)
            self._atomic_write_json(
                self._targets_file, [t.to_dict() for t in self._targets.values()]
            )
            return True

    def save_worker(self, worker: WorkerNode) -> WorkerNode:
        if not SAFE_ENTITY_ID_RE.match(worker.id):
            raise ValueError(f"Invalid worker id: {worker.id!r}")
        with self._lock:
            self._workers[worker.id] = worker
            self._atomic_write_json(
                self._workers_file, [w.to_dict() for w in self._workers.values()]
            )
        return worker

    def list_workers(self) -> List[WorkerNode]:
        with self._lock:
            return list(self._workers.values())

    def get_policies(self) -> SecurityPolicies:
        with self._lock:
            return SecurityPolicies(**self._policies.to_dict())

    def save_policies(self, policies: SecurityPolicies) -> SecurityPolicies:
        with self._lock:
            self._policies = policies
            self._atomic_write_json(self._policies_file, policies.to_dict())
        return policies

    def append_audit(self, entry: AuditEntry) -> None:
        with self._lock:
            with self._audit_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    def list_audit(self, limit: int = 50) -> List[AuditEntry]:
        with self._lock:
            if not self._audit_file.exists():
                return []
            lines = [ln.strip() for ln in self._audit_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        out: List[AuditEntry] = []
        for ln in reversed(lines[-max(1, min(limit, 500)):]):
            try:
                out.append(AuditEntry(**json.loads(ln)))
            except Exception:
                continue
        return out

    def append_assistant_event(self, event: Dict[str, Any]) -> None:
        with self._lock:
            self._assistant_history.append(event)
            self._assistant_history = self._assistant_history[-100:]
            self._atomic_write_json(self._assistant_file, self._assistant_history)

    def list_assistant_history(self, limit: int = 30) -> List[Dict[str, Any]]:
        with self._lock:
            return list(reversed(self._assistant_history[-max(1, min(limit, 100)):]))
