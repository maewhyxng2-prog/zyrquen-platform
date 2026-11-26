"""
Task Memory & Experience Retrieval for ZYRQUEN Tool Center.
-----------------------------------------------------------
Records structured tool-orchestration experiences (goal, tool sequence,
context keys, outcome verdict, error taxonomy, recovery actions, latency)
into SQLite and retrieves relevant lessons alongside `episodic_experiences`
to inform Tool Intelligence & Selection and Failure Recovery.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from typing import Any


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _extract_keywords(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9_.\-]+|[\u0E00-\u0E7F]{2,}", str(text or "").lower())
    seen: list[str] = []
    for tok in tokens:
        if len(tok) >= 2 and tok not in seen:
            seen.append(tok)
        if len(seen) >= 24:
            break
    return seen


def init_task_memory_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS task_memory_entries (
            id TEXT PRIMARY KEY,
            trace_id TEXT,
            goal TEXT NOT NULL,
            goal_keywords_json TEXT NOT NULL,
            toolkit_ids_json TEXT NOT NULL,
            capability_sequence_json TEXT NOT NULL,
            outcome_status TEXT NOT NULL CHECK(outcome_status IN ('SUCCESS', 'PARTIAL_SUCCESS', 'FAILED', 'UNVERIFIED')),
            error_code TEXT,
            error_message TEXT,
            recovery_action TEXT,
            context_keys_json TEXT NOT NULL DEFAULT '[]',
            latency_ms REAL NOT NULL DEFAULT 0.0,
            verified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_task_memory_created
            ON task_memory_entries (created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_task_memory_outcome
            ON task_memory_entries (outcome_status, created_at DESC);
        """
    )


def record_task_memory(
    conn: sqlite3.Connection,
    *,
    trace_id: str | None,
    goal: str,
    toolkit_ids: list[str],
    capability_sequence: list[str],
    outcome_status: str,
    error_code: str | None = None,
    error_message: str | None = None,
    recovery_action: str | None = None,
    context_keys: list[str] | None = None,
    latency_ms: float = 0.0,
    verified: bool = False,
) -> str:
    init_task_memory_schema(conn)
    norm_outcome = outcome_status if outcome_status in {"SUCCESS", "PARTIAL_SUCCESS", "FAILED", "UNVERIFIED"} else "UNVERIFIED"
    entry_id = str(uuid.uuid4())
    keywords = _extract_keywords(goal)
    with conn:
        conn.execute(
            """
            INSERT INTO task_memory_entries (
                id, trace_id, goal, goal_keywords_json, toolkit_ids_json,
                capability_sequence_json, outcome_status, error_code, error_message,
                recovery_action, context_keys_json, latency_ms, verified, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                trace_id,
                str(goal or "")[:500],
                json.dumps(keywords, ensure_ascii=False),
                json.dumps(sorted(set(toolkit_ids)), ensure_ascii=False),
                json.dumps(capability_sequence, ensure_ascii=False),
                norm_outcome,
                error_code,
                str(error_message)[:500] if error_message else None,
                str(recovery_action)[:300] if recovery_action else None,
                json.dumps(sorted(set(context_keys or [])), ensure_ascii=False),
                round(float(latency_ms or 0.0), 2),
                1 if verified else 0,
                _now_iso(),
            ),
        )
    return entry_id


def retrieve_relevant_memories(
    conn: sqlite3.Connection,
    goal: str,
    *,
    limit: int = 8,
) -> dict[str, Any]:
    init_task_memory_schema(conn)
    query_kws = set(_extract_keywords(goal))
    rows = conn.execute(
        "SELECT * FROM task_memory_entries ORDER BY created_at DESC LIMIT 100"
    ).fetchall()

    scored: list[dict[str, Any]] = []
    for r in rows:
        try:
            row_kws = set(json.loads(r["goal_keywords_json"] or "[]"))
        except Exception:
            row_kws = set()
        if not query_kws:
            sim = 0.5
        else:
            union = query_kws | row_kws
            sim = len(query_kws & row_kws) / len(union) if union else 0.0
        if sim <= 0.0 and query_kws:
            continue
        item = dict(r)
        item["similarity"] = round(sim, 3)
        scored.append(item)

    scored.sort(key=lambda x: (-x["similarity"], 0 if x["outcome_status"] == "SUCCESS" else 1, -x["verified"]))

    # Also inspect existing episodic_experiences if table exists
    episodic_matches: list[dict[str, Any]] = []
    has_ep = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='episodic_experiences'"
    ).fetchone()
    if has_ep:
        for ep in conn.execute(
            "SELECT id, goal, outcome_status, gap_type, created_at FROM episodic_experiences ORDER BY created_at DESC LIMIT 30"
        ).fetchall():
            ep_kws = set(_extract_keywords(ep["goal"]))
            overlap = len(query_kws & ep_kws)
            if overlap > 0 or not query_kws:
                episodic_matches.append({**dict(ep), "keyword_overlap": overlap})
        episodic_matches.sort(key=lambda x: -x["keyword_overlap"])

    return {
        "matches": scored[:limit],
        "episodic_matches": episodic_matches[:5],
        "success_examples": [m for m in scored if m["outcome_status"] == "SUCCESS"][:4],
        "failure_lessons": [m for m in scored if m["outcome_status"] in {"FAILED", "PARTIAL_SUCCESS"}][:4],
    }


def summarize_capability_track_record(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Aggregate empirical success rate & average latency per capability_id."""
    init_task_memory_schema(conn)
    stats: dict[str, dict[str, Any]] = {}
    rows = conn.execute(
        """
        SELECT capability_sequence_json, outcome_status, latency_ms, verified
        FROM task_memory_entries
        ORDER BY created_at DESC
        LIMIT 250
        """
    ).fetchall()
    for r in rows:
        try:
            caps = json.loads(r["capability_sequence_json"] or "[]")
        except Exception:
            caps = []
        is_ok = r["outcome_status"] == "SUCCESS" and bool(r["verified"])
        lat = float(r["latency_ms"] or 0.0)
        for cid in caps:
            cur = stats.setdefault(cid, {"runs": 0, "successes": 0, "total_latency_ms": 0.0})
            cur["runs"] += 1
            if is_ok:
                cur["successes"] += 1
            cur["total_latency_ms"] += lat

    # Supplement with tool_center_invocations if available
    has_inv = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tool_center_invocations'"
    ).fetchone()
    if has_inv:
        for r in conn.execute(
            "SELECT capability_id, status, latency_ms FROM tool_center_invocations ORDER BY created_at DESC LIMIT 250"
        ).fetchall():
            cid = r["capability_id"]
            cur = stats.setdefault(cid, {"runs": 0, "successes": 0, "total_latency_ms": 0.0})
            cur["runs"] += 1
            if r["status"] == "COMPLETED":
                cur["successes"] += 1
            cur["total_latency_ms"] += float(r["latency_ms"] or 0.0)

    out: dict[str, dict[str, Any]] = {}
    for cid, cur in stats.items():
        runs = cur["runs"]
        out[cid] = {
            "runs": runs,
            "success_rate": round(cur["successes"] / runs, 3) if runs > 0 else 0.0,
            "avg_latency_ms": round(cur["total_latency_ms"] / runs, 2) if runs > 0 else 0.0,
        }
    return out


def analyze_failure_patterns(conn: sqlite3.Connection, *, limit: int = 10) -> list[dict[str, Any]]:
    init_task_memory_schema(conn)
    rows = conn.execute(
        """
        SELECT capability_sequence_json, error_code, error_message, goal, created_at
        FROM task_memory_entries
        WHERE outcome_status IN ('FAILED', 'PARTIAL_SUCCESS', 'UNVERIFIED')
        ORDER BY created_at DESC
        LIMIT 100
        """
    ).fetchall()
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        err_code = str(r["error_code"] or "EXECUTION_ERROR")
        try:
            caps = json.loads(r["capability_sequence_json"] or "[]")
        except Exception:
            caps = []
        cap_key = caps[0] if caps else "orchestration"
        key = (cap_key, err_code)
        bucket = grouped.setdefault(
            key,
            {
                "capability_id": cap_key,
                "error_code": err_code,
                "count": 0,
                "sample_goal": r["goal"],
                "sample_error": r["error_message"],
                "last_seen": r["created_at"],
            },
        )
        bucket["count"] += 1
    patterns = sorted(grouped.values(), key=lambda x: (-x["count"], x["capability_id"]))
    return patterns[:limit]
