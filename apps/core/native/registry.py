"""Phase 3.5 / Phase 10 Gate 2: model registry and versioning for ZYRQUEN native model.

A registered version is an immutable snapshot: a copy of a verified checkpoint plus the
exact tokenizer file and dataset manifest it was trained with, linked by SHA-256.
Reuses CheckpointManager (Phase 4) for checkpoint verification; does not duplicate it.
Standard library only (checkpoint loading is injected, default torch).

Concurrency & Filesystem Boundary:
- Within a single host, ModelRegistry serializes allocations and registry.json writes
  via an in-process RLock + POSIX advisory file lock (fcntl.flock on .registry.lock)
  plus O_CREAT | O_EXCL reservation files under .reservations/.
- Limitation on Shared / Network Volumes (NFS, CIFS/SMB, object-storage FUSE):
  POSIX fcntl.flock() is advisory and may not coordinate across separate hosts if the
  volume is mounted with nolock/local_lock or lacks distributed lock semantics. In
  multi-node deployments sharing a network volume, coordinate registration via a single
  training coordinator or database-level advisory locks.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
import re
import secrets
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None

from apps.core.native.tokenizer import ZyrquenTokenizer
from apps.core.training_infrastructure.recovery.checkpoint_recovery import (
    CheckpointManager, _safe_torch_load)

SCHEMA = "zyrquen.model-registry.v1"
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
NATIVE_MODEL_VERSION_RE = re.compile(
    r"^ZYRQUEN-Native-(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
)
SPLITS = ("train", "validation", "test")
LIFECYCLE_STATES = (
    "development",
    "registered",
    "evaluated",
    "verified",
    "staging",
    "production",
    "quarantined",
    "archived",
)
PROMOTABLE_LIFECYCLE_STATES = ("verified", "staging", "production")

@dataclass
class _InProcessLockState:
    rlock: threading.RLock
    depth: int = 0


_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[Path, _InProcessLockState] = {}


def _get_lock_state(root: Path) -> _InProcessLockState:
    resolved = root.resolve()
    with _THREAD_LOCKS_GUARD:
        state = _THREAD_LOCKS.get(resolved)
        if state is None:
            state = _InProcessLockState(rlock=threading.RLock())
            _THREAD_LOCKS[resolved] = state
        return state


@dataclass(frozen=True)
class NativeVersionReservation:
    version: str
    parent: str | None
    token: str


class RegistryError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_dataset(dataset_dir: Path) -> dict:
    """Re-verify every split file and the content hash against the dataset manifest."""
    mpath = dataset_dir / "manifest.json"
    if not mpath.is_file():
        raise RegistryError("dataset manifest.json not found")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    files = manifest.get("files", {})
    for split in SPLITS:
        entry = files.get(f"{split}.jsonl")
        path = dataset_dir / f"{split}.jsonl"
        if entry is None or not path.is_file() or _sha256(path) != entry["sha256"]:
            raise RegistryError(f"dataset integrity check failed: {split}.jsonl")
    combined = hashlib.sha256("".join(files[f"{s}.jsonl"]["sha256"] for s in SPLITS).encode()).hexdigest()
    if combined != manifest.get("content_sha256"):
        raise RegistryError("dataset content hash does not match manifest")
    return manifest


class ModelRegistry:
    def __init__(self, root: str | Path, load_fn: Callable[[str], Any] = _safe_torch_load):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._load = load_fn
        self._lock_state = _get_lock_state(self.root)

    @contextmanager
    def _registry_lock(self):
        with self._lock_state.rlock:
            if self._lock_state.depth > 0:
                self._lock_state.depth += 1
                try:
                    yield
                finally:
                    self._lock_state.depth -= 1
                return

            self.root.mkdir(parents=True, exist_ok=True)
            lock_path = self.root / ".registry.lock"
            if lock_path.is_symlink():
                raise RegistryError("refusing symlinked registry lock file")
            if fcntl is None:  # pragma: no cover
                self._lock_state.depth = 1
                try:
                    yield
                finally:
                    self._lock_state.depth = 0
                return
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                self._lock_state.depth = 1
                try:
                    yield
                finally:
                    self._lock_state.depth = 0
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    # ---- persistence ----
    @property
    def _path(self) -> Path:
        return self.root / "registry.json"

    @property
    def _reservations_dir(self) -> Path:
        return self.root / ".reservations"

    def _reservation_file(self, version: str) -> Path:
        if not _VERSION.match(version):
            raise RegistryError("invalid version name (use letters, digits, . _ - ; max 64 chars)")
        return self._reservations_dir / f"{version}.json"

    def _read_reservations_unlocked(self) -> dict[str, dict]:
        rdir = self._reservations_dir
        if not rdir.is_dir():
            return {}
        out: dict[str, dict] = {}
        for item in sorted(rdir.glob("*.json")):
            if item.is_symlink():
                continue
            try:
                payload = json.loads(item.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                out[item.stem] = {"version": item.stem}
                continue
            ver = payload.get("version") if isinstance(payload, dict) else None
            out[ver if isinstance(ver, str) and ver else item.stem] = payload
        return out

    def _read(self) -> dict:
        if not self._path.is_file():
            return {"schema": SCHEMA, "versions": {}, "active": None, "history": []}
        data = json.loads(self._path.read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA:
            raise RegistryError("unsupported registry schema")
        return data

    def _write(self, data: dict) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._path)

    def _highest_registered_native_version(self, data: dict) -> str | None:
        parsed: list[tuple[int, int, int, str]] = []
        for name in data.get("versions", {}):
            if not isinstance(name, str):
                continue
            match = NATIVE_MODEL_VERSION_RE.match(name)
            if match:
                major, minor, patch = (int(part) for part in match.groups())
                parsed.append((major, minor, patch, name))
        return max(parsed)[3] if parsed else None

    def _next_native_candidate_unlocked(self, data: dict) -> tuple[str, str | None]:
        registered_names = {
            name for name in data.get("versions", {}) if isinstance(name, str)
        }
        reserved_names = set(self._read_reservations_unlocked().keys())
        artifacts_dir = self.root / "artifacts"
        artifact_names = (
            {p.name for p in artifacts_dir.iterdir()}
            if artifacts_dir.is_dir()
            else set()
        )
        all_taken = registered_names | reserved_names | artifact_names

        parsed_all: list[tuple[int, int, int, str]] = []
        for name in all_taken:
            match = NATIVE_MODEL_VERSION_RE.match(name)
            if match:
                major, minor, patch = (int(part) for part in match.groups())
                parsed_all.append((major, minor, patch, name))

        if not parsed_all:
            major, minor, patch = 0, 1, 0
        else:
            major, minor, patch, _ = max(parsed_all)
            patch += 1

        # Parent lineage always points to the highest already-committed version in
        # registry.json (never to an uncommitted in-flight reservation).
        parent = self._highest_registered_native_version(data)

        while True:
            candidate = f"ZYRQUEN-Native-{major}.{minor}.{patch}"
            artifact_dir = artifacts_dir / candidate
            res_file = self._reservation_file(candidate)
            if (
                candidate not in all_taken
                and not artifact_dir.exists()
                and not res_file.exists()
            ):
                return candidate, parent
            patch += 1

    # ---- atomic reservation ----
    def reserve_next_native_version(
        self, *, training_run_id: str | None = None
    ) -> NativeVersionReservation:
        """Atomically reserve the next ZYRQUEN-Native-MAJOR.MINOR.PATCH version."""
        with self._registry_lock():
            data = self._read()
            self._reservations_dir.mkdir(parents=True, exist_ok=True)
            candidate, parent = self._next_native_candidate_unlocked(data)
            token = secrets.token_hex(16)
            res_file = self._reservation_file(candidate)
            payload = {
                "version": candidate,
                "parent": parent,
                "token": token,
                "training_run_id": training_run_id,
                "pid": os.getpid(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                fd = os.open(res_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError as exc:
                raise RegistryError(f"version already reserved: {candidate}") from exc
            try:
                os.write(fd, json.dumps(payload, indent=2).encode("utf-8"))
            finally:
                os.close(fd)
            return NativeVersionReservation(
                version=candidate,
                parent=parent,
                token=token,
            )

    def release_reservation(self, version: str, token: str) -> bool:
        """Release a held version reservation if the caller's token matches."""
        with self._registry_lock():
            res_file = self._reservation_file(version)
            if not res_file.is_file() or res_file.is_symlink():
                return False
            try:
                payload = json.loads(res_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
            expected = payload.get("token") if isinstance(payload, dict) else None
            if not isinstance(expected, str) or not isinstance(token, str):
                return False
            if not secrets.compare_digest(expected, token):
                raise RegistryError(f"reservation token mismatch for {version}")
            res_file.unlink(missing_ok=True)
            return True

    def list_reservations(self) -> list[dict]:
        with self._registry_lock():
            return list(self._read_reservations_unlocked().values())

    # ---- register ----
    def register(self, version: str, checkpoint_dir: str | Path, tokenizer_path: str | Path,
                 dataset_dir: str | Path, metrics: dict | None = None, notes: str = "",
                 parent: str | None = None, reservation_token: str | None = None) -> dict:
        if not _VERSION.match(version):
            raise RegistryError("invalid version name (use letters, digits, . _ - ; max 64 chars)")

        with self._registry_lock():
            data = self._read()
            if version in data["versions"]:
                raise RegistryError(f"version already registered: {version}")
            if parent is not None and parent not in data["versions"]:
                raise RegistryError(f"unknown parent version: {parent}")

            res_file = self._reservation_file(version)
            if res_file.is_symlink():
                raise RegistryError(f"refusing symlinked reservation file for {version}")
            has_reservation = res_file.is_file()
            if has_reservation:
                try:
                    res_payload = json.loads(res_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise RegistryError(f"unreadable reservation for {version}") from exc
                expected_token = res_payload.get("token") if isinstance(res_payload, dict) else None
                if (
                    not isinstance(expected_token, str)
                    or not isinstance(reservation_token, str)
                    or not secrets.compare_digest(expected_token, reservation_token)
                ):
                    raise RegistryError(f"version is reserved by another worker: {version}")
            elif reservation_token is not None:
                raise RegistryError(f"reservation not found for version: {version}")

            # 1. checkpoint: newest one whose SHA-256 verifies (Phase 4 manager)
            manager = CheckpointManager(checkpoint_dir, load_fn=self._load)
            entry = manager.latest_valid()
            if entry is None:
                raise RegistryError("no checkpoint with a valid SHA-256 in checkpoint_dir")
            ckpt_path = Path(checkpoint_dir) / entry["file"]

            # 2. tokenizer: load() verifies its own fingerprint
            try:
                tok = ZyrquenTokenizer.load(tokenizer_path)
            except (ValueError, OSError, KeyError) as exc:
                raise RegistryError(f"tokenizer failed verification: {exc}") from exc

            # 3. dataset: every split and the content hash
            ds_manifest = _verify_dataset(Path(dataset_dir))

            # 4. references embedded in the checkpoint must match what is being linked
            state = self._load(str(ckpt_path))
            if not isinstance(state, dict):
                raise RegistryError("checkpoint state is not a dictionary")
            if state.get("tokenizer_sha256") != tok.fingerprint():
                raise RegistryError("checkpoint was not trained with this tokenizer (sha256 mismatch or missing)")
            if state.get("dataset_version") != ds_manifest["version"]:
                raise RegistryError("checkpoint was not trained on this dataset version (mismatch or missing)")

            # 5. immutable snapshot (never overwrite existing version directory)
            dest = self.root / "artifacts" / version
            try:
                dest.mkdir(parents=True, exist_ok=False)
            except FileExistsError as exc:
                raise RegistryError(f"artifact directory already exists: {version}") from exc
            try:
                shutil.copy2(ckpt_path, dest / "checkpoint.pt")
                shutil.copy2(tokenizer_path, dest / "tokenizer.json")
                shutil.copy2(Path(dataset_dir) / "manifest.json", dest / "dataset_manifest.json")
                if _sha256(dest / "checkpoint.pt") != entry["sha256"]:
                    raise RegistryError("artifact copy failed verification")
            except Exception:
                shutil.rmtree(dest, ignore_errors=True)
                raise

            record = {
                "version": version,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "parent": parent,
                "lifecycle_status": "registered",
                "checkpoint": {"step": entry["step"], "sha256": entry["sha256"],
                               "size_bytes": entry["size_bytes"], "path": f"artifacts/{version}/checkpoint.pt"},
                "tokenizer": {"version": tok.version, "sha256": tok.fingerprint(),
                              "file_sha256": _sha256(dest / "tokenizer.json"),
                              "path": f"artifacts/{version}/tokenizer.json"},
                "dataset": {"version": ds_manifest["version"], "content_sha256": ds_manifest["content_sha256"],
                            "path": f"artifacts/{version}/dataset_manifest.json"},
                "training_config": state.get("config"),
                "model_config": state.get("model_config"),
                "metrics": metrics or {},
                "evaluation_evidence": None,
                "workflow_lineage": {},
                "notes": notes,
            }
            data["versions"][version] = record
            self._write(data)
            if has_reservation:
                res_file.unlink(missing_ok=True)
            return record

    def register_next_native_version(
        self,
        checkpoint_dir: str | Path,
        tokenizer_path: str | Path,
        dataset_dir: str | Path,
        *,
        metrics: dict | None = None,
        notes: str = "",
        training_run_id: str | None = None,
    ) -> dict:
        """Atomically allocate, register, and record the next native version without auto-promotion."""
        with self._registry_lock():
            reservation = self.reserve_next_native_version(
                training_run_id=training_run_id
            )
            try:
                return self.register(
                    reservation.version,
                    checkpoint_dir,
                    tokenizer_path,
                    dataset_dir,
                    metrics=metrics,
                    notes=notes,
                    parent=reservation.parent,
                    reservation_token=reservation.token,
                )
            except Exception:
                self.release_reservation(reservation.version, reservation.token)
                raise

    # ---- query / verify ----
    def get(self, version: str) -> dict:
        try:
            return self._read()["versions"][version]
        except KeyError:
            raise RegistryError(f"unknown version: {version}") from None

    def list_versions(self) -> list[dict]:
        return sorted(self._read()["versions"].values(), key=lambda r: r["created_at"])

    def active_version(self) -> str | None:
        return self._read()["active"]

    def verify(self, version: str) -> bool:
        rec = self.get(version)
        for key, digest_field in (("checkpoint", "sha256"), ("tokenizer", "file_sha256")):
            p = self.root / rec[key]["path"]
            if not p.is_file() or _sha256(p) != rec[key][digest_field]:
                return False
        manifest_path = self.root / rec["dataset"]["path"]
        if not manifest_path.is_file():
            return False
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8")).get("content_sha256") == \
                rec["dataset"]["content_sha256"]
        except json.JSONDecodeError:
            return False

    # ---- lifecycle & evaluation gate ----
    def attach_evaluation_evidence(
        self,
        version: str,
        *,
        eval_run_id: str,
        report_sha256: str,
        metrics: dict[str, Any],
        passed: bool,
        zero_regression: bool = True,
        workflow_run_id: str | None = None,
        reason: str = "",
    ) -> dict:
        """Attach verified evaluation evidence and transition version to verified or quarantined."""
        with self._registry_lock():
            data = self._read()
            if version not in data["versions"]:
                raise RegistryError(f"unknown version: {version}")
            rec = data["versions"][version]
            next_status = "verified" if (passed and zero_regression) else "quarantined"
            rec["lifecycle_status"] = next_status
            rec["evaluation_evidence"] = {
                "eval_run_id": eval_run_id,
                "report_sha256": report_sha256,
                "passed": bool(passed),
                "zero_regression": bool(zero_regression),
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "summary": metrics,
            }
            if metrics:
                merged = dict(rec.get("metrics") or {})
                merged.update(metrics)
                rec["metrics"] = merged
            lineage = dict(rec.get("workflow_lineage") or {})
            if workflow_run_id:
                lineage["eval_workflow_run_id"] = workflow_run_id
            rec["workflow_lineage"] = lineage
            self._write(data)
            return rec

    def set_lifecycle_status(
        self,
        version: str,
        lifecycle_status: str,
        *,
        approval_id: str | None = None,
        approved_by: str | None = None,
        reason: str = "",
    ) -> dict:
        if lifecycle_status not in LIFECYCLE_STATES:
            raise RegistryError(f"unsupported lifecycle status: {lifecycle_status}")
        with self._registry_lock():
            data = self._read()
            if version not in data["versions"]:
                raise RegistryError(f"unknown version: {version}")
            rec = data["versions"][version]
            if lifecycle_status == "staging" and rec.get("lifecycle_status") != "verified":
                raise RegistryError(f"version {version} must be verified before staging")
            rec["lifecycle_status"] = lifecycle_status
            lineage = dict(rec.get("workflow_lineage") or {})
            if approval_id:
                lineage["approval_id"] = approval_id
            if approved_by:
                lineage["approved_by"] = approved_by
            if reason:
                lineage["status_reason"] = reason
            rec["workflow_lineage"] = lineage
            self._write(data)
            return rec

    def compare_versions(self, base_version: str, candidate_version: str) -> dict:
        """Compare numeric evaluation metrics and capability deltas between two versions."""
        base = self.get(base_version)
        cand = self.get(candidate_version)
        base_m = base.get("metrics") or {}
        cand_m = cand.get("metrics") or {}

        numeric_deltas: dict[str, dict[str, float | None]] = {}
        regressed_metrics: list[str] = []
        all_keys = sorted(set(base_m.keys()) | set(cand_m.keys()))
        for key in all_keys:
            b_val = base_m.get(key)
            c_val = cand_m.get(key)
            if isinstance(b_val, (int, float)) and not isinstance(b_val, bool) and isinstance(c_val, (int, float)) and not isinstance(c_val, bool):
                delta = round(float(c_val) - float(b_val), 6)
                numeric_deltas[key] = {
                    "base": float(b_val),
                    "candidate": float(c_val),
                    "delta": delta,
                }
                if key.endswith("loss"):
                    if delta > 0.01:
                        regressed_metrics.append(key)
                elif delta < -0.01:
                    regressed_metrics.append(key)

        return {
            "base_version": base_version,
            "candidate_version": candidate_version,
            "base_lifecycle": base.get("lifecycle_status", "registered"),
            "candidate_lifecycle": cand.get("lifecycle_status", "registered"),
            "metric_deltas": numeric_deltas,
            "regressed_metrics": regressed_metrics,
            "zero_regression": len(regressed_metrics) == 0,
        }

    # ---- promote / rollback ----
    def promote(
        self,
        version: str,
        *,
        enforce_evaluation_gate: bool = False,
        approval_id: str | None = None,
        approved_by: str | None = None,
    ) -> None:
        with self._registry_lock():
            if not self.verify(version):
                raise RegistryError(f"integrity check failed, refusing to activate {version}")
            data = self._read()
            rec = data["versions"][version]
            if enforce_evaluation_gate:
                lifecycle = rec.get("lifecycle_status", "registered")
                ev = rec.get("evaluation_evidence")
                if lifecycle not in PROMOTABLE_LIFECYCLE_STATES:
                    raise RegistryError(
                        f"promotion blocked: version {version} has lifecycle_status={lifecycle!r} "
                        f"(expected one of {PROMOTABLE_LIFECYCLE_STATES})"
                    )
                if not isinstance(ev, dict) or not ev.get("passed") or not ev.get("zero_regression"):
                    raise RegistryError(
                        f"promotion blocked: version {version} lacks passing evaluation evidence"
                    )
                if not approval_id:
                    raise RegistryError(
                        f"promotion blocked: Tier-2 approval_id is required to promote {version}"
                    )

            if data["active"] == version:
                if enforce_evaluation_gate:
                    rec["lifecycle_status"] = "production"
                    self._write(data)
                return
            if data["active"] is not None:
                prev_ver = data["active"]
                data["history"].append(prev_ver)
                if prev_ver in data["versions"] and data["versions"][prev_ver].get("lifecycle_status") == "production":
                    data["versions"][prev_ver]["lifecycle_status"] = "archived"
            data["active"] = version
            if enforce_evaluation_gate or "lifecycle_status" in rec:
                rec["lifecycle_status"] = "production"
            if approval_id or approved_by:
                lineage = dict(rec.get("workflow_lineage") or {})
                if approval_id:
                    lineage["approval_id"] = approval_id
                if approved_by:
                    lineage["approved_by"] = approved_by
                rec["workflow_lineage"] = lineage
            self._write(data)

    def rollback(self, to_version: str | None = None, *, approval_id: str | None = None) -> str:
        """Re-activate the previous active version (or a specific registered one)."""
        with self._registry_lock():
            data = self._read()
            prev_active = data["active"]
            if to_version is None:
                while data["history"]:
                    candidate = data["history"].pop()
                    if candidate in data["versions"] and candidate != data["active"] and self.verify(candidate):
                        data["active"] = candidate
                        if prev_active and prev_active in data["versions"] and data["versions"][prev_active].get("lifecycle_status") == "production":
                            data["versions"][prev_active]["lifecycle_status"] = "archived"
                        data["versions"][candidate]["lifecycle_status"] = "production"
                        if approval_id:
                            lineage = dict(data["versions"][candidate].get("workflow_lineage") or {})
                            lineage["rollback_approval_id"] = approval_id
                            data["versions"][candidate]["workflow_lineage"] = lineage
                        self._write(data)
                        return candidate
                raise RegistryError("no earlier verified version to roll back to")
            if to_version not in data["versions"]:
                raise RegistryError(f"unknown version: {to_version}")
            if not self.verify(to_version):
                raise RegistryError(f"integrity check failed, refusing to activate {to_version}")
            if data["active"] not in (None, to_version):
                data["history"].append(data["active"])
                if prev_active and prev_active in data["versions"] and data["versions"][prev_active].get("lifecycle_status") == "production":
                    data["versions"][prev_active]["lifecycle_status"] = "archived"
            data["active"] = to_version
            data["versions"][to_version]["lifecycle_status"] = "production"
            if approval_id:
                lineage = dict(data["versions"][to_version].get("workflow_lineage") or {})
                lineage["rollback_approval_id"] = approval_id
                data["versions"][to_version]["workflow_lineage"] = lineage
            self._write(data)
            return to_version
