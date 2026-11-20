"""Phase 3.5: model registry and versioning for the ZYRQUEN native model.

A registered version is an immutable snapshot: a copy of a verified checkpoint plus the
exact tokenizer file and dataset manifest it was trained with, linked by SHA-256.
Reuses CheckpointManager (Phase 4) for checkpoint verification; does not duplicate it.
Standard library only (checkpoint loading is injected, default torch).
"""
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from apps.core.native.tokenizer import ZyrquenTokenizer
from apps.core.training_infrastructure.recovery.checkpoint_recovery import (
    CheckpointManager, _torch_load)

SCHEMA = "zyrquen.model-registry.v1"
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SPLITS = ("train", "validation", "test")


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
    def __init__(self, root: str | Path, load_fn: Callable[[str], Any] = _torch_load):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._load = load_fn

    # ---- persistence ----
    @property
    def _path(self) -> Path:
        return self.root / "registry.json"

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

    # ---- register ----
    def register(self, version: str, checkpoint_dir: str | Path, tokenizer_path: str | Path,
                 dataset_dir: str | Path, metrics: dict | None = None, notes: str = "",
                 parent: str | None = None) -> dict:
        if not _VERSION.match(version):
            raise RegistryError("invalid version name (use letters, digits, . _ - ; max 64 chars)")
        data = self._read()
        if version in data["versions"]:
            raise RegistryError(f"version already registered: {version}")
        if parent is not None and parent not in data["versions"]:
            raise RegistryError(f"unknown parent version: {parent}")

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

        # 5. immutable snapshot
        dest = self.root / "artifacts" / version
        dest.mkdir(parents=True, exist_ok=False)
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
            "notes": notes,
        }
        data["versions"][version] = record
        self._write(data)
        return record

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

    # ---- promote / rollback ----
    def promote(self, version: str) -> None:
        if not self.verify(version):
            raise RegistryError(f"integrity check failed, refusing to activate {version}")
        data = self._read()
        if data["active"] == version:
            return
        if data["active"] is not None:
            data["history"].append(data["active"])
        data["active"] = version
        self._write(data)

    def rollback(self, to_version: str | None = None) -> str:
        """Re-activate the previous active version (or a specific registered one)."""
        data = self._read()
        if to_version is None:
            while data["history"]:
                candidate = data["history"].pop()
                if candidate in data["versions"] and candidate != data["active"] and self.verify(candidate):
                    data["active"] = candidate
                    self._write(data)
                    return candidate
            raise RegistryError("no earlier verified version to roll back to")
        if to_version not in data["versions"]:
            raise RegistryError(f"unknown version: {to_version}")
        if not self.verify(to_version):
            raise RegistryError(f"integrity check failed, refusing to activate {to_version}")
        if data["active"] not in (None, to_version):
            data["history"].append(data["active"])
        data["active"] = to_version
        self._write(data)
        return to_version
