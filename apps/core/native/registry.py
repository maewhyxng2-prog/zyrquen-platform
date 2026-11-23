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
import math
import os
import re
import secrets
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

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
V10_MODEL_VERSION_PREFIX = "ZYRQUEN-Native-10."
V10_MODEL_VERSION_RE = re.compile(
    r"^ZYRQUEN-Native-10\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
)
V10_VERSIONING_CONTRACT_SCHEMA = "zyrquen.v10.versioning_contract.v1"
V11_MODEL_VERSION_PREFIX = "ZYRQUEN-Native-11."
V11_MODEL_VERSION_RE = re.compile(
    r"^ZYRQUEN-Native-11\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
)
SPLITS = ("train", "validation", "test")
V11_SPLITS = ("train", "validation", "unseen", "ood")
LIFECYCLE_STATES = (
    "development",
    "registered",
    "evaluated",
    "verified",
    "staging",
    "production",
    "quarantined",
    "blocked",
    "failed",
    "archived",
)
PROMOTABLE_LIFECYCLE_STATES = ("verified", "staging", "production")
FROZEN_BASELINE_NAMES = frozenset(
    {"v7", "v8", "v9", "ZYRQUEN-v7", "ZYRQUEN-v8", "ZYRQUEN-v9"}
)
_DISALLOWED_EVAL_STATUSES = frozenset(
    {"NOT RUN", "NOT_RUN", "BLOCKED", "FAIL", "FAILED", "ERROR", "UNKNOWN", "PENDING"}
)
_ZYRQUEN_CONFIG_CORE_KEYS = (
    "vocab_size",
    "max_seq_len",
    "n_layers",
    "n_heads",
    "d_model",
    "d_ff",
)


def _is_valid_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdefABCDEF" for ch in value)
    )


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _validate_evaluation_metrics_dict(metrics: Any) -> None:
    if not isinstance(metrics, dict) or not metrics:
        raise RegistryError("evaluation verification requires non-empty numeric metrics")
    finite_count = 0
    for key, val in metrics.items():
        if val is None:
            continue
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            if not math.isfinite(float(val)):
                raise RegistryError(f"evaluation metric {key!r} is non-finite: {val!r}")
            finite_count += 1
    if finite_count == 0:
        raise RegistryError("evaluation verification requires at least one finite numeric metric")


def _validate_evaluation_evidence_record(ev: Any, version: str) -> None:
    if not isinstance(ev, dict):
        raise RegistryError(f"version {version} lacks evaluation_evidence")
    if ev.get("passed") is not True or ev.get("zero_regression") is not True:
        raise RegistryError(f"version {version} evaluation_evidence is not passing/zero-regression")
    if not _is_valid_sha256_hex(ev.get("report_sha256")):
        raise RegistryError(f"version {version} evaluation_evidence lacks valid report_sha256")
    eval_run_id = ev.get("eval_run_id")
    if not isinstance(eval_run_id, str) or not eval_run_id.strip():
        raise RegistryError(f"version {version} evaluation_evidence lacks eval_run_id")
    eval_status = ev.get("evaluation_status")
    if eval_status is not None:
        if str(eval_status).strip().upper() in _DISALLOWED_EVAL_STATUSES:
            raise RegistryError(
                f"version {version} cannot be certified from evaluation_status={eval_status!r}"
            )
    if ev.get("inference_executed") is False:
        raise RegistryError(
            f"version {version} cannot be certified when inference_executed is False"
        )
    _validate_evaluation_metrics_dict(ev.get("summary"))

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
    source: str = "canonical_auto"


@dataclass(frozen=True)
class CanonicalVersionContract:
    schema: str
    target_major: int
    default_minor: int
    prefix: str
    pattern: str
    initial_version: str
    resolution_policy: str
    audit_ignores_legacy_versions: bool
    protected_baselines: tuple[str, ...]

    def matches(self, version: Any) -> bool:
        return is_v10_model_version(version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "target_major": self.target_major,
            "default_minor": self.default_minor,
            "prefix": self.prefix,
            "pattern": self.pattern,
            "initial_version": self.initial_version,
            "resolution_policy": self.resolution_policy,
            "audit_ignores_legacy_versions": self.audit_ignores_legacy_versions,
            "protected_baselines": list(self.protected_baselines),
        }


class RegistryError(RuntimeError):
    pass


def is_v10_model_version(version: Any) -> bool:
    """Return True strictly when version matches ZYRQUEN-Native-10.<minor>.<patch>."""
    return isinstance(version, str) and bool(V10_MODEL_VERSION_RE.match(version))


def is_v11_model_version(version: Any) -> bool:
    """Return True strictly when version matches ZYRQUEN-Native-11.<minor>.<patch>."""
    return isinstance(version, str) and bool(V11_MODEL_VERSION_RE.match(version))


V10_VERSIONING_CONTRACT = CanonicalVersionContract(
    schema=V10_VERSIONING_CONTRACT_SCHEMA,
    target_major=10,
    default_minor=0,
    prefix=V10_MODEL_VERSION_PREFIX,
    pattern=V10_MODEL_VERSION_RE.pattern,
    initial_version="ZYRQUEN-Native-10.0.0",
    resolution_policy="once_per_run",
    audit_ignores_legacy_versions=True,
    protected_baselines=tuple(sorted(FROZEN_BASELINE_NAMES)),
)


def validate_native_model_version_name(
    version: Any,
    *,
    require_v10: bool = False,
) -> str:
    """Validate an explicit native model version identifier against the naming contract."""
    if not isinstance(version, str) or not version.strip():
        raise RegistryError("model_version must be a non-empty string")
    if version != version.strip() or not _VERSION.match(version):
        raise RegistryError(
            "invalid model_version format (use letters, digits, . _ - ; max 64 chars)"
        )
    if version in FROZEN_BASELINE_NAMES:
        raise RegistryError(f"cannot overwrite protected baseline identifier: {version}")
    if not NATIVE_MODEL_VERSION_RE.match(version):
        raise RegistryError(
            "invalid native model_version; expected ZYRQUEN-Native-MAJOR.MINOR.PATCH"
        )
    if require_v10 and not V10_MODEL_VERSION_RE.match(version):
        raise RegistryError(
            "invalid V10 model_version; expected ZYRQUEN-Native-10.MINOR.PATCH"
        )
    return version


def compute_next_native_version(
    existing_versions: Iterable[str],
    *,
    major: int | None = None,
    default_minor: int | None = None,
) -> tuple[str, str | None]:
    """Central deterministic allocator for the next ZYRQUEN-Native-MAJOR.MINOR.PATCH ID."""
    taken = {v for v in existing_versions if isinstance(v, str) and v}
    parsed_all: list[tuple[int, int, int, str]] = []
    for name in taken:
        match = NATIVE_MODEL_VERSION_RE.match(name)
        if not match:
            continue
        m_val, minor, patch = (int(part) for part in match.groups())
        if major is not None and m_val != int(major):
            continue
        parsed_all.append((m_val, minor, patch, name))

    parent = max(parsed_all)[3] if parsed_all else None
    if not parsed_all:
        if major is not None:
            m_val = int(major)
            minor = 0 if default_minor is None else int(default_minor)
            patch = 0
        else:
            m_val = 0
            minor = 1 if default_minor is None else int(default_minor)
            patch = 0
    else:
        m_val, minor, patch, _ = max(parsed_all)
        patch += 1

    while True:
        candidate = f"ZYRQUEN-Native-{m_val}.{minor}.{patch}"
        if candidate not in taken:
            return candidate, parent
        patch += 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_dataset(dataset_dir: Path) -> dict:
    """Re-verify every split file and the content hash against the dataset manifest (3-split or V11 4-split)."""
    from apps.core.native.dataset import SCHEMA as DATASET_SCHEMA, verify_dataset_manifest

    if dataset_dir.is_symlink() or not dataset_dir.is_dir():
        raise RegistryError("dataset directory missing or symlinked")
    mpath = dataset_dir / "manifest.json"
    if mpath.is_symlink() or not mpath.is_file():
        raise RegistryError("dataset manifest.json not found or symlinked")
    try:
        raw_manifest = json.loads(mpath.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"dataset manifest unreadable: {exc}") from exc
    if not isinstance(raw_manifest, dict):
        raise RegistryError("dataset manifest.json must be a JSON object")
    if "schema" in raw_manifest and raw_manifest.get("schema") != DATASET_SCHEMA:
        raise RegistryError("dataset manifest unsupported schema")
    if not isinstance(raw_manifest.get("files"), dict) and not isinstance(raw_manifest.get("splits"), dict):
        raise RegistryError("dataset manifest missing files/splits mapping")
    try:
        return verify_dataset_manifest(dataset_dir, require_schema=("schema" in raw_manifest))
    except ValueError as exc:
        raise RegistryError(str(exc)) from exc


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
            if not isinstance(payload, dict):
                out[item.stem] = {"version": item.stem}
                continue
            ver = payload.get("version")
            out[ver if isinstance(ver, str) and ver else item.stem] = payload
        return out

    def _read(self) -> dict:
        if not self._path.is_file():
            return {"schema": SCHEMA, "versions": {}, "active": None, "history": []}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RegistryError(f"unreadable registry.json: {exc}") from exc
        if not isinstance(data, dict) or data.get("schema") != SCHEMA:
            raise RegistryError("unsupported registry schema")
        versions = data.get("versions")
        if versions is None:
            data["versions"] = {}
        elif not isinstance(versions, dict):
            raise RegistryError("invalid registry versions mapping")
        history = data.get("history")
        if history is None:
            data["history"] = []
        elif not isinstance(history, list):
            raise RegistryError("invalid registry history list")
        data.setdefault("active", None)
        return data

    def _write(self, data: dict) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._path)

    def _highest_registered_native_version(
        self, data: dict, *, major: int | None = None
    ) -> str | None:
        parsed: list[tuple[int, int, int, str]] = []
        for name in data.get("versions", {}):
            if not isinstance(name, str):
                continue
            match = NATIVE_MODEL_VERSION_RE.match(name)
            if match:
                m_val, minor, patch = (int(part) for part in match.groups())
                if major is not None and m_val != int(major):
                    continue
                parsed.append((m_val, minor, patch, name))
        return max(parsed)[3] if parsed else None

    def _next_native_candidate_unlocked(
        self,
        data: dict,
        *,
        major: int | None = None,
        default_minor: int | None = None,
        taken_versions: Iterable[str] | None = None,
    ) -> tuple[str, str | None]:
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
        extra_taken = {
            name for name in (taken_versions or ()) if isinstance(name, str) and name
        }
        all_taken = registered_names | reserved_names | artifact_names | extra_taken

        candidate, _ = compute_next_native_version(
            all_taken, major=major, default_minor=default_minor
        )
        # Parent lineage always points to the highest already-committed version in
        # registry.json within the same target major line (never uncommitted reservations).
        parent = self._highest_registered_native_version(data, major=major)

        match = NATIVE_MODEL_VERSION_RE.match(candidate)
        assert match is not None
        m_val, minor, patch = (int(part) for part in match.groups())
        while True:
            candidate = f"ZYRQUEN-Native-{m_val}.{minor}.{patch}"
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
        self,
        *,
        training_run_id: str | None = None,
        major: int | None = None,
        default_minor: int | None = None,
        taken_versions: Iterable[str] | None = None,
        parent: str | None = None,
    ) -> NativeVersionReservation:
        """Atomically reserve the next ZYRQUEN-Native-MAJOR.MINOR.PATCH version."""
        with self._registry_lock():
            data = self._read()
            if parent is not None and parent not in data["versions"]:
                raise RegistryError(f"unknown parent version: {parent}")
            self._reservations_dir.mkdir(parents=True, exist_ok=True)
            candidate, inferred_parent = self._next_native_candidate_unlocked(
                data,
                major=major,
                default_minor=default_minor,
                taken_versions=taken_versions,
            )
            resolved_parent = parent if parent is not None else inferred_parent
            token = secrets.token_hex(16)
            res_file = self._reservation_file(candidate)
            payload = {
                "version": candidate,
                "parent": resolved_parent,
                "token": token,
                "source": "canonical_auto",
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
                parent=resolved_parent,
                token=token,
                source="canonical_auto",
            )

    def reserve_next_v10_version(
        self,
        *,
        training_run_id: str | None = None,
        taken_versions: Iterable[str] | None = None,
    ) -> NativeVersionReservation:
        """Atomically reserve the next canonical V10 version (ZYRQUEN-Native-10.MINOR.PATCH)."""
        return self.reserve_next_native_version(
            training_run_id=training_run_id,
            major=10,
            default_minor=0,
            taken_versions=taken_versions,
        )

    def reserve_specific_native_version(
        self,
        version: str,
        *,
        training_run_id: str | None = None,
        parent: str | None = None,
        require_v10: bool = False,
    ) -> NativeVersionReservation:
        """Atomically reserve an explicit canonical version, rejecting duplicates or collisions."""
        validated = validate_native_model_version_name(version, require_v10=require_v10)
        with self._registry_lock():
            data = self._read()
            if validated in data.get("versions", {}):
                raise RegistryError(f"version already registered: {validated}")
            artifact_dir = self.root / "artifacts" / validated
            if artifact_dir.exists():
                raise RegistryError(f"artifact directory already exists: {validated}")
            if parent is not None and parent not in data.get("versions", {}):
                raise RegistryError(f"unknown parent version: {parent}")

            self._reservations_dir.mkdir(parents=True, exist_ok=True)
            res_file = self._reservation_file(validated)
            if res_file.is_symlink():
                raise RegistryError(f"refusing symlinked reservation file for {validated}")
            resolved_parent = parent
            if resolved_parent is None:
                match = NATIVE_MODEL_VERSION_RE.match(validated)
                assert match is not None
                resolved_parent = self._highest_registered_native_version(
                    data, major=int(match.group(1))
                )
            token = secrets.token_hex(16)
            payload = {
                "version": validated,
                "parent": resolved_parent,
                "token": token,
                "source": "explicit",
                "training_run_id": training_run_id,
                "pid": os.getpid(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                fd = os.open(res_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError as exc:
                raise RegistryError(f"version already reserved: {validated}") from exc
            try:
                os.write(fd, json.dumps(payload, indent=2).encode("utf-8"))
            finally:
                os.close(fd)
            return NativeVersionReservation(
                version=validated,
                parent=resolved_parent,
                token=token,
                source="explicit",
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
                 parent: str | None = None, reservation_token: str | None = None,
                 architecture: dict | None = None, training_metadata: dict | None = None,
                 hardware: dict | None = None, capabilities: dict | None = None,
                 frozen: bool = False, prompt_format: str | None = None) -> dict:
        if not _VERSION.match(version):
            raise RegistryError("invalid version name (use letters, digits, . _ - ; max 64 chars)")
        if version in FROZEN_BASELINE_NAMES:
            raise RegistryError(f"cannot overwrite protected baseline identifier: {version}")

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

            resolved_arch = architecture if architecture is not None else state.get("model_config")
            resolved_training = training_metadata if training_metadata is not None else state.get("config")
            resolved_prompt_format = (
                prompt_format if prompt_format is not None else state.get("prompt_format")
            )
            record = {
                "version": version,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "parent": parent,
                "lifecycle_status": "registered",
                "frozen": bool(frozen),
                "checkpoint": {"step": entry["step"], "sha256": entry["sha256"],
                               "size_bytes": entry["size_bytes"], "path": f"artifacts/{version}/checkpoint.pt"},
                "tokenizer": {"version": tok.version, "sha256": tok.fingerprint(),
                              "file_sha256": _sha256(dest / "tokenizer.json"),
                              "vocab_size": tok.vocab_size,
                              "path": f"artifacts/{version}/tokenizer.json"},
                "dataset": {"version": ds_manifest["version"], "content_sha256": ds_manifest["content_sha256"],
                            "path": f"artifacts/{version}/dataset_manifest.json"},
                "architecture": resolved_arch,
                "training_config": resolved_training,
                "model_config": state.get("model_config"),
                "prompt_format": resolved_prompt_format if isinstance(resolved_prompt_format, str) else None,
                "hardware": hardware,
                "capabilities": capabilities or {},
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
        major: int | None = None,
        default_minor: int | None = None,
        taken_versions: Iterable[str] | None = None,
    ) -> dict:
        """Atomically allocate, register, and record the next native version without auto-promotion."""
        with self._registry_lock():
            reservation = self.reserve_next_native_version(
                training_run_id=training_run_id,
                major=major,
                default_minor=default_minor,
                taken_versions=taken_versions,
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

    def register_next_v10_version(
        self,
        checkpoint_dir: str | Path,
        tokenizer_path: str | Path,
        dataset_dir: str | Path,
        *,
        metrics: dict | None = None,
        notes: str = "",
        training_run_id: str | None = None,
        taken_versions: Iterable[str] | None = None,
    ) -> dict:
        """Atomically allocate, register, and record the next canonical V10 version."""
        return self.register_next_native_version(
            checkpoint_dir,
            tokenizer_path,
            dataset_dir,
            metrics=metrics,
            notes=notes,
            training_run_id=training_run_id,
            major=10,
            default_minor=0,
            taken_versions=taken_versions,
        )

    # ---- query / verify ----
    def get(self, version: str) -> dict:
        try:
            return self._read()["versions"][version]
        except KeyError:
            raise RegistryError(f"unknown version: {version}") from None

    def list_versions(self) -> list[dict]:
        versions = [r for r in self._read()["versions"].values() if isinstance(r, dict)]
        return sorted(versions, key=lambda r: str(r.get("created_at") or ""))

    def active_version(self) -> str | None:
        return self._read().get("active")

    def verify(self, version: str) -> bool:
        rec = self.get(version)
        if not isinstance(rec, dict):
            return False
        resolved_root = self.root.resolve()
        for key, digest_field in (("checkpoint", "sha256"), ("tokenizer", "file_sha256")):
            section = rec.get(key)
            if not isinstance(section, dict):
                return False
            rel = section.get("path")
            expected_digest = section.get(digest_field)
            if (
                not isinstance(rel, str)
                or not rel
                or not isinstance(expected_digest, str)
                or not expected_digest
            ):
                return False
            p = self.root / rel
            if (
                p.is_symlink()
                or not p.resolve().is_relative_to(resolved_root)
                or not p.is_file()
                or _sha256(p) != expected_digest
            ):
                return False
        ds_section = rec.get("dataset")
        if not isinstance(ds_section, dict):
            return False
        ds_rel = ds_section.get("path")
        ds_digest = ds_section.get("content_sha256")
        if (
            not isinstance(ds_rel, str)
            or not ds_rel
            or not isinstance(ds_digest, str)
            or not ds_digest
        ):
            return False
        manifest_path = self.root / ds_rel
        if (
            manifest_path.is_symlink()
            or not manifest_path.resolve().is_relative_to(resolved_root)
            or not manifest_path.is_file()
        ):
            return False
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return isinstance(manifest_data, dict) and manifest_data.get("content_sha256") == ds_digest

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
        capabilities: dict[str, Any] | None = None,
        workflow_run_id: str | None = None,
        reason: str = "",
        evaluation_status: str | None = None,
        inference_executed: bool | None = None,
        report_schema: str | None = None,
    ) -> dict:
        """Attach verified evaluation evidence and transition version to verified or quarantined."""
        if passed and zero_regression:
            if not isinstance(eval_run_id, str) or not eval_run_id.strip():
                raise RegistryError("evaluation verification requires a non-empty eval_run_id")
            if not _is_valid_sha256_hex(report_sha256):
                raise RegistryError("evaluation verification requires a valid 64-char SHA-256 report digest")
            if evaluation_status is not None and str(evaluation_status).strip().upper() in _DISALLOWED_EVAL_STATUSES:
                raise RegistryError(
                    f"cannot certify verified status from evaluation_status={evaluation_status!r}"
                )
            if inference_executed is False:
                raise RegistryError("cannot certify verified status when inference_executed is False")
            _validate_evaluation_metrics_dict(metrics)

        with self._registry_lock():
            data = self._read()
            if version not in data["versions"]:
                raise RegistryError(f"unknown version: {version}")
            rec = data["versions"][version]
            if rec.get("frozen") or version in FROZEN_BASELINE_NAMES:
                raise RegistryError(f"version {version} is frozen/closed and cannot be mutated")
            next_status = "verified" if (passed and zero_regression) else "quarantined"
            rec["lifecycle_status"] = next_status
            ev_record: dict[str, Any] = {
                "eval_run_id": eval_run_id,
                "report_sha256": report_sha256,
                "passed": bool(passed),
                "zero_regression": bool(zero_regression),
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "summary": dict(metrics or {}),
            }
            if evaluation_status is not None:
                ev_record["evaluation_status"] = evaluation_status
            if inference_executed is not None:
                ev_record["inference_executed"] = bool(inference_executed)
            if report_schema is not None:
                ev_record["report_schema"] = report_schema
            rec["evaluation_evidence"] = ev_record
            if metrics:
                merged = dict(rec.get("metrics") or {})
                merged.update(metrics)
                rec["metrics"] = merged
            if capabilities:
                merged_caps = dict(rec.get("capabilities") or {})
                merged_caps.update(capabilities)
                rec["capabilities"] = merged_caps
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
        if lifecycle_status == "verified":
            raise RegistryError(
                "cannot transition to 'verified' directly; call attach_evaluation_evidence() with real passing evidence"
            )
        if lifecycle_status == "production":
            raise RegistryError(
                "cannot transition to 'production' via set_lifecycle_status(); use promote(enforce_evaluation_gate=True)"
            )
        with self._registry_lock():
            data = self._read()
            if version not in data["versions"]:
                raise RegistryError(f"unknown version: {version}")
            rec = data["versions"][version]
            if rec.get("frozen") or version in FROZEN_BASELINE_NAMES:
                raise RegistryError(f"version {version} is frozen/closed and cannot be mutated")
            if lifecycle_status == "staging":
                if rec.get("lifecycle_status") != "verified":
                    raise RegistryError(f"version {version} must be verified before staging")
                _validate_evaluation_evidence_record(rec.get("evaluation_evidence"), version)
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

    def check_compatibility(
        self,
        version: str,
        *,
        tokenizer_sha256: str | None = None,
        expected_model_type: str | None = None,
    ) -> dict[str, Any]:
        """Verify artifact hashes, tokenizer compatibility, and architecture metadata."""
        rec = self.get(version)
        reasons: list[str] = []
        artifacts_ok = self.verify(version)
        if not artifacts_ok:
            reasons.append("Artifact SHA-256 verification failed or files missing.")

        tok_info = rec.get("tokenizer") or {}
        tok_ok = bool(tok_info.get("sha256")) and (
            tokenizer_sha256 is None or tok_info.get("sha256") == tokenizer_sha256
        )
        if not tok_ok:
            reasons.append("Tokenizer SHA-256 missing or incompatible.")

        arch_info = rec.get("architecture") or rec.get("model_config")
        if not isinstance(arch_info, dict):
            arch_ok = False
        elif expected_model_type is None:
            arch_ok = True
        elif arch_info.get("model_type") == expected_model_type:
            arch_ok = True
        elif (
            expected_model_type == "zyrquen-decoder"
            and "model_type" not in arch_info
            and all(
                isinstance(arch_info.get(k), int)
                and not isinstance(arch_info.get(k), bool)
                and arch_info[k] > 0
                for k in _ZYRQUEN_CONFIG_CORE_KEYS
            )
        ):
            arch_ok = True
        else:
            arch_ok = False
        if not arch_ok:
            reasons.append("Architecture / model_config metadata missing or mismatched.")

        return {
            "version": version,
            "compatible": artifacts_ok and tok_ok and arch_ok,
            "checks": {
                "artifacts_sha256": artifacts_ok,
                "tokenizer_sha256": tok_ok,
                "architecture_config": arch_ok,
            },
            "reasons": reasons,
        }

    def get_lineage(self, version: str) -> dict[str, Any]:
        """Trace parent lineage and provenance chain from version back to baseline."""
        data = self._read()
        chain: list[dict[str, Any]] = []
        seen: set[str] = set()
        curr: str | None = version
        while curr is not None:
            if curr in seen:
                raise RegistryError(f"cycle detected in model lineage at {curr}")
            if curr not in data["versions"]:
                raise RegistryError(f"unknown version in lineage: {curr}")
            seen.add(curr)
            rec = data["versions"][curr]
            ev = rec.get("evaluation_evidence") or {}
            chain.append(
                {
                    "version": curr,
                    "parent": rec.get("parent"),
                    "lifecycle_status": rec.get("lifecycle_status", "registered"),
                    "created_at": rec.get("created_at"),
                    "dataset_version": (rec.get("dataset") or {}).get("version"),
                    "dataset_sha256": (rec.get("dataset") or {}).get("content_sha256"),
                    "checkpoint_sha256": (rec.get("checkpoint") or {}).get("sha256"),
                    "tokenizer_sha256": (rec.get("tokenizer") or {}).get("sha256"),
                    "eval_report_sha256": ev.get("report_sha256"),
                    "eval_passed": ev.get("passed"),
                    "workflow_lineage": rec.get("workflow_lineage") or {},
                }
            )
            curr = rec.get("parent")
        return {"version": version, "depth": len(chain), "ancestors": chain}

    def compare_versions(self, base_version: str, candidate_version: str) -> dict:
        """Compare numeric evaluation metrics and capability deltas between two versions."""
        base = self.get(base_version)
        cand = self.get(candidate_version)

        def _diff_numeric(base_map: dict[str, Any], cand_map: dict[str, Any]) -> tuple[dict, list[str]]:
            deltas: dict[str, dict[str, float | None]] = {}
            regressed: list[str] = []
            for key in sorted(set(base_map.keys()) | set(cand_map.keys())):
                b_val = base_map.get(key)
                c_val = cand_map.get(key)
                if (
                    isinstance(b_val, (int, float))
                    and not isinstance(b_val, bool)
                    and isinstance(c_val, (int, float))
                    and not isinstance(c_val, bool)
                ):
                    delta = round(float(c_val) - float(b_val), 6)
                    deltas[key] = {"base": float(b_val), "candidate": float(c_val), "delta": delta}
                    if key.endswith("loss"):
                        if delta > 0.01:
                            regressed.append(key)
                    elif delta < -0.01:
                        regressed.append(key)
            return deltas, regressed

        numeric_deltas, regressed_metrics = _diff_numeric(
            base.get("metrics") or {}, cand.get("metrics") or {}
        )
        capability_deltas, regressed_capabilities = _diff_numeric(
            base.get("capabilities") or {}, cand.get("capabilities") or {}
        )

        return {
            "base_version": base_version,
            "candidate_version": candidate_version,
            "base_lifecycle": base.get("lifecycle_status", "registered"),
            "candidate_lifecycle": cand.get("lifecycle_status", "registered"),
            "metric_deltas": numeric_deltas,
            "regressed_metrics": regressed_metrics,
            "capability_deltas": capability_deltas,
            "regressed_capabilities": regressed_capabilities,
            "zero_regression": (len(regressed_metrics) == 0 and len(regressed_capabilities) == 0),
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
                compat = self.check_compatibility(version)
                if not compat["compatible"]:
                    raise RegistryError(
                        f"promotion blocked: compatibility check failed for {version}: {compat['reasons']}"
                    )
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
                _validate_evaluation_evidence_record(ev, version)
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


def resolve_canonical_model_version(
    *,
    explicit_version: str | None = None,
    parent_version: str | None = None,
    registry: ModelRegistry | None = None,
    existing_checkpoint_versions: Iterable[str] = (),
    target_major: int | None = 10,
    training_run_id: str | None = None,
) -> NativeVersionReservation:
    """Resolve ONE canonical native model version ID across CheckpointManager and ModelRegistry.

    - Resolution happens once per `training_run_id`: if an active reservation already exists
      for `training_run_id` in `registry`, the same `NativeVersionReservation` is returned
      (or `RegistryError` is raised if `explicit_version` conflicts with it).
    - If `explicit_version` is supplied, it is validated against the canonical contract
      (and `V10_MODEL_VERSION_RE` when `target_major == 10`) and rejected if it already
      exists in checkpoint history or ModelRegistry.
    - If `explicit_version` is omitted, a single canonical ID is allocated once using the
      shared major-line rule (`ZYRQUEN-Native-10.0.0` onward for V10) and atomically
      reserved in `registry` when present.
    """
    taken_ckpt = {
        str(v) for v in existing_checkpoint_versions if isinstance(v, str) and v
    }
    normalized_parent = (
        parent_version.strip()
        if isinstance(parent_version, str)
        else parent_version
    )
    if normalized_parent == "":
        normalized_parent = None
    normalized_run_id = (
        training_run_id.strip()
        if isinstance(training_run_id, str)
        else None
    ) or None

    require_v10 = target_major == 10
    default_minor = 0 if target_major in (10, 11) else 1

    if registry is not None:
        with registry._registry_lock():
            if normalized_run_id is not None:
                active_res = registry._read_reservations_unlocked()
                for res_payload in active_res.values():
                    if not isinstance(res_payload, dict):
                        continue
                    if res_payload.get("training_run_id") != normalized_run_id:
                        continue
                    existing_ver = res_payload.get("version")
                    existing_token = res_payload.get("token")
                    if not isinstance(existing_ver, str) or not isinstance(existing_token, str) or not existing_token:
                        continue
                    if require_v10 and not is_v10_model_version(existing_ver):
                        raise RegistryError(
                            f"training_run_id {normalized_run_id} holds non-V10 reservation {existing_ver}"
                        )
                    if explicit_version is not None and explicit_version != existing_ver:
                        raise RegistryError(
                            f"training_run_id {normalized_run_id} already resolved to {existing_ver} (cannot rebind to {explicit_version})"
                        )
                    if normalized_parent is not None and normalized_parent != res_payload.get("parent"):
                        raise RegistryError(
                            f"training_run_id {normalized_run_id} already resolved with parent {res_payload.get('parent')!r}"
                        )
                    return NativeVersionReservation(
                        version=existing_ver,
                        parent=res_payload.get("parent"),
                        token=existing_token,
                        source=str(res_payload.get("source") or "canonical_auto"),
                    )

            if explicit_version is not None:
                validated = validate_native_model_version_name(
                    explicit_version, require_v10=require_v10
                )
                if validated in taken_ckpt:
                    raise RegistryError(
                        f"model_version already exists in checkpoint version_manifest.json: {validated}"
                    )
                return registry.reserve_specific_native_version(
                    validated,
                    training_run_id=normalized_run_id,
                    parent=normalized_parent,
                    require_v10=require_v10,
                )

            return registry.reserve_next_native_version(
                training_run_id=normalized_run_id,
                major=target_major,
                default_minor=default_minor,
                taken_versions=taken_ckpt,
                parent=normalized_parent,
            )

    if explicit_version is not None:
        validated = validate_native_model_version_name(
            explicit_version, require_v10=require_v10
        )
        if validated in taken_ckpt:
            raise RegistryError(
                f"model_version already exists in checkpoint version_manifest.json: {validated}"
            )
        return NativeVersionReservation(
            version=validated,
            parent=normalized_parent,
            token="",
            source="explicit",
        )

    candidate, inferred_parent = compute_next_native_version(
        taken_ckpt,
        major=target_major,
        default_minor=default_minor,
    )
    return NativeVersionReservation(
        version=candidate,
        parent=normalized_parent if normalized_parent is not None else inferred_parent,
        token="",
        source="canonical_auto",
    )
