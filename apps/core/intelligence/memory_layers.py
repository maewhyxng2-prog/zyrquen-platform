"""Segmented Knowledge & Corpus Layers with Provenance, Deduplication, and Leakage Checks."""

from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_WHITESPACE_RE = re.compile(r"\s+")
ALLOWED_KNOWLEDGE_STATUSES = frozenset({"VERIFIED"})


def normalize_text(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return _WHITESPACE_RE.sub(" ", text.strip().lower())


def content_sha256(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def token_shingles(text: str, n: int = 5) -> set[tuple[str, ...]]:
    tokens = normalize_text(text).split(" ")
    tokens = [t for t in tokens if t]
    if len(tokens) < n:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


@dataclass(frozen=True)
class MemoryRecord:
    record_id: str
    content: str
    content_hash: str
    source_id: str
    retrieved_at: str
    evidence_status: str
    metadata: dict[str, Any] = field(default_factory=dict)


class WorkingMemory:
    """Short-lived task/session scratchpad with bounded capacity and optional TTL."""

    def __init__(self, max_items: int = 128) -> None:
        if max_items < 1:
            raise ValueError("max_items must be >= 1")
        self._max_items = max_items
        self._items: dict[str, tuple[Any, float | None]] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()

    def put(self, key: str, value: Any, *, ttl_sec: float | None = None) -> None:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("key must be non-empty string")
        expires_at = (time.monotonic() + ttl_sec) if ttl_sec is not None else None
        with self._lock:
            if key in self._order:
                self._order.remove(key)
            elif len(self._order) >= self._max_items:
                oldest = self._order.pop(0)
                self._items.pop(oldest, None)
            self._items[key] = (value, expires_at)
            self._order.append(key)

    def get(self, key: str, default: Any = None) -> Any:
        now = time.monotonic()
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return default
            val, expires_at = entry
            if expires_at is not None and now > expires_at:
                self._items.pop(key, None)
                if key in self._order:
                    self._order.remove(key)
                return default
            return val

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._order.clear()

    def size(self) -> int:
        now = time.monotonic()
        with self._lock:
            expired = [
                k for k, (_, exp) in self._items.items() if exp is not None and now > exp
            ]
            for k in expired:
                self._items.pop(k, None)
                if k in self._order:
                    self._order.remove(k)
            return len(self._items)


class EpisodicMemory:
    """Append-only chronological execution and interaction log (not training corpus)."""

    def __init__(self) -> None:
        self._episodes: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def append(
        self,
        *,
        episode_id: str,
        mission_id: str,
        summary: str,
        outcome: str,
        recorded_at: str,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        if not episode_id.strip() or not summary.strip():
            raise ValueError("episode_id and summary must be non-empty")
        entry = {
            "episode_id": episode_id,
            "mission_id": mission_id,
            "summary": summary,
            "outcome": outcome,
            "recorded_at": recorded_at,
            "evidence_refs": list(evidence_refs or []),
        }
        with self._lock:
            self._episodes.append(entry)
        return dict(entry)

    def list_episodes(self, mission_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(item)
                for item in self._episodes
                if mission_id is None or item["mission_id"] == mission_id
            ]


class VerifiedKnowledgeStore:
    """Stores strictly VERIFIED facts with full provenance and hash deduplication."""

    def __init__(self) -> None:
        self._records_by_hash: dict[str, MemoryRecord] = {}
        self._lock = threading.RLock()

    def add(
        self,
        *,
        record_id: str,
        content: str,
        source_id: str,
        retrieved_at: str,
        evidence_status: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if evidence_status not in ALLOWED_KNOWLEDGE_STATUSES:
            return {
                "stored": False,
                "reason": f"rejected_status:{evidence_status}",
                "learned": False,
            }
        if not isinstance(source_id, str) or not source_id.strip():
            return {"stored": False, "reason": "missing_source_id", "learned": False}
        if not isinstance(retrieved_at, str) or not retrieved_at.strip():
            return {"stored": False, "reason": "missing_retrieved_at", "learned": False}
        if not isinstance(content, str) or not content.strip():
            return {"stored": False, "reason": "empty_content", "learned": False}

        digest = content_sha256(content)
        with self._lock:
            if digest in self._records_by_hash:
                return {
                    "stored": False,
                    "duplicate": True,
                    "reason": "duplicate_content_hash",
                    "content_hash": digest,
                    "learned": False,
                }
            record = MemoryRecord(
                record_id=record_id,
                content=content.strip(),
                content_hash=digest,
                source_id=source_id.strip(),
                retrieved_at=retrieved_at.strip(),
                evidence_status="VERIFIED",
                metadata=dict(metadata or {}),
            )
            self._records_by_hash[digest] = record
        return {
            "stored": True,
            "duplicate": False,
            "content_hash": digest,
            "learned": True,
        }

    def query(self, keyword: str) -> list[MemoryRecord]:
        needle = normalize_text(keyword)
        with self._lock:
            return [
                rec
                for rec in self._records_by_hash.values()
                if not needle or needle in normalize_text(rec.content)
            ]

    def count(self) -> int:
        with self._lock:
            return len(self._records_by_hash)


class EvaluationCorpusStore:
    """Isolated held-out evaluation corpus (unseen/ood); never exposed to training writes."""

    ALLOWED_SPLITS = frozenset({"unseen", "ood", "validation"})

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._hashes: set[str] = set()
        self._shingles: set[tuple[str, ...]] = set()
        self._lock = threading.RLock()

    def add_heldout(self, *, sample_id: str, text: str, split: str) -> dict[str, Any]:
        if split not in self.ALLOWED_SPLITS:
            raise ValueError(f"Invalid eval split: {split!r}")
        if not text.strip():
            raise ValueError("Evaluation text cannot be empty")
        digest = content_sha256(text)
        shingles = token_shingles(text, n=5)
        with self._lock:
            self._items[sample_id] = {
                "sample_id": sample_id,
                "text": text.strip(),
                "split": split,
                "content_hash": digest,
            }
            self._hashes.add(digest)
            self._shingles.update(shingles)
        return {"sample_id": sample_id, "split": split, "content_hash": digest}

    def is_contaminated(self, candidate_text: str) -> tuple[bool, str | None]:
        digest = content_sha256(candidate_text)
        cand_shingles = token_shingles(candidate_text, n=5)
        with self._lock:
            if digest in self._hashes:
                return True, "exact_eval_hash_overlap"
            if cand_shingles and (cand_shingles & self._shingles):
                return True, "five_gram_eval_overlap"
        return False, None

    def count(self) -> int:
        with self._lock:
            return len(self._items)


class TrainingCorpusStore:
    """Curated training corpus enforcing verification, deduplication, and zero eval leakage."""

    def __init__(self, evaluation_corpus: EvaluationCorpusStore) -> None:
        self._eval_corpus = evaluation_corpus
        self._records: dict[str, MemoryRecord] = {}
        self._lock = threading.RLock()

    def admit(
        self,
        *,
        record_id: str,
        content: str,
        source_id: str,
        retrieved_at: str,
        evidence_status: str,
    ) -> dict[str, Any]:
        if evidence_status != "VERIFIED":
            return {
                "admitted": False,
                "reason": f"non_verified_evidence:{evidence_status}",
            }
        if not source_id.strip() or not retrieved_at.strip() or not content.strip():
            return {"admitted": False, "reason": "missing_provenance_or_content"}

        contaminated, leakage_reason = self._eval_corpus.is_contaminated(content)
        if contaminated:
            return {
                "admitted": False,
                "reason": f"eval_contamination_blocked:{leakage_reason}",
            }

        digest = content_sha256(content)
        with self._lock:
            if digest in self._records:
                return {
                    "admitted": False,
                    "duplicate": True,
                    "reason": "duplicate_training_sample",
                    "content_hash": digest,
                }
            self._records[digest] = MemoryRecord(
                record_id=record_id,
                content=content.strip(),
                content_hash=digest,
                source_id=source_id.strip(),
                retrieved_at=retrieved_at.strip(),
                evidence_status="VERIFIED",
            )
        return {"admitted": True, "content_hash": digest}

    def list_records(self) -> list[MemoryRecord]:
        with self._lock:
            return list(self._records.values())

    def count(self) -> int:
        with self._lock:
            return len(self._records)


class SegmentedKnowledgeEngine:
    """Coordinates all 5 isolated memory & corpus tiers cleanly."""

    def __init__(self, working_max_items: int = 128) -> None:
        self.working = WorkingMemory(max_items=working_max_items)
        self.episodic = EpisodicMemory()
        self.verified = VerifiedKnowledgeStore()
        self.evaluation_corpus = EvaluationCorpusStore()
        self.training_corpus = TrainingCorpusStore(self.evaluation_corpus)
