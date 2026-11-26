# ZYRQUEN Phase 3.5 - Checkpoint + Model Versioning
#
# This file does not implement checkpoint storage. It wraps the existing
# CheckpointManager and adds version metadata around its real checkpoint files.

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.core.training_infrastructure.recovery.checkpoint_recovery import CheckpointManager


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _hash_dict(data: dict) -> str:
    text = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class ModelVersion:
    model_version: str
    parent_version: str | None
    step: int
    checkpoint_file: str
    checkpoint_sha256: str
    dataset_version: str
    dataset_content_hash: str
    config_hash: str
    tokenizer_sha256: str | None = None
    val_loss: float | None = None
    perplexity: float | None = None
    created_at: str = ""
    metrics: dict | None = None


class VersionedCheckpointManager:
    """
    Wrap CheckpointManager and add model-version metadata.
    Checkpoint files remain written and verified by CheckpointManager.
    """

    def __init__(
        self,
        checkpoint_dir: str | Path,
        keep_last: int = 3,
        *,
        save_fn=None,
        load_fn=None,
    ):
        self.dir = Path(checkpoint_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        kwargs = {}
        if save_fn is not None:
            kwargs["save_fn"] = save_fn
        if load_fn is not None:
            kwargs["load_fn"] = load_fn
        self._inner = CheckpointManager(self.dir, keep_last=keep_last, **kwargs)
        self.version_manifest_path = self.dir / "version_manifest.json"

    def _read_versions(self) -> list[dict]:
        if not self.version_manifest_path.exists():
            return []
        try:
            data = json.loads(
                self.version_manifest_path.read_text(encoding="utf-8")
            )
            return data.get("versions", [])
        except Exception:
            return []

    def _write_versions(self, versions: list[dict]) -> None:
        payload = {
            "schema": "zyrquen.model-version-manifest.v1",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "versions": versions,
        }
        tmp = self.version_manifest_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.version_manifest_path)

    def save_versioned(
        self,
        *,
        step: int,
        state: Any,
        model_version: str,
        dataset_version: str,
        dataset_content_hash: str,
        config: dict,
        parent_version: str | None = None,
        tokenizer_sha256: str | None = None,
        val_loss: float | None = None,
        perplexity: float | None = None,
        metrics: dict | None = None,
    ) -> dict:
        existing = self._read_versions()
        if any(
            version.get("model_version") == model_version
            for version in existing
        ):
            raise ValueError(
                f"model_version duplicate: {model_version} already exists"
            )

        resolved_tok_sha = tokenizer_sha256
        if resolved_tok_sha is None and isinstance(state, dict):
            raw_tok = state.get("tokenizer_sha256")
            if isinstance(raw_tok, str) and raw_tok:
                resolved_tok_sha = raw_tok

        ckpt_path = self._inner.save(step, state)
        ckpt_sha = (
            _sha256_file(ckpt_path)
            if ckpt_path.exists()
            else ""
        )

        entry = ModelVersion(
            model_version=model_version,
            parent_version=parent_version,
            step=step,
            checkpoint_file=ckpt_path.name,
            checkpoint_sha256=ckpt_sha,
            dataset_version=dataset_version,
            dataset_content_hash=dataset_content_hash,
            config_hash=_hash_dict(config),
            tokenizer_sha256=resolved_tok_sha,
            val_loss=val_loss,
            perplexity=perplexity,
            created_at=datetime.now(timezone.utc).isoformat(),
            metrics=metrics or {},
        )
        data = asdict(entry)
        existing.append(data)
        self._write_versions(existing)
        return data

    def register_existing_checkpoint(
        self,
        *,
        model_version: str,
        dataset_version: str,
        dataset_content_hash: str,
        config: dict,
        parent_version: str | None = None,
        tokenizer_sha256: str | None = None,
        val_loss: float | None = None,
        perplexity: float | None = None,
        metrics: dict | None = None,
        step: int | None = None,
    ) -> dict:
        """Index the latest (or specified) CheckpointManager artifact in version_manifest.json without duplicating .pt."""
        existing = self._read_versions()
        if any(version.get("model_version") == model_version for version in existing):
            raise ValueError(f"model_version duplicate: {model_version} already exists")

        manifest_entries = self._inner._read_manifest()
        if step is not None:
            inner_entry = next(
                (item for item in manifest_entries if item.get("step") == step),
                None,
            )
            if inner_entry is None or not self._inner.verify(inner_entry):
                raise ValueError(f"checkpoint integrity verification failed for step {step}")
        else:
            inner_entry = self._inner.latest_valid()
            if inner_entry is None:
                raise ValueError("no verified checkpoint found in checkpoint_dir")

        ckpt_path = self.dir / inner_entry["file"]
        resolved_tok_sha = tokenizer_sha256
        if not resolved_tok_sha:
            try:
                loaded = self._inner._load(str(ckpt_path))
                if isinstance(loaded, dict):
                    raw_tok = loaded.get("tokenizer_sha256")
                    if isinstance(raw_tok, str) and raw_tok:
                        resolved_tok_sha = raw_tok
            except Exception:
                pass

        entry = ModelVersion(
            model_version=model_version,
            parent_version=parent_version,
            step=int(inner_entry["step"]),
            checkpoint_file=str(inner_entry["file"]),
            checkpoint_sha256=_sha256_file(ckpt_path),
            dataset_version=dataset_version,
            dataset_content_hash=dataset_content_hash,
            config_hash=_hash_dict(config),
            tokenizer_sha256=resolved_tok_sha,
            val_loss=val_loss,
            perplexity=perplexity,
            created_at=datetime.now(timezone.utc).isoformat(),
            metrics=metrics or {},
        )
        data = asdict(entry)
        existing.append(data)
        self._write_versions(existing)
        return data

    def list_versions(self) -> list[dict]:
        return self._read_versions()

    def get_version(self, model_version: str) -> dict | None:
        for version in self._read_versions():
            if version.get("model_version") == model_version:
                return version
        return None

    def latest_version(self) -> dict | None:
        versions = self._read_versions()
        return versions[-1] if versions else None

    def verify_version(
        self,
        model_version: str,
        *,
        expected_tokenizer_sha256: str | None = None,
    ) -> bool:
        entry = self.get_version(model_version)
        if not entry:
            return False

        if expected_tokenizer_sha256 is not None:
            if entry.get("tokenizer_sha256") != expected_tokenizer_sha256:
                return False

        ckpt_path = self.dir / entry["checkpoint_file"]
        if not ckpt_path.exists():
            return False
        if _sha256_file(ckpt_path) != entry["checkpoint_sha256"]:
            return False

        if not self._inner.manifest_path.exists():
            return False
        try:
            manifest = json.loads(
                self._inner.manifest_path.read_text(encoding="utf-8")
            )
            inner_entry = next(
                (
                    item
                    for item in manifest["checkpoints"]
                    if item["file"] == entry["checkpoint_file"]
                    and item["step"] == entry["step"]
                ),
                None,
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            return False

        return inner_entry is not None and self._inner.verify(inner_entry)

    def load_latest(self):
        return self._inner.load_latest()
