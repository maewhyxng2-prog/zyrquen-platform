"""ZYRQUEN Native Evaluation Engine.

Provides verifiable checkpoint integrity, dataset manifest/SHA-256 verification,
and evaluation threshold validation without hardcoded datasets or dummy metrics.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.core.native.checkpoint import VersionedCheckpointManager
from apps.core.native.dataset import SCHEMA as DATASET_SCHEMA, SPLITS as DATASET_SPLITS
from apps.core.training_infrastructure.validation.model_validator import ModelValidator


class EvaluationError(ValueError):
    """Base error for verifiable evaluation failures."""


class EvaluationEvidenceError(EvaluationError):
    """Raised when required dataset, checkpoint, or evaluation evidence is missing or invalid."""


class EvaluationNotConfiguredError(RuntimeError):
    """Raised when evaluation artifacts or native evaluation execution are not configured."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class EvaluationEngine:
    def __init__(
        self,
        checkpoint_dir: str | Path | None = None,
        max_val_loss: float | None = None,
        max_perplexity: float | None = None,
    ):
        self.max_val_loss = max_val_loss
        self.max_perplexity = max_perplexity
        self.validator = ModelValidator(
            max_val_loss=max_val_loss,
            max_perplexity=max_perplexity,
        )
        if checkpoint_dir is None:
            self.checkpoint_dir: Path | None = None
            self.versions: VersionedCheckpointManager | None = None
        else:
            self.checkpoint_dir = Path(checkpoint_dir)
            self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
            self.versions = VersionedCheckpointManager(self.checkpoint_dir)

    def get_status(self) -> dict[str, Any]:
        configured = self.checkpoint_dir is not None and self.checkpoint_dir.is_dir()
        return {
            "status": "evidence_validation_only" if configured else "not_configured",
            "checkpoint_dir_configured": configured,
            "native_inference_evaluation_wired": False,
        }

    def _require_configured(self) -> tuple[Path, VersionedCheckpointManager]:
        if self.checkpoint_dir is None or self.versions is None:
            raise EvaluationNotConfiguredError(
                "checkpoint_dir is not configured for evaluation"
            )
        return self.checkpoint_dir, self.versions

    def verify_checkpoint_version(
        self,
        model_version: str,
        *,
        checkpoint_id: str | None = None,
    ) -> dict[str, Any]:
        _, versions = self._require_configured()
        if not isinstance(model_version, str) or not model_version.strip():
            raise EvaluationEvidenceError("model_version must be a non-empty string")
        version = versions.get_version(model_version)
        if not version:
            raise EvaluationEvidenceError(f"ไม่เจอ model_version: {model_version}")
        if not versions.verify_version(model_version):
            raise EvaluationEvidenceError(
                f"checkpoint integrity check failed for model_version: {model_version}"
            )
        if checkpoint_id is not None and checkpoint_id not in {
            version.get("checkpoint_file"),
            version.get("checkpoint_sha256"),
        }:
            raise EvaluationEvidenceError(
                f"checkpoint_id does not match model_version {model_version}"
            )
        return version

    def verify_dataset(
        self,
        dataset_dir: str | Path,
        *,
        expected_version: str | None = None,
        expected_checksum: str | None = None,
    ) -> dict[str, Any]:
        if dataset_dir is None or str(dataset_dir).strip() == "":
            raise EvaluationEvidenceError("dataset_dir is required for evaluation")
        root = Path(dataset_dir)
        if not root.is_dir():
            raise EvaluationEvidenceError(f"dataset directory not found: {root}")
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise EvaluationEvidenceError(f"dataset manifest.json not found in: {root}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvaluationEvidenceError(
                f"dataset manifest.json is unreadable: {root}"
            ) from exc

        if not isinstance(manifest, dict) or manifest.get("schema") != DATASET_SCHEMA:
            raise EvaluationEvidenceError("unsupported or invalid dataset manifest schema")

        files = manifest.get("files")
        if not isinstance(files, dict):
            raise EvaluationEvidenceError("dataset manifest missing files metadata")

        for split in DATASET_SPLITS:
            filename = f"{split}.jsonl"
            entry = files.get(filename)
            split_path = root / filename
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("sha256"), str)
                or not split_path.is_file()
            ):
                raise EvaluationEvidenceError(
                    f"dataset integrity check failed: missing {filename}"
                )
            if _sha256_file(split_path) != entry["sha256"]:
                raise EvaluationEvidenceError(
                    f"dataset integrity check failed: {filename} checksum mismatch"
                )

        combined = hashlib.sha256(
            "".join(files[f"{split}.jsonl"]["sha256"] for split in DATASET_SPLITS).encode("utf-8")
        ).hexdigest()
        if combined != manifest.get("content_sha256"):
            raise EvaluationEvidenceError("dataset content_sha256 does not match manifest")

        eval_doc_count = sum(
            int(files[f"{split}.jsonl"].get("documents", 0))
            for split in ("validation", "test")
        )
        if eval_doc_count <= 0:
            raise EvaluationEvidenceError(
                "dataset contains no validation or test documents for evaluation"
            )

        if expected_version is not None and manifest.get("version") != expected_version:
            raise EvaluationEvidenceError(
                "dataset version does not match checkpoint dataset_version"
            )
        if (
            expected_checksum is not None
            and manifest["content_sha256"].lower() != expected_checksum.lower()
        ):
            raise EvaluationEvidenceError(
                "dataset checksum does not match expected dataset_checksum"
            )
        return manifest

    def evaluate(
        self,
        model_version: str,
        metrics: dict[str, Any],
        *,
        dataset_dir: str | Path | None = None,
        dataset_checksum: str | None = None,
    ) -> dict[str, Any]:
        checkpoint_dir, _ = self._require_configured()
        version = self.verify_checkpoint_version(model_version)

        if not isinstance(metrics, dict) or not metrics:
            raise EvaluationEvidenceError(
                "metrics must be a non-empty dictionary of verifiable evaluation evidence"
            )
        for key in ("val_loss", "perplexity"):
            if key in metrics and isinstance(metrics[key], bool):
                raise EvaluationEvidenceError(f"metric {key!r} must not be a boolean")

        dataset_manifest: dict[str, Any] | None = None
        if dataset_dir is not None:
            dataset_manifest = self.verify_dataset(
                dataset_dir,
                expected_version=version.get("dataset_version"),
                expected_checksum=dataset_checksum or version.get("dataset_content_hash"),
            )
        elif dataset_checksum is not None:
            expected_hash = version.get("dataset_content_hash")
            if not expected_hash or expected_hash.lower() != dataset_checksum.lower():
                raise EvaluationEvidenceError(
                    "dataset_checksum does not match checkpoint dataset_content_hash"
                )

        report = self.validator.validate(checkpoint_dir, metrics)
        if isinstance(report, dict):
            passed = bool(report.get("passed", report.get("is_valid", report.get("valid", False))))
            detail = report
        else:
            passed = bool(getattr(report, "passed", getattr(report, "is_valid", getattr(report, "valid", False))))
            detail = {"checks": getattr(report, "checks", []), "passed": passed}

        result = {
            "schema": "zyrquen.evaluation.v1",
            "model_version": model_version,
            "dataset_version": version.get("dataset_version"),
            "dataset_content_hash": (
                dataset_manifest["content_sha256"]
                if dataset_manifest is not None
                else version.get("dataset_content_hash")
            ),
            "checkpoint_file": version.get("checkpoint_file"),
            "checkpoint_sha256": version.get("checkpoint_sha256"),
            "metrics": dict(metrics),
            "val_loss": metrics.get("val_loss"),
            "perplexity": metrics.get("perplexity"),
            "passed": passed,
            "validator": detail,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
        out = (checkpoint_dir / f"evaluation_{model_version}.json").resolve()
        if not out.is_relative_to(checkpoint_dir.resolve()):
            raise EvaluationEvidenceError("model_version produces an invalid report path")
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, out)
        return result

    def run_evaluation(
        self,
        model_version: str,
        *,
        dataset_dir: str | Path | None = None,
        dataset_checksum: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_configured()
        version = self.verify_checkpoint_version(model_version)
        if dataset_dir is None:
            raise EvaluationEvidenceError(
                "dataset_dir is required; hardcoded dataset paths are not permitted"
            )
        self.verify_dataset(
            dataset_dir,
            expected_version=version.get("dataset_version"),
            expected_checksum=dataset_checksum,
        )
        if metrics is None:
            raise EvaluationNotConfiguredError(
                "Native model inference evaluation is not wired; cannot compute metrics without verified evaluation evidence"
            )
        return self.evaluate(
            model_version,
            metrics,
            dataset_dir=dataset_dir,
            dataset_checksum=dataset_checksum,
        )

