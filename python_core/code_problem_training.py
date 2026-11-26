#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — Native Code Understanding & Problem-Solving Training Engine
------------------------------------------------------------------------
100% Pure Python 3.11 Standard Library (zero external LLMs, zero fabricated results).

Implements an end-to-end verifiable pipeline to train and measure ZYRQUEN's
native `NativeTransformerLM` + `NativeBPETokenizer` on code understanding,
bug diagnosis, and verified patch patterns:

1. AST + Execution-Verified Corpus Curation (`curate_code_problem_corpus`):
   - Parses real Python source files in the repository with `ast.parse` to build
     structural code-understanding records (`CODE_AST`, `CONTROL_FLOW`).
   - Verifies each bug-fix & problem-solving task by actually running `buggy_code`
     (confirming it fails its test assertions) and `fixed_code` (confirming AST
     validity + passing all assertions) before adding it to the dataset.
   - Enforces strict problem-family isolation across `train`, `val`, and `test`
     splits so unseen test problem families never appear in `train` or `val`.

2. Controlled Neural Code Training (`run_code_problem_experiment`):
   - Trains a random-initialized `NativeTransformerLM` on the curated code &
     debugging corpus (`d_model=16, n_heads=2, n_layers=1, d_ff=32, max_seq_len=32`).
   - Measures real before-vs-after held-out test loss, perplexity, token accuracy,
     and contrastive bug-vs-fix ranking accuracy on unseen problem families.
   - Stages candidate weights in `experiments` behind the Admin Approval Gate
     (never overwrites existing checkpoints).

3. Honest Unseen Code Probe Evaluation (`evaluate_code_problem_model`):
   - Evaluates the latest approved neural checkpoint (or reports `NOT_RUN`
     if no neural checkpoint is promoted yet) on unseen code-understanding and
     debugging tasks without fabricating scores.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from native_neural import NativeTransformerLM, train_neural_model
from native_tokenizer import NativeBPETokenizer

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# Curated, strictly partitioned engineering problem families.
# Families assigned to `train`, `val`, and `test` are disjoint so held-out evaluation
# measures generalization to unseen bug classes and code structures.
_CODE_PROBLEM_TASKS: tuple[dict[str, Any], ...] = (
    # --- TRAIN FAMILIES ---
    {
        "id": "prob-div-zero",
        "family": "division_zero_guard",
        "split": "train",
        "diagnosis": "ZeroDivisionError when denominator is 0; guard denominator == 0 and return safe fallback.",
        "buggy_code": "def safe_ratio(a, b):\n    return a / b\n",
        "fixed_code": "def safe_ratio(a, b):\n    if b == 0:\n        return 0.0\n    return a / b\n",
        "test_code": "assert safe_ratio(10, 2) == 5.0\nassert safe_ratio(10, 0) == 0.0\n",
    },
    {
        "id": "prob-mutable-default",
        "family": "mutable_default_arg",
        "split": "train",
        "diagnosis": "Mutable list default argument shared across calls; use None default and allocate inside function.",
        "buggy_code": "def append_item(val, items=[]):\n    items.append(val)\n    return items\n",
        "fixed_code": "def append_item(val, items=None):\n    if items is None:\n        items = []\n    items.append(val)\n    return items\n",
        "test_code": "assert append_item(1) == [1]\nassert append_item(2) == [2]\n",
    },
    {
        "id": "prob-off-by-one-slice",
        "family": "off_by_one_index",
        "split": "train",
        "diagnosis": "IndexError from off-by-one upper bound len(arr); return arr[-1] with empty check.",
        "buggy_code": "def last_elem(arr):\n    return arr[len(arr)]\n",
        "fixed_code": "def last_elem(arr):\n    if not arr:\n        return None\n    return arr[len(arr) - 1]\n",
        "test_code": "assert last_elem([4, 7, 9]) == 9\nassert last_elem([]) is None\n",
    },
    {
        "id": "prob-dict-key-missing",
        "family": "missing_dict_key",
        "split": "train",
        "diagnosis": "KeyError on direct dict indexing; use mapping.get(key, 0) for safe lookup.",
        "buggy_code": "def read_count(counts, key):\n    return counts[key] + 1\n",
        "fixed_code": "def read_count(counts, key):\n    return counts.get(key, 0) + 1\n",
        "test_code": "assert read_count({'a': 2}, 'a') == 3\nassert read_count({}, 'missing') == 1\n",
    },
    {
        "id": "prob-empty-avg",
        "family": "empty_collection_agg",
        "split": "train",
        "diagnosis": "ZeroDivisionError when averaging empty list; check if not values before sum/len.",
        "buggy_code": "def mean_vals(values):\n    return sum(values) / len(values)\n",
        "fixed_code": "def mean_vals(values):\n    if not values:\n        return 0.0\n    return sum(values) / len(values)\n",
        "test_code": "assert mean_vals([2, 4]) == 3.0\nassert mean_vals([]) == 0.0\n",
    },
    {
        "id": "prob-recursion-base",
        "family": "recursion_base_case",
        "split": "train",
        "diagnosis": "Infinite recursion without n <= 1 base case; terminate at n <= 1 returning 1.",
        "buggy_code": "def fact(n):\n    return n * fact(n - 1)\n",
        "fixed_code": "def fact(n):\n    if n <= 1:\n        return 1\n    return n * fact(n - 1)\n",
        "test_code": "assert fact(4) == 24\nassert fact(0) == 1\n",
    },
    {
        "id": "prob-clamp-bounds",
        "family": "range_clamping",
        "split": "train",
        "diagnosis": "Inverted min/max clamping; enforce low <= value <= high using max(low, min(high, value)).",
        "buggy_code": "def clamp(val, low, high):\n    return min(low, max(high, val))\n",
        "fixed_code": "def clamp(val, low, high):\n    return max(low, min(high, val))\n",
        "test_code": "assert clamp(5, 0, 10) == 5\nassert clamp(-3, 0, 10) == 0\nassert clamp(20, 0, 10) == 10\n",
    },
    {
        "id": "prob-str-strip-norm",
        "family": "string_normalization",
        "split": "train",
        "diagnosis": "Case and whitespace mismatch in identifier check; strip() and lower() before comparison.",
        "buggy_code": "def same_tag(a, b):\n    return a == b\n",
        "fixed_code": "def same_tag(a, b):\n    return str(a).strip().lower() == str(b).strip().lower()\n",
        "test_code": "assert same_tag('  Alpha ', 'alpha') is True\nassert same_tag('beta', 'gamma') is False\n",
    },
    # --- VALIDATION FAMILIES (DISJOINT FROM TRAIN & TEST) ---
    {
        "id": "prob-val-dedup-order",
        "family": "order_preserving_dedup",
        "split": "val",
        "diagnosis": "set() loses original sequence order; track seen items in set while appending in order.",
        "buggy_code": "def dedup_ordered(items):\n    return list(set(items))\n",
        "fixed_code": "def dedup_ordered(items):\n    seen = set()\n    out = []\n    for x in items:\n        if x not in seen:\n            seen.add(x)\n            out.append(x)\n    return out\n",
        "test_code": "assert dedup_ordered([3, 1, 2, 3, 1]) == [3, 1, 2]\nassert dedup_ordered(['b', 'a', 'b']) == ['b', 'a'] or dedup_ordered([9, 2, 5, 2, 9]) == [9, 2, 5]\n",
    },
    {
        "id": "prob-val-shallow-copy",
        "family": "input_mutation_leak",
        "split": "val",
        "diagnosis": "Mutates caller dict in place; copy dictionary before setting normalized status field.",
        "buggy_code": "def with_status(rec, status):\n    rec['status'] = status\n    return rec\n",
        "fixed_code": "def with_status(rec, status):\n    out = dict(rec)\n    out['status'] = status\n    return out\n",
        "test_code": "orig = {'id': 1}\nout = with_status(orig, 'OK')\nassert out['status'] == 'OK' and 'status' not in orig\n",
    },
    {
        "id": "prob-val-none-guard",
        "family": "null_text_guard",
        "split": "val",
        "diagnosis": "AttributeError when text is None; coalesce None to empty string before strip.",
        "buggy_code": "def clean_name(text):\n    return text.strip()\n",
        "fixed_code": "def clean_name(text):\n    return (text or '').strip()\n",
        "test_code": "assert clean_name(None) == ''\nassert clean_name('  ok ') == 'ok'\n",
    },
    # --- HELD-OUT UNSEEN TEST FAMILIES (DISJOINT FROM TRAIN & VAL) ---
    {
        "id": "prob-test-binary-search",
        "family": "binary_search_boundary",
        "split": "test",
        "diagnosis": "Binary search uses strict lo < hi and misses single-element boundary; use lo <= hi.",
        "buggy_code": "def bsearch(nums, target):\n    lo, hi = 0, len(nums) - 1\n    while lo < hi:\n        mid = (lo + hi) // 2\n        if nums[mid] == target:\n            return mid\n        if nums[mid] < target:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return -1\n",
        "fixed_code": "def bsearch(nums, target):\n    lo, hi = 0, len(nums) - 1\n    while lo <= hi:\n        mid = (lo + hi) // 2\n        if nums[mid] == target:\n            return mid\n        if nums[mid] < target:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return -1\n",
        "test_code": "assert bsearch([1, 3, 5, 7], 7) == 3\nassert bsearch([1, 3, 5, 7], 1) == 0\nassert bsearch([1, 3, 5, 7], 4) == -1\n",
    },
    {
        "id": "prob-test-int-parse",
        "family": "safe_integer_parsing",
        "split": "test",
        "diagnosis": "ValueError on non-numeric string; wrap int(raw) in try/except ValueError returning default.",
        "buggy_code": "def parse_int(raw, default=0):\n    return int(raw)\n",
        "fixed_code": "def parse_int(raw, default=0):\n    try:\n        return int(raw)\n    except (TypeError, ValueError):\n        return default\n",
        "test_code": "assert parse_int('42') == 42\nassert parse_int('abc', -1) == -1\nassert parse_int(None, 0) == 0\n",
    },
    {
        "id": "prob-test-path-traversal",
        "family": "path_traversal_guard",
        "split": "test",
        "diagnosis": "Path traversal via '..' escapes base directory; resolve paths and enforce is_relative_to(base).",
        "buggy_code": "from pathlib import Path\ndef safe_child(base, rel):\n    return Path(base) / rel\n",
        "fixed_code": "from pathlib import Path\ndef safe_child(base, rel):\n    root = Path(base).resolve()\n    target = (root / rel).resolve()\n    if not target.is_relative_to(root):\n        raise ValueError('path escapes root')\n    return target\n",
        "test_code": "from pathlib import Path\ntry:\n    safe_child('/tmp/ws', '../etc/passwd')\n    assert False, 'expected ValueError'\nexcept ValueError:\n    pass\nassert safe_child('/tmp/ws', 'a.txt') == Path('/tmp/ws/a.txt').resolve()\n",
    },
)


def _exec_with_step_limit(code_str: str, label: str, max_steps: int = 15000) -> dict[str, Any]:
    steps = 0
    prev_trace = sys.gettrace()

    def _tracer(frame: Any, event: str, arg: Any) -> Any:
        nonlocal steps
        steps += 1
        if steps > max_steps:
            raise TimeoutError(f"Execution exceeded {max_steps} trace steps")
        return _tracer

    ns: dict[str, Any] = {}
    compiled = compile(code_str, label, "exec")
    sys.settrace(_tracer)
    try:
        exec(compiled, ns, ns)
    finally:
        sys.settrace(prev_trace)
    return ns


def _verify_task_execution(task: dict[str, Any]) -> dict[str, Any]:
    """
    Execute buggy_code and fixed_code in clean isolated dicts to confirm:
    1. Both parse or buggy fails expected tests.
    2. fixed_code passes ast.parse() and passes every assertion in test_code.
    """
    fixed_code = str(task.get("fixed_code") or "")
    buggy_code = str(task.get("buggy_code") or "")
    test_code = str(task.get("test_code") or "")

    try:
        ast.parse(fixed_code)
        fixed_ast_ok = True
    except SyntaxError:
        fixed_ast_ok = False

    buggy_failed = False
    try:
        _exec_with_step_limit(buggy_code + "\n" + test_code, f"<{task['id']}:buggy>")
    except Exception:
        buggy_failed = True

    fixed_passed = False
    fixed_error: str | None = None
    if fixed_ast_ok:
        try:
            _exec_with_step_limit(fixed_code + "\n" + test_code, f"<{task['id']}:fixed>")
            fixed_passed = True
        except Exception as exc:
            fixed_error = f"{type(exc).__name__}: {exc}"

    return {
        "id": str(task["id"]),
        "family": str(task["family"]),
        "split": str(task["split"]),
        "fixed_ast_ok": fixed_ast_ok,
        "buggy_failed_as_expected": buggy_failed,
        "fixed_passed": fixed_passed,
        "fixed_error": fixed_error,
        "verified": bool(fixed_ast_ok and buggy_failed and fixed_passed),
    }


def _extract_repo_ast_records(max_records: int = 36) -> list[dict[str, str]]:
    """
    Inspect real Python source files in `python_core/` and `apps/core/intelligence/`
    via `ast.parse` to create structural code-understanding records without fabrication.
    """
    candidates = [
        _REPO_ROOT / "python_core" / "dataset_ingestion.py",
        _REPO_ROOT / "python_core" / "native_neural.py",
        _REPO_ROOT / "python_core" / "tools_engine.py",
        _REPO_ROOT / "apps" / "core" / "intelligence" / "static_validation.py",
    ]
    records: list[dict[str, str]] = []
    for path in candidates:
        if not path.exists():
            continue
        try:
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(path))
        except (OSError, SyntaxError):
            continue
        rel_name = path.relative_to(_REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                args = [a.arg for a in node.args.args[:5]]
                has_try = any(isinstance(sub, ast.Try) for sub in ast.walk(node))
                has_if = any(isinstance(sub, ast.If) for sub in ast.walk(node))
                has_raise = any(isinstance(sub, ast.Raise) for sub in ast.walk(node))
                has_return = any(isinstance(sub, ast.Return) for sub in ast.walk(node))
                guards = []
                if has_if:
                    guards.append("branch_guard")
                if has_try:
                    guards.append("try_except")
                if has_raise:
                    guards.append("explicit_raise")
                if has_return:
                    guards.append("explicit_return")
                line = (
                    f"CODE_AST {rel_name} def {node.name}({', '.join(args)}) -> "
                    f"patterns: {' '.join(guards) or 'straight_line'}"
                )
                records.append({"text": line, "source": rel_name, "kind": "code_ast"})
                if len(records) >= max_records:
                    return records
    return records


def _diff_patch_snippet(task: dict[str, Any]) -> tuple[str, str]:
    """Extract concise differing lines between buggy_code and fixed_code so sequences fit within max_seq_len."""
    bug_lines = [ln.strip() for ln in str(task["buggy_code"]).splitlines() if ln.strip()]
    fix_lines = [ln.strip() for ln in str(task["fixed_code"]).splitlines() if ln.strip()]
    bug_set = set(bug_lines)
    fix_set = set(fix_lines)
    bug_diff = [ln for ln in bug_lines if ln not in fix_set] or bug_lines
    fix_diff = [ln for ln in fix_lines if ln not in bug_set] or fix_lines
    return " ; ".join(bug_diff), " ; ".join(fix_diff)


def _format_task_training_lines(task: dict[str, Any]) -> list[str]:
    """Convert a verified bug-fix task into concise structured code-understanding sequences."""
    bug_snip, fix_snip = _diff_patch_snippet(task)
    return [
        f"BUG {bug_snip} # {task['family']}",
        f"FIX {fix_snip} # {task['family']}",
    ]


def curate_code_problem_corpus(
    conn: sqlite3.Connection,
    user_id: str,
    ingest_fn: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    name: str = "code-problem-solving-corpus",
    extra_tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Build a strictly split, AST- and execution-verified code understanding &
    problem-solving dataset and register it via `ingest_fn`.
    """
    tasks = list(_CODE_PROBLEM_TASKS)
    if extra_tasks:
        for item in extra_tasks:
            if isinstance(item, dict) and item.get("fixed_code") and item.get("buggy_code"):
                tasks.append({
                    "id": str(item.get("id") or f"custom-{uuid.uuid4().hex[:8]}"),
                    "family": str(item.get("family") or f"custom_{uuid.uuid4().hex[:6]}"),
                    "split": str(item.get("split") or "train") if item.get("split") in {"train", "val", "test"} else "train",
                    "diagnosis": str(item.get("diagnosis") or "Verified bug fix"),
                    "buggy_code": str(item["buggy_code"]),
                    "fixed_code": str(item["fixed_code"]),
                    "test_code": str(item.get("test_code") or "assert True"),
                })

    verifications: list[dict[str, Any]] = []
    splits_payload: dict[str, list[dict[str, Any]]] = {"train": [], "val": [], "test": []}

    for task in tasks:
        ver = _verify_task_execution(task)
        verifications.append(ver)
        if not ver["verified"]:
            continue
        sp = ver["split"] if ver["split"] in splits_payload else "train"
        for line in _format_task_training_lines(task):
            splits_payload[sp].append({
                "text": line,
                "source": f"verified_task:{ver['family']}",
                "split": sp,
            })

    # Add real AST records from repository files ONLY into `train` and `val`
    # keeping `test` exclusively for unseen problem families.
    ast_records = _extract_repo_ast_records(max_records=6)
    for idx, rec in enumerate(ast_records):
        target_sp = "val" if idx % 6 == 0 else "train"
        splits_payload[target_sp].append({
            "text": rec["text"],
            "source": rec["source"],
            "split": target_sp,
        })

    if not splits_payload["train"] or not splits_payload["val"] or not splits_payload["test"]:
        return {
            "ok": False,
            "error": "Unable to build non-empty train/val/test verified code splits.",
            "verifications": verifications,
        }

    ingest_res = ingest_fn({
        "name": name,
        "splits": splits_payload,
        "user_id": user_id,
        "provenance": "native_ast_and_sandbox_verified",
        "source_name": "zyrquen_code_problem_tasks",
        "license": "INTERNAL_VERIFIED",
        "extract_kg": False,
        "redact_pii": True,
        "strict_entity_isolation": False,
    })
    if not ingest_res.get("ok"):
        return ingest_res

    verified_count = sum(1 for v in verifications if v["verified"])
    return {
        **ingest_res,
        "code_verification": {
            "total_tasks": len(verifications),
            "verified_tasks": verified_count,
            "failed_tasks": len(verifications) - verified_count,
            "ast_records_added": len(ast_records),
            "splits_counts": {k: len(v) for k, v in splits_payload.items()},
            "tasks": verifications,
        },
    }


def _score_contrastive_code_probe(
    model: NativeTransformerLM,
    tokenizer: NativeBPETokenizer,
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Evaluate whether `model` assigns lower cross-entropy loss to verified fixed code
    patterns than to buggy code patterns on held-out unseen problem families.
    """
    cases: list[dict[str, Any]] = []
    correct = 0
    for task in tasks:
        bug_snip, fix_snip = _diff_patch_snippet(task)
        fix_text = f"FIX {fix_snip} # {task['family']}"
        bug_text = f"FIX {bug_snip} # {task['family']}"

        fix_seq = tokenizer.encode(fix_text, add_bos=True, add_eos=True)
        bug_seq = tokenizer.encode(bug_text, add_bos=True, add_eos=True)
        fix_eval = model.evaluate_sequences([fix_seq])
        bug_eval = model.evaluate_sequences([bug_seq])
        passed = float(fix_eval["loss"]) < float(bug_eval["loss"])
        if passed:
            correct += 1
        cases.append({
            "task_id": task["id"],
            "family": task["family"],
            "fix_loss": round(float(fix_eval["loss"]), 4),
            "bug_loss": round(float(bug_eval["loss"]), 4),
            "preferred_fix": passed,
        })
    total = len(cases)
    return {
        "total": total,
        "passed": correct,
        "accuracy": round(correct / max(1, total), 4),
        "cases": cases,
    }


def run_code_problem_experiment(
    conn: sqlite3.Connection,
    checkpoint_dir: Path,
    user_id: str,
    *,
    dataset_id: str | None = None,
    epochs: int = 3,
    seed: int = 42,
) -> dict[str, Any]:
    """
    Train a random-initialized `NativeTransformerLM` on code understanding &
    debugging splits, evaluate pre- vs post-training loss & contrastive bug-vs-fix
    generalization on unseen problem families, and stage behind Approval Gate.
    """
    if dataset_id:
        ds = conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
    else:
        ds = conn.execute(
            """
            SELECT * FROM datasets
            WHERE leakage_detected=0
              AND total_records>=5
              AND (provenance='native_ast_and_sandbox_verified' OR name LIKE '%code%')
            ORDER BY created_at DESC LIMIT 1
            """
        ).fetchone()
    if not ds:
        return {
            "ok": False,
            "error": "ไม่พบชุดข้อมูลโค้ดที่สะอาดและผ่านการตรวจ AST/Sandbox — กรุณาเตรียมชุดข้อมูลโค้ดก่อน",
        }
    if ds["leakage_detected"]:
        return {"ok": False, "error": "ปฏิเสธการฝึก: ชุดข้อมูลมี Data Leakage"}

    splits = json.loads(ds["records_json"])
    train_lines = list(splits.get("train", []))
    val_lines = list(splits.get("val", []))
    test_lines = list(splits.get("test", []))
    if not train_lines or not val_lines or not test_lines:
        return {"ok": False, "error": "ชุดข้อมูลต้องมี split train/val/test ครบทั้ง 3 ส่วน"}

    safe_epochs = max(2, min(8, int(epochs)))
    unseen_tasks = [t for t in _CODE_PROBLEM_TASKS if t["split"] == "test"]
    task_checks = [_verify_task_execution(t) for t in unseen_tasks]

    # Measure random-init pre-training contrastive baseline with the same tokenizer & seed
    pre_tok = NativeBPETokenizer.train(train_lines, target_vocab_size=310, min_pair_freq=2, version=1)
    pre_model = NativeTransformerLM(
        vocab_size=pre_tok.vocab_size,
        d_model=16,
        n_heads=2,
        n_layers=1,
        d_ff=32,
        max_seq_len=32,
        seed=seed,
    )
    pre_contrastive = _score_contrastive_code_probe(pre_model, pre_tok, unseen_tasks)

    train_res = train_neural_model(
        train_lines,
        val_lines,
        test_lines,
        d_model=16,
        n_heads=2,
        n_layers=1,
        d_ff=32,
        max_seq_len=32,
        epochs=safe_epochs,
        lr=0.022,
        grad_accum_steps=2,
        target_vocab_size=310,
        seed=seed,
    )
    if not train_res.get("ok"):
        return train_res

    post_contrastive = _score_contrastive_code_probe(
        train_res["model"], train_res["tokenizer"], unseen_tasks
    )

    init_train = float(train_res["initial_train_loss"])
    final_train = float(train_res["final_train_loss"])
    init_val = float(train_res["initial_val_loss"])
    final_val = float(train_res["final_val_loss"])

    prev_neural = conn.execute(
        "SELECT id, version, val_loss, perplexity FROM checkpoints WHERE eval_status LIKE 'NEURAL%' ORDER BY version DESC LIMIT 1"
    ).fetchone()
    prev_val_loss = float(prev_neural["val_loss"]) if prev_neural else None
    regression_detected = bool(prev_val_loss is not None and final_val > (prev_val_loss * 1.15))
    improved = (final_train < init_train) and (final_val < init_val) and not regression_detected

    exp_id = str(uuid.uuid4())
    cand_path = checkpoint_dir / f"exp_code_{exp_id[:8]}_neural.json.gz"
    metrics_payload = {
        "training_focus": "code_understanding_and_problem_solving",
        "param_count": train_res["param_count"],
        "initial_train_loss": init_train,
        "final_train_loss": final_train,
        "initial_val_loss": init_val,
        "final_val_loss": final_val,
        "val_perplexity": train_res["val_perplexity"],
        "test_loss": train_res["test_loss"],
        "test_perplexity": train_res["test_perplexity"],
        "test_accuracy": train_res["test_accuracy"],
        "pre_contrastive_accuracy": pre_contrastive["accuracy"],
        "post_contrastive_accuracy": post_contrastive["accuracy"],
        "contrastive_probe": post_contrastive,
        "unseen_execution_verified": all(c["verified"] for c in task_checks),
        "regression_detected": regression_detected,
        "tokenizer": train_res["tokenizer_metrics"],
        "history": train_res["history"],
        "honest_limitations": [
            "NativeTransformerLM runs at token level with max_seq_len=32 and compact parameter budget on CPU; it measures code-token cross-entropy and contrastive fix-vs-bug ranking rather than full multi-file code synthesis.",
        ],
    }
    train_res["model"].save_checkpoint(cand_path, train_res["tokenizer"], metrics=metrics_payload)

    hypothesis = (
        f"ฝึก Native Transformer ด้านความเข้าใจโค้ดและแก้ปัญหา ({train_res['param_count']} params, "
        f"max_seq_len=32) บนชุดข้อมูล '{ds['name']}' {safe_epochs} epochs"
    )
    baseline_metrics = {
        "initial_train_loss": init_train,
        "initial_val_loss": init_val,
        "pre_contrastive_accuracy": pre_contrastive["accuracy"],
        "prev_checkpoint_version": prev_neural["version"] if prev_neural else None,
        "prev_val_loss": prev_val_loss,
    }
    candidate_metrics = {
        "training_focus": "code_understanding_and_problem_solving",
        "final_train_loss": final_train,
        "final_val_loss": final_val,
        "val_perplexity": train_res["val_perplexity"],
        "test_loss": train_res["test_loss"],
        "test_perplexity": train_res["test_perplexity"],
        "test_accuracy": train_res["test_accuracy"],
        "post_contrastive_accuracy": post_contrastive["accuracy"],
        "regression_detected": regression_detected,
        "param_count": train_res["param_count"],
        "vocab_size": train_res["tokenizer"].vocab_size,
        "weights_path": str(cand_path),
    }

    if regression_detected:
        approval_status = "REGRESSION_FAILED"
    elif improved:
        approval_status = "PENDING_APPROVAL"
    else:
        approval_status = "REJECTED_NO_GAIN"

    with conn:
        conn.execute(
            """
            INSERT INTO experiments (
                id, hypothesis, dataset_id, baseline_ckpt_id, candidate_ckpt_id,
                baseline_metrics_json, candidate_metrics_json, improved,
                approval_status, approved_by, created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                exp_id,
                hypothesis,
                ds["id"],
                prev_neural["id"] if prev_neural else None,
                None,
                json.dumps(baseline_metrics, ensure_ascii=False),
                json.dumps(candidate_metrics, ensure_ascii=False),
                1 if improved else 0,
                approval_status,
                user_id,
                _now_iso(),
            ),
        )

    exp_row = dict(conn.execute("SELECT * FROM experiments WHERE id=?", (exp_id,)).fetchone())
    return {
        "ok": True,
        "experiment": exp_row,
        "improved": improved,
        "metrics": metrics_payload,
        "external_models_used": False,
    }


def evaluate_code_problem_model(conn: sqlite3.Connection) -> dict[str, Any]:
    """
    Evaluate the latest promoted neural checkpoint on unseen code-understanding
    and debugging tasks. Returns honest `NOT_RUN` if no promoted checkpoint exists.
    """
    unseen_tasks = [t for t in _CODE_PROBLEM_TASKS if t["split"] == "test"]
    task_checks = [_verify_task_execution(t) for t in unseen_tasks]

    ckpt = conn.execute(
        "SELECT * FROM checkpoints WHERE eval_status LIKE 'NEURAL%' ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if not ckpt:
        return {
            "ok": True,
            "status": "NOT_RUN",
            "reason": "ยังไม่มี Neural Checkpoint ที่ผ่านการอนุมัติโปรโมตในระบบ",
            "unseen_task_execution_checks": task_checks,
            "external_models_used": False,
        }

    weights_path = Path(str(ckpt["weights_path"] or ""))
    if not weights_path.exists():
        return {
            "ok": False,
            "status": "BLOCKED",
            "error": f"ไม่พบไฟล์น้ำหนัก Checkpoint v{ckpt['version']} บนดิสก์",
            "external_models_used": False,
        }

    model, tokenizer, saved_metrics = NativeTransformerLM.load_checkpoint(weights_path)
    unseen_lines = []
    for t in unseen_tasks:
        unseen_lines.extend(_format_task_training_lines(t))
    seqs = [tokenizer.encode(ln, add_bos=True, add_eos=True) for ln in unseen_lines if ln.strip()]
    seq_eval = model.evaluate_sequences(seqs)
    contrastive = _score_contrastive_code_probe(model, tokenizer, unseen_tasks)

    return {
        "ok": True,
        "status": "VERIFIED" if all(c["verified"] for c in task_checks) and seq_eval["loss"] > 0 else "PARTIAL",
        "checkpoint_version": int(ckpt["version"]),
        "dataset_id": ckpt["dataset_id"],
        "unseen_test_loss": round(float(seq_eval["loss"]), 4),
        "unseen_test_perplexity": round(float(seq_eval["perplexity"]), 3),
        "unseen_token_accuracy": round(float(seq_eval["accuracy"]), 4),
        "contrastive_probe": contrastive,
        "unseen_task_execution_checks": task_checks,
        "training_focus": saved_metrics.get("training_focus", "general_neural"),
        "external_models_used": False,
    }
