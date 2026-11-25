"""Versioned Knowledge Triple CRUD Persistence Linked to Dataset Version Manifests.

Pure Python 3.11 standard library (SQLite WAL + SHA-256 manifest verification).
Every Knowledge Triple is deterministically versioned, tracks immutable revision
history, and must link to a verified ZYRQUEN Dataset Version manifest on disk.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.core.native.dataset import _sha256_file, verify_dataset_manifest
from apps.core.native.dataset_status import validate_dataset_version

_WS_RE = re.compile(r"\s+")
_VALID_STATUSES = frozenset({"active", "superseded", "deleted"})


class KnowledgeTripleError(ValueError):
    """Base validation/persistence error for Knowledge Triple operations."""


class DatasetManifestLinkError(KnowledgeTripleError):
    """Raised when a linked Dataset Version manifest is missing, invalid, or tampered."""


class TripleNotFoundError(LookupError):
    """Raised when a requested Knowledge Triple ID does not exist."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_term(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise KnowledgeTripleError(f"{field_name} must be a string.")
    cleaned = _WS_RE.sub(" ", value).strip()
    if not cleaned:
        raise KnowledgeTripleError(f"{field_name} must not be empty.")
    if len(cleaned) > 512:
        raise KnowledgeTripleError(f"{field_name} exceeds maximum length of 512 characters.")
    return cleaned


def _validate_confidence(confidence: Any) -> float:
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise KnowledgeTripleError("confidence must be a finite number between 0.0 and 1.0.")
    val = float(confidence)
    if not math.isfinite(val) or not (0.0 <= val <= 1.0):
        raise KnowledgeTripleError("confidence must be between 0.0 and 1.0.")
    return round(val, 6)


def _compute_triple_sha256(
    subject: str,
    relation: str,
    obj: str,
    dataset_version: str,
) -> str:
    canonical = "|".join(
        [
            subject.casefold(),
            relation.casefold(),
            obj.casefold(),
            dataset_version,
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _serialize_metadata(metadata: dict[str, Any] | None) -> str:
    if metadata is None:
        return "{}"
    if not isinstance(metadata, dict):
        raise KnowledgeTripleError("metadata must be a dictionary.")
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True)


class KnowledgeTripleStore:
    """Thread-safe SQLite WAL CRUD & versioned store for Dataset-linked Knowledge Triples."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        dataset_root: str | Path | None = None,
    ) -> None:
        raw_db = Path(db_path).expanduser()
        if raw_db.is_symlink():
            raise KnowledgeTripleError("Knowledge database path must not be a symlink.")
        self.db_path = raw_db.resolve(strict=False)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.dataset_root = self._resolve_dataset_root(dataset_root)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=10.0,
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._init_schema()

    @staticmethod
    def _resolve_dataset_root(dataset_root: str | Path | None) -> Path | None:
        raw = str(
            dataset_root
            if dataset_root is not None
            else os.getenv("ZYRQUEN_DATASET_ROOT", "")
        ).strip()
        if not raw:
            return None
        candidate = Path(raw).expanduser()
        if candidate.is_symlink():
            raise DatasetManifestLinkError("dataset_root must not be a symlink.")
        return candidate.resolve(strict=False)

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS knowledge_triples (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                relation TEXT NOT NULL,
                object TEXT NOT NULL,
                dataset_version TEXT NOT NULL,
                dataset_content_sha256 TEXT NOT NULL,
                dataset_manifest_sha256 TEXT NOT NULL,
                triple_sha256 TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'active',
                source TEXT NOT NULL DEFAULT 'dataset_manifest',
                confidence REAL NOT NULL DEFAULT 1.0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_by TEXT NOT NULL DEFAULT 'system',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (status IN ('active', 'superseded', 'deleted')),
                CHECK (version >= 1),
                UNIQUE(subject, relation, object, dataset_version)
            );

            CREATE INDEX IF NOT EXISTS idx_kt_dataset_version
                ON knowledge_triples(dataset_version, status);
            CREATE INDEX IF NOT EXISTS idx_kt_subject_relation
                ON knowledge_triples(subject, relation, status);

            CREATE TABLE IF NOT EXISTS knowledge_triple_versions (
                revision_id TEXT PRIMARY KEY,
                triple_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                operation TEXT NOT NULL,
                subject TEXT NOT NULL,
                relation TEXT NOT NULL,
                object TEXT NOT NULL,
                dataset_version TEXT NOT NULL,
                dataset_content_sha256 TEXT NOT NULL,
                dataset_manifest_sha256 TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence REAL NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                actor TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_ktv_triple_id
                ON knowledge_triple_versions(triple_id, version);
            """
        )
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _resolve_and_verify_manifest(
        self,
        dataset_version: str,
        *,
        dataset_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        clean_version = validate_dataset_version(dataset_version)
        if dataset_dir is not None:
            raw_dir = Path(dataset_dir).expanduser()
            if raw_dir.is_symlink():
                raise DatasetManifestLinkError("Dataset directory must not be a symlink.")
            resolved_dir = raw_dir.resolve(strict=False)
            if self.dataset_root is not None:
                if resolved_dir != self.dataset_root and not resolved_dir.is_relative_to(self.dataset_root):
                    raise DatasetManifestLinkError(
                        "Dataset directory escapes configured dataset_root."
                    )
        else:
            if self.dataset_root is None:
                raise DatasetManifestLinkError(
                    "dataset_root or dataset_dir is required to verify Dataset Version manifest."
                )
            if not self.dataset_root.is_dir():
                raise DatasetManifestLinkError(
                    f"Configured dataset_root does not exist: {self.dataset_root}"
                )
            candidate = (self.dataset_root / clean_version).resolve(strict=False)
            if candidate == self.dataset_root or not candidate.is_relative_to(self.dataset_root):
                raise DatasetManifestLinkError("Dataset version resolves outside dataset_root.")
            resolved_dir = candidate

        if not resolved_dir.is_dir():
            raise DatasetManifestLinkError(
                f"Dataset version directory not found for {clean_version!r}."
            )

        try:
            manifest = verify_dataset_manifest(resolved_dir)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise DatasetManifestLinkError(
                f"Dataset manifest verification failed for {clean_version!r}: {exc}"
            ) from exc

        manifest_ver = str(manifest.get("version") or "").strip()
        if manifest_ver != clean_version:
            raise DatasetManifestLinkError(
                f"Dataset manifest version {manifest_ver!r} does not match requested {clean_version!r}."
            )
        manifest_sha = _sha256_file(resolved_dir / "manifest.json")
        return {
            "dataset_version": clean_version,
            "dataset_content_sha256": str(manifest["content_sha256"]),
            "dataset_manifest_sha256": manifest_sha,
            "dataset_dir": str(resolved_dir),
            "manifest": manifest,
        }

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "subject": row["subject"],
            "relation": row["relation"],
            "object": row["object"],
            "dataset_version": row["dataset_version"],
            "dataset_content_sha256": row["dataset_content_sha256"],
            "dataset_manifest_sha256": row["dataset_manifest_sha256"],
            "triple_sha256": row["triple_sha256"],
            "version": int(row["version"]),
            "status": row["status"],
            "source": row["source"],
            "confidence": float(row["confidence"]),
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _revision_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "revision_id": row["revision_id"],
            "triple_id": row["triple_id"],
            "version": int(row["version"]),
            "operation": row["operation"],
            "subject": row["subject"],
            "relation": row["relation"],
            "object": row["object"],
            "dataset_version": row["dataset_version"],
            "dataset_content_sha256": row["dataset_content_sha256"],
            "dataset_manifest_sha256": row["dataset_manifest_sha256"],
            "status": row["status"],
            "confidence": float(row["confidence"]),
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "actor": row["actor"],
            "recorded_at": row["recorded_at"],
        }

    def _append_revision_locked(
        self,
        *,
        triple_id: str,
        version: int,
        operation: str,
        subject: str,
        relation: str,
        obj: str,
        dataset_version: str,
        dataset_content_sha256: str,
        dataset_manifest_sha256: str,
        status: str,
        confidence: float,
        metadata_json: str,
        actor: str,
        recorded_at: str,
    ) -> dict[str, Any]:
        rev_id = str(uuid.uuid4())
        self._conn.execute(
            """
            INSERT INTO knowledge_triple_versions (
                revision_id, triple_id, version, operation,
                subject, relation, object,
                dataset_version, dataset_content_sha256, dataset_manifest_sha256,
                status, confidence, metadata_json, actor, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rev_id,
                triple_id,
                version,
                operation,
                subject,
                relation,
                obj,
                dataset_version,
                dataset_content_sha256,
                dataset_manifest_sha256,
                status,
                confidence,
                metadata_json,
                actor,
                recorded_at,
            ),
        )
        return {
            "revision_id": rev_id,
            "triple_id": triple_id,
            "version": version,
            "operation": operation,
            "recorded_at": recorded_at,
        }

    def create_triple(
        self,
        subject: str,
        relation: str,
        obj: str,
        *,
        dataset_version: str,
        dataset_dir: str | Path | None = None,
        source: str = "dataset_manifest",
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
        actor: str = "system",
    ) -> dict[str, Any]:
        """Create and persist a new Knowledge Triple linked to a verified Dataset Version manifest."""
        clean_subj = _normalize_term(subject, "subject")
        clean_rel = _normalize_term(relation, "relation")
        clean_obj = _normalize_term(obj, "object")
        clean_conf = _validate_confidence(confidence)
        clean_source = _normalize_term(source, "source")
        clean_actor = _normalize_term(actor, "actor")
        meta_json = _serialize_metadata(metadata)
        link = self._resolve_and_verify_manifest(dataset_version, dataset_dir=dataset_dir)

        triple_id = str(uuid.uuid4())
        now = _now_iso()
        triple_sha = _compute_triple_sha256(
            clean_subj, clean_rel, clean_obj, link["dataset_version"]
        )

        with self._lock:
            existing = self._conn.execute(
                """
                SELECT * FROM knowledge_triples
                WHERE subject=? AND relation=? AND object=? AND dataset_version=?
                """,
                (clean_subj, clean_rel, clean_obj, link["dataset_version"]),
            ).fetchone()
            if existing is not None:
                raise KnowledgeTripleError(
                    f"Knowledge triple already exists for dataset_version={link['dataset_version']!r}."
                )

            contradictions = [
                self._row_to_dict(r)
                for r in self._conn.execute(
                    """
                    SELECT * FROM knowledge_triples
                    WHERE subject=? AND relation=? AND object!=? AND status='active'
                    """,
                    (clean_subj, clean_rel, clean_obj),
                ).fetchall()
            ]

            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO knowledge_triples (
                        id, subject, relation, object,
                        dataset_version, dataset_content_sha256, dataset_manifest_sha256,
                        triple_sha256, version, status, source, confidence,
                        metadata_json, created_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'active', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        triple_id,
                        clean_subj,
                        clean_rel,
                        clean_obj,
                        link["dataset_version"],
                        link["dataset_content_sha256"],
                        link["dataset_manifest_sha256"],
                        triple_sha,
                        clean_source,
                        clean_conf,
                        meta_json,
                        clean_actor,
                        now,
                        now,
                    ),
                )
                rev = self._append_revision_locked(
                    triple_id=triple_id,
                    version=1,
                    operation="create",
                    subject=clean_subj,
                    relation=clean_rel,
                    obj=clean_obj,
                    dataset_version=link["dataset_version"],
                    dataset_content_sha256=link["dataset_content_sha256"],
                    dataset_manifest_sha256=link["dataset_manifest_sha256"],
                    status="active",
                    confidence=clean_conf,
                    metadata_json=meta_json,
                    actor=clean_actor,
                    recorded_at=now,
                )

            row = self._conn.execute(
                "SELECT * FROM knowledge_triples WHERE id=?", (triple_id,)
            ).fetchone()
            record = self._row_to_dict(row)
            record["latest_revision"] = rev
            record["contradictions"] = contradictions
            return record

    def get_triple(
        self,
        triple_id: str,
        *,
        include_history: bool = False,
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM knowledge_triples WHERE id=?",
                (str(triple_id),),
            ).fetchone()
            if row is None:
                return None
            out = self._row_to_dict(row)
            if include_history:
                out["history"] = self.get_triple_history(triple_id)
            return out

    def get_triple_history(self, triple_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM knowledge_triple_versions
                WHERE triple_id=?
                ORDER BY version ASC, recorded_at ASC
                """,
                (str(triple_id),),
            ).fetchall()
            return [self._revision_to_dict(r) for r in rows]

    def list_triples(
        self,
        *,
        dataset_version: str | None = None,
        subject: str | None = None,
        relation: str | None = None,
        object_val: str | None = None,
        status: str | None = "active",
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if not (1 <= int(limit) <= 1000):
            raise KnowledgeTripleError("limit must be between 1 and 1000.")
        if int(offset) < 0:
            raise KnowledgeTripleError("offset must be >= 0.")

        clauses: list[str] = []
        params: list[Any] = []
        if dataset_version is not None:
            clauses.append("dataset_version=?")
            params.append(validate_dataset_version(dataset_version))
        if subject is not None:
            clauses.append("subject=?")
            params.append(_normalize_term(subject, "subject"))
        if relation is not None:
            clauses.append("relation=?")
            params.append(_normalize_term(relation, "relation"))
        if object_val is not None:
            clauses.append("object=?")
            params.append(_normalize_term(object_val, "object"))
        if not include_deleted:
            if status is not None:
                if status not in _VALID_STATUSES:
                    raise KnowledgeTripleError(f"Unsupported triple status filter: {status!r}")
                clauses.append("status=?")
                params.append(status)
            else:
                clauses.append("status!='deleted'")
        elif status is not None:
            if status not in _VALID_STATUSES:
                raise KnowledgeTripleError(f"Unsupported triple status filter: {status!r}")
            clauses.append("status=?")
            params.append(status)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT * FROM knowledge_triples "
            f"{where_sql} "
            "ORDER BY updated_at DESC, id ASC LIMIT ? OFFSET ?"
        )
        params.extend([int(limit), int(offset)])
        with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def update_triple(
        self,
        triple_id: str,
        *,
        subject: str | None = None,
        relation: str | None = None,
        obj: str | None = None,
        dataset_version: str | None = None,
        dataset_dir: str | Path | None = None,
        status: str | None = None,
        confidence: float | None = None,
        metadata: dict[str, Any] | None = None,
        actor: str = "system",
        verify_manifest: bool = True,
    ) -> dict[str, Any]:
        """Update a Knowledge Triple atomically, incrementing version and appending immutable history."""
        clean_actor = _normalize_term(actor, "actor")
        with self._lock:
            existing = self._conn.execute(
                "SELECT * FROM knowledge_triples WHERE id=?",
                (str(triple_id),),
            ).fetchone()
            if existing is None:
                raise TripleNotFoundError(f"Knowledge triple not found: {triple_id}")

            new_subj = _normalize_term(subject, "subject") if subject is not None else existing["subject"]
            new_rel = _normalize_term(relation, "relation") if relation is not None else existing["relation"]
            new_obj = _normalize_term(obj, "object") if obj is not None else existing["object"]
            new_conf = _validate_confidence(confidence) if confidence is not None else float(existing["confidence"])
            new_status = status if status is not None else existing["status"]
            if new_status not in _VALID_STATUSES:
                raise KnowledgeTripleError(f"Unsupported triple status: {new_status!r}")
            new_meta_json = (
                _serialize_metadata(metadata)
                if metadata is not None
                else str(existing["metadata_json"] or "{}")
            )

            target_ds_version = (
                validate_dataset_version(dataset_version)
                if dataset_version is not None
                else str(existing["dataset_version"])
            )
            if dataset_version is not None or dataset_dir is not None or verify_manifest:
                link = self._resolve_and_verify_manifest(
                    target_ds_version,
                    dataset_dir=dataset_dir,
                )
                ds_content_sha = link["dataset_content_sha256"]
                ds_manifest_sha = link["dataset_manifest_sha256"]
            else:
                ds_content_sha = str(existing["dataset_content_sha256"])
                ds_manifest_sha = str(existing["dataset_manifest_sha256"])

            duplicate = self._conn.execute(
                """
                SELECT id FROM knowledge_triples
                WHERE subject=? AND relation=? AND object=? AND dataset_version=? AND id!=?
                """,
                (new_subj, new_rel, new_obj, target_ds_version, str(triple_id)),
            ).fetchone()
            if duplicate is not None:
                raise KnowledgeTripleError(
                    f"Another triple already exists with the same (subject, relation, object, dataset_version)."
                )

            next_version = int(existing["version"]) + 1
            now = _now_iso()
            triple_sha = _compute_triple_sha256(
                new_subj, new_rel, new_obj, target_ds_version
            )

            with self._conn:
                self._conn.execute(
                    """
                    UPDATE knowledge_triples
                    SET subject=?, relation=?, object=?,
                        dataset_version=?, dataset_content_sha256=?, dataset_manifest_sha256=?,
                        triple_sha256=?, version=?, status=?, confidence=?,
                        metadata_json=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        new_subj,
                        new_rel,
                        new_obj,
                        target_ds_version,
                        ds_content_sha,
                        ds_manifest_sha,
                        triple_sha,
                        next_version,
                        new_status,
                        new_conf,
                        new_meta_json,
                        now,
                        str(triple_id),
                    ),
                )
                rev = self._append_revision_locked(
                    triple_id=str(triple_id),
                    version=next_version,
                    operation="update",
                    subject=new_subj,
                    relation=new_rel,
                    obj=new_obj,
                    dataset_version=target_ds_version,
                    dataset_content_sha256=ds_content_sha,
                    dataset_manifest_sha256=ds_manifest_sha,
                    status=new_status,
                    confidence=new_conf,
                    metadata_json=new_meta_json,
                    actor=clean_actor,
                    recorded_at=now,
                )

            updated = self._conn.execute(
                "SELECT * FROM knowledge_triples WHERE id=?",
                (str(triple_id),),
            ).fetchone()
            out = self._row_to_dict(updated)
            out["latest_revision"] = rev
            return out

    def delete_triple(
        self,
        triple_id: str,
        *,
        hard: bool = False,
        actor: str = "system",
    ) -> dict[str, Any]:
        """Delete a Knowledge Triple (soft-delete by default; preserves version audit history)."""
        clean_actor = _normalize_term(actor, "actor")
        with self._lock:
            existing = self._conn.execute(
                "SELECT * FROM knowledge_triples WHERE id=?",
                (str(triple_id),),
            ).fetchone()
            if existing is None:
                raise TripleNotFoundError(f"Knowledge triple not found: {triple_id}")

            next_version = int(existing["version"]) + 1
            now = _now_iso()
            op = "hard_delete" if hard else "soft_delete"

            with self._conn:
                if hard:
                    self._conn.execute(
                        "DELETE FROM knowledge_triples WHERE id=?",
                        (str(triple_id),),
                    )
                else:
                    self._conn.execute(
                        """
                        UPDATE knowledge_triples
                        SET status='deleted', version=?, updated_at=?
                        WHERE id=?
                        """,
                        (next_version, now, str(triple_id)),
                    )
                rev = self._append_revision_locked(
                    triple_id=str(triple_id),
                    version=next_version,
                    operation=op,
                    subject=existing["subject"],
                    relation=existing["relation"],
                    obj=existing["object"],
                    dataset_version=existing["dataset_version"],
                    dataset_content_sha256=existing["dataset_content_sha256"],
                    dataset_manifest_sha256=existing["dataset_manifest_sha256"],
                    status="deleted",
                    confidence=float(existing["confidence"]),
                    metadata_json=str(existing["metadata_json"] or "{}"),
                    actor=clean_actor,
                    recorded_at=now,
                )

            return {
                "deleted": True,
                "hard": bool(hard),
                "triple_id": str(triple_id),
                "version": next_version,
                "status": "deleted",
                "revision": rev,
            }

    def verify_triple_manifest_link(
        self,
        triple_id: str,
        *,
        dataset_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """Re-verify that a triple's linked Dataset Version manifest still matches stored SHA-256 digests."""
        triple = self.get_triple(triple_id)
        if triple is None:
            raise TripleNotFoundError(f"Knowledge triple not found: {triple_id}")
        try:
            live = self._resolve_and_verify_manifest(
                triple["dataset_version"],
                dataset_dir=dataset_dir,
            )
        except DatasetManifestLinkError as exc:
            return {
                "triple_id": triple_id,
                "dataset_version": triple["dataset_version"],
                "verified": False,
                "reason": str(exc),
            }

        content_match = live["dataset_content_sha256"] == triple["dataset_content_sha256"]
        manifest_match = live["dataset_manifest_sha256"] == triple["dataset_manifest_sha256"]
        verified = bool(content_match and manifest_match)
        return {
            "triple_id": triple_id,
            "dataset_version": triple["dataset_version"],
            "verified": verified,
            "content_sha256_match": content_match,
            "manifest_sha256_match": manifest_match,
            "reason": None if verified else "Linked dataset manifest digest drifted after triple creation.",
        }
