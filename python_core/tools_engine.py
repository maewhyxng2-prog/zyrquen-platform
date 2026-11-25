#!/usr/bin/env python3
"""
ZYRQUEN Native-First + Tool-Augmented Intelligence Engine
---------------------------------------------------------
P1: Tool Execution Adapter with explicit contracts, risk tiers, & input validation
P2: Real Multi-Source Public Web Search (MediaWiki + DuckDuckGo Instant API) & Document Reader
P3: Structured Evidence Verification (untrusted web tagging, multi-source corroboration,
    knowledge-graph cross-checking, and honest data-limitation reporting inside Native Core)
P4: Local Deterministic Compute (AST/Algebra/Stats) & Sandboxed Workspace File Manager
P5: Permission Enforcement, Approval Gate, & Unified Audit Trail
"""

from datetime import datetime, timezone
from html.parser import HTMLParser
import ast
import collections
import csv
import io
import ipaddress
import json
import re
import socket
import sqlite3
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Callable


BLOCKED_EXTERNAL_LLM_HOSTS = {
    "api.openai.com",
    "openai.com",
    "api.anthropic.com",
    "anthropic.com",
    "generativelanguage.googleapis.com",
    "aiplatform.googleapis.com",
    "api.groq.com",
    "api.together.xyz",
    "openrouter.ai",
    "api.cohere.ai",
    "api-inference.huggingface.co",
    "api.mistral.ai",
    "api.perplexity.ai",
}

TOOL_CONTRACTS = {
    "web_search": {
        "risk_tier": "external_readonly",
        "untrusted_source": True,
        "required_fields": ["query"],
    },
    "doc_fetch": {
        "risk_tier": "external_readonly",
        "untrusted_source": True,
        "required_fields": ["url"],
    },
    "calc_ast": {
        "risk_tier": "local_readonly",
        "untrusted_source": False,
        "required_fields": ["expression"],
    },
    "workspace_file_read": {
        "risk_tier": "sandbox_io",
        "untrusted_source": False,
        "required_fields": [],
    },
}


class _VisibleTextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.title_parts: list[str] = []
        self.headings: list[str] = []
        self._in_title = False
        self._in_heading = False
        self._heading_buf: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        t = tag.lower()
        if t in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        elif t == "title":
            self._in_title = True
        elif t in {"h1", "h2", "h3"}:
            self._in_heading = True
            self._heading_buf = []

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in {"script", "style", "noscript", "svg"} and self._skip_depth > 0:
            self._skip_depth -= 1
        elif t == "title":
            self._in_title = False
        elif t in {"h1", "h2", "h3"} and self._in_heading:
            self._in_heading = False
            heading = re.sub(r"\s+", " ", "".join(self._heading_buf)).strip()
            if heading and len(self.headings) < 8:
                self.headings.append(heading[:120])

    def handle_data(self, data: str) -> None:
        cleaned = re.sub(r"\s+", " ", data).strip()
        if not cleaned or self._skip_depth > 0:
            return
        if self._in_title:
            self.title_parts.append(cleaned)
        else:
            if self._in_heading:
                self._heading_buf.append(cleaned)
            self.text_parts.append(cleaned)


def _today_utc() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _log_tool_audit(
    conn: sqlite3.Connection,
    user_id: str,
    action: str,
    target: str,
    outcome: str,
    details: dict | None = None,
) -> None:
    actor_email = "system"
    if user_id:
        row = conn.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
        if row:
            actor_email = row["email"]
    conn.execute(
        """
        INSERT INTO audit_logs (id, actor_id, actor_email, action, target, outcome, details_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            user_id or "system",
            actor_email,
            action,
            target,
            outcome,
            json.dumps(details or {}, ensure_ascii=False),
            _now_iso(),
        ),
    )


def init_tools_schema(conn: sqlite3.Connection, data_dir: Path) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS external_tools (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL CHECK(category IN ('web', 'document', 'compute', 'file')),
            description TEXT NOT NULL,
            endpoint_allowlist_json TEXT NOT NULL DEFAULT '[]',
            permission_mode TEXT NOT NULL CHECK(permission_mode IN ('auto', 'approval_required', 'disabled')),
            enabled INTEGER NOT NULL DEFAULT 1,
            quota_daily INTEGER NOT NULL DEFAULT 50,
            calls_today INTEGER NOT NULL DEFAULT 0,
            last_reset_date TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL DEFAULT 'system',
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tool_invocations (
            id TEXT PRIMARY KEY,
            tool_id TEXT NOT NULL,
            conversation_id TEXT,
            user_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('PENDING_APPROVAL', 'COMPLETED', 'REJECTED', 'FAILED', 'BLOCKED')),
            input_json TEXT NOT NULL,
            output_json TEXT,
            analysis_summary TEXT,
            approved_by TEXT,
            latency_ms REAL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )

    today = _today_utc()
    now = _now_iso()
    default_web_allowlist = json.dumps(["en.wikipedia.org", "th.wikipedia.org", "api.duckduckgo.com"])
    default_tools = [
        (
            "web_search",
            "ค้นหาเว็บหลายแหล่ง (Multi-Source Web Search)",
            "web",
            "สืบค้นและเปรียบเทียบหลักฐานจาก Wikipedia และ DuckDuckGo Instant API ผ่าน HTTPS (ไม่ใช่ LLM ภายนอก)",
            default_web_allowlist,
            "approval_required",
            1,
            50,
            0,
            today,
            "system",
            now,
        ),
        (
            "doc_fetch",
            "อ่านเอกสารเว็บ (Document Reader Tool)",
            "document",
            "ดึงเนื้อหาและโครงสร้างหัวข้อจาก URL สาธารณะที่อนุญาต (HTTPS + ป้องกันเครือข่ายภายใน)",
            json.dumps(["en.wikipedia.org", "th.wikipedia.org", "docs.python.org"]),
            "approval_required",
            1,
            30,
            0,
            today,
            "system",
            now,
        ),
        (
            "calc_ast",
            "คำนวณ AST / สมการ / สถิติ (Compute Tool)",
            "compute",
            "เรียกใช้เครื่องมือคำนวณ AST สมการเชิงเส้น และสถิติภายในเครื่องโดยไม่พึ่งพาภายนอก",
            json.dumps([]),
            "auto",
            1,
            200,
            0,
            today,
            "system",
            now,
        ),
        (
            "workspace_file_read",
            "จัดการและอ่านไฟล์เวิร์กสเปซ (File Sandbox Tool)",
            "file",
            "อ่าน/แสดงรายการไฟล์ข้อความใน workspace_files อย่างปลอดภัย (การเขียนไฟล์ต้องผ่าน Approval Gate)",
            json.dumps([]),
            "auto",
            1,
            100,
            0,
            today,
            "system",
            now,
        ),
    ]
    for row in default_tools:
        conn.execute(
            """
            INSERT OR IGNORE INTO external_tools (
                id, name, category, description, endpoint_allowlist_json,
                permission_mode, enabled, quota_daily, calls_today,
                last_reset_date, created_by, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )

    # Upgrade legacy web_search allowlist cleanly if unmodified from old default
    existing_web = conn.execute(
        "SELECT endpoint_allowlist_json FROM external_tools WHERE id='web_search'"
    ).fetchone()
    if existing_web and existing_web["endpoint_allowlist_json"] == json.dumps(["en.wikipedia.org", "th.wikipedia.org"]):
        conn.execute(
            "UPDATE external_tools SET endpoint_allowlist_json=?, description=?, updated_at=? WHERE id='web_search'",
            (
                default_web_allowlist,
                "สืบค้นและเปรียบเทียบหลักฐานจาก Wikipedia และ DuckDuckGo Instant API ผ่าน HTTPS (ไม่ใช่ LLM ภายนอก)",
                now,
            ),
        )

    ws_dir = data_dir / "workspace_files"
    ws_dir.mkdir(parents=True, exist_ok=True)


def _is_global_public_ip(ip_str: str) -> bool:
    try:
        ip_obj = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return bool(
        ip_obj.is_global
        and not ip_obj.is_private
        and not ip_obj.is_loopback
        and not ip_obj.is_link_local
        and not ip_obj.is_multicast
        and not ip_obj.is_reserved
        and not ip_obj.is_unspecified
    )


def validate_safe_public_url(url: str, allowlist: list[str] | None = None) -> tuple[bool, str]:
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except Exception:
        return False, "รูปแบบ URL ไม่ถูกต้อง"

    if parsed.scheme.lower() != "https":
        return False, "อนุญาตเฉพาะโปรโตคอล https:// เท่านั้น"

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False, "ไม่พบชื่อโฮสต์ใน URL"

    if hostname in {"localhost", "127.0.0.1", "::1"} or hostname.endswith(".local"):
        return False, "ไม่อนุญาตให้เข้าถึงโฮสต์ภายในเครื่อง"

    for blocked in BLOCKED_EXTERNAL_LLM_HOSTS:
        if hostname == blocked or hostname.endswith(f".{blocked}"):
            return False, f"ถูกบล็อกตามนโยบาย ZYRQUEN: ไม่อนุญาตให้เชื่อมต่อโฮสต์โมเดล AI ภายนอก ({hostname})"

    if allowlist:
        allowed_match = False
        for dom in allowlist:
            d = str(dom).strip().lower()
            if not d:
                continue
            if hostname == d or hostname.endswith(f".{d}"):
                allowed_match = True
                break
        if not allowed_match:
            return False, f"โดเมน '{hostname}' ไม่อยู่ใน Endpoint Allowlist ของเครื่องมือนี้"

    try:
        ipaddress.ip_address(hostname)
        if not _is_global_public_ip(hostname):
            return False, "ไม่อนุญาต IP เครือข่ายส่วนตัวหรือ Metadata"
    except ValueError:
        pass

    try:
        addr_info = socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        return False, f"ไม่สามารถแปลงชื่อโดเมน '{hostname}': {exc}"

    if not addr_info:
        return False, f"ไม่พบที่อยู่ IP สำหรับ '{hostname}'"

    for entry in addr_info:
        resolved_ip = entry[4][0]
        if not _is_global_public_ip(resolved_ip):
            return False, f"ปฏิเสธการเชื่อมต่อ: โฮสต์ชี้ไปยัง IP ที่ไม่อนุญาต ({resolved_ip})"

    return True, hostname


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowlist: list[str] | None) -> None:
        super().__init__()
        self.allowlist = allowlist

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        ok, err = validate_safe_public_url(newurl, self.allowlist)
        if not ok:
            raise urllib.error.URLError(f"Redirect blocked: {err}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_http_get(
    url: str,
    allowlist: list[str] | None = None,
    max_bytes: int = 120_000,
    timeout: float = 8.0,
) -> dict:
    ok, msg = validate_safe_public_url(url, allowlist)
    if not ok:
        return {"ok": False, "error": msg}

    opener = urllib.request.build_opener(_SafeRedirectHandler(allowlist))
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ZYRQUEN-ExternalTool/1.1 (+native-first-subordinate)",
            "Accept": "application/json, text/plain, text/html",
        },
        method="GET",
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            status_code = getattr(resp, "status", 200)
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read(max_bytes)
            text = raw.decode("utf-8", errors="replace")
            return {
                "ok": True,
                "url": resp.geturl(),
                "status_code": status_code,
                "content_type": content_type,
                "body": text,
            }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"HTTP {exc.code}: {exc.reason}"}
    except Exception as exc:
        return {"ok": False, "error": f"Network request failed: {exc}"}


def _query_mediawiki_source(wiki_host: str, query: str, allowlist: list[str]) -> tuple[list[dict], str | None]:
    encoded_q = urllib.parse.quote(query)
    api_url = (
        f"https://{wiki_host}/w/api.php?action=query&list=search&srsearch={encoded_q}"
        f"&utf8=1&format=json&srlimit=3"
    )
    res = safe_http_get(api_url, allowlist)
    if not res["ok"]:
        return [], res["error"]
    try:
        data = json.loads(res["body"])
        hits = data.get("query", {}).get("search", [])
    except Exception as exc:
        return [], f"MediaWiki parse failed: {exc}"

    retrieved_at = _now_iso()
    out = []
    for h in hits[:3]:
        title = str(h.get("title", "")).strip()
        snippet = re.sub(r"<[^>]+>", "", str(h.get("snippet", ""))).strip()
        article_url = f"https://{wiki_host}/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
        out.append(
            {
                "provider": wiki_host,
                "source_id": f"{wiki_host}:{title}",
                "title": title,
                "snippet": snippet,
                "url": article_url,
                "retrieved_at": retrieved_at,
                "trust_status": "UNTRUSTED_WEB_EVIDENCE",
            }
        )
    return out, None


def _query_duckduckgo_instant(query: str, allowlist: list[str]) -> tuple[list[dict], str | None]:
    encoded_q = urllib.parse.quote(query)
    api_url = f"https://api.duckduckgo.com/?q={encoded_q}&format=json&no_html=1&skip_disambig=1"
    res = safe_http_get(api_url, allowlist)
    if not res["ok"]:
        return [], res["error"]
    try:
        data = json.loads(res["body"])
    except Exception as exc:
        return [], f"DuckDuckGo parse failed: {exc}"

    retrieved_at = _now_iso()
    items: list[dict] = []
    abstract = str(data.get("AbstractText", "")).strip()
    abstract_url = str(data.get("AbstractURL", "")).strip()
    heading = str(data.get("Heading", "")).strip() or query
    if abstract:
        items.append(
            {
                "provider": "api.duckduckgo.com",
                "source_id": f"ddg:{heading}",
                "title": heading,
                "snippet": abstract[:400],
                "url": abstract_url or f"https://duckduckgo.com/?q={encoded_q}",
                "retrieved_at": retrieved_at,
                "trust_status": "UNTRUSTED_WEB_EVIDENCE",
            }
        )
    for topic in data.get("RelatedTopics", [])[:3]:
        if isinstance(topic, dict) and topic.get("Text") and topic.get("FirstURL"):
            items.append(
                {
                    "provider": "api.duckduckgo.com",
                    "source_id": f"ddg:{str(topic.get('Text', ''))[:40]}",
                    "title": str(topic.get("Text", ""))[:72],
                    "snippet": str(topic.get("Text", ""))[:320],
                    "url": str(topic.get("FirstURL", "")),
                    "retrieved_at": retrieved_at,
                    "trust_status": "UNTRUSTED_WEB_EVIDENCE",
                }
            )
    return items, None


def _run_web_search(query: str, allowlist: list[str]) -> dict:
    q = query.strip()
    if not q:
        return {"ok": False, "error": "กรุณาระบุคำค้นหา"}

    eff_allowlist = [str(d).strip().lower() for d in allowlist if str(d).strip()]
    has_thai = bool(re.search(r"[\u0E00-\u0E7F]", q))

    candidate_hosts: list[str] = []
    if has_thai and (not eff_allowlist or "th.wikipedia.org" in eff_allowlist):
        candidate_hosts.append("th.wikipedia.org")
    if not eff_allowlist or "en.wikipedia.org" in eff_allowlist:
        candidate_hosts.append("en.wikipedia.org")
    elif not candidate_hosts:
        for h in eff_allowlist:
            if "wikipedia.org" in h:
                candidate_hosts.append(h)

    all_items: list[dict] = []
    provider_errors: list[str] = []
    queried_providers: list[str] = []

    for host in candidate_hosts[:2]:
        queried_providers.append(host)
        items, err = _query_mediawiki_source(host, q, eff_allowlist or [host])
        all_items.extend(items)
        if err:
            provider_errors.append(f"{host}: {err}")

    if not eff_allowlist or "api.duckduckgo.com" in eff_allowlist:
        queried_providers.append("api.duckduckgo.com")
        ddg_items, ddg_err = _query_duckduckgo_instant(q, eff_allowlist or ["api.duckduckgo.com"])
        all_items.extend(ddg_items)
        if ddg_err:
            provider_errors.append(f"api.duckduckgo.com: {ddg_err}")

    if not all_items and provider_errors:
        return {"ok": False, "error": "; ".join(provider_errors[:2])}

    return {
        "ok": True,
        "providers_queried": queried_providers,
        "provider_errors": provider_errors,
        "query": q,
        "retrieved_at": _now_iso(),
        "results": all_items[:6],
    }


def _run_doc_fetch(url: str, allowlist: list[str]) -> dict:
    res = safe_http_get(url, allowlist)
    if not res["ok"]:
        return res
    ctype = res.get("content_type", "").lower()
    body = res["body"]
    title = ""
    headings: list[str] = []
    extracted = body
    if "html" in ctype or "<html" in body[:300].lower():
        parser = _VisibleTextHTMLParser()
        try:
            parser.feed(body)
            parser.close()
            title = " ".join(parser.title_parts)[:160]
            headings = parser.headings
            extracted = "\n".join(parser.text_parts)
        except Exception:
            extracted = re.sub(r"<[^>]+>", " ", body)
    extracted = re.sub(r"\n{3,}", "\n\n", extracted).strip()[:3500]
    parsed_host = urllib.parse.urlparse(res["url"]).hostname or ""
    return {
        "ok": True,
        "url": res["url"],
        "provider": parsed_host,
        "source_id": parsed_host,
        "title": title,
        "headings": headings,
        "content_type": ctype,
        "retrieved_at": _now_iso(),
        "trust_status": "UNTRUSTED_WEB_EVIDENCE",
        "excerpt": extracted,
    }


def _sanitize_rel_filename(name: str) -> str | None:
    cleaned = name.strip().replace("\\", "/")
    if not cleaned or cleaned.startswith("/") or ".." in cleaned.split("/"):
        return None
    if not re.fullmatch(r"[a-zA-Z0-9\u0E00-\u0E7F._\- ]{1,96}", cleaned):
        return None
    return cleaned


def safe_workspace_path(data_dir: Path, filename: str) -> Path | None:
    safe_name = _sanitize_rel_filename(str(filename or ""))
    if not safe_name:
        return None
    ws_dir = (Path(data_dir) / "workspace_files").resolve()
    target = (ws_dir / safe_name).resolve()
    if not target.is_relative_to(ws_dir) or target.is_symlink():
        return None
    return target


def analyze_structured_dataset_content(raw_text: str, filename_hint: str = "") -> dict:
    """Deterministic local structured dataset inspection for CSV/JSON content (zero external models)."""
    text = (raw_text or "").strip()
    if not text:
        return {"ok": False, "error": "ไม่มีข้อมูลสำหรับวิเคราะห์"}

    hint_l = (filename_hint or "").strip().lower()
    # Try JSON first if extension hints .json or starts with [ or {
    if hint_l.endswith(".json") or text.startswith("[") or text.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                dict_rows = [r for r in parsed if isinstance(r, dict)]
                if dict_rows:
                    columns: list[str] = []
                    seen_cols: set[str] = set()
                    for row in dict_rows:
                        for k in row.keys():
                            ks = str(k)
                            if ks not in seen_cols:
                                seen_cols.add(ks)
                                columns.append(ks)
                    null_counts: dict[str, int] = {c: 0 for c in columns}
                    numeric_vals: dict[str, list[float]] = {c: [] for c in columns}
                    row_sigs: list[str] = []
                    for row in dict_rows:
                        row_sigs.append(json.dumps(row, sort_keys=True, ensure_ascii=False))
                        for c in columns:
                            val = row.get(c)
                            if val is None or (isinstance(val, str) and not val.strip()):
                                null_counts[c] += 1
                            elif isinstance(val, (int, float)) and not isinstance(val, bool):
                                numeric_vals[c].append(float(val))
                    duplicates = len(row_sigs) - len(set(row_sigs))
                    numeric_stats = {}
                    for c, vals in numeric_vals.items():
                        if vals:
                            numeric_stats[c] = {
                                "count": len(vals),
                                "min": round(min(vals), 4),
                                "max": round(max(vals), 4),
                                "mean": round(statistics.fmean(vals), 4),
                            }
                    return {
                        "ok": True,
                        "format": "json_records",
                        "rows": len(parsed),
                        "dict_rows": len(dict_rows),
                        "columns": columns,
                        "duplicate_rows": duplicates,
                        "missing_counts": {k: v for k, v in null_counts.items() if v > 0},
                        "numeric_summary": numeric_stats,
                        "issues": ([] if len(dict_rows) == len(parsed) else ["พบรายการที่ไม่ใช่ object ปะปนอยู่ใน JSON array"]),
                    }
                return {
                    "ok": True,
                    "format": "json_array",
                    "rows": len(parsed),
                    "columns": [],
                    "duplicate_rows": len(parsed) - len({json.dumps(x, sort_keys=True, ensure_ascii=False) for x in parsed}),
                    "missing_counts": {},
                    "numeric_summary": {},
                    "issues": [],
                }
            if isinstance(parsed, dict):
                return {
                    "ok": True,
                    "format": "json_object",
                    "rows": len(parsed),
                    "columns": [str(k) for k in list(parsed.keys())[:24]],
                    "duplicate_rows": 0,
                    "missing_counts": {str(k): 1 for k, v in parsed.items() if v is None or v == ""},
                    "numeric_summary": {},
                    "issues": [],
                }
        except json.JSONDecodeError as exc:
            return {
                "ok": False,
                "format": "json_invalid",
                "error": f"JSON ไม่ถูกต้องที่บรรทัด {exc.lineno} คอลัมน์ {exc.colno}: {exc.msg}",
            }

    # Try CSV / TSV deterministic parse
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 1 and ("," in lines[0] or "\t" in lines[0] or hint_l.endswith(".csv")):
        delimiter = "\t" if ("\t" in lines[0] and "," not in lines[0]) else ","
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = [r for r in reader if any(cell.strip() for cell in r)]
        if not rows:
            return {"ok": False, "error": "ไฟล์ CSV ว่างเปล่า"}
        headers = [h.strip() or f"col_{idx}" for idx, h in enumerate(rows[0])]
        data_rows = rows[1:]
        issues: list[str] = []
        ragged_lines: list[int] = []
        null_counts = {h: 0 for h in headers}
        numeric_cols: dict[str, list[float]] = {h: [] for h in headers}
        row_sigs: list[tuple[str, ...]] = []
        for idx, r in enumerate(data_rows, start=2):
            if len(r) != len(headers):
                ragged_lines.append(idx)
            row_sigs.append(tuple(c.strip() for c in r))
            for col_i, h in enumerate(headers):
                cell = r[col_i].strip() if col_i < len(r) else ""
                if cell == "" or cell.lower() in {"null", "none", "nan", "na"}:
                    null_counts[h] += 1
                else:
                    try:
                        numeric_cols[h].append(float(cell))
                    except ValueError:
                        pass
        if ragged_lines:
            issues.append(f"จำนวนคอลัมน์ไม่ตรงกับ Header ที่บรรทัด {', '.join(str(x) for x in ragged_lines[:8])}")
        duplicates = len(row_sigs) - len(set(row_sigs))
        if duplicates > 0:
            issues.append(f"พบแถวข้อมูลซ้ำกัน {duplicates} แถว")
        numeric_stats = {}
        for h, vals in numeric_cols.items():
            if vals:
                numeric_stats[h] = {
                    "count": len(vals),
                    "min": round(min(vals), 4),
                    "max": round(max(vals), 4),
                    "mean": round(statistics.fmean(vals), 4),
                }
        return {
            "ok": True,
            "format": "csv",
            "rows": len(data_rows),
            "columns": headers,
            "duplicate_rows": duplicates,
            "missing_counts": {k: v for k, v in null_counts.items() if v > 0},
            "numeric_summary": numeric_stats,
            "issues": issues,
        }

    return {"ok": False, "error": "รูปแบบข้อมูลไม่ใช่ JSON หรือ CSV ที่ตรวจโครงสร้างได้โดยตรง"}


def inspect_workspace_code_content(raw_text: str, filename_hint: str = "") -> dict:
    """Deterministic static & syntax inspection for workspace code/text artifacts."""
    text = raw_text or ""
    if not text.strip():
        return {"ok": False, "error": "ไฟล์หรือข้อความว่างเปล่า"}

    hint_l = (filename_hint or "").strip().lower()
    lines = text.splitlines()
    defects: list[dict] = []
    symbols: list[str] = []

    is_json = hint_l.endswith(".json") or (text.lstrip().startswith(("{", "[")) and not hint_l.endswith(".py"))
    is_python = hint_l.endswith(".py") or bool(
        re.search(r"^\s*(?:def\s+\w+\s*\(|class\s+\w+|import\s+\w+|from\s+\w+\s+import)", text, re.MULTILINE)
    )

    if is_json:
        try:
            parsed = json.loads(text)
            kind = type(parsed).__name__
            return {
                "ok": True,
                "language": "json",
                "line_count": len(lines),
                "symbols": list(parsed.keys())[:16] if isinstance(parsed, dict) else [],
                "defects": [],
                "passed": True,
                "summary": f"ตรวจสอบโครงสร้าง JSON ({kind}, {len(lines)} บรรทัด) ผ่านเกณฑ์ ไม่พบ Syntax Error",
            }
        except json.JSONDecodeError as exc:
            defects.append({
                "line": exc.lineno,
                "column": exc.colno,
                "severity": "error",
                "message": f"JSON syntax error: {exc.msg}",
            })
            return {
                "ok": True,
                "language": "json",
                "line_count": len(lines),
                "symbols": [],
                "defects": defects,
                "passed": False,
                "summary": f"พบข้อผิดพลาด JSON ที่บรรทัด {exc.lineno} คอลัมน์ {exc.colno}: {exc.msg}",
            }

    if is_python:
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    symbols.append(f"{type(node).__name__.replace('Def', '').lower()}:{node.name}@{node.lineno}")
            # Also scan for basic static hygiene markers
            for idx, ln in enumerate(lines, start=1):
                if re.search(r"\bexcept\s*:", ln):
                    defects.append({
                        "line": idx,
                        "severity": "warning",
                        "message": "Bare except: อาจซ่อนข้อผิดพลาดที่ควรระบุชนิดข้อยกเว้น",
                    })
                if re.search(r"(?:TODO|FIXME|BUG)\b", ln):
                    defects.append({
                        "line": idx,
                        "severity": "info",
                        "message": f"พบเครื่องหมายงานค้างในโค้ด: {ln.strip()[:80]}",
                    })
            return {
                "ok": True,
                "language": "python",
                "line_count": len(lines),
                "symbols": symbols[:20],
                "defects": defects[:20],
                "passed": not any(d["severity"] == "error" for d in defects),
                "summary": (
                    f"AST Python ผ่าน ({len(lines)} บรรทัด, {len(symbols)} สัญลักษณ์)"
                    if not defects
                    else f"AST Python ผ่าน แต่พบข้อสังเกต {len(defects)} จุด"
                ),
            }
        except SyntaxError as exc:
            defects.append({
                "line": exc.lineno or 1,
                "column": exc.offset or 0,
                "severity": "error",
                "message": f"Python SyntaxError: {exc.msg}",
            })
            return {
                "ok": True,
                "language": "python",
                "line_count": len(lines),
                "symbols": [],
                "defects": defects,
                "passed": False,
                "summary": f"พบ Python SyntaxError ที่บรรทัด {exc.lineno or 1}: {exc.msg}",
            }

    # General text / markdown / structured artifact inspection
    for idx, ln in enumerate(lines, start=1):
        if re.search(r"(?:TODO|FIXME|BUG|ERROR)\b", ln):
            defects.append({"line": idx, "severity": "info", "message": ln.strip()[:90]})
    return {
        "ok": True,
        "language": "text",
        "line_count": len(lines),
        "symbols": [ln.strip()[:60] for ln in lines if ln.lstrip().startswith("#")][:10],
        "defects": defects[:20],
        "passed": True,
        "summary": f"ตรวจสอบไฟล์ข้อความ {len(lines)} บรรทัดเรียบร้อย",
    }


def _run_workspace_file_tool(
    data_dir: Path,
    tool_input: dict,
    approved_by: str | None,
) -> dict:
    ws_dir = (data_dir / "workspace_files").resolve()
    ws_dir.mkdir(parents=True, exist_ok=True)
    action = str(tool_input.get("action", "read")).strip().lower()
    filename = str(tool_input.get("filename", "")).strip()
    inline_content = str(tool_input.get("content", ""))

    if action == "list" or (action == "read" and (not filename or filename.lower() in {"list", "all", "ls", "รายการ"})):
        files = []
        for entry in sorted(ws_dir.iterdir()):
            if entry.is_file() and not entry.is_symlink():
                files.append(
                    {
                        "name": entry.name,
                        "size_bytes": entry.stat().st_size,
                        "modified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(entry.stat().st_mtime)),
                    }
                )
        return {"ok": True, "action": "list", "files": files[:40]}

    if action in {"inspect", "analyze_dataset"} and not filename and inline_content.strip():
        if action == "analyze_dataset":
            report = analyze_structured_dataset_content(inline_content)
            return {"ok": bool(report.get("ok")), "action": action, "filename": "(inline)", **report}
        report = inspect_workspace_code_content(inline_content)
        return {"ok": bool(report.get("ok")), "action": action, "filename": "(inline)", **report}

    safe_name = _sanitize_rel_filename(filename)
    if not safe_name:
        return {"ok": False, "error": "ชื่อไฟล์ไม่ปลอดภัยหรือไม่อยู่ในรูปแบบที่อนุญาต"}

    target = (ws_dir / safe_name).resolve()
    if not target.is_relative_to(ws_dir):
        return {"ok": False, "error": "ปฏิเสธการเข้าถึงนอกโฟลเดอร์เวิร์กสเปซ"}
    if target.is_symlink():
        return {"ok": False, "error": "ไม่อนุญาตให้อ่านหรือเขียนไฟล์ symlink"}

    if action == "write":
        if not approved_by:
            return {"ok": False, "requires_approval": True, "error": "การเขียนไฟล์ต้องผ่าน Approval Gate"}
        allowed_ext = (".txt", ".md", ".json", ".csv")
        if not safe_name.lower().endswith(allowed_ext):
            return {"ok": False, "error": "รองรับเฉพาะไฟล์ .txt, .md, .json, .csv"}
        content = inline_content[:20000]
        target.write_text(content, encoding="utf-8")
        return {
            "ok": True,
            "action": "write",
            "filename": safe_name,
            "size_bytes": len(content.encode("utf-8")),
        }

    if not target.exists() or not target.is_file():
        return {"ok": False, "error": f"ไม่พบไฟล์ '{safe_name}' ในพื้นที่ไฟล์เวิร์กสเปซ"}

    content = target.read_text(encoding="utf-8", errors="replace")[:20000]
    if action == "analyze_dataset":
        report = analyze_structured_dataset_content(content, safe_name)
        return {"ok": bool(report.get("ok")), "action": action, "filename": safe_name, **report}
    if action == "inspect":
        report = inspect_workspace_code_content(content, safe_name)
        return {"ok": bool(report.get("ok")), "action": action, "filename": safe_name, **report}

    return {
        "ok": True,
        "action": "read",
        "filename": safe_name,
        "size_bytes": target.stat().st_size,
        "content": content[:6000],
    }


def list_workspace_files(data_dir: Path) -> list[dict]:
    res = _run_workspace_file_tool(data_dir, {"action": "list"}, None)
    return res.get("files", []) if res.get("ok") else []


def save_workspace_file(data_dir: Path, filename: str, content: str) -> dict:
    safe_name = _sanitize_rel_filename(filename)
    if not safe_name:
        return {"ok": False, "error": "ชื่อไฟล์ไม่ถูกต้อง"}
    allowed_ext = (".txt", ".md", ".json", ".csv")
    if not safe_name.lower().endswith(allowed_ext):
        return {"ok": False, "error": "รองรับเฉพาะไฟล์ .txt, .md, .json, .csv"}
    ws_dir = (data_dir / "workspace_files").resolve()
    ws_dir.mkdir(parents=True, exist_ok=True)
    target = (ws_dir / safe_name).resolve()
    if not target.is_relative_to(ws_dir) or target.is_symlink():
        return {"ok": False, "error": "เส้นทางไฟล์ไม่ปลอดภัย"}
    trimmed = content[:50000]
    target.write_text(trimmed, encoding="utf-8")
    return {
        "ok": True,
        "file": {
            "name": safe_name,
            "size_bytes": len(trimmed.encode("utf-8")),
            "modified_at": _now_iso(),
        },
    }


def validate_tool_input(tool_id: str, tool_input: dict) -> tuple[bool, str | None]:
    contract = TOOL_CONTRACTS.get(tool_id)
    if not contract:
        return False, f"ไม่พบสัญญา Tool Contract สำหรับ '{tool_id}'"
    for field in contract["required_fields"]:
        val = str(tool_input.get(field, "")).strip()
        if not val:
            return False, f"เครื่องมือ '{tool_id}' ต้องระบุข้อมูลนำเข้า '{field}'"
    if tool_id == "workspace_file_read":
        act = str(tool_input.get("action", "read")).strip().lower()
        if act not in {"read", "list", "write", "inspect", "analyze_dataset"}:
            return False, "รองรับเฉพาะ action: read, list, inspect, analyze_dataset หรือ write"
        if act == "write" and not str(tool_input.get("filename", "")).strip():
            return False, "การเขียนไฟล์ต้องระบุชื่อไฟล์"
        if act in {"inspect", "analyze_dataset"} and not str(tool_input.get("filename", "")).strip() and not str(tool_input.get("content", "")).strip():
            return False, "ต้องระบุชื่อไฟล์หรือเนื้อหาที่ต้องการตรวจสอบ"
    return True, None


STALE_EVIDENCE_MAX_AGE_SECONDS = 7 * 24 * 3600


def _is_blocked_llm_host(hostname: str) -> bool:
    h = hostname.strip().lower()
    if not h:
        return False
    return any(h == b or h.endswith(f".{b}") for b in BLOCKED_EXTERNAL_LLM_HOSTS)


def _validate_evidence_source_metadata(provider: str, url: str) -> tuple[bool, str]:
    prov = (provider or "").strip().lower()
    u = (url or "").strip()
    if not u:
        return False, "ไม่มี URL อ้างอิงแหล่งที่มา"
    try:
        parsed = urllib.parse.urlparse(u)
    except Exception:
        return False, "URL อ้างอิงไม่ถูกต้อง"
    if parsed.scheme.lower() != "https":
        return False, f"โปรโตคอล URL ไม่ใช่ https:// ({parsed.scheme or 'none'})"
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False, "ไม่พบโดเมนปลายทางใน URL"
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        return False, f"ไม่อนุญาตแหล่งอ้างอิงภายใน/local ({host})"
    try:
        ip_obj = ipaddress.ip_address(host)
        if not ip_obj.is_global:
            return False, f"ไม่อนุญาต IP เครือข่ายส่วนตัว ({host})"
    except ValueError:
        pass
    if _is_blocked_llm_host(host) or _is_blocked_llm_host(prov):
        return False, f"ปฏิเสธแหล่งข้อมูลจากโฮสต์โมเดล AI ภายนอก ({prov or host})"
    if not prov:
        return False, "ไม่ระบุผู้ให้บริการ/แหล่งข้อมูล (provider)"
    return True, host


def _parse_iso_utc(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    raw = str(ts_str).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


_CONFLICT_SLOTS: list[tuple[str, re.Pattern[str]]] = [
    ("release_year", re.compile(r"(?:released|created|founded|launched|เปิดตัว|ก่อตั้ง|สร้างขึ้น)(?:\s+(?:in|on|ในปี|เมื่อปี|ปี))?\s+(\d{4})\b", re.IGNORECASE)),
    ("version", re.compile(r"(?:version|เวอร์ชัน|รุ่น)\s+v?(\d+(?:\.\d+)+)\b", re.IGNORECASE)),
    ("atomic_number", re.compile(r"(?:atomic\s+number|เลขอะตอม)(?:\s*(?:is|คือ|=|:))?\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE)),
    ("port", re.compile(r"(?:default\s+)?(?:port|พอร์ต)(?:\s*(?:is|คือ|=|:))?\s+(\d{2,5})\b", re.IGNORECASE)),
    ("count_metric", re.compile(r"(?:มี|contains|consists\s+of|ทั้งหมด)\s+(\d+(?:\.\d+)?)\s+(?:คน|ผล|ชิ้น|เล่ม|pages|items|nodes|hops)\b", re.IGNORECASE)),
]


def _detect_source_conflicts(
    source_chunks: dict[str, list[str]],
    kg_matches: list[dict],
) -> list[dict]:
    conflicts: list[dict] = []
    if not source_chunks:
        return conflicts

    # 1. Cross-provider same-slot numeric conflicts
    slot_provider_vals: dict[str, dict[str, set[str]]] = collections.defaultdict(lambda: collections.defaultdict(set))
    for prov, chunks in source_chunks.items():
        joined = " ".join(chunks)
        for slot_name, pattern in _CONFLICT_SLOTS:
            for match in pattern.findall(joined):
                slot_provider_vals[slot_name][prov].add(str(match).strip())

    for slot_name, prov_map in slot_provider_vals.items():
        single_val_provs = {p: next(iter(vs)) for p, vs in prov_map.items() if len(vs) == 1}
        if len(single_val_provs) >= 2:
            distinct_vals = sorted(set(single_val_provs.values()))
            if len(distinct_vals) >= 2:
                conflicts.append({
                    "type": "CROSS_SOURCE_NUMERIC_CONFLICT",
                    "slot": slot_name,
                    "claims": single_val_provs,
                    "detail": f"แหล่งข้อมูลระบุค่า '{slot_name}' ไม่ตรงกัน ({', '.join(f'{p}={v}' for p, v in sorted(single_val_provs.items()))})",
                })

    # 2. Cross-provider explicit affirmative vs negative polarity conflict on shared context
    if len(source_chunks) >= 2:
        neg_re = re.compile(r"\b(?:is\s+not|are\s+not|does\s+not\s+support|cannot|never\s+supported|no\s+longer)\b|(?:ไม่รองรับ|ไม่ใช่|ไม่ได้ใช้|ยกเลิกแล้ว)", re.IGNORECASE)
        pos_re = re.compile(r"\b(?:supports|is\s+supported|is\s+compatible|enabled\s+by\s+default)\b|(?:รองรับอย่างเป็นทางการ|ใช้งานร่วมกันได้|เปิดใช้งานเป็นค่าเริ่มต้น)", re.IGNORECASE)
        neg_provs: list[str] = []
        pos_provs: list[str] = []
        for prov, chunks in source_chunks.items():
            joined = " ".join(chunks)
            has_neg = bool(neg_re.search(joined))
            has_pos = bool(pos_re.search(joined))
            if has_neg and not has_pos:
                neg_provs.append(prov)
            elif has_pos and not has_neg:
                pos_provs.append(prov)
        if neg_provs and pos_provs:
            conflicts.append({
                "type": "CROSS_SOURCE_POLARITY_CONFLICT",
                "slot": "assertion_polarity",
                "claims": {**{p: "affirmative" for p in pos_provs}, **{p: "negative" for p in neg_provs}},
                "detail": f"แหล่งข้อมูลให้ข้อสรุปขัดแย้งกัน ({', '.join(pos_provs)} ยืนยัน vs {', '.join(neg_provs)} ปฏิเสธ)",
            })

    # 3. External source numeric contradiction against verified internal KG slot
    for kg in kg_matches:
        subj = str(kg.get("subject", "")).strip()
        rel = str(kg.get("relation", "")).strip()
        obj = str(kg.get("object", "")).strip()
        if not subj or not re.fullmatch(r"\d+(?:\.\d+)?", obj):
            continue
        subj_l = subj.lower()
        rel_l = rel.lower()
        for prov, chunks in source_chunks.items():
            joined = " ".join(chunks)
            joined_l = joined.lower()
            if subj_l in joined_l and any(k in joined_l for k in [rel_l, "atomic number", "เลขอะตอม", "port", "พอร์ต", "version", "เวอร์ชัน"]):
                for slot_name, pattern in _CONFLICT_SLOTS:
                    found_vals = set(pattern.findall(joined))
                    if len(found_vals) == 1:
                        ext_val = next(iter(found_vals))
                        if ext_val != obj and (
                            ("เลขอะตอม" in rel_l and slot_name == "atomic_number")
                            or ("พอร์ต" in rel_l or "port" in rel_l) and slot_name == "port"
                            or ("เวอร์ชัน" in rel_l or "version" in rel_l) and slot_name == "version"
                        ):
                            conflicts.append({
                                "type": "EXTERNAL_VS_KG_CONFLICT",
                                "slot": slot_name,
                                "claims": {prov: ext_val, "internal_kg": obj},
                                "detail": f"แหล่งภายนอก {prov} ระบุ {subj} ({slot_name}={ext_val}) ขัดแย้งกับกราฟความรู้ภายใน ({obj})",
                            })

    return conflicts


def analyze_tool_result(
    conn: sqlite3.Connection,
    tool_id: str,
    raw_output: dict,
    tokenize_fn: Callable[[str], list[str]],
    extract_terms_fn: Callable[[str], list[str]],
    query_kg_fn: Callable[[sqlite3.Connection, str], list[dict]],
) -> dict:
    """
    P3 Structured Evidence & Native Evaluation + Anti-Fabrication Verification:
    - Validates every evidence source URL and rejects missing/local/blocked-LLM sources
    - Tracks retrieved_at timestamps and flags STALE evidence older than threshold
    - Compares term agreement across distinct verified providers
    - Cross-checks against ZYRQUEN's internal Knowledge Graph
    - Reports explicit verification_status, trust_grade & limitations honestly
    """
    if tool_id == "calc_ast":
        return {
            "trust_grade": "INTERNAL_DETERMINISTIC",
            "verification_status": "VERIFIED",
            "freshness_status": "FRESH",
            "retrieved_at": _now_iso(),
            "token_count": 0,
            "top_terms": [],
            "kg_matches": [],
            "distinct_providers": ["zyrquen_ast"],
            "cross_source_shared_terms": [],
            "numeric_values": [raw_output.get("result")] if "result" in raw_output else [],
            "rejected_sources": [],
            "limitations": [],
            "summary": "ZYRQUEN Native Compute ยืนยันผลคำนวณเชิงสัญลักษณ์ภายใน 100%",
        }

    if tool_id == "workspace_file_read":
        if raw_output.get("action") == "list":
            names = [f["name"] for f in raw_output.get("files", [])]
            return {
                "trust_grade": "SANDBOX_LOCAL_FILE",
                "verification_status": "VERIFIED",
                "freshness_status": "FRESH",
                "retrieved_at": _now_iso(),
                "token_count": len(names),
                "top_terms": names[:6],
                "kg_matches": [],
                "distinct_providers": ["workspace_files"],
                "cross_source_shared_terms": [],
                "numeric_values": [],
                "rejected_sources": [],
                "limitations": ["แสดงเฉพาะไฟล์ภายในโฟลเดอร์ Sandbox ของระบบ"],
                "summary": f"ZYRQUEN Native Core ตรวจพบไฟล์ในพื้นที่ปลอดภัย {len(names)} รายการ",
            }
        if raw_output.get("action") == "write":
            return {
                "trust_grade": "SANDBOX_LOCAL_FILE",
                "verification_status": "VERIFIED",
                "freshness_status": "FRESH",
                "retrieved_at": _now_iso(),
                "token_count": 0,
                "top_terms": [str(raw_output.get("filename", ""))],
                "kg_matches": [],
                "distinct_providers": ["workspace_files"],
                "cross_source_shared_terms": [],
                "numeric_values": [str(raw_output.get("size_bytes", 0))],
                "rejected_sources": [],
                "limitations": [],
                "summary": f"บันทึกไฟล์ `{raw_output.get('filename')}` สำเร็จหลังผ่าน Approval Gate",
            }
        if raw_output.get("action") == "analyze_dataset":
            return {
                "trust_grade": "SANDBOX_LOCAL_FILE",
                "verification_status": "VERIFIED",
                "freshness_status": "FRESH",
                "retrieved_at": _now_iso(),
                "token_count": int(raw_output.get("rows", 0)),
                "top_terms": list(raw_output.get("columns", []))[:6],
                "kg_matches": [],
                "distinct_providers": ["workspace_files"],
                "cross_source_shared_terms": [],
                "numeric_values": [],
                "rejected_sources": [],
                "limitations": list(raw_output.get("issues", [])),
                "summary": f"วิเคราะห์โครงสร้างข้อมูล `{raw_output.get('filename', '')}` ({raw_output.get('format')}, {raw_output.get('rows', 0)} แถว)",
            }
        if raw_output.get("action") == "inspect":
            passed = bool(raw_output.get("passed", True))
            return {
                "trust_grade": "SANDBOX_LOCAL_FILE",
                "verification_status": "VERIFIED" if passed else "DEFECTS_FOUND",
                "freshness_status": "FRESH",
                "retrieved_at": _now_iso(),
                "token_count": int(raw_output.get("line_count", 0)),
                "top_terms": list(raw_output.get("symbols", []))[:6],
                "kg_matches": [],
                "distinct_providers": ["workspace_files"],
                "cross_source_shared_terms": [],
                "numeric_values": [],
                "rejected_sources": [],
                "limitations": [d.get("message", "") for d in (raw_output.get("defects") or [])[:4]],
                "summary": str(raw_output.get("summary") or f"ตรวจสอบไฟล์ `{raw_output.get('filename', '')}`"),
            }

    text_chunks: list[str] = []
    source_terms: dict[str, set[str]] = collections.defaultdict(set)
    source_chunks: dict[str, list[str]] = collections.defaultdict(list)
    evidence_items: list[dict] = []
    rejected_sources: list[dict] = []
    observed_timestamps: list[datetime] = []

    top_ts = _parse_iso_utc(raw_output.get("retrieved_at"))
    if top_ts:
        observed_timestamps.append(top_ts)

    if tool_id == "web_search":
        for item in raw_output.get("results", []):
            prov = str(item.get("provider", "")).strip()
            item_url = str(item.get("url", "")).strip()
            src_ok, src_reason = _validate_evidence_source_metadata(prov, item_url)
            if not src_ok:
                rejected_sources.append({
                    "provider": prov or "unknown",
                    "url": item_url,
                    "title": str(item.get("title", "")),
                    "reason": src_reason,
                })
                continue
            item_ts = _parse_iso_utc(item.get("retrieved_at")) or top_ts
            if item_ts:
                observed_timestamps.append(item_ts)
            chunk = f"{item.get('title', '')} {item.get('snippet', '')}"
            text_chunks.append(chunk)
            source_chunks[prov].append(chunk)
            item_terms = set(extract_terms_fn(chunk))
            source_terms[prov].update(item_terms)
            evidence_items.append(
                {
                    "provider": prov,
                    "source_id": item.get("source_id") or f"{prov}:{item.get('title', '')}",
                    "title": item.get("title", ""),
                    "url": item_url,
                    "retrieved_at": (item_ts.strftime("%Y-%m-%dT%H:%M:%SZ") if item_ts else None),
                    "trust_status": item.get("trust_status", "UNTRUSTED_WEB_EVIDENCE"),
                }
            )
    elif tool_id == "doc_fetch":
        prov = str(raw_output.get("provider", "")).strip()
        doc_url = str(raw_output.get("url", "")).strip()
        src_ok, src_reason = _validate_evidence_source_metadata(prov, doc_url)
        if not src_ok:
            rejected_sources.append({
                "provider": prov or "unknown",
                "url": doc_url,
                "title": str(raw_output.get("title", "")),
                "reason": src_reason,
            })
        else:
            chunk = f"{raw_output.get('title', '')}\n{' '.join(raw_output.get('headings', []))}\n{raw_output.get('excerpt', '')}"
            text_chunks.append(chunk)
            source_chunks[prov].append(chunk)
            source_terms[prov].update(extract_terms_fn(chunk[:1500]))
            evidence_items.append(
                {
                    "provider": prov,
                    "source_id": raw_output.get("source_id") or prov,
                    "title": raw_output.get("title", ""),
                    "url": doc_url,
                    "retrieved_at": (top_ts.strftime("%Y-%m-%dT%H:%M:%SZ") if top_ts else None),
                    "trust_status": raw_output.get("trust_status", "UNTRUSTED_WEB_EVIDENCE"),
                }
            )
    elif tool_id == "workspace_file_read":
        content = str(raw_output.get("content", ""))
        text_chunks.append(content)
        source_terms["workspace_files"].update(extract_terms_fn(content[:1500]))

    now_dt = datetime.now(timezone.utc)
    if tool_id in {"web_search", "doc_fetch"}:
        if any((now_dt - ts).total_seconds() > STALE_EVIDENCE_MAX_AGE_SECONDS for ts in observed_timestamps):
            freshness_status = "STALE"
        elif observed_timestamps:
            freshness_status = "FRESH"
        else:
            freshness_status = "UNKNOWN"
    else:
        freshness_status = "FRESH"

    combined = "\n".join(text_chunks).strip()
    tokens = [t for t in tokenize_fn(combined) if len(t) >= 2]
    terms = extract_terms_fn(combined[:1800])
    freq = collections.Counter(tokens)
    top_terms = [
        w
        for w, _ in freq.most_common(10)
        if w not in {"the", "and", "for", "with", "that", "from", "this", "are", "was", "ของ", "และ", "ที่", "ใน"}
    ][:6]

    distinct_providers = list(source_terms.keys())
    term_provider_counts: collections.Counter = collections.Counter()
    for prov, tset in source_terms.items():
        for t in tset:
            if len(t) >= 3:
                term_provider_counts[t] += 1
    shared_terms = [t for t, c in term_provider_counts.most_common(8) if c >= 2][:6]

    kg_matches = query_kg_fn(conn, " ".join(terms[:8])) if terms else []
    numbers = re.findall(r"\b\d+(?:\.\d+)?\b", combined[:1500])[:6]
    conflicts = _detect_source_conflicts(source_chunks, kg_matches) if tool_id in {"web_search", "doc_fetch"} else []

    if tool_id == "workspace_file_read":
        trust_grade = "SANDBOX_LOCAL_FILE"
        verification_status = "VERIFIED"
    elif rejected_sources and not evidence_items:
        has_blocked_llm = any("โมเดล AI ภายนอก" in r.get("reason", "") for r in rejected_sources)
        trust_grade = "BLOCKED" if has_blocked_llm else "UNVERIFIED"
        verification_status = trust_grade
    elif not evidence_items:
        trust_grade = "INSUFFICIENT_EVIDENCE"
        verification_status = "NOT_FOUND"
    elif freshness_status == "STALE":
        trust_grade = "STALE"
        verification_status = "STALE"
    elif conflicts:
        trust_grade = "CONFLICTING_SOURCES"
        verification_status = "CONFLICTING"
    elif len(distinct_providers) >= 2 and len(shared_terms) >= 1:
        trust_grade = "CORROBORATED_MULTI_SOURCE"
        verification_status = "VERIFIED"
    else:
        trust_grade = "UNCORROBORATED_SINGLE_SOURCE"
        verification_status = "UNVERIFIED"

    limitations: list[str] = []
    if tool_id in {"web_search", "doc_fetch"}:
        limitations.append("ข้อมูลจากเว็บไซต์ภายนอกถูกตีตราเป็นหลักฐานรอการตรวจสอบ ไม่ใช่ข้อเท็จจริงภายในที่พิสูจน์แล้ว")
    if rejected_sources:
        limitations.append(
            f"คัดกรองแหล่งอ้างอิงที่ไม่ผ่านเกณฑ์ออก {len(rejected_sources)} รายการ (ไม่มี URL HTTPS ที่ถูกต้อง หรือเป็นโฮสต์ต้องห้าม)"
        )
    if freshness_status == "STALE":
        limitations.append("ข้อมูลหลักฐานล้าสมัย (STALE: retrieved_at เกินระยะเวลาที่กำหนด ควรสืบค้นใหม่ก่อนอ้างอิง)")
    if conflicts:
        for cf in conflicts[:3]:
            limitations.append(f"ข้อขัดแย้งของหลักฐาน: {cf['detail']}")
    if trust_grade == "UNCORROBORATED_SINGLE_SOURCE":
        limitations.append("พบหลักฐานจากแหล่งเดียวหรือยังไม่มีคำสำคัญยืนยันข้ามหลายแหล่ง ควรตรวจสอบเอกสารต้นทางเพิ่มเติม")
    if trust_grade in {"INSUFFICIENT_EVIDENCE", "UNVERIFIED", "BLOCKED"} and not evidence_items:
        limitations.append("ไม่พบหลักฐานเพียงพอจากแหล่งสาธารณะที่อนุญาต")

    kg_note = (
        f"เชื่อมโยงกับกราฟความรู้ภายใน {len(kg_matches)} รายการ"
        if kg_matches
        else "ยังไม่พบข้อมูลชุดนี้ในกราฟความรู้เดิม"
    )
    summary = (
        f"[{trust_grade}] Native Core ประเมินหลักฐานจาก {len(distinct_providers)} แหล่ง ({len(tokens)} หน่วยคำ) · "
        f"คำสำคัญ: {', '.join(top_terms[:5]) or 'ไม่มี'} · {kg_note}"
    )

    latest_ts = max(observed_timestamps).strftime("%Y-%m-%dT%H:%M:%SZ") if observed_timestamps else None

    return {
        "trust_grade": trust_grade,
        "verification_status": verification_status,
        "freshness_status": freshness_status,
        "retrieved_at": latest_ts,
        "token_count": len(tokens),
        "top_terms": top_terms,
        "distinct_providers": distinct_providers,
        "cross_source_shared_terms": shared_terms,
        "kg_matches": [
            {"subject": m["subject"], "relation": m["relation"], "object": m["object"]}
            for m in kg_matches[:4]
        ],
        "numeric_values": numbers,
        "conflicts": conflicts,
        "evidence_items": evidence_items,
        "rejected_sources": rejected_sources,
        "limitations": limitations,
        "summary": summary,
    }


def detect_tool_intent(prompt: str) -> tuple[str, dict] | None:
    cleaned = prompt.strip()

    m_research = re.match(
        r"^(?:ค้นคว้า|เปรียบเทียบ|research|investigate|compare)\s*:?\s*(.+)$",
        cleaned,
        re.IGNORECASE,
    )
    if m_research:
        return "web_search", {"query": m_research.group(1).strip(), "compare_sources": True}

    m_web = re.match(
        r"^(?:ค้นหาเว็บ|ค้นเว็บ|web_search|websearch|search_web)\s*:?\s*(.+)$",
        cleaned,
        re.IGNORECASE,
    )
    if m_web:
        return "web_search", {"query": m_web.group(1).strip()}

    m_doc = re.match(
        r"^(?:อ่านเอกสาร|ดึงเว็บ|doc_fetch|fetch_doc|fetch)\s*:?\s*(https?://\S+)$",
        cleaned,
        re.IGNORECASE,
    )
    if m_doc:
        return "doc_fetch", {"url": m_doc.group(1).strip()}

    m_write = re.match(
        r"^(?:เขียนไฟล์|บันทึกไฟล์|write_file)\s*:?\s*(.+?)\s*(?:\||::)\s*(.+)$",
        cleaned,
        re.IGNORECASE | re.DOTALL,
    )
    if m_write:
        return "workspace_file_read", {
            "action": "write",
            "filename": m_write.group(1).strip(),
            "content": m_write.group(2).strip(),
        }

    m_inspect = re.match(
        r"^(?:ตรวจสอบโค้ด|ตรวจไฟล์|วิเคราะห์ไฟล์ข้อมูล|วิเคราะห์ข้อมูลไฟล์|inspect_file|analyze_dataset)\s*:?\s*(.+)$",
        cleaned,
        re.IGNORECASE,
    )
    if m_inspect:
        target_arg = m_inspect.group(1).strip()
        target_low = target_arg.lower()
        is_attached_ref = target_low in {
            "นี้",
            "ชุดนี้",
            "ไฟล์นี้",
            "อันนี้",
            "โค้ดนี้",
            "ที่แนบ",
            "ด้านล่าง",
            "this",
            "this file",
            "attached",
            "attachment",
        }
        if not is_attached_ref:
            if any(k in cleaned.lower() for k in ("วิเคราะห์ไฟล์ข้อมูล", "วิเคราะห์ข้อมูลไฟล์", "analyze_dataset", ".csv")):
                return "workspace_file_read", {"action": "analyze_dataset", "filename": target_arg}
            return "workspace_file_read", {"action": "inspect", "filename": target_arg}

    m_file = re.match(
        r"^(?:อ่านไฟล์|จัดการไฟล์|ไฟล์เวิร์กสเปซ|ไฟล์|file_read|read_file)\s*:?\s*(.*)$",
        cleaned,
        re.IGNORECASE,
    )
    if m_file:
        arg = m_file.group(1).strip()
        if not arg or arg.lower() in {"list", "ls", "all", "ทั้งหมด", "รายการ"}:
            return "workspace_file_read", {"action": "list"}
        return "workspace_file_read", {"action": "read", "filename": arg}

    m_nat_th = re.match(
        r"^(?:ช่วย|รบกวน|กรุณา)?\s*(?:สืบค้นข้อมูล|ค้นหาข้อมูล|หาข้อมูล|เช็กข้อมูล|เช็คข้อมูล|ตรวจสอบข้อมูล|ตามหาข้อมูล|สืบค้น|ค้นหา)"
        r"(?:\s*ข้อมูล)?(?:\s*(?:ล่าสุด|เพิ่มเติม|ใหม่|ออนไลน์))?\s*(?:เกี่ยวกับ|เรื่อง|ของ|คำว่า)?\s*(?:เรื่อง|คำว่า)?\s*(.+)$",
        cleaned,
        re.IGNORECASE,
    )
    if m_nat_th:
        q = m_nat_th.group(1).strip()
        q = re.sub(
            r"\s*(?:ให้หน่อยครับ|ให้หน่อยค่ะ|ให้หน่อย|หน่อยครับ|หน่อยค่ะ|หน่อย|ทีครับ|ทีค่ะ|ครับ|ค่ะ)\s*[?!.]*$",
            "",
            q,
        ).strip()
        if len(q) >= 2:
            return "web_search", {"query": q}

    m_nat_en = re.match(
        r"^(?:please\s+)?(?:search(?:\s+the\s+web)?\s+for|look\s+up|find\s+(?:the\s+)?(?:latest\s+)?info(?:rmation)?\s+(?:on|about))\s+(.+?)\s*[?!.]*$",
        cleaned,
        re.IGNORECASE,
    )
    if m_nat_en:
        q = m_nat_en.group(1).strip()
        if len(q) >= 2:
            return "web_search", {"query": q}

    return None


def invoke_tool_governed(
    conn: sqlite3.Connection,
    data_dir: Path,
    tool_id: str,
    tool_input: dict,
    user_id: str,
    conversation_id: str | None = None,
    approved_by: str | None = None,
    existing_invocation_id: str | None = None,
    tokenize_fn: Callable[[str], list[str]] | None = None,
    extract_terms_fn: Callable[[str], list[str]] | None = None,
    query_kg_fn: Callable[[sqlite3.Connection, str], list[dict]] | None = None,
    calc_fn: Callable[[str], dict | None] | None = None,
) -> dict:
    started = time.perf_counter()
    tool_row = conn.execute("SELECT * FROM external_tools WHERE id=?", (tool_id,)).fetchone()
    if not tool_row:
        return {"ok": False, "error": f"ไม่พบเครื่องมือ '{tool_id}' ใน Tool Registry"}

    valid_in, valid_err = validate_tool_input(tool_id, tool_input)
    if not valid_in:
        return {"ok": False, "error": valid_err}

    today = _today_utc()
    calls_today = int(tool_row["calls_today"]) if tool_row["last_reset_date"] == today else 0
    if tool_row["last_reset_date"] != today:
        with conn:
            conn.execute(
                "UPDATE external_tools SET calls_today=0, last_reset_date=? WHERE id=?",
                (today, tool_id),
            )

    if not tool_row["enabled"] or tool_row["permission_mode"] == "disabled":
        inv_id = existing_invocation_id or str(uuid.uuid4())
        now = _now_iso()
        with conn:
            if existing_invocation_id:
                conn.execute(
                    """
                    UPDATE tool_invocations
                    SET status='BLOCKED', output_json=?, analysis_summary=?, approved_by=?, latency_ms=0, updated_at=?
                    WHERE id=?
                    """,
                    (
                        json.dumps({"error": "เครื่องมือถูกปิดการใช้งานชั่วคราวโดยผู้ดูแลระบบ"}),
                        "ถูกบล็อกตามสิทธิ์ Permission Policy",
                        approved_by,
                        now,
                        inv_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO tool_invocations (id, tool_id, conversation_id, user_id, status, input_json, output_json, analysis_summary, approved_by, latency_ms, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'BLOCKED', ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        inv_id,
                        tool_id,
                        conversation_id,
                        user_id,
                        json.dumps(tool_input, ensure_ascii=False),
                        json.dumps({"error": "เครื่องมือถูกปิดการใช้งานชั่วคราวโดยผู้ดูแลระบบ"}),
                        "ถูกบล็อกตามสิทธิ์ Permission Policy",
                        approved_by,
                        now,
                        now,
                    ),
                )
            _log_tool_audit(conn, user_id, f"TOOL_{tool_id.upper()}_BLOCKED", inv_id, "BLOCKED")
        row = dict(conn.execute("SELECT * FROM tool_invocations WHERE id=?", (inv_id,)).fetchone())
        return {"ok": True, "status": "BLOCKED", "invocation": row, "tool": dict(tool_row)}

    if calls_today >= int(tool_row["quota_daily"]):
        with conn:
            _log_tool_audit(conn, user_id, f"TOOL_{tool_id.upper()}_QUOTA", tool_id, "QUOTA_EXCEEDED")
        return {
            "ok": False,
            "error": f"เครื่องมือ '{tool_row['name']}' ใช้ครบโควตารายวันแล้ว ({calls_today}/{tool_row['quota_daily']})",
        }

    needs_approval = tool_row["permission_mode"] == "approval_required" or (
        tool_id == "workspace_file_read" and str(tool_input.get("action", "")).lower() == "write"
    )
    if needs_approval and not approved_by:
        inv_id = str(uuid.uuid4())
        now = _now_iso()
        with conn:
            conn.execute(
                """
                INSERT INTO tool_invocations (id, tool_id, conversation_id, user_id, status, input_json, output_json, analysis_summary, approved_by, latency_ms, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'PENDING_APPROVAL', ?, NULL, ?, NULL, 0, ?, ?)
                """,
                (
                    inv_id,
                    tool_id,
                    conversation_id,
                    user_id,
                    json.dumps(tool_input, ensure_ascii=False),
                    f"รออนุมัติจากผู้ดูแลระบบก่อนเรียกใช้เครื่องมือ `{tool_id}`",
                    now,
                    now,
                ),
            )
            _log_tool_audit(conn, user_id, f"TOOL_GATE_REQUEST_{tool_id.upper()}", inv_id, "PENDING_APPROVAL")
        row = dict(conn.execute("SELECT * FROM tool_invocations WHERE id=?", (inv_id,)).fetchone())
        return {"ok": True, "status": "PENDING_APPROVAL", "invocation": row, "tool": dict(tool_row)}

    allowlist = json.loads(tool_row["endpoint_allowlist_json"] or "[]")
    if tool_id == "web_search":
        base_query = str(tool_input.get("query", ""))
        sub_queries = [
            str(sq).strip()
            for sq in (tool_input.get("sub_queries") or [])
            if str(sq).strip() and str(sq).strip().lower() != base_query.strip().lower()
        ][:2]
        raw_out = _run_web_search(base_query, allowlist)
        if sub_queries:
            merged_results: list[dict] = list(raw_out.get("results") or []) if raw_out.get("ok") else []
            seen_urls = {str(r.get("url") or "").strip().lower() for r in merged_results if r.get("url")}
            provs_q = list(raw_out.get("providers_queried") or [])
            prov_errs = list(raw_out.get("provider_errors") or [])
            if not raw_out.get("ok") and raw_out.get("error"):
                prov_errs.append(str(raw_out["error"]))
            executed_queries = [base_query]
            for sq in sub_queries:
                sub_res = _run_web_search(sq, allowlist)
                executed_queries.append(sq)
                if sub_res.get("ok"):
                    for p in sub_res.get("providers_queried") or []:
                        if p not in provs_q:
                            provs_q.append(p)
                    prov_errs.extend(sub_res.get("provider_errors") or [])
                    for item in sub_res.get("results") or []:
                        u_key = str(item.get("url") or "").strip().lower()
                        if u_key and u_key in seen_urls:
                            continue
                        if u_key:
                            seen_urls.add(u_key)
                        merged_results.append(item)
                elif sub_res.get("error"):
                    prov_errs.append(f"{sq}: {sub_res['error']}")
            if merged_results or raw_out.get("ok"):
                raw_out = {
                    "ok": True,
                    "providers_queried": provs_q,
                    "provider_errors": prov_errs[:4],
                    "query": base_query,
                    "sub_queries_executed": executed_queries,
                    "retrieved_at": raw_out.get("retrieved_at") or _now_iso(),
                    "results": merged_results[:10],
                }
            elif prov_errs:
                raw_out = {"ok": False, "error": "; ".join(prov_errs[:2])}
    elif tool_id == "doc_fetch":
        raw_out = _run_doc_fetch(str(tool_input.get("url", "")), allowlist)
    elif tool_id == "workspace_file_read":
        raw_out = _run_workspace_file_tool(data_dir, tool_input, approved_by)
    elif tool_id == "calc_ast":
        expr = str(tool_input.get("expression", "")).strip()
        calc_res = calc_fn(expr) if calc_fn else None
        raw_out = (
            {"ok": True, **calc_res}
            if calc_res
            else {"ok": False, "error": f"ไม่สามารถประมวลผลนิพจน์คำนวณ '{expr}' ผ่าน AST ได้"}
        )
    else:
        raw_out = {"ok": False, "error": f"ยังไม่มีตัวดำเนินการสำหรับ '{tool_id}'"}

    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    status = "COMPLETED" if raw_out.get("ok") else "FAILED"
    analysis_obj = (
        analyze_tool_result(conn, tool_id, raw_out, tokenize_fn, extract_terms_fn, query_kg_fn)
        if (raw_out.get("ok") and tokenize_fn and extract_terms_fn and query_kg_fn)
        else {"summary": str(raw_out.get("error", "")), "trust_grade": "FAILED", "limitations": []}
    )
    analysis_summary = analysis_obj.get("summary", "")

    now = _now_iso()
    inv_id = existing_invocation_id or str(uuid.uuid4())
    with conn:
        if raw_out.get("ok"):
            conn.execute(
                "UPDATE external_tools SET calls_today = calls_today + 1, last_reset_date=?, updated_at=? WHERE id=?",
                (today, now, tool_id),
            )
        if existing_invocation_id:
            conn.execute(
                """
                UPDATE tool_invocations
                SET status=?, output_json=?, analysis_summary=?, approved_by=?, latency_ms=?, updated_at=?
                WHERE id=?
                """,
                (
                    status,
                    json.dumps(raw_out, ensure_ascii=False),
                    analysis_summary,
                    approved_by,
                    latency_ms,
                    now,
                    inv_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO tool_invocations (id, tool_id, conversation_id, user_id, status, input_json, output_json, analysis_summary, approved_by, latency_ms, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    inv_id,
                    tool_id,
                    conversation_id,
                    user_id,
                    status,
                    json.dumps(tool_input, ensure_ascii=False),
                    json.dumps(raw_out, ensure_ascii=False),
                    analysis_summary,
                    approved_by,
                    latency_ms,
                    now,
                    now,
                ),
            )
        _log_tool_audit(
            conn,
            user_id,
            f"TOOL_EXEC_{tool_id.upper()}",
            inv_id,
            status,
            {"trust_grade": analysis_obj.get("trust_grade"), "approved_by": approved_by},
        )

    row = dict(conn.execute("SELECT * FROM tool_invocations WHERE id=?", (inv_id,)).fetchone())
    return {
        "ok": True,
        "status": status,
        "invocation": row,
        "raw_output": raw_out,
        "analysis": analysis_obj,
        "tool": dict(tool_row),
    }


def format_tool_markdown(tool_id: str, inv_result: dict) -> str:
    st = inv_result["status"]
    tool = inv_result["tool"]
    if st == "BLOCKED":
        return (
            f"**เครื่องมือ `{tool['name']}` ถูกปิดสิทธิ์การใช้งาน (BLOCKED)**\n\n"
            f"ผู้ดูแลระบบหรือนโยบายความปลอดภัยระงับการเรียกใช้เครื่องมือนี้ไว้ สามารถตรวจสอบสิทธิ์ได้ที่ **ตั้งค่า → นักพัฒนา**"
        )
    if st == "PENDING_APPROVAL":
        inv = inv_result["invocation"]
        return (
            f"**รอการอนุมัติก่อนเรียกใช้เครื่องมือภายนอก (Approval Gate: PENDING_APPROVAL)**\n\n"
            f"- เครื่องมือ: `{tool['name']}` (`{tool_id}`)\n"
            f"- ข้อมูลนำเข้า: `{inv['input_json']}`\n"
            f"- รหัสคำขอ: `{inv['id'][:8]}`\n\n"
            f"ZYRQUEN Native Core หยุดรอผู้ดูแลระบบอนุมัติใน **ตั้งค่า → ผู้ดูแลระบบ → Tool Approval Gate** เพื่อความปลอดภัยก่อนส่งคำขอหรือแก้ไขข้อมูล"
        )
    if st == "FAILED":
        err = inv_result.get("raw_output", {}).get("error", "ไม่ทราบสาเหตุ")
        return f"**เครื่องมือ `{tool['name']}` ดำเนินการไม่สำเร็จ:** {err}"

    raw = inv_result.get("raw_output", {})
    analysis = inv_result.get("analysis", {})
    trust_grade = analysis.get("trust_grade", "UNKNOWN")
    lines = [
        f"**ผลสังเคราะห์หลักฐานโดย ZYRQUEN Native Core** (`{tool['name']}` · ระดับความน่าเชื่อถือ: `{trust_grade}`)",
        "",
        f"> {analysis.get('summary', '')}",
        "",
    ]

    if analysis.get("cross_source_shared_terms"):
        lines.append(
            f"- คำสำคัญที่สอดคล้องข้ามแหล่งข้อมูล: `{', '.join(analysis['cross_source_shared_terms'])}`"
        )

    if tool_id == "web_search":
        results = raw.get("results", [])
        if not results:
            lines.append("- ไม่พบรายการค้นหาสาธารณะที่ตรงคำค้น")
        for r in results:
            lines.append(
                f"- **[{r.get('provider', 'web')}] {r['title']}**: {r['snippet']} (`{r['url']}`)"
            )
    elif tool_id == "doc_fetch":
        lines.append(f"- แหล่งที่มา: `{raw.get('url', '')}`")
        if raw.get("title"):
            lines.append(f"- ชื่อเอกสาร: **{raw['title']}**")
        if raw.get("headings"):
            lines.append(f"- หัวข้อหลักในเอกสาร: {', '.join(raw['headings'][:4])}")
        excerpt = str(raw.get("excerpt", ""))[:900]
        lines.append(f"\n{excerpt}")
    elif tool_id == "workspace_file_read":
        if raw.get("action") == "list":
            for f in raw.get("files", []):
                lines.append(f"- `{f['name']}` ({f['size_bytes']} bytes)")
        elif raw.get("action") == "write":
            lines.append(
                f"- บันทึกไฟล์ `{raw.get('filename')}` เรียบร้อยแล้ว ({raw.get('size_bytes')} bytes)"
            )
        elif raw.get("action") == "analyze_dataset":
            lines.append(f"- ไฟล์ข้อมูล: `{raw.get('filename')}` · รูปแบบ `{raw.get('format')}` · จำนวน `{raw.get('rows')}` แถว")
            if raw.get("columns"):
                lines.append(f"- คอลัมน์: `{', '.join(raw['columns'][:12])}`")
            if raw.get("missing_counts"):
                lines.append(f"- ค่าว่าง/หายไป: `{json.dumps(raw['missing_counts'], ensure_ascii=False)}`")
            if raw.get("numeric_summary"):
                for col, st_obj in list(raw["numeric_summary"].items())[:5]:
                    lines.append(f"- สถิติคอลัมน์ `{col}`: min `{st_obj['min']}`, max `{st_obj['max']}`, mean `{st_obj['mean']}`")
            for iss in (raw.get("issues") or []):
                lines.append(f"- ประเด็นที่ตรวจพบ: {iss}")
        elif raw.get("action") == "inspect":
            lines.append(f"- ไฟล์: `{raw.get('filename')}` ({raw.get('language')}, {raw.get('line_count')} บรรทัด)")
            if raw.get("symbols"):
                lines.append(f"- สัญลักษณ์/หัวข้อที่พบ: `{', '.join(raw['symbols'][:8])}`")
            if raw.get("defects"):
                for d in raw["defects"][:8]:
                    lines.append(f"- บรรทัด {d.get('line', '?')} [{d.get('severity', 'info')}]: {d.get('message')}")
            else:
                lines.append("- ไม่พบข้อผิดพลาดเชิงไวยากรณ์หรือโครงสร้าง")
        else:
            lines.append(f"- ไฟล์: `{raw.get('filename')}` ({raw.get('size_bytes')} bytes)")
            lines.append(f"\n```\n{str(raw.get('content', ''))[:1200]}\n```")
    elif tool_id == "calc_ast":
        lines.append(f"- ผลลัพธ์คำนวณ: `{raw.get('result')}`")

    if analysis.get("kg_matches"):
        lines.append("\n**เชื่อมโยงกับกราฟความรู้ภายใน ZYRQUEN:**")
        for kg in analysis["kg_matches"]:
            lines.append(f"- `{kg['subject']}` — *{kg['relation']}* → `{kg['object']}`")

    limitations = analysis.get("limitations") or []
    if limitations:
        lines.append("\n**ข้อจำกัดและคำเตือนความน่าเชื่อถือของข้อมูล:**")
        for lim in limitations:
            lines.append(f"- {lim}")

    return "\n".join(lines)
