from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional


VALID_RUN_STATUSES = ("QUEUED", "RUNNING", "PASS", "FAIL", "BLOCKED", "CANCELLED")
VALID_ISOLATION_MODES = (
    "isolated_db",
    "docker_ephemeral",
    "sqlite_sandbox",
    "archive_sandbox",
)
VALID_BACKUP_FORMATS = (
    "postgresql_custom",
    "sqlite_dump",
    "archive_zip",
    "archive_tar",
)
VALID_PRIORITIES = ("high", "normal", "low")
SAFE_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{4,64}$")
SAFE_ENTITY_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{2,64}$")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class StepRecord:
    step_key: str
    status: str  # "PASS" | "FAIL" | "BLOCKED" | "NOT_RUN" | "RUNNING" | "CANCELLED"
    duration_sec: Optional[float]
    detail: str


@dataclass
class RunRecord:
    run_id: str
    source_name: str
    backup_format: str
    backup_uri: str
    target_dbname: str
    min_total_rows: int
    required_tables: List[str]
    expected_sha256: Optional[str]
    status: str  # "QUEUED" | "RUNNING" | "PASS" | "FAIL" | "BLOCKED" | "CANCELLED"
    started_at: str
    isolation_mode: str = "isolated_db"
    drop_after_verify: bool = True
    finished_at: Optional[str] = None
    duration_sec: Optional[float] = None
    steps: List[StepRecord] = field(default_factory=list)
    discrepancies: List[str] = field(default_factory=list)
    report: Optional[Dict[str, Any]] = None
    priority: str = "normal"
    worker_id: str = "worker-local-01"
    operator: str = "system"
    attempt: int = 1
    max_retries: int = 1
    parent_run_id: Optional[str] = None
    timeout_sec: float = 120.0
    logs_tail: List[str] = field(default_factory=list)
    cancel_requested: bool = False
    backup_source_id: Optional[str] = None
    target_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BackupSource:
    id: str
    name: str
    backup_format: str
    uri: str
    size_bytes: int
    sha256: str
    baseline_sha256: str
    file_count: int
    manifest_hashes: Dict[str, str] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    last_checked_at: Optional[str] = None
    last_check_status: str = "NOT_RUN"  # "PASS" | "FAIL" | "BLOCKED" | "NOT_RUN"
    last_discrepancies: List[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RestoreTarget:
    id: str
    name: str
    engine: str  # "sqlite" | "postgresql" | "archive"
    isolation_mode: str
    target_dbname: str
    host: str = "127.0.0.1"
    port: int = 5432
    user: str = "restoreproof_user"
    drop_after_verify: bool = True
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkerNode:
    id: str
    name: str
    endpoint: str
    isolation_modes: List[str] = field(default_factory=lambda: ["sqlite_sandbox", "archive_sandbox", "isolated_db"])
    max_concurrent: int = 2
    status: str = "ONLINE"
    last_heartbeat: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SecurityPolicies:
    require_sha256_match: bool = True
    auto_cleanup_ephemeral: bool = True
    reserved_db_blocklist: List[str] = field(
        default_factory=lambda: ["postgres", "template0", "template1", "zyrquen", "production", "prod"]
    )
    default_timeout_sec: float = 120.0
    default_max_retries: int = 1
    alert_on_fail: bool = True
    alert_on_blocked: bool = True
    require_approval_for_assistant_mutations: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuditEntry:
    id: str
    timestamp: str
    actor: str
    action: str
    target: str
    outcome: str
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
