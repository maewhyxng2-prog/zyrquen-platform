#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — REAL-ONLY Training Worker v1.1 (Pure Python 3.11 Standard Library)
------------------------------------------------------------------------------
กฎเหล็ก:
- ไม่มี synthetic, ไม่มี mock, ไม่มี fallback, ไม่มีตัวเลขจำลอง
- ถ้าไม่มีข้อมูลจริง หรือข้อมูลไม่ผ่านการตรวจ AST / Leakage / ขั้นต่ำ -> หยุดทันที (Fail-Closed)
- ห้ามเขียนทับ Checkpoint เดิม และต้องผ่าน Approval Gate ก่อนใช้งานจริงเสมอ
- ไม่เรียกใช้โมเดลภายนอกโดยเด็ดขาด (`external_models_used: false`)
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import random
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

DISALLOWED_PROVENANCE_TOKENS = (
    "fake",
    "mock",
    "fabricated",
    "synthetic",
    "external_llm",
    "openai",
    "chatgpt",
    "claude",
    "anthropic",
    "gemini",
    "llama",
)

FEATURE_NAMES = (
    "log_ast_nodes",
    "callable_defs",
    "branch_guards",
    "exception_handlers",
    "loop_constructs",
    "return_or_assert",
)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ast_check(code: str) -> tuple[bool, int, ast.AST | None]:
    try:
        tree = ast.parse(code)
        node_count = sum(1 for _ in ast.walk(tree))
        return True, node_count, tree
    except SyntaxError:
        return False, 0, None


def sandbox_check(code: str, timeout: float = 2.0) -> tuple[bool, str | None]:
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode == 0:
            return True, None
        err = (proc.stderr or proc.stdout or f"exit_code={proc.returncode}").strip()
        return False, err[:240]
    except subprocess.TimeoutExpired:
        return False, f"timeout>{timeout}s"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def extract_ast_features(tree: ast.AST, node_count: int) -> list[float]:
    callable_defs = 0
    branch_guards = 0
    exception_handlers = 0
    loop_constructs = 0
    return_or_assert = 0

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            callable_defs += 1
        elif isinstance(node, (ast.If, ast.IfExp)):
            branch_guards += 1
        elif isinstance(node, (ast.Try, ast.ExceptHandler, ast.Raise)):
            exception_handlers += 1
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            loop_constructs += 1
        elif isinstance(node, (ast.Return, ast.Assert)):
            return_or_assert += 1

    return [
        math.log1p(max(0, node_count)),
        float(callable_defs),
        float(branch_guards),
        float(exception_handlers),
        float(loop_constructs),
        float(return_or_assert),
    ]


def _sigmoid(z: float) -> float:
    if z >= 35.0:
        return 1.0 - 1e-15
    if z <= -35.0:
        return 1e-15
    return 1.0 / (1.0 + math.exp(-z))


def _evaluate_split(
    rows: list[dict[str, Any]],
    weights: list[float],
    bias: float,
) -> dict[str, Any]:
    if not rows:
        return {
            "count": 0,
            "loss": None,
            "accuracy": None,
            "precision": None,
            "recall": None,
            "f1": None,
            "tp": 0,
            "fp": 0,
            "tn": 0,
            "fn": 0,
        }
    total_loss = 0.0
    tp = fp = tn = fn = 0
    for row in rows:
        x = row["features_norm"]
        y = int(row["label"])
        logit = bias + sum(w * xi for w, xi in zip(weights, x))
        prob = _sigmoid(logit)
        prob_clipped = min(max(prob, 1e-12), 1.0 - 1e-12)
        total_loss += -(y * math.log(prob_clipped) + (1 - y) * math.log(1.0 - prob_clipped))
        pred = 1 if prob >= 0.5 else 0
        if pred == 1 and y == 1:
            tp += 1
        elif pred == 1 and y == 0:
            fp += 1
        elif pred == 0 and y == 0:
            tn += 1
        else:
            fn += 1

    n = len(rows)
    acc = (tp + tn) / n
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2.0 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
    return {
        "count": n,
        "loss": round(total_loss / n, 6),
        "accuracy": round(acc, 6),
        "precision": round(prec, 6),
        "recall": round(rec, 6),
        "f1": round(f1, 6),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
    }


def _resolve_non_overwriting_dir(out_dir: Path, run_id: str) -> Path:
    """Ensure existing checkpoints/reports are never silently overwritten."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_file = out_dir / "checkpoint.json"
    report_file = out_dir / "evaluation_report.json"
    if not ckpt_file.exists() and not report_file.exists():
        return out_dir
    versioned = out_dir / f"run_{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}_{run_id[:8]}"
    versioned.mkdir(parents=True, exist_ok=True)
    return versioned


def _stratified_disjoint_split(
    records: list[dict[str, Any]],
    seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rng = random.Random(seed)
    pos = [r for r in records if r["label"] == 1]
    neg = [r for r in records if r["label"] == 0]
    rng.shuffle(pos)
    rng.shuffle(neg)

    def _split_bucket(bucket: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        n = len(bucket)
        if n < 3:
            raise ValueError(f"Each label class requires at least 3 samples for train/val/test split (got {n}).")
        n_val = max(1, round(n * 0.15))
        n_test = max(1, round(n * 0.15))
        if n - (n_val + n_test) < 1:
            n_val = 1
            n_test = 1
        val_part = bucket[:n_val]
        test_part = bucket[n_val : n_val + n_test]
        train_part = bucket[n_val + n_test :]
        return train_part, val_part, test_part

    tr_p, va_p, te_p = _split_bucket(pos)
    tr_n, va_n, te_n = _split_bucket(neg)
    train = tr_p + tr_n
    val = va_p + va_n
    test = te_p + te_n
    rng.shuffle(train)
    rng.shuffle(val)
    rng.shuffle(test)
    return train, val, test


def run_real_only_training(
    *,
    data_path: str | Path,
    out_dir: str | Path,
    epochs: int = 5,
    lr: float = 0.05,
    seed: int = 42,
    min_samples: int = 30,
    run_sandbox_audit: bool = False,
    require_sandbox_pass: bool = False,
    l2_reg: float = 1e-4,
) -> dict[str, Any]:
    """
    Execute fail-closed real-only training on an external JSONL file where each line is
    `{"code": "<python code>", "label": 0|1}`.
    """
    src = Path(data_path)
    if not src.exists() or not src.is_file():
        return {
            "ok": False,
            "status": "BLOCKED",
            "reason": "MISSING_DATA_FILE",
            "error": f"STOP: ไม่พบไฟล์ข้อมูลจริง: {src} — จะไม่สร้าง synthetic / mock / demo data แทน",
            "external_models_used": False,
            "synthetic_data_used": False,
        }

    file_sha = sha256_file(src)
    raw_lines = src.read_text(encoding="utf-8").splitlines()

    seen_hashes: set[str] = set()
    valid_records: list[dict[str, Any]] = []
    rejected_stats = {
        "empty_lines": 0,
        "invalid_json": 0,
        "missing_code_or_label": 0,
        "disallowed_provenance": 0,
        "syntax_error": 0,
        "sandbox_failed": 0,
        "duplicates_removed": 0,
    }
    sandbox_passed_count = 0
    sandbox_failed_count = 0

    for line_no, raw in enumerate(raw_lines, start=1):
        stripped = raw.strip()
        if not stripped:
            rejected_stats["empty_lines"] += 1
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            rejected_stats["invalid_json"] += 1
            continue
        if not isinstance(obj, dict):
            rejected_stats["invalid_json"] += 1
            continue

        code = obj.get("code")
        label = obj.get("label")
        if not isinstance(code, str) or not code.strip() or isinstance(label, bool) or label not in (0, 1):
            rejected_stats["missing_code_or_label"] += 1
            continue

        prov_blob = " ".join(
            str(obj.get(k, "") or "") for k in ("provenance", "source", "origin", "generator")
        ).lower()
        if any(tok in prov_blob for tok in DISALLOWED_PROVENANCE_TOKENS):
            rejected_stats["disallowed_provenance"] += 1
            continue

        canon_code = code.strip()
        code_hash = sha256_text(canon_code)
        if code_hash in seen_hashes:
            rejected_stats["duplicates_removed"] += 1
            continue

        ast_ok, node_count, tree = ast_check(canon_code)
        if not ast_ok or tree is None:
            rejected_stats["syntax_error"] += 1
            continue

        sb_ok: bool | None = None
        sb_err: str | None = None
        if run_sandbox_audit or require_sandbox_pass:
            sb_ok, sb_err = sandbox_check(canon_code)
            if sb_ok:
                sandbox_passed_count += 1
            else:
                sandbox_failed_count += 1
                if require_sandbox_pass:
                    rejected_stats["sandbox_failed"] += 1
                    continue

        seen_hashes.add(code_hash)
        valid_records.append(
            {
                "line_no": line_no,
                "code_sha256": code_hash,
                "label": int(label),
                "node_count": node_count,
                "features_raw": extract_ast_features(tree, node_count),
                "sandbox_passed": sb_ok,
                "sandbox_error": sb_err,
            }
        )

    if len(valid_records) < min_samples:
        return {
            "ok": False,
            "status": "BLOCKED",
            "reason": "INSUFFICIENT_REAL_DATA",
            "error": (
                f"STOP: ข้อมูลจริงที่ผ่านการตรวจสอบมีเพียง {len(valid_records)} รายการ "
                f"(ต้องการอย่างน้อย {min_samples} รายการ) — จะไม่สร้างข้อมูลจำลองเพิ่ม"
            ),
            "valid_records": len(valid_records),
            "min_samples_required": min_samples,
            "rejected_stats": rejected_stats,
            "data_sha256": file_sha,
            "external_models_used": False,
            "synthetic_data_used": False,
        }

    pos_count = sum(1 for r in valid_records if r["label"] == 1)
    neg_count = sum(1 for r in valid_records if r["label"] == 0)
    if pos_count < 3 or neg_count < 3:
        return {
            "ok": False,
            "status": "BLOCKED",
            "reason": "CLASS_IMBALANCE_UNSPLITTABLE",
            "error": (
                f"STOP: ต้องมีข้อมูลจริงทั้ง label=0 (พบ {neg_count}) และ label=1 (พบ {pos_count}) "
                f"อย่างน้อยคลาสละ 3 รายการ เพื่อแบ่ง train/val/test โดยไม่รั่วไหล"
            ),
            "valid_records": len(valid_records),
            "external_models_used": False,
            "synthetic_data_used": False,
        }

    train_rows, val_rows, test_rows = _stratified_disjoint_split(valid_records, seed=seed)

    train_hashes = {r["code_sha256"] for r in train_rows}
    val_hashes = {r["code_sha256"] for r in val_rows}
    test_hashes = {r["code_sha256"] for r in test_rows}
    leak_count = (
        len(train_hashes & val_hashes)
        + len(train_hashes & test_hashes)
        + len(val_hashes & test_hashes)
    )
    if leak_count != 0:
        return {
            "ok": False,
            "status": "BLOCKED",
            "reason": "DATA_LEAKAGE_DETECTED",
            "error": f"STOP: ตรวจพบ Data Leakage ข้าม split จำนวน {leak_count} รายการ",
            "leak_count": leak_count,
            "external_models_used": False,
            "synthetic_data_used": False,
        }

    # Normalize strictly using train split statistics (zero val/test leakage)
    num_features = len(FEATURE_NAMES)
    means = [
        sum(r["features_raw"][j] for r in train_rows) / len(train_rows)
        for j in range(num_features)
    ]
    stds = []
    for j in range(num_features):
        var = sum((r["features_raw"][j] - means[j]) ** 2 for r in train_rows) / len(train_rows)
        stds.append(math.sqrt(var) if var > 1e-12 else 1.0)

    for bucket in (train_rows, val_rows, test_rows):
        for r in bucket:
            r["features_norm"] = [
                (r["features_raw"][j] - means[j]) / stds[j] for j in range(num_features)
            ]

    weights = [0.0] * num_features
    bias = 0.0
    safe_epochs = max(1, min(500, int(epochs)))
    safe_lr = float(lr)

    initial_val_eval = _evaluate_split(val_rows, weights, bias)
    initial_test_eval = _evaluate_split(test_rows, weights, bias)

    # Majority class baseline on train split applied to test split (honest baseline, never fabricated)
    train_pos = sum(1 for r in train_rows if r["label"] == 1)
    majority_label = 1 if train_pos >= (len(train_rows) - train_pos) else 0
    majority_test_correct = sum(1 for r in test_rows if r["label"] == majority_label)
    majority_baseline_acc = round(majority_test_correct / len(test_rows), 6)

    rng = random.Random(seed)
    history: list[dict[str, Any]] = []
    nan_detected = False

    for epoch in range(1, safe_epochs + 1):
        epoch_order = list(train_rows)
        rng.shuffle(epoch_order)
        for row in epoch_order:
            x = row["features_norm"]
            y = float(row["label"])
            logit = bias + sum(w * xi for w, xi in zip(weights, x))
            prob = _sigmoid(logit)
            err = prob - y
            for j in range(num_features):
                grad = err * x[j] + l2_reg * weights[j]
                weights[j] -= safe_lr * grad
            bias -= safe_lr * err

        if any(math.isnan(w) or math.isinf(w) for w in weights) or math.isnan(bias) or math.isinf(bias):
            nan_detected = True
            break

        tr_ep = _evaluate_split(train_rows, weights, bias)
        va_ep = _evaluate_split(val_rows, weights, bias)
        history.append(
            {
                "epoch": epoch,
                "train_loss": tr_ep["loss"],
                "train_accuracy": tr_ep["accuracy"],
                "val_loss": va_ep["loss"],
                "val_accuracy": va_ep["accuracy"],
            }
        )

    if nan_detected:
        return {
            "ok": False,
            "status": "FAILED_NAN",
            "reason": "NUMERICAL_INSTABILITY",
            "error": "STOP: ตรวจพบ NaN/Inf ระหว่างการฝึก หยุดทันทีโดยไม่บันทึก Checkpoint",
            "external_models_used": False,
            "synthetic_data_used": False,
        }

    final_train_eval = _evaluate_split(train_rows, weights, bias)
    final_val_eval = _evaluate_split(val_rows, weights, bias)
    final_test_eval = _evaluate_split(test_rows, weights, bias)

    val_loss_improved = (
        final_val_eval["loss"] is not None
        and initial_val_eval["loss"] is not None
        and final_val_eval["loss"] < initial_val_eval["loss"]
    )
    beat_majority_baseline = (
        final_test_eval["accuracy"] is not None
        and final_test_eval["accuracy"] > majority_baseline_acc
    )
    improved = bool(val_loss_improved and beat_majority_baseline)
    approval_status = "PENDING_APPROVAL" if improved else "REJECTED_NO_GAIN"

    run_id = str(uuid.uuid4())
    artifact_dir = _resolve_non_overwriting_dir(Path(out_dir), run_id)
    split_hashes = {
        "train": sha256_text("\n".join(sorted(train_hashes))),
        "val": sha256_text("\n".join(sorted(val_hashes))),
        "test": sha256_text("\n".join(sorted(test_hashes))),
    }

    checkpoint_payload = {
        "schema": "zyrquen.real_only_ast_classifier.v1.1",
        "run_id": run_id,
        "created_at": _now_iso(),
        "model_family": "NativeASTLogisticClassifier",
        "external_models_used": False,
        "synthetic_data_used": False,
        "seed": seed,
        "epochs": safe_epochs,
        "lr": safe_lr,
        "l2_reg": l2_reg,
        "feature_names": list(FEATURE_NAMES),
        "normalization": {
            "fitted_on": "train_split_only",
            "mean": [round(m, 8) for m in means],
            "std": [round(s, 8) for s in stds],
        },
        "weights": [round(w, 8) for w in weights],
        "bias": round(bias, 8),
        "data_provenance": {
            "path": str(src),
            "data_sha256": file_sha,
            "split_hashes": split_hashes,
            "leak_count": leak_count,
        },
        "approval": approval_status,
    }

    ckpt_path = artifact_dir / "checkpoint.json"
    ckpt_path.write_text(json.dumps(checkpoint_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    ckpt_sha = sha256_file(ckpt_path)

    report_payload = {
        "schema": "zyrquen.real_only_evaluation_report.v1.1",
        "run_id": run_id,
        "evaluated_at": _now_iso(),
        "external_models_used": False,
        "synthetic_data_used": False,
        "data_sha256": file_sha,
        "checkpoint_sha256": ckpt_sha,
        "leak_count": leak_count,
        "dataset_summary": {
            "total_lines_read": len(raw_lines),
            "valid_dedup_records": len(valid_records),
            "label_counts": {"0": neg_count, "1": pos_count},
            "splits": {"train": len(train_rows), "val": len(val_rows), "test": len(test_rows)},
            "split_hashes": split_hashes,
            "rejected_stats": rejected_stats,
            "sandbox_audit": {
                "executed": bool(run_sandbox_audit or require_sandbox_pass),
                "require_sandbox_pass": require_sandbox_pass,
                "passed": sandbox_passed_count,
                "failed": sandbox_failed_count,
            },
        },
        "baselines": {
            "initial_zero_weights_val": initial_val_eval,
            "initial_zero_weights_test": initial_test_eval,
            "majority_class_test_accuracy": majority_baseline_acc,
            "majority_class_label": majority_label,
        },
        "final_metrics": {
            "train": final_train_eval,
            "val": final_val_eval,
            "test": final_test_eval,
        },
        "history": history,
        "improved_over_baseline": improved,
        "approval": approval_status,
        "limitations": [
            "Trains a linear AST-feature classifier (6 structural features) strictly on the supplied JSONL records; not a general-purpose pretrained LLM.",
        ],
    }

    report_path = artifact_dir / "evaluation_report.json"
    report_path.write_text(json.dumps(report_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "ok": True,
        "status": "TRAINED",
        "run_id": run_id,
        "artifact_dir": str(artifact_dir),
        "checkpoint_path": str(ckpt_path),
        "report_path": str(report_path),
        "checkpoint_sha256": ckpt_sha,
        "data_sha256": file_sha,
        "leak_count": leak_count,
        "improved": improved,
        "approval": approval_status,
        "baselines": report_payload["baselines"],
        "final_metrics": report_payload["final_metrics"],
        "dataset_summary": report_payload["dataset_summary"],
        "external_models_used": False,
        "synthetic_data_used": False,
    }


def record_real_only_training_in_db(
    conn: sqlite3.Connection,
    *,
    checkpoint_dir: Path,
    user_id: str,
    data_path: str | Path,
    epochs: int = 5,
    lr: float = 0.05,
    seed: int = 42,
    min_samples: int = 30,
    run_sandbox_audit: bool = False,
    require_sandbox_pass: bool = False,
) -> dict[str, Any]:
    """
    Execute `run_real_only_training` and, when training runs, record the candidate experiment
    in SQLite `experiments` behind the Admin Approval Gate without auto-promoting.
    """
    out_root = checkpoint_dir / "real_only_runs"
    res = run_real_only_training(
        data_path=data_path,
        out_dir=out_root,
        epochs=epochs,
        lr=lr,
        seed=seed,
        min_samples=min_samples,
        run_sandbox_audit=run_sandbox_audit,
        require_sandbox_pass=require_sandbox_pass,
    )
    if not res.get("ok"):
        return res

    exp_id = str(res["run_id"])
    baseline_metrics = res["baselines"]
    candidate_metrics = {
        "training_focus": "real_only_jsonl_ast_classifier",
        "data_sha256": res["data_sha256"],
        "checkpoint_sha256": res["checkpoint_sha256"],
        "checkpoint_path": res["checkpoint_path"],
        "report_path": res["report_path"],
        "final_metrics": res["final_metrics"],
        "leak_count": res["leak_count"],
    }
    hypothesis = (
        f"Real-only AST training on external JSONL (sha256:{res['data_sha256'][:12]}), "
        f"{epochs} epochs, seed={seed}"
    )

    dataset_ref = f"real-only:{res['data_sha256'][:12]}"
    with conn:
        conn.execute(
            """
            INSERT INTO experiments (
                id, hypothesis, dataset_id, baseline_ckpt_id, candidate_ckpt_id,
                baseline_metrics_json, candidate_metrics_json, improved,
                approval_status, approved_by, created_by, created_at
            )
            VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                exp_id,
                hypothesis,
                dataset_ref,
                json.dumps(baseline_metrics, ensure_ascii=False),
                json.dumps(candidate_metrics, ensure_ascii=False),
                1 if res["improved"] else 0,
                res["approval"],
                user_id,
                _now_iso(),
            ),
        )

    return {
        **res,
        "experiment_id": exp_id,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="ZYRQUEN Ω∞ REAL-ONLY Training Worker v1.1 (Zero synthetic/mock/fallback)"
    )
    ap.add_argument(
        "--data",
        required=True,
        help='ไฟล์ JSONL ข้อมูลจริงเท่านั้น - บรรทัดละ {"code": "...", "label": 0/1}',
    )
    ap.add_argument("--out", required=True, help="โฟลเดอร์ปลายทางสำหรับบันทึก Checkpoint และรายงาน")
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--lr", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--min-samples", type=int, default=30)
    ap.add_argument("--sandbox-audit", action="store_true", help="รันตรวจ subprocess sandbox บนโค้ดแต่ละรายการ")
    ap.add_argument("--require-sandbox-pass", action="store_true", help="คัดกรองเฉพาะโค้ดที่รันผ่าน sandbox")
    args = ap.parse_args(argv)

    result = run_real_only_training(
        data_path=args.data,
        out_dir=args.out,
        epochs=args.epochs,
        lr=args.lr,
        seed=args.seed,
        min_samples=args.min_samples,
        run_sandbox_audit=bool(args.sandbox_audit),
        require_sandbox_pass=bool(args.require_sandbox_pass),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
