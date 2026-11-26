#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — Continual Learning, Anti-Forgetting Consolidation & Failure-Driven Curriculum Synthesis
---------------------------------------------------------------------------------------------------
100% Pure Python 3.11 Standard Library (browser-independent, zero external AI models).

Addresses Priority 2 & Priority 3 of the ZYRQUEN Master Architecture Directive:
1. Failure-Driven Curriculum Synthesis:
   - Inspects unresolved `reasoning_traces` (`NOT_LEARNED`, `BLOCKED`, `FAILED`) and
     `episodic_experiences` (`FAILED`, `BLOCKED`).
   - Grounds remediation statements strictly in verified `knowledge_triples` (never fabricates
     answers) while checking against held-out prompts & eval splits to block data leakage.
2. Continual Learning & Catastrophic Forgetting Protection:
   - Resumes from existing verified `NativeTransformerLM` checkpoints (preserving lineage) or
     initializes a random-init baseline round when no prior neural checkpoint exists.
   - Mixes deterministic Experience Replay samples with new training records.
   - Applies L2 Anchor Weight Consolidation (`anchor_l2_lambda * (theta - theta_prev)`) during
     backpropagation to resist catastrophic forgetting of previously learned representations.
   - Measures pre- vs post-round retention on an anchor set and gates promotion strictly via
     Approval Gate (`FORGETTING_FAILED` / `PENDING_APPROVAL` / `REJECTED_NO_GAIN`).
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from native_neural import (
    NativeTransformerLM,
    _adamw_step,
    _grad_l2_norm,
    train_neural_model,
)
from native_tokenizer import NativeBPETokenizer


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _classify_trace_failure(row: sqlite3.Row) -> str:
    status = str(row["status"] or "").upper()
    prompt_l = str(row["prompt"] or "").lower()
    trace_raw = str(row["trace_json"] or "")
    if "contradiction" in trace_raw.lower() or "ขัดแย้ง" in trace_raw:
        return "causal_contradiction"
    if status in {"NOT_LEARNED", "UNKNOWN"}:
        return "unlearned_concept"
    if status == "UNCERTAIN":
        return "ambiguous_or_uncertain_intent"
    if status == "UNABLE_TO_INFER" or any(k in prompt_l for k in ("ถ้า", "หาก", "ทุก", "ไม่มี", "if ", "all ", "สมการ", "=")):
        return "symbolic_reasoning_gap"
    return "execution_or_evidence_gap"


def synthesize_failure_curriculum(
    conn: sqlite3.Connection,
    *,
    heldout_prompts: list[str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """
    Synthesize a leakage-checked remediation curriculum from real failures in
    `reasoning_traces` and `episodic_experiences`, paired strictly with verified
    `knowledge_triples` (never fabricates unverified answers).
    """
    safe_limit = max(1, min(int(limit), 200))

    # Build held-out leakage exclusion set from caller + existing datasets val/test splits
    excluded_norm: set[str] = {_norm(p) for p in (heldout_prompts or []) if _norm(p)}
    ds_rows = conn.execute("SELECT records_json FROM datasets").fetchall()
    for ds in ds_rows:
        try:
            splits = json.loads(ds["records_json"] or "{}")
            for split_name in ("val", "test", "unseen", "ood"):
                for rec in splits.get(split_name, []) or []:
                    nk = _norm(rec)
                    if nk:
                        excluded_norm.add(nk)
        except Exception:
            continue

    # Load verified knowledge triples only (confidence >= 0.8, excluding conflicting/stale)
    triples = conn.execute(
        """
        SELECT subject, relation, object, source, confidence
        FROM knowledge_triples
        WHERE confidence >= 0.8
          AND source NOT LIKE '%uncorroborated%'
          AND source NOT LIKE '%conflicting%'
          AND source NOT LIKE '%stale%'
        ORDER BY created_at DESC
        LIMIT 300
        """
    ).fetchall()

    triple_index: list[tuple[str, str, str, str, set[str]]] = []
    for t in triples:
        stmt = f"{t['subject']} {t['relation']} {t['object']}"
        toks = {
            w.lower()
            for w in re.findall(r"[A-Za-z0-9_]+|[\u0E00-\u0E7F]{2,}", stmt)
            if len(w) >= 2
        }
        triple_index.append(
            (str(t["subject"]), str(t["relation"]), str(t["object"]), stmt, toks)
        )

    trace_failures = conn.execute(
        """
        SELECT id, prompt, status, mode, trace_json, created_at
        FROM reasoning_traces
        WHERE status IN ('NOT_LEARNED', 'UNABLE_TO_INFER', 'UNCERTAIN', 'UNKNOWN', 'BLOCKED', 'FAILED')
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (safe_limit,),
    ).fetchall()

    episodic_failures = conn.execute(
        """
        SELECT id, mission_id, goal, outcome_status, gap_type, hypothesis_json, created_at
        FROM episodic_experiences
        WHERE outcome_status IN ('FAILED', 'BLOCKED')
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (safe_limit,),
    ).fetchall()

    gap_breakdown: dict[str, int] = {}
    curriculum_items: list[dict[str, Any]] = []
    unresolved_gaps: list[dict[str, Any]] = []
    seen_stmt_norm: set[str] = set()
    leaked_skipped = 0

    def _process_signal(
        *,
        source_type: str,
        source_id: str,
        raw_prompt: str,
        gap_category: str,
    ) -> None:
        nonlocal leaked_skipped
        gap_breakdown[gap_category] = gap_breakdown.get(gap_category, 0) + 1
        q_tokens = {
            w.lower()
            for w in re.findall(r"[A-Za-z0-9_]+|[\u0E00-\u0E7F]{2,}", raw_prompt)
            if len(w) >= 2
        }
        matched_stmts: list[tuple[int, str]] = []
        for subj, _rel, _obj, stmt, t_toks in triple_index:
            overlap = len(q_tokens & t_toks)
            if subj.lower() in raw_prompt.lower():
                overlap += 2
            if overlap > 0:
                matched_stmts.append((overlap, stmt))
        matched_stmts.sort(key=lambda item: -item[0])

        remediated = False
        for _score, stmt in matched_stmts[:2]:
            sn = _norm(stmt)
            if sn in excluded_norm:
                leaked_skipped += 1
                continue
            if sn in seen_stmt_norm:
                remediated = True
                continue
            seen_stmt_norm.add(sn)
            curriculum_items.append(
                {
                    "source_type": source_type,
                    "source_id": source_id,
                    "gap_category": gap_category,
                    "trigger_prompt": raw_prompt[:160],
                    "training_statement": stmt,
                    "provenance": "verified_knowledge_triple",
                }
            )
            remediated = True

        if not remediated:
            unresolved_gaps.append(
                {
                    "source_type": source_type,
                    "source_id": source_id,
                    "gap_category": gap_category,
                    "prompt": raw_prompt[:160],
                    "reason": "no_verified_triple_grounding",
                }
            )

    for tr in trace_failures:
        _process_signal(
            source_type="reasoning_trace",
            source_id=str(tr["id"]),
            raw_prompt=str(tr["prompt"] or ""),
            gap_category=_classify_trace_failure(tr),
        )

    for ep in episodic_failures:
        _process_signal(
            source_type="episodic_experience",
            source_id=str(ep["id"]),
            raw_prompt=str(ep["goal"] or ""),
            gap_category=str(ep["gap_type"] or "execution_or_evidence_gap"),
        )

    manifest_payload = json.dumps(
        [item["training_statement"] for item in curriculum_items],
        ensure_ascii=False,
        sort_keys=False,
    ).encode("utf-8")
    manifest_sha256 = hashlib.sha256(manifest_payload).hexdigest()

    return {
        "ok": True,
        "traces_scanned": len(trace_failures),
        "episodes_scanned": len(episodic_failures),
        "curriculum_count": len(curriculum_items),
        "curriculum_items": curriculum_items,
        "unresolved_gaps_count": len(unresolved_gaps),
        "unresolved_gaps": unresolved_gaps[:25],
        "gap_breakdown": gap_breakdown,
        "leaked_items_filtered": leaked_skipped,
        "leakage_checked": True,
        "ready_for_replay": len(curriculum_items) >= 2,
        "manifest_sha256": manifest_sha256,
        "synthesized_at": _now_iso(),
    }


def _add_l2_anchor_grads(
    params: Any,
    anchor_params: Any,
    grads: Any,
    l2_lambda: float,
) -> None:
    """Add EWC-lite isotropic quadratic consolidation gradient: lambda * (theta - theta_anchor)."""
    if l2_lambda <= 0.0:
        return

    def _walk(p: Any, ap: Any, g: Any) -> None:
        if isinstance(p, dict):
            for k in p:
                _walk(p[k], ap[k], g[k])
        elif isinstance(p, list):
            if p and isinstance(p[0], list):
                for r in range(len(p)):
                    _walk(p[r], ap[r], g[r])
            elif p and isinstance(p[0], float):
                for i in range(len(p)):
                    g[i] += l2_lambda * (p[i] - ap[i])

    _walk(params, anchor_params, grads)


def _mean_parameter_drift(params: Any, anchor_params: Any) -> float:
    sq_sum = 0.0
    count = 0

    def _walk(p: Any, ap: Any) -> None:
        nonlocal sq_sum, count
        if isinstance(p, dict):
            for k in p:
                _walk(p[k], ap[k])
        elif isinstance(p, list):
            if p and isinstance(p[0], list):
                for r in range(len(p)):
                    _walk(p[r], ap[r])
            elif p and isinstance(p[0], float):
                for i in range(len(p)):
                    diff = p[i] - ap[i]
                    sq_sum += diff * diff
                    count += 1

    _walk(params, anchor_params)
    return round(math.sqrt(sq_sum / max(1, count)), 6)


def _resolve_replay_and_anchor_lines(
    conn: sqlite3.Connection,
    *,
    new_train_lines: list[str] | None,
    anchor_lines: list[str] | None,
) -> tuple[list[str], list[str], str | None]:
    """Gather clean dataset / triple records for continual learning while keeping anchor lines disjoint."""
    ds_rows = conn.execute(
        "SELECT id, records_json FROM datasets WHERE leakage_detected=0 AND total_records>=5 ORDER BY created_at DESC"
    ).fetchall()

    resolved_dataset_id: str | None = str(ds_rows[0]["id"]) if ds_rows else None

    resolved_new: list[str] = [ln.strip() for ln in (new_train_lines or []) if str(ln).strip()]
    resolved_anchor: list[str] = [ln.strip() for ln in (anchor_lines or []) if str(ln).strip()]

    if not resolved_new and ds_rows:
        splits = json.loads(ds_rows[0]["records_json"] or "{}")
        resolved_new = [str(ln).strip() for ln in (splits.get("train") or []) if str(ln).strip()]

    if not resolved_new:
        triples = conn.execute(
            """
            SELECT subject, relation, object FROM knowledge_triples
            WHERE confidence >= 0.8
              AND source NOT LIKE '%conflicting%'
              AND source NOT LIKE '%uncorroborated%'
              AND source NOT LIKE '%stale%'
            ORDER BY created_at DESC LIMIT 60
            """
        ).fetchall()
        resolved_new = [f"{r['subject']} {r['relation']} {r['object']}" for r in triples]

    if not resolved_anchor:
        # Prefer validation lines from earliest clean dataset as historical retention anchor
        for ds in reversed(ds_rows):
            splits = json.loads(ds["records_json"] or "{}")
            cand = [str(ln).strip() for ln in (splits.get("val") or []) if str(ln).strip()]
            if not cand:
                cand = [str(ln).strip() for ln in (splits.get("train") or []) if str(ln).strip()][:6]
            if cand:
                resolved_anchor.extend(cand)
                break

    if not resolved_anchor and len(resolved_new) >= 4:
        split_idx = max(2, len(resolved_new) // 3)
        resolved_anchor = resolved_new[:split_idx]
        resolved_new = resolved_new[split_idx:]

    # Deduplicate preserving order
    def _dedup(lines: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for ln in lines:
            k = _norm(ln)
            if k and k not in seen:
                seen.add(k)
                out.append(ln)
        return out

    return _dedup(resolved_new), _dedup(resolved_anchor), resolved_dataset_id


def run_continual_learning_round(
    conn: sqlite3.Connection,
    checkpoint_dir: Path,
    user_id: str,
    *,
    new_train_lines: list[str] | None = None,
    anchor_lines: list[str] | None = None,
    replay_ratio: float = 0.35,
    anchor_l2_lambda: float = 0.02,
    max_forgetting_loss_delta: float = 0.25,
    max_forgetting_acc_drop: float = 0.15,
    epochs: int = 6,
    lr: float = 0.012,
    seed: int = 42,
) -> dict[str, Any]:
    """
    Execute a Continual Learning round with Experience Replay + L2 Weight Consolidation,
    measure retention/catastrophic forgetting across rounds, and gate promotion via `experiments`.
    """
    resolved_new, resolved_anchor, dataset_id = _resolve_replay_and_anchor_lines(
        conn,
        new_train_lines=new_train_lines,
        anchor_lines=anchor_lines,
    )
    if len(resolved_new) < 2 or len(resolved_anchor) < 2:
        return {
            "ok": False,
            "error": (
                f"Continual learning requires >=2 new samples ({len(resolved_new)}) "
                f"and >=2 anchor samples ({len(resolved_anchor)})."
            ),
        }

    if dataset_id is None:
        dataset_id = "continual-curriculum"

    prev_ckpt = conn.execute(
        """
        SELECT id, version, weights_path, val_loss, eval_accuracy
        FROM checkpoints
        WHERE eval_status LIKE 'NEURAL%'
        ORDER BY version DESC
        LIMIT 1
        """
    ).fetchone()

    base_model: NativeTransformerLM | None = None
    tokenizer: NativeBPETokenizer | None = None
    parent_ckpt_id: str | None = None
    parent_ckpt_version: int | None = None

    if prev_ckpt and prev_ckpt["weights_path"]:
        wpath = Path(str(prev_ckpt["weights_path"]))
        if wpath.exists():
            base_model, tokenizer, _ = NativeTransformerLM.load_checkpoint(wpath)
            parent_ckpt_id = str(prev_ckpt["id"])
            parent_ckpt_version = int(prev_ckpt["version"])

    # If no previous neural checkpoint exists on disk, establish Round 0 baseline on anchor lines first
    if base_model is None or tokenizer is None:
        round0 = train_neural_model(
            resolved_anchor,
            resolved_anchor,
            resolved_new[:2],
            epochs=max(4, min(epochs, 6)),
            lr=lr,
            seed=seed,
        )
        if not round0.get("ok"):
            return round0
        base_model = round0["model"]
        tokenizer = round0["tokenizer"]

    anchor_params = copy.deepcopy(base_model.params)

    anchor_seqs = [tokenizer.encode(ln, add_bos=True, add_eos=True) for ln in resolved_anchor]
    new_seqs = [tokenizer.encode(ln, add_bos=True, add_eos=True) for ln in resolved_new]

    baseline_anchor_eval = base_model.evaluate_sequences(anchor_seqs)
    baseline_new_eval = base_model.evaluate_sequences(new_seqs)

    # Deterministic Experience Replay mix
    replay_count = 0
    if replay_ratio > 0.0 and anchor_seqs:
        replay_count = max(1, int(round(len(new_seqs) * min(max(replay_ratio, 0.0), 1.0))))
    rng = random.Random(seed)
    replay_pool = list(anchor_seqs)
    rng.shuffle(replay_pool)
    replay_seqs = [replay_pool[i % len(replay_pool)] for i in range(replay_count)]
    combined_train_seqs = list(new_seqs) + replay_seqs

    max_seq_len = int(base_model.config["max_seq_len"])
    m_state = base_model.zero_grads()
    v_state = base_model.zero_grads()
    grad_accum_steps = 2
    max_grad_norm = 1.0
    total_opt_steps = max(1, (len(combined_train_seqs) * epochs + grad_accum_steps - 1) // grad_accum_steps)
    opt_step = 0
    accum_grads = base_model.zero_grads()
    accum_count = 0
    history: list[dict[str, Any]] = []

    for ep in range(1, max(1, int(epochs)) + 1):
        order = list(range(len(combined_train_seqs)))
        rng.shuffle(order)
        ep_loss = 0.0
        ep_items = 0

        for idx in order:
            seq = combined_train_seqs[idx]
            if len(seq) < 2:
                continue
            inp = seq[:-1][:max_seq_len]
            tgt = seq[1 : len(inp) + 1]
            loss_val, _, accum_grads = base_model.forward_loss_and_backward(
                inp, tgt, grads=accum_grads
            )
            if math.isnan(loss_val) or math.isinf(loss_val):
                return {"ok": False, "error": "Continual learning halted: NaN/Inf loss detected"}
            ep_loss += loss_val
            ep_items += 1
            accum_count += 1

            if accum_count >= grad_accum_steps:
                opt_step += 1
                _add_l2_anchor_grads(
                    base_model.params,
                    anchor_params,
                    accum_grads,
                    anchor_l2_lambda * accum_count,
                )
                g_scale = 1.0 / accum_count
                gnorm = _grad_l2_norm(accum_grads, g_scale)
                clip_scale = min(1.0, max_grad_norm / gnorm) if gnorm > max_grad_norm and gnorm > 0 else 1.0
                prog = min(1.0, opt_step / max(1, total_opt_steps))
                cur_lr = lr * (0.15 + 0.85 * 0.5 * (1.0 + math.cos(math.pi * prog)))
                _adamw_step(
                    base_model.params,
                    accum_grads,
                    m_state,
                    v_state,
                    lr=cur_lr,
                    beta1=0.9,
                    beta2=0.98,
                    eps=1e-8,
                    weight_decay=0.01,
                    step_num=opt_step,
                    grad_scale=g_scale,
                    clip_scale=clip_scale,
                )
                accum_grads = base_model.zero_grads()
                accum_count = 0

        if accum_count > 0:
            opt_step += 1
            _add_l2_anchor_grads(
                base_model.params,
                anchor_params,
                accum_grads,
                anchor_l2_lambda * accum_count,
            )
            g_scale = 1.0 / accum_count
            gnorm = _grad_l2_norm(accum_grads, g_scale)
            clip_scale = min(1.0, max_grad_norm / gnorm) if gnorm > max_grad_norm and gnorm > 0 else 1.0
            _adamw_step(
                base_model.params,
                accum_grads,
                m_state,
                v_state,
                lr=lr * 0.2,
                beta1=0.9,
                beta2=0.98,
                eps=1e-8,
                weight_decay=0.01,
                step_num=opt_step,
                grad_scale=g_scale,
                clip_scale=clip_scale,
            )
            accum_grads = base_model.zero_grads()
            accum_count = 0

        anchor_ep = base_model.evaluate_sequences(anchor_seqs)
        new_ep = base_model.evaluate_sequences(new_seqs)
        history.append(
            {
                "epoch": ep,
                "mixed_train_loss": round(ep_loss / max(1, ep_items), 4),
                "anchor_loss": anchor_ep["loss"],
                "new_task_loss": new_ep["loss"],
            }
        )

    post_anchor_eval = base_model.evaluate_sequences(anchor_seqs)
    post_new_eval = base_model.evaluate_sequences(new_seqs)

    forgetting_loss_delta = round(float(post_anchor_eval["loss"]) - float(baseline_anchor_eval["loss"]), 4)
    forgetting_acc_drop = round(float(baseline_anchor_eval["accuracy"]) - float(post_anchor_eval["accuracy"]), 4)
    base_acc = max(0.05, float(baseline_anchor_eval["accuracy"]))
    retention_rate = round(
        max(0.0, min(1.0, 1.0 - max(0.0, forgetting_acc_drop) / base_acc - max(0.0, forgetting_loss_delta) * 0.25)),
        4,
    )
    param_drift_rms = _mean_parameter_drift(base_model.params, anchor_params)

    catastrophic_forgetting = bool(
        forgetting_loss_delta > max_forgetting_loss_delta
        or forgetting_acc_drop > max_forgetting_acc_drop
    )
    new_task_improved = bool(float(post_new_eval["loss"]) < float(baseline_new_eval["loss"]))
    improved = bool(new_task_improved and not catastrophic_forgetting)

    exp_id = str(uuid.uuid4())
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    cand_path = checkpoint_dir / f"exp_cl_{exp_id[:8]}_neural.json.gz"

    continual_metrics = {
        "mode": "continual_replay_consolidation",
        "parent_ckpt_id": parent_ckpt_id,
        "parent_ckpt_version": parent_ckpt_version,
        "new_samples": len(new_seqs),
        "replay_samples": len(replay_seqs),
        "anchor_samples": len(anchor_seqs),
        "replay_ratio": float(replay_ratio),
        "anchor_l2_lambda": float(anchor_l2_lambda),
        "baseline_anchor_loss": baseline_anchor_eval["loss"],
        "baseline_anchor_accuracy": baseline_anchor_eval["accuracy"],
        "post_anchor_loss": post_anchor_eval["loss"],
        "post_anchor_accuracy": post_anchor_eval["accuracy"],
        "baseline_new_loss": baseline_new_eval["loss"],
        "post_new_loss": post_new_eval["loss"],
        "forgetting_loss_delta": forgetting_loss_delta,
        "forgetting_accuracy_drop": forgetting_acc_drop,
        "retention_rate": retention_rate,
        "param_drift_rms": param_drift_rms,
        "catastrophic_forgetting_detected": catastrophic_forgetting,
        "new_task_improved": new_task_improved,
        "param_count": base_model.parameter_count(),
        "vocab_size": tokenizer.vocab_size,
        "history": history,
    }
    base_model.save_checkpoint(cand_path, tokenizer, metrics=continual_metrics)

    if catastrophic_forgetting:
        approval_status = "FORGETTING_FAILED"
    elif improved:
        approval_status = "PENDING_APPROVAL"
    else:
        approval_status = "REJECTED_NO_GAIN"

    hypothesis = (
        f"Continual Learning Round (Replay {len(replay_seqs)}/{len(anchor_seqs)} anchor, "
        f"L2 Consolidation λ={anchor_l2_lambda}) บน {len(new_seqs)} ตัวอย่างใหม่ "
        f"[retention={retention_rate:.2f}, forgetting_Δloss={forgetting_loss_delta:+.4f}]"
    )
    baseline_payload = {
        "parent_ckpt_id": parent_ckpt_id,
        "parent_ckpt_version": parent_ckpt_version,
        "baseline_anchor_loss": baseline_anchor_eval["loss"],
        "baseline_anchor_accuracy": baseline_anchor_eval["accuracy"],
        "baseline_new_loss": baseline_new_eval["loss"],
    }
    candidate_payload = {
        "final_train_loss": post_new_eval["loss"],
        "final_val_loss": post_anchor_eval["loss"],
        "val_perplexity": post_anchor_eval["perplexity"],
        "test_accuracy": post_new_eval["accuracy"],
        "forgetting_loss_delta": forgetting_loss_delta,
        "forgetting_accuracy_drop": forgetting_acc_drop,
        "retention_rate": retention_rate,
        "catastrophic_forgetting_detected": catastrophic_forgetting,
        "param_drift_rms": param_drift_rms,
        "param_count": base_model.parameter_count(),
        "vocab_size": tokenizer.vocab_size,
        "weights_path": str(cand_path),
    }

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
                dataset_id,
                parent_ckpt_id,
                None,
                json.dumps(baseline_payload, ensure_ascii=False),
                json.dumps(candidate_payload, ensure_ascii=False),
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
        "catastrophic_forgetting_detected": catastrophic_forgetting,
        "continual_metrics": continual_metrics,
    }
