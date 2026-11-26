import hashlib
import json
import logging
import os
import re
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from apps.core.native.config import ZyrquenConfig
from apps.core.native.registry import ModelRegistry, RegistryError
from apps.core.native.tokenizer import ZyrquenTokenizer

from .exceptions import ModelLoadError, ModelNotFoundError

logger = logging.getLogger(__name__)
native_generation_lock = Lock()

NATIVE_MODEL_VERSION_RE = re.compile(
    r"^ZYRQUEN-Native-(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
)
ARTIFACT_MANIFEST_SCHEMA = "zyrquen.native-artifact.v1"


def _safe_torch_load(path: str) -> Any:
    import torch

    return torch.load(path, map_location="cpu", weights_only=True)


def validate_native_model_version(version: str | None) -> str:
    if not isinstance(version, str) or not NATIVE_MODEL_VERSION_RE.match(version):
        raise ModelLoadError(
            "Invalid native model version; expected ZYRQUEN-Native-MAJOR.MINOR.PATCH."
        )
    return version


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_safe_artifact_file(rel_or_name: str, base_dir: Path, label: str) -> Path:
    if not isinstance(rel_or_name, str) or not rel_or_name.strip():
        raise ModelLoadError(f"Missing path for native {label}.")
    rel_path = Path(rel_or_name)
    if rel_path.is_absolute():
        raise ModelLoadError(f"Absolute path is not allowed for native {label}.")

    resolved_base = base_dir.resolve()
    raw_target = base_dir / rel_path
    # Reject symlinks on the target file or any parent component inside base_dir.
    cur = base_dir
    for part in rel_path.parts:
        cur = cur / part
        if cur.is_symlink():
            raise ModelLoadError(f"Refusing symlinked native {label}: {cur}")

    resolved_target = raw_target.resolve()
    if not resolved_target.is_relative_to(resolved_base):
        raise ModelLoadError(f"Native {label} path escapes artifact root.")
    return resolved_target


def _read_json(path: Path) -> dict:
    if path.is_symlink():
        raise ModelLoadError(f"Refusing symlinked metadata file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelLoadError(f"Failed to read JSON metadata: {path}") from exc
    if not isinstance(data, dict):
        raise ModelLoadError(f"Metadata root must be a JSON object: {path}")
    return data


def _extract_state_dict(state: dict) -> dict:
    model_state = state.get("model")
    if not isinstance(model_state, dict) or not model_state:
        raise ModelLoadError("Checkpoint does not contain a valid native model state_dict.")
    return model_state


class NativeModelLoader:
    def __init__(
        self,
        model_path: str | Path | None = None,
        *,
        registry_root: str | Path | None = None,
        model_version: str | None = None,
        load_fn: Callable[[str], Any] = _safe_torch_load,
    ):
        self._project_root = Path(__file__).resolve().parents[2]

        raw_registry = (
            str(registry_root).strip()
            if registry_root is not None
            else os.getenv("ZYRQUEN_MODEL_REGISTRY_ROOT", "").strip()
        )
        raw_model_path = (
            str(model_path).strip()
            if model_path is not None
            else os.getenv("ZYRQUEN_MODEL_PATH", "").strip()
        )
        raw_version = (
            str(model_version).strip()
            if model_version is not None
            else os.getenv("ZYRQUEN_MODEL_VERSION", "").strip()
        )

        self.registry_root: Path | None = (
            self._resolve_path(raw_registry) if raw_registry else None
        )
        self.model_path: Path | None = (
            self._resolve_path(raw_model_path) if raw_model_path else None
        )
        self.requested_version: str | None = raw_version or None
        self._load_fn = load_fn

        self.model = None
        self.tokenizer: ZyrquenTokenizer | None = None
        self.model_config: ZyrquenConfig | None = None
        self.model_version: str | None = None
        self.checkpoint_sha256: str | None = None
        self.tokenizer_sha256: str | None = None
        self.dataset_version: str | None = None
        self.dataset_content_sha256: str | None = None
        self.artifact_origin: str | None = None
        self.prompt_format: str | None = None
        self.artifact_metrics: dict[str, Any] = {}
        self.is_trained: bool = False
        self.evidence: dict[str, Any] = {}

        self._last_error: str | None = None
        self._last_error_kind: str | None = None
        self._load_lock = Lock()

    def _resolve_path(self, raw: str | Path) -> Path:
        path = Path(raw)
        return path if path.is_absolute() else (self._project_root / path)

    @property
    def max_seq_len(self) -> int | None:
        if self.model_config is not None:
            return self.model_config.max_seq_len
        cfg = getattr(self.model, "cfg", None)
        return getattr(cfg, "max_seq_len", None)

    def _reset_loaded_state(self) -> None:
        self.model = None
        self.tokenizer = None
        self.model_config = None
        self.model_version = None
        self.checkpoint_sha256 = None
        self.tokenizer_sha256 = None
        self.dataset_version = None
        self.dataset_content_sha256 = None
        self.artifact_origin = None
        self.prompt_format = None
        self.artifact_metrics = {}
        self.is_trained = False
        self.evidence = {}

    def unload(self) -> None:
        with self._load_lock:
            self._reset_loaded_state()
            self._last_error = None
            self._last_error_kind = None

    def _effective_registry_root(self) -> Path | None:
        if self.registry_root is not None:
            return self.registry_root
        if (
            self.model_path is not None
            and self.model_path.is_dir()
            and (self.model_path / "registry.json").is_file()
        ):
            return self.model_path
        return None

    def is_configured(self) -> bool:
        reg_root = self._effective_registry_root()
        if reg_root is not None:
            reg_file = reg_root / "registry.json"
            if not reg_root.is_dir() or not reg_file.is_file():
                return False
            try:
                data = _read_json(reg_file)
            except ModelLoadError:
                return True
            target = self.requested_version or data.get("active")
            return bool(target)
        if self.model_path is not None:
            return self.model_path.exists()
        return False

    def health_state(self) -> str:
        if self.is_ready():
            return "ready"
        if self._last_error_kind == "load_error":
            return "degraded"
        if self._last_error_kind == "not_found":
            return "not_configured"
        return "degraded" if self.is_configured() else "not_configured"

    def _resolve_from_registry(self, reg_root: Path) -> dict[str, Any]:
        reg_file = reg_root / "registry.json"
        if not reg_root.is_dir() or not reg_file.is_file():
            raise ModelNotFoundError(
                f"Native model registry not configured at: {reg_root}"
            )
        if reg_root.is_symlink() or reg_file.is_symlink():
            raise ModelLoadError("Refusing symlinked native model registry or registry.json.")

        try:
            registry = ModelRegistry(reg_root, load_fn=self._load_fn)
            version = self.requested_version or registry.active_version()
        except RegistryError as exc:
            raise ModelLoadError(f"Native model registry error: {exc}") from exc

        if not version:
            raise ModelNotFoundError(
                "No active native model version is configured in the registry."
            )

        validate_native_model_version(version)

        try:
            record = registry.get(version)
        except RegistryError as exc:
            raise ModelLoadError(f"Registry verification failed: {exc}") from exc

        ckpt_meta = record.get("checkpoint") or {}
        tok_meta = record.get("tokenizer") or {}
        ds_meta = record.get("dataset") or {}

        ckpt_path = _ensure_safe_artifact_file(ckpt_meta.get("path", ""), reg_root, "checkpoint")
        tok_path = _ensure_safe_artifact_file(tok_meta.get("path", ""), reg_root, "tokenizer")
        ds_manifest_path = _ensure_safe_artifact_file(
            ds_meta.get("path", ""), reg_root, "dataset manifest"
        )

        try:
            if not registry.verify(version):
                raise ModelLoadError(
                    f"Registry integrity verification failed for {version}."
                )
        except RegistryError as exc:
            raise ModelLoadError(f"Registry verification failed: {exc}") from exc

        return {
            "origin": "model_registry",
            "version": version,
            "checkpoint_path": ckpt_path,
            "checkpoint_sha256": ckpt_meta.get("sha256"),
            "checkpoint_step": ckpt_meta.get("step"),
            "tokenizer_path": tok_path,
            "tokenizer_fingerprint": tok_meta.get("sha256"),
            "tokenizer_file_sha256": tok_meta.get("file_sha256"),
            "tokenizer_schema": tok_meta.get("schema"),
            "dataset_manifest_path": ds_manifest_path,
            "dataset_version": ds_meta.get("version"),
            "dataset_content_sha256": ds_meta.get("content_sha256"),
            "model_config": record.get("model_config"),
            "prompt_format": record.get("prompt_format"),
            "metrics": record.get("metrics") or {},
        }

    def _resolve_from_artifact_dir(self, artifact_dir: Path) -> dict[str, Any]:
        if not artifact_dir.exists():
            raise ModelNotFoundError(
                f"Native model directory not found: {artifact_dir}"
            )
        if artifact_dir.is_symlink() or not artifact_dir.is_dir():
            raise ModelLoadError(
                f"Native model path must be a non-symlink directory: {artifact_dir}"
            )

        manifest_path = artifact_dir / "artifact_manifest.json"
        if not manifest_path.is_file():
            raise ModelLoadError(
                "Rejected non-native artifact directory: missing artifact_manifest.json or registry.json."
            )

        manifest = _read_json(manifest_path)
        if manifest.get("schema") != ARTIFACT_MANIFEST_SCHEMA:
            raise ModelLoadError(
                f"Unsupported artifact manifest schema: {manifest.get('schema')}"
            )

        version = self.requested_version or manifest.get("model_version")
        if self.requested_version and manifest.get("model_version") != self.requested_version:
            raise ModelLoadError(
                f"Artifact version mismatch: expected {self.requested_version}, found {manifest.get('model_version')}."
            )
        validate_native_model_version(version)

        ckpt_meta = manifest.get("checkpoint") or {}
        tok_meta = manifest.get("tokenizer") or {}
        ds_meta = manifest.get("dataset") or {}

        ckpt_path = _ensure_safe_artifact_file(
            ckpt_meta.get("file") or "checkpoint.pt", artifact_dir, "checkpoint"
        )
        tok_path = _ensure_safe_artifact_file(
            tok_meta.get("file") or "tokenizer.json", artifact_dir, "tokenizer"
        )
        ds_manifest_path = _ensure_safe_artifact_file(
            ds_meta.get("manifest_file") or "dataset_manifest.json",
            artifact_dir,
            "dataset manifest",
        )

        expected_ckpt_sha = ckpt_meta.get("sha256")
        expected_tok_file_sha = tok_meta.get("file_sha256")
        expected_tok_fp = tok_meta.get("sha256")
        expected_ds_content_sha = ds_meta.get("content_sha256")
        if not expected_ckpt_sha or not expected_tok_file_sha or not expected_tok_fp:
            raise ModelLoadError("Artifact manifest is missing required SHA-256 digests.")

        if not ckpt_path.is_file() or _file_sha256(ckpt_path) != expected_ckpt_sha:
            raise ModelLoadError("Checkpoint SHA-256 verification failed.")
        if not tok_path.is_file() or _file_sha256(tok_path) != expected_tok_file_sha:
            raise ModelLoadError("Tokenizer file SHA-256 verification failed.")
        if not ds_manifest_path.is_file():
            raise ModelLoadError("Dataset manifest file is missing.")
        ds_manifest = _read_json(ds_manifest_path)
        if expected_ds_content_sha and ds_manifest.get("content_sha256") != expected_ds_content_sha:
            raise ModelLoadError("Dataset manifest content_sha256 verification failed.")

        return {
            "origin": "native_artifact_dir",
            "version": version,
            "checkpoint_path": ckpt_path,
            "checkpoint_sha256": expected_ckpt_sha,
            "checkpoint_step": ckpt_meta.get("step"),
            "tokenizer_path": tok_path,
            "tokenizer_fingerprint": expected_tok_fp,
            "tokenizer_file_sha256": expected_tok_file_sha,
            "tokenizer_schema": tok_meta.get("schema"),
            "dataset_manifest_path": ds_manifest_path,
            "dataset_version": ds_meta.get("version") or ds_manifest.get("version"),
            "dataset_content_sha256": expected_ds_content_sha or ds_manifest.get("content_sha256"),
            "model_config": manifest.get("model_config"),
            "prompt_format": manifest.get("prompt_format"),
            "metrics": manifest.get("metrics") or {},
        }

    def load(self) -> None:
        with self._load_lock:
            if self.is_ready():
                return

            self._last_error = None
            self._last_error_kind = None

            try:
                reg_root = self._effective_registry_root()
                if reg_root is not None:
                    spec = self._resolve_from_registry(reg_root)
                elif self.model_path is not None:
                    spec = self._resolve_from_artifact_dir(self.model_path)
                else:
                    raise ModelNotFoundError(
                        "Neither ZYRQUEN_MODEL_REGISTRY_ROOT nor ZYRQUEN_MODEL_PATH is configured."
                    )

                ckpt_path: Path = spec["checkpoint_path"]
                tok_path: Path = spec["tokenizer_path"]

                if not ckpt_path.is_file():
                    raise ModelLoadError(f"Checkpoint file missing: {ckpt_path}")
                actual_ckpt_sha = _file_sha256(ckpt_path)
                if spec["checkpoint_sha256"] != actual_ckpt_sha:
                    raise ModelLoadError("Checkpoint SHA-256 mismatch.")

                try:
                    tokenizer = ZyrquenTokenizer.load(tok_path)
                except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
                    raise ModelLoadError(
                        f"Native tokenizer failed integrity check: {exc}"
                    ) from exc

                actual_tok_fp = tokenizer.fingerprint()
                if spec["tokenizer_fingerprint"] != actual_tok_fp:
                    raise ModelLoadError("Tokenizer fingerprint SHA-256 mismatch.")

                try:
                    state = self._load_fn(str(ckpt_path))
                except Exception as exc:
                    raise ModelLoadError(
                        f"Failed to load checkpoint payload: {exc}"
                    ) from exc

                if not isinstance(state, dict):
                    raise ModelLoadError("Checkpoint payload must be a dictionary.")

                if state.get("tokenizer_sha256") != actual_tok_fp:
                    raise ModelLoadError(
                        "Checkpoint tokenizer_sha256 does not match loaded tokenizer fingerprint."
                    )

                expected_ds_version = spec.get("dataset_version")
                if not expected_ds_version or state.get("dataset_version") != expected_ds_version:
                    raise ModelLoadError(
                        "Checkpoint dataset_version does not match artifact dataset manifest."
                    )

                raw_cfg = state.get("model_config")
                if not isinstance(raw_cfg, dict) or not raw_cfg:
                    raise ModelLoadError("Checkpoint is missing model_config.")

                expected_cfg = spec.get("model_config")
                if isinstance(expected_cfg, dict) and expected_cfg and expected_cfg != raw_cfg:
                    raise ModelLoadError(
                        "Checkpoint model_config does not match registry/artifact metadata."
                    )

                try:
                    cfg = ZyrquenConfig.from_dict(raw_cfg)
                except (TypeError, ValueError) as exc:
                    raise ModelLoadError(f"Invalid ZyrquenConfig: {exc}") from exc

                if cfg.vocab_size != tokenizer.vocab_size:
                    raise ModelLoadError(
                        f"Config vocab_size ({cfg.vocab_size}) does not match "
                        f"ZyrquenTokenizer vocab_size ({tokenizer.vocab_size})."
                    )

                state_dict = _extract_state_dict(state)

                try:
                    import torch
                    from apps.core.native.model import ZyrquenModel
                except ImportError as exc:
                    raise ModelLoadError(
                        "PyTorch runtime is not available for ZyrquenModel."
                    ) from exc

                try:
                    model = ZyrquenModel(cfg)
                    model.load_state_dict(state_dict, strict=True)
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                    model.to(device)
                    model.eval()
                except Exception as exc:
                    raise ModelLoadError(
                        f"Failed to construct ZyrquenModel or load weights: {exc}"
                    ) from exc

                expected_tok_schema = spec.get("tokenizer_schema")
                if expected_tok_schema and tokenizer.schema != expected_tok_schema:
                    raise ModelLoadError(
                        f"Tokenizer schema mismatch: expected {expected_tok_schema}, got {tokenizer.schema}."
                    )

                prompt_format = state.get("prompt_format") or spec.get("prompt_format")
                if (
                    spec.get("prompt_format")
                    and state.get("prompt_format")
                    and spec.get("prompt_format") != state.get("prompt_format")
                ):
                    raise ModelLoadError("Checkpoint prompt_format does not match artifact metadata.")

                step = int(state.get("step") or spec.get("checkpoint_step") or 0)
                metrics = spec.get("metrics") or {}
                has_training_evidence = bool(
                    step > 0
                    and state.get("config") is not None
                    and (metrics or state.get("train_loss") is not None)
                )
                has_eval_evidence = bool(
                    isinstance(metrics, dict)
                    and any(k in metrics for k in ("val_loss", "perplexity", "eval_loss"))
                )

                self.tokenizer = tokenizer
                self.model = model
                self.model_config = cfg
                self.model_version = spec["version"]
                self.checkpoint_sha256 = actual_ckpt_sha
                self.tokenizer_sha256 = actual_tok_fp
                self.dataset_version = expected_ds_version
                self.dataset_content_sha256 = spec.get("dataset_content_sha256")
                self.artifact_origin = spec["origin"]
                self.prompt_format = prompt_format if isinstance(prompt_format, str) else None
                self.artifact_metrics = dict(metrics) if isinstance(metrics, dict) else {}
                self.is_trained = has_training_evidence
                self.evidence = {
                    "model_version": spec["version"],
                    "checkpoint_step": step,
                    "prompt_format": self.prompt_format,
                    "has_training_evidence": has_training_evidence,
                    "has_evaluation_evidence": has_eval_evidence,
                    "capability_status": (
                        "evaluated"
                        if (has_training_evidence and has_eval_evidence)
                        else (
                            "trained_unverified"
                            if has_training_evidence
                            else "untrained_baseline"
                        )
                    ),
                }
                if self.artifact_metrics:
                    self.evidence["metrics"] = dict(self.artifact_metrics)

                logger.info(
                    "ZYRQUEN native model loaded version=%s origin=%s device=%s",
                    self.model_version,
                    self.artifact_origin,
                    device,
                )

            except ModelNotFoundError as exc:
                self._reset_loaded_state()
                self._last_error = str(exc)
                self._last_error_kind = "not_found"
                raise
            except ModelLoadError as exc:
                self._reset_loaded_state()
                self._last_error = str(exc)
                self._last_error_kind = "load_error"
                raise
            except Exception as exc:
                self._reset_loaded_state()
                self._last_error = str(exc)
                self._last_error_kind = "load_error"
                logger.exception("Native model loading failed")
                raise ModelLoadError(
                    "Unable to load the native model artifact."
                ) from exc

    def is_ready(self) -> bool:
        return (
            self.model is not None
            and self.tokenizer is not None
            and self.model_config is not None
            and self.model_version is not None
        )
