import json
import logging
import os
from pathlib import Path
from threading import Lock

from .exceptions import ModelLoadError, ModelNotFoundError
from .inference import NativeInferenceEngine
from .model_loader import NativeModelLoader

logger = logging.getLogger(__name__)

NGI_CAPABILITIES = (
    ("native_representation", "Native Representation"),
    ("knowledge_acquisition", "Knowledge Acquisition"),
    ("relational_reasoning", "Relational Reasoning"),
    ("planning_decomposition", "Planning & Decomposition"),
    ("verification", "Verification"),
    ("adaptive_learning", "Adaptive Learning"),
    ("knowledge_integration", "Knowledge Integration"),
    ("generalization", "Generalization"),
)


def _normalize_pct(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if numeric <= 1.0:
        numeric *= 100.0
    return round(max(0.0, min(100.0, numeric)), 2)


def _extract_capability_score(raw_metrics: dict, key: str) -> float | None:
    if not isinstance(raw_metrics, dict):
        return None
    per_cap = raw_metrics.get("capabilities") or raw_metrics.get("test_per_capability")
    if isinstance(per_cap, dict) and key in per_cap:
        entry = per_cap[key]
        if isinstance(entry, dict):
            fg = entry.get("free_generation")
            if isinstance(fg, dict) and "exact_match" in fg:
                return _normalize_pct(fg["exact_match"])
            if "score" in entry:
                return _normalize_pct(entry["score"])
            if "exact_match" in entry:
                return _normalize_pct(entry["exact_match"])
        return _normalize_pct(entry)
    return _normalize_pct(raw_metrics.get(f"{key}_score"))


class NativeRuntime:
    def __init__(self, loader=None):
        self.loader = loader or NativeModelLoader()
        self.engine = NativeInferenceEngine(self.loader)

        self._initialized = False
        self._initialization_lock = Lock()

    def initialize(self) -> bool:
        with self._initialization_lock:
            if self.loader.is_ready():
                self._initialized = True
                return True

            try:
                self.loader.load()
                self._initialized = self.loader.is_ready()

            except ModelNotFoundError:
                logger.warning("Native model artifact is not configured or installed")
                self._initialized = False

            except ModelLoadError:
                logger.exception("Native model initialization failed")
                self._initialized = False

            return self._initialized

    def is_ready(self) -> bool:
        return self._initialized and self.loader.is_ready()

    def _load_real_eval_metrics(self) -> tuple[dict, str | None]:
        evidence = getattr(self.loader, "evidence", None)
        if isinstance(evidence, dict) and isinstance(evidence.get("metrics"), dict) and evidence["metrics"]:
            return evidence["metrics"], "active_model_registry"

        report_env = os.getenv("ZYRQUEN_EVAL_REPORT_PATH", "").strip()
        if report_env:
            report_path = Path(report_env)
            if report_path.is_file() and not report_path.is_symlink():
                try:
                    data = json.loads(report_path.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and data:
                        return data, str(report_path)
                except (OSError, json.JSONDecodeError):
                    logger.warning("Failed to parse ZYRQUEN_EVAL_REPORT_PATH")
        return {}, None

    def get_health_status(self) -> dict:
        ready = self.is_ready()
        if ready:
            runtime_status = "ready"
        else:
            health_fn = getattr(self.loader, "health_state", None)
            if callable(health_fn):
                state = health_fn()
                runtime_status = state if state in {"not_configured", "degraded"} else "degraded"
            else:
                model_path = getattr(self.loader, "model_path", None)
                runtime_status = (
                    "not_configured"
                    if (model_path is None or not model_path.is_dir())
                    else "degraded"
                )

        model_version = getattr(self.loader, "model_version", None) if ready else None
        platform_version = os.getenv("ZYRQUEN_PLATFORM_VERSION", "").strip() or model_version

        raw_metrics, metrics_source = self._load_real_eval_metrics()
        capabilities = []
        if raw_metrics:
            for key, label in NGI_CAPABILITIES:
                score = _extract_capability_score(raw_metrics, key)
                if score is not None:
                    capabilities.append(
                        {
                            "key": key,
                            "label": label,
                            "score": score,
                            "status": "measured",
                        }
                    )

        gen_score = _normalize_pct(raw_metrics.get("generalization_score"))
        if gen_score is None and raw_metrics:
            gen_score = _extract_capability_score(raw_metrics, "generalization")

        rel_rate = _normalize_pct(raw_metrics.get("relational_reasoning_success_rate"))
        if rel_rate is None and raw_metrics:
            rel_rate = _extract_capability_score(raw_metrics, "relational_reasoning")

        has_progress = gen_score is not None or rel_rate is not None

        return {
            "runtime_status": runtime_status,
            "native_model_loaded": self.loader.is_ready(),
            "platform_version": platform_version,
            "model_version": model_version,
            "artifact_origin": getattr(self.loader, "artifact_origin", None) if ready else None,
            "is_trained": bool(getattr(self.loader, "is_trained", False)) if ready else False,
            "max_seq_len": getattr(self.loader, "max_seq_len", None) if ready else None,
            "authority": "ZYRQUEN Native AI Core",
            "inference_available": ready,
            "progress_metrics": (
                {
                    "generalization_score": gen_score,
                    "relational_reasoning_success_rate": rel_rate,
                    "evaluation_status": "evaluated",
                    "metrics_source": metrics_source,
                }
                if has_progress
                else None
            ),
            "capabilities": capabilities,
        }

    def shutdown(self) -> None:
        """Release native model resources during application shutdown."""
        with self._initialization_lock:
            self._initialized = False
            unload_fn = getattr(self.loader, "unload", None)
            if callable(unload_fn):
                unload_fn()
            else:
                self.loader.model = None
                self.loader.tokenizer = None


runtime = NativeRuntime()
