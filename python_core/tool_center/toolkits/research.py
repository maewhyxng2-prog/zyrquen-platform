"""
Research Toolkit for ZYRQUEN Tool Center.
Binds SSRF URL validation, multi-source ResearchVerifier, and P5-gated web_search / doc_fetch.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from typing import Any
from urllib.parse import urlparse

from apps.core.intelligence.memory_layers import VerifiedKnowledgeStore
from apps.core.intelligence.research import ResearchSource, ResearchVerifier, validate_research_url
import memory_learning as ml
import tools_engine as te
import zyrquen_core as zc

from ..contracts import CapabilitySpec, ToolkitManifest


def _is_blocked_ai_host(host: str) -> bool:
    h = (host or "").strip().lower()
    return any(h == b or h.endswith(f".{b}") for b in te.BLOCKED_EXTERNAL_LLM_HOSTS)


def _handle_url_validate(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    url = str(payload.get("url") or "").strip()
    res = validate_research_url(url)
    host = str(res.get("host") or (urlparse(url).hostname or "")).strip().lower()
    ai_blocked = _is_blocked_ai_host(host)
    scheme_ok = str(res.get("scheme") or "").lower() == "https"
    policy_ok = bool(res.get("valid")) and scheme_ok and not ai_blocked
    err_reason = None
    if ai_blocked:
        err_reason = f"ถูกบล็อกตามนโยบาย ZYRQUEN: ไม่อนุญาตให้เชื่อมต่อโฮสต์โมเดล AI ภายนอก ({host})"
    elif not res.get("valid"):
        err_reason = str(res.get("reason"))
    elif not scheme_ok:
        err_reason = "อนุญาตเฉพาะโปรโตคอล https:// เท่านั้น"

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "url": url,
            "safe": policy_ok,
            "research_validation": res,
            "network_policy_ok": policy_ok,
            "error": err_reason,
        },
        "summary": f"ตรวจสอบ URL {'ปลอดภัยพร้อมใช้งาน' if policy_ok else 'ไม่ผ่านนโยบายความปลอดภัย'}: {url}",
    }


def _handle_evidence_corroborate(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    topic = str(payload.get("topic") or "").strip()
    raw_sources = payload.get("sources") or []
    if not topic or not isinstance(raw_sources, list):
        return {
            "ok": False,
            "status": "FAILED",
            "error": "topic and sources list are required.",
            "output": {},
        }

    now_iso = datetime.now(timezone.utc).isoformat()
    sources: list[ResearchSource] = []
    for idx, item in enumerate(raw_sources, start=1):
        if not isinstance(item, dict):
            continue
        ts_raw = str(item.get("retrieved_at") or "").strip() or now_iso
        url_val = str(item.get("url") or item.get("source_url") or "")
        provider_val = str(item.get("provider") or item.get("source_authority") or "").strip() or None
        source_id = str(item.get("source_id") or provider_val or f"src-{idx}")
        claim_val = str(item.get("claim") or item.get("claim_text") or item.get("raw_text") or "")
        sources.append(
            ResearchSource(
                source_id=source_id,
                source_url=url_val,
                retrieved_at=ts_raw,
                claim_text=claim_val,
                polarity=str(item.get("polarity") or "affirms"),
                canonical_value=item.get("canonical_value"),
                credibility_score=float(item.get("credibility_score", 0.85)),
                source_authority=provider_val,
            )
        )

    verifier = ResearchVerifier()
    kg_store = VerifiedKnowledgeStore()
    verdict = verifier.verify_claim(topic=topic, sources=sources, knowledge_store=kg_store)
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "topic": topic,
            "verdict": verdict.status,
            "learnable": verdict.learnable,
            "verified_fact": verdict.verified_claim,
            "sources_used": list(verdict.sources_used),
            "rejected_reasons": [f"{k}: {v}" for k, v in verdict.rejected_sources.items()],
            "rejected_sources": dict(verdict.rejected_sources),
            "injection_detected": verdict.injection_detected,
            "written_to_verified_memory": verdict.learnable,
        },
        "summary": f"ผลตรวจสอบหลักฐานหัวข้อ '{topic}': {verdict.status} (แหล่งที่ผ่าน {len(verdict.sources_used)})",
    }


def _handle_web_search(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    conn = ctx.get("conn")
    if conn is None:
        return {"ok": False, "status": "BLOCKED", "error": "Database connection unavailable.", "output": {}}
    res = te.invoke_tool_governed(
        conn,
        ctx["data_dir"],
        "web_search",
        {"query": str(payload.get("query") or "").strip()},
        user_id=ctx["user_id"],
        conversation_id=ctx.get("conversation_id"),
        approved_by=ctx.get("approved_by"),
        tokenize_fn=zc.tokenize,
        extract_terms_fn=zc.extract_query_terms,
        query_kg_fn=zc.query_knowledge_graph,
        calc_fn=zc._calc_any_for_tool,
    )
    return {
        "ok": bool(res.get("ok")),
        "status": str(res.get("status") or "FAILED"),
        "output": {
            "tool_invocation": res.get("invocation"),
            "analysis": res.get("analysis"),
            "tool_output": res.get("raw_output") or res.get("output"),
        },
        "summary": str((res.get("analysis") or {}).get("summary") or f"web_search status: {res.get('status')}"),
        "error": res.get("error"),
    }


def _handle_doc_fetch(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    conn = ctx.get("conn")
    if conn is None:
        return {"ok": False, "status": "BLOCKED", "error": "Database connection unavailable.", "output": {}}
    res = te.invoke_tool_governed(
        conn,
        ctx["data_dir"],
        "doc_fetch",
        {"url": str(payload.get("url") or "").strip()},
        user_id=ctx["user_id"],
        conversation_id=ctx.get("conversation_id"),
        approved_by=ctx.get("approved_by"),
        tokenize_fn=zc.tokenize,
        extract_terms_fn=zc.extract_query_terms,
        query_kg_fn=zc.query_knowledge_graph,
        calc_fn=zc._calc_any_for_tool,
    )
    return {
        "ok": bool(res.get("ok")),
        "status": str(res.get("status") or "FAILED"),
        "output": {
            "tool_invocation": res.get("invocation"),
            "analysis": res.get("analysis"),
            "tool_output": res.get("raw_output") or res.get("output"),
        },
        "summary": str((res.get("analysis") or {}).get("summary") or f"doc_fetch status: {res.get('status')}"),
        "error": res.get("error"),
    }


def _handle_knowledge_retrieve(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    target_entity = str(payload.get("target_entity") or "").strip()
    conn = ctx.get("conn")
    if conn is None:
        return {"ok": False, "status": "BLOCKED", "error": "Database connection unavailable.", "output": {}}
    if not query:
        return {"ok": False, "status": "FAILED", "error": "query is required.", "output": {}}

    hits = zc.query_knowledge_graph(conn, query)
    path_info = None
    if target_entity:
        path_info = zc.find_graph_path(conn, query, target_entity, max_depth=4)

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "query": query,
            "matches": hits,
            "match_count": len(hits),
            "graph_path": path_info,
        },
        "summary": f"สืบค้นกราฟความรู้ '{query}': พบ {len(hits)} ความสัมพันธ์",
    }


_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
)


def _parse_iso_dt(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _handle_source_provenance(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    raw_sources = payload.get("sources") or []
    if not isinstance(raw_sources, list) or not raw_sources:
        return {"ok": False, "status": "FAILED", "error": "sources list is required.", "output": {}}

    audited: list[dict[str, Any]] = []
    rejected_count = 0
    for idx, src in enumerate(raw_sources, start=1):
        if not isinstance(src, dict):
            continue
        url = str(src.get("url") or src.get("source_url") or "").strip()
        text = str(src.get("claim") or src.get("raw_text") or "").strip()
        ts = str(src.get("retrieved_at") or "").strip()
        authority = str(src.get("provider") or src.get("source_authority") or "").strip()

        url_check = validate_research_url(url) if url else {"valid": False, "reason": "missing_url", "host": ""}
        host = str(url_check.get("host") or (urlparse(url).hostname or "")).lower()
        ai_blocked = _is_blocked_ai_host(host)
        scheme_ok = str(url_check.get("scheme") or "").lower() == "https"
        has_injection = any(pat.search(text) for pat in _INJECTION_PATTERNS)
        parsed_ts = _parse_iso_dt(ts)
        content_sha = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""

        if has_injection or ai_blocked or (url and (not url_check.get("valid") or not scheme_ok)):
            status = "REJECTED"
            rejected_count += 1
        elif url and authority and parsed_ts and text:
            status = "FACT_CANDIDATE"
        elif text and (url or authority):
            status = "HYPOTHESIS"
        else:
            status = "UNVERIFIED"

        audited.append({
            "index": idx,
            "url": url,
            "host": host,
            "authority": authority or None,
            "has_valid_timestamp": parsed_ts is not None,
            "injection_flagged": has_injection,
            "ai_host_blocked": ai_blocked,
            "content_sha256": content_sha,
            "epistemic_status": status,
        })

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "source_count": len(audited),
            "rejected_count": rejected_count,
            "fact_candidate_count": sum(1 for a in audited if a["epistemic_status"] == "FACT_CANDIDATE"),
            "audited_sources": audited,
        },
        "summary": f"ตรวจสอบ Provenance {len(audited)} แหล่ง: ผ่านเกณฑ์ข้อเท็จจริง {sum(1 for a in audited if a['epistemic_status'] == 'FACT_CANDIDATE')}, ปฏิเสธ {rejected_count}",
    }


def _handle_claim_verification(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    claim = str(payload.get("claim") or "").strip()
    raw_sources = payload.get("sources") or []
    if not claim:
        return {"ok": False, "status": "FAILED", "error": "claim is required.", "output": {}}

    conn = ctx.get("conn")
    kg_hits = zc.query_knowledge_graph(conn, claim) if conn is not None else []

    claim_tokens = set(re.findall(r"[A-Za-z0-9_\u0E00-\u0E7F]{2,}", claim.lower()))
    supports = 0
    contradicts = 0
    rejected = 0
    used_sources: list[str] = []

    for item in raw_sources if isinstance(raw_sources, list) else []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        txt = str(item.get("claim") or item.get("raw_text") or "").strip()
        polarity = str(item.get("polarity") or "affirms").lower()
        if any(p.search(txt) for p in _INJECTION_PATTERNS):
            rejected += 1
            continue
        if url:
            vc = validate_research_url(url)
            if not vc.get("valid") or _is_blocked_ai_host(str(vc.get("host") or "")):
                rejected += 1
                continue
        txt_tokens = set(re.findall(r"[A-Za-z0-9_\u0E00-\u0E7F]{2,}", txt.lower()))
        overlap = len(claim_tokens & txt_tokens) / max(1, len(claim_tokens))
        if overlap < 0.2:
            continue
        used_sources.append(str(item.get("provider") or url or "source"))
        if polarity in {"contradicts", "refutes", "denies"}:
            contradicts += 1
        else:
            supports += 1

    if contradicts > 0 and supports > 0:
        classification = "CONTRADICTED"
    elif contradicts > 0 and supports == 0:
        classification = "CONTRADICTED"
    elif supports >= 2 or (supports >= 1 and len(kg_hits) >= 1):
        classification = "VERIFIED_FACT"
    elif supports == 1 or len(kg_hits) >= 1:
        classification = "HYPOTHESIS"
    else:
        classification = "UNVERIFIED"

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "claim": claim,
            "classification": classification,
            "supporting_sources": supports,
            "contradicting_sources": contradicts,
            "kg_matches_count": len(kg_hits),
            "rejected_sources": rejected,
            "sources_used": used_sources,
        },
        "summary": f"ผลการทวนสอบข้ออ้าง: {classification} (สนับสนุน={supports}, ขัดแย้ง={contradicts}, KG={len(kg_hits)})",
    }


def _handle_temporal_analysis(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    events = payload.get("events") or []
    max_age_days = float(payload.get("max_age_days") or 365.0)
    ref_dt = _parse_iso_dt(payload.get("reference_time")) or datetime.now(timezone.utc)
    if not isinstance(events, list) or not events:
        return {"ok": False, "status": "FAILED", "error": "events array is required.", "output": {}}

    parsed_events: list[dict[str, Any]] = []
    invalid_timestamps: list[dict[str, Any]] = []
    for idx, ev in enumerate(events):
        if not isinstance(ev, dict):
            continue
        ts_str = str(ev.get("timestamp") or ev.get("retrieved_at") or "").strip()
        dt = _parse_iso_dt(ts_str)
        if dt is None:
            invalid_timestamps.append({"index": idx, "timestamp": ts_str})
            continue
        age_days = (ref_dt - dt).total_seconds() / 86400.0
        parsed_events.append({
            "index": idx,
            "label": str(ev.get("label") or ev.get("id") or f"ev-{idx + 1}"),
            "timestamp": dt.isoformat(),
            "age_days": round(age_days, 2),
            "stale": age_days > max_age_days,
            "future_dated": age_days < -0.01,
            "_dt": dt,
        })

    chronological_ok = all(
        parsed_events[i]["_dt"] <= parsed_events[i + 1]["_dt"]
        for i in range(len(parsed_events) - 1)
    )
    out_events = [{k: v for k, v in e.items() if k != "_dt"} for e in parsed_events]
    stale_count = sum(1 for e in out_events if e["stale"])
    span_days = 0.0
    if len(parsed_events) >= 2:
        dts = [e["_dt"] for e in parsed_events]
        span_days = round((max(dts) - min(dts)).total_seconds() / 86400.0, 2)

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "event_count": len(events),
            "valid_timestamp_count": len(out_events),
            "invalid_timestamps": invalid_timestamps,
            "chronological_order": chronological_ok,
            "stale_count": stale_count,
            "span_days": span_days,
            "events": out_events,
        },
        "summary": f"วิเคราะห์ลำดับเวลา {len(out_events)} เหตุการณ์: เรียงลำดับ={chronological_ok}, ล้าสมัย={stale_count}",
    }


def _handle_knowledge_gap_detection(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    conn = ctx.get("conn")
    topics = [str(t).strip() for t in (payload.get("topics") or []) if str(t).strip()]
    missing_topics: list[dict[str, Any]] = []
    sparse_topics: list[dict[str, Any]] = []

    if conn is not None:
        for topic in topics:
            hits = zc.query_knowledge_graph(conn, topic)
            if not hits:
                missing_topics.append({"topic": topic, "reason": "no_knowledge_graph_triples"})
            elif len(hits) < 2:
                sparse_topics.append({"topic": topic, "triple_count": len(hits), "reason": "single_relation_only"})
        system_gaps = ml.detect_capability_gaps(conn)
    else:
        missing_topics = [{"topic": t, "reason": "db_unavailable_for_kg_check"} for t in topics]
        system_gaps = []

    gaps_detected = bool(missing_topics or sparse_topics or system_gaps)
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "gaps_detected": gaps_detected,
            "missing_topics": missing_topics,
            "sparse_topics": sparse_topics,
            "system_capability_gaps": system_gaps[:20],
            "total_gaps": len(missing_topics) + len(sparse_topics) + len(system_gaps),
        },
        "summary": f"ตรวจช่องว่างความรู้: ไม่พบใน KG {len(missing_topics)}, ข้อมูลบาง {len(sparse_topics)}, ช่องว่างระบบ {len(system_gaps)}",
    }


def _handle_contradiction_resolution(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    topic = str(payload.get("topic") or "").strip()
    claims = payload.get("claims") or []
    if not topic or not isinstance(claims, list) or len(claims) < 2:
        return {"ok": False, "status": "FAILED", "error": "topic and at least 2 claims are required.", "output": {}}

    grouped: dict[str, dict[str, Any]] = {}
    for c in claims:
        if not isinstance(c, dict):
            continue
        pos = str(c.get("canonical_value") or c.get("stance") or c.get("claim") or "").strip()
        if not pos:
            continue
        cred = max(0.0, min(1.0, float(c.get("credibility_score", 0.5))))
        bucket = grouped.setdefault(pos, {"value": pos, "count": 0, "total_weight": 0.0, "sources": []})
        bucket["count"] += 1
        bucket["total_weight"] = round(bucket["total_weight"] + cred, 4)
        bucket["sources"].append(str(c.get("source") or c.get("provider") or "unknown"))

    ranked = sorted(grouped.values(), key=lambda x: (-x["total_weight"], -x["count"], x["value"]))
    if len(ranked) <= 1:
        status = "NO_CONFLICT"
        winner = ranked[0]["value"] if ranked else None
    elif abs(ranked[0]["total_weight"] - ranked[1]["total_weight"]) < 0.25:
        status = "UNRESOLVED_TIE"
        winner = None
    else:
        status = "EVIDENCE_WEIGHTED_PREFERENCE"
        winner = ranked[0]["value"]

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "topic": topic,
            "resolution_status": status,
            "preferred_claim": winner,
            "positions": ranked,
            "conflict_count": max(0, len(ranked) - 1),
        },
        "summary": f"วิเคราะห์ความขัดแย้ง '{topic}': {status}" + (f" (น้ำหนักหลักฐานนำ: {winner})" if winner else ""),
    }


def register_research_toolkit(registry: Any) -> None:
    manifest = ToolkitManifest(
        id="research",
        name="Research Toolkit",
        thai_name="ชุดเครื่องมือวิจัยและตรวจสอบหลักฐาน",
        version="1.2.0",
        description="ค้นคืนกราฟความรู้ ตรวจสอบ URL/Provenance, ทวนสอบข้ออ้าง, วิเคราะห์เวลา, ช่องว่างความรู้ และแก้ความขัดแย้งหลักฐาน",
        category="research",
        dependencies=("apps.core.intelligence.research", "python_core.tools_engine", "python_core.zyrquen_core"),
        default_permission="auto",
        lifecycle_status="READY",
        bound_modules=(
            "apps/core/intelligence/research.py",
            "python_core/research_pipeline.py",
            "python_core/tools_engine.py",
            "python_core/zyrquen_core.py",
        ),
        documentation="แยกส่วนค้นความรู้และวิเคราะห์หลักฐานออฟไลน์ออกจากคำขอเครือข่ายภายนอกซึ่งต้องผ่าน P5 Approval Gate",
    )

    specs = [
        (
            CapabilitySpec(
                id="research.knowledge_retrieve",
                toolkit_id="research",
                name="ค้นคืนและเชื่อมโยงกราฟความรู้ภายใน (Knowledge Retrieval)",
                version="1.0.0",
                description="ค้นหาความสัมพันธ์ใน SQLite Knowledge Graph (รวมอนุมานหลายช่วง Multi-Hop BFS)",
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string"},
                        "target_entity": {"type": "string"},
                    },
                },
                output_schema={"type": "object", "required": ["query", "matches", "match_count"]},
                dependencies=("python_core.zyrquen_core",),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/zyrquen_core.py",),
                documentation="ค้นหาข้อเท็จจริงและเส้นทางเชื่อมโยงระหว่างโหนดในกราฟความรู้",
                example_input={"query": "ZYRQUEN"},
                keywords=("knowledge", "graph", "kg", "retrieve", "ความรู้", "ค้นคืน", "วิจัย"),
            ),
            _handle_knowledge_retrieve,
        ),
        (
            CapabilitySpec(
                id="research.url_validate",
                toolkit_id="research",
                name="ตรวจสอบความปลอดภัย URL (SSRF & AI-Host Guard)",
                version="1.0.0",
                description="ตรวจว่า URL เป็นสาธารณะที่ปลอดภัย ไม่ใช่เครือข่ายภายใน/localhost/placeholder หรือโฮสต์ LLM ภายนอก",
                input_schema={
                    "type": "object",
                    "required": ["url"],
                    "properties": {"url": {"type": "string"}},
                },
                output_schema={"type": "object", "required": ["safe", "url"]},
                dependencies=("apps.core.intelligence.research", "python_core.tools_engine"),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("apps/core/intelligence/research.py", "python_core/tools_engine.py"),
                documentation="ตรวจสอบ URL ก่อนดึงเอกสารเพื่อป้องกัน SSRF และโฮสต์ต้องห้าม",
                example_input={"url": "https://en.wikipedia.org/wiki/SQLite"},
                keywords=("url", "ssrf", "research", "link", "วิจัย", "ตรวจสอบลิงก์"),
            ),
            _handle_url_validate,
        ),
        (
            CapabilitySpec(
                id="research.evidence_corroborate",
                toolkit_id="research",
                name="ตรวจสอบและสอบทานหลักฐานหลายแหล่ง",
                version="1.0.0",
                description="ตรวจ Prompt Injection, ความขัดแย้งระหว่างแหล่ง, และความเก่าของข้อมูลโดยไม่ปลอมผล VERIFIED",
                input_schema={
                    "type": "object",
                    "required": ["topic", "sources"],
                    "properties": {
                        "topic": {"type": "string"},
                        "sources": {"type": "array"},
                    },
                },
                output_schema={"type": "object", "required": ["verdict", "sources_used", "rejected_reasons"]},
                dependencies=("apps.core.intelligence.research", "apps.core.intelligence.memory_layers"),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("apps/core/intelligence/research.py", "apps/core/intelligence/memory_layers.py"),
                documentation="ส่ง topic และรายการ sources [{url, provider, claim, raw_text}] เพื่อประเมินความน่าเชื่อถือ",
                example_input={
                    "topic": "SQLite WAL",
                    "sources": [
                        {
                            "url": "https://www.sqlite.org/wal.html",
                            "provider": "sqlite.org",
                            "claim": "WAL allows concurrent readers and one writer.",
                        },
                        {
                            "url": "https://en.wikipedia.org/wiki/SQLite",
                            "provider": "wikipedia",
                            "claim": "WAL allows concurrent readers and one writer.",
                        },
                    ],
                },
                keywords=("evidence", "corroborate", "research", "verify", "หลักฐาน", "วิจัย", "ความน่าเชื่อถือ"),
            ),
            _handle_evidence_corroborate,
        ),
        (
            CapabilitySpec(
                id="research.web_search",
                toolkit_id="research",
                name="สืบค้นเว็บหลายแหล่ง (P5 Gate)",
                version="1.0.0",
                description="สืบค้น Wikipedia และ DuckDuckGo Instant API ผ่าน HTTPS ภายใต้การอนุมัติ P5 Approval Gate",
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}},
                },
                output_schema={"type": "object", "required": []},
                dependencies=("python_core.tools_engine",),
                permission_mode="approval_required",
                risk_tier="external_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tools_engine.py",),
                documentation="คำขอจากผู้ใช้ทั่วไปจะเข้าสู่สถานะ PENDING_APPROVAL จนกว่าผู้ดูแลจะอนุมัติ",
                example_input={"query": "SQLite WAL"},
                keywords=("search", "web", "research", "สืบค้น", "วิจัย"),
            ),
            _handle_web_search,
        ),
        (
            CapabilitySpec(
                id="research.doc_fetch",
                toolkit_id="research",
                name="อ่านเอกสารเว็บสาธารณะ (P5 Gate)",
                version="1.0.0",
                description="ดึงเนื้อหาและโครงสร้างหัวข้อจากเอกสาร HTTPS ที่ผ่าน Allowlist ภายใต้การอนุมัติ P5 Approval Gate",
                input_schema={
                    "type": "object",
                    "required": ["url"],
                    "properties": {"url": {"type": "string"}},
                },
                output_schema={"type": "object", "required": []},
                dependencies=("python_core.tools_engine",),
                permission_mode="approval_required",
                risk_tier="external_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tools_engine.py",),
                documentation="จำกัดเฉพาะโดเมนใน Allowlist และบล็อกเครือข่ายภายใน",
                example_input={"url": "https://en.wikipedia.org/wiki/SQLite"},
                keywords=("fetch", "document", "url", "วิจัย", "อ่านเว็บ"),
            ),
            _handle_doc_fetch,
        ),
        (
            CapabilitySpec(
                id="research.source_provenance",
                toolkit_id="research",
                name="ตรวจสอบแหล่งที่มาและความน่าเชื่อถือเอกสาร (Source Provenance)",
                version="1.0.0",
                description="ตรวจ URL allowlist, timestamp, SHA-256 fingerprint, Prompt Injection และจำแนก Fact Candidate vs Hypothesis",
                input_schema={
                    "type": "object",
                    "required": ["sources"],
                    "properties": {"sources": {"type": "array"}},
                },
                output_schema={"type": "object", "required": ["source_count", "rejected_count", "audited_sources"]},
                dependencies=("apps.core.intelligence.research",),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/research.py",),
                documentation="ประเมินความน่าเชื่อถือและแยกแหล่งที่ถูกปฏิเสธออกจากแหล่งที่ตรวจสอบได้",
                example_input={"sources": [{"url": "https://www.sqlite.org/wal.html", "provider": "sqlite.org", "retrieved_at": "2026-11-20T00:00:00Z", "claim": "WAL mode enabled"}]},
                keywords=("provenance", "source", "authority", "citation", "แหล่งที่มา"),
            ),
            _handle_source_provenance,
        ),
        (
            CapabilitySpec(
                id="research.claim_verification",
                toolkit_id="research",
                name="ทวนสอบข้ออ้างเทียบ Knowledge Graph และหลักฐาน (Claim Verification)",
                version="1.0.0",
                description="จำแนกข้ออ้างเป็น VERIFIED_FACT, HYPOTHESIS, UNVERIFIED หรือ CONTRADICTED จากหลักฐานและ KG จริง",
                input_schema={
                    "type": "object",
                    "required": ["claim"],
                    "properties": {
                        "claim": {"type": "string"},
                        "sources": {"type": "array"},
                    },
                },
                output_schema={"type": "object", "required": ["claim", "classification", "supporting_sources", "contradicting_sources"]},
                dependencies=("apps.core.intelligence.research", "python_core.zyrquen_core"),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/research.py",),
                documentation="ไม่ประกาศ VERIFIED_FACT หากมีแหล่งสนับสนุนน้อยกว่าเกณฑ์หรือมีความขัดแย้ง",
                example_input={"claim": "SQLite WAL allows concurrent readers", "sources": [{"url": "https://www.sqlite.org/wal.html", "claim": "SQLite WAL allows concurrent readers"}]},
                keywords=("claim", "verify", "fact", "hypothesis", "ทวนสอบข้ออ้าง"),
            ),
            _handle_claim_verification,
        ),
        (
            CapabilitySpec(
                id="research.temporal_analysis",
                toolkit_id="research",
                name="วิเคราะห์ลำดับเวลาและความสดใหม่ข้อมูล (Temporal Analysis)",
                version="1.0.0",
                description="ตรวจลำดับเหตุการณ์ตามเวลา ISO-8601 หาความคลาดเคลื่อน ความล้าสมัย และช่วงเวลาทั้งหมด",
                input_schema={
                    "type": "object",
                    "required": ["events"],
                    "properties": {
                        "events": {"type": "array"},
                        "max_age_days": {"type": "number"},
                        "reference_time": {"type": "string"},
                    },
                },
                output_schema={"type": "object", "required": ["valid_timestamp_count", "chronological_order", "stale_count"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/research.py",),
                documentation="ตรวจสอบความเรียงตามเวลาและความเก่าของเหตุการณ์/แหล่งข้อมูล",
                example_input={"events": [{"label": "v1", "timestamp": "2026-11-01T00:00:00Z"}, {"label": "v2", "timestamp": "2026-11-20T00:00:00Z"}]},
                keywords=("temporal", "timeline", "chronological", "freshness", "ลำดับเวลา"),
            ),
            _handle_temporal_analysis,
        ),
        (
            CapabilitySpec(
                id="research.knowledge_gap_detection",
                toolkit_id="research",
                name="ตรวจจับช่องว่างความรู้และสมรรถนะระบบ (Knowledge Gap Detection)",
                version="1.0.0",
                description="ตรวจสอบหัวข้อที่ยังไม่มีความสัมพันธ์หรือมีข้อมูลบางใน Knowledge Graph ร่วมกับ capability gaps",
                input_schema={
                    "type": "object",
                    "properties": {"topics": {"type": "array"}},
                },
                output_schema={"type": "object", "required": ["gaps_detected", "missing_topics", "total_gaps"]},
                dependencies=("python_core.memory_learning", "python_core.zyrquen_core"),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/memory_learning.py",),
                documentation="ระบุช่องว่างของข้อมูลในกราฟความรู้โดยไม่แต่งเติมคำตอบ",
                example_input={"topics": ["ZYRQUEN", "quantum_unseen_topic"]},
                keywords=("gap", "knowledge", "missing", "ช่องว่างความรู้"),
            ),
            _handle_knowledge_gap_detection,
        ),
        (
            CapabilitySpec(
                id="research.contradiction_resolution",
                toolkit_id="research",
                name="วิเคราะห์และจำแนกข้อขัดแย้งระหว่างหลักฐาน (Contradiction Resolution)",
                version="1.0.0",
                description="ถ่วงน้ำหนักจุดยืนที่ขัดแย้งตาม credibility และจำนวนแหล่ง หรือรายงาน UNRESOLVED_TIE อย่างซื่อสัตย์",
                input_schema={
                    "type": "object",
                    "required": ["topic", "claims"],
                    "properties": {
                        "topic": {"type": "string"},
                        "claims": {"type": "array"},
                    },
                },
                output_schema={"type": "object", "required": ["topic", "resolution_status", "positions", "conflict_count"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/research.py",),
                documentation="เปรียบเทียบหลักฐานที่ขัดแย้งกันโดยไม่เดาผู้ชนะเมื่อน้ำหนักเท่ากัน",
                example_input={"topic": "default_timeout", "claims": [{"canonical_value": "3s", "credibility_score": 0.9, "source": "docs"}, {"canonical_value": "10s", "credibility_score": 0.4, "source": "blog"}]},
                keywords=("contradiction", "conflict", "resolve", "evidence", "ข้อขัดแย้ง"),
            ),
            _handle_contradiction_resolution,
        ),
    ]

    registry.register_toolkit(manifest, specs)
