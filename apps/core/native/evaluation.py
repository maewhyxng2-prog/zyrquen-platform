# ZYRQUEN Phase 3.6 - Evaluation Engine (Core)
import json
from datetime import datetime, timezone
from pathlib import Path
from apps.core.native.checkpoint import VersionedCheckpointManager
from apps.core.training_infrastructure.validation.model_validator import ModelValidator

class EvaluationEngine:
    def __init__(self, checkpoint_dir, max_val_loss=None, max_perplexity=None):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.versions = VersionedCheckpointManager(self.checkpoint_dir)
        self.validator = ModelValidator(max_val_loss=max_val_loss, max_perplexity=max_perplexity)
    def evaluate(self, model_version: str, metrics: dict) -> dict:
        version = self.versions.get_version(model_version)
        if not version:
            raise ValueError(f"ไม่เจอ model_version: {model_version}")
        report = self.validator.validate(self.checkpoint_dir, metrics)
        if isinstance(report, dict):
            passed = bool(report.get("passed", report.get("is_valid", report.get("valid", False))))
            detail = report
        else:
            passed = bool(getattr(report, "passed", getattr(report, "is_valid", getattr(report, "valid", False))))
            detail = {"report": str(report)}
        result = {
            "schema": "zyrquen.evaluation.v1",
            "model_version": model_version,
            "dataset_version": version.get("dataset_version"),
            "dataset_content_hash": version.get("dataset_content_hash"),
            "checkpoint_file": version.get("checkpoint_file"),
            "metrics": metrics,
            "val_loss": metrics.get("val_loss"),
            "perplexity": metrics.get("perplexity"),
            "passed": passed,
            "validator": detail,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
        out = self.checkpoint_dir / f"evaluation_{model_version}.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
