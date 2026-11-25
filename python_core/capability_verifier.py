#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — Real Capability Verification & 7-State Ledger
----------------------------------------------------------
Enforces the architectural mandate:
  REAL CAPABILITY — MEASURED, NOT DECLARED

Official 7-state taxonomy:
  - NOT_IMPLEMENTED   : No implementation exists
  - IMPLEMENTED       : Code exists, not yet measured
  - TESTED            : Passed scoped tests only (lacks E2E, unseen data, or postconditions)
  - PARTIAL           : Partially verified or blocked on optional external environment
  - VERIFIED          : Passed measured benchmark + unseen dataset + E2E + postconditions + no regression
  - BLOCKED           : Cannot execute or verify in current environment
  - REGRESSION_FAILED : Regressed relative to previously persisted baseline

Self-assessment cannot promote any domain to VERIFIED.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from typing import Any

CAPABILITY_STATUSES = (
    "NOT_IMPLEMENTED",
    "IMPLEMENTED",
    "TESTED",
    "PARTIAL",
    "VERIFIED",
    "BLOCKED",
    "REGRESSION_FAILED",
)

CAPABILITY_DOMAINS = (
    "native_core",
    "research",
    "planning",
    "memory",
    "learning",
    "autonomous_execution",
)

DOMAIN_LABELS = {
    "native_core": "Native Core (Cognition, Math, BPE, Neural, Abstention)",
    "research": "Autonomous Research (Query, Quarantine, Corroboration, Web)",
    "planning": "Strategic Planning & DAG Contracts",
    "memory": "5-Tier Memory & Knowledge Graph",
    "learning": "Controlled Self-Improvement & Generalization",
    "autonomous_execution": "Real-World Execution & Postconditions",
}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _evidence_digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def evaluate_domain_capability(
    domain: str,
    *,
    implemented: bool,
    case_records: list[dict[str, Any]],
    has_unseen_dataset: bool,
    leakage_detected: bool,
    has_e2e_probe: bool,
    has_postcondition_check: bool,
    blocked_dependencies: list[str] | None = None,
    disclosed_gaps: list[str] | None = None,
    previous_baseline: dict[str, Any] | None = None,
    self_declared_status: str | None = None,
) -> dict[str, Any]:
    """
    Deterministically compute a subsystem's capability status from real evidence.
    `self_declared_status` is ignored for promotion (enforcing anti-self-assessment).
    """
    if domain not in CAPABILITY_DOMAINS:
        raise ValueError(f"Unknown capability domain: {domain}")

    blocked = [b for b in (blocked_dependencies or []) if str(b).strip()]
    gaps = [g for g in (disclosed_gaps or []) if str(g).strip()]
    total = len(case_records)
    passed = sum(1 for c in case_records if c.get("passed"))
    failed = total - passed
    neg_cases = [c for c in case_records if c.get("polarity") == "negative"]
    false_positives = sum(1 for c in neg_cases if not c.get("passed"))
    score = round(passed / total, 4) if total > 0 else 0.0

    regressed = False
    regression_reasons: list[str] = []
    if previous_baseline is not None:
        prev_score = float(previous_baseline.get("score", 0.0))
        prev_fp = int(previous_baseline.get("false_positives", 0))
        prev_status = str(previous_baseline.get("status", ""))
        if prev_status in ("VERIFIED", "TESTED", "PARTIAL") and score < prev_score:
            regressed = True
            regression_reasons.append(f"Score regressed from {prev_score:.4f} to {score:.4f}")
        if false_positives > prev_fp:
            regressed = True
            regression_reasons.append(f"False positives increased from {prev_fp} to {false_positives}")

    if not implemented:
        status = "NOT_IMPLEMENTED"
    elif regressed:
        status = "REGRESSION_FAILED"
    elif total == 0:
        status = "BLOCKED" if blocked else "IMPLEMENTED"
    elif failed > 0:
        status = "PARTIAL" if passed > 0 else ("BLOCKED" if blocked else "PARTIAL")
    elif blocked:
        # All local/isolated probes passed, but an external dependency is blocked/offline
        status = "PARTIAL"
    elif has_unseen_dataset and not leakage_detected and has_e2e_probe and has_postcondition_check and false_positives == 0:
        status = "VERIFIED"
    else:
        # Passed scoped probes, but missing one of the strict VERIFIED prerequisites
        status = "TESTED"

    if not has_unseen_dataset:
        gaps.append("Missing unseen held-out evaluation dataset")
    if leakage_detected:
        gaps.append("Data leakage detected between training and evaluation datasets")
    if not has_e2e_probe:
        gaps.append("Missing End-to-End execution evidence")
    if not has_postcondition_check:
        gaps.append("Missing post-execution postcondition verification")
    for b in blocked:
        gaps.append(f"BLOCKED dependency: {b}")
    gaps.extend(regression_reasons)

    # Deduplicate gaps while preserving order
    unique_gaps: list[str] = []
    seen_g: set[str] = set()
    for g in gaps:
        if g not in seen_g:
            seen_g.add(g)
            unique_gaps.append(g)

    evidence_core = {
        "domain": domain,
        "status": status,
        "case_ids": [c.get("id") for c in case_records],
        "passed": passed,
        "total": total,
        "false_positives": false_positives,
        "score": score,
        "has_unseen_dataset": bool(has_unseen_dataset),
        "leakage_detected": bool(leakage_detected),
        "has_e2e_probe": bool(has_e2e_probe),
        "has_postcondition_check": bool(has_postcondition_check),
        "blocked_dependencies": blocked,
        "regressed": regressed,
    }

    return {
        "domain": domain,
        "label": DOMAIN_LABELS[domain],
        "status": status,
        "implemented": bool(implemented),
        "measured": total > 0,
        "passed": passed,
        "total": total,
        "failed": failed,
        "false_positives": false_positives,
        "score": score,
        "criteria": {
            "has_benchmark": total > 0,
            "has_unseen_dataset": bool(has_unseen_dataset) and not bool(leakage_detected),
            "has_e2e_probe": bool(has_e2e_probe),
            "has_postcondition_check": bool(has_postcondition_check),
            "zero_blocked_dependencies": len(blocked) == 0,
            "zero_regression": not regressed,
            "threshold_met": total > 0 and failed == 0 and false_positives == 0,
        },
        "self_assessment_blocked": True,
        "self_declared_ignored": bool(self_declared_status and self_declared_status != status),
        "blocked_dependencies": blocked,
        "disclosed_gaps": unique_gaps,
        "case_ids": [c.get("id") for c in case_records],
        "evidence_hash": _evidence_digest(evidence_core),
        "evaluated_at": _now_iso(),
    }


def build_capability_ledger(
    domain_specs: dict[str, dict[str, Any]],
    *,
    previous_baselines: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble the full 6-domain capability ledger enforcing REAL CAPABILITY rules."""
    prev_map = previous_baselines or {}
    domains: dict[str, dict[str, Any]] = {}
    counts = {st: 0 for st in CAPABILITY_STATUSES}

    for dom in CAPABILITY_DOMAINS:
        spec = domain_specs.get(dom)
        if not spec:
            entry = evaluate_domain_capability(
                dom,
                implemented=False,
                case_records=[],
                has_unseen_dataset=False,
                leakage_detected=False,
                has_e2e_probe=False,
                has_postcondition_check=False,
                disclosed_gaps=["Domain not yet registered in capability verification suite"],
                previous_baseline=prev_map.get(dom),
            )
        else:
            entry = evaluate_domain_capability(
                dom,
                implemented=bool(spec.get("implemented", True)),
                case_records=list(spec.get("case_records", [])),
                has_unseen_dataset=bool(spec.get("has_unseen_dataset", False)),
                leakage_detected=bool(spec.get("leakage_detected", False)),
                has_e2e_probe=bool(spec.get("has_e2e_probe", False)),
                has_postcondition_check=bool(spec.get("has_postcondition_check", False)),
                blocked_dependencies=list(spec.get("blocked_dependencies", [])),
                disclosed_gaps=list(spec.get("disclosed_gaps", [])),
                previous_baseline=prev_map.get(dom),
                self_declared_status=spec.get("self_declared_status"),
            )
        domains[dom] = entry
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1

    return {
        "policy": "REAL_CAPABILITY_MEASURED_NOT_DECLARED",
        "self_assessment_blocked": True,
        "allowed_statuses": list(CAPABILITY_STATUSES),
        "domains": domains,
        "summary": {
            "total_domains": len(CAPABILITY_DOMAINS),
            "verified": counts["VERIFIED"],
            "tested": counts["TESTED"],
            "partial": counts["PARTIAL"],
            "implemented": counts["IMPLEMENTED"],
            "blocked": counts["BLOCKED"],
            "regression_failed": counts["REGRESSION_FAILED"],
            "not_implemented": counts["NOT_IMPLEMENTED"],
            "counts_by_status": counts,
        },
    }


def load_latest_baselines(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT b.domain, b.status, b.score, b.passed, b.total, b.false_positives, b.evidence_hash, b.created_at
        FROM capability_baselines b
        INNER JOIN (
            SELECT domain, MAX(created_at) AS max_ts
            FROM capability_baselines
            GROUP BY domain
        ) latest
        ON b.domain = latest.domain AND b.created_at = latest.max_ts
        """
    ).fetchall()
    return {str(r["domain"]): dict(r) for r in rows}


def persist_capability_baselines(
    conn: sqlite3.Connection,
    ledger: dict[str, Any],
    *,
    benchmark_version: str,
    model_version: str,
) -> list[dict[str, Any]]:
    now = _now_iso()
    saved: list[dict[str, Any]] = []
    with conn:
        for dom, entry in ledger["domains"].items():
            bid = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO capability_baselines (
                    id, domain, benchmark_version, model_version, status,
                    score, passed, total, false_positives, evidence_hash,
                    details_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bid,
                    dom,
                    benchmark_version,
                    model_version,
                    entry["status"],
                    float(entry["score"]),
                    int(entry["passed"]),
                    int(entry["total"]),
                    int(entry["false_positives"]),
                    entry["evidence_hash"],
                    json.dumps(entry, ensure_ascii=False),
                    now,
                ),
            )
            saved.append({"id": bid, "domain": dom, "status": entry["status"], "score": entry["score"]})
    return saved
