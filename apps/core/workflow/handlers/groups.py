"""Built-in workflow step handlers (pure stdlib)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from apps.core.native.dataset import load_split_records, verify_dataset_manifest
from apps.core.native.train.StageAwareSampler import (
    StageAwareSampler,
    validate_stage_weights,
)

_V10_REPORT_SCHEMA = "zyrquen.v10.evaluation_report.v1"
_V10_EXPECTED_CAPABILITIES: tuple[str, ...] = (
    "native_core",
    "planning",
    "memory",
    "learning",
    "autonomous_execution",
    "research",
)

_DISALLOWED_PROVENANCE_TOKENS: tuple[str, ...] = (
    "fake",
    "mock",
    "fabricated",
    "synthetic_llm",
    "external_llm",
    "gpt",
    "openai",
    "claude",
    "gemini",
    "unverified",
    "uncorroborated",
    "conflicting",
    "stale",
)


def _is_valid_provenance(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    cleaned = value.strip().lower()
    if not cleaned:
        return False
    return not any(tok in cleaned for tok in _DISALLOWED_PROVENANCE_TOKENS)


def _verify_knowledge_quality_summary(
    kq: Any,
    *,
    min_provenance_coverage_pct: float = 100.0,
    allow_contradictions: bool = False,
) -> tuple[bool, str | None]:
    if kq is None:
        return True, None
    if not isinstance(kq, Mapping):
        return False, "knowledge_quality must be a mapping"

    status = str(kq.get("status") or "").strip().upper()
    if status in {"FAILED", "BLOCKED", "ERROR"}:
        return False, f"knowledge_quality status is {status}"

    contradictions = kq.get("contradiction_groups", 0)
    if isinstance(contradictions, bool) or not isinstance(contradictions, (int, float)):
        return False, "knowledge_quality.contradiction_groups must be numeric"
    if not allow_contradictions and float(contradictions) > 0:
        return False, f"knowledge_quality reports {int(contradictions)} unresolved contradiction group(s)"

    total_triples = kq.get("total_triples", 0)
    if isinstance(total_triples, bool) or not isinstance(total_triples, (int, float)):
        return False, "knowledge_quality.total_triples must be numeric"
    if float(total_triples) > 0:
        cov = kq.get("provenance_coverage_pct", 0.0)
        if isinstance(cov, bool) or not isinstance(cov, (int, float)) or not math.isfinite(float(cov)):
            return False, "knowledge_quality.provenance_coverage_pct must be a finite number"
        if float(cov) < float(min_provenance_coverage_pct):
            return (
                False,
                f"knowledge_quality provenance coverage {float(cov):.1f}% is below required {float(min_provenance_coverage_pct):.1f}%",
            )
        verified_triples = kq.get("verified_triples", total_triples)
        if isinstance(verified_triples, bool) or not isinstance(verified_triples, (int, float)):
            return False, "knowledge_quality.verified_triples must be numeric"
        if float(verified_triples) <= 0:
            return False, "knowledge_quality reports zero verified triples"

    return True, None


def _filter_verified_ingestion_records(
    raw_records: Sequence[Any],
    *,
    dataset_provenance: str | None,
    min_quality_score: float,
    require_provenance: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    verified: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for idx, item in enumerate(raw_records):
        if isinstance(item, str):
            rec: dict[str, Any] = {"text": item}
        elif isinstance(item, Mapping):
            rec = dict(item)
        else:
            rejected.append({"index": idx, "reason": "malformed_record_type"})
            continue

        if rec.get("leakage_detected") is True or rec.get("verified") is False or rec.get("knowledge_verified") is False:
            rejected.append({"index": idx, "reason": "unverified_or_leaky_record"})
            continue

        if rec.get("contradiction") is True or rec.get("has_contradiction") is True:
            rejected.append({"index": idx, "reason": "knowledge_contradiction"})
            continue

        prov = rec.get("provenance") if rec.get("provenance") is not None else rec.get("source")
        effective_prov = prov if prov is not None else dataset_provenance
        if prov is not None or require_provenance:
            if not _is_valid_provenance(effective_prov):
                rejected.append({"index": idx, "reason": "invalid_or_missing_provenance"})
                continue

        q_raw = rec.get("quality_score")
        if q_raw is None:
            q_raw = rec.get("confidence")
        if q_raw is not None:
            if isinstance(q_raw, bool) or not isinstance(q_raw, (int, float)):
                rejected.append({"index": idx, "reason": "invalid_quality_score"})
                continue
            q_val = float(q_raw)
            if not math.isfinite(q_val) or q_val < min_quality_score:
                rejected.append({"index": idx, "reason": "below_min_quality_score"})
                continue

        verified.append(rec)

    return verified, rejected


def _blocked_training_response(
    payload: Mapping[str, Any],
    *,
    reason: str,
    status: str = "BLOCKED",
    verified_count: int = 0,
    rejected_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "passed": False,
        "dataset_version": payload.get("dataset_version"),
        "external_models_used": False,
        "provenance_verified": False if "PROVENANCE" in reason else None,
        "knowledge_quality_verified": False if "KNOWLEDGE" in reason else None,
        "blocked_reason": reason,
        "error": reason,
        "verified_record_count": verified_count,
        "rejected_record_count": len(rejected_records or []),
        "rejected_records": list(rejected_records or [])[:20],
    }


def handle_evaluation_gate(payload: dict[str, Any]) -> dict[str, Any]:
    """Verify V10 evaluation report schema and anti-False-PASS gates."""
    report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
    schema = report.get("schema")
    overall = str(report.get("overall_status") or "").upper()
    passed = schema == _V10_REPORT_SCHEMA and overall == "PASS"
    return {
        "schema": _V10_REPORT_SCHEMA,
        "passed": passed,
        "overall_status": overall or "NOT_RUN",
    }


def handle_training_execute(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute governed training ingestion step with StageAwareSampler, knowledge quality, and provenance checks."""
    if not isinstance(payload, Mapping):
        return {
            "status": "FAILED",
            "passed": False,
            "external_models_used": False,
            "blocked_reason": "INVALID_PAYLOAD",
            "error": "training payload must be a mapping",
        }

    if payload.get("leakage_verified") is False or payload.get("leakage_detected") is True:
        return _blocked_training_response(payload, reason="LEAKAGE_DETECTED")

    require_provenance = bool(payload.get("require_provenance", False))
    dataset_provenance_raw = payload.get("provenance")
    if dataset_provenance_raw is not None:
        if not _is_valid_provenance(dataset_provenance_raw):
            return _blocked_training_response(
                payload,
                reason=f"PROVENANCE_VALIDATION_FAILED: disallowed or empty provenance {dataset_provenance_raw!r}",
            )
        dataset_provenance: str | None = str(dataset_provenance_raw).strip()
    else:
        dataset_provenance = None

    min_prov_cov_raw = payload.get("min_provenance_coverage_pct", 100.0)
    if isinstance(min_prov_cov_raw, bool) or not isinstance(min_prov_cov_raw, (int, float)):
        return _blocked_training_response(
            payload,
            status="FAILED",
            reason="INVALID_CONFIG: min_provenance_coverage_pct must be numeric",
        )
    kq_ok, kq_err = _verify_knowledge_quality_summary(
        payload.get("knowledge_quality"),
        min_provenance_coverage_pct=float(min_prov_cov_raw),
        allow_contradictions=bool(payload.get("allow_contradictions", False)),
    )
    if not kq_ok:
        return _blocked_training_response(
            payload,
            reason=f"KNOWLEDGE_QUALITY_VALIDATION_FAILED: {kq_err}",
        )

    min_quality_raw = payload.get("min_quality_score", 0.7)
    if isinstance(min_quality_raw, bool) or not isinstance(min_quality_raw, (int, float)) or not math.isfinite(float(min_quality_raw)):
        return _blocked_training_response(
            payload,
            status="FAILED",
            reason="INVALID_CONFIG: min_quality_score must be a finite number",
        )
    min_quality_score = float(min_quality_raw)

    raw_records: list[Any] | None = None
    for key in ("records", "entries", "samples"):
        if key in payload and payload[key] is not None:
            candidate = payload[key]
            if isinstance(candidate, (str, bytes, bytearray)) or not isinstance(candidate, Sequence):
                return _blocked_training_response(
                    payload,
                    status="FAILED",
                    reason=f"INVALID_INGESTION_INPUT: {key} must be a sequence of records",
                )
            raw_records = list(candidate)
            break

    dataset_dir = payload.get("dataset_dir")
    if raw_records is None and dataset_dir is not None:
        split_name = str(payload.get("split") or "train").strip()
        try:
            manifest = verify_dataset_manifest(Path(str(dataset_dir)))
            if dataset_provenance is None:
                manifest_prov = manifest.get("provenance")
                if manifest_prov is not None:
                    if not _is_valid_provenance(manifest_prov):
                        return _blocked_training_response(
                            payload,
                            reason=f"PROVENANCE_VALIDATION_FAILED: disallowed manifest provenance {manifest_prov!r}",
                        )
                    dataset_provenance = str(manifest_prov).strip()
            raw_records = list(load_split_records(Path(str(dataset_dir)), split_name))
        except (OSError, ValueError, TypeError) as exc:
            return _blocked_training_response(
                payload,
                status="BLOCKED",
                reason=f"DATASET_INTEGRITY_FAILED: {exc}",
            )

    explicit_weights = payload.get("stage_weights")
    stage_key = str(payload.get("stage_key") or "stage")
    seed = payload.get("seed", 0)
    num_samples = payload.get("num_samples")
    replacement = payload.get("replacement", True)

    if raw_records is None:
        if require_provenance and dataset_provenance is None:
            return _blocked_training_response(
                payload,
                reason="PROVENANCE_VALIDATION_FAILED: dataset provenance is required",
            )
        if explicit_weights is not None:
            try:
                validated_weights = validate_stage_weights(explicit_weights)
            except ValueError as exc:
                return _blocked_training_response(
                    payload,
                    status="FAILED",
                    reason=f"INVALID_STAGE_WEIGHTS: {exc}",
                )
        else:
            validated_weights = None
        return {
            "status": "READY",
            "passed": True,
            "dataset_version": payload.get("dataset_version"),
            "external_models_used": False,
            "provenance_verified": dataset_provenance is not None or not require_provenance,
            "knowledge_quality_verified": True,
            "stage_weights": validated_weights,
        }

    verified_records, rejected_records = _filter_verified_ingestion_records(
        raw_records,
        dataset_provenance=dataset_provenance,
        min_quality_score=min_quality_score,
        require_provenance=require_provenance,
    )
    if not verified_records:
        return _blocked_training_response(
            payload,
            reason="NO_VERIFIED_TRAINING_RECORDS: all ingested records failed provenance or knowledge quality checks",
            verified_count=0,
            rejected_records=rejected_records,
        )

    sampler_records = verified_records
    resolved_weights = explicit_weights
    if resolved_weights is None:
        # Derive quality-aware stage weights from verified records
        normalized_records: list[dict[str, Any]] = []
        stage_quality_totals: dict[str, float] = {}
        stage_counts_raw: dict[str, int] = {}
        for rec in verified_records:
            st = rec.get(stage_key) or rec.get("capability") or rec.get("split") or "train"
            if not isinstance(st, str) or not st.strip():
                st = "train"
            rec_copy = dict(rec)
            rec_copy[stage_key] = st
            normalized_records.append(rec_copy)
            q_val = rec.get("quality_score", rec.get("confidence", 1.0))
            q_float = float(q_val) if isinstance(q_val, (int, float)) and not isinstance(q_val, bool) else 1.0
            stage_quality_totals[st] = stage_quality_totals.get(st, 0.0) + max(0.1, q_float)
            stage_counts_raw[st] = stage_counts_raw.get(st, 0) + 1
        sampler_records = normalized_records
        resolved_weights = {
            st: stage_quality_totals[st] / stage_counts_raw[st]
            for st in stage_counts_raw
        }

    try:
        sampler = StageAwareSampler(
            sampler_records,
            stage_weights=resolved_weights,
            seed=seed,
            num_samples=num_samples,
            replacement=replacement,
            stage_key=stage_key,
        )
        sampled_indices = sampler.sample_indices()
        sampled_distribution = sampler.measure_stage_distribution(sampled_indices)
    except ValueError as exc:
        return _blocked_training_response(
            payload,
            status="FAILED",
            reason=f"STAGE_SAMPLER_CONFIG_ERROR: {exc}",
            verified_count=len(verified_records),
            rejected_records=rejected_records,
        )

    return {
        "status": "READY",
        "passed": True,
        "dataset_version": payload.get("dataset_version"),
        "external_models_used": False,
        "provenance_verified": True,
        "knowledge_quality_verified": True,
        "verified_record_count": len(verified_records),
        "rejected_record_count": len(rejected_records),
        "rejected_records": rejected_records[:20],
        "sampler": {
            "class": "StageAwareSampler",
            "seed": sampler.seed,
            "num_samples": len(sampled_indices),
            "stage_counts": sampler.stage_counts,
            "stage_weights": sampler.stage_weights,
            "normalized_weights": sampler.normalized_weights,
            "sampled_distribution": sampled_distribution,
            "sampled_indices": sampled_indices,
        },
    }


def handle_dataset_ingest(payload: dict[str, Any]) -> dict[str, Any]:
    """Record governed dataset ingestion readiness gate check."""
    return {
        "status": "READY",
        "dataset_version": payload.get("dataset_version"),
        "leakage_verified": bool(payload.get("leakage_verified", True)),
    }
