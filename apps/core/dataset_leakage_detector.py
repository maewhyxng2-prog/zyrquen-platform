"""
ZYRQUEN Ω∞ — Semantic Hashing Dataset Leakage Detector (Pure Python 3.11 Stdlib)
--------------------------------------------------------------------------------
Automatically compares incoming dataset entries against existing `train` and
`val` / `validation` splits (and across internal candidate splits) using
multi-signal deterministic semantic hashing:

1. Exact Canonical Digest (SHA-256 over Unicode-NFC, casefolded, normalized text)
2. 64-bit Locality-Sensitive SimHash over weighted semantic word/subword/Thai
   shingles, indexed via 4 x 16-bit LSH bands + verified with weighted shingle
   similarity to eliminate short-text false positives
3. Slot-Masked Structural Semantic Hash (normalizing numeric/ID/email/URL slots
   when sufficient informative non-slot tokens exist)

Zero external pretrained models, embeddings, or third-party dependencies.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_REFERENCE_SPLITS: tuple[str, ...] = ("train", "val", "validation")
DEFAULT_EVAL_SPLITS: tuple[str, ...] = ("val", "validation", "test", "unseen", "ood")

_ZERO_WIDTH_TRANS = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)
_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-z0-9_]+|[\u0E00-\u0E7F]+")
_THAI_RUN_RE = re.compile(r"[\u0E00-\u0E7F]{2,}")
_LATIN_WORD_RE = re.compile(r"[a-z0-9_]+")

_EMAIL_SLOT_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_URL_SLOT_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_UUID_SLOT_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_HEX_SLOT_RE = re.compile(r"\b[0-9a-f]{12,64}\b", re.IGNORECASE)
_ID_SLOT_RE = re.compile(r"\b[A-Za-z]{1,6}[-_]\d{2,}\b|\b[A-Za-z]+_[A-Za-z0-9_]*\d+\b")
_NUM_SLOT_RE = re.compile(r"(?<!\w)\d+(?:[.,:/-]\d+)*(?!\w)")
_QUOTED_SLOT_RE = re.compile(r"[\"'][^\"']{1,48}[\"']")

_EN_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "been", "by", "for", "from",
        "has", "have", "he", "her", "hers", "his", "if", "in", "into", "is", "it",
        "its", "of", "on", "or", "our", "out", "over", "per", "she", "that", "the",
        "their", "them", "then", "there", "these", "they", "this", "those", "to",
        "under", "using", "was", "we", "were", "when", "where", "which", "while",
        "who", "will", "with", "within", "without",
    }
)


class SemanticHashLeakageError(ValueError):
    """Raised when incoming dataset entries semantically collide with protected splits."""


def normalize_text(text: str) -> str:
    """Normalize Unicode NFC, strip zero-width chars, collapse whitespace, casefold."""
    cleaned = unicodedata.normalize("NFC", str(text or "")).translate(_ZERO_WIDTH_TRANS)
    return _WS_RE.sub(" ", cleaned).strip().casefold()


def extract_record_text(record: str | Mapping[str, Any]) -> str:
    """Extract comparable natural-language text from plain string or structured dataset record."""
    if isinstance(record, str):
        return record
    if isinstance(record, Mapping):
        if "input" in record or "target" in record:
            inp = str(record.get("input") or "").strip()
            tgt = str(record.get("target") or "").strip()
            return f"{inp} {tgt}".strip()
        if "prompt" in record or "completion" in record or "response" in record:
            p = str(record.get("prompt") or "").strip()
            r = str(record.get("completion") or record.get("response") or "").strip()
            return f"{p} {r}".strip()
        if all(k in record for k in ("subject", "relation", "object")):
            return (
                f"{str(record.get('subject') or '').strip()} "
                f"{str(record.get('relation') or '').strip()} "
                f"{str(record.get('object') or '').strip()}"
            ).strip()
        for key in ("text", "content", "document", "body"):
            val = record.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return json.dumps(dict(record), ensure_ascii=False, sort_keys=True)
    return str(record or "")


def _extract_semantic_features(norm_text: str) -> tuple[Counter[str], int]:
    """
    Build weighted semantic features from normalized text:
    - Content English/Latin unigrams (stopwords down-weighted) + bigrams
    - Thai character 3-gram and 4-gram shingles (word-boundary free)
    Returns `(feature_weights, informative_token_count)`.
    """
    weights: Counter[str] = Counter()
    informative_tokens = 0

    latin_tokens: list[str] = []
    for tok in _LATIN_WORD_RE.findall(norm_text):
        latin_tokens.append(tok)
        if tok in _EN_STOPWORDS or len(tok) <= 1:
            weights[f"sw:{tok}"] += 1
        else:
            informative_tokens += 1
            weights[f"w:{tok}"] += 3

    content_latin = [t for t in latin_tokens if t not in _EN_STOPWORDS and len(t) > 1]
    for idx in range(len(content_latin) - 1):
        weights[f"bg:{content_latin[idx]}_{content_latin[idx + 1]}"] += 2

    for thai_run in _THAI_RUN_RE.findall(norm_text):
        if len(thai_run) < 3:
            informative_tokens += 1
            weights[f"th2:{thai_run}"] += 3
            continue
        informative_tokens += max(1, len(thai_run) // 3)
        for i in range(len(thai_run) - 2):
            weights[f"th3:{thai_run[i : i + 3]}"] += 2
        for i in range(len(thai_run) - 3):
            weights[f"th4:{thai_run[i : i + 4]}"] += 3

    return weights, informative_tokens


def compute_simhash64(feature_weights: Mapping[str, int]) -> int:
    """Compute a deterministic 64-bit SimHash over weighted semantic features."""
    if not feature_weights:
        return 0
    accum = [0.0] * 64
    for feat, weight in feature_weights.items():
        if weight <= 0:
            continue
        digest = hashlib.sha256(feat.encode("utf-8")).digest()
        val = int.from_bytes(digest[:8], "big", signed=False)
        w = float(weight)
        for bit in range(64):
            if (val >> bit) & 1:
                accum[bit] += w
            else:
                accum[bit] -= w
    fingerprint = 0
    for bit, score in enumerate(accum):
        if score >= 0.0:
            fingerprint |= 1 << bit
    return fingerprint


def hamming_distance_64(a: int, b: int) -> int:
    """Return Hamming distance between two 64-bit unsigned integer hashes."""
    return (int(a) ^ int(b)).bit_count()


def _simhash_bands(simhash_val: int) -> tuple[tuple[int, int], ...]:
    """Split a 64-bit SimHash into 8 x 8-bit bands for LSH candidate lookup."""
    return tuple((band, (simhash_val >> (band * 8)) & 0xFF) for band in range(8))


def _compute_structural_hash(norm_text: str) -> str | None:
    """
    Compute a slot-masked order-insensitive semantic token hash when the record
    contains at least 4 informative non-slot tokens (prevents short-ID collisions).
    """
    masked = _URL_SLOT_RE.sub(" <url> ", norm_text)
    masked = _EMAIL_SLOT_RE.sub(" <email> ", masked)
    masked = _UUID_SLOT_RE.sub(" <id> ", masked)
    masked = _HEX_SLOT_RE.sub(" <id> ", masked)
    masked = _ID_SLOT_RE.sub(" <id> ", masked)
    masked = _QUOTED_SLOT_RE.sub(" <str> ", masked)
    masked = _NUM_SLOT_RE.sub(" <num> ", masked)

    slot_tokens = set()
    informative = set()
    for raw_tok in re.findall(r"<[a-z]+>|[a-z0-9_]+|[\u0E00-\u0E7F]{2,}", masked):
        if raw_tok.startswith("<") and raw_tok.endswith(">"):
            slot_tokens.add(raw_tok)
        elif raw_tok not in _EN_STOPWORDS and len(raw_tok) >= 2:
            if 0x0E00 <= ord(raw_tok[0]) <= 0x0E7F and len(raw_tok) >= 4:
                for i in range(len(raw_tok) - 2):
                    informative.add(raw_tok[i : i + 3])
            else:
                informative.add(raw_tok)

    if not slot_tokens or len(informative) < 4:
        return None
    canonical_struct = " ".join(sorted(informative)) + " || " + " ".join(sorted(slot_tokens))
    return hashlib.sha256(canonical_struct.encode("utf-8")).hexdigest()[:24]


def weighted_jaccard_similarity(a: Mapping[str, int], b: Mapping[str, int]) -> float:
    """Compute weighted Jaccard similarity across non-stopword semantic features."""
    core_a = {k: v for k, v in a.items() if not k.startswith("sw:")}
    core_b = {k: v for k, v in b.items() if not k.startswith("sw:")}
    if not core_a or not core_b:
        return 0.0
    keys = set(core_a) | set(core_b)
    inter = 0.0
    union = 0.0
    for k in keys:
        va = float(core_a.get(k, 0))
        vb = float(core_b.get(k, 0))
        inter += min(va, vb)
        union += max(va, vb)
    return inter / union if union > 0.0 else 0.0


def cosine_feature_similarity(a: Mapping[str, int], b: Mapping[str, int]) -> float:
    """Compute cosine similarity over non-stopword weighted semantic features."""
    core_a = {k: v for k, v in a.items() if not k.startswith("sw:")}
    core_b = {k: v for k, v in b.items() if not k.startswith("sw:")}
    if not core_a or not core_b:
        return 0.0
    dot = sum(float(va) * float(core_b[k]) for k, va in core_a.items() if k in core_b)
    if dot <= 0.0:
        return 0.0
    norm_a = math.sqrt(sum(float(v) * float(v) for v in core_a.values()))
    norm_b = math.sqrt(sum(float(v) * float(v) for v in core_b.values()))
    denom = norm_a * norm_b
    return dot / denom if denom > 0.0 else 0.0


@dataclass(frozen=True)
class SemanticFingerprint:
    record_index: int
    split: str
    dataset_name: str
    exact_sha256: str
    simhash_64: int
    structural_hash: str | None
    informative_tokens: int
    preview: str
    features: Mapping[str, int] = field(repr=False)

    @property
    def simhash_hex(self) -> str:
        return f"{self.simhash_64:016x}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_index": self.record_index,
            "split": self.split,
            "dataset_name": self.dataset_name,
            "exact_sha256": self.exact_sha256,
            "simhash_64": self.simhash_hex,
            "structural_hash": self.structural_hash,
            "informative_tokens": self.informative_tokens,
            "preview": self.preview,
        }


@dataclass(frozen=True)
class LeakageMatch:
    match_type: str
    new_split: str
    new_index: int
    existing_split: str
    existing_dataset: str
    existing_index: int
    hamming_distance: int
    semantic_similarity: float
    simhash_new: str
    simhash_existing: str
    new_preview: str
    existing_preview: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_type": self.match_type,
            "new_split": self.new_split,
            "new_index": self.new_index,
            "existing_split": self.existing_split,
            "existing_dataset": self.existing_dataset,
            "existing_index": self.existing_index,
            "hamming_distance": self.hamming_distance,
            "semantic_similarity": round(self.semantic_similarity, 4),
            "simhash_new": self.simhash_new,
            "simhash_existing": self.simhash_existing,
            "new_preview": self.new_preview,
            "existing_preview": self.existing_preview,
        }


@dataclass(frozen=True)
class SemanticLeakageReport:
    passed: bool
    status: str
    new_records_scanned: int
    reference_records_scanned: int
    reference_splits_scanned: list[str]
    exact_matches: int
    near_duplicate_matches: int
    structural_matches: int
    matches: list[LeakageMatch] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "status": self.status,
            "new_records_scanned": self.new_records_scanned,
            "reference_records_scanned": self.reference_records_scanned,
            "reference_splits_scanned": list(self.reference_splits_scanned),
            "exact_matches": self.exact_matches,
            "near_duplicate_matches": self.near_duplicate_matches,
            "structural_matches": self.structural_matches,
            "matches": [m.to_dict() for m in self.matches[:50]],
            "violations": list(self.violations),
        }


class _SemanticIndex:
    """Fast LSH + Exact + Structural index over a collection of SemanticFingerprints."""

    def __init__(self) -> None:
        self.items: list[SemanticFingerprint] = []
        self.by_exact: dict[str, SemanticFingerprint] = {}
        self.by_struct: dict[str, SemanticFingerprint] = {}
        self.by_band: dict[tuple[int, int], list[SemanticFingerprint]] = {}

    def add(self, fp: SemanticFingerprint) -> None:
        self.items.append(fp)
        if fp.exact_sha256 and fp.exact_sha256 not in self.by_exact:
            self.by_exact[fp.exact_sha256] = fp
        if fp.structural_hash and fp.structural_hash not in self.by_struct:
            self.by_struct[fp.structural_hash] = fp
        if fp.simhash_64:
            for band_key in _simhash_bands(fp.simhash_64):
                self.by_band.setdefault(band_key, []).append(fp)

    def match(
        self,
        candidate: SemanticFingerprint,
        *,
        max_hamming: int,
        min_similarity: float,
        min_informative_tokens: int,
    ) -> LeakageMatch | None:
        if not candidate.exact_sha256:
            return None

        # 1. Exact canonical semantic hash collision
        exact_hit = self.by_exact.get(candidate.exact_sha256)
        if exact_hit is not None:
            return LeakageMatch(
                match_type="exact_semantic_hash",
                new_split=candidate.split,
                new_index=candidate.record_index,
                existing_split=exact_hit.split,
                existing_dataset=exact_hit.dataset_name,
                existing_index=exact_hit.record_index,
                hamming_distance=0,
                semantic_similarity=1.0,
                simhash_new=candidate.simhash_hex,
                simhash_existing=exact_hit.simhash_hex,
                new_preview=candidate.preview,
                existing_preview=exact_hit.preview,
            )

        # 2. 64-bit SimHash near-duplicate via 4-band LSH + full scan fallback when index is small
        if candidate.informative_tokens >= min_informative_tokens:
            seen_ids: set[int] = set()
            pool: list[SemanticFingerprint] = []
            for band_key in _simhash_bands(candidate.simhash_64):
                for fp in self.by_band.get(band_key, ()):
                    fid = id(fp)
                    if fid not in seen_ids:
                        seen_ids.add(fid)
                        pool.append(fp)
            if len(self.items) <= 2000:
                for fp in self.items:
                    fid = id(fp)
                    if fid not in seen_ids:
                        seen_ids.add(fid)
                        pool.append(fp)

            best_hit: SemanticFingerprint | None = None
            best_sim = -1.0
            best_ham = 65
            for ref in pool:
                if ref.informative_tokens < min_informative_tokens:
                    continue
                ham = hamming_distance_64(candidate.simhash_64, ref.simhash_64)
                if ham > max_hamming:
                    continue
                sim = weighted_jaccard_similarity(candidate.features, ref.features)
                if sim >= min_similarity and (sim > best_sim or (sim == best_sim and ham < best_ham)):
                    best_hit = ref
                    best_sim = sim
                    best_ham = ham

            if best_hit is not None:
                return LeakageMatch(
                    match_type="simhash_near_duplicate",
                    new_split=candidate.split,
                    new_index=candidate.record_index,
                    existing_split=best_hit.split,
                    existing_dataset=best_hit.dataset_name,
                    existing_index=best_hit.record_index,
                    hamming_distance=best_ham,
                    semantic_similarity=best_sim,
                    simhash_new=candidate.simhash_hex,
                    simhash_existing=best_hit.simhash_hex,
                    new_preview=candidate.preview,
                    existing_preview=best_hit.preview,
                )

        # 3. Slot-masked structural semantic hash collision
        if candidate.structural_hash:
            struct_hit = self.by_struct.get(candidate.structural_hash)
            if struct_hit is not None:
                sim = weighted_jaccard_similarity(candidate.features, struct_hit.features)
                ham = hamming_distance_64(candidate.simhash_64, struct_hit.simhash_64)
                return LeakageMatch(
                    match_type="structural_semantic_hash",
                    new_split=candidate.split,
                    new_index=candidate.record_index,
                    existing_split=struct_hit.split,
                    existing_dataset=struct_hit.dataset_name,
                    existing_index=struct_hit.record_index,
                    hamming_distance=ham,
                    semantic_similarity=sim,
                    simhash_new=candidate.simhash_hex,
                    simhash_existing=struct_hit.simhash_hex,
                    new_preview=candidate.preview,
                    existing_preview=struct_hit.preview,
                )

        return None


class DatasetLeakageDetector:
    """
    Compares incoming dataset entries against current training & validation splits
    using deterministic multi-signal semantic hashing before persistence.
    """

    def __init__(
        self,
        *,
        simhash_max_hamming: int = 16,
        min_semantic_similarity: float = 0.68,
        min_informative_tokens: int = 4,
        reference_splits: tuple[str, ...] = DEFAULT_REFERENCE_SPLITS,
    ) -> None:
        if not (0 <= simhash_max_hamming <= 32):
            raise ValueError("simhash_max_hamming must be between 0 and 32.")
        if not (0.0 <= min_semantic_similarity <= 1.0):
            raise ValueError("min_semantic_similarity must be between 0.0 and 1.0.")
        self.simhash_max_hamming = int(simhash_max_hamming)
        self.min_semantic_similarity = float(min_semantic_similarity)
        self.min_informative_tokens = max(1, int(min_informative_tokens))
        self.reference_splits = tuple(str(sp).strip().lower() for sp in reference_splits if str(sp).strip())

    def compute_fingerprint(
        self,
        record: str | Mapping[str, Any],
        *,
        record_index: int = 0,
        split: str = "incoming",
        dataset_name: str = "incoming",
    ) -> SemanticFingerprint:
        raw_text = extract_record_text(record)
        norm = normalize_text(raw_text)
        exact_sha = hashlib.sha256(norm.encode("utf-8")).hexdigest() if norm else ""
        feats, informative = _extract_semantic_features(norm)
        simhash_val = compute_simhash64(feats) if norm else 0
        struct_hash = _compute_structural_hash(norm) if norm else None
        return SemanticFingerprint(
            record_index=record_index,
            split=split,
            dataset_name=dataset_name,
            exact_sha256=exact_sha,
            simhash_64=simhash_val,
            structural_hash=struct_hash,
            informative_tokens=informative,
            preview=raw_text[:120],
            features=feats,
        )

    def load_reference_splits_from_dirs(
        self,
        dataset_dirs: Iterable[str | Path],
        *,
        allowed_root: str | Path | None = None,
        splits: tuple[str, ...] | None = None,
    ) -> dict[str, dict[str, list[Any]]]:
        """
        Load existing `train` / `val` / `validation` JSONL records from dataset directories.
        Returns `{dataset_name: {split_name: [record, ...]}}`.
        """
        target_splits = tuple(splits or self.reference_splits)
        resolved_root = Path(allowed_root).resolve() if allowed_root is not None else None
        out: dict[str, dict[str, list[Any]]] = {}

        for raw_dir in dataset_dirs:
            dpath = Path(raw_dir)
            if dpath.is_symlink() or not dpath.is_dir():
                continue
            resolved_dir = dpath.resolve()
            if resolved_root is not None:
                if resolved_dir != resolved_root and not resolved_dir.is_relative_to(resolved_root):
                    continue
            ds_name = resolved_dir.name
            ds_splits: dict[str, list[Any]] = {}
            for sp in target_splits:
                sp_file = (resolved_dir / f"{sp}.jsonl").resolve()
                if sp_file.is_symlink() or not sp_file.is_file() or not sp_file.is_relative_to(resolved_dir):
                    continue
                rows: list[Any] = []
                for line in sp_file.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        rows.append(line.strip())
                if rows:
                    ds_splits[sp] = rows
            if ds_splits:
                out[ds_name] = ds_splits
        return out

    def load_reference_splits_from_sqlite(
        self,
        conn: sqlite3.Connection,
        *,
        exclude_dataset_id: str | None = None,
        splits: tuple[str, ...] | None = None,
    ) -> dict[str, dict[str, list[Any]]]:
        """Load active `train` / `val` / `validation` splits from SQLite `datasets` table."""
        target_splits = tuple(splits or self.reference_splits)
        out: dict[str, dict[str, list[Any]]] = {}
        try:
            rows = conn.execute(
                "SELECT id, name, records_json FROM datasets ORDER BY created_at DESC"
            ).fetchall()
        except sqlite3.Error:
            return out

        for row in rows:
            ds_id = str(row["id"] if isinstance(row, sqlite3.Row) else row[0])
            if exclude_dataset_id and ds_id == exclude_dataset_id:
                continue
            ds_name = str(row["name"] if isinstance(row, sqlite3.Row) else row[1]) or ds_id
            raw_json = row["records_json"] if isinstance(row, sqlite3.Row) else row[2]
            try:
                parsed = json.loads(raw_json or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(parsed, dict):
                continue
            ds_splits: dict[str, list[Any]] = {}
            for sp in target_splits:
                recs = parsed.get(sp)
                if isinstance(recs, list) and recs:
                    ds_splits[sp] = recs
            if ds_splits:
                out[f"{ds_name} ({ds_id[:8]})"] = ds_splits
        return out

    def _build_index_from_references(
        self,
        reference_splits: Mapping[str, Any],
    ) -> tuple[_SemanticIndex, list[str]]:
        """
        Accept either:
          - `{split_name: [records...]}` (single current corpus)
          - `{dataset_name: {split_name: [records...]}}` (multi-version corpora)
        """
        index = _SemanticIndex()
        scanned_splits: set[str] = set()

        def _index_split(ds_label: str, sp_name: str, recs: Iterable[Any]) -> None:
            sp_l = sp_name.strip().lower()
            if sp_l not in self.reference_splits:
                return
            scanned_splits.add(sp_l)
            for idx, rec in enumerate(recs):
                fp = self.compute_fingerprint(
                    rec,
                    record_index=idx,
                    split=sp_l,
                    dataset_name=ds_label,
                )
                if fp.exact_sha256:
                    index.add(fp)

        for key, val in reference_splits.items():
            if isinstance(val, Mapping):
                for sp_name, recs in val.items():
                    if isinstance(recs, (list, tuple)):
                        _index_split(str(key), str(sp_name), recs)
            elif isinstance(val, (list, tuple)):
                _index_split("current_dataset", str(key), val)

        return index, sorted(scanned_splits)

    def check_entries(
        self,
        new_entries: Iterable[str | Mapping[str, Any]] | Mapping[str, Iterable[str | Mapping[str, Any]]],
        *,
        reference_splits: Mapping[str, Any] | None = None,
        reference_dirs: Iterable[str | Path] | None = None,
        reference_conn: sqlite3.Connection | None = None,
        exclude_dataset_id: str | None = None,
        allowed_root: str | Path | None = None,
        check_internal_splits: bool = True,
        raise_on_leakage: bool = False,
    ) -> SemanticLeakageReport:
        """
        Compare new dataset entries against existing `train` / `val` (`validation`)
        reference splits (and internal candidate splits when `new_entries` is a split map)
        using semantic hashing.
        """
        merged_refs: dict[str, Any] = {}
        if reference_splits:
            for k, v in reference_splits.items():
                merged_refs[str(k)] = v
        if reference_dirs:
            dir_refs = self.load_reference_splits_from_dirs(
                reference_dirs, allowed_root=allowed_root
            )
            for ds_k, sp_map in dir_refs.items():
                merged_refs[f"dir:{ds_k}"] = sp_map
        if reference_conn is not None:
            db_refs = self.load_reference_splits_from_sqlite(
                reference_conn, exclude_dataset_id=exclude_dataset_id
            )
            for ds_k, sp_map in db_refs.items():
                merged_refs[f"db:{ds_k}"] = sp_map

        ref_index, ref_splits_scanned = self._build_index_from_references(merged_refs)

        if isinstance(new_entries, Mapping):
            incoming_by_split: dict[str, list[Any]] = {
                str(sp).strip().lower(): list(recs)
                for sp, recs in new_entries.items()
                if recs is not None
            }
        else:
            incoming_by_split = {"incoming": list(new_entries)}

        matches: list[LeakageMatch] = []
        new_fps_by_split: dict[str, list[SemanticFingerprint]] = {}
        total_new = 0

        for sp_name, recs in incoming_by_split.items():
            sp_fps: list[SemanticFingerprint] = []
            for idx, rec in enumerate(recs):
                total_new += 1
                fp = self.compute_fingerprint(
                    rec,
                    record_index=idx,
                    split=sp_name,
                    dataset_name="incoming",
                )
                if not fp.exact_sha256:
                    continue
                sp_fps.append(fp)
                if ref_index.items:
                    hit = ref_index.match(
                        fp,
                        max_hamming=self.simhash_max_hamming,
                        min_similarity=self.min_semantic_similarity,
                        min_informative_tokens=self.min_informative_tokens,
                    )
                    if hit is not None:
                        matches.append(hit)
            if sp_fps:
                new_fps_by_split[sp_name] = sp_fps

        # Also check cross-split semantic leakage within incoming multi-split payloads
        if check_internal_splits and len(new_fps_by_split) > 1:
            split_order = list(new_fps_by_split.keys())
            for i, sp_a in enumerate(split_order):
                idx_a = _SemanticIndex()
                for fp_a in new_fps_by_split[sp_a]:
                    idx_a.add(fp_a)
                for sp_b in split_order[i + 1 :]:
                    for fp_b in new_fps_by_split[sp_b]:
                        hit = idx_a.match(
                            fp_b,
                            max_hamming=self.simhash_max_hamming,
                            min_similarity=self.min_semantic_similarity,
                            min_informative_tokens=self.min_informative_tokens,
                        )
                        if hit is not None:
                            matches.append(hit)

        exact_cnt = sum(1 for m in matches if m.match_type == "exact_semantic_hash")
        near_cnt = sum(1 for m in matches if m.match_type == "simhash_near_duplicate")
        struct_cnt = sum(1 for m in matches if m.match_type == "structural_semantic_hash")

        violation_groups: Counter[tuple[str, str, str]] = Counter()
        for m in matches:
            violation_groups[(m.match_type, m.new_split, m.existing_split)] += 1
        violations = [
            f"{mtype}:{new_sp}<->{ref_sp}:{cnt}"
            for (mtype, new_sp, ref_sp), cnt in sorted(violation_groups.items())
        ]

        passed = len(matches) == 0
        report = SemanticLeakageReport(
            passed=passed,
            status="PASS" if passed else "FAIL",
            new_records_scanned=total_new,
            reference_records_scanned=len(ref_index.items),
            reference_splits_scanned=ref_splits_scanned,
            exact_matches=exact_cnt,
            near_duplicate_matches=near_cnt,
            structural_matches=struct_cnt,
            matches=matches,
            violations=violations,
        )
        if raise_on_leakage and not passed:
            raise SemanticHashLeakageError(
                f"Semantic hash data leakage detected during ingestion: {', '.join(violations)}"
            )
        return report


def prevent_ingestion_leakage(
    new_entries: Iterable[str | Mapping[str, Any]] | Mapping[str, Iterable[str | Mapping[str, Any]]],
    *,
    reference_splits: Mapping[str, Any] | None = None,
    reference_dirs: Iterable[str | Path] | None = None,
    reference_conn: sqlite3.Connection | None = None,
    allowed_root: str | Path | None = None,
    simhash_max_hamming: int = 16,
    min_semantic_similarity: float = 0.68,
) -> SemanticLeakageReport:
    """Fail-closed helper that blocks ingestion if semantic hash leakage is detected."""
    detector = DatasetLeakageDetector(
        simhash_max_hamming=simhash_max_hamming,
        min_semantic_similarity=min_semantic_similarity,
    )
    return detector.check_entries(
        new_entries,
        reference_splits=reference_splits,
        reference_dirs=reference_dirs,
        reference_conn=reference_conn,
        allowed_root=allowed_root,
        raise_on_leakage=True,
    )
