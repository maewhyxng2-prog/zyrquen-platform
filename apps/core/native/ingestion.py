"""Raw Data Ingestion, Pre-Ingestion Leakage Gate & V11 Dataset Version Mapper (pure stdlib)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from apps.core.dataset_leakage_detector import (
    DatasetLeakageDetector,
    SemanticHashLeakageError,
    extract_record_text,
    normalize_text,
)
from apps.core.native.dataset import V11_SPLITS, clean_text, redact_pii
from apps.core.native.dataset_status import (
    get_dataset_version_status,
    ingest_v11_dataset,
    inspect_v11_training_dataset_readiness,
    validate_dataset_version,
    verify_dataset_approval_ticket,
)

MAX_RAW_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MiB
MAX_INGESTION_RECORDS = 50_000

_SUPPORTED_FORMATS = frozenset({"auto", "jsonl", "json", "csv", "text"})
_DEFAULT_SPLIT_RATIOS: dict[str, float] = {
    "train": 0.70,
    "validation": 0.10,
    "unseen": 0.10,
    "ood": 0.10,
}


class RawIngestionError(ValueError):
    """Raised when raw upload payload is malformed or fails pre-ingestion validation."""


class IngestionPayloadTooLargeError(ValueError):
    """Raised when raw upload payload exceeds configured byte or record limits."""


def _validate_split_ratios(split_ratios: Mapping[str, float] | None) -> dict[str, float]:
    if not split_ratios:
        return dict(_DEFAULT_SPLIT_RATIOS)
    cleaned: dict[str, float] = {}
    for sp in V11_SPLITS:
        val = split_ratios.get(sp)
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            raise RawIngestionError(f"split_ratios must include numeric fraction for {sp!r}.")
        fval = float(val)
        if fval <= 0.0 or fval >= 1.0:
            raise RawIngestionError(f"split_ratios[{sp!r}] must be strictly between 0 and 1.")
        cleaned[sp] = fval
    total = sum(cleaned.values())
    if abs(total - 1.0) > 1e-3:
        raise RawIngestionError(f"split_ratios must sum to 1.0 (got {total:.4f}).")
    return cleaned


def _coerce_entry_to_record(raw_item: Any, idx: int) -> dict[str, Any]:
    if isinstance(raw_item, str):
        text = clean_text(raw_item)
        if not text:
            raise RawIngestionError(f"Record at index {idx} is empty.")
        return {"text": text}
    if not isinstance(raw_item, Mapping):
        raise RawIngestionError(f"Record at index {idx} must be a string or JSON object.")

    out: dict[str, Any] = {}
    split_val = raw_item.get("split")
    if split_val is not None:
        sp_clean = str(split_val).strip().lower()
        if sp_clean == "val":
            sp_clean = "validation"
        if sp_clean not in V11_SPLITS:
            raise RawIngestionError(
                f"Record at index {idx} has invalid split {split_val!r}; expected one of {list(V11_SPLITS)}."
            )
        out["split"] = sp_clean

    if "input" in raw_item and "target" in raw_item:
        inp = clean_text(str(raw_item.get("input") or ""))
        tgt = clean_text(str(raw_item.get("target") or ""))
        if not inp or not tgt:
            raise RawIngestionError(f"SFT record at index {idx} has empty 'input' or 'target'.")
        out["input"] = inp
        out["target"] = tgt
        if raw_item.get("capability"):
            out["capability"] = str(raw_item["capability"]).strip()
        return out

    if "prompt" in raw_item and ("completion" in raw_item or "response" in raw_item):
        inp = clean_text(str(raw_item.get("prompt") or ""))
        tgt = clean_text(str(raw_item.get("completion") or raw_item.get("response") or ""))
        if not inp or not tgt:
            raise RawIngestionError(f"Prompt/completion record at index {idx} has empty text.")
        out["input"] = inp
        out["target"] = tgt
        return out

    if all(k in raw_item for k in ("subject", "relation", "object")):
        subj = clean_text(str(raw_item.get("subject") or ""))
        rel = clean_text(str(raw_item.get("relation") or ""))
        obj = clean_text(str(raw_item.get("object") or ""))
        if not subj or not rel or not obj:
            raise RawIngestionError(f"Triple record at index {idx} has empty subject/relation/object.")
        out["text"] = f"{subj} {rel} {obj}"
        return out

    for key in ("text", "content", "document", "body"):
        if key in raw_item and raw_item.get(key) is not None:
            txt = clean_text(str(raw_item.get(key) or ""))
            if not txt:
                raise RawIngestionError(f"Text record at index {idx} is empty.")
            out["text"] = txt
            return out

    raise RawIngestionError(
        f"Record at index {idx} must contain ('input','target'), ('prompt','completion'), ('subject','relation','object'), or 'text'."
    )


def parse_raw_entries(
    *,
    raw_content: str | bytes | None = None,
    entries: Sequence[Any] | None = None,
    fmt: str = "auto",
    max_bytes: int = MAX_RAW_UPLOAD_BYTES,
    max_records: int = MAX_INGESTION_RECORDS,
) -> tuple[list[dict[str, Any]], str]:
    """Parse raw upload bytes/text or structured entries cleanly into normalized records."""
    clean_fmt = str(fmt or "auto").strip().lower()
    if clean_fmt not in _SUPPORTED_FORMATS:
        raise RawIngestionError(
            f"Unsupported raw ingestion format {fmt!r}; expected one of {sorted(_SUPPORTED_FORMATS)}."
        )

    if entries is not None and raw_content is not None:
        raise RawIngestionError("Provide either 'raw_content' or 'entries', not both.")
    if entries is None and raw_content is None:
        raise RawIngestionError("Either 'raw_content' or 'entries' is required.")

    if entries is not None:
        if len(entries) > max_records:
            raise IngestionPayloadTooLargeError(
                f"Entry count ({len(entries)}) exceeds maximum allowed ({max_records})."
            )
        parsed = [_coerce_entry_to_record(item, idx) for idx, item in enumerate(entries)]
        if not parsed:
            raise RawIngestionError("No valid records found in entries payload.")
        return parsed, "json"

    if isinstance(raw_content, (bytes, bytearray)):
        if len(raw_content) > max_bytes:
            raise IngestionPayloadTooLargeError(
                f"Raw upload size ({len(raw_content)} bytes) exceeds limit ({max_bytes} bytes)."
            )
        if b"\x00" in raw_content:
            raise RawIngestionError("Binary null bytes are not permitted in raw dataset uploads.")
        try:
            text_payload = bytes(raw_content).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RawIngestionError("Raw upload must be valid UTF-8 text.") from exc
    else:
        text_payload = str(raw_content or "")
        encoded_len = len(text_payload.encode("utf-8"))
        if encoded_len > max_bytes:
            raise IngestionPayloadTooLargeError(
                f"Raw upload size ({encoded_len} bytes) exceeds limit ({max_bytes} bytes)."
            )
        if "\x00" in text_payload:
            raise RawIngestionError("Null bytes are not permitted in raw dataset uploads.")

    stripped = text_payload.strip()
    if not stripped:
        raise RawIngestionError("Raw upload payload is empty.")

    detected_fmt = clean_fmt
    if detected_fmt == "auto":
        if stripped.startswith("[") or (stripped.startswith("{") and "\n" not in stripped):
            detected_fmt = "json"
        else:
            lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
            if lines and all(ln.startswith("{") and ln.endswith("}") for ln in lines[:5]):
                detected_fmt = "jsonl"
            elif lines and ("," in lines[0]) and any(
                hdr in lines[0].lower() for hdr in ("input,target", "text", "prompt,completion", "subject,relation,object")
            ):
                detected_fmt = "csv"
            else:
                detected_fmt = "text"

    records: list[dict[str, Any]] = []
    if detected_fmt == "json":
        try:
            loaded = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise RawIngestionError(f"Invalid JSON upload: {exc}") from exc
        if isinstance(loaded, dict) and isinstance(loaded.get("entries"), list):
            loaded = loaded["entries"]
        if isinstance(loaded, dict):
            loaded = [loaded]
        if not isinstance(loaded, list):
            raise RawIngestionError("JSON upload must be a JSON object or array of records.")
        if len(loaded) > max_records:
            raise IngestionPayloadTooLargeError(
                f"Record count ({len(loaded)}) exceeds maximum allowed ({max_records})."
            )
        records = [_coerce_entry_to_record(item, idx) for idx, item in enumerate(loaded)]
    elif detected_fmt == "jsonl":
        for idx, line in enumerate(stripped.splitlines()):
            ln = line.strip()
            if not ln:
                continue
            if len(records) >= max_records:
                raise IngestionPayloadTooLargeError(
                    f"Record count exceeds maximum allowed ({max_records})."
                )
            try:
                obj = json.loads(ln)
            except json.JSONDecodeError as exc:
                raise RawIngestionError(f"Invalid JSONL at line {idx + 1}: {exc}") from exc
            records.append(_coerce_entry_to_record(obj, idx))
    elif detected_fmt == "csv":
        reader = csv.DictReader(io.StringIO(stripped))
        if not reader.fieldnames:
            raise RawIngestionError("CSV upload is missing header columns.")
        for idx, row in enumerate(reader):
            if len(records) >= max_records:
                raise IngestionPayloadTooLargeError(
                    f"Record count exceeds maximum allowed ({max_records})."
                )
            records.append(_coerce_entry_to_record(row, idx))
    else:  # text
        blocks = [blk.strip() for blk in re.split(r"\n{2,}", stripped) if blk.strip()]
        if len(blocks) == 1:
            blocks = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
        if len(blocks) > max_records:
            raise IngestionPayloadTooLargeError(
                f"Record count ({len(blocks)}) exceeds maximum allowed ({max_records})."
            )
        records = [_coerce_entry_to_record(blk, idx) for idx, blk in enumerate(blocks)]

    if not records:
        raise RawIngestionError("No valid records parsed from raw upload.")
    return records, detected_fmt


def map_entries_to_v11_splits(
    records: Sequence[Mapping[str, Any]],
    *,
    do_redact_pii: bool = True,
    split_ratios: Mapping[str, float] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Deterministically deduplicate and map records into 4 V11 splits required for training."""
    ratios = _validate_split_ratios(split_ratios)
    cleaned_records: list[dict[str, Any]] = []
    seen_norms: set[str] = set()
    detected_mode: str | None = None

    for idx, row in enumerate(records):
        rec = dict(row)
        if "input" in rec and "target" in rec:
            mode = "sft"
            inp = clean_text(str(rec["input"]))
            tgt = clean_text(str(rec["target"]))
            if do_redact_pii:
                inp = redact_pii(inp)
                tgt = redact_pii(tgt)
            if not inp or not tgt:
                continue
            item: dict[str, Any] = {"input": inp, "target": tgt}
            if rec.get("capability"):
                item["capability"] = str(rec["capability"])
        elif "text" in rec:
            mode = "text"
            txt = clean_text(str(rec["text"]))
            if do_redact_pii:
                txt = redact_pii(txt)
            if not txt:
                continue
            item = {"text": txt}
        else:
            raise RawIngestionError(f"Normalized record at index {idx} has invalid schema.")

        if detected_mode is None:
            detected_mode = mode
        elif detected_mode != mode:
            raise RawIngestionError(
                "Mixed SFT ('input','target') and plain 'text' records in one ingestion upload are forbidden."
            )

        norm_key = normalize_text(extract_record_text(item))
        if not norm_key or norm_key in seen_norms:
            continue
        seen_norms.add(norm_key)
        if "split" in rec:
            item["split"] = rec["split"]
        cleaned_records.append(item)

    if len(cleaned_records) < len(V11_SPLITS):
        raise RawIngestionError(
            f"At least {len(V11_SPLITS)} unique records are required to populate V11 4-split datasets "
            f"{list(V11_SPLITS)} (got {len(cleaned_records)})."
        )

    splits: dict[str, list[dict[str, Any]]] = {sp: [] for sp in V11_SPLITS}
    unassigned: list[tuple[str, dict[str, Any]]] = []

    t_train = ratios["train"]
    t_val = t_train + ratios["validation"]
    t_unseen = t_val + ratios["unseen"]

    for item in cleaned_records:
        explicit_sp = item.get("split")
        if explicit_sp in V11_SPLITS:
            splits[explicit_sp].append(item)
            continue
        digest = hashlib.sha256(
            normalize_text(extract_record_text(item)).encode("utf-8")
        ).hexdigest()
        bucket = int(digest[:8], 16) / 0x100000000
        if bucket < t_train:
            assigned = "train"
        elif bucket < t_val:
            assigned = "validation"
        elif bucket < t_unseen:
            assigned = "unseen"
        else:
            assigned = "ood"
        unassigned.append((digest, {**item, "split": assigned}))
        splits[assigned].append({**item, "split": assigned})

    # If deterministic hash bucketing left any non-explicit split empty (small datasets),
    # deterministically rebalance from the largest split (sorted by digest) without guessing.
    if all("split" not in r for r in cleaned_records):
        for sp in V11_SPLITS:
            if not splits[sp]:
                donor_sp = max(V11_SPLITS, key=lambda name: len(splits[name]))
                if len(splits[donor_sp]) <= 1:
                    break
                moved = splits[donor_sp].pop()
                moved["split"] = sp
                splits[sp].append(moved)

    empty = [sp for sp in V11_SPLITS if not splits[sp]]
    if empty:
        raise RawIngestionError(
            f"All 4 V11 splits {list(V11_SPLITS)} must be non-empty; empty splits: {empty}."
        )
    return splits


def _collect_existing_dataset_dirs(
    *,
    dataset_root: str | Path | None = None,
    dataset_dir: str | Path | None = None,
) -> tuple[list[Path], Path | None]:
    root_val = str(
        dataset_root if dataset_root is not None else os.getenv("ZYRQUEN_DATASET_ROOT", "")
    ).strip()
    dir_val = str(
        dataset_dir if dataset_dir is not None else os.getenv("ZYRQUEN_DATASET_DIR", "")
    ).strip()

    dirs: list[Path] = []
    resolved_root: Path | None = None
    if root_val:
        raw_root = Path(root_val)
        if not raw_root.is_symlink() and raw_root.is_dir():
            resolved_root = raw_root.resolve()
            for child in sorted(resolved_root.iterdir()):
                if child.is_dir() and not child.is_symlink() and not child.name.startswith("."):
                    dirs.append(child)
    if dir_val:
        raw_dir = Path(dir_val)
        if not raw_dir.is_symlink() and raw_dir.is_dir():
            res_dir = raw_dir.resolve()
            if res_dir not in dirs:
                dirs.append(res_dir)
    return dirs, resolved_root


def validate_raw_ingestion(
    *,
    raw_content: str | bytes | None = None,
    entries: Sequence[Any] | None = None,
    fmt: str = "auto",
    do_redact_pii: bool = True,
    split_ratios: Mapping[str, float] | None = None,
    dataset_root: str | Path | None = None,
    dataset_dir: str | Path | None = None,
    simhash_max_hamming: int = 16,
    min_semantic_similarity: float = 0.68,
) -> dict[str, Any]:
    """Parse raw data, map deterministically to V11 4-split structure, and run DatasetLeakageDetector."""
    parsed, detected_fmt = parse_raw_entries(
        raw_content=raw_content,
        entries=entries,
        fmt=fmt,
    )
    splits = map_entries_to_v11_splits(
        parsed,
        do_redact_pii=do_redact_pii,
        split_ratios=split_ratios,
    )
    existing_dirs, resolved_root = _collect_existing_dataset_dirs(
        dataset_root=dataset_root,
        dataset_dir=dataset_dir,
    )
    detector = DatasetLeakageDetector(
        simhash_max_hamming=simhash_max_hamming,
        min_semantic_similarity=min_semantic_similarity,
    )
    leakage_report = detector.check_entries(
        splits,
        reference_dirs=existing_dirs,
        allowed_root=resolved_root,
        check_internal_splits=True,
        raise_on_leakage=False,
    )
    return {
        "valid": leakage_report.passed,
        "detected_format": detected_fmt,
        "parsed_records": len(parsed),
        "split_counts": {sp: len(rows) for sp, rows in splits.items()},
        "splits": splits,
        "leakage_report": leakage_report.to_dict(),
    }


def ingest_raw_dataset_upload(
    *,
    dataset_version: str,
    source_name: str,
    license_str: str,
    provenance: str,
    raw_content: str | bytes | None = None,
    entries: Sequence[Any] | None = None,
    fmt: str = "auto",
    do_redact_pii: bool = True,
    split_ratios: Mapping[str, float] | None = None,
    approval_id: str | None = None,
    workflow_engine: Any | None = None,
    dataset_root: str | Path | None = None,
    dataset_dir: str | Path | None = None,
    require_approval: bool = True,
) -> dict[str, Any]:
    """Validate raw upload with DatasetLeakageDetector and persist as verified training dataset version."""
    clean_version = validate_dataset_version(dataset_version)
    if require_approval:
        verify_dataset_approval_ticket(
            workflow_engine,
            approval_id,
            dataset_version=clean_version,
        )

    validation = validate_raw_ingestion(
        raw_content=raw_content,
        entries=entries,
        fmt=fmt,
        do_redact_pii=do_redact_pii,
        split_ratios=split_ratios,
        dataset_root=dataset_root,
        dataset_dir=dataset_dir,
    )
    if not validation["valid"]:
        violations = validation["leakage_report"].get("violations") or []
        raise SemanticHashLeakageError(
            f"Pre-ingestion semantic leakage validation failed: {', '.join(violations)}"
        )

    ingested = ingest_v11_dataset(
        dataset_version=clean_version,
        splits=validation["splits"],
        source_name=source_name,
        license_str=license_str,
        provenance=provenance,
        dataset_root=dataset_root,
        do_redact_pii=do_redact_pii,
        approval_id=approval_id,
        workflow_engine=workflow_engine,
        require_approval=require_approval,
    )

    root_val = str(
        dataset_root if dataset_root is not None else os.getenv("ZYRQUEN_DATASET_ROOT", "")
    ).strip()
    version_dir = (Path(root_val).resolve() / clean_version).resolve() if root_val else None
    training_readiness = inspect_v11_training_dataset_readiness(version_dir)

    return {
        "ingested": True,
        "dataset_version": clean_version,
        "detected_format": validation["detected_format"],
        "parsed_records": validation["parsed_records"],
        "split_counts": validation["split_counts"],
        "pre_ingestion_leakage": validation["leakage_report"],
        "dataset_status": ingested,
        "training_pipeline_mapping": {
            "dataset_version": clean_version,
            "content_sha256": ingested.get("content_sha256"),
            "four_split_ready": bool(training_readiness.get("verified")),
            "required_splits": list(V11_SPLITS),
            "split_counts": training_readiness.get("split_counts", {}),
        },
    }


def get_dataset_training_mapping(
    dataset_version: str,
    *,
    dataset_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return verified dataset version manifest & training pipeline compatibility mapping."""
    clean_version = validate_dataset_version(dataset_version)
    version_status = get_dataset_version_status(clean_version, dataset_root=dataset_root)
    root_val = str(
        dataset_root if dataset_root is not None else os.getenv("ZYRQUEN_DATASET_ROOT", "")
    ).strip()
    version_dir = (Path(root_val).resolve() / clean_version).resolve() if root_val else None
    readiness = inspect_v11_training_dataset_readiness(version_dir)
    return {
        "dataset_version": clean_version,
        "status": version_status.get("status"),
        "verified": bool(version_status.get("verified")),
        "training_ready": bool(version_status.get("training_ready")) and bool(readiness.get("verified")),
        "content_sha256": version_status.get("content_sha256"),
        "format": version_status.get("format"),
        "splits": version_status.get("splits"),
        "split_counts": version_status.get("split_counts"),
        "approval_gate": version_status.get("approval_gate"),
        "training_readiness": readiness,
    }
