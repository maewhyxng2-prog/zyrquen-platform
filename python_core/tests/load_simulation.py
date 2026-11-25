#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — Continuous Load Simulation & Stress Benchmark
-----------------------------------------------------------
Evaluates Native Core endurance, latency distribution, SQLite WAL concurrency,
memory footprint, reasoning accuracy, and abstention integrity under sustained,
high-complexity mixed workloads without adding features or modifying production DBs.
"""

from __future__ import annotations

import collections
import concurrent.futures
import json
import math
import os
import platform
import random
import resource
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PYTHON_CORE_DIR = Path(__file__).resolve().parent.parent
if str(PYTHON_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_CORE_DIR))

import db_bridge  # noqa: E402
import tools_engine as te  # noqa: E402
import zyrquen_core as zc  # noqa: E402
from tests.benchmark_suite import isolated_core_env  # noqa: E402


def _get_rss_mb() -> float:
    """Read current resident set size in MB (Linux /proc/self/status fallback to ru_maxrss)."""
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    kb = float(line.split()[1])
                    return round(kb / 1024.0, 2)
    except OSError:
        pass
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 2)


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = (len(sorted_vals) - 1) * (pct / 100.0)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return round(sorted_vals[lo], 2)
    frac = idx - lo
    return round(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac, 2)


def _summarize_stage(
    name: str,
    records: list[dict[str, Any]],
    wall_ms: float,
) -> dict[str, Any]:
    latencies = sorted(r["latency_ms"] for r in records)
    total = len(records)
    passed = sum(1 for r in records if r["passed"])
    errors = sum(1 for r in records if r.get("error"))
    lock_errors = sum(1 for r in records if r.get("sqlite_lock_error"))
    ext_llm_breaches = sum(1 for r in records if r.get("external_llm_breach"))
    false_positives = sum(1 for r in records if r.get("polarity") == "negative" and not r["passed"])
    failures = [
        {
            "id": r["id"],
            "kind": r["kind"],
            "expected": r["expected"],
            "actual": r["actual"],
            "error": r.get("error"),
        }
        for r in records
        if not r["passed"]
    ]
    return {
        "stage": name,
        "total_ops": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "errors": errors,
        "sqlite_lock_errors": lock_errors,
        "false_positives": false_positives,
        "external_llm_breaches": ext_llm_breaches,
        "wall_ms": round(wall_ms, 2),
        "throughput_rps": round((total / (wall_ms / 1000.0)), 2) if wall_ms > 0 else 0.0,
        "latency_ms": {
            "min": round(latencies[0], 2) if latencies else 0.0,
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
            "p99": _percentile(latencies, 99),
            "max": round(latencies[-1], 2) if latencies else 0.0,
            "mean": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        },
        "failure_samples": failures[:15],
    }


def _check_dag_acyclic(steps: list[dict[str, Any]]) -> bool:
    if not steps:
        return False
    ids = {s["step_id"] for s in steps}
    adj: dict[str, list[str]] = collections.defaultdict(list)
    for s in steps:
        for dep in s.get("depends_on", []):
            if dep not in ids or dep == s["step_id"]:
                return False
            adj[dep].append(s["step_id"])
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str) -> bool:
        if node in visiting:
            return False
        if node in visited:
            return True
        visiting.add(node)
        for nxt in adj.get(node, []):
            if not dfs(nxt):
                return False
        visiting.remove(node)
        visited.add(node)
        return True

    return all(dfs(sid) for sid in ids)


def _execute_probe(
    case_id: str,
    kind: str,
    prompt: str,
    mode: str,
    validator,
    *,
    polarity: str = "positive",
    user_id: str = "load-sim-user",
) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        res = zc.handle_infer({"prompt": prompt, "mode": mode, "user_id": user_id})
        dt = (time.perf_counter() - t0) * 1000.0
        ext_breach = res.get("trace", {}).get("external_models_used") is not False
        ok, expected_desc, actual_desc = validator(res)
        return {
            "id": case_id,
            "kind": kind,
            "polarity": polarity,
            "passed": bool(ok) and not ext_breach,
            "expected": expected_desc,
            "actual": actual_desc,
            "latency_ms": dt,
            "error": None,
            "sqlite_lock_error": False,
            "external_llm_breach": ext_breach,
        }
    except sqlite3.OperationalError as exc:
        dt = (time.perf_counter() - t0) * 1000.0
        is_lock = "locked" in str(exc).lower() or "busy" in str(exc).lower()
        return {
            "id": case_id,
            "kind": kind,
            "polarity": polarity,
            "passed": False,
            "expected": "no exception",
            "actual": f"OperationalError: {exc}",
            "latency_ms": dt,
            "error": str(exc),
            "sqlite_lock_error": is_lock,
            "external_llm_breach": False,
        }
    except Exception as exc:
        dt = (time.perf_counter() - t0) * 1000.0
        return {
            "id": case_id,
            "kind": kind,
            "polarity": polarity,
            "passed": False,
            "expected": "no exception",
            "actual": f"{type(exc).__name__}: {exc}",
            "latency_ms": dt,
            "error": str(exc),
            "sqlite_lock_error": False,
            "external_llm_breach": False,
        }


def _generate_complex_workload(rng: random.Random, count: int) -> list[tuple[str, str, str, str, Any, str]]:
    """
    Generate deterministic-seed unseen mixed workloads across all ZYRQUEN engines.
    Returns list of (case_id, kind, prompt, mode, validator_fn, polarity).
    """
    tasks: list[tuple[str, str, str, str, Any, str]] = []
    non_ml_goals = [
        "สร้างระบบจัดการห้องสมุดชุมชนอัจฉริยะ",
        "พัฒนาแอปพลิเคชันติดตามการส่งพัสดุออนไลน์",
        "ออกแบบบริการ API จัดตารางนัดหมายคลินิก",
        "สร้างระบบแนะนำบทความวิจัยภาษาไทย",
        "พัฒนาเครื่องมือตรวจสอบคลังสินค้าย่อย",
    ]
    ml_goals = [
        "เตรียมข้อมูล ฝึกโมเดล และประเมินผล Checkpoint ใหม่",
        "ตรวจสอบ Data Leakage และ Benchmark โมเดล ZYRQUEN",
    ]
    unseen_negatives = [
        "ใครคือผู้ชนะรางวัลโนเบลสาขาฟิสิกส์ปี 2099",
        "สภาวะอากาศบนดาวอังคารวันพรุ่งนี้เป็นอย่างไร",
        "ราคาหุ้นของบริษัท ZetaQuantum ในตลาดโตเกียววันนี้เท่าไร",
        "ทำนายผลฟุตบอลโลกนัดชิงชนะเลิศล่วงหน้า",
        "อธิบายสถาปัตยกรรมลับของโครงการ OrionX99 ที่ยังไม่เปิดเผย",
    ]

    for idx in range(count):
        bucket = idx % 10
        cid = f"W-{idx + 1:03d}"

        if bucket == 0:
            # Nested AST math with polite Thai suffixes
            a = rng.randint(2, 25)
            b = rng.randint(3, 18)
            c = rng.randint(2, 9)
            k = rng.choice([4, 9, 16, 25, 36, 49, 64, 81])
            expected = (a * b) + int(math.isqrt(k)) - c
            suffix = rng.choice(["หน่อยครับ", "ให้หน่อยค่ะ?", "ได้เท่าไร", ""])
            prompt = f"คำนวณ ({a} * {b}) + sqrt({k}) - {c} {suffix}".strip()
            tasks.append((
                cid, "math_ast", prompt, "auto",
                lambda r, exp=expected: (
                    r["status"] == "VERIFIED" and r["trace"].get("math", {}).get("result") == exp,
                    f"VERIFIED({exp})", f"{r['status']}({r['trace'].get('math', {}).get('result')})"
                ),
                "positive",
            ))

        elif bucket == 1:
            # Unseen Quadratic Equations (2 real roots, repeated root, or negative discriminant)
            variant = idx % 3
            if variant == 0:
                r1, r2 = sorted([rng.randint(-8, -1), rng.randint(1, 9)])
                b_coef = -(r1 + r2)
                c_coef = r1 * r2
                b_str = f"+ {b_coef}x" if b_coef >= 0 else f"- {abs(b_coef)}x"
                c_str = f"+ {c_coef}" if c_coef >= 0 else f"- {abs(c_coef)}"
                prompt = f"แก้สมการ: x^2 {b_str} {c_str} = 0"
                exp_tag = f"roots({r1},{r2})"
            elif variant == 1:
                r0 = rng.randint(1, 12)
                prompt = f"แก้สมการ: (x - {r0})^2 = 0"
                exp_tag = f"root({r0})"
            else:
                k = rng.randint(1, 30)
                prompt = f"แก้สมการ: x^2 + {k} = 0"
                exp_tag = "no_real_solution"
            tasks.append((
                cid, "quadratic_algebra", prompt, "auto",
                lambda r, exp=exp_tag: (
                    r["status"] == "VERIFIED" and r["trace"].get("algebra", {}).get("summary_tag") == exp,
                    f"VERIFIED({exp})", f"{r['status']}({r['trace'].get('algebra', {}).get('summary_tag')})"
                ),
                "positive",
            ))

        elif bucket == 2:
            # Unseen 2-variable or 3-variable RREF Linear Systems (or inconsistent trap)
            if idx % 4 == 3:
                k1, k2 = rng.randint(1, 10), rng.randint(11, 20)
                prompt = f"แก้สมการ: x + y = {k1}, x + y = {k2}"
                exp_tag = "no_solution"
            elif idx % 2 == 0:
                xv, yv = rng.randint(1, 12), rng.randint(1, 12)
                c1 = rng.randint(1, 4) * xv + rng.randint(1, 4) * yv
                a1, b1 = rng.randint(1, 4), rng.randint(1, 4)
                c1 = a1 * xv + b1 * yv
                a2, b2 = rng.randint(2, 5), -rng.randint(1, 3)
                # Ensure determinant != 0
                if a1 * b2 - a2 * b1 == 0:
                    b2 -= 1
                c2 = a2 * xv + b2 * yv
                b2_s = f"+ {b2}y" if b2 >= 0 else f"- {abs(b2)}y"
                prompt = f"แก้สมการ: {a1}x + {b1}y = {c1}, {a2}x {b2_s} = {c2}"
                exp_tag = f"system(x={xv},y={yv})"
            else:
                xv, yv, zv = rng.randint(1, 6), rng.randint(1, 6), rng.randint(1, 6)
                c1 = xv + yv + zv
                c2 = 2 * xv - yv + zv
                c3 = xv + 2 * yv - zv
                prompt = f"แก้สมการ: x + y + z = {c1}, 2x - y + z = {c2}, x + 2y - z = {c3}"
                exp_tag = f"system(x={xv},y={yv},z={zv})"
            tasks.append((
                cid, "linear_system_rref", prompt, "auto",
                lambda r, exp=exp_tag: (
                    r["status"] == "VERIFIED" and r["trace"].get("algebra", {}).get("summary_tag") == exp,
                    f"VERIFIED({exp})", f"{r['status']}({r['trace'].get('algebra', {}).get('summary_tag')})"
                ),
                "positive",
            ))

        elif bucket == 3:
            # 4-hop Transitive Logic Chains + Contradiction/Mixed-Attribute Traps
            n0, n1, n2, n3, n4 = [f"E{idx}_{j}" for j in range(5)]
            if idx % 5 == 0:
                prompt = f"ถ้า {n0} > {n1} และ {n1} > {n0} แล้ว {n0} เทียบกับ {n1} เป็นอย่างไร"
                tasks.append((
                    cid, "logic_contradiction", prompt, "auto",
                    lambda r: (
                        r["status"] == "BLOCKED" and r["trace"].get("logic", {}).get("contradiction") is True,
                        "BLOCKED(contradiction=True)", f"{r['status']}({r['trace'].get('logic')})"
                    ),
                    "negative",
                ))
            elif idx % 5 == 1:
                prompt = f"ถ้า {n0} สูงกว่า {n1} และ {n1} หนักกว่า {n2} แล้ว {n0} เทียบกับ {n2} เป็นอย่างไร"
                tasks.append((
                    cid, "logic_mixed_attr_abstain", prompt, "auto",
                    lambda r: (
                        r["status"] == "UNABLE_TO_INFER" and r["trace"].get("logic", {}).get("determined") is False,
                        "UNABLE_TO_INFER(determined=False)", f"{r['status']}({r['trace'].get('logic')})"
                    ),
                    "negative",
                ))
            else:
                prompt = f"ถ้า {n0} > {n1} และ {n1} >= {n2} และ {n2} > {n3} และ {n3} >= {n4} แล้ว {n0} เทียบกับ {n4} เป็นอย่างไร"
                exp_rel = f"{n0} > {n4}"
                tasks.append((
                    cid, "transitive_logic", prompt, "auto",
                    lambda r, exp=exp_rel: (
                        r["status"] == "VERIFIED" and r["trace"].get("logic", {}).get("derived_relation") == exp,
                        f"VERIFIED({exp})", f"{r['status']}({r['trace'].get('logic', {}).get('derived_relation')})"
                    ),
                    "positive",
                ))

        elif bucket == 4:
            # Thai Quantitative Word Math + Zero-Divisor Abstention
            op = idx % 5
            if op == 0:
                q = rng.randint(2, 15)
                d = rng.randint(2, 9)
                prompt = f"มีเอกสาร {q * d} หน้า แบ่งให้ {d} คนเท่าๆ กัน จะได้คนละกี่หน้า"
                tasks.append((
                    cid, "word_math_div", prompt, "auto",
                    lambda r, exp=q: (
                        r["status"] == "VERIFIED" and r["trace"].get("word_math", {}).get("result") == exp,
                        f"VERIFIED({exp})", f"{r['status']}({r['trace'].get('word_math', {}).get('result')})"
                    ),
                    "positive",
                ))
            elif op == 1:
                g = rng.randint(2, 12)
                u = rng.randint(3, 15)
                prompt = f"ซื้อสมุด {g} กล่อง กล่องละ {u} เล่ม จะมีสมุดทั้งหมดกี่เล่ม"
                tasks.append((
                    cid, "word_math_mul", prompt, "auto",
                    lambda r, exp=g * u: (
                        r["status"] == "VERIFIED" and r["trace"].get("word_math", {}).get("result") == exp,
                        f"VERIFIED({exp})", f"{r['status']}({r['trace'].get('word_math', {}).get('result')})"
                    ),
                    "positive",
                ))
            elif op == 2:
                a, b = rng.randint(50, 300), rng.randint(10, 45)
                prompt = f"มีเงิน {a} บาท จ่ายไป {b} บาท จะเหลือเงินกี่บาท"
                tasks.append((
                    cid, "word_math_sub", prompt, "auto",
                    lambda r, exp=a - b: (
                        r["status"] == "VERIFIED" and r["trace"].get("word_math", {}).get("result") == exp,
                        f"VERIFIED({exp})", f"{r['status']}({r['trace'].get('word_math', {}).get('result')})"
                    ),
                    "positive",
                ))
            elif op == 3:
                a, b = rng.randint(10, 90), rng.randint(10, 90)
                prompt = f"มีหนังสือ {a} เล่ม ได้รับเพิ่มอีก {b} เล่ม รวมมีหนังสือกี่เล่ม"
                tasks.append((
                    cid, "word_math_add", prompt, "auto",
                    lambda r, exp=a + b: (
                        r["status"] == "VERIFIED" and r["trace"].get("word_math", {}).get("result") == exp,
                        f"VERIFIED({exp})", f"{r['status']}({r['trace'].get('word_math', {}).get('result')})"
                    ),
                    "positive",
                ))
            else:
                prompt = "มีแอปเปิ้ล 24 ผล แบ่งให้ 0 คนเท่าๆ กัน จะได้คนละกี่ผล"
                tasks.append((
                    cid, "word_math_zero_div", prompt, "auto",
                    lambda r: (
                        r["status"] == "UNABLE_TO_INFER",
                        "UNABLE_TO_INFER", r["status"]
                    ),
                    "negative",
                ))

        elif bucket == 5:
            # Multi-hop Graph BFS (5..7 hops) on dynamically seeded Stage-1 graph
            chain_idx = idx % 5
            hops = 5 + (idx % 3)  # 5, 6, or 7 hops
            start_n = f"Chain{chain_idx}_N0"
            end_n = f"Chain{chain_idx}_N{hops}"
            prompt = f"เชื่อมโยง: {start_n} -> {end_n}"
            tasks.append((
                cid, f"multihop_{hops}", prompt, "auto",
                lambda r, h=hops: (
                    r["status"] == "VERIFIED"
                    and ((r["trace"].get("graph_path") or {}).get("path") or {}).get("hops") == h,
                    f"VERIFIED(hops={h})",
                    f"{r['status']}(hops={((r['trace'].get('graph_path') or {}).get('path') or {}).get('hops')})"
                ),
                "positive",
            ))

        elif bucket == 6:
            # Domain-adaptive Planning in both mode="auto" and mode="plan"
            if idx % 3 == 0:
                goal = ml_goals[idx % len(ml_goals)]
                tasks.append((
                    cid, "plan_mlops", goal, "plan",
                    lambda r: (
                        r["status"] == "PLANNED"
                        and (r["trace"].get("plan") or {}).get("domain_mode") == "mlops_native"
                        and _check_dag_acyclic((r["trace"].get("plan") or {}).get("steps", [])),
                        "PLANNED(mlops_native acyclic DAG)",
                        f"{r['status']}({(r['trace'].get('plan') or {}).get('domain_mode')})"
                    ),
                    "positive",
                ))
            else:
                goal = non_ml_goals[idx % len(non_ml_goals)]
                mode_sel = "plan" if idx % 2 == 0 else "auto"
                prompt = goal if mode_sel == "plan" else f"วางแผน: {goal}"
                tasks.append((
                    cid, f"plan_domain_{mode_sel}", prompt, mode_sel,
                    lambda r: (
                        r["status"] == "PLANNED"
                        and (r["trace"].get("plan") or {}).get("domain_mode") == "general_engineering"
                        and _check_dag_acyclic((r["trace"].get("plan") or {}).get("steps", [])),
                        "PLANNED(general_engineering acyclic DAG)",
                        f"{r['status']}({(r['trace'].get('plan') or {}).get('domain_mode')})"
                    ),
                    "positive",
                ))

        elif bucket == 7:
            # Natural-Language Research Gate (must require approval, never bypass gate)
            topic = rng.choice(["PostgreSQL", "Rust Async", "SQLite WAL", "WebAssembly", "Vector Index"])
            prompt = f"ช่วยหาข้อมูลล่าสุดเกี่ยวกับเรื่อง {topic} ให้หน่อย"
            tasks.append((
                cid, "research_gate", prompt, "auto",
                lambda r: (
                    r["status"] == "PENDING_APPROVAL"
                    and (r["trace"].get("external_tool") or {}).get("tool_id") == "web_search",
                    "PENDING_APPROVAL(web_search)",
                    f"{r['status']}({(r['trace'].get('external_tool') or {}).get('tool_id')})"
                ),
                "positive",
            ))

        elif bucket == 8:
            # Statistics & Mixed KG Direct Retrieval under load
            if idx % 2 == 0:
                vals = [rng.randint(5, 100) for _ in range(5)]
                mean_exp = sum(vals) / len(vals)
                mean_fmt = int(mean_exp) if mean_exp.is_integer() else round(mean_exp, 6)
                prompt = "สถิติ: " + ", ".join(str(v) for v in vals)
                tasks.append((
                    cid, "statistics", prompt, "auto",
                    lambda r, exp=mean_fmt: (
                        r["status"] == "VERIFIED" and r["trace"].get("statistics", {}).get("mean") == exp,
                        f"VERIFIED({exp})", f"{r['status']}({r['trace'].get('statistics', {}).get('mean')})"
                    ),
                    "positive",
                ))
            else:
                prompt = "เชื่อมโยง: PrefixNode1 -> PrefixTarget2"
                tasks.append((
                    cid, "prefix_collision_guard", prompt, "auto",
                    lambda r: (
                        r["status"] == "VERIFIED"
                        and (((r["trace"].get("graph_path") or {}).get("path") or {}).get("edges") or [{}])[0].get("from") == "PrefixNode1",
                        "VERIFIED(start=PrefixNode1)",
                        f"{r['status']}(start={((((r['trace'].get('graph_path') or {}).get('path') or {}).get('edges') or [{}])[0].get('from'))})"
                    ),
                    "positive",
                ))

        else:
            # Out-of-distribution Negative Abstention (must stay NOT_LEARNED despite large KG)
            prompt = unseen_negatives[idx % len(unseen_negatives)]
            tasks.append((
                cid, "negative_abstention", prompt, "auto",
                lambda r: (
                    r["status"] == "NOT_LEARNED",
                    "NOT_LEARNED", r["status"]
                ),
                "negative",
            ))

    return tasks


def run_load_simulation(
    *,
    scale: float = 1.0,
    workers: int = 8,
    processes: int = 12,
    seed: int = 20261124,
) -> dict[str, Any]:
    rng = random.Random(seed)
    rss_start = _get_rss_mb()

    # Clamp counts cleanly while honoring scale
    num_distractors = max(12, int(45 * scale))
    num_storm_ops = max(50, int(250 * scale))
    num_concurrent_ops = max(24, int(120 * scale))
    num_proc_ops = max(4, int(processes))

    with isolated_core_env() as tmp_path:
        orig_bridge_data = db_bridge.DATA_DIR
        db_bridge.DATA_DIR = zc.DATA_DIR

        try:
            # ------------------------------------------------------------------
            # Stage 1: High-Volume Knowledge Graph Scaling & 7-Hop Seeding
            # ------------------------------------------------------------------
            s1_records: list[dict[str, Any]] = []
            s1_t0 = time.perf_counter()

            # 5 deep 7-hop chains (35 triples) + cross links
            for c_idx in range(5):
                for hop in range(7):
                    src = f"Chain{c_idx}_N{hop}"
                    dst = f"Chain{c_idx}_N{hop + 1}"
                    rec = _execute_probe(
                        f"S1-CHAIN-{c_idx}-{hop}", "kg_teach_chain",
                        f"สอน: {src} -> ส่งต่อไปยัง -> {dst}", "knowledge",
                        lambda r: (r["status"] == "VERIFIED", "VERIFIED", r["status"]),
                    )
                    s1_records.append(rec)

            # Prefix collision triples (PrefixNode1 vs PrefixNode10 vs PrefixNode100)
            for s, o in [("PrefixNode1", "PrefixTarget2"), ("PrefixNode10", "DeadEnd10"), ("PrefixNode100", "DeadEnd100")]:
                s1_records.append(_execute_probe(
                    f"S1-PREF-{s}", "kg_teach_prefix",
                    f"สอน: {s} -> เชื่อม -> {o}", "knowledge",
                    lambda r: (r["status"] == "VERIFIED", "VERIFIED", r["status"]),
                ))

            # Distractor triples to test scalability & false-positive resistance
            for d_idx in range(num_distractors):
                s1_records.append(_execute_probe(
                    f"S1-DIST-{d_idx}", "kg_teach_distractor",
                    f"สอน: SatelliteCluster{d_idx} -> สังกัด -> OrbitSector{d_idx % 7}", "knowledge",
                    lambda r: (r["status"] == "VERIFIED", "VERIFIED", r["status"]),
                ))

            # Deliberate contradiction triple check
            s1_records.append(_execute_probe(
                "S1-CONTRA-A", "kg_teach_base",
                "สอน: ReactorAlpha -> ระดับความปลอดภัย -> Tier1", "knowledge",
                lambda r: (r["status"] == "VERIFIED", "VERIFIED", r["status"]),
            ))
            s1_records.append(_execute_probe(
                "S1-CONTRA-B", "kg_teach_contradiction",
                "สอน: ReactorAlpha -> ระดับความปลอดภัย -> Tier4", "knowledge",
                lambda r: (
                    r["status"] == "VERIFIED" and "Tier1" in (r["trace"].get("teach") or {}).get("contradictions", []),
                    "VERIFIED(contradicts Tier1)",
                    f"{r['status']}({(r['trace'].get('teach') or {}).get('contradictions')})",
                ),
            ))

            # Verify 7-hop retrieval across all 5 chains under populated graph
            for c_idx in range(5):
                s1_records.append(_execute_probe(
                    f"S1-BFS7-{c_idx}", "kg_verify_7hop",
                    f"เชื่อมโยง: Chain{c_idx}_N0 -> Chain{c_idx}_N7", "auto",
                    lambda r: (
                        r["status"] == "VERIFIED"
                        and ((r["trace"].get("graph_path") or {}).get("path") or {}).get("hops") == 7,
                        "VERIFIED(hops=7)",
                        f"{r['status']}(hops={((r['trace'].get('graph_path') or {}).get('path') or {}).get('hops')})",
                    ),
                ))

            s1_wall = (time.perf_counter() - s1_t0) * 1000.0
            stage1 = _summarize_stage("Stage 1: KG Scaling & 7-Hop Multi-Branch Stress", s1_records, s1_wall)

            # ------------------------------------------------------------------
            # Stage 2: Sustained Mixed Complex Reasoning Storm
            # ------------------------------------------------------------------
            storm_tasks = _generate_complex_workload(rng, num_storm_ops)
            s2_records: list[dict[str, Any]] = []
            s2_t0 = time.perf_counter()
            for cid, kind, prompt, mode, validator, polarity in storm_tasks:
                s2_records.append(_execute_probe(cid, kind, prompt, mode, validator, polarity=polarity))
            s2_wall = (time.perf_counter() - s2_t0) * 1000.0
            stage2 = _summarize_stage("Stage 2: Sustained Mixed Complex Reasoning Storm", s2_records, s2_wall)

            # ------------------------------------------------------------------
            # Stage 3: Concurrent Multi-Worker Thread Contention (SQLite WAL)
            # ------------------------------------------------------------------
            user_res = db_bridge.handle_action(
                "auth_create_user",
                {"email": "loadsim@test.local", "display_name": "LoadSim", "role": "admin", "password_hash": "h"},
            )
            uid = user_res["user"]["id"]
            conv_res = db_bridge.handle_action("conv_create", {"user_id": uid, "title": "LoadSim", "mode": "auto"})
            cid_conv = conv_res["conversation"]["id"]

            concurrent_tasks = _generate_complex_workload(rng, num_concurrent_ops)

            def _run_thread_item(item_tuple: tuple[int, tuple[str, str, str, str, Any, str]]) -> dict[str, Any]:
                idx_item, (c_id, kind, prompt, mode, validator, polarity) = item_tuple
                # Mix 15% knowledge writes + db_bridge conversation persistence to exercise real WAL write contention
                if idx_item % 7 == 0:
                    rec = _execute_probe(
                        f"CONC-W-{idx_item}", "concurrent_kg_write",
                        f"สอน: DynamicBatch{idx_item} -> เชื่อมกับ -> TargetPool{idx_item % 5}", "knowledge",
                        lambda r: (r["status"] == "VERIFIED", "VERIFIED", r["status"]),
                        user_id=uid,
                    )
                    return rec

                rec = _execute_probe(
                    f"CONC-{c_id}", f"concurrent_{kind}", prompt, mode, validator,
                    polarity=polarity, user_id=uid,
                )
                if idx_item % 5 == 0 and rec["error"] is None:
                    t_save0 = time.perf_counter()
                    try:
                        saved = db_bridge.handle_action(
                            "conv_save_exchange",
                            {
                                "user_id": uid,
                                "conversation_id": cid_conv,
                                "user_content": prompt,
                                "mode": mode,
                                "assistant_content": f"persisted-{c_id}",
                                "assistant_status": "VERIFIED" if polarity == "positive" else "NOT_LEARNED",
                                "trace": {"external_models_used": False},
                            },
                        )
                        rec["latency_ms"] += (time.perf_counter() - t_save0) * 1000.0
                        if not saved.get("ok"):
                            rec["passed"] = False
                            rec["actual"] = f"conv_save_exchange failed: {saved}"
                    except sqlite3.OperationalError as exc:
                        rec["passed"] = False
                        rec["error"] = str(exc)
                        rec["sqlite_lock_error"] = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                return rec

            s3_t0 = time.perf_counter()
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                s3_records = list(pool.map(_run_thread_item, enumerate(concurrent_tasks)))
            s3_wall = (time.perf_counter() - s3_t0) * 1000.0
            stage3 = _summarize_stage(
                f"Stage 3: Concurrent Multi-Worker WAL Contention ({workers} threads)",
                s3_records,
                s3_wall,
            )

            # ------------------------------------------------------------------
            # Stage 4: Multi-Process Subprocess CLI Burst (Server -> Python Boundary)
            # ------------------------------------------------------------------
            db_path_str = str(zc.DB_PATH)
            data_dir_str = str(zc.DATA_DIR)
            ckpt_dir_str = str(zc.CHECKPOINT_DIR)

            proc_prompts = [
                ("PROC-MATH", "คำนวณ (2^10 - 24) / 10 หน่อยครับ", "auto", "VERIFIED", 100),
                ("PROC-QUAD", "แก้สมการ: x^2 - 7x + 10 = 0", "auto", "VERIFIED", "roots(2,5)"),
                ("PROC-SYS", "แก้สมการ: 2x + y = 9, x - y = 3", "auto", "VERIFIED", "system(x=4,y=1)"),
                ("PROC-BFS", "เชื่อมโยง: Chain0_N0 -> Chain0_N7", "auto", "VERIFIED", 7),
                ("PROC-PLAN", "สร้างระบบจัดการนัดหมายทันตกรรม", "plan", "PLANNED", "general_engineering"),
                ("PROC-NEG", "ราคาทองคำในอีก 50 ปีข้างหน้าเป็นเท่าไร", "auto", "NOT_LEARNED", None),
            ]

            def _run_subprocess_case(idx_p: int) -> dict[str, Any]:
                base_id, prompt, mode, exp_status, exp_val = proc_prompts[idx_p % len(proc_prompts)]
                cid_p = f"{base_id}-{idx_p}"
                py_code = (
                    "import json, sys; from pathlib import Path; import zyrquen_core as zc; "
                    "zc.DATA_DIR = Path(sys.argv[1]); zc.CHECKPOINT_DIR = Path(sys.argv[2]); zc.DB_PATH = Path(sys.argv[3]); "
                    "res = zc.handle_infer(json.loads(sys.argv[4])); "
                    "print(json.dumps({'status': res['status'], 'trace': res['trace']}, ensure_ascii=False))"
                )
                payload_json = json.dumps({"prompt": prompt, "mode": mode, "user_id": uid}, ensure_ascii=False)
                t0 = time.perf_counter()
                try:
                    cp = subprocess.run(
                        [sys.executable, "-c", py_code, data_dir_str, ckpt_dir_str, db_path_str, payload_json],
                        cwd=str(PYTHON_CORE_DIR),
                        env={**os.environ, "PYTHONPATH": str(PYTHON_CORE_DIR)},
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                    dt = (time.perf_counter() - t0) * 1000.0
                    if cp.returncode != 0:
                        is_lock = "locked" in cp.stderr.lower() or "busy" in cp.stderr.lower()
                        return {
                            "id": cid_p,
                            "kind": f"subprocess_{base_id.lower()}",
                            "polarity": "negative" if exp_status == "NOT_LEARNED" else "positive",
                            "passed": False,
                            "expected": exp_status,
                            "actual": cp.stderr.strip()[:160],
                            "latency_ms": dt,
                            "error": cp.stderr.strip()[:200],
                            "sqlite_lock_error": is_lock,
                            "external_llm_breach": False,
                        }
                    parsed = json.loads(cp.stdout.strip())
                    tr = parsed.get("trace") or {}
                    ext_breach = tr.get("external_models_used") is not False
                    ok = parsed.get("status") == exp_status
                    if ok and base_id == "PROC-MATH":
                        ok = (tr.get("math") or {}).get("result") == exp_val
                    elif ok and base_id in ("PROC-QUAD", "PROC-SYS"):
                        ok = (tr.get("algebra") or {}).get("summary_tag") == exp_val
                    elif ok and base_id == "PROC-BFS":
                        ok = ((tr.get("graph_path") or {}).get("path") or {}).get("hops") == exp_val
                    elif ok and base_id == "PROC-PLAN":
                        ok = (tr.get("plan") or {}).get("domain_mode") == exp_val
                    return {
                        "id": cid_p,
                        "kind": f"subprocess_{base_id.lower()}",
                        "polarity": "negative" if exp_status == "NOT_LEARNED" else "positive",
                        "passed": bool(ok) and not ext_breach,
                        "expected": f"{exp_status}({exp_val})",
                        "actual": parsed.get("status"),
                        "latency_ms": dt,
                        "error": None,
                        "sqlite_lock_error": False,
                        "external_llm_breach": ext_breach,
                    }
                except Exception as exc:
                    dt = (time.perf_counter() - t0) * 1000.0
                    return {
                        "id": cid_p,
                        "kind": f"subprocess_{base_id.lower()}",
                        "polarity": "negative" if exp_status == "NOT_LEARNED" else "positive",
                        "passed": False,
                        "expected": exp_status,
                        "actual": str(exc),
                        "latency_ms": dt,
                        "error": str(exc),
                        "sqlite_lock_error": False,
                        "external_llm_breach": False,
                    }

            s4_t0 = time.perf_counter()
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, num_proc_ops)) as pool:
                s4_records = list(pool.map(_run_subprocess_case, range(num_proc_ops)))
            s4_wall = (time.perf_counter() - s4_t0) * 1000.0
            stage4 = _summarize_stage(
                f"Stage 4: Multi-Process CLI Spawn Burst ({num_proc_ops} processes)",
                s4_records,
                s4_wall,
            )

            # Inspect final isolated DB metrics before cleanup
            conn = zc.get_db()
            total_triples = conn.execute("SELECT COUNT(*) FROM knowledge_triples").fetchone()[0]
            total_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            conn.close()
            db_kb = round(zc.DB_PATH.stat().st_size / 1024.0, 2) if zc.DB_PATH.exists() else 0.0
            wal_path = Path(str(zc.DB_PATH) + "-wal")
            wal_kb = round(wal_path.stat().st_size / 1024.0, 2) if wal_path.exists() else 0.0
        finally:
            db_bridge.DATA_DIR = orig_bridge_data

    rss_end = _get_rss_mb()
    stages = [stage1, stage2, stage3, stage4]
    total_ops = sum(s["total_ops"] for s in stages)
    total_passed = sum(s["passed"] for s in stages)
    total_errors = sum(s["errors"] for s in stages)
    total_locks = sum(s["sqlite_lock_errors"] for s in stages)
    total_fps = sum(s["false_positives"] for s in stages)
    total_llm_breaches = sum(s["external_llm_breaches"] for s in stages)

    return {
        "suite": "ZYRQUEN Ω∞ Continuous Load Simulation v1",
        "environment": {
            "python_version": platform.python_version(),
            "platform": platform.system(),
            "cpu_count": os.cpu_count() or 1,
            "external_models_used": False,
            "seed": seed,
            "scale": scale,
            "thread_workers": workers,
            "subprocess_burst": num_proc_ops,
        },
        "summary": {
            "total_operations": total_ops,
            "passed": total_passed,
            "failed": total_ops - total_passed,
            "overall_pass_rate": round(total_passed / total_ops, 4) if total_ops else 0.0,
            "total_errors": total_errors,
            "sqlite_lock_errors": total_locks,
            "false_positives": total_fps,
            "external_llm_breaches": total_llm_breaches,
        },
        "resources": {
            "rss_start_mb": rss_start,
            "rss_end_mb": rss_end,
            "rss_delta_mb": round(rss_end - rss_start, 2),
            "isolated_triples_persisted": total_triples,
            "isolated_messages_persisted": total_messages,
            "sqlite_db_kb": db_kb,
            "sqlite_wal_kb": wal_kb,
        },
        "stages": stages,
    }


def format_load_report_text(report: dict[str, Any]) -> str:
    env = report["environment"]
    s = report["summary"]
    res = report["resources"]
    lines = [
        "=== ZYRQUEN Ω∞ Continuous Load Simulation Report ===",
        f"Environment: Python {env['python_version']} ({env['platform']}, CPUs={env['cpu_count']}) | Seed={env['seed']} | Scale={env['scale']} | External LLMs={env['external_models_used']}",
        f"Total Ops: {s['total_operations']} | Passed: {s['passed']} | Failed: {s['failed']} ({s['overall_pass_rate']*100:.2f}%)",
        f"Errors: {s['total_errors']} | SQLite Locks: {s['sqlite_lock_errors']} | False Positives: {s['false_positives']} | External LLM Breaches: {s['external_llm_breaches']}",
        f"Resources: RSS {res['rss_start_mb']} -> {res['rss_end_mb']} MB (delta {res['rss_delta_mb']:+.2f} MB) | KG Triples={res['isolated_triples_persisted']} | DB={res['sqlite_db_kb']} KB | WAL={res['sqlite_wal_kb']} KB",
        "",
        "Stage Breakdown:",
    ]
    for st in report["stages"]:
        lat = st["latency_ms"]
        lines.append(
            f"  - {st['stage']}: {st['passed']}/{st['total_ops']} ({st['pass_rate']*100:.1f}%) | "
            f"{st['throughput_rps']:.1f} req/s | p50={lat['p50']}ms p95={lat['p95']}ms p99={lat['p99']}ms max={lat['max']}ms | "
            f"locks={st['sqlite_lock_errors']} errs={st['errors']}"
        )
        for fail in st["failure_samples"]:
            lines.append(f"      FAIL [{fail['id']}] ({fail['kind']}): expected={fail['expected']} actual={fail['actual']}")
    return "\n".join(lines)


if __name__ == "__main__":
    scale_arg = 1.0
    workers_arg = 8
    procs_arg = 12
    for arg in sys.argv[1:]:
        if arg.startswith("--scale="):
            scale_arg = max(0.2, float(arg.split("=", 1)[1]))
        elif arg.startswith("--workers="):
            workers_arg = max(2, int(arg.split("=", 1)[1]))
        elif arg.startswith("--processes="):
            procs_arg = max(2, int(arg.split("=", 1)[1]))
    rep = run_load_simulation(scale=scale_arg, workers=workers_arg, processes=procs_arg)
    if "--json" in sys.argv:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(format_load_report_text(rep))
