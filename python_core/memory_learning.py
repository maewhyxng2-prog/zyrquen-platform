#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — 5-Tier Memory Separation & Verified Self-Improvement Engine (P2)
-----------------------------------------------------------------------------
Tiers:
  1. Working Memory (active mission context)
  2. Episodic Memory (`episodic_experiences` SQLite table)
  3. Verified Knowledge (`knowledge_triples`, strictly gated against CONFLICTING_SOURCES)
  4. Training Corpus (`datasets` curated from verified records, deduped & leakage-checked)
  5. Evaluation Corpus (strictly disjoint held-out prompts)

Controlled Self-Improvement Loop:
  Observe Mission Results -> Detect Capability Gap -> Generate Hypothesis
  -> Run Isolated Before/After Experiment -> Require Admin Approval before Promotion.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from native_neural import train_neural_model


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def record_episodic_experience(
    conn: sqlite3.Connection,
    *,
    mission_id: str | None,
    goal: str,
    outcome_status: str,
    gap_type: str | None,
    hypothesis: dict[str, Any],
    verified_delta: float = 0.0,
) -> str:
    exp_id = str(uuid.uuid4())
    with conn:
        conn.execute(
            """
            INSERT INTO episodic_experiences (
                id, mission_id, goal, outcome_status, gap_type,
                hypothesis_json, verified_delta, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exp_id,
                mission_id,
                goal[:400],
                outcome_status,
                gap_type,
                json.dumps(hypothesis, ensure_ascii=False),
                float(verified_delta),
                _now_iso(),
            ),
        )
    return exp_id


def detect_capability_gaps(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Inspect real runtime history (episodic failures, missing checkpoints, KG conflicts)."""
    gaps: list[dict[str, Any]] = []
    failed_missions = conn.execute(
        "SELECT id, goal, status FROM autonomous_missions WHERE status IN ('FAILED', 'BLOCKED') ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    for fm in failed_missions:
        gaps.append(
            {
                "gap_type": "EXECUTION_OR_EVIDENCE_GAP",
                "target": fm["goal"][:120],
                "detail": f"ภารกิจ {fm['id'][:8]} จบด้วยสถานะ {fm['status']}",
            }
        )

    neural_ckpts = conn.execute(
        "SELECT COUNT(*) FROM checkpoints WHERE eval_status LIKE 'NEURAL%'"
    ).fetchone()[0]
    if neural_ckpts == 0:
        gaps.append(
            {
                "gap_type": "NO_NEURAL_CHECKPOINT",
                "target": "native_neural_transformer",
                "detail": "ยังไม่มี Neural Transformer Checkpoint ที่ผ่านการฝึกจาก Random Initialization",
            }
        )

    clean_ds = conn.execute(
        "SELECT COUNT(*) FROM datasets WHERE leakage_detected=0 AND total_records>=5"
    ).fetchone()[0]
    if clean_ds == 0:
        gaps.append(
            {
                "gap_type": "INSUFFICIENT_TRAINING_CORPUS",
                "target": "datasets",
                "detail": "ยังไม่มีชุดข้อมูลฝึกที่ผ่านการตรวจ Data Leakage (>= 5 รายการ)",
            }
        )
    return gaps


def curate_verified_training_corpus(
    conn: sqlite3.Connection,
    user_id: str,
    ingest_fn: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    heldout_prompts: list[str] | None = None,
    name: str = "verified-knowledge-corpus",
) -> dict[str, Any]:
    """
    Build a deduplicated training corpus strictly from Verified Knowledge triples
    (excluding untrusted/conflicting/stale entries) and guard against held-out contamination.
    """
    rows = conn.execute(
        """
        SELECT subject, relation, object, source, confidence
        FROM knowledge_triples
        WHERE confidence >= 0.8
          AND source NOT LIKE '%uncorroborated%'
          AND source NOT LIKE '%conflicting%'
          AND source NOT LIKE '%stale%'
        ORDER BY created_at DESC
        LIMIT 200
        """
    ).fetchall()
    held_norm = {p.strip().lower() for p in (heldout_prompts or []) if p.strip()}
    lines: list[str] = []
    for r in rows:
        stmt = f"{r['subject']} {r['relation']} {r['object']}"
        if stmt.lower() in held_norm:
            continue
        lines.append(stmt)

    if len(lines) < 5:
        return {
            "ok": False,
            "error": f"ต้องการข้อเท็จจริงที่ยืนยันแล้วอย่างน้อย 5 รายการ (พบ {len(lines)} รายการ)",
        }
    return ingest_fn(
        {
            "name": name,
            "content": "\n".join(lines),
            "user_id": user_id,
            "provenance": "verified_knowledge_graph",
        }
    )


def run_controlled_neural_experiment(
    conn: sqlite3.Connection,
    checkpoint_dir: Path,
    user_id: str,
    *,
    dataset_id: str | None = None,
    epochs: int = 8,
    seed: int = 42,
    require_baseline_and_approval: bool = False,
) -> dict[str, Any]:
    """
    Execute an isolated controlled training experiment on a clean dataset:
    - Enforces provenance, zero data leakage, baseline evaluation, and approval gate when strict mode enabled
    - Compares random-initialized baseline loss/perplexity vs post-training held-out val/test loss
    - Saves candidate checkpoint artifact without overwriting active checkpoints
    - Records experiment in `experiments` table requiring Admin approval to promote
    """
    if dataset_id:
        ds = conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
    else:
        ds = conn.execute(
            "SELECT * FROM datasets WHERE leakage_detected=0 AND total_records>=5 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if not ds:
        return {"ok": False, "error": "ไม่พบชุดข้อมูลที่สะอาดสำหรับรันการทดลอง"}
    if ds["leakage_detected"]:
        return {"ok": False, "error": "ปฏิเสธการทดลอง: ชุดข้อมูลมี Data Leakage"}

    if require_baseline_and_approval:
        eval_count = int(conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0])
        baseline_count = int(conn.execute("SELECT COUNT(*) FROM capability_baselines").fetchone()[0])
        if eval_count == 0 and baseline_count == 0:
            return {
                "ok": False,
                "error": "Training blocked (Step 3): ต้องประเมิน Baseline ก่อนจึงจะรันการทดลองฝึกได้",
            }
        approved_runs = int(
            conn.execute(
                "SELECT COUNT(*) FROM workflow_runs WHERE group_id='native_training' AND status='COMPLETED' AND approved_by IS NOT NULL"
            ).fetchone()[0]
        )
        if approved_runs == 0:
            return {
                "ok": False,
                "error": "Training blocked (Step 4): ต้องผ่านการตรวจสอบและอนุมัติจากผู้ดูแลระบบ (Approval Gate) ก่อนเริ่มฝึก",
            }

    splits = json.loads(ds["records_json"])
    train_lines = splits.get("train", [])
    val_lines = splits.get("val", [])
    test_lines = splits.get("test", [])

    train_res = train_neural_model(
        train_lines,
        val_lines,
        test_lines,
        epochs=epochs,
        seed=seed,
    )
    if not train_res.get("ok"):
        return train_res

    init_val = float(train_res["initial_val_loss"])
    final_val = float(train_res["final_val_loss"])
    init_train = float(train_res["initial_train_loss"])
    final_train = float(train_res["final_train_loss"])

    prev_neural = conn.execute(
        "SELECT id, version, val_loss, perplexity FROM checkpoints WHERE eval_status LIKE 'NEURAL%' ORDER BY version DESC LIMIT 1"
    ).fetchone()
    prev_val_loss = float(prev_neural["val_loss"]) if prev_neural else None
    regression_detected = bool(prev_val_loss is not None and final_val > (prev_val_loss * 1.10))
    improved = (final_train < init_train) and (final_val < init_val) and not regression_detected

    exp_id = str(uuid.uuid4())
    cand_path = checkpoint_dir / f"exp_{exp_id[:8]}_neural.json.gz"
    metrics_payload = {
        "param_count": train_res["param_count"],
        "initial_train_loss": init_train,
        "final_train_loss": final_train,
        "initial_val_loss": init_val,
        "final_val_loss": final_val,
        "val_perplexity": train_res["val_perplexity"],
        "test_loss": train_res["test_loss"],
        "test_perplexity": train_res["test_perplexity"],
        "test_accuracy": train_res["test_accuracy"],
        "regression_detected": regression_detected,
        "tokenizer": train_res["tokenizer_metrics"],
        "history": train_res["history"],
    }
    train_res["model"].save_checkpoint(cand_path, train_res["tokenizer"], metrics=metrics_payload)

    hypothesis = (
        f"ฝึก Native Transformer จาก Random Init ({train_res['param_count']} params, "
        f"BPE vocab={train_res['tokenizer'].vocab_size}) บนชุดข้อมูล '{ds['name']}' {epochs} epochs "
        f"เพื่อลด validation loss"
    )
    baseline_metrics = {
        "initial_train_loss": init_train,
        "initial_val_loss": init_val,
        "prev_checkpoint_version": prev_neural["version"] if prev_neural else None,
        "prev_val_loss": prev_val_loss,
    }
    candidate_metrics = {
        "final_train_loss": final_train,
        "final_val_loss": final_val,
        "val_perplexity": train_res["val_perplexity"],
        "test_loss": train_res["test_loss"],
        "test_perplexity": train_res["test_perplexity"],
        "test_accuracy": train_res["test_accuracy"],
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
    }


def decide_experiment(
    conn: sqlite3.Connection,
    checkpoint_dir: Path,
    *,
    experiment_id: str,
    decision: str,
    admin_email: str,
    admin_id: str,
) -> dict[str, Any]:
    exp = conn.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone()
    if not exp:
        return {"ok": False, "error": "Experiment not found"}
    if exp["approval_status"] != "PENDING_APPROVAL":
        return {"ok": False, "error": f"Experiment is in state {exp['approval_status']}"}

    if decision == "reject":
        with conn:
            conn.execute(
                "UPDATE experiments SET approval_status='REJECTED', approved_by=? WHERE id=?",
                (admin_email, experiment_id),
            )
        row = dict(conn.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone())
        return {"ok": True, "experiment": row}

    if not exp["improved"]:
        return {"ok": False, "error": "Cannot promote experiment without measured improvement"}

    cand = json.loads(exp["candidate_metrics_json"] or "{}")
    weights_path = Path(str(cand.get("weights_path", "")))
    if not weights_path.exists():
        return {"ok": False, "error": "Candidate checkpoint artifact missing on disk"}

    max_ver = conn.execute("SELECT COALESCE(MAX(version), 0) FROM checkpoints").fetchone()[0]
    new_ver = int(max_ver) + 1
    ckpt_id = str(uuid.uuid4())
    final_path = checkpoint_dir / f"ckpt_neural_v{new_ver}_{ckpt_id[:8]}.json.gz"
    weights_path.replace(final_path)

    with conn:
        conn.execute(
            """
            INSERT INTO checkpoints (
                id, version, dataset_id, vocab_size, ngram_order,
                train_loss, val_loss, perplexity, eval_accuracy, eval_status,
                weights_path, created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ckpt_id,
                new_ver,
                exp["dataset_id"],
                int(cand.get("vocab_size", 0)),
                0,
                float(cand.get("final_train_loss", 0.0)),
                float(cand.get("final_val_loss", 0.0)),
                float(cand.get("val_perplexity", 1.0)),
                float(cand.get("test_accuracy", 0.0)),
                "NEURAL_VERIFIED",
                str(final_path),
                admin_id or admin_email,
                _now_iso(),
            ),
        )
        cand["weights_path"] = str(final_path)
        conn.execute(
            """
            UPDATE experiments
            SET approval_status='APPROVED', approved_by=?, candidate_ckpt_id=?, candidate_metrics_json=?
            WHERE id=?
            """,
            (admin_email, ckpt_id, json.dumps(cand, ensure_ascii=False), experiment_id),
        )

    row = dict(conn.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone())
    ckpt_row = dict(conn.execute("SELECT * FROM checkpoints WHERE id=?", (ckpt_id,)).fetchone())
    return {"ok": True, "experiment": row, "checkpoint": ckpt_row}
