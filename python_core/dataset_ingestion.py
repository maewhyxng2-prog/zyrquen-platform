#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — Real-Data Dataset Ingestion Pipeline (Python 3.11 Standard Library Only)
-------------------------------------------------------------------------------------
Capabilities:
1. Real-Data Multi-Format Ingestion:
   - Plain text (line-by-line or document blocks)
   - JSONL ({"text": ...}, {"input": ..., "target": ...}, or {"subject": ..., "relation": ..., "object": ...})
   - JSON (array of records/strings OR pre-split object {"train": [...], "validation"/"val": [...], "test": [...], ...})
   - CSV (auto-detects text / input+target / subject+relation+object and optional split column)
2. Provenance & License Enforcement:
   - Rejects empty provenance/source/license (when specified) and synthetic/external LLM tokens
   - Records full source attribution, format, ingestion timestamp, and user ID
3. Manifest & Cryptographic Checksums (SHA-256):
   - Computes input_sha256, per-split JSONL SHA-256, content_sha256, and manifest_sha256
   - Atomically persists immutable dataset bundle under DATA_DIR/datasets/<slug>_<id8>/ (never overwrites)
   - Real verification (`verify_dataset_integrity`) recomputing DB + disk SHA-256 checksums
4. Multi-Layer Data Leakage Detection:
   - Exact & canonical normalized duplicates across ALL split pairs (train<->val, train<->test, val<->test, unseen, ood)
   - Near-duplicate token Jaccard overlap across ALL split pairs
   - Template leakage (slot-masked skeleton collision with numeric/ID/quoted slots)
   - Entity overlap audit (plus optional strict entity isolation enforcement)
   - Held-out benchmark contamination detection
5. Governed Knowledge Graph Extraction & Approval Gate Staging:
   - Extracts explicit or deterministic factual triples (subject, relation, object)
   - Scans contradictions against existing `knowledge_triples` and within the batch
   - NEVER bypasses the Approval Gate: stages proposals in `kg_ingestion_proposals` (`PENDING_APPROVAL`)
   - Commits to `knowledge_triples` ONLY after Admin approval + checksum/leakage re-verification
"""

from __future__ import annotations

import collections
import csv
import hashlib
import io
import json
import random
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from apps.core.dataset_leakage_detector import DatasetLeakageDetector

SCHEMA_VERSION = "zyrquen.dataset-manifest.v1"

DISALLOWED_PROVENANCE_TOKENS = (
    "fake",
    "mock",
    "fabricated",
    "synthetic_llm",
    "external_llm",
    "gpt",
    "openai",
    "claude",
    "gemini",
    "chatgpt",
    "anthropic",
    "llama",
)

_ZERO_WIDTH_MAP = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+66|0)[\s\-]?\d{1,2}[\s\-]?\d{3}[\s\-]?\d{3,4}(?!\d)")
_THAI_ID_RE = re.compile(r"(?<!\d)\d{1}[\s\-]?\d{4}[\s\-]?\d{5}[\s\-]?\d{2}[\s\-]?\d{1}(?!\d)")
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)")

_UUID_OR_HEX_RE = re.compile(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b|\b[0-9a-f]{12,}\b", re.IGNORECASE)
_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_QUOTED_RE = re.compile(r"(['\"])(?:\\.|(?!\1).)*\1")
_ENTITY_TOKEN_RE = re.compile(r"\b(?:[A-Z][A-Za-z0-9_.-]{1,32}|[A-Z]{2,}[A-Za-z0-9_.-]*)\b")

_ARROW_TRIPLE_RE = re.compile(
    r"^(?:สอน\s*:\s*|teach\s*:\s*)?(.+?)\s*(?:->|→)\s*(.+?)\s*(?:->|→)\s*(.+)$",
    re.IGNORECASE,
)
_EN_FACT_RE = re.compile(
    r"^([A-Za-z0-9_.-]{2,40}(?:\s+[A-Za-z0-9_.-]{2,30})?)\s+"
    r"(supports|uses|provides|contains|requires|enables|stores|verifies|enforces|produces|depends_on)\s+"
    r"([A-Za-z0-9_.,:\-/ ]{2,80})[.;]?$",
    re.IGNORECASE,
)
_TH_FACT_RE = re.compile(
    r"^([\u0E00-\u0E7FA-Za-z0-9_.-]{2,48})\s+"
    r"(รองรับ|ใช้|จัดเก็บ|พัฒนาโดย|ประกอบด้วย|เชื่อมต่อ|บังคับใช้|ตรวจสอบ|ป้องกัน)\s+"
    r"([\u0E00-\u0E7FA-Za-z0-9_.,:\-/ ]{2,80})[.;]?$"
)

_FALLBACK_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u0E00-\u0E7F]{2,}")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def clean_text(text: str) -> str:
    cleaned = unicodedata.normalize("NFC", str(text or "")).translate(_ZERO_WIDTH_MAP)
    cleaned = _CONTROL_RE.sub("", cleaned).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in cleaned.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def redact_pii_with_stats(text: str) -> tuple[str, dict[str, int]]:
    out, email_n = _EMAIL_RE.subn("[EMAIL]", text)
    out, thai_id_n = _THAI_ID_RE.subn("[ID]", out)
    out, card_n = _CARD_RE.subn("[NUMBER]", out)
    out, phone_n = _PHONE_RE.subn("[PHONE]", out)
    stats = {
        "email": email_n,
        "thai_id": thai_id_n,
        "card_number": card_n,
        "phone": phone_n,
        "total_redacted": email_n + thai_id_n + card_n + phone_n,
    }
    return out, stats


def redact_pii(text: str) -> str:
    redacted, _ = redact_pii_with_stats(text)
    return redacted


def _default_canonical_key(text: str) -> str:
    base = re.sub(r"[^\w\u0E00-\u0E7F\s]", " ", str(text or "").casefold())
    return re.sub(r"\s+", " ", base).strip()


def _default_tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _FALLBACK_TOKEN_RE.finditer(str(text or ""))]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name or "").strip()).strip("-.")
    return (slug[:48] or "dataset").lower()


def init_dataset_pipeline_schema(conn: sqlite3.Connection) -> None:
    """Safely migrate `datasets` metadata columns and create `kg_ingestion_proposals` table."""
    existing_cols = {
        r["name"] for r in conn.execute("PRAGMA table_info(datasets)").fetchall()
    }
    add_cols = [
        ("source_name", "TEXT NOT NULL DEFAULT 'developer_manual_corpus'"),
        ("license", "TEXT NOT NULL DEFAULT 'INTERNAL_VERIFIED'"),
        ("provenance", "TEXT NOT NULL DEFAULT 'developer_manual_corpus'"),
        ("source_format", "TEXT NOT NULL DEFAULT 'text'"),
        ("content_sha256", "TEXT NOT NULL DEFAULT ''"),
        ("manifest_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("artifact_dir", "TEXT"),
    ]
    for col_name, col_def in add_cols:
        if col_name not in existing_cols:
            conn.execute(f"ALTER TABLE datasets ADD COLUMN {col_name} {col_def}")

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS kg_ingestion_proposals (
            id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL,
            dataset_name TEXT NOT NULL,
            provenance TEXT NOT NULL,
            source_name TEXT NOT NULL,
            license TEXT NOT NULL,
            manifest_hash TEXT NOT NULL,
            proposal_checksum TEXT NOT NULL,
            triples_json TEXT NOT NULL,
            contradictions_json TEXT NOT NULL,
            triple_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'PENDING_APPROVAL'
                CHECK(status IN ('PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'BLOCKED')),
            submitted_by TEXT NOT NULL,
            approved_by TEXT,
            decision_reason TEXT,
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_kg_proposals_status_created
            ON kg_ingestion_proposals(status, created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_kg_proposals_dataset
            ON kg_ingestion_proposals(dataset_id);
        """
    )


def validate_provenance_metadata(
    *,
    name: str,
    provenance: str | None,
    source_name: str | None,
    license_str: str | None,
) -> tuple[str, str, str, str]:
    clean_name = clean_text(name)[:80] or "untitled-corpus"
    clean_prov = clean_text(provenance or "developer_manual_corpus")[:160]
    clean_source = clean_text(source_name or clean_prov or "developer_manual_corpus")[:120]
    clean_license = clean_text(license_str or "INTERNAL_VERIFIED")[:120]

    if not clean_prov:
        raise ValueError("Dataset provenance is required.")
    if not clean_source:
        raise ValueError("Dataset source_name is required.")
    if not clean_license:
        raise ValueError("Dataset license is required.")

    combined = f"{clean_name} {clean_prov} {clean_source} {clean_license}".lower()
    for tok in DISALLOWED_PROVENANCE_TOKENS:
        if tok in combined:
            raise ValueError(
                f"Dataset rejected: disallowed synthetic or external model provenance '{clean_prov}' (matched token '{tok}')."
            )
    return clean_name, clean_prov, clean_source, clean_license


def _apply_redact_pii(text: str, pii_stats: dict[str, int] | None) -> str:
    redacted, counts = redact_pii_with_stats(text)
    if pii_stats is not None:
        for k, v in counts.items():
            pii_stats[k] = int(pii_stats.get(k, 0)) + int(v)
    return redacted


def _record_from_obj(
    obj: Any,
    *,
    default_source: str,
    do_redact_pii: bool,
    pii_stats: dict[str, int] | None = None,
) -> dict[str, Any] | None:
    """Convert raw dict or string record into normalized internal record dict."""
    if isinstance(obj, str):
        txt = clean_text(obj)
        if do_redact_pii:
            txt = _apply_redact_pii(txt, pii_stats)
        if not txt:
            return None
        return {"text": txt, "source": default_source, "kind": "text"}

    if not isinstance(obj, dict):
        return None

    declared_split = str(obj.get("split") or "").strip().lower() or None
    if declared_split == "validation":
        declared_split = "val"
    rec_source = clean_text(str(obj.get("source") or default_source))[:120] or default_source

    if "subject" in obj and "relation" in obj and "object" in obj:
        subj = clean_text(str(obj["subject"]))
        rel = clean_text(str(obj["relation"]))
        target_obj = clean_text(str(obj["object"]))
        if do_redact_pii:
            subj = _apply_redact_pii(subj, pii_stats)
            rel = _apply_redact_pii(rel, pii_stats)
            target_obj = _apply_redact_pii(target_obj, pii_stats)
        if not subj or not rel or not target_obj:
            return None
        txt = f"{subj} -> {rel} -> {target_obj}"
        rec: dict[str, Any] = {
            "text": txt,
            "triple": {"subject": subj, "relation": rel, "object": target_obj},
            "source": rec_source,
            "kind": "kg_triple",
        }
        if declared_split:
            rec["split"] = declared_split
        return rec

    if "input" in obj and "target" in obj:
        inp = clean_text(str(obj["input"]))
        tgt = clean_text(str(obj["target"]))
        if do_redact_pii:
            inp = _apply_redact_pii(inp, pii_stats)
            tgt = _apply_redact_pii(tgt, pii_stats)
        if not inp or not tgt:
            return None
        rec = {
            "text": f"{inp} => {tgt}",
            "input": inp,
            "target": tgt,
            "source": rec_source,
            "kind": "sft",
        }
        if declared_split:
            rec["split"] = declared_split
        return rec

    if "text" in obj or "content" in obj:
        txt = clean_text(str(obj.get("text") if "text" in obj else obj.get("content")))
        if do_redact_pii:
            txt = _apply_redact_pii(txt, pii_stats)
        if not txt:
            return None
        rec = {"text": txt, "source": rec_source, "kind": "text"}
        if declared_split:
            rec["split"] = declared_split
        return rec

    return None


def _detect_format(raw_text: str, requested_format: str, explicit_splits: Any) -> str:
    fmt = str(requested_format or "auto").strip().lower()
    if explicit_splits is not None:
        return "pre_split_json"
    if fmt in {"text", "jsonl", "json", "csv"}:
        return fmt
    stripped = raw_text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict) and any(k in parsed for k in ("train", "val", "validation", "test")):
                return "pre_split_json"
            if isinstance(parsed, list):
                return "json"
        except json.JSONDecodeError:
            pass
    non_empty = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    if non_empty and all(ln.startswith("{") and ln.endswith("}") for ln in non_empty[:5]):
        try:
            for ln in non_empty[:5]:
                json.loads(ln)
            return "jsonl"
        except json.JSONDecodeError:
            pass
    if len(non_empty) >= 2:
        header = non_empty[0].lower()
        header_cols = {c.strip() for c in header.split(",")}
        if header_cols & {"text", "content", "input", "subject"} and (
            "text" in header_cols
            or ("input" in header_cols and "target" in header_cols)
            or ({"subject", "relation", "object"} <= header_cols)
        ):
            return "csv"
    return "text"


def parse_real_dataset_payload(
    *,
    raw_text: str,
    requested_format: str = "auto",
    explicit_splits: dict[str, Any] | None = None,
    default_source: str,
    do_redact_pii: bool = True,
    pii_stats: dict[str, int] | None = None,
) -> tuple[str, list[dict[str, Any]], dict[str, list[dict[str, Any]]] | None]:
    """
    Parse real datasets in text, jsonl, json, csv, or pre-split JSON format.
    Returns `(resolved_format, flat_records, pre_split_dict_or_none)`.
    """
    fmt = _detect_format(raw_text, requested_format, explicit_splits)
    records: list[dict[str, Any]] = []

    if fmt == "pre_split_json":
        splits_obj = explicit_splits
        if splits_obj is None:
            splits_obj = json.loads(raw_text)
        if not isinstance(splits_obj, dict):
            raise ValueError("Pre-split JSON payload must be an object containing split arrays.")
        key_map = {
            "train": "train",
            "val": "val",
            "validation": "val",
            "test": "test",
            "unseen": "unseen",
            "ood": "ood",
        }
        parsed_splits: dict[str, list[dict[str, Any]]] = {}
        for raw_k, target_k in key_map.items():
            if raw_k in splits_obj and isinstance(splits_obj[raw_k], list):
                bucket = parsed_splits.setdefault(target_k, [])
                for item in splits_obj[raw_k]:
                    rec = _record_from_obj(item, default_source=default_source, do_redact_pii=do_redact_pii, pii_stats=pii_stats)
                    if rec is not None:
                        rec["split"] = target_k
                        bucket.append(rec)
                        records.append(rec)
        if not parsed_splits.get("train") or not parsed_splits.get("val") or not parsed_splits.get("test"):
            raise ValueError("Pre-split dataset requires non-empty train, val/validation, and test splits.")
        return "pre_split_json", records, parsed_splits

    if fmt == "json":
        parsed = json.loads(raw_text)
        if not isinstance(parsed, list):
            raise ValueError("JSON dataset must be an array of records or a pre-split object.")
        for item in parsed:
            rec = _record_from_obj(item, default_source=default_source, do_redact_pii=do_redact_pii, pii_stats=pii_stats)
            if rec is not None:
                records.append(rec)
    elif fmt == "jsonl":
        for idx, line in enumerate(raw_text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at line {idx}: {exc}") from exc
            rec = _record_from_obj(obj, default_source=default_source, do_redact_pii=do_redact_pii, pii_stats=pii_stats)
            if rec is not None:
                records.append(rec)
    elif fmt == "csv":
        reader = csv.DictReader(io.StringIO(raw_text))
        if not reader.fieldnames:
            raise ValueError("CSV dataset requires a header row.")
        for row in reader:
            cleaned_row = {str(k or "").strip().lower(): (v or "") for k, v in row.items()}
            rec = _record_from_obj(cleaned_row, default_source=default_source, do_redact_pii=do_redact_pii, pii_stats=pii_stats)
            if rec is not None:
                records.append(rec)
    else:
        for line in raw_text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            rec = _record_from_obj(stripped, default_source=default_source, do_redact_pii=do_redact_pii, pii_stats=pii_stats)
            if rec is not None:
                records.append(rec)

    # Check if records carry explicit split assignments covering train + val + test
    explicit_buckets: dict[str, list[dict[str, Any]]] = {}
    has_split_labels = any("split" in r for r in records)
    if has_split_labels and all("split" in r for r in records):
        for r in records:
            sp = str(r["split"])
            if sp in {"train", "val", "test", "unseen", "ood"}:
                explicit_buckets.setdefault(sp, []).append(r)
        if explicit_buckets.get("train") and explicit_buckets.get("val") and explicit_buckets.get("test"):
            return fmt, records, explicit_buckets

    return fmt, records, None


def _template_skeleton(text: str, tokenize_fn: Callable[[str], list[str]]) -> tuple[str, bool]:
    """Mask numeric/UUID/quoted slots; return `(skeleton, has_slot_marker)`."""
    has_slot = False
    s = str(text or "")
    if _UUID_OR_HEX_RE.search(s):
        s = _UUID_OR_HEX_RE.sub(" <ID> ", s)
        has_slot = True
    if _QUOTED_RE.search(s):
        s = _QUOTED_RE.sub(" <Q> ", s)
        has_slot = True
    if _NUM_RE.search(s):
        s = _NUM_RE.sub(" <NUM> ", s)
        has_slot = True
    if "[EMAIL]" in s or "[PHONE]" in s or "[ID]" in s or "[NUMBER]" in s:
        has_slot = True
    if not has_slot:
        return "", False
    toks = tokenize_fn(s.replace("<ID>", "xid").replace("<Q>", "xq").replace("<NUM>", "xnum"))
    if len(toks) < 4:
        return "", False
    return " ".join(toks), True


def _load_heldout_benchmark_prompts() -> list[str]:
    prompts: list[str] = []
    try:
        from tests.benchmark_fixtures import HELD_OUT_NEGATIVE_PROMPTS  # type: ignore

        for item in HELD_OUT_NEGATIVE_PROMPTS:
            p = str(item.get("prompt") or "").strip()
            if p:
                prompts.append(p)
    except Exception:
        pass
    return prompts


def run_leakage_detection(
    splits: dict[str, list[dict[str, Any]]],
    *,
    canonical_key_fn: Callable[[str], str] | None = None,
    tokenize_fn: Callable[[str], list[str]] | None = None,
    strict_entity_isolation: bool = False,
    heldout_prompts: list[str] | None = None,
    near_dup_threshold: float = 0.72,
    reference_conn: sqlite3.Connection | None = None,
    reference_splits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Comprehensive cross-split, cross-dataset semantic hash, & benchmark leakage check:
    - Exact / canonical normalized text overlap
    - Near-duplicate token Jaccard overlap
    - 64-bit SimHash + structural semantic hashing against existing train/validation splits
    - Template skeleton overlap (for slotted records)
    - Entity overlap audit (flagged when strict_entity_isolation=True)
    - Held-out evaluation / benchmark prompt contamination
    """
    canon_fn = canonical_key_fn or _default_canonical_key
    tok_fn = tokenize_fn or _default_tokenize

    split_names = [sp for sp in ("train", "val", "test", "unseen", "ood") if splits.get(sp)]
    split_counts = {sp: len(splits[sp]) for sp in split_names}

    canon_sets: dict[str, set[str]] = {}
    token_sets: dict[str, list[tuple[int, set[str]]]] = {}
    template_maps: dict[str, set[str]] = {}
    entity_maps: dict[str, set[str]] = {}

    for sp in split_names:
        c_set: set[str] = set()
        t_list: list[tuple[int, set[str]]] = []
        tpl_set: set[str] = set()
        ent_set: set[str] = set()
        for idx, rec in enumerate(splits[sp]):
            txt = str(rec.get("input") or rec.get("text") or "")
            ck = canon_fn(txt)
            if ck:
                c_set.add(ck)
            toks = set(tok_fn(ck or txt))
            if len(toks) >= 4:
                t_list.append((idx, toks))
            skel, has_slot = _template_skeleton(txt, tok_fn)
            if has_slot and skel:
                tpl_set.add(skel)
            for m in _ENTITY_TOKEN_RE.finditer(txt):
                tok_e = m.group(0)
                if len(tok_e) >= 2:
                    ent_set.add(tok_e)
        canon_sets[sp] = c_set
        token_sets[sp] = t_list
        template_maps[sp] = tpl_set
        entity_maps[sp] = ent_set

    exact_overlaps: list[dict[str, Any]] = []
    near_dup_overlaps: list[dict[str, Any]] = []
    template_overlaps: list[dict[str, Any]] = []
    entity_overlaps: list[dict[str, Any]] = []
    eval_contamination: list[dict[str, Any]] = []
    violations: list[str] = []

    for i, sp_a in enumerate(split_names):
        for sp_b in split_names[i + 1 :]:
            shared_exact = sorted(canon_sets[sp_a] & canon_sets[sp_b])
            if shared_exact:
                exact_overlaps.append(
                    {"split_a": sp_a, "split_b": sp_b, "count": len(shared_exact), "samples": shared_exact[:3]}
                )
                violations.append(f"exact_overlap:{sp_a}<->{sp_b}:{len(shared_exact)}")

            near_pairs = 0
            for _, ta in token_sets[sp_a]:
                for _, tb in token_sets[sp_b]:
                    union_sz = len(ta | tb)
                    if union_sz > 0 and (len(ta & tb) / union_sz) >= near_dup_threshold:
                        near_pairs += 1
                        break
            if near_pairs > 0:
                near_dup_overlaps.append({"split_a": sp_a, "split_b": sp_b, "count": near_pairs})
                violations.append(f"near_duplicate_overlap:{sp_a}<->{sp_b}:{near_pairs}")

            shared_tpl = sorted(template_maps[sp_a] & template_maps[sp_b])
            if shared_tpl:
                template_overlaps.append(
                    {"split_a": sp_a, "split_b": sp_b, "count": len(shared_tpl), "samples": shared_tpl[:3]}
                )
                violations.append(f"template_leakage:{sp_a}<->{sp_b}:{len(shared_tpl)}")

            shared_ent = sorted(entity_maps[sp_a] & entity_maps[sp_b])
            if shared_ent:
                entity_overlaps.append(
                    {"split_a": sp_a, "split_b": sp_b, "count": len(shared_ent), "samples": shared_ent[:5]}
                )
                if strict_entity_isolation:
                    violations.append(f"entity_leakage:{sp_a}<->{sp_b}:{len(shared_ent)}")

    # Check held-out evaluation / benchmark contamination
    held_all = list(heldout_prompts or []) + _load_heldout_benchmark_prompts()
    held_canon = {canon_fn(p): p for p in held_all if canon_fn(p)}
    if held_canon:
        for sp in split_names:
            hits = sorted(canon_sets[sp] & set(held_canon.keys()))
            if hits:
                eval_contamination.append({"split": sp, "count": len(hits), "samples": hits[:3]})
                violations.append(f"eval_contamination:{sp}:{len(hits)}")

    # Semantic hashing comparison against existing train/val splits + internal cross-split pairs
    semantic_detector = DatasetLeakageDetector()
    semantic_report = semantic_detector.check_entries(
        splits,
        reference_splits=reference_splits,
        reference_conn=reference_conn,
        check_internal_splits=True,
        raise_on_leakage=False,
    )
    if not semantic_report.passed:
        for sv in semantic_report.violations:
            tag = f"semantic_hash:{sv}"
            if tag not in violations:
                violations.append(tag)

    passed = len(violations) == 0
    return {
        "passed": passed,
        "status": "PASS" if passed else "FAIL",
        "leakage_detected": 0 if passed else 1,
        "split_counts": split_counts,
        "exact_overlaps": exact_overlaps,
        "near_dup_overlaps": near_dup_overlaps,
        "template_overlaps": template_overlaps,
        "entity_overlaps": entity_overlaps,
        "eval_contamination": eval_contamination,
        "semantic_hash_report": semantic_report.to_dict(),
        "strict_entity_isolation": bool(strict_entity_isolation),
        "violations": violations,
    }


def extract_kg_candidates(
    records: list[dict[str, Any]],
    conn: sqlite3.Connection,
    *,
    enable_pattern_extraction: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Deterministically extract Knowledge Graph candidate triples `(subject, relation, object)`
    from structured KG records or factual sentences (zero external LLM).
    Returns `(unique_candidates, contradiction_warnings)`.
    """
    raw_triples: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    for rec in records:
        if rec.get("kind") == "kg_triple" and isinstance(rec.get("triple"), dict):
            tr = rec["triple"]
            s, r, o = tr["subject"].strip(), tr["relation"].strip(), tr["object"].strip()
            k = (s.casefold(), r.casefold(), o.casefold())
            if s and r and o and k not in seen_keys:
                seen_keys.add(k)
                raw_triples.append({"subject": s, "relation": r, "object": o, "extraction": "structured"})
            continue

        txt = str(rec.get("text") or "").strip()
        if not txt or not enable_pattern_extraction:
            continue

        m_arrow = _ARROW_TRIPLE_RE.match(txt)
        if m_arrow:
            s, r, o = m_arrow.group(1).strip(), m_arrow.group(2).strip(), m_arrow.group(3).strip()
            if 1 <= len(s) <= 120 and 1 <= len(r) <= 80 and 1 <= len(o) <= 200:
                k = (s.casefold(), r.casefold(), o.casefold())
                if k not in seen_keys:
                    seen_keys.add(k)
                    raw_triples.append({"subject": s, "relation": r, "object": o, "extraction": "arrow_triple"})
            continue

        m_fact = _EN_FACT_RE.match(txt) or _TH_FACT_RE.match(txt)
        if m_fact:
            s, r, o = m_fact.group(1).strip(), m_fact.group(2).strip(), m_fact.group(3).strip()
            if 1 <= len(s) <= 120 and 1 <= len(r) <= 80 and 1 <= len(o) <= 200:
                k = (s.casefold(), r.casefold(), o.casefold())
                if k not in seen_keys:
                    seen_keys.add(k)
                    raw_triples.append({"subject": s, "relation": r, "object": o, "extraction": "factual_pattern"})

    # Filter already-identical triples in DB and detect contradictions
    filtered: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    batch_sr_objs: dict[tuple[str, str], set[str]] = collections.defaultdict(set)

    for tr in raw_triples:
        s, r, o = tr["subject"], tr["relation"], tr["object"]
        exists = conn.execute(
            "SELECT id FROM knowledge_triples WHERE lower(subject)=lower(?) AND lower(relation)=lower(?) AND lower(object)=lower(?)",
            (s, r, o),
        ).fetchone()
        if exists:
            continue

        db_conflicts = [
            row["object"]
            for row in conn.execute(
                "SELECT object FROM knowledge_triples WHERE lower(subject)=lower(?) AND lower(relation)=lower(?)",
                (s, r),
            ).fetchall()
            if row["object"].casefold() != o.casefold()
        ]
        sr_key = (s.casefold(), r.casefold())
        batch_conflicts = [obj for obj in batch_sr_objs[sr_key] if obj.casefold() != o.casefold()]
        batch_sr_objs[sr_key].add(o)

        all_conflicts = sorted(set(db_conflicts + batch_conflicts))
        if all_conflicts:
            contradictions.append(
                {
                    "subject": s,
                    "relation": r,
                    "proposed_object": o,
                    "existing_objects": all_conflicts,
                }
            )
        tr_item = {
            **tr,
            "has_contradiction": bool(all_conflicts),
            "conflicting_objects": all_conflicts,
        }
        filtered.append(tr_item)

    return filtered, contradictions


def _write_immutable_bundle(
    data_dir: Path,
    *,
    dataset_id: str,
    dataset_name: str,
    splits_records: dict[str, list[dict[str, Any]]],
    manifest_template: dict[str, Any],
) -> tuple[Path, dict[str, Any], str]:
    """Atomically write train/val/test JSONL + manifest.json into an immutable dataset directory."""
    datasets_root = (data_dir / "datasets").resolve()
    datasets_root.mkdir(parents=True, exist_ok=True)
    bundle_name = f"{_safe_slug(dataset_name)}_{dataset_id[:8]}"
    target_dir = (datasets_root / bundle_name).resolve()
    if target_dir == datasets_root or not target_dir.is_relative_to(datasets_root):
        raise ValueError("Resolved dataset bundle path escapes datasets root.")
    if target_dir.exists() or target_dir.is_symlink():
        raise FileExistsError(f"Immutable dataset artifact directory already exists: {bundle_name}")

    staging = Path(tempfile.mkdtemp(prefix=f".ds_{dataset_id[:8]}_", dir=str(datasets_root)))
    try:
        files_meta: dict[str, dict[str, Any]] = {}
        split_hashes: list[str] = []
        for sp in ("train", "val", "test", "unseen", "ood"):
            rows = splits_records.get(sp)
            if not rows:
                continue
            sp_path = staging / f"{sp}.jsonl"
            with sp_path.open("w", encoding="utf-8") as fh:
                for item in rows:
                    fh.write(json.dumps(item, ensure_ascii=False) + "\n")
            sha = _sha256_file(sp_path)
            files_meta[f"{sp}.jsonl"] = {"documents": len(rows), "sha256": sha}
            split_hashes.append(sha)

        content_sha256 = hashlib.sha256("".join(split_hashes).encode("utf-8")).hexdigest()
        manifest = {
            **manifest_template,
            "content_sha256": content_sha256,
            "files": files_meta,
        }
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        manifest_sha256 = _sha256_bytes(manifest_bytes)
        manifest["manifest_sha256"] = manifest_sha256
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        staging.rename(target_dir)
        return target_dir, manifest, manifest_sha256
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def ingest_dataset(
    conn: sqlite3.Connection,
    data_dir: Path,
    payload: dict[str, Any],
    *,
    canonical_key_fn: Callable[[str], str] | None = None,
    tokenize_fn: Callable[[str], list[str]] | None = None,
) -> dict[str, Any]:
    """
    Full real-data Dataset Ingestion Pipeline:
    1. Validate provenance & license (reject synthetic/external LLM sources)
    2. Parse real formats (text / jsonl / json / csv / pre-split JSON) + clean + PII redact
    3. Deduplicate & deterministically split Train/Val/Test (or validate explicit splits)
    4. Run multi-layer Data Leakage detection (exact, near-dup, template, entity, benchmark)
    5. Generate SHA-256 checksums & manifest (`zyrquen.dataset-manifest.v1`) + write immutable bundle
    6. Extract Knowledge Graph candidates and stage into `kg_ingestion_proposals` (`PENDING_APPROVAL`)
       so KG storage NEVER bypasses the Admin Approval Gate!
    """
    init_dataset_pipeline_schema(conn)
    canon_fn = canonical_key_fn or _default_canonical_key
    tok_fn = tokenize_fn or _default_tokenize

    try:
        name, provenance, source_name, license_str = validate_provenance_metadata(
            name=str(payload.get("name") or "untitled-corpus"),
            provenance=payload.get("provenance"),
            source_name=payload.get("source_name"),
            license_str=payload.get("license"),
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    raw_text = str(payload.get("content") or "").strip()
    explicit_splits = payload.get("splits")
    user_id = str(payload.get("user_id") or "")
    requested_format = str(payload.get("format") or "auto")
    do_redact_pii = bool(payload.get("redact_pii", True))
    extract_kg = bool(payload.get("extract_kg", True))
    strict_entity_isolation = bool(payload.get("strict_entity_isolation", False))
    heldout_prompts = payload.get("heldout_prompts") if isinstance(payload.get("heldout_prompts"), list) else None

    if not raw_text and not explicit_splits:
        return {"ok": False, "error": "Dataset content or pre-split payload is required."}

    input_sha256 = _sha256_text(
        raw_text if raw_text else json.dumps(explicit_splits, ensure_ascii=False, sort_keys=True)
    )

    pii_stats: dict[str, int] = {
        "email": 0,
        "thai_id": 0,
        "card_number": 0,
        "phone": 0,
        "total_redacted": 0,
    }
    try:
        resolved_fmt, parsed_records, pre_split_records = parse_real_dataset_payload(
            raw_text=raw_text,
            requested_format=requested_format,
            explicit_splits=explicit_splits if isinstance(explicit_splits, dict) else None,
            default_source=source_name,
            do_redact_pii=do_redact_pii,
            pii_stats=pii_stats,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"Dataset parsing failed: {exc}"}

    deduplicated_removed = 0
    if pre_split_records is not None:
        splits_records = pre_split_records
        unique_records: list[dict[str, Any]] = []
        for sp in ("train", "val", "test", "unseen", "ood"):
            unique_records.extend(splits_records.get(sp, []))
        if len(unique_records) < 5:
            return {
                "ok": False,
                "error": "Dataset requires at least 5 non-empty records across splits.",
            }
    else:
        if len(parsed_records) < 5:
            return {
                "ok": False,
                "error": "Dataset requires at least 5 non-empty lines/records for Train/Val/Test splitting.",
            }
        seen_norms: set[str] = set()
        unique_records = []
        for rec in parsed_records:
            norm = canon_fn(rec["text"]) or re.sub(r"\s+", " ", rec["text"].lower())
            if norm not in seen_norms:
                seen_norms.add(norm)
                unique_records.append(rec)
            else:
                deduplicated_removed += 1

        if len(unique_records) < 3:
            return {
                "ok": False,
                "error": "Dataset has fewer than 3 unique lines after near-duplicate removal.",
            }

        rng = random.Random(42)
        shuffled = list(unique_records)
        rng.shuffle(shuffled)
        n = len(shuffled)
        train_end = max(1, int(n * 0.7))
        val_end = max(train_end + 1, int(n * 0.85))
        if val_end >= n:
            val_end = n - 1
        splits_records = {
            "train": shuffled[:train_end],
            "val": shuffled[train_end:val_end],
            "test": shuffled[val_end:],
        }

    leakage_report = run_leakage_detection(
        splits_records,
        canonical_key_fn=canon_fn,
        tokenize_fn=tok_fn,
        strict_entity_isolation=strict_entity_isolation,
        heldout_prompts=[str(x) for x in heldout_prompts] if heldout_prompts else None,
        reference_conn=conn,
    )
    leakage = int(leakage_report["leakage_detected"])

    train_lines = [r["text"] for r in splits_records.get("train", [])]
    val_lines = [r["text"] for r in splits_records.get("val", [])]
    test_lines = [r["text"] for r in splits_records.get("test", [])]

    dataset_id = str(uuid.uuid4())
    ingested_at = _now_iso()
    manifest_template = {
        "schema": SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "name": name,
        "source_name": source_name,
        "license": license_str,
        "provenance": provenance,
        "source_format": resolved_fmt,
        "pii_redacted": do_redact_pii,
        "pii_redaction_summary": pii_stats,
        "input_sha256": input_sha256,
        "total_records": len(unique_records),
        "deduplicated_removed": deduplicated_removed,
        "leakage_detected": leakage,
        "leakage_report": leakage_report,
        "ingested_by": user_id,
        "ingested_at": ingested_at,
    }

    try:
        artifact_dir, manifest_obj, manifest_sha256 = _write_immutable_bundle(
            data_dir,
            dataset_id=dataset_id,
            dataset_name=name,
            splits_records=splits_records,
            manifest_template=manifest_template,
        )
    except (OSError, ValueError, FileExistsError) as exc:
        return {"ok": False, "error": f"Failed to persist immutable dataset manifest: {exc}"}

    # Preserve 64-char SHA-256 manifest hash (content_sha256) used by training gate
    manifest_hash = str(manifest_obj["content_sha256"])

    records_obj = {
        "train": train_lines,
        "val": val_lines,
        "test": test_lines,
        "unseen": [r["text"] for r in splits_records.get("unseen", [])],
        "ood": [r["text"] for r in splits_records.get("ood", [])],
        "provenance": provenance,
        "source_name": source_name,
        "license": license_str,
        "source_format": resolved_fmt,
        "input_sha256": input_sha256,
        "manifest_sha256": manifest_sha256,
        "provenance_verified": True,
        "leakage_checked_at": ingested_at,
        "leakage_report": leakage_report,
    }

    with conn:
        conn.execute(
            """
            INSERT INTO datasets (
                id, name, manifest_hash, total_records, train_count, val_count, test_count,
                leakage_detected, status, created_by, created_at, records_json,
                source_name, license, provenance, source_format, content_sha256, manifest_json, artifact_dir
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dataset_id,
                name,
                manifest_hash,
                len(unique_records),
                len(train_lines),
                len(val_lines),
                len(test_lines),
                leakage,
                "LEAKAGE_BLOCKED" if leakage else "READY",
                user_id,
                ingested_at,
                json.dumps(records_obj, ensure_ascii=False),
                source_name,
                license_str,
                provenance,
                resolved_fmt,
                manifest_hash,
                json.dumps(manifest_obj, ensure_ascii=False),
                str(artifact_dir),
            ),
        )

    # Extract & Stage Knowledge Graph Proposals behind Approval Gate (NEVER auto-commit!)
    kg_proposal: dict[str, Any] | None = None
    if extract_kg:
        candidates, contradictions = extract_kg_candidates(unique_records, conn, enable_pattern_extraction=True)
        if candidates:
            proposal_id = str(uuid.uuid4())
            proposal_status = "BLOCKED" if leakage else "PENDING_APPROVAL"
            decision_reason = (
                "Blocked automatically: source dataset failed Data Leakage check."
                if leakage
                else None
            )
            proposal_checksum = _sha256_text(
                json.dumps(
                    {
                        "dataset_id": dataset_id,
                        "manifest_hash": manifest_hash,
                        "provenance": provenance,
                        "triples": candidates,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            with conn:
                conn.execute(
                    """
                    INSERT INTO kg_ingestion_proposals (
                        id, dataset_id, dataset_name, provenance, source_name, license,
                        manifest_hash, proposal_checksum, triples_json, contradictions_json,
                        triple_count, status, submitted_by, approved_by, decision_reason,
                        created_at, reviewed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL)
                    """,
                    (
                        proposal_id,
                        dataset_id,
                        name,
                        provenance,
                        source_name,
                        license_str,
                        manifest_hash,
                        proposal_checksum,
                        json.dumps(candidates, ensure_ascii=False),
                        json.dumps(contradictions, ensure_ascii=False),
                        len(candidates),
                        proposal_status,
                        user_id,
                        decision_reason,
                        ingested_at,
                    ),
                )
            kg_proposal = dict(
                conn.execute(
                    "SELECT id, dataset_id, dataset_name, provenance, source_name, license, manifest_hash, proposal_checksum, triple_count, status, contradictions_json, triples_json, created_at FROM kg_ingestion_proposals WHERE id=?",
                    (proposal_id,),
                ).fetchone()
            )

    row = dict(
        conn.execute(
            """
            SELECT id, name, manifest_hash, total_records, train_count, val_count, test_count,
                   leakage_detected, status, created_by, created_at,
                   source_name, license, provenance, source_format, content_sha256, artifact_dir
            FROM datasets WHERE id=?
            """,
            (dataset_id,),
        ).fetchone()
    )
    return {
        "ok": True,
        "dataset": row,
        "manifest": manifest_obj,
        "checksum": {
            "input_sha256": input_sha256,
            "content_sha256": manifest_hash,
            "manifest_sha256": manifest_sha256,
            "files": manifest_obj["files"],
        },
        "leakage_report": leakage_report,
        "kg_proposal": kg_proposal,
        "deduplicated_removed": deduplicated_removed,
        "pii_redaction_summary": pii_stats,
    }


def verify_dataset_integrity(conn: sqlite3.Connection, dataset_id: str) -> dict[str, Any]:
    """Recompute and verify DB records, split files, manifest.json, and SHA-256 checksums."""
    init_dataset_pipeline_schema(conn)
    ds = conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
    if not ds:
        return {"ok": False, "verified": False, "error": "Dataset not found"}

    ds_dict = dict(ds)
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    manifest_hash = str(ds_dict.get("manifest_hash") or "")
    provenance = str(ds_dict.get("provenance") or "")
    if len(manifest_hash) != 64:
        errors.append("Invalid or missing 64-char SHA-256 manifest_hash")
    if not provenance or any(tok in provenance.lower() for tok in DISALLOWED_PROVENANCE_TOKENS):
        errors.append(f"Invalid provenance '{provenance}'")

    artifact_dir_raw = ds_dict.get("artifact_dir")
    disk_verified = False
    if artifact_dir_raw:
        art_dir = Path(str(artifact_dir_raw))
        manifest_path = art_dir / "manifest.json"
        if not art_dir.is_dir() or not manifest_path.is_file():
            errors.append("On-disk dataset bundle or manifest.json is missing")
        else:
            try:
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
                split_hashes: list[str] = []
                files_map = manifest_data.get("files") if isinstance(manifest_data.get("files"), dict) else {}
                ordered_fnames = [
                    f"{sp}.jsonl" for sp in ("train", "val", "test", "unseen", "ood") if f"{sp}.jsonl" in files_map
                ]
                for fname in files_map:
                    if fname not in ordered_fnames:
                        ordered_fnames.append(fname)
                for fname in ordered_fnames:
                    fmeta = files_map.get(fname)
                    fpath = (art_dir / fname).resolve()
                    if not fpath.is_relative_to(art_dir.resolve()) or not fpath.is_file():
                        errors.append(f"Missing split artifact {fname}")
                        continue
                    actual_sha = _sha256_file(fpath)
                    expected_sha = str((fmeta or {}).get("sha256") or "")
                    if actual_sha != expected_sha:
                        errors.append(f"Checksum mismatch for {fname}")
                    split_hashes.append(actual_sha)
                recomputed_content_sha = hashlib.sha256("".join(split_hashes).encode("utf-8")).hexdigest()
                if recomputed_content_sha != manifest_hash:
                    errors.append("Recomputed content_sha256 does not match DB manifest_hash")
                else:
                    disk_verified = True
                manifest_sha256_val = str(manifest_data.get("manifest_sha256") or "")
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                manifest_sha256_val = ""
                errors.append(f"Failed to verify disk manifest: {exc}")
    else:
        manifest_sha256_val = ""
        # Legacy DB-only dataset fallback verification
        try:
            rec_obj = json.loads(ds_dict.get("records_json") or "{}")
            all_lines = (
                (rec_obj.get("train") or [])
                + (rec_obj.get("val") or [])
                + (rec_obj.get("test") or [])
            )
            checks.append({"check": "legacy_records_present", "passed": len(all_lines) > 0})
            if not all_lines:
                errors.append("Dataset records_json is empty")
        except Exception as exc:
            errors.append(f"Corrupted records_json: {exc}")

    if int(ds_dict.get("leakage_detected") or 0) != 0:
        errors.append("Dataset has leakage_detected=1")

    verified = len(errors) == 0
    return {
        "ok": True,
        "verified": verified,
        "status": "VERIFIED" if verified else "FAILED",
        "dataset_id": ds_dict["id"],
        "name": ds_dict["name"],
        "provenance": provenance,
        "source_name": ds_dict.get("source_name"),
        "license": ds_dict.get("license"),
        "source_format": ds_dict.get("source_format"),
        "manifest_hash": manifest_hash,
        "content_sha256": manifest_hash,
        "manifest_sha256": manifest_sha256_val,
        "disk_verified": disk_verified,
        "disk_bundle_verified": disk_verified,
        "leakage_detected": int(ds_dict.get("leakage_detected") or 0),
        "errors": errors,
        "checks": checks,
    }


def verify_all_datasets_for_workflow(conn: sqlite3.Connection) -> dict[str, Any]:
    """Run real checksum, provenance, and leakage verification across all registered datasets."""
    init_dataset_pipeline_schema(conn)
    ds_rows = conn.execute("SELECT id, name, leakage_detected FROM datasets ORDER BY created_at DESC").fetchall()
    results = [verify_dataset_integrity(conn, str(r["id"])) for r in ds_rows]
    leak_count = sum(1 for r in ds_rows if int(r["leakage_detected"] or 0) != 0)
    hash_failures = [res for res in results if not res.get("verified")]
    return {
        "total": len(ds_rows),
        "leak_count": leak_count,
        "checksum_failed_count": len(hash_failures),
        "all_verified": len(hash_failures) == 0 and leak_count == 0,
        "results": results,
    }


def decide_kg_proposal(
    conn: sqlite3.Connection,
    *,
    proposal_id: str,
    decision: str,
    admin_email: str,
    admin_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """
    Admin Approval Gate for storing Dataset-extracted Knowledge Graph triples into `knowledge_triples`.
    - Rejecting stores 0 triples and records decision.
    - Approving re-verifies dataset integrity, zero leakage, and proposal_checksum (fail-closed)
      before committing triples into `knowledge_triples` with full dataset provenance.
    - Never bypasses `native_training` Approval Gate.
    """
    init_dataset_pipeline_schema(conn)
    prop = conn.execute("SELECT * FROM kg_ingestion_proposals WHERE id=?", (proposal_id,)).fetchone()
    if not prop:
        return {"ok": False, "error": "Knowledge Graph proposal not found"}
    if prop["status"] != "PENDING_APPROVAL":
        return {"ok": False, "error": f"Proposal is not awaiting approval (status={prop['status']})"}

    now_ts = _now_iso()
    if decision == "reject":
        with conn:
            conn.execute(
                """
                UPDATE kg_ingestion_proposals
                SET status='REJECTED', approved_by=?, decision_reason=?, reviewed_at=?
                WHERE id=?
                """,
                (admin_email, reason or f"Rejected at KG Approval Gate by {admin_email}", now_ts, proposal_id),
            )
        updated = dict(conn.execute("SELECT * FROM kg_ingestion_proposals WHERE id=?", (proposal_id,)).fetchone())
        return {"ok": True, "proposal": updated, "committed_triples": 0}

    # Re-verify parent dataset checksum, provenance, and zero leakage before committing KG
    ds_verify = verify_dataset_integrity(conn, str(prop["dataset_id"]))
    if not ds_verify.get("verified"):
        with conn:
            conn.execute(
                """
                UPDATE kg_ingestion_proposals
                SET status='BLOCKED', approved_by=?, decision_reason=?, reviewed_at=?
                WHERE id=?
                """,
                (
                    admin_email,
                    f"Blocked at KG Approval Gate: {'; '.join(ds_verify.get('errors') or ['integrity check failed'])}",
                    now_ts,
                    proposal_id,
                ),
            )
        return {
            "ok": False,
            "error": f"KG Approval Gate blocked commit: dataset integrity/leakage failed ({'; '.join(ds_verify.get('errors') or [])})",
        }

    triples = json.loads(prop["triples_json"] or "[]")
    expected_checksum = _sha256_text(
        json.dumps(
            {
                "dataset_id": prop["dataset_id"],
                "manifest_hash": prop["manifest_hash"],
                "provenance": prop["provenance"],
                "triples": triples,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if expected_checksum != prop["proposal_checksum"]:
        return {"ok": False, "error": "Proposal checksum verification failed; refusing KG commit."}

    source_tag = f"dataset:{prop['dataset_name']}|{prop['provenance']}|sha256:{str(prop['manifest_hash'])[:12]}"
    committed = 0
    skipped_duplicates = 0
    committed_ids: list[str] = []

    with conn:
        for tr in triples:
            s = str(tr.get("subject") or "").strip()[:120]
            r = str(tr.get("relation") or "").strip()[:80]
            o = str(tr.get("object") or "").strip()[:200]
            if not s or not r or not o:
                continue
            dup = conn.execute(
                "SELECT id FROM knowledge_triples WHERE lower(subject)=lower(?) AND lower(relation)=lower(?) AND lower(object)=lower(?)",
                (s, r, o),
            ).fetchone()
            if dup:
                skipped_duplicates += 1
                continue
            has_contra = bool(tr.get("has_contradiction"))
            conf = 0.7 if has_contra else 0.95
            tid = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO knowledge_triples (id, subject, relation, object, source, confidence, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (tid, s, r, o, source_tag, conf, admin_id or admin_email, now_ts),
            )
            committed += 1
            committed_ids.append(tid)

        conn.execute(
            """
            UPDATE kg_ingestion_proposals
            SET status='APPROVED', approved_by=?, decision_reason=?, reviewed_at=?
            WHERE id=?
            """,
            (
                admin_email,
                reason or f"Approved by {admin_email} ({committed} committed, {skipped_duplicates} skipped duplicates)",
                now_ts,
                proposal_id,
            ),
        )

    updated = dict(conn.execute("SELECT * FROM kg_ingestion_proposals WHERE id=?", (proposal_id,)).fetchone())
    return {
        "ok": True,
        "proposal": updated,
        "committed_triples": committed,
        "skipped_duplicates": skipped_duplicates,
        "committed_triple_ids": committed_ids,
    }
