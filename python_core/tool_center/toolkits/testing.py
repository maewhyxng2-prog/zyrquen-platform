"""
Testing Toolkit for ZYRQUEN Tool Center.
Executes real deterministic contract probes, dataset SHA-256 integrity checks, and 7-state verification.
"""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
import re
import tempfile
from typing import Any

import dataset_ingestion as di

from ..contracts import CapabilitySpec, ToolkitManifest
from ..sandbox import run_python_sandbox, run_workspace_unittest
from ..software_engineering import run_engineering_benchmark


def _handle_toolkit_self_test(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    toolkit_id = str(payload.get("toolkit_id") or "").strip().lower()
    registry = ctx["registry"]
    report = registry.verify_toolkit(toolkit_id or None, conn=ctx.get("conn"), data_dir=ctx.get("data_dir"))
    if not report.get("ok"):
        return {
            "ok": False,
            "status": "FAILED",
            "error": report.get("error") or "Toolkit verification failed",
            "output": report,
        }
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": report,
        "summary": report.get("summary") or "ทดสอบชุดเครื่องมือสำเร็จ",
    }


def _handle_dataset_verify(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    dataset_id = str(payload.get("dataset_id") or "").strip()
    if not dataset_id:
        return {"ok": False, "status": "FAILED", "error": "dataset_id is required.", "output": {}}
    conn = ctx.get("conn")
    if conn is None:
        return {"ok": False, "status": "BLOCKED", "error": "Database connection unavailable.", "output": {}}
    res = di.verify_dataset_integrity(conn, dataset_id)
    if not res.get("ok") and res.get("error") == "Dataset not found":
        return {"ok": False, "status": "FAILED", "error": "Dataset not found", "output": res}
    verified = bool(res.get("verified"))
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": res,
        "summary": (
            f"ชุดข้อมูล {res.get('name', dataset_id)}: "
            f"{'ผ่านการตรวจ SHA-256 และความสมบูรณ์' if verified else 'พบความผิดปกติ: ' + ', '.join(res.get('errors') or [])}"
        ),
    }


def _handle_contract_assertion(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    cases = payload.get("cases") or []
    if not isinstance(cases, list) or not cases:
        return {"ok": False, "status": "FAILED", "error": "cases array must be non-empty.", "output": {}}

    results: list[dict[str, Any]] = []
    passed = 0
    for idx, case in enumerate(cases[:50]):
        if not isinstance(case, dict):
            results.append({"index": idx, "passed": False, "error": "Case must be an object"})
            continue
        name = str(case.get("name") or f"case-{idx + 1}")
        op = str(case.get("op") or "eq")
        actual = case.get("actual")
        expected = case.get("expected")
        ok = False
        if op == "eq":
            ok = actual == expected
        elif op == "ne":
            ok = actual != expected
        elif op == "contains":
            ok = str(expected) in str(actual) if not isinstance(actual, list) else expected in actual
        elif op == "truthy":
            ok = bool(actual)
        elif op == "gt":
            try:
                ok = float(actual) > float(expected)
            except (TypeError, ValueError):
                ok = False
        elif op == "lt":
            try:
                ok = float(actual) < float(expected)
            except (TypeError, ValueError):
                ok = False
        if ok:
            passed += 1
        results.append({
            "index": idx,
            "name": name,
            "op": op,
            "passed": ok,
            "actual": actual,
            "expected": expected,
        })

    total = len(results)
    failed = total - passed
    verdict = "PASS" if failed == 0 else "FAILED"
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "verdict": verdict,
            "passed": passed,
            "failed": failed,
            "total": total,
            "results": results,
        },
        "summary": f"ผลการตรวจ Assertions: {verdict} ({passed}/{total} ผ่าน)",
    }


def _handle_sandbox_run(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    source = str(payload.get("source") or "")
    if not source.strip():
        return {"ok": False, "status": "FAILED", "error": "source is required.", "output": {}}
    timeout_s = float(payload.get("timeout_s") or 3.0)
    input_data = payload.get("input_data") if isinstance(payload.get("input_data"), dict) else {}
    res = run_python_sandbox(source, input_data=input_data, timeout_s=timeout_s)
    if not res.get("ok") and res.get("status") == "BLOCKED":
        return {
            "ok": False,
            "status": "BLOCKED",
            "error": res.get("stderr") or "Sandbox policy blocked snippet.",
            "output": res,
        }
    return {
        "ok": bool(res.get("ok")),
        "status": str(res.get("status") or "FAILED"),
        "error": None if res.get("ok") else (res.get("stderr") or "Sandbox execution failed"),
        "output": res,
        "summary": (
            f"รันใน Sandbox แยกสำเร็จ ({res.get('duration_ms')} ms)"
            if res.get("ok")
            else f"การรันใน Sandbox ไม่ผ่าน: {res.get('stderr')}"
        ),
    }


def _handle_engineering_benchmark(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    mode = str((payload or {}).get("mode") or "quick").strip().lower()
    if mode == "comprehensive":
        from ..autonomous_training import run_comprehensive_benchmark

        rep = run_comprehensive_benchmark(
            ctx["registry"],
            conn=ctx.get("conn"),
            data_dir=ctx.get("data_dir"),
        )
    else:
        rep = run_engineering_benchmark(
            ctx["registry"],
            conn=ctx.get("conn"),
            data_dir=ctx.get("data_dir"),
        )
    m = rep.get("metrics") or {}
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": rep,
        "summary": (
            f"Engineering Benchmark ({mode}, {rep.get('status')}): "
            f"{rep.get('passed')}/{rep.get('total')} ผ่าน "
            f"(success_rate={m.get('success_rate')}, {m.get('execution_time_ms')} ms)"
        ),
    }


def _executable_lines(source: str) -> set[int]:
    tree = ast.parse(source, mode="exec")
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            lines.add(int(node.lineno))
    return lines


def _handle_coverage_analysis(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    module_source = str(payload.get("module_source") or "").strip()
    test_source = str(payload.get("test_source") or "").strip()
    if not module_source or not test_source:
        return {"ok": False, "status": "FAILED", "error": "module_source and test_source are required.", "output": {}}

    try:
        exec_lines = sorted(_executable_lines(module_source))
    except SyntaxError as exc:
        return {"ok": False, "status": "FAILED", "error": f"Invalid module_source syntax: {exc}", "output": {}}

    clean_module_lines = [
        ("# __future__ stripped for sandbox trace" if re.match(r"^\s*from\s+__future__\s+import\b", ln) else ln)
        for ln in module_source.splitlines()
    ]
    clean_module = "\n".join(clean_module_lines)
    mod_line_count = len(clean_module_lines)
    harness = (
        "import json, sys\n"
        "_covered = set()\n"
        "_MOD_START = 0\n"
        f"_MOD_LEN = {mod_line_count}\n"
        "def _tracer(frame, event, arg):\n"
        "    if event == 'line':\n"
        "        ln = frame.f_lineno\n"
        "        if _MOD_START <= ln < _MOD_START + _MOD_LEN:\n"
        "            _covered.add(ln - _MOD_START + 1)\n"
        "    return _tracer\n"
        "try:\n"
        "    1 // 0\n"
        "except ZeroDivisionError as _e:\n"
        "    _MOD_START = _e.__traceback__.tb_lineno + 3\n"
        + clean_module
        + "\n"
        + "sys.settrace(_tracer)\n"
        + "try:\n"
        + "\n".join("    " + ln for ln in test_source.splitlines())
        + "\nfinally:\n    sys.settrace(None)\n"
        + "print('__COV__' + json.dumps(sorted(_covered)))\n"
    )
    res = run_python_sandbox(harness, timeout_s=4.0)
    if not res.get("ok"):
        return {
            "ok": False,
            "status": str(res.get("status") or "FAILED"),
            "error": res.get("stderr") or "Coverage execution failed in sandbox.",
            "output": res,
        }

    covered_lines: list[int] = []
    for ln in str(res.get("stdout") or "").splitlines():
        if ln.startswith("__COV__"):
            covered_lines = json.loads(ln[len("__COV__"):])
            break
    covered_exec = sorted(set(covered_lines) & set(exec_lines))
    uncovered_exec = sorted(set(exec_lines) - set(covered_exec))
    pct = round((len(covered_exec) / len(exec_lines)) * 100.0, 2) if exec_lines else 100.0
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "sandbox_isolated": True,
            "total_executable_lines": len(exec_lines),
            "covered_line_count": len(covered_exec),
            "covered_lines": covered_exec,
            "uncovered_lines": uncovered_exec,
            "coverage_percent": pct,
        },
        "summary": f"วิเคราะห์ Line Coverage ใน Sandbox: {pct}% ({len(covered_exec)}/{len(exec_lines)} บรรทัด)",
    }


def _generate_mutants(module_source: str, max_mutants: int = 8) -> list[dict[str, Any]]:
    tree = ast.parse(module_source, mode="exec")
    mutants: list[dict[str, Any]] = []

    def _add_mutant(mutated_tree: ast.AST, lineno: int, mutation_op: str) -> None:
        if len(mutants) >= max_mutants:
            return
        ast.fix_missing_locations(mutated_tree)
        mutants.append({
            "mutant_id": f"M{len(mutants) + 1}",
            "line": lineno,
            "mutation": mutation_op,
            "source": ast.unparse(mutated_tree) + "\n",
        })

    for idx, node in enumerate(ast.walk(tree)):
        if len(mutants) >= max_mutants:
            break
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            cloned = copy.deepcopy(tree)
            target_nodes = [n for n in ast.walk(cloned) if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult))]
            bin_nodes_orig = [n for n in ast.walk(tree) if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult))]
            pos = bin_nodes_orig.index(node)
            t = target_nodes[pos]
            if isinstance(t.op, ast.Add):
                t.op = ast.Sub()
                _add_mutant(cloned, getattr(node, "lineno", 0), "Add -> Sub")
            elif isinstance(t.op, ast.Sub):
                t.op = ast.Add()
                _add_mutant(cloned, getattr(node, "lineno", 0), "Sub -> Add")
            elif isinstance(t.op, ast.Mult):
                t.op = ast.Add()
                _add_mutant(cloned, getattr(node, "lineno", 0), "Mult -> Add")
        elif isinstance(node, ast.Compare) and node.ops and isinstance(node.ops[0], (ast.Eq, ast.NotEq, ast.Gt, ast.Lt)):
            cloned = copy.deepcopy(tree)
            cmp_orig = [n for n in ast.walk(tree) if isinstance(n, ast.Compare) and n.ops]
            cmp_clone = [n for n in ast.walk(cloned) if isinstance(n, ast.Compare) and n.ops]
            pos = cmp_orig.index(node)
            op0 = cmp_clone[pos].ops[0]
            if isinstance(op0, ast.Eq):
                cmp_clone[pos].ops[0] = ast.NotEq()
                _add_mutant(cloned, getattr(node, "lineno", 0), "Eq -> NotEq")
            elif isinstance(op0, ast.NotEq):
                cmp_clone[pos].ops[0] = ast.Eq()
                _add_mutant(cloned, getattr(node, "lineno", 0), "NotEq -> Eq")
            elif isinstance(op0, ast.Gt):
                cmp_clone[pos].ops[0] = ast.LtE()
                _add_mutant(cloned, getattr(node, "lineno", 0), "Gt -> LtE")
            elif isinstance(op0, ast.Lt):
                cmp_clone[pos].ops[0] = ast.GtE()
                _add_mutant(cloned, getattr(node, "lineno", 0), "Lt -> GtE")
    return mutants


def _handle_mutation_testing(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    module_name = str(payload.get("module_name") or "target_mod").strip()
    module_source = str(payload.get("module_source") or "").strip()
    test_source = str(payload.get("test_source") or "").strip()
    max_mutants = max(1, min(12, int(payload.get("max_mutants") or 8)))
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,40}", module_name):
        return {"ok": False, "status": "FAILED", "error": "module_name must be a valid Python identifier.", "output": {}}
    if not module_source or not test_source:
        return {"ok": False, "status": "FAILED", "error": "module_source and test_source are required.", "output": {}}

    try:
        mutants = _generate_mutants(module_source, max_mutants=max_mutants)
    except SyntaxError as exc:
        return {"ok": False, "status": "FAILED", "error": f"Invalid module_source syntax: {exc}", "output": {}}

    with tempfile.TemporaryDirectory(prefix="zyrquen_mut_") as tmp_dir:
        ws = Path(tmp_dir)
        (ws / f"{module_name}.py").write_text(module_source, encoding="utf-8")
        (ws / f"test_{module_name}.py").write_text(test_source, encoding="utf-8")
        baseline = run_workspace_unittest(ws, timeout_s=4.0)
        if not baseline.get("ok"):
            return {
                "ok": False,
                "status": "FAILED",
                "error": f"Baseline tests must pass before mutation testing: {baseline.get('stderr')}",
                "output": {"baseline_passed": False, "baseline": baseline},
            }

        killed = 0
        survived: list[dict[str, Any]] = []
        details: list[dict[str, Any]] = []
        for m in mutants:
            (ws / f"{module_name}.py").write_text(m["source"], encoding="utf-8")
            m_res = run_workspace_unittest(ws, timeout_s=4.0)
            is_killed = not bool(m_res.get("ok"))
            if is_killed:
                killed += 1
            else:
                survived.append({"mutant_id": m["mutant_id"], "line": m["line"], "mutation": m["mutation"]})
            details.append({
                "mutant_id": m["mutant_id"],
                "line": m["line"],
                "mutation": m["mutation"],
                "status": "KILLED" if is_killed else "SURVIVED",
            })

    total = len(mutants)
    score = round(killed / total, 4) if total > 0 else 1.0
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "baseline_passed": True,
            "total_mutants": total,
            "killed": killed,
            "survived_count": len(survived),
            "mutation_score": score,
            "survived_mutants": survived,
            "details": details,
        },
        "summary": f"Mutation Testing: ฆ่า mutant ได้ {killed}/{total} (mutation_score={score})",
    }


def _handle_property_based(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    source = str(payload.get("source") or "").strip()
    function_name = str(payload.get("function_name") or "").strip()
    invariant_expr = str(payload.get("invariant_expr") or "result is not None").strip()
    arg_types = payload.get("arg_types") if isinstance(payload.get("arg_types"), list) else ["int"]
    seed = int(payload.get("seed") or 42)
    iterations = max(5, min(100, int(payload.get("iterations") or 25)))
    if not source or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,48}", function_name):
        return {"ok": False, "status": "FAILED", "error": "source and valid function_name are required.", "output": {}}

    harness = (
        f"{source}\n\n"
        "import json, random\n"
        f"_rng = random.Random({seed})\n"
        f"_arg_types = {arg_types!r}\n"
        "_failures = []\n"
        "def _gen(t):\n"
        "    if t == 'int':\n"
        "        return _rng.choice([0, -1, 1, _rng.randint(-100, 100)])\n"
        "    if t == 'pos_int':\n"
        "        return _rng.randint(1, 100)\n"
        "    if t == 'float':\n"
        "        return round(_rng.uniform(-50.0, 50.0), 3)\n"
        "    if t == 'str':\n"
        "        return ''.join(_rng.choice('abc123 ') for _ in range(_rng.randint(0, 8)))\n"
        "    if t == 'list_int':\n"
        "        return [_rng.randint(-20, 20) for _ in range(_rng.randint(0, 6))]\n"
        "    return _rng.randint(-10, 10)\n\n"
        f"for _i in range({iterations}):\n"
        "    args = [_gen(t) for t in _arg_types]\n"
        "    try:\n"
        f"        result = {function_name}(*args)\n"
        f"        _ok = bool({invariant_expr})\n"
        "        if not _ok:\n"
        "            _failures.append({'iteration': _i, 'args': args, 'result': repr(result), 'error': 'Invariant violated'})\n"
        "            break\n"
        "    except Exception as _exc:\n"
        "        _failures.append({'iteration': _i, 'args': args, 'error': type(_exc).__name__ + ': ' + str(_exc)})\n"
        "        break\n"
        "print('__PROP__' + json.dumps({'passed': len(_failures) == 0, 'iterations': _i + 1, 'failures': _failures}))\n"
    )
    res = run_python_sandbox(harness, timeout_s=4.0)
    if not res.get("ok"):
        return {"ok": False, "status": str(res.get("status") or "FAILED"), "error": res.get("stderr"), "output": res}

    parsed: dict[str, Any] = {}
    for ln in str(res.get("stdout") or "").splitlines():
        if ln.startswith("__PROP__"):
            parsed = json.loads(ln[len("__PROP__"):])
            break
    passed = bool(parsed.get("passed"))
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "passed": passed,
            "seed": seed,
            "iterations_run": parsed.get("iterations", 0),
            "counterexamples": parsed.get("failures", []),
            "sandbox_isolated": True,
        },
        "summary": (
            f"Property-Based Testing ผ่าน {parsed.get('iterations', 0)}/{iterations} รอบ (seed={seed})"
            if passed
            else f"พบ Counterexample ใน Property-Based Testing (seed={seed})"
        ),
    }


def _handle_performance_profile(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    source = str(payload.get("source") or "").strip()
    iterations = max(1, min(500, int(payload.get("iterations") or 20)))
    if not source:
        return {"ok": False, "status": "FAILED", "error": "source is required.", "output": {}}

    harness = (
        "import json, time, tracemalloc\n"
        "tracemalloc.start()\n"
        "_t0 = time.perf_counter()\n"
        f"for _iter in range({iterations}):\n"
        + "\n".join("    " + ln for ln in source.splitlines())
        + "\n_elapsed_ms = round((time.perf_counter() - _t0) * 1000, 4)\n"
        "_cur_b, _peak_b = tracemalloc.get_traced_memory()\n"
        "tracemalloc.stop()\n"
        "print('__PROF__' + json.dumps({'total_ms': _elapsed_ms, 'peak_kb': round(_peak_b / 1024, 3), 'current_kb': round(_cur_b / 1024, 3)}))\n"
    )
    res = run_python_sandbox(harness, timeout_s=5.0)
    if not res.get("ok"):
        return {"ok": False, "status": str(res.get("status") or "FAILED"), "error": res.get("stderr"), "output": res}

    prof: dict[str, Any] = {}
    for ln in str(res.get("stdout") or "").splitlines():
        if ln.startswith("__PROF__"):
            prof = json.loads(ln[len("__PROF__"):])
            break
    total_ms = float(prof.get("total_ms") or 0.0)
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "sandbox_isolated": True,
            "iterations": iterations,
            "total_ms": total_ms,
            "avg_ms_per_iteration": round(total_ms / iterations, 4),
            "peak_memory_kb": float(prof.get("peak_kb") or 0.0),
        },
        "summary": f"วัดประสิทธิภาพ {iterations} รอบใน Sandbox: รวม {total_ms} ms, Peak RAM {prof.get('peak_kb', 0)} KB",
    }


def _handle_regression_diff(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    baseline = payload.get("baseline")
    candidate = payload.get("candidate")
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        return {"ok": False, "status": "FAILED", "error": "baseline and candidate objects are required.", "output": {}}

    base_cases = {str(c.get("name") or c.get("task_id")): bool(c.get("passed")) for c in (baseline.get("tasks") or baseline.get("cases") or []) if isinstance(c, dict)}
    cand_cases = {str(c.get("name") or c.get("task_id")): bool(c.get("passed")) for c in (candidate.get("tasks") or candidate.get("cases") or []) if isinstance(c, dict)}

    newly_failed = sorted(k for k, v in cand_cases.items() if not v and base_cases.get(k) is True)
    newly_passed = sorted(k for k, v in cand_cases.items() if v and base_cases.get(k) is False)
    base_rate = float((baseline.get("metrics") or {}).get("success_rate", baseline.get("pass_rate", 0.0)))
    cand_rate = float((candidate.get("metrics") or {}).get("success_rate", candidate.get("pass_rate", 0.0)))
    rate_delta = round(cand_rate - base_rate, 4)
    regression_detected = bool(newly_failed) or rate_delta < 0.0

    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "regression_detected": regression_detected,
            "pass_rate_delta": rate_delta,
            "newly_failed": newly_failed,
            "newly_passed": newly_passed,
            "baseline_count": len(base_cases),
            "candidate_count": len(cand_cases),
        },
        "summary": (
            f"ตรวจพบ Regression ({len(newly_failed)} รายการตกใหม่, delta={rate_delta})"
            if regression_detected
            else f"ไม่พบ Regression (delta={rate_delta}, ผ่านเพิ่ม {len(newly_passed)} รายการ)"
        ),
    }


def _handle_failure_root_cause(payload: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    failures = payload.get("failures") or []
    if not isinstance(failures, list) or not failures:
        return {"ok": False, "status": "FAILED", "error": "failures array is required.", "output": {}}

    clusters: dict[str, dict[str, Any]] = {}
    for idx, f in enumerate(failures):
        if isinstance(f, str):
            name = f"failure-{idx + 1}"
            text = f
        elif isinstance(f, dict):
            name = str(f.get("name") or f.get("task_id") or f"failure-{idx + 1}")
            text = str(f.get("traceback") or f.get("stderr") or f.get("error") or "")
        else:
            continue
        m = re.search(r"([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\b", text)
        exc_cls = m.group(1) if m else "AssertionOrContractFailure"
        bucket = clusters.setdefault(exc_cls, {"exception_type": exc_cls, "count": 0, "cases": [], "sample_message": text[:200]})
        bucket["count"] += 1
        bucket["cases"].append(name)

    ranked = sorted(clusters.values(), key=lambda c: (-c["count"], c["exception_type"]))
    return {
        "ok": True,
        "status": "COMPLETED",
        "output": {
            "total_failures": len(failures),
            "cluster_count": len(ranked),
            "clusters": ranked,
            "top_root_cause": ranked[0]["exception_type"] if ranked else None,
        },
        "summary": f"จัดกลุ่มสาเหตุความล้มเหลว {len(failures)} กรณีได้ {len(ranked)} กลุ่ม (หลัก: {ranked[0]['exception_type'] if ranked else 'N/A'})",
    }


def register_testing_toolkit(registry: Any) -> None:
    manifest = ToolkitManifest(
        id="testing",
        name="Testing Toolkit",
        thai_name="ชุดเครื่องมือทดสอบและทวนสอบ",
        version="1.2.0",
        description="รันการทดสอบจริง, Line Coverage, Mutation Testing, Property-Based, Performance Profile, Regression Diff และจัดกลุ่มสาเหตุราก",
        category="testing",
        dependencies=("python_core.capability_verifier", "python_core.dataset_ingestion"),
        default_permission="auto",
        lifecycle_status="READY",
        bound_modules=(
            "python_core/capability_verifier.py",
            "python_core/dataset_ingestion.py",
            "python_core/tool_center/sandbox.py",
            "python_core/tool_center/software_engineering.py",
        ),
        documentation="ใช้ทดสอบและยืนยันการทำงานจริงของแต่ละ Toolkit และโค้ดใน Sandbox โดยไม่ปลอมสถานะ PASS",
    )

    specs = [
        (
            CapabilitySpec(
                id="testing.toolkit_self_test",
                toolkit_id="testing",
                name="ทดสอบชุดเครื่องมือจริง (Toolkit Verification Probes)",
                version="1.0.0",
                description="รันชุดทดสอบจริงทั้ง Positive และ Negative Cases ของแต่ละ Toolkit และวัดผลตามเกณฑ์ Capability Verifier",
                input_schema={
                    "type": "object",
                    "required": [],
                    "properties": {"toolkit_id": {"type": "string"}},
                },
                output_schema={"type": "object", "required": ["status", "passed", "total"]},
                dependencies=("python_core.capability_verifier",),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/capability_verifier.py",),
                documentation="ระบุ toolkit_id (เช่น 'data') หรือเว้นว่างเพื่อทดสอบทุก Toolkit ใน Tool Center",
                example_input={"toolkit_id": "data"},
                keywords=("test", "verify", "qa", "benchmark", "ทดสอบ", "ทวนสอบ"),
            ),
            _handle_toolkit_self_test,
        ),
        (
            CapabilitySpec(
                id="testing.dataset_verify",
                toolkit_id="testing",
                name="ทวนสอบ SHA-256 และความสมบูรณ์ Dataset",
                version="1.0.0",
                description="คำนวณ SHA-256 ใหม่เทียบกับฐานข้อมูลและไฟล์ Manifest บนดิสก์จริง",
                input_schema={
                    "type": "object",
                    "required": ["dataset_id"],
                    "properties": {"dataset_id": {"type": "string"}},
                },
                output_schema={"type": "object", "required": ["verified"]},
                dependencies=("python_core.dataset_ingestion",),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/dataset_ingestion.py",),
                documentation="ระบุ dataset_id ที่ต้องการตรวจสอบ checksum และ split leakage",
                example_input={"dataset_id": "ds-id"},
                keywords=("dataset", "checksum", "sha256", "verify", "ทดสอบ", "ชุดข้อมูล"),
            ),
            _handle_dataset_verify,
        ),
        (
            CapabilitySpec(
                id="testing.contract_assertion",
                toolkit_id="testing",
                name="ตรวจ Assertion เชิงสัญญาข้อมูล",
                version="1.0.0",
                description="ตรวจสอบค่าจริงเทียบกับค่าคาดหวังด้วยตัวดำเนินการ eq, ne, contains, truthy, gt, lt",
                input_schema={
                    "type": "object",
                    "required": ["cases"],
                    "properties": {"cases": {"type": "array"}},
                },
                output_schema={"type": "object", "required": ["verdict", "passed", "failed", "total"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/capability_verifier.py",),
                documentation="ส่งรายการ cases [{name, op, actual, expected}] เพื่อตรวจผลจริง",
                example_input={
                    "cases": [
                        {"name": "status_check", "op": "eq", "actual": "VERIFIED", "expected": "VERIFIED"},
                        {"name": "score_gt_zero", "op": "gt", "actual": 1, "expected": 0},
                    ]
                },
                keywords=("assert", "test", "check", "ทดสอบ"),
            ),
            _handle_contract_assertion,
        ),
        (
            CapabilitySpec(
                id="testing.sandbox_run",
                toolkit_id="testing",
                name="รันทดสอบโค้ดใน Isolated Sandbox",
                version="1.0.0",
                description="ทดสอบโค้ด Python ในไดเรกทอรีแยกพร้อมตรวจ AST Policy, ตัดตัวแปรลับ, จำกัดเวลาและทรัพยากร",
                input_schema={
                    "type": "object",
                    "required": ["source"],
                    "properties": {
                        "source": {"type": "string"},
                        "input_data": {"type": "object"},
                        "timeout_s": {"type": "number"},
                    },
                },
                output_schema={"type": "object", "required": ["sandbox_isolated", "stdout", "duration_ms"]},
                dependencies=("python_core.tool_center.sandbox",),
                permission_mode="auto",
                risk_tier="sandbox_io",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/sandbox.py",),
                documentation="ส่ง source Python เพื่อรันทดสอบอย่างปลอดภัยในสภาพแวดล้อมแยก",
                example_input={"source": "x = sum([1, 2, 3])\nprint(x)"},
                keywords=("sandbox", "execute", "test", "isolated", "ทดสอบโค้ด", "สภาพแวดล้อมแยก"),
            ),
            _handle_sandbox_run,
        ),
        (
            CapabilitySpec(
                id="testing.engineering_benchmark",
                toolkit_id="testing",
                name="รัน Real Software Engineering Benchmark",
                version="1.0.0",
                description="ทดสอบความสามารถวิศวกรรมซอฟต์แวร์จริง 6 ด้าน (Repo Understanding, Diff/Rollback, Autonomous Repair Loop, API Contract/RBAC, Security, Regression Prevention)",
                input_schema={"type": "object", "required": [], "properties": {"mode": {"type": "string", "enum": ["quick", "comprehensive"]}}},
                output_schema={"type": "object", "required": ["status", "passed", "total", "metrics", "tasks"]},
                dependencies=("python_core.tool_center.software_engineering",),
                permission_mode="auto",
                risk_tier="sandbox_io",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/software_engineering.py",),
                documentation="รันทดสอบจริงใน Sandbox แยกพร้อมวัด Success Rate, Regression Rate และเวลาจริง",
                example_input={},
                keywords=("benchmark", "engineering", "repair", "regression", "ทดสอบวิศวกรรม"),
            ),
            _handle_engineering_benchmark,
        ),
        (
            CapabilitySpec(
                id="testing.coverage_analysis",
                toolkit_id="testing",
                name="วิเคราะห์ Line Coverage ใน Sandbox (Coverage Analysis)",
                version="1.0.0",
                description="วัดบรรทัดคำสั่งที่ถูกรันจริงเทียบกับบรรทัด executable ทั้งหมดในโมดูลภายใน Isolated Sandbox",
                input_schema={
                    "type": "object",
                    "required": ["module_source", "test_source"],
                    "properties": {"module_source": {"type": "string"}, "test_source": {"type": "string"}},
                },
                output_schema={"type": "object", "required": ["coverage_percent", "total_executable_lines", "covered_line_count"]},
                dependencies=("python_core.tool_center.sandbox",),
                permission_mode="auto",
                risk_tier="sandbox_io",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/testing.py",),
                documentation="ส่ง module_source และ test_source เพื่อวัด line coverage จริง",
                example_input={"module_source": "def f(x):\n    if x > 0:\n        return x\n    return -x\n", "test_source": "assert f(3) == 3\nassert f(-2) == 2\n"},
                keywords=("coverage", "lines", "trace", "testing", "ความครอบคลุม"),
            ),
            _handle_coverage_analysis,
        ),
        (
            CapabilitySpec(
                id="testing.mutation_testing",
                toolkit_id="testing",
                name="ทดสอบความแข็งแกร่งชุดทดสอบ (Mutation Testing)",
                version="1.0.0",
                description="สร้าง AST Mutants เชิงกำหนดและรัน unittest แยกเพื่อตรวจว่าชุดทดสอบจับข้อผิดพลาดได้จริงหรือไม่",
                input_schema={
                    "type": "object",
                    "required": ["module_source", "test_source"],
                    "properties": {
                        "module_name": {"type": "string"},
                        "module_source": {"type": "string"},
                        "test_source": {"type": "string"},
                        "max_mutants": {"type": "integer"},
                    },
                },
                output_schema={"type": "object", "required": ["baseline_passed", "total_mutants", "killed", "mutation_score"]},
                dependencies=("python_core.tool_center.sandbox",),
                permission_mode="auto",
                risk_tier="sandbox_io",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/testing.py",),
                documentation="วัดคุณภาพของ unit tests ด้วยการกลายพันธุ์ AST ใน sandbox",
                example_input={
                    "module_name": "mcalc",
                    "module_source": "def add(a, b):\n    return a + b\n",
                    "test_source": "import unittest\nfrom mcalc import add\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertEqual(add(2, 3), 5)\n",
                },
                keywords=("mutation", "mutant", "quality", "testing", "ทดสอบกลายพันธุ์"),
            ),
            _handle_mutation_testing,
        ),
        (
            CapabilitySpec(
                id="testing.property_based",
                toolkit_id="testing",
                name="ทดสอบเชิงคุณสมบัติแบบสุ่มมี Seed (Property-Based Testing)",
                version="1.0.0",
                description="สร้างอินพุตหลากหลายด้วย Seed คงที่เพื่อทดสอบ Invariant ของฟังก์ชันใน Isolated Sandbox",
                input_schema={
                    "type": "object",
                    "required": ["source", "function_name"],
                    "properties": {
                        "source": {"type": "string"},
                        "function_name": {"type": "string"},
                        "arg_types": {"type": "array"},
                        "invariant_expr": {"type": "string"},
                        "seed": {"type": "integer"},
                        "iterations": {"type": "integer"},
                    },
                },
                output_schema={"type": "object", "required": ["passed", "iterations_run", "counterexamples"]},
                dependencies=("python_core.tool_center.sandbox",),
                permission_mode="auto",
                risk_tier="sandbox_io",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/testing.py",),
                documentation="ค้นหา Counterexample ของฟังก์ชันโดยใช้ Seed ที่ทำซ้ำได้",
                example_input={"source": "def abs_sq(x):\n    return x * x\n", "function_name": "abs_sq", "arg_types": ["int"], "invariant_expr": "result >= 0"},
                keywords=("property", "fuzz", "invariant", "counterexample", "seed"),
            ),
            _handle_property_based,
        ),
        (
            CapabilitySpec(
                id="testing.performance_profile",
                toolkit_id="testing",
                name="วัดประสิทธิภาพเวลาและหน่วยความจำ (Performance Profile)",
                version="1.0.0",
                description="วัด wall-clock latency และ Peak Memory (tracemalloc) ของโค้ด Python ใน Isolated Sandbox",
                input_schema={
                    "type": "object",
                    "required": ["source"],
                    "properties": {"source": {"type": "string"}, "iterations": {"type": "integer"}},
                },
                output_schema={"type": "object", "required": ["iterations", "total_ms", "avg_ms_per_iteration", "peak_memory_kb"]},
                dependencies=("python_core.tool_center.sandbox",),
                permission_mode="auto",
                risk_tier="sandbox_io",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/testing.py",),
                documentation="โปรไฟล์เวลาและความจำแบบปลอดภัยใน sandbox",
                example_input={"source": "total = sum(i * i for i in range(200))", "iterations": 10},
                keywords=("performance", "profile", "latency", "memory", "benchmark", "ประสิทธิภาพ"),
            ),
            _handle_performance_profile,
        ),
        (
            CapabilitySpec(
                id="testing.regression_diff",
                toolkit_id="testing",
                name="เปรียบเทียบ Regression ระหว่าง Baseline และ Candidate",
                version="1.0.0",
                description="เทียบผลทดสอบ/benchmark 2 รอบเพื่อตรวจหารายการที่เคยผ่านแล้วตกใหม่และส่วนต่างอัตราผ่าน",
                input_schema={
                    "type": "object",
                    "required": ["baseline", "candidate"],
                    "properties": {"baseline": {"type": "object"}, "candidate": {"type": "object"}},
                },
                output_schema={"type": "object", "required": ["regression_detected", "pass_rate_delta", "newly_failed", "newly_passed"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/testing.py",),
                documentation="ตรวจจับ regression จากผลทดสอบเชิงโครงสร้าง",
                example_input={"baseline": {"pass_rate": 1.0, "tasks": [{"name": "t1", "passed": True}]}, "candidate": {"pass_rate": 1.0, "tasks": [{"name": "t1", "passed": True}]}},
                keywords=("regression", "diff", "compare", "baseline", "ถดถอย"),
            ),
            _handle_regression_diff,
        ),
        (
            CapabilitySpec(
                id="testing.failure_root_cause",
                toolkit_id="testing",
                name="จัดกลุ่มและสรุปสาเหตุรากของความล้มเหลว (Failure Root Cause)",
                version="1.0.0",
                description="จัดกลุ่มรายการทดสอบที่ล้มเหลวตามชนิด Exception และกรณีที่ได้รับผลกระทบ",
                input_schema={
                    "type": "object",
                    "required": ["failures"],
                    "properties": {"failures": {"type": "array"}},
                },
                output_schema={"type": "object", "required": ["total_failures", "cluster_count", "clusters"]},
                dependencies=(),
                permission_mode="auto",
                risk_tier="local_readonly",
                lifecycle_status="READY",
                bound_modules=("python_core/tool_center/toolkits/testing.py",),
                documentation="สรุปกลุ่ม error หลักจากชุดทดสอบที่ล้มเหลว",
                example_input={"failures": [{"name": "test_div", "error": "ZeroDivisionError: division by zero"}]},
                keywords=("failure", "root_cause", "cluster", "traceback", "สาเหตุล้มเหลว"),
            ),
            _handle_failure_root_cause,
        ),
    ]

    registry.register_toolkit(manifest, specs)
