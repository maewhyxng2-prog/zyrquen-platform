"""
Data Toolkit for ZYRQUEN Tool Center.
Binds DatasetLeakageDetector, deterministic CSV/JSON profiling, and AST Math/Stats engine.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import statistics
import xml.etree.ElementTree as ET
from typing import Any

from apps.core.dataset_leakage_detector import DatasetLeakageDetector
import tools_engine as te
import zyrquen_core as zc

from ..contracts import CapabilitySpec, ToolkitManifest


def _parse_xml_records(raw_xml: str) -> list[dict[str, Any]]:
    root = ET.fromstring(raw_xml)
    children = list(root)
    if not children:
        rec = dict(root.attrib)
        if root.text and root.text.strip():
            rec["text"] = root.text.strip()
        return [rec] if rec else []
    rows: list[dict[str, Any]] = []
    for child in children:
        row: dict[str, Any] = dict(child.attrib)
        sub_children = list(child)
        if sub_children:
            for sc in sub_children:
                row[sc.tag] = (sc.text or "").strip()
        elif child.text and child.text.strip():
            row[child.tag] = child.text.strip()
        rows.append(row)
    return rows


def _handle_leakage_check(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    train = payload.get("train") or []
    validation = payload.get("validation") or []
    test = payload.get("test") or []
    if not isinstance(train, list) or not isinstance(validation, list) or not isinstance(test, list):
        return {
            "ok": False,
            "status": "FAILED",
            "error": "train, validation, and test must be arrays of text/records.",
            "output": {},
        }
    if not train and not validation and not test:
        return {
            "ok": False,
            "status": "FAILED",
            "error": "At least one split must be non-empty.",
            "output": {},
        }

    detector = DatasetLeakageDetector()
    split_payload: dict[str, list[Any]] = {}
    if test:
        split_payload["test"] = test
    report = detector.check_entries(
        split_payload,
        reference_splits={"train": train, "validation": validation},
        check_internal_splits=True,
    )
    seen_norm: set[str] = set()
    train_dups = 0
    for item in train:
        norm = " ".join(str(item).lower().split())
        if norm in seen_norm:
            train_dups += 1
        seen_norm.add(norm)

    cross_matches = [m.to_dict() for m in report.matches]
    leakage_found = not report.passed

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "leakage_detected": leakage_found,
            "cross_split_matches": cross_matches[:25],
            "cross_split_match_count": len(cross_matches),
            "exact_matches": report.exact_matches,
            "near_duplicate_matches": report.near_duplicate_matches,
            "structural_matches": report.structural_matches,
            "violations": report.violations,
            "train_internal_duplicates": train_dups,
            "counts": {"train": len(train), "validation": len(validation), "test": len(test)},
            "test_report": {
                "leakage_detected": leakage_found,
                "match_count": len(cross_matches),
            },
        },
        "summary": (
            f"ตรวจพบ Data Leakage ข้ามชุดข้อมูล {len(cross_matches)} รายการ"
            if leakage_found
            else f"ผ่านการตรวจ Data Leakage (Train {len(train)}, Val {len(validation)}, Test {len(test)}, ซ้ำใน Train {train_dups})"
        ),
    }


def _parse_structured_rows(raw_content: str, fmt: str) -> tuple[str, list[dict[str, Any]]]:
    detected_fmt = fmt
    rows: list[dict[str, Any]] = []
    if fmt == "auto":
        if raw_content.startswith("<"):
            detected_fmt = "xml"
        elif raw_content.startswith("[") or raw_content.startswith("{"):
            detected_fmt = "json"
        elif "," in raw_content.splitlines()[0]:
            detected_fmt = "csv"
        else:
            detected_fmt = "jsonl"

    if detected_fmt == "xml":
        rows = _parse_xml_records(raw_content)
    elif detected_fmt == "json":
        parsed = json.loads(raw_content)
        if isinstance(parsed, list):
            rows = [r if isinstance(r, dict) else {"value": r} for r in parsed]
        elif isinstance(parsed, dict):
            rows = [parsed]
        else:
            rows = [{"value": parsed}]
    elif detected_fmt == "jsonl":
        for line in raw_content.splitlines():
            s = line.strip()
            if s:
                obj = json.loads(s)
                rows.append(obj if isinstance(obj, dict) else {"value": obj})
    else:
        reader = csv.DictReader(io.StringIO(raw_content))
        rows = [dict(r) for r in reader]
    return detected_fmt, rows


def _handle_profile_structured(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    raw_content = str(payload.get("content") or "").strip()
    fmt = str(payload.get("format") or "auto").strip().lower()
    if not raw_content:
        return {"ok": False, "status": "FAILED", "error": "content is required.", "output": {}}

    try:
        detected_fmt, rows = _parse_structured_rows(raw_content, fmt)
    except Exception as exc:
        return {"ok": False, "status": "FAILED", "error": f"Failed to parse {fmt}: {exc}", "output": {}}

    columns: list[str] = []
    seen_cols: set[str] = set()
    for row in rows:
        for k in row.keys():
            if k not in seen_cols:
                seen_cols.add(k)
                columns.append(str(k))

    missing_by_col: dict[str, int] = {c: 0 for c in columns}
    numeric_by_col: dict[str, list[float]] = {c: [] for c in columns}
    seen_rows: set[str] = set()
    duplicate_rows = 0

    for row in rows:
        canonical = json.dumps(row, sort_keys=True, ensure_ascii=False)
        if canonical in seen_rows:
            duplicate_rows += 1
        seen_rows.add(canonical)
        for col in columns:
            val = row.get(col)
            if val is None or (isinstance(val, str) and not val.strip()):
                missing_by_col[col] += 1
                continue
            try:
                num = float(val)
                if math.isfinite(num):
                    numeric_by_col[col].append(num)
            except (TypeError, ValueError):
                pass

    numeric_stats: dict[str, dict[str, float | int]] = {}
    for col, nums in numeric_by_col.items():
        if len(nums) >= 1:
            numeric_stats[col] = {
                "count": len(nums),
                "min": min(nums),
                "max": max(nums),
                "mean": round(statistics.mean(nums), 4),
                "stdev": round(statistics.stdev(nums), 4) if len(nums) > 1 else 0.0,
            }

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "format": detected_fmt,
            "row_count": len(rows),
            "columns": columns,
            "duplicate_rows": duplicate_rows,
            "missing_counts": missing_by_col,
            "numeric_stats": numeric_stats,
        },
        "summary": (
            f"วิเคราะห์ข้อมูล {detected_fmt.upper()}: {len(rows)} แถว, {len(columns)} คอลัมน์, "
            f"ซ้ำ {duplicate_rows} แถว"
        ),
    }


def _handle_transform(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    raw_content = str(payload.get("content") or "").strip()
    source_format = str(payload.get("source_format") or "auto").strip().lower()
    target_format = str(payload.get("target_format") or "json").strip().lower()
    deduplicate = bool(payload.get("deduplicate", False))
    if not raw_content:
        return {"ok": False, "status": "FAILED", "error": "content is required.", "output": {}}

    try:
        detected_fmt, rows = _parse_structured_rows(raw_content, source_format)
    except Exception as exc:
        return {"ok": False, "status": "FAILED", "error": f"Transform parse failed: {exc}", "output": {}}

    if deduplicate:
        seen: set[str] = set()
        unique_rows: list[dict[str, Any]] = []
        for r in rows:
            canon = json.dumps(r, sort_keys=True, ensure_ascii=False)
            if canon not in seen:
                seen.add(canon)
                unique_rows.append(r)
        rows = unique_rows

    if target_format == "jsonl":
        transformed = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    elif target_format == "csv":
        cols: list[str] = []
        for r in rows:
            for k in r.keys():
                if k not in cols:
                    cols.append(str(k))
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols)
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c, "") for c in cols})
        transformed = buf.getvalue().strip()
    else:
        target_format = "json"
        transformed = json.dumps(rows, ensure_ascii=False, indent=2)

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "source_format": detected_fmt,
            "target_format": target_format,
            "record_count": len(rows),
            "transformed_content": transformed,
        },
        "summary": f"แปลงข้อมูล {detected_fmt.upper()} → {target_format.upper()} จำนวน {len(rows)} รายการสำเร็จ",
    }


def _handle_db_inspect(_payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    conn = ctx.get("conn")
    if conn is None:
        return {"ok": False, "status": "BLOCKED", "error": "Database connection unavailable.", "output": {}}

    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name ASC"
        ).fetchall()
    ]
    counts: dict[str, int] = {}
    for tbl in tables:
        if tbl.replace("_", "").isalnum():
            counts[tbl] = int(conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0])

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "table_count": len(tables),
            "tables": tables,
            "row_counts": counts,
        },
        "summary": f"ตรวจสอบฐานข้อมูล SQLite: พบ {len(tables)} ตาราง",
    }


def _handle_calc_ast(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    expr = str(payload.get("expression") or "").strip()
    if not expr:
        return {"ok": False, "status": "FAILED", "error": "expression is required.", "output": {}}
    calc_res = zc._calc_any_for_tool(expr)
    if not isinstance(calc_res, dict) or (calc_res.get("ok") is False):
        return {
            "ok": False,
            "status": "FAILED",
            "error": str((calc_res or {}).get("error") or "Unable to evaluate expression deterministically"),
            "output": calc_res if isinstance(calc_res, dict) else {},
        }
    out_obj = {**calc_res, "ok": True}
    val_repr = out_obj.get("result", out_obj.get("mean", out_obj.get("solutions", "")))
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": out_obj,
        "summary": str(out_obj.get("summary") or f"คำนวณ AST สำเร็จ: {val_repr}"),
    }


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?$")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _infer_scalar_type(val: Any) -> str:
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, int):
        return "integer"
    if isinstance(val, float):
        return "float" if math.isfinite(val) else "string"
    s = str(val).strip()
    if not s:
        return "null"
    if s.lower() in {"true", "false"}:
        return "boolean"
    if re.fullmatch(r"[+-]?\d+", s):
        return "integer"
    if re.fullmatch(r"[+-]?(?:\d+\.\d+|\d*\.\d+)", s):
        return "float"
    if _ISO_DATE_RE.match(s):
        return "iso_date"
    if _EMAIL_RE.match(s):
        return "email"
    return "string"


def _handle_schema_inference(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    raw_content = str(payload.get("content") or "").strip()
    fmt = str(payload.get("format") or "auto").strip().lower()
    if not raw_content:
        return {"ok": False, "status": "FAILED", "error": "content is required.", "output": {}}
    try:
        detected_fmt, rows = _parse_structured_rows(raw_content, fmt)
    except Exception as exc:
        return {"ok": False, "status": "FAILED", "error": f"Schema parse failed: {exc}", "output": {}}

    cols: list[str] = []
    for r in rows:
        for k in r.keys():
            if str(k) not in cols:
                cols.append(str(k))

    fields: list[dict[str, Any]] = []
    pk_candidates: list[str] = []
    for col in cols:
        observed_types: set[str] = set()
        non_null_vals: list[str] = []
        null_count = 0
        for r in rows:
            t = _infer_scalar_type(r.get(col))
            if t == "null":
                null_count += 1
            else:
                observed_types.add(t)
                non_null_vals.append(str(r.get(col)).strip())

        if not observed_types:
            inferred = "null"
        elif observed_types == {"integer"}:
            inferred = "integer"
        elif observed_types <= {"integer", "float"}:
            inferred = "float"
        elif len(observed_types) == 1:
            inferred = next(iter(observed_types))
        else:
            inferred = "mixed"

        distinct = len(set(non_null_vals))
        is_unique_nonnull = len(rows) > 0 and null_count == 0 and distinct == len(rows)
        if is_unique_nonnull and inferred in {"integer", "string"}:
            pk_candidates.append(col)

        fields.append({
            "name": col,
            "inferred_type": inferred,
            "observed_types": sorted(observed_types),
            "nullable": null_count > 0,
            "null_count": null_count,
            "distinct_count": distinct,
            "unique": is_unique_nonnull,
            "sample_values": non_null_vals[:3],
        })

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "format": detected_fmt,
            "row_count": len(rows),
            "column_count": len(fields),
            "fields": fields,
            "primary_key_candidates": pk_candidates,
        },
        "summary": f"อนุมาน Schema สำเร็จ ({detected_fmt.upper()}): {len(fields)} คอลัมน์, {len(rows)} แถว",
    }


def _handle_duplicate_detection(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    raw_content = str(payload.get("content") or "").strip()
    fmt = str(payload.get("format") or "auto").strip().lower()
    key_fields = [str(k).strip() for k in (payload.get("key_fields") or []) if str(k).strip()]
    similarity_threshold = float(payload.get("similarity_threshold") or 0.85)
    if not raw_content:
        return {"ok": False, "status": "FAILED", "error": "content is required.", "output": {}}
    try:
        detected_fmt, rows = _parse_structured_rows(raw_content, fmt)
    except Exception as exc:
        return {"ok": False, "status": "FAILED", "error": f"Duplicate parse failed: {exc}", "output": {}}

    exact_seen: dict[str, list[int]] = {}
    key_seen: dict[str, list[int]] = {}
    row_tokens: list[set[str]] = []

    for idx, row in enumerate(rows):
        canon = json.dumps(row, sort_keys=True, ensure_ascii=False)
        exact_seen.setdefault(canon, []).append(idx)
        if key_fields:
            k_canon = json.dumps({kf: str(row.get(kf) or "").strip().lower() for kf in key_fields}, sort_keys=True, ensure_ascii=False)
            key_seen.setdefault(k_canon, []).append(idx)
        text_blob = " ".join(str(v or "").lower() for v in row.values())
        row_tokens.append(set(re.findall(r"[a-z0-9_\u0E00-\u0E7F]+", text_blob)))

    exact_groups = [idxs for idxs in exact_seen.values() if len(idxs) > 1]
    key_groups = [idxs for idxs in key_seen.values() if len(idxs) > 1] if key_fields else []

    near_pairs: list[dict[str, Any]] = []
    limit_n = min(len(rows), 250)
    for i in range(limit_n):
        for j in range(i + 1, limit_n):
            if json.dumps(rows[i], sort_keys=True) == json.dumps(rows[j], sort_keys=True):
                continue
            union = row_tokens[i] | row_tokens[j]
            if not union:
                continue
            jaccard = len(row_tokens[i] & row_tokens[j]) / len(union)
            if jaccard >= similarity_threshold:
                near_pairs.append({"row_a": i, "row_b": j, "similarity": round(jaccard, 4)})
                if len(near_pairs) >= 50:
                    break
        if len(near_pairs) >= 50:
            break

    has_dups = bool(exact_groups or key_groups or near_pairs)
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "format": detected_fmt,
            "row_count": len(rows),
            "duplicates_found": has_dups,
            "exact_duplicate_groups": exact_groups[:30],
            "exact_duplicate_count": sum(len(g) - 1 for g in exact_groups),
            "key_duplicate_groups": key_groups[:30],
            "near_duplicate_pairs": near_pairs,
        },
        "summary": (
            f"ตรวจจับข้อมูลซ้ำใน {len(rows)} แถว: ซ้ำตรง {sum(len(g) - 1 for g in exact_groups)}, "
            f"ซ้ำตามคีย์ {sum(len(g) - 1 for g in key_groups)}, ใกล้เคียง {len(near_pairs)} คู่"
        ),
    }


def _handle_anomaly_detection(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    raw_content = str(payload.get("content") or "").strip()
    fmt = str(payload.get("format") or "auto").strip().lower()
    z_thresh = float(payload.get("z_threshold") or 2.5)
    if not raw_content:
        return {"ok": False, "status": "FAILED", "error": "content is required.", "output": {}}
    try:
        detected_fmt, rows = _parse_structured_rows(raw_content, fmt)
    except Exception as exc:
        return {"ok": False, "status": "FAILED", "error": f"Anomaly parse failed: {exc}", "output": {}}

    cols: list[str] = []
    for r in rows:
        for k in r.keys():
            if str(k) not in cols:
                cols.append(str(k))

    anomalies: list[dict[str, Any]] = []
    for col in cols:
        nums: list[tuple[int, float]] = []
        type_counts: dict[str, int] = {}
        for idx, r in enumerate(rows):
            val = r.get(col)
            t = _infer_scalar_type(val)
            if t != "null":
                type_counts[t] = type_counts.get(t, 0) + 1
            try:
                num = float(val)
                if math.isfinite(num):
                    nums.append((idx, num))
            except (TypeError, ValueError):
                pass

        # Numeric IQR / Modified Z-score outliers
        if len(nums) >= 4:
            vals = sorted(v for _, v in nums)
            med = statistics.median(vals)
            deviations = sorted(abs(v - med) for v in vals)
            mad = statistics.median(deviations)
            q1 = vals[len(vals) // 4]
            q3 = vals[(3 * len(vals)) // 4]
            iqr = q3 - q1
            low_f = q1 - 1.5 * iqr
            high_f = q3 + 1.5 * iqr
            for idx, v in nums:
                mod_z = (0.6745 * abs(v - med) / mad) if mad > 0 else 0.0
                if (iqr > 0 and (v < low_f or v > high_f)) or mod_z >= z_thresh:
                    anomalies.append({
                        "row_index": idx,
                        "column": col,
                        "value": v,
                        "kind": "numeric_outlier",
                        "modified_z": round(mod_z, 3),
                        "detail": f"median={med}, bounds=[{round(low_f, 3)}, {round(high_f, 3)}]",
                    })

        # Type drift detection if one dominant type exists (>= 70%)
        total_non_null = sum(type_counts.values())
        if total_non_null >= 4 and len(type_counts) > 1:
            dominant_type, dominant_count = max(type_counts.items(), key=lambda kv: kv[1])
            if dominant_count / total_non_null >= 0.7:
                for idx, r in enumerate(rows):
                    t = _infer_scalar_type(r.get(col))
                    if t != "null" and t != dominant_type and not (dominant_type == "float" and t == "integer"):
                        anomalies.append({
                            "row_index": idx,
                            "column": col,
                            "value": r.get(col),
                            "kind": "type_drift",
                            "detail": f"expected {dominant_type}, got {t}",
                        })

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "format": detected_fmt,
            "row_count": len(rows),
            "anomaly_count": len(anomalies),
            "anomalies_detected": len(anomalies) > 0,
            "anomalies": anomalies[:100],
        },
        "summary": f"ตรวจความผิดปกติข้อมูล {len(rows)} แถว: พบ {len(anomalies)} รายการ",
    }


def _handle_semantic_validation(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    raw_content = str(payload.get("content") or "").strip()
    fmt = str(payload.get("format") or "auto").strip().lower()
    rules = payload.get("rules")
    if not raw_content or not isinstance(rules, dict):
        return {"ok": False, "status": "FAILED", "error": "content and rules object are required.", "output": {}}
    try:
        detected_fmt, rows = _parse_structured_rows(raw_content, fmt)
    except Exception as exc:
        return {"ok": False, "status": "FAILED", "error": f"Semantic parse failed: {exc}", "output": {}}

    required_fields = [str(f) for f in (rules.get("required_fields") or [])]
    ranges = rules.get("ranges") if isinstance(rules.get("ranges"), dict) else {}
    allowed_values = rules.get("allowed_values") if isinstance(rules.get("allowed_values"), dict) else {}
    patterns = rules.get("patterns") if isinstance(rules.get("patterns"), dict) else {}
    unique_fields = [str(f) for f in (rules.get("unique_fields") or [])]

    violations: list[dict[str, Any]] = []
    seen_unique: dict[str, set[str]] = {f: set() for f in unique_fields}

    for idx, row in enumerate(rows):
        for req_f in required_fields:
            val = row.get(req_f)
            if val is None or (isinstance(val, str) and not val.strip()):
                violations.append({"row_index": idx, "field": req_f, "rule": "required", "detail": "Missing required value"})

        for field_name, bounds in ranges.items():
            if not isinstance(bounds, dict) or field_name not in row:
                continue
            raw_v = row.get(field_name)
            if raw_v is None or (isinstance(raw_v, str) and not raw_v.strip()):
                continue
            try:
                num = float(raw_v)
                if "min" in bounds and num < float(bounds["min"]):
                    violations.append({"row_index": idx, "field": field_name, "rule": "min_range", "detail": f"{num} < {bounds['min']}"})
                if "max" in bounds and num > float(bounds["max"]):
                    violations.append({"row_index": idx, "field": field_name, "rule": "max_range", "detail": f"{num} > {bounds['max']}"})
            except (TypeError, ValueError):
                violations.append({"row_index": idx, "field": field_name, "rule": "numeric_expected", "detail": f"'{raw_v}' is not numeric"})

        for field_name, allowed in allowed_values.items():
            if isinstance(allowed, list) and field_name in row:
                val = row.get(field_name)
                if val is not None and str(val).strip() != "" and val not in allowed and str(val) not in [str(a) for a in allowed]:
                    violations.append({"row_index": idx, "field": field_name, "rule": "allowed_values", "detail": f"'{val}' not in {allowed}"})

        for field_name, pat in patterns.items():
            if field_name in row and row.get(field_name) is not None:
                sval = str(row.get(field_name))
                if sval and not re.match(str(pat), sval):
                    violations.append({"row_index": idx, "field": field_name, "rule": "pattern", "detail": f"'{sval}' did not match /{pat}/"})

        for uf in unique_fields:
            val = str(row.get(uf) or "").strip()
            if val:
                if val in seen_unique[uf]:
                    violations.append({"row_index": idx, "field": uf, "rule": "unique", "detail": f"Duplicate key '{val}'"})
                seen_unique[uf].add(val)

    valid = len(violations) == 0
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "format": detected_fmt,
            "row_count": len(rows),
            "valid": valid,
            "violation_count": len(violations),
            "violations": violations[:100],
        },
        "summary": f"ตรวจสอบกฎ Semantic ({len(rows)} แถว): {'ผ่านทั้งหมด' if valid else f'พบข้อละเมิด {len(violations)} รายการ'}",
    }


def _handle_dataset_lineage(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    conn = ctx.get("conn")
    if conn is None:
        return {"ok": False, "status": "BLOCKED", "error": "Database connection unavailable.", "output": {}}

    dataset_id = str(payload.get("dataset_id") or "").strip()
    has_tbl = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='datasets'").fetchone()
    if not has_tbl:
        return {"ok": True, "status": "COMPLETED", "output": {"datasets": [], "count": 0}, "summary": "ยังไม่มีตาราง datasets ในฐานข้อมูล"}

    if dataset_id:
        row = conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        if not row:
            return {"ok": False, "status": "FAILED", "error": f"Dataset '{dataset_id}' not found.", "output": {}}
        rows = [dict(row)]
    else:
        rows = [dict(r) for r in conn.execute("SELECT * FROM datasets ORDER BY created_at DESC LIMIT 20").fetchall()]

    lineages: list[dict[str, Any]] = []
    for r in rows:
        lineages.append({
            "dataset_id": r.get("id"),
            "name": r.get("name"),
            "format": r.get("format"),
            "status": r.get("status"),
            "sha256": r.get("sha256") or r.get("content_sha256"),
            "row_count": r.get("row_count") or r.get("rows_count"),
            "created_by": r.get("created_by"),
            "created_at": r.get("created_at"),
            "source_origin": r.get("source") or r.get("origin") or "ingested_dataset",
        })

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "count": len(lineages),
            "datasets": lineages,
        },
        "summary": f"ดึง Lineage ข้อมูลสำเร็จ {len(lineages)} ชุด",
    }


def _handle_dataset_version_compare(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    base_raw = str(payload.get("baseline_content") or "").strip()
    cand_raw = str(payload.get("candidate_content") or "").strip()
    fmt = str(payload.get("format") or "auto").strip().lower()
    if not base_raw or not cand_raw:
        return {"ok": False, "status": "FAILED", "error": "baseline_content and candidate_content are required.", "output": {}}
    try:
        fmt_a, rows_a = _parse_structured_rows(base_raw, fmt)
        fmt_b, rows_b = _parse_structured_rows(cand_raw, fmt)
    except Exception as exc:
        return {"ok": False, "status": "FAILED", "error": f"Dataset compare parse failed: {exc}", "output": {}}

    cols_a = sorted({str(k) for r in rows_a for k in r.keys()})
    cols_b = sorted({str(k) for r in rows_b for k in r.keys()})
    added_cols = sorted(set(cols_b) - set(cols_a))
    removed_cols = sorted(set(cols_a) - set(cols_b))

    sha_a = hashlib.sha256(base_raw.encode("utf-8")).hexdigest()
    sha_b = hashlib.sha256(cand_raw.encode("utf-8")).hexdigest()
    numeric_drift: dict[str, dict[str, float]] = {}
    for col in sorted(set(cols_a) & set(cols_b)):
        vals_a = [float(r[col]) for r in rows_a if col in r and _infer_scalar_type(r[col]) in {"integer", "float"}]
        vals_b = [float(r[col]) for r in rows_b if col in r and _infer_scalar_type(r[col]) in {"integer", "float"}]
        if vals_a and vals_b:
            ma = statistics.mean(vals_a)
            mb = statistics.mean(vals_b)
            numeric_drift[col] = {"baseline_mean": round(ma, 4), "candidate_mean": round(mb, 4), "mean_delta": round(mb - ma, 4)}

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "baseline_format": fmt_a,
            "candidate_format": fmt_b,
            "baseline_rows": len(rows_a),
            "candidate_rows": len(rows_b),
            "row_delta": len(rows_b) - len(rows_a),
            "added_columns": added_cols,
            "removed_columns": removed_cols,
            "identical_digest": sha_a == sha_b,
            "baseline_sha256": sha_a,
            "candidate_sha256": sha_b,
            "numeric_drift": numeric_drift,
        },
        "summary": f"เปรียบเทียบเวอร์ชันข้อมูล: แถว {len(rows_a)} -> {len(rows_b)}, คอลัมน์เพิ่ม {len(added_cols)} ลบ {len(removed_cols)}",
    }


def register_data_toolkit(registry: Any) -> None:
    manifest = ToolkitManifest(
        id="data",
        name="Data Toolkit",
        thai_name="ชุดเครื่องมือข้อมูลและการคำนวณ",
        version="1.2.0",
        description="ประมวลผล CSV/JSON/XML, อนุมาน Schema, ตรวจซ้ำ/ผิดปกติ/กฎ Semantic, เปรียบเทียบเวอร์ชัน, Lineage และ AST/Leakage",
        category="data",
        dependencies=("apps.core.dataset_leakage_detector", "python_core.zyrquen_core"),
        default_permission="auto",
        lifecycle_status="READY",
        bound_modules=(
            "apps/core/dataset_leakage_detector.py",
            "python_core/dataset_ingestion.py",
            "python_core/zyrquen_core.py",
        ),
        documentation="ประมวลผล ตรวจสอบคุณภาพ อนุมานโครงสร้าง ตรวจความผิดปกติและ Lineage ของข้อมูลแบบอ่านอย่างเดียว",
    )

    specs = [
        (
            CapabilitySpec(
                id="data.leakage_check",
                toolkit_id="data",
                name="ตรวจจับ Data Leakage ข้ามชุดข้อมูล",
                version="1.0.0",
                description="ใช้ Semantic Hashing + Exact Digest + Slot-Masked Hash ตรวจสอบการปนเปื้อนระหว่าง Train, Validation และ Test",
                input_schema={
                    "type": "object",
                    "required": ["train"],
                    "properties": {
                        "train": {"type": "array"},
                        "validation": {"type": "array"},
                        "test": {"type": "array"},
                    },
                },
                output_schema={"type": "object", "required": ["leakage_detected", "cross_split_match_count", "counts"]},
                dependencies=("apps.core.dataset_leakage_detector",),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("apps/core/dataset_leakage_detector.py",),
                documentation="ส่งอาร์เรย์ train, validation, test เพื่อตรวจหา Exact Duplicate และ Near-Duplicate ข้าม Split",
                example_input={
                    "train": ["alpha sample record one", "beta sample record two"],
                    "validation": ["gamma validation record"],
                    "test": ["delta unseen test record"],
                },
                keywords=("data", "leakage", "dataset", "split", "train", "ข้อมูล", "ชุดข้อมูล"),
            ),
            _handle_leakage_check,
        ),
        (
            CapabilitySpec(
                id="data.profile_structured",
                toolkit_id="data",
                name="วิเคราะห์และทำโปรไฟล์ CSV / JSON / JSONL / XML",
                version="1.1.0",
                description="แยกคอลัมน์ นับค่าว่าง ตรวจแถวซ้ำ และสรุปสถิติเชิงตัวเลข (min/max/mean/stdev) จากข้อมูลจริง",
                input_schema={
                    "type": "object",
                    "required": ["content"],
                    "properties": {
                        "content": {"type": "string"},
                        "format": {"type": "string", "enum": ["auto", "csv", "json", "jsonl", "xml"]},
                    },
                },
                output_schema={"type": "object", "required": ["format", "row_count", "columns", "duplicate_rows"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/dataset_ingestion.py",),
                documentation="ส่งเนื้อหา CSV, JSON, JSONL หรือ XML เพื่อวิเคราะห์โครงสร้างและคุณภาพข้อมูล",
                example_input={"format": "csv", "content": "name,score\nalice,92\nbob,85\nbob,85"},
                keywords=("csv", "json", "xml", "profile", "data", "stats", "ข้อมูล", "ตาราง", "สถิติ"),
            ),
            _handle_profile_structured,
        ),
        (
            CapabilitySpec(
                id="data.transform",
                toolkit_id="data",
                name="แปลงและทำความสะอาดข้อมูล (Data Transformation)",
                version="1.0.0",
                description="แปลงรูปแบบระหว่าง CSV, JSON, JSONL และ XML พร้อมตัวเลือกลบแถวซ้ำเชิงกำหนด",
                input_schema={
                    "type": "object",
                    "required": ["content"],
                    "properties": {
                        "content": {"type": "string"},
                        "source_format": {"type": "string", "enum": ["auto", "csv", "json", "jsonl", "xml"]},
                        "target_format": {"type": "string", "enum": ["json", "jsonl", "csv"]},
                        "deduplicate": {"type": "boolean"},
                    },
                },
                output_schema={"type": "object", "required": ["source_format", "target_format", "record_count", "transformed_content"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/data.py",),
                documentation="แปลงโครงสร้างข้อมูลระหว่าง CSV/JSON/JSONL/XML และคัดกรองข้อมูลซ้ำ",
                example_input={"content": "name,score\nalice,90\nalice,90", "target_format": "json", "deduplicate": True},
                keywords=("transform", "convert", "csv", "json", "xml", "แปลงข้อมูล"),
            ),
            _handle_transform,
        ),
        (
            CapabilitySpec(
                id="data.db_inspect",
                toolkit_id="data",
                name="ตรวจสอบโครงสร้างฐานข้อมูล SQLite (Read-Only)",
                version="1.0.0",
                description="อ่านรายชื่อตารางและจำนวนแถวจริงจาก SQLite ภายในระบบโดยไม่อนุญาต SQL ที่แก้ไขข้อมูล",
                input_schema={"type": "object", "required": [], "properties": {}},
                output_schema={"type": "object", "required": ["table_count", "tables", "row_counts"]},
                dependencies=("python_core.zyrquen_core",),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/zyrquen_core.py",),
                documentation="แสดงรายการตารางและจำนวนระเบียนปัจจุบันในฐานข้อมูลหลัก",
                example_input={},
                keywords=("database", "sqlite", "tables", "ฐานข้อมูล"),
            ),
            _handle_db_inspect,
        ),
        (
            CapabilitySpec(
                id="data.calc_ast",
                toolkit_id="data",
                name="คำนวณ AST / แก้สมการ / สถิติเชิงกำหนด",
                version="1.0.0",
                description="ประมวลผลนิพจน์คณิตศาสตร์ สมการเชิงเส้น/กำลังสอง และสถิติผ่านตัวคำนวณ AST ภายในเครื่อง",
                input_schema={
                    "type": "object",
                    "required": ["expression"],
                    "properties": {"expression": {"type": "string"}},
                },
                output_schema={"type": "object", "required": ["ok"]},
                dependencies=("python_core.zyrquen_core",),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/zyrquen_core.py", "python_core/tools_engine.py"),
                documentation="ตัวอย่าง: '(2^12 - 96) / 16', 'แก้สมการ: 3x + 7 = 22', 'สถิติ: 10, 20, 30'",
                example_input={"expression": "(2^12 - 96) / 16"},
                keywords=("math", "calc", "ast", "equation", "statistics", "คำนวณ", "สมการ", "สถิติ"),
            ),
            _handle_calc_ast,
        ),
        (
            CapabilitySpec(
                id="data.schema_inference",
                toolkit_id="data",
                name="อนุมานโครงสร้างข้อมูลอัตโนมัติ (Schema Inference)",
                version="1.0.0",
                description="อนุมานชนิดข้อมูล (integer, float, boolean, iso_date, email, string), ค่าว่าง และคีย์หลักที่เหมาะสมจาก CSV/JSON/XML",
                input_schema={
                    "type": "object",
                    "required": ["content"],
                    "properties": {
                        "content": {"type": "string"},
                        "format": {"type": "string", "enum": ["auto", "csv", "json", "jsonl", "xml"]},
                    },
                },
                output_schema={"type": "object", "required": ["format", "row_count", "column_count", "fields"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/data.py",),
                documentation="วิเคราะห์โครงสร้างและชนิดข้อมูลแต่ละคอลัมน์เชิงกำหนด",
                example_input={"content": "id,email,score\n1,a@b.com,9.5\n2,c@d.com,8.0"},
                keywords=("schema", "infer", "types", "columns", "โครงสร้างข้อมูล"),
            ),
            _handle_schema_inference,
        ),
        (
            CapabilitySpec(
                id="data.duplicate_detection",
                toolkit_id="data",
                name="ตรวจจับข้อมูลซ้ำและใกล้เคียงภายในชุดข้อมูล (Duplicate Detection)",
                version="1.0.0",
                description="ตรวจหาแถวซ้ำตรง, ซ้ำตาม key_fields และใกล้เคียงกันด้วย Jaccard similarity ภายในชุดข้อมูลเดียว",
                input_schema={
                    "type": "object",
                    "required": ["content"],
                    "properties": {
                        "content": {"type": "string"},
                        "format": {"type": "string"},
                        "key_fields": {"type": "array"},
                        "similarity_threshold": {"type": "number"},
                    },
                },
                output_schema={"type": "object", "required": ["duplicates_found", "exact_duplicate_count", "near_duplicate_pairs"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/data.py",),
                documentation="ตรวจข้อมูลซ้ำภายในชุดเดียว (ต่างจาก leakage_check ที่ตรวจข้าม Train/Val/Test)",
                example_input={"content": "id,name\n1,Alpha\n1,Alpha\n2,Beta"},
                keywords=("duplicate", "dedup", "near-duplicate", "ข้อมูลซ้ำ"),
            ),
            _handle_duplicate_detection,
        ),
        (
            CapabilitySpec(
                id="data.anomaly_detection",
                toolkit_id="data",
                name="ตรวจจับค่าผิดปกติและ Type Drift (Anomaly Detection)",
                version="1.0.0",
                description="ตรวจค่า Outlier ด้วย IQR และ Modified Z-Score พร้อมตรวจการเปลี่ยนชนิดข้อมูลในคอลัมน์",
                input_schema={
                    "type": "object",
                    "required": ["content"],
                    "properties": {
                        "content": {"type": "string"},
                        "format": {"type": "string"},
                        "z_threshold": {"type": "number"},
                    },
                },
                output_schema={"type": "object", "required": ["row_count", "anomaly_count", "anomalies_detected", "anomalies"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/data.py",),
                documentation="ค้นหา outlier ทางสถิติและ type drift ในตารางข้อมูล",
                example_input={"content": "id,val\n1,10\n2,11\n3,9\n4,12\n5,999"},
                keywords=("anomaly", "outlier", "iqr", "zscore", "ผิดปกติ"),
            ),
            _handle_anomaly_detection,
        ),
        (
            CapabilitySpec(
                id="data.semantic_validation",
                toolkit_id="data",
                name="ตรวจสอบกฎความถูกต้องเชิงความหมาย (Semantic Validation)",
                version="1.0.0",
                description="ตรวจข้อมูลเทียบกับกฎ required_fields, ranges, allowed_values, regex patterns และ unique_fields",
                input_schema={
                    "type": "object",
                    "required": ["content", "rules"],
                    "properties": {
                        "content": {"type": "string"},
                        "format": {"type": "string"},
                        "rules": {"type": "object"},
                    },
                },
                output_schema={"type": "object", "required": ["valid", "violation_count", "violations"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/data.py",),
                documentation="ระบุกฎเชิงธุรกิจเพื่อตรวจความถูกต้องของทุกแถว",
                example_input={"content": "age,role\n25,admin\n-3,guest", "rules": {"ranges": {"age": {"min": 0, "max": 120}}}},
                keywords=("semantic", "rules", "validation", "constraints", "ตรวจกฎข้อมูล"),
            ),
            _handle_semantic_validation,
        ),
        (
            CapabilitySpec(
                id="data.dataset_lineage",
                toolkit_id="data",
                name="ตรวจสอบประวัติและแหล่งที่มาชุดข้อมูล (Dataset Lineage)",
                version="1.0.0",
                description="อ่านเมตาดาตา แฮช SHA-256 ผู้สร้าง และแหล่งที่มาของชุดข้อมูลจากฐานข้อมูล SQLite",
                input_schema={"type": "object", "properties": {"dataset_id": {"type": "string"}}},
                output_schema={"type": "object", "required": ["count", "datasets"]},
                dependencies=("python_core.zyrquen_core",),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/data.py",),
                documentation="ติดตาม provenance และ checksum ของ dataset ที่นำเข้าในระบบ",
                example_input={},
                keywords=("lineage", "provenance", "dataset", "metadata", "แหล่งที่มา"),
            ),
            _handle_dataset_lineage,
        ),
        (
            CapabilitySpec(
                id="data.dataset_version_compare",
                toolkit_id="data",
                name="เปรียบเทียบความแตกต่างระหว่างชุดข้อมูล 2 เวอร์ชัน",
                version="1.0.0",
                description="เปรียบเทียบ schema, จำนวนแถว, SHA-256 digest และค่าเฉลี่ยเชิงตัวเลขระหว่าง baseline กับ candidate",
                input_schema={
                    "type": "object",
                    "required": ["baseline_content", "candidate_content"],
                    "properties": {
                        "baseline_content": {"type": "string"},
                        "candidate_content": {"type": "string"},
                        "format": {"type": "string"},
                    },
                },
                output_schema={"type": "object", "required": ["row_delta", "added_columns", "removed_columns", "identical_digest"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/data.py",),
                documentation="วัดความเปลี่ยนแปลงและ drift ระหว่างชุดข้อมูลสองเวอร์ชัน",
                example_input={"baseline_content": "k,v\na,10", "candidate_content": "k,v,note\na,20,ok"},
                keywords=("compare", "version", "diff", "drift", "เปรียบเทียบข้อมูล"),
            ),
            _handle_dataset_version_compare,
        ),
    ]

    registry.register_toolkit(manifest, specs)
