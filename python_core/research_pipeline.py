#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — Autonomous Multi-Stage Research Pipeline (P1)
----------------------------------------------------------
Pipeline:
  Query Decomposition -> Web Search -> Document Fetch -> Prompt-Injection Quarantine
  -> Structured Claim Extraction -> Cross-Source Contradiction & Freshness Verification

Strictly subordinates external web data as UNTRUSTED_WEB_EVIDENCE and preserves
CONFLICTING_SOURCES -> NOT_LEARNED. Zero external LLM usage.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from tools_engine import analyze_tool_result, invoke_tool_governed


_INJECTION_PATTERNS = [
    re.compile(r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?", re.I),
    re.compile(r"(?:system|assistant|developer)\s*:\s*", re.I),
    re.compile(r"<\s*/?\s*(?:script|style|iframe|system|prompt)\b[^>]*>", re.I),
    re.compile(r"^\s*(?:สอน|จำว่า|ภารกิจ|ปฏิบัติการ|วางแผน|เขียนไฟล์|write_file|doc_fetch|web_search)\s*:", re.I | re.M),
]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def decompose_research_queries(goal: str) -> list[str]:
    """Break a mission goal into 1-3 focused search queries without external LLMs."""
    cleaned = re.sub(
        r"^(?:ภารกิจ|ปฏิบัติการ(?:อัตโนมัติ)?|mission|autonomous|ค้นคว้า|สืบค้น|เปรียบเทียบ|research|investigate|compare)\s*:?\s*",
        "",
        goal.strip(),
        flags=re.IGNORECASE,
    ).strip()
    if not cleaned:
        return []

    # Split multi-topic Thai/English connectors into focused sub-queries
    parts = re.split(r"\s*(?:และ|กับ|เทียบกับ|vs\.?|versus|,|;)\s*", cleaned, flags=re.IGNORECASE)
    queries: list[str] = []
    seen: set[str] = set()

    def _add_q(q: str) -> None:
        q_clean = re.sub(
            r"^(?:พัฒนาองค์ความรู้(?:เกี่ยวกับ|เรื่อง)?|สร้างองค์ความรู้(?:เกี่ยวกับ|เรื่อง)?|ตรวจสอบ|วิเคราะห์|เรื่อง|เกี่ยวกับ)\s*",
            "",
            q.strip(),
            flags=re.IGNORECASE,
        ).strip()
        if len(q_clean) >= 2 and q_clean.lower() not in seen:
            seen.add(q_clean.lower())
            queries.append(q_clean[:160])

    _add_q(cleaned)
    for p in parts:
        if len(queries) >= 3:
            break
        if len(p.strip()) >= 3:
            _add_q(p)
    return queries[:3]


def sanitize_untrusted_text(raw_text: str) -> tuple[str, list[str]]:
    """
    Quarantine untrusted external document text against prompt/command injection.
    Returns (sanitized_text, warnings).
    """
    warnings: list[str] = []
    text = str(raw_text or "")
    for pat in _INJECTION_PATTERNS:
        if pat.search(text):
            warnings.append(f"Quarantined untrusted directive pattern: {pat.pattern[:48]}")
            text = pat.sub("[QUARANTINED_DIRECTIVE] ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text, warnings


def extract_structured_claims(
    text: str,
    query_terms: list[str],
    *,
    source_url: str,
    provider: str,
    max_claims: int = 5,
) -> list[dict[str, Any]]:
    """Extract grounded factual claim snippets matching query terms from sanitized text."""
    sanitized, _ = sanitize_untrusted_text(text)
    if not sanitized:
        return []

    sentences = re.split(r"(?<=[.!?])\s+|\n+", sanitized)
    q_terms = {t.lower() for t in query_terms if len(t) >= 2}
    scored: list[tuple[int, str]] = []
    for sent in sentences:
        s = sent.strip()
        if len(s) < 16 or len(s) > 420:
            continue
        s_low = s.lower()
        overlap = sum(1 for qt in q_terms if qt in s_low)
        if overlap > 0 or not q_terms:
            scored.append((overlap, s))

    scored.sort(key=lambda item: (-item[0], len(item[1])))
    claims: list[dict[str, Any]] = []
    seen_txt: set[str] = set()
    for score, s in scored:
        key = s.lower()
        if key in seen_txt:
            continue
        seen_txt.add(key)
        claims.append(
            {
                "claim_text": s,
                "term_overlap": score,
                "source_url": source_url,
                "provider": provider,
                "trust_status": "UNTRUSTED_WEB_EVIDENCE",
            }
        )
        if len(claims) >= max_claims:
            break
    return claims


def _persist_mission_evidence(
    conn: sqlite3.Connection,
    mission_id: str,
    node_id: str | None,
    evidence_items: list[dict[str, Any]],
    trust_grade: str,
    claims_by_url: dict[str, list[dict[str, Any]]],
) -> None:
    now = _now_iso()
    for item in evidence_items:
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        prov = str(item.get("provider") or "web")
        ret_at = str(item.get("retrieved_at") or now)
        snippet = str(item.get("snippet") or item.get("title") or "")
        claims = claims_by_url.get(url, [])
        digest = hashlib.sha256(f"{url}|{snippet}".encode("utf-8")).hexdigest()
        existing = conn.execute(
            "SELECT id FROM mission_evidence WHERE mission_id=? AND source_url=? AND content_sha256=?",
            (mission_id, url, digest),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            """
            INSERT INTO mission_evidence (
                id, mission_id, node_id, source_url, provider,
                retrieved_at, trust_grade, content_sha256, extracted_claims_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                mission_id,
                node_id,
                url,
                prov,
                ret_at,
                trust_grade,
                digest,
                _to_json(claims),
            ),
        )


def _to_json(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def run_research_pipeline(
    conn: sqlite3.Connection,
    data_dir: Path,
    goal: str,
    *,
    user_id: str,
    conversation_id: str | None = None,
    mission_id: str | None = None,
    node_id: str | None = None,
    approved_by: str | None = None,
    existing_invocation_id: str | None = None,
    tokenize_fn: Callable[[str], list[str]],
    extract_terms_fn: Callable[[str], list[str]],
    query_kg_fn: Callable[[sqlite3.Connection, str], list[dict]],
    calc_fn: Callable[[str], dict | None],
) -> dict[str, Any]:
    """
    Execute multi-stage research for a goal:
      1) Query decomposition
      2) Governed web_search (respecting P5 Approval Gate)
      3) Optional doc_fetch deep read when permitted by tool policy
      4) Prompt-injection quarantine + claim extraction + evidence verification
    """
    queries = decompose_research_queries(goal)
    if not queries:
        return {
            "ok": False,
            "status": "FAILED",
            "verdict": "INSUFFICIENT_EVIDENCE",
            "error": "ไม่สามารถแตกคำค้นหาจากเป้าหมายได้",
            "queries": [],
            "claims": [],
            "injection_warnings": [],
        }

    primary_query = queries[0]
    search_res = invoke_tool_governed(
        conn,
        data_dir,
        "web_search",
        {"query": primary_query, "compare_sources": True, "sub_queries": queries},
        user_id=user_id,
        conversation_id=conversation_id,
        approved_by=approved_by,
        existing_invocation_id=existing_invocation_id,
        tokenize_fn=tokenize_fn,
        extract_terms_fn=extract_terms_fn,
        query_kg_fn=query_kg_fn,
        calc_fn=calc_fn,
    )

    inv_id = (search_res.get("invocation") or {}).get("id")
    if inv_id and mission_id:
        with conn:
            conn.execute(
                "UPDATE tool_invocations SET mission_id=?, mission_node_id=? WHERE id=?",
                (mission_id, node_id, inv_id),
            )

    r_status = str(search_res.get("status") or "FAILED")
    if r_status == "PENDING_APPROVAL":
        return {
            "ok": True,
            "status": "PENDING_APPROVAL",
            "verdict": "PENDING_APPROVAL",
            "invocation_id": inv_id,
            "tool_id": "web_search",
            "queries": queries,
            "claims": [],
            "injection_warnings": [],
            "analysis": {},
        }

    if r_status != "COMPLETED":
        return {
            "ok": False,
            "status": r_status,
            "verdict": "BLOCKED" if r_status == "BLOCKED" else "INSUFFICIENT_EVIDENCE",
            "invocation_id": inv_id,
            "tool_id": "web_search",
            "queries": queries,
            "error": search_res.get("error") or (search_res.get("raw_output") or {}).get("error") or f"web_search {r_status}",
            "claims": [],
            "injection_warnings": [],
            "analysis": search_res.get("analysis") or {},
        }

    analysis = dict(search_res.get("analysis") or {})
    raw_output = dict(search_res.get("raw_output") or {})
    results_list = list(raw_output.get("results") or [])
    q_terms = extract_terms_fn(primary_query)

    injection_warnings: list[str] = []
    all_claims: list[dict[str, Any]] = []
    claims_by_url: dict[str, list[dict[str, Any]]] = {}
    doc_fetch_info: dict[str, Any] = {"attempted": False, "status": "NOT_NEEDED"}

    for item in results_list:
        url = str(item.get("url") or "").strip()
        prov = str(item.get("provider") or "web")
        snippet = str(item.get("snippet") or "")
        sanitized_snip, warns = sanitize_untrusted_text(snippet)
        injection_warnings.extend(warns)
        item_claims = extract_structured_claims(sanitized_snip, q_terms, source_url=url, provider=prov, max_claims=3)
        if item_claims:
            all_claims.extend(item_claims)
            claims_by_url.setdefault(url, []).extend(item_claims)

    # Attempt real full-document fetch if doc_fetch is enabled + auto (or explicitly approved), never bypassing P5 Gate
    doc_tool = conn.execute("SELECT enabled, permission_mode FROM external_tools WHERE id='doc_fetch'").fetchone()
    first_url = next((str(r.get("url") or "").strip() for r in results_list if str(r.get("url") or "").startswith("https://")), "")
    if first_url and doc_tool and doc_tool["enabled"] and doc_tool["permission_mode"] != "disabled":
        if doc_tool["permission_mode"] == "auto" or approved_by:
            doc_fetch_info["attempted"] = True
            doc_res = invoke_tool_governed(
                conn,
                data_dir,
                "doc_fetch",
                {"url": first_url},
                user_id=user_id,
                conversation_id=conversation_id,
                approved_by=approved_by if doc_tool["permission_mode"] == "approval_required" else None,
                tokenize_fn=tokenize_fn,
                extract_terms_fn=extract_terms_fn,
                query_kg_fn=query_kg_fn,
                calc_fn=calc_fn,
            )
            doc_inv_id = (doc_res.get("invocation") or {}).get("id")
            if doc_inv_id and mission_id:
                with conn:
                    conn.execute(
                        "UPDATE tool_invocations SET mission_id=?, mission_node_id=? WHERE id=?",
                        (mission_id, node_id, doc_inv_id),
                    )
            doc_fetch_info["status"] = doc_res.get("status", "FAILED")
            doc_fetch_info["url"] = first_url
            if doc_res.get("status") == "COMPLETED":
                doc_raw = doc_res.get("raw_output") or {}
                excerpt = str(doc_raw.get("excerpt") or "")
                sanitized_doc, doc_warns = sanitize_untrusted_text(excerpt)
                injection_warnings.extend(doc_warns)
                doc_claims = extract_structured_claims(
                    sanitized_doc,
                    q_terms,
                    source_url=first_url,
                    provider=str(doc_raw.get("provider") or "doc_fetch"),
                    max_claims=4,
                )
                all_claims.extend(doc_claims)
                claims_by_url.setdefault(first_url, []).extend(doc_claims)
                # Re-analyze including document excerpt for deeper conflict/freshness check
                doc_analysis = analyze_tool_result(
                    conn,
                    "doc_fetch",
                    doc_raw,
                    tokenize_fn,
                    extract_terms_fn,
                    query_kg_fn,
                )
                if doc_analysis.get("trust_grade") in {"CONFLICTING_SOURCES", "STALE", "BLOCKED"}:
                    analysis["trust_grade"] = doc_analysis["trust_grade"]
                    analysis["conflicts"] = list(analysis.get("conflicts") or []) + list(doc_analysis.get("conflicts") or [])
                    analysis["limitations"] = list(analysis.get("limitations") or []) + list(doc_analysis.get("limitations") or [])
        else:
            doc_fetch_info = {
                "attempted": False,
                "status": "APPROVAL_REQUIRED_FOR_DEEP_READ",
                "url": first_url,
            }

    t_grade = str(analysis.get("trust_grade") or "INSUFFICIENT_EVIDENCE")
    # Preserve CONFLICTING_SOURCES -> NOT_LEARNED mapping
    verdict_map = {
        "CORROBORATED_MULTI_SOURCE": "VERIFIED",
        "UNCORROBORATED_SINGLE_SOURCE": "SINGLE_SOURCE_UNVERIFIED",
        "CONFLICTING_SOURCES": "CONFLICTING_SOURCES",
        "STALE": "STALE",
        "INSUFFICIENT_EVIDENCE": "INSUFFICIENT_EVIDENCE",
        "BLOCKED": "BLOCKED",
        "UNVERIFIED": "INSUFFICIENT_EVIDENCE",
    }
    verdict = verdict_map.get(t_grade, "INSUFFICIENT_EVIDENCE")

    evidence_items = list(analysis.get("evidence_items") or [])
    if mission_id and evidence_items:
        with conn:
            _persist_mission_evidence(conn, mission_id, node_id, evidence_items, t_grade, claims_by_url)

    return {
        "ok": True,
        "status": "COMPLETED",
        "verdict": verdict,
        "trust_grade": t_grade,
        "invocation_id": inv_id,
        "tool_id": "web_search",
        "queries": queries,
        "sub_queries_executed": raw_output.get("sub_queries_executed", queries[:1]),
        "doc_fetch": doc_fetch_info,
        "claims": all_claims[:10],
        "injection_warnings": injection_warnings[:5],
        "analysis": analysis,
    }
