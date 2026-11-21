#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — v9 Evaluator & 6 Principle Probes (Step 4)
=======================================================
Read-only scientific evaluation of trained v9 Arm checkpoints (arm_a/b/c/d) on
data/nagi_v9/ (`val_unseen`, `val_ood`, `test_unseen`, `test_ood`).

Implements:
  - Fail-closed Data Leakage Gate (audit_leakage_v9.run_audit) & Checkpoint EL-05 check
  - Teacher-Forced & Free-Generation (Autoregressive) evaluation
  - All Blueprint Section 8.3 & 10.3 metrics (exposure_bias_gap, unseen_entity_copy_acc,
    unseen_entity_reasoning_acc, multi_hop_acc, adaptive_override_acc,
    adaptive_retention_acc, conflict_detection_f1, plan_validity_acc,
    impossible_plan_acc, verification_acc, eos/repetition stability, p_gen split)
  - All 6 Principle Diagnostic Probes (Alpha-Renaming, Premise Permutation,
    Depth Extrapolation, Distractor Sensitivity, Override vs Conflict Minimal Pairs,
    Pointer Gate Discipline)
  - Honest Acceptance & Stop Criteria evaluation + optional 4-Arm comparison

Never fabricates metrics or marks uncompared/blocked items as PASS.
Does NOT modify v7/v8 files, checkpoints, data/nagi_v9/, apps/, or phases/.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from audit_leakage_v9 import (  # noqa: E402
    EXPECTED_CAPABILITIES,
    classify_entity_format,
    run_audit,
    tokenize_structural_text,
)
from train_nagi_v9 import (  # noqa: E402
    ARM_DESCRIPTIONS,
    BOS_ID,
    EOS_ID,
    MAX_CPU_MODEL_PARAMETERS,
    MAX_CPU_SEQUENCE_LENGTH,
    PAD_ID,
    UNK_ID,
    SlotBinding,
    atomic_write_text,
    collect_runtime_environment,
    encode_pair_slotted,
    encode_pair_standard,
    free_generate_row,
    instantiate_arm_model,
    load_jsonl,
    require_torch,
    sha256_file,
    verify_vocab_no_eval_leakage,
)

EVAL_SPLITS = ("val_unseen", "val_ood", "test_unseen", "test_ood")


def calc_repetition(toks: list[str]) -> bool:
    if len(toks) < 2:
        return False
    # Flag single-token loop (e.g. "E1 E1 E1") or adjacent duplicate non-arrow tokens
    if len(set(toks)) == 1:
        return True
    for i in range(len(toks) - 1):
        if toks[i] == toks[i + 1]:
            return True
    return False


def teacher_forced_eval_row(
    arm: str,
    model,
    row: dict[str, Any],
    stoi: dict[str, int],
    itos: dict[int, str],
    max_seq: int,
    use_slots: bool,
    torch_mod,
    F,
    device,
) -> dict[str, Any]:
    exp_toks = tokenize_structural_text(row["target"])
    model.eval()

    if arm == "arm_d" and use_slots:
        enc = encode_pair_slotted(row["input"], row["target"], stoi, max_seq, permute_slots=False)
        if enc is None:
            raise ValueError(f"Row {row.get('id')} exceeds max_seq={max_seq}")
        src_ids, trg_ids, binding = enc
    else:
        enc_std = encode_pair_standard(row["input"], row["target"], stoi, max_seq)
        if enc_std is None:
            raise ValueError(f"Row {row.get('id')} exceeds max_seq={max_seq}")
        src_ids, trg_ids = enc_std
        binding = SlotBinding({}, {})

    with torch_mod.no_grad():
        if arm == "arm_a":
            prefix = src_ids[:-1]
            tgt_body = trg_ids[1:]
            if len(prefix) + len(tgt_body) > max_seq:
                prefix = prefix[: max(1, max_seq - len(tgt_body))]
            ids = prefix + tgt_body
            labels = [-100] * len(prefix) + tgt_body
            x = torch_mod.tensor([ids[:-1]], dtype=torch_mod.long, device=device)
            y = torch_mod.tensor([labels[1:]], dtype=torch_mod.long, device=device)
            logits = model(x)
            loss = float(
                F.cross_entropy(
                    logits.reshape(-1, model.vocab_size), y.reshape(-1), ignore_index=-100
                ).item()
            )
            start_pos = len(prefix) - 1
            pred_ids = logits[0, start_pos:, :].argmax(dim=-1).tolist()
            gold_ids = tgt_body
        elif arm in ("arm_b", "arm_c"):
            src_t = torch_mod.tensor([src_ids], dtype=torch_mod.long, device=device)
            trg_t = torch_mod.tensor([trg_ids], dtype=torch_mod.long, device=device)
            probs, _ = model(src_t, trg_t, teacher_forcing_ratio=1.0)
            log_probs = torch_mod.log(probs[:, 1:, :].clamp(min=1e-12))
            gold_t = trg_t[:, 1:]
            loss = float(
                F.nll_loss(
                    log_probs.reshape(-1, model.vocab_size), gold_t.reshape(-1), ignore_index=PAD_ID
                ).item()
            )
            pred_ids = probs[0, 1:, :].argmax(dim=-1).tolist()
            gold_ids = gold_t[0].tolist()
        else:
            src_t = torch_mod.tensor([src_ids], dtype=torch_mod.long, device=device)
            trg_t = torch_mod.tensor([trg_ids], dtype=torch_mod.long, device=device)
            trg_in = trg_t[:, :-1]
            trg_out = trg_t[:, 1:]
            final_dist, _ = model(src_t, trg_in)
            log_probs = torch_mod.log(final_dist.clamp(min=1e-12))
            loss = float(
                F.nll_loss(
                    log_probs.reshape(-1, model.vocab_size), trg_out.reshape(-1), ignore_index=PAD_ID
                ).item()
            )
            pred_ids = final_dist[0].argmax(dim=-1).tolist()
            gold_ids = trg_out[0].tolist()

    tok_corr = sum(1 for p, g in zip(pred_ids, gold_ids) if p == g)
    eos_pos = pred_ids.index(EOS_ID) if EOS_ID in pred_ids else -1
    body_ids = pred_ids[:eos_pos] if eos_pos >= 0 else pred_ids
    pred_toks = []
    for pid in body_ids:
        t = itos.get(pid, "<unk>")
        if use_slots and t in binding.slot_to_surface:
            t = binding.slot_to_surface[t]
        pred_toks.append(t)

    return {
        "token_corr": tok_corr,
        "token_tot": len(gold_ids),
        "loss": loss,
        "pred_toks": pred_toks,
        "eos_pos": eos_pos,
        "exact": pred_toks == exp_toks,
        "first": bool(pred_toks and exp_toks and pred_toks[0] == exp_toks[0]),
        "premature_eos": 0 <= eos_pos < len(exp_toks),
        "rep": calc_repetition(pred_toks),
    }


def _safe_rate(hit: int, tot: int) -> float | None:
    return (hit / tot) if tot > 0 else None


def evaluate_rows(
    arm: str,
    model,
    rows: list[dict[str, Any]],
    vocab: list[str],
    stoi: dict[str, int],
    itos: dict[int, str],
    max_seq: int,
    max_gen_len: int,
    use_slots: bool,
    train_entities: set[str],
    torch_mod,
    F,
    device,
) -> dict[str, Any]:
    """Evaluate a list of rows in both Teacher-Forced and Free-Generation modes."""
    per_cap: dict[str, Any] = {}
    err_cases: dict[str, list[dict[str, Any]]] = {}
    tok_counter: Counter[str] = Counter()

    def new_acc() -> dict[str, Any]:
        return {
            "n": 0,
            "tf_exact": 0,
            "tf_first": 0,
            "tf_eos": 0,
            "tf_prem": 0,
            "tf_rep": 0,
            "tf_tok_corr": 0,
            "tf_tok_tot": 0,
            "tf_losses": [],
            "fg_exact": 0,
            "fg_first": 0,
            "fg_eos": 0,
            "fg_prem": 0,
            "fg_rep": 0,
            "fg_eos_positions": [],
            # Copy vs Reasoning breakdown (Free-Gen)
            "copy_row_hit": 0,
            "copy_row_tot": 0,
            "copy_ent_hit": 0,
            "copy_ent_tot": 0,
            "unseen_ent_hit": 0,
            "unseen_ent_tot": 0,
            "reason_row_hit": 0,
            "reason_row_tot": 0,
            "pgens_all": [],
            "pgens_copy": [],
            "pgens_reason": [],
            # Multi-hop buckets
            "hop_1_hit": 0,
            "hop_1_tot": 0,
            "hop_2_3_hit": 0,
            "hop_2_3_tot": 0,
            "hop_4p_hit": 0,
            "hop_4p_tot": 0,
            # Specialized NGI metrics
            "adaptive_override_hit": 0,
            "adaptive_override_tot": 0,
            "adaptive_retention_hit": 0,
            "adaptive_retention_tot": 0,
            "conflict_tp": 0,
            "conflict_fp": 0,
            "conflict_fn": 0,
            "conflict_exact_hit": 0,
            "conflict_exact_tot": 0,
            "plan_valid_hit": 0,
            "plan_valid_tot": 0,
            "plan_impossible_hit": 0,
            "plan_impossible_tot": 0,
            "verif_hit": 0,
            "verif_tot": 0,
            "verdict_preds": Counter(),
        }

    overall_acc = new_acc()

    def update_acc(acc: dict[str, Any], row: dict[str, Any], tf: dict[str, Any], fg_toks: list[str], fg_eos: int, fg_pgen: float | None):
        exp_toks = tokenize_structural_text(row["target"])
        cap = str(row.get("capability", ""))
        tmpl_id = str(row.get("template_id", ""))
        is_ent_target = bool(row.get("entity_target")) or any(
            classify_entity_format(t) is not None for t in exp_toks
        )
        hop = int(row.get("hop_depth", 1))

        acc["n"] += 1
        # Teacher-Forced
        acc["tf_tok_corr"] += tf["token_corr"]
        acc["tf_tok_tot"] += tf["token_tot"]
        acc["tf_losses"].append(tf["loss"])
        if tf["exact"]:
            acc["tf_exact"] += 1
        if tf["first"]:
            acc["tf_first"] += 1
        if tf["eos_pos"] >= 0:
            acc["tf_eos"] += 1
            if tf["premature_eos"]:
                acc["tf_prem"] += 1
        if tf["rep"]:
            acc["tf_rep"] += 1

        # Free-Generation
        fg_exact = fg_toks == exp_toks
        fg_first = bool(fg_toks and exp_toks and fg_toks[0] == exp_toks[0])
        fg_prem = 0 <= fg_eos < len(exp_toks)
        fg_rep = calc_repetition(fg_toks)

        if fg_exact:
            acc["fg_exact"] += 1
        if fg_first:
            acc["fg_first"] += 1
        if fg_eos >= 0:
            acc["fg_eos"] += 1
            acc["fg_eos_positions"].append(fg_eos)
            if fg_prem:
                acc["fg_prem"] += 1
        if fg_rep:
            acc["fg_rep"] += 1

        if fg_pgen is not None:
            acc["pgens_all"].append(fg_pgen)
            if is_ent_target:
                acc["pgens_copy"].append(fg_pgen)
            else:
                acc["pgens_reason"].append(fg_pgen)

        if is_ent_target:
            acc["copy_row_tot"] += 1
            if fg_exact:
                acc["copy_row_hit"] += 1
            for idx, tok in enumerate(exp_toks):
                if classify_entity_format(tok) is not None:
                    acc["copy_ent_tot"] += 1
                    matched = idx < len(fg_toks) and fg_toks[idx] == tok
                    if matched:
                        acc["copy_ent_hit"] += 1
                    if tok not in train_entities:
                        acc["unseen_ent_tot"] += 1
                        if matched:
                            acc["unseen_ent_hit"] += 1
        else:
            acc["reason_row_tot"] += 1
            if fg_exact:
                acc["reason_row_hit"] += 1

        # Multi-hop buckets
        if hop <= 1:
            acc["hop_1_tot"] += 1
            if fg_exact:
                acc["hop_1_hit"] += 1
        elif hop <= 3:
            acc["hop_2_3_tot"] += 1
            if fg_exact:
                acc["hop_2_3_hit"] += 1
        else:
            acc["hop_4p_tot"] += 1
            if fg_exact:
                acc["hop_4p_hit"] += 1

        # Capability-specific behavioral metrics
        inp_low = str(row.get("input", "")).lower()
        tgt_str = str(row.get("target", "")).strip()
        pred_str = " ".join(fg_toks).strip()

        if cap == "adaptive_learning":
            # Distinguish override vs retention vs chained/retract cleanly via template/prompt cues
            if tmpl_id == "AL_TR_01" or (
                any(k in inp_low for k in ("update:", "patch [", "delta (")) and tgt_str != "unknown"
            ):
                # Check if queried entity is the updated entity (appears after update/patch/delta)
                sep_key = next((k for k in ("update:", "patch [", "delta (") if k in inp_low), None)
                if sep_key:
                    after_upd = inp_low.split(sep_key, 1)[1]
                    q_part = ""
                    for q_cue in ("query ", "read ", "state_of "):
                        if q_cue in after_upd:
                            q_part = after_upd.split(q_cue, 1)[1]
                            upd_body = after_upd.split(q_cue, 1)[0]
                            q_ent = q_part.strip().split()[0] if q_part.strip() else ""
                            if q_ent and q_ent in upd_body:
                                acc["adaptive_override_tot"] += 1
                                if fg_exact:
                                    acc["adaptive_override_hit"] += 1
                            elif q_ent:
                                acc["adaptive_retention_tot"] += 1
                                if fg_exact:
                                    acc["adaptive_retention_hit"] += 1
                            break

        if cap in ("knowledge_integration", "relational_reasoning"):
            gold_conflict = tgt_str == "conflict"
            pred_conflict = pred_str == "conflict"
            if gold_conflict and pred_conflict:
                acc["conflict_tp"] += 1
            elif pred_conflict and not gold_conflict:
                acc["conflict_fp"] += 1
            elif gold_conflict and not pred_conflict:
                acc["conflict_fn"] += 1
            if gold_conflict:
                acc["conflict_exact_tot"] += 1
                if fg_exact:
                    acc["conflict_exact_hit"] += 1

        if cap == "planning_decomposition" or (
            cap == "generalization" and any(k in inp_low for k in ("plan ?", "compose_plan", "derive_plan"))
        ):
            if tgt_str == "impossible":
                acc["plan_impossible_tot"] += 1
                if fg_exact:
                    acc["plan_impossible_hit"] += 1
            else:
                acc["plan_valid_tot"] += 1
                if fg_exact:
                    acc["plan_valid_hit"] += 1

        if cap == "verification":
            acc["verif_tot"] += 1
            if fg_exact:
                acc["verif_hit"] += 1

        if cap in ("verification", "knowledge_integration") and not is_ent_target:
            acc["verdict_preds"][pred_str or "<empty>"] += 1

    def finalize(acc: dict[str, Any]) -> dict[str, Any]:
        n = max(1, acc["n"])
        tf_exact = acc["tf_exact"] / n
        fg_exact = acc["fg_exact"] / n
        tp, fp, fn = acc["conflict_tp"], acc["conflict_fp"], acc["conflict_fn"]
        conflict_f1 = (2 * tp / (2 * tp + fp + fn)) if (2 * tp + fp + fn) > 0 else None

        majority_pred_share = None
        if acc["verdict_preds"]:
            top_cnt = acc["verdict_preds"].most_common(1)[0][1]
            tot_vp = sum(acc["verdict_preds"].values())
            majority_pred_share = top_cnt / max(1, tot_vp)

        return {
            "count": acc["n"],
            "teacher_forced": {
                "exact_match": tf_exact,
                "token_acc": _safe_rate(acc["tf_tok_corr"], acc["tf_tok_tot"]),
                "loss_avg": (sum(acc["tf_losses"]) / len(acc["tf_losses"])) if acc["tf_losses"] else None,
                "first_token_acc": acc["tf_first"] / n,
                "eos_hit_rate": acc["tf_eos"] / n,
                "premature_eos_rate": acc["tf_prem"] / n,
                "repetition_rate": acc["tf_rep"] / n,
            },
            "free_generation": {
                "exact_match": fg_exact,
                "correct": acc["fg_exact"],
                "first_token_acc": acc["fg_first"] / n,
                "eos_hit_rate": acc["fg_eos"] / n,
                "avg_eos_position": (sum(acc["fg_eos_positions"]) / len(acc["fg_eos_positions"])) if acc["fg_eos_positions"] else None,
                "premature_eos_rate": acc["fg_prem"] / n,
                "repetition_rate": acc["fg_rep"] / n,
                "entity_copy_acc": _safe_rate(acc["copy_ent_hit"], acc["copy_ent_tot"]),
                "entity_count": acc["copy_ent_tot"],
                "unseen_entity_copy_acc": _safe_rate(acc["unseen_ent_hit"], acc["unseen_ent_tot"]),
                "unseen_entity_count": acc["unseen_ent_tot"],
                "unseen_entity_reasoning_acc": _safe_rate(acc["reason_row_hit"], acc["reason_row_tot"]),
                "unseen_reasoning_count": acc["reason_row_tot"],
                "copy_row_exact_acc": _safe_rate(acc["copy_row_hit"], acc["copy_row_tot"]),
                "mean_p_gen": (sum(acc["pgens_all"]) / len(acc["pgens_all"])) if acc["pgens_all"] else None,
                "copy_tasks_mean_p_gen": (sum(acc["pgens_copy"]) / len(acc["pgens_copy"])) if acc["pgens_copy"] else None,
                "reasoning_tasks_mean_p_gen": (sum(acc["pgens_reason"]) / len(acc["pgens_reason"])) if acc["pgens_reason"] else None,
                "multi_hop_acc": {
                    "1_hop": _safe_rate(acc["hop_1_hit"], acc["hop_1_tot"]),
                    "2_to_3_hop": _safe_rate(acc["hop_2_3_hit"], acc["hop_2_3_tot"]),
                    "4_plus_hop": _safe_rate(acc["hop_4p_hit"], acc["hop_4p_tot"]),
                    "counts": {
                        "1_hop": acc["hop_1_tot"],
                        "2_to_3_hop": acc["hop_2_3_tot"],
                        "4_plus_hop": acc["hop_4p_tot"],
                    },
                },
                "adaptive_override_acc": _safe_rate(acc["adaptive_override_hit"], acc["adaptive_override_tot"]),
                "adaptive_retention_acc": _safe_rate(acc["adaptive_retention_hit"], acc["adaptive_retention_tot"]),
                "conflict_detection_f1": conflict_f1,
                "contradiction_acc": _safe_rate(acc["conflict_exact_hit"], acc["conflict_exact_tot"]),
                "plan_validity_acc": _safe_rate(acc["plan_valid_hit"], acc["plan_valid_tot"]),
                "impossible_plan_acc": _safe_rate(acc["plan_impossible_hit"], acc["plan_impossible_tot"]),
                "verification_acc": _safe_rate(acc["verif_hit"], acc["verif_tot"]),
                "verdict_majority_collapse_share": majority_pred_share,
            },
            "exposure_bias_gap": tf_exact - fg_exact,
        }

    caps_present = [c for c in EXPECTED_CAPABILITIES if any(r.get("capability") == c for r in rows)]
    for cap in caps_present:
        cap_rows = [r for r in rows if r.get("capability") == cap]
        c_acc = new_acc()
        errs: list[dict[str, Any]] = []
        for r in cap_rows:
            tf = teacher_forced_eval_row(arm, model, r, stoi, itos, max_seq, use_slots, torch_mod, F, device)
            fg_toks, fg_eos, fg_pgen = free_generate_row(
                arm, model, r["input"], vocab, stoi, itos, max_seq, max_gen_len, use_slots, torch_mod, device
            )
            tok_counter.update(fg_toks)
            update_acc(c_acc, r, tf, fg_toks, fg_eos, fg_pgen)
            update_acc(overall_acc, r, tf, fg_toks, fg_eos, fg_pgen)
            exp_toks = tokenize_structural_text(r["target"])
            if fg_toks != exp_toks and len(errs) < 5:
                errs.append(
                    {
                        "id": r.get("id"),
                        "template_id": r.get("template_id"),
                        "hop_depth": r.get("hop_depth"),
                        "input": r["input"],
                        "expected": r["target"],
                        "predicted": " ".join(fg_toks),
                        "teacher_forced_predicted": " ".join(tf["pred_toks"]),
                        "eos_pos": fg_eos,
                        "mean_p_gen": round(fg_pgen, 4) if fg_pgen is not None else None,
                    }
                )
        per_cap[cap] = finalize(c_acc)
        err_cases[cap] = errs

    return {
        "overall": finalize(overall_acc),
        "per_capability": per_cap,
        "errors": err_cases,
        "top_predicted_tokens": tok_counter.most_common(12),
    }


def _extract_entities_ordered(text: str) -> list[str]:
    seen: list[str] = []
    seen_set: set[str] = set()
    for tok in tokenize_structural_text(text):
        if classify_entity_format(tok) is not None and tok not in seen_set:
            seen_set.add(tok)
            seen.append(tok)
    return seen


def _alpha_rename_text(text: str, mapping: dict[str, str]) -> str:
    # Preserve exact formatting by replacing whitespace-separated tokens cleanly
    return " ".join(mapping.get(tok, tok) for tok in text.split())


def _permute_premises_safe(row: dict[str, Any], rng: random.Random) -> str | None:
    """
    Deterministically shuffle premise clauses on order-independent templates
    while keeping query/target semantics 100% invariant.
    """
    inp = str(row.get("input", ""))
    cap = str(row.get("capability", ""))
    tmpl = str(row.get("template_id", ""))

    if cap == "relational_reasoning" and tmpl.startswith("RR_TR_") and " | " in inp:
        left, right = inp.split(" | ", 1)
        if ": " in left:
            prefix, body = left.split(": ", 1)
            clauses = [c.strip() for c in body.split(" , ") if c.strip()]
            if len(clauses) >= 2:
                shuffled = list(clauses)
                rng.shuffle(shuffled)
                if shuffled == clauses:
                    shuffled = list(reversed(clauses))
                return f"{prefix}: {' , '.join(shuffled)} | {right}"

    if cap == "knowledge_acquisition" and tmpl.startswith("KA_TR_") and " | " in inp:
        left, right = inp.split(" | ", 1)
        if ": " in left:
            prefix, body = left.split(": ", 1)
            clauses = [c.strip() for c in body.split(" ; ") if c.strip()]
            if len(clauses) >= 2:
                shuffled = list(clauses)
                rng.shuffle(shuffled)
                if shuffled == clauses:
                    shuffled = list(reversed(clauses))
                return f"{prefix}: {' ; '.join(shuffled)} | {right}"

    if cap == "planning_decomposition" and tmpl.startswith("PD_TR_") and inp.count(" | ") == 2:
        p1, p2, p3 = inp.split(" | ")
        if ": " in p2 and " ; missing:" not in p2:
            prefix, body = p2.split(": ", 1)
            clauses = [c.strip() for c in body.split(" , ") if c.strip()]
            if len(clauses) >= 2:
                shuffled = list(clauses)
                rng.shuffle(shuffled)
                if shuffled == clauses:
                    shuffled = list(reversed(clauses))
                return f"{p1} | {prefix}: {' , '.join(shuffled)} | {p3}"

    return None


def run_principle_probes(
    arm: str,
    model,
    splits_data: dict[str, list[dict[str, Any]]],
    splits_results: dict[str, dict[str, Any]],
    vocab: list[str],
    stoi: dict[str, int],
    itos: dict[int, str],
    max_seq: int,
    max_gen_len: int,
    use_slots: bool,
    train_entities: set[str],
    torch_mod,
    device,
) -> dict[str, Any]:
    """Run all 6 Principle Diagnostic Probes from Blueprint Section 4.2 / 10.3."""
    probes: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Probe 1: Alpha-Renaming Invariance (3 fresh random unseen renamings)
    # ------------------------------------------------------------------
    test_unseen = splits_data["test_unseen"]
    probe1_sample: list[dict[str, Any]] = []
    for cap in EXPECTED_CAPABILITIES:
        probe1_sample.extend([r for r in test_unseen if r.get("capability") == cap][:5])

    fresh_pool = [f"TE_E{i:03d}" for i in range(900, 990) if f"TE_E{i:03d}" not in train_entities and f"TE_E{i:03d}" not in stoi]
    rng1 = random.Random(9001)
    variant_accs: list[float] = []
    orig_hits = 0
    consistent_all = 0
    n_p1 = max(1, len(probe1_sample))

    per_item_preds: list[list[bool]] = []
    for r in probe1_sample:
        pred0, _, _ = free_generate_row(
            arm, model, r["input"], vocab, stoi, itos, max_seq, max_gen_len, use_slots, torch_mod, device
        )
        ok0 = pred0 == tokenize_structural_text(r["target"])
        if ok0:
            orig_hits += 1
        per_item_preds.append([ok0])

    variant_accs.append(orig_hits / n_p1)
    for v_idx in range(3):
        v_hits = 0
        for item_i, r in enumerate(probe1_sample):
            ents = _extract_entities_ordered(f"{r['input']} {r['target']}")
            chosen = rng1.sample(fresh_pool, k=len(ents))
            mapping = dict(zip(ents, chosen))
            renamed_inp = _alpha_rename_text(r["input"], mapping)
            renamed_tgt = _alpha_rename_text(r["target"], mapping)
            pred_v, _, _ = free_generate_row(
                arm, model, renamed_inp, vocab, stoi, itos, max_seq, max_gen_len, use_slots, torch_mod, device
            )
            ok_v = pred_v == tokenize_structural_text(renamed_tgt)
            if ok_v:
                v_hits += 1
            per_item_preds[item_i].append(ok_v)
        variant_accs.append(v_hits / n_p1)

    for flags in per_item_preds:
        if all(flags) or not any(flags):
            consistent_all += 1

    p1_diff_pp = (max(variant_accs) - min(variant_accs)) * 100.0
    probes["probe_1_alpha_renaming_invariance"] = {
        "description": "Accuracy variance across original + 3 random unseen entity renamings",
        "sample_size": len(probe1_sample),
        "accuracies": [round(a, 4) for a in variant_accs],
        "max_diff_pp": round(p1_diff_pp, 2),
        "behavioral_consistency_rate": round(consistent_all / n_p1, 4),
        "threshold": "< 2.0 pp",
        "passed": p1_diff_pp < 2.0,
    }

    # ------------------------------------------------------------------
    # Probe 2: Premise Permutation Invariance
    # ------------------------------------------------------------------
    rng2 = random.Random(9002)
    perm_cases: list[tuple[dict[str, Any], str]] = []
    for r in splits_data["val_unseen"] + splits_data["test_unseen"]:
        permuted = _permute_premises_safe(r, rng2)
        if permuted is not None:
            perm_cases.append((r, permuted))
    perm_cases = perm_cases[:60]

    orig_p2_hits = 0
    perm_p2_hits = 0
    for r, p_inp in perm_cases:
        exp_toks = tokenize_structural_text(r["target"])
        p_orig, _, _ = free_generate_row(
            arm, model, r["input"], vocab, stoi, itos, max_seq, max_gen_len, use_slots, torch_mod, device
        )
        p_shuf, _, _ = free_generate_row(
            arm, model, p_inp, vocab, stoi, itos, max_seq, max_gen_len, use_slots, torch_mod, device
        )
        if p_orig == exp_toks:
            orig_p2_hits += 1
        if p_shuf == exp_toks:
            perm_p2_hits += 1

    n_p2 = max(1, len(perm_cases))
    acc_p2_orig = orig_p2_hits / n_p2
    acc_p2_perm = perm_p2_hits / n_p2
    p2_drop_pp = (acc_p2_orig - acc_p2_perm) * 100.0
    probes["probe_2_premise_permutation_invariance"] = {
        "description": "Accuracy drop when premise clauses are shuffled",
        "sample_size": len(perm_cases),
        "acc_canonical": round(acc_p2_orig, 4),
        "acc_shuffled": round(acc_p2_perm, 4),
        "drop_pp": round(p2_drop_pp, 2),
        "threshold": "< 5.0 pp",
        "passed": len(perm_cases) > 0 and p2_drop_pp < 5.0,
    }

    # ------------------------------------------------------------------
    # Probe 3: Depth Extrapolation Gap (2-3 hop vs 4-5 hop)
    # ------------------------------------------------------------------
    tu_hops = splits_results["test_unseen"]["overall"]["free_generation"]["multi_hop_acc"]
    to_hops = splits_results["test_ood"]["overall"]["free_generation"]["multi_hop_acc"]
    acc_2_3 = tu_hops.get("2_to_3_hop")
    acc_4_5 = to_hops.get("4_plus_hop")
    depth_gap_pp = (
        round((acc_2_3 - acc_4_5) * 100.0, 2)
        if (acc_2_3 is not None and acc_4_5 is not None)
        else None
    )
    probes["probe_3_depth_extrapolation_gap"] = {
        "description": "2-3 hop (test_unseen) vs 4-5 hop (test_ood)",
        "acc_2_3_hop": acc_2_3,
        "acc_4_5_hop": acc_4_5,
        "depth_gap_pp": depth_gap_pp,
        "threshold": "4+ hop >= 0.65",
        "passed": acc_4_5 is not None and acc_4_5 >= 0.65,
    }

    # ------------------------------------------------------------------
    # Probe 4: Distractor Sensitivity (0 vs 3-5 distractor facts)
    # ------------------------------------------------------------------
    p4_pool = [f"TE_E{i:03d}" for i in range(800, 890) if f"TE_E{i:03d}" not in train_entities and f"TE_E{i:03d}" not in stoi]
    rng4 = random.Random(9004)
    p4_pairs: list[tuple[str, str, str]] = []
    for i in range(24):
        ents = rng4.sample(p4_pool, k=10)
        mode = i % 3
        if mode == 0:
            # Knowledge acquisition: 0 distractors vs 4 distractors
            clean_inp = f"facts: {ents[0]} -> {ents[1]} | lookup {ents[0]} ?"
            hard_clauses = [
                f"{ents[0]} -> {ents[1]}",
                f"{ents[2]} -> {ents[3]}",
                f"{ents[4]} -> {ents[5]}",
                f"{ents[6]} -> {ents[7]}",
                f"{ents[8]} -> {ents[9]}",
            ]
            rng4.shuffle(hard_clauses)
            hard_inp = f"facts: {' ; '.join(hard_clauses)} | lookup {ents[0]} ?"
            tgt = ents[1]
        elif mode == 1:
            # Relational reasoning 2-hop: 0 distractors vs 3 distractors
            clean_inp = f"rel: {ents[0]} > {ents[1]} , {ents[1]} > {ents[2]} | query {ents[0]} ? {ents[2]}"
            hard_clauses = [
                f"{ents[0]} > {ents[1]}",
                f"{ents[1]} > {ents[2]}",
                f"{ents[3]} > {ents[4]}",
                f"{ents[5]} > {ents[6]}",
                f"{ents[7]} > {ents[8]}",
            ]
            rng4.shuffle(hard_clauses)
            hard_inp = f"rel: {' , '.join(hard_clauses)} | query {ents[0]} ? {ents[2]}"
            tgt = ">"
        else:
            # Native representation pair_list: 1 pair vs 4 pairs
            clean_inp = f"pair_list: {ents[0]} : {ents[1]} | pair_right {ents[0]} ?"
            hard_clauses = [
                f"{ents[0]} : {ents[1]}",
                f"{ents[2]} : {ents[3]}",
                f"{ents[4]} : {ents[5]}",
                f"{ents[6]} : {ents[7]}",
            ]
            rng4.shuffle(hard_clauses)
            hard_inp = f"pair_list: {' ; '.join(hard_clauses)} | pair_right {ents[0]} ?"
            tgt = ents[1]
        p4_pairs.append((clean_inp, hard_inp, tgt))

    clean_hits = 0
    hard_hits = 0
    for c_inp, h_inp, tgt in p4_pairs:
        exp_t = tokenize_structural_text(tgt)
        pc, _, _ = free_generate_row(arm, model, c_inp, vocab, stoi, itos, max_seq, max_gen_len, use_slots, torch_mod, device)
        ph, _, _ = free_generate_row(arm, model, h_inp, vocab, stoi, itos, max_seq, max_gen_len, use_slots, torch_mod, device)
        if pc == exp_t:
            clean_hits += 1
        if ph == exp_t:
            hard_hits += 1

    acc_clean = clean_hits / len(p4_pairs)
    acc_hard = hard_hits / len(p4_pairs)
    p4_drop_pp = (acc_clean - acc_hard) * 100.0
    probes["probe_4_distractor_sensitivity"] = {
        "description": "Matched unseen pairs with 0 distractors vs 3-4 distractors",
        "pair_count": len(p4_pairs),
        "acc_zero_distractor": round(acc_clean, 4),
        "acc_with_distractors": round(acc_hard, 4),
        "drop_pp": round(p4_drop_pp, 2),
        "threshold": "< 10.0 pp",
        "passed": p4_drop_pp < 10.0,
    }

    # ------------------------------------------------------------------
    # Probe 5: Override vs Conflict Minimal Pairs
    # ------------------------------------------------------------------
    rng5 = random.Random(9005)
    ov_hits = 0
    cf_hits = 0
    both_ok = 0
    collapse_cnt = 0
    n_p5 = 24
    for _ in range(n_p5):
        a, b, c, d, e, f, g = rng5.sample(p4_pool, k=7)
        ov_inp = f"fact: {a} -> {b} ; {c} -> {d} | obs: {e} -> {f} | update: {a} -> {g} | integrate {a} ?"
        cf_inp = f"fact: {a} -> {b} ; {c} -> {d} | obs: {a} -> {g} ; {e} -> {f} | integrate {a} ?"
        p_ov, _, _ = free_generate_row(arm, model, ov_inp, vocab, stoi, itos, max_seq, max_gen_len, use_slots, torch_mod, device)
        p_cf, _, _ = free_generate_row(arm, model, cf_inp, vocab, stoi, itos, max_seq, max_gen_len, use_slots, torch_mod, device)
        ok_ov = p_ov == [g]
        ok_cf = p_cf == ["conflict"]
        if ok_ov:
            ov_hits += 1
        if ok_cf:
            cf_hits += 1
        if ok_ov and ok_cf:
            both_ok += 1
        if p_ov == p_cf:
            collapse_cnt += 1

    probes["probe_5_override_vs_conflict_minimal_pairs"] = {
        "description": "Minimal pairs differing only in update: (override) vs obs: (conflict)",
        "pair_count": n_p5,
        "override_acc": round(ov_hits / n_p5, 4),
        "conflict_acc": round(cf_hits / n_p5, 4),
        "both_correct_rate": round(both_ok / n_p5, 4),
        "identical_output_collapse_rate": round(collapse_cnt / n_p5, 4),
        "passed": (ov_hits / n_p5) >= 0.75 and (cf_hits / n_p5) >= 0.75 and (collapse_cnt / n_p5) <= 0.15,
    }

    # ------------------------------------------------------------------
    # Probe 6: Pointer Gate Discipline (mean_p_gen Copy vs Reasoning)
    # ------------------------------------------------------------------
    copy_pgens: list[float] = []
    reason_pgens: list[float] = []
    for sp in ("test_unseen", "test_ood"):
        fg = splits_results[sp]["overall"]["free_generation"]
        if fg["copy_tasks_mean_p_gen"] is not None:
            copy_pgens.append(fg["copy_tasks_mean_p_gen"])
        if fg["reasoning_tasks_mean_p_gen"] is not None:
            reason_pgens.append(fg["reasoning_tasks_mean_p_gen"])

    if copy_pgens and reason_pgens:
        copy_pg = sum(copy_pgens) / len(copy_pgens)
        reason_pg = sum(reason_pgens) / len(reason_pgens)
        p6_pass = copy_pg <= 0.45 and reason_pg >= 0.60
        probes["probe_6_pointer_gate_discipline"] = {
            "description": "Copy-intensive mean_p_gen (<=0.45) vs Reasoning/Verdict mean_p_gen (>=0.60)",
            "copy_tasks_mean_p_gen": round(copy_pg, 4),
            "reasoning_tasks_mean_p_gen": round(reason_pg, 4),
            "separation": round(reason_pg - copy_pg, 4),
            "thresholds": {"copy_max": 0.45, "reasoning_min": 0.60},
            "passed": p6_pass,
        }
    else:
        probes["probe_6_pointer_gate_discipline"] = {
            "description": "Pointer gate discipline (not applicable when architecture lacks pointer gate)",
            "copy_tasks_mean_p_gen": None,
            "reasoning_tasks_mean_p_gen": None,
            "status": "NOT_APPLICABLE",
            "passed": None,
        }

    return probes


def assess_acceptance_and_stop_criteria(
    arm: str,
    ckpt: dict[str, Any],
    splits_results: dict[str, dict[str, Any]],
    probes: dict[str, Any],
    baseline_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    tu_fg = splits_results["test_unseen"]["overall"]["free_generation"]
    to_fg = splits_results["test_ood"]["overall"]["free_generation"]
    tu_gap = splits_results["test_unseen"]["overall"]["exposure_bias_gap"]
    to_gap = splits_results["test_ood"]["overall"]["exposure_bias_gap"]

    # Combined test aggregates
    tu_n = splits_results["test_unseen"]["overall"]["count"]
    to_n = splits_results["test_ood"]["overall"]["count"]

    def _wavg(k: str) -> float | None:
        v1, v2 = tu_fg.get(k), to_fg.get(k)
        if v1 is None and v2 is None:
            return None
        if v1 is None:
            return v2
        if v2 is None:
            return v1
        return (v1 * tu_n + v2 * to_n) / max(1, tu_n + to_n)

    unseen_copy = _wavg("unseen_entity_copy_acc")
    unseen_reason = _wavg("unseen_entity_reasoning_acc")
    eos_rate = _wavg("eos_hit_rate")
    prem_rate = _wavg("premature_eos_rate")
    rep_rate = _wavg("repetition_rate")
    max_gap = max(tu_gap, to_gap)

    adaptive_ov = _wavg("adaptive_override_acc")
    adaptive_ret = _wavg("adaptive_retention_acc")
    conflict_f1 = _wavg("conflict_detection_f1")
    plan_val = _wavg("plan_validity_acc")
    plan_imp = _wavg("impossible_plan_acc")
    verif_acc = _wavg("verification_acc")
    hop_2_3 = tu_fg["multi_hop_acc"].get("2_to_3_hop")
    hop_4p = to_fg["multi_hop_acc"].get("4_plus_hop")

    p6 = probes["probe_6_pointer_gate_discipline"]

    criteria = {
        "unseen_entity_copy_ge_0.85": {
            "value": unseen_copy,
            "threshold": ">= 0.85 (not N/A)",
            "status": "PASS" if (unseen_copy is not None and unseen_copy >= 0.85) else "FAIL",
        },
        "unseen_entity_reasoning_ge_0.75": {
            "value": unseen_reason,
            "threshold": ">= 0.75",
            "status": "PASS" if (unseen_reason is not None and unseen_reason >= 0.75) else "FAIL",
        },
        "multi_hop_2_3_ge_0.80": {
            "value": hop_2_3,
            "threshold": ">= 0.80",
            "status": "PASS" if (hop_2_3 is not None and hop_2_3 >= 0.80) else "FAIL",
        },
        "multi_hop_4plus_ge_0.65": {
            "value": hop_4p,
            "threshold": ">= 0.65",
            "status": "PASS" if (hop_4p is not None and hop_4p >= 0.65) else "FAIL",
        },
        "adaptive_override_ge_0.75": {
            "value": adaptive_ov,
            "threshold": ">= 0.75",
            "status": "PASS" if (adaptive_ov is not None and adaptive_ov >= 0.75) else "FAIL",
        },
        "adaptive_retention_ge_0.85": {
            "value": adaptive_ret,
            "threshold": ">= 0.85",
            "status": "PASS" if (adaptive_ret is not None and adaptive_ret >= 0.85) else "FAIL",
        },
        "conflict_detection_f1_ge_0.80": {
            "value": conflict_f1,
            "threshold": ">= 0.80",
            "status": "PASS" if (conflict_f1 is not None and conflict_f1 >= 0.80) else "FAIL",
        },
        "planning_and_verification_ge_0.75": {
            "value": {"plan_validity": plan_val, "impossible_plan": plan_imp, "verification": verif_acc},
            "threshold": "each >= 0.75",
            "status": (
                "PASS"
                if all(x is not None and x >= 0.75 for x in (plan_val, plan_imp, verif_acc))
                else "FAIL"
            ),
        },
        "exposure_bias_gap_le_0.10": {
            "value": max_gap,
            "threshold": "<= 0.10",
            "status": "PASS" if max_gap <= 0.10 else "FAIL",
        },
        "generation_stability": {
            "value": {"eos_hit_rate": eos_rate, "premature_eos_rate": prem_rate, "repetition_rate": rep_rate},
            "threshold": "eos>=0.95, prem<=0.02, rep<=0.05",
            "status": (
                "PASS"
                if (
                    eos_rate is not None
                    and eos_rate >= 0.95
                    and prem_rate is not None
                    and prem_rate <= 0.02
                    and rep_rate is not None
                    and rep_rate <= 0.05
                )
                else "FAIL"
            ),
        },
        "pointer_gate_discipline": {
            "value": {
                "copy": p6.get("copy_tasks_mean_p_gen"),
                "reasoning": p6.get("reasoning_tasks_mean_p_gen"),
            },
            "threshold": "copy<=0.45, reasoning>=0.60",
            "status": (
                "NOT_APPLICABLE"
                if p6.get("passed") is None
                else ("PASS" if p6["passed"] else "FAIL")
            ),
        },
        "compute_cap_under_5m": {
            "value": ckpt.get("params"),
            "threshold": f"<= {MAX_CPU_MODEL_PARAMETERS}",
            "status": "PASS" if (ckpt.get("params") or 0) <= MAX_CPU_MODEL_PARAMETERS else "FAIL",
        },
    }

    # Cross-arm comparison criterion if baseline reports were provided
    if baseline_reports:
        base_ood = [
            r["splits"]["test_ood"]["overall"]["free_generation"]["exact_match"]
            for r in baseline_reports
            if "splits" in r and "test_ood" in r["splits"]
        ]
        max_base_ood = max(base_ood) if base_ood else None
        my_ood = to_fg["exact_match"]
        delta_ood = (my_ood - max_base_ood) if max_base_ood is not None else None
        criteria["beats_baselines_ood_by_5pp"] = {
            "value": {"arm_test_ood": my_ood, "max_baseline_test_ood": max_base_ood, "delta": delta_ood},
            "threshold": ">= +0.05 vs max(baselines)",
            "status": "PASS" if (delta_ood is not None and delta_ood >= 0.05) else "FAIL",
        }
    else:
        criteria["beats_baselines_ood_by_5pp"] = {
            "value": None,
            "threshold": ">= +0.05 vs max(Arm A, B, C)",
            "status": "PENDING_COMPARISON",
        }

    # Stop / Abort checks
    stop_triggers: list[str] = []
    if unseen_copy is None:
        stop_triggers.append("unseen_entity_copy_acc is N/A")
    if rep_rate is not None and rep_rate > 0.10:
        stop_triggers.append(f"autoregressive_repetition_collapse ({rep_rate:.4f} > 0.10)")
    if eos_rate is not None and eos_rate < 0.85:
        stop_triggers.append(f"eos_hit_rate_collapse ({eos_rate:.4f} < 0.85)")
    reason_pg = p6.get("reasoning_tasks_mean_p_gen")
    if reason_pg is not None and reason_pg < 0.15:
        stop_triggers.append(f"shallow_copy_collapse_on_reasoning (mean_p_gen={reason_pg:.4f} < 0.15)")
    maj_tu = tu_fg.get("verdict_majority_collapse_share")
    if maj_tu is not None and maj_tu > 0.80:
        stop_triggers.append(f"majority_class_collapse_test_unseen ({maj_tu:.4f} > 0.80)")

    return {
        "criteria": criteria,
        "stop_criteria_triggered": stop_triggers,
    }


def format_markdown_report(report: dict[str, Any]) -> str:
    ckpt = report["checkpoint"]
    lines = [
        f"# ZYRQUEN Ω∞ — v9 Evaluation Report ({ckpt['arm']})\n\n",
        f"- **Description:** {ckpt['description']}\n",
        f"- **Checkpoint:** `{ckpt['path']}` (`sha256={ckpt['sha256'][:16]}...`, step=`{ckpt.get('step')}`, best_step=`{ckpt.get('best_step')}`)\n",
        f"- **Params:** `{ckpt['params']}` | **Train Vocab Size:** `{ckpt['vocab_size']}` | **Ephemeral Slots:** `{ckpt['use_slots']}` | **EL-05 Leakage:** `0`\n\n",
        "## 1. Split Overview (Teacher-Forced vs Free-Generation)\n\n",
        "| Split | N | TF Exact | FG Exact | Exp Gap | Unseen Copy | Unseen Reason | 2-3 Hop | 4+ Hop | EOS Hit | Rep Rate | Copy p_gen | Reason p_gen |\n",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n",
    ]

    def _f(val) -> str:
        return "N/A" if val is None else f"{val:.4f}"

    for sp in EVAL_SPLITS:
        ov = report["splits"][sp]["overall"]
        tf = ov["teacher_forced"]
        fg = ov["free_generation"]
        mh = fg["multi_hop_acc"]
        lines.append(
            f"| {sp} | {ov['count']} | {_f(tf['exact_match'])} | {_f(fg['exact_match'])} | {_f(ov['exposure_bias_gap'])} | "
            f"{_f(fg['unseen_entity_copy_acc'])} | {_f(fg['unseen_entity_reasoning_acc'])} | "
            f"{_f(mh['2_to_3_hop'])} | {_f(mh['4_plus_hop'])} | {_f(fg['eos_hit_rate'])} | "
            f"{_f(fg['repetition_rate'])} | {_f(fg['copy_tasks_mean_p_gen'])} | {_f(fg['reasoning_tasks_mean_p_gen'])} |\n"
        )

    for sp in ("test_unseen", "test_ood"):
        lines.append(f"\n## 2. Per-Capability Breakdown — `{sp}`\n\n")
        lines.append(
            "| Capability | N | TF Exact | FG Exact | Exp Gap | Unseen Copy | Unseen Reason | EOS Hit | Rep Rate |\n"
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|\n"
        )
        for cap, entry in report["splits"][sp]["per_capability"].items():
            tf = entry["teacher_forced"]
            fg = entry["free_generation"]
            lines.append(
                f"| {cap} | {entry['count']} | {_f(tf['exact_match'])} | {_f(fg['exact_match'])} | "
                f"{_f(entry['exposure_bias_gap'])} | {_f(fg['unseen_entity_copy_acc'])} | "
                f"{_f(fg['unseen_entity_reasoning_acc'])} | {_f(fg['eos_hit_rate'])} | {_f(fg['repetition_rate'])} |\n"
            )

    lines.append("\n## 3. 6 Principle Diagnostic Probes\n\n")
    for pname, pinfo in report["principle_probes"].items():
        status = "N/A" if pinfo.get("passed") is None else ("PASS" if pinfo["passed"] else "FAIL")
        lines.append(f"- **`{pname}`** [{status}]: `{json.dumps(pinfo, ensure_ascii=False)}`\n")

    lines.append("\n## 4. Acceptance & Stop Criteria Assessment\n\n")
    for cname, cinfo in report["acceptance_assessment"]["criteria"].items():
        lines.append(f"- **{cname}**: `{cinfo['status']}` (value=`{cinfo['value']}`, threshold=`{cinfo['threshold']}`)\n")
    stops = report["acceptance_assessment"]["stop_criteria_triggered"]
    lines.append(f"- **Stop Criteria Triggered:** `{stops if stops else 'NONE'}`\n")

    if report.get("novel_structure_evaluation"):
        ns = report["novel_structure_evaluation"]
        lines.append("\n## 5. Novel Structure & OOD Generalization Summary\n\n")
        lines.append(
            f"- **Zero Template/Skeleton Leakage Confirmed:** `TL-01={ns['tl01_zero_template_leakage']}`, "
            f"`SL-01={ns['sl01_zero_skeleton_leakage']}`\n"
            f"- **Val-Unseen vs Val-OOD FG Exact:** `{_f(ns['val_unseen_fg_exact'])}` vs `{_f(ns['val_ood_fg_exact'])}` "
            f"(OOD gap=`{_f(ns['val_ood_structure_gap'])}`)\n"
            f"- **Test-Unseen vs Test-OOD FG Exact:** `{_f(ns['test_unseen_fg_exact'])}` vs `{_f(ns['test_ood_fg_exact'])}` "
            f"(OOD gap=`{_f(ns['test_ood_structure_gap'])}`)\n"
        )

    if report.get("arm_comparison"):
        lines.append("\n## 6. Multi-Arm Comparison (Apples-to-Apples on `data/nagi_v9/`)\n\n")
        lines.append(
            "| Arm | Params | Val Unseen FG | Val OOD FG | Test Unseen FG | Test OOD FG | Unseen Copy (Test) | Efficiency (`TestOOD / 100k`) |\n"
            "|---|---:|---:|---:|---:|---:|---:|---:|\n"
        )
        for row in report["arm_comparison"]:
            lines.append(
                f"| {row['arm']} | {row['params']} | {_f(row['val_unseen_fg_exact'])} | "
                f"{_f(row['val_ood_fg_exact'])} | {_f(row['test_unseen_fg_exact'])} | "
                f"{_f(row['test_ood_fg_exact'])} | {_f(row['test_unseen_copy_acc'])} | {_f(row['efficiency_ratio'])} |\n"
            )

    if report.get("regression_comparison"):
        lines.append("\n## 7. Regression Comparison Against Baselines\n\n")
        for cmp_entry in report["regression_comparison"]:
            lines.append(
                f"- **vs `{cmp_entry['baseline_arm']}`** (`zero_regression={cmp_entry['zero_regression']}`, "
                f"`test_unseen_delta={_f(cmp_entry['overall_deltas']['test_unseen_fg_exact'])}`, "
                f"`test_ood_delta={_f(cmp_entry['overall_deltas']['test_ood_fg_exact'])}`, "
                f"`regressed_capabilities={cmp_entry['regressed_capabilities']}`)\n"
            )

    return "".join(lines)


def build_novel_structure_evaluation(
    splits_results: dict[str, dict[str, Any]],
    probes: dict[str, Any],
    audit_report: dict[str, Any],
) -> dict[str, Any]:
    vu_fg = splits_results["val_unseen"]["overall"]["free_generation"]["exact_match"]
    vo_fg = splits_results["val_ood"]["overall"]["free_generation"]["exact_match"]
    tu_fg = splits_results["test_unseen"]["overall"]["free_generation"]["exact_match"]
    to_fg = splits_results["test_ood"]["overall"]["free_generation"]["exact_match"]

    per_cap_ood: dict[str, Any] = {}
    for cap in EXPECTED_CAPABILITIES:
        tu_cap = splits_results["test_unseen"]["per_capability"].get(cap)
        to_cap = splits_results["test_ood"]["per_capability"].get(cap)
        tu_val = tu_cap["free_generation"]["exact_match"] if tu_cap else None
        to_val = to_cap["free_generation"]["exact_match"] if to_cap else None
        per_cap_ood[cap] = {
            "test_unseen_fg_exact": tu_val,
            "test_ood_fg_exact": to_val,
            "structure_gap": round(tu_val - to_val, 4) if (tu_val is not None and to_val is not None) else None,
        }

    gates = audit_report.get("gates", {})
    return {
        "tl01_zero_template_leakage": bool(gates.get("TL-01", {}).get("passed", False)),
        "sl01_zero_skeleton_leakage": bool(gates.get("SL-01", {}).get("passed", False)),
        "val_unseen_fg_exact": vu_fg,
        "val_ood_fg_exact": vo_fg,
        "val_ood_structure_gap": round(vu_fg - vo_fg, 4),
        "test_unseen_fg_exact": tu_fg,
        "test_ood_fg_exact": to_fg,
        "test_ood_structure_gap": round(tu_fg - to_fg, 4),
        "probe_2_premise_permutation_passed": probes["probe_2_premise_permutation_invariance"].get("passed"),
        "probe_3_depth_extrapolation_passed": probes["probe_3_depth_extrapolation_gap"].get("passed"),
        "probe_4_distractor_sensitivity_passed": probes["probe_4_distractor_sensitivity"].get("passed"),
        "per_capability_test_ood": per_cap_ood,
    }


def build_regression_comparison(
    current_report: dict[str, Any],
    baseline_reports: list[dict[str, Any]],
    tolerance: float = 0.01,
) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for base in baseline_reports:
        base_arm = base.get("checkpoint", {}).get("arm", "unknown")
        overall_deltas: dict[str, float | None] = {}
        for sp in EVAL_SPLITS:
            curr_sp = current_report["splits"].get(sp, {}).get("overall", {}).get("free_generation", {}).get("exact_match")
            base_sp = base.get("splits", {}).get(sp, {}).get("overall", {}).get("free_generation", {}).get("exact_match")
            overall_deltas[f"{sp}_fg_exact"] = (
                round(curr_sp - base_sp, 4) if (curr_sp is not None and base_sp is not None) else None
            )

        per_cap_deltas: dict[str, dict[str, float | None]] = {}
        regressed: list[str] = []
        for cap in EXPECTED_CAPABILITIES:
            tu_c = current_report["splits"]["test_unseen"]["per_capability"].get(cap, {}).get("free_generation", {}).get("exact_match")
            tu_b = base.get("splits", {}).get("test_unseen", {}).get("per_capability", {}).get(cap, {}).get("free_generation", {}).get("exact_match")
            to_c = current_report["splits"]["test_ood"]["per_capability"].get(cap, {}).get("free_generation", {}).get("exact_match")
            to_b = base.get("splits", {}).get("test_ood", {}).get("per_capability", {}).get(cap, {}).get("free_generation", {}).get("exact_match")
            d_tu = round(tu_c - tu_b, 4) if (tu_c is not None and tu_b is not None) else None
            d_to = round(to_c - to_b, 4) if (to_c is not None and to_b is not None) else None
            per_cap_deltas[cap] = {"test_unseen_delta": d_tu, "test_ood_delta": d_to}
            if (d_tu is not None and d_tu < -tolerance) or (d_to is not None and d_to < -tolerance):
                regressed.append(cap)

        comparisons.append(
            {
                "baseline_arm": base_arm,
                "baseline_checkpoint_sha256": base.get("checkpoint", {}).get("sha256"),
                "tolerance": tolerance,
                "overall_deltas": overall_deltas,
                "per_capability_deltas": per_cap_deltas,
                "regressed_capabilities": regressed,
                "zero_regression": len(regressed) == 0,
            }
        )
    return comparisons


def build_arm_comparison_rows(current_report: dict[str, Any], compare_paths: list[str]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for p_str in compare_paths:
        p = Path(p_str)
        if p.is_file():
            reports.append(json.loads(p.read_text(encoding="utf-8")))
    reports.append(current_report)

    seen_arms: dict[str, dict[str, Any]] = {}
    for rep in reports:
        arm_id = rep["checkpoint"]["arm"]
        seen_arms[arm_id] = rep

    rows = []
    for arm_id in sorted(seen_arms.keys()):
        rep = seen_arms[arm_id]
        params = rep["checkpoint"]["params"]
        to_fg = rep["splits"]["test_ood"]["overall"]["free_generation"]["exact_match"]
        tu_fg = rep["splits"]["test_unseen"]["overall"]["free_generation"]["exact_match"]
        vu_fg = rep["splits"]["val_unseen"]["overall"]["free_generation"]["exact_match"]
        vo_fg = rep["splits"]["val_ood"]["overall"]["free_generation"]["exact_match"]
        copy_tu = rep["splits"]["test_unseen"]["overall"]["free_generation"]["unseen_entity_copy_acc"]
        eff = (to_fg / (params / 100_000.0)) if params else None
        rows.append(
            {
                "arm": arm_id,
                "params": params,
                "val_unseen_fg_exact": vu_fg,
                "val_ood_fg_exact": vo_fg,
                "test_unseen_fg_exact": tu_fg,
                "test_ood_fg_exact": to_fg,
                "test_unseen_copy_acc": copy_tu,
                "efficiency_ratio": round(eff, 4) if eff is not None else None,
            }
        )
    return rows


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Evaluate ZYRQUEN v9 Checkpoint + 6 Principle Probes")
    ap.add_argument("--arm", choices=("arm_a", "arm_b", "arm_c", "arm_d"), default=None)
    ap.add_argument("--checkpoint", "--ckpt", dest="checkpoint", required=True, help="Path to .pt checkpoint")
    ap.add_argument("--data", default="data/nagi_v9", help="Dataset directory")
    ap.add_argument("--output_dir", "--out", dest="output_dir", required=True, help="Directory for report.json & report.md")
    ap.add_argument("--max_len", type=int, default=48, help="Max free-generation output tokens")
    ap.add_argument("--compare", nargs="*", default=[], help="Optional list of baseline report.json paths for 4-arm comparison")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data)
    ckpt_path = Path(args.checkpoint)

    if not (data_dir / "manifest.json").is_file():
        print(f"BLOCKED: Missing manifest.json in {data_dir}", file=sys.stderr)
        return 1
    audit_report = run_audit(data_dir)
    if audit_report.get("overall_status") != "PASS":
        failed = [k for k, v in audit_report["gates"].items() if not v.get("passed")]
        print(f"BLOCKED: Data Leakage Gate FAIL: {failed}", file=sys.stderr)
        return 1

    if not ckpt_path.is_file():
        print(f"BLOCKED: Checkpoint not found at {ckpt_path}", file=sys.stderr)
        return 1

    torch_mod, nn, F = require_torch()
    device = torch_mod.device("cuda" if torch_mod.cuda.is_available() else "cpu")
    ckpt = torch_mod.load(ckpt_path, map_location=device, weights_only=False)

    arm = args.arm or ckpt.get("arm")
    if arm not in ARM_DESCRIPTIONS:
        print(f"BLOCKED: Unknown or missing arm in checkpoint: {arm}", file=sys.stderr)
        return 1
    if args.arm and ckpt.get("arm") and args.arm != ckpt.get("arm"):
        print(f"BLOCKED: --arm {args.arm} does not match checkpoint arm {ckpt.get('arm')}", file=sys.stderr)
        return 1

    vocab = ckpt.get("vocab")
    if not isinstance(vocab, list) or not vocab:
        print("BLOCKED: Checkpoint missing train-only vocab", file=sys.stderr)
        return 1

    splits_data = {sp: load_jsonl(data_dir / f"{sp}.jsonl") for sp in ("train", *EVAL_SPLITS)}
    eval_all_rows = [r for sp in EVAL_SPLITS for r in splits_data[sp]]
    el05_ok, el05_overlap = verify_vocab_no_eval_leakage(vocab, eval_all_rows)
    if not el05_ok:
        print(f"BLOCKED: EL-05 vocab entity leakage detected in checkpoint: {el05_overlap[:10]}", file=sys.stderr)
        return 1

    stoi = {tok: idx for idx, tok in enumerate(vocab)}
    itos = {idx: tok for tok, idx in stoi.items()}
    arch_cfg = ckpt.get("arch_cfg", {})
    use_slots = bool(ckpt.get("use_slots", False))
    max_seq = int(arch_cfg.get("seq_len", MAX_CPU_SEQUENCE_LENGTH))

    model = instantiate_arm_model(arm, len(vocab), arch_cfg, torch_mod, nn, F, device)
    model_state = ckpt.get("model_state") or ckpt.get("model")
    if model_state is None:
        print("BLOCKED: Checkpoint missing model_state", file=sys.stderr)
        return 1
    model.load_state_dict(model_state)
    model.eval()

    train_entities: set[str] = set()
    for r in splits_data["train"]:
        for tok in tokenize_structural_text(f"{r['input']} {r['target']}"):
            if classify_entity_format(tok) is not None:
                train_entities.add(tok)

    splits_results: dict[str, dict[str, Any]] = {}
    for sp in EVAL_SPLITS:
        splits_results[sp] = evaluate_rows(
            arm=arm,
            model=model,
            rows=splits_data[sp],
            vocab=vocab,
            stoi=stoi,
            itos=itos,
            max_seq=max_seq,
            max_gen_len=args.max_len,
            use_slots=use_slots,
            train_entities=train_entities,
            torch_mod=torch_mod,
            F=F,
            device=device,
        )

    probes = run_principle_probes(
        arm=arm,
        model=model,
        splits_data=splits_data,
        splits_results=splits_results,
        vocab=vocab,
        stoi=stoi,
        itos=itos,
        max_seq=max_seq,
        max_gen_len=args.max_len,
        use_slots=use_slots,
        train_entities=train_entities,
        torch_mod=torch_mod,
        device=device,
    )

    baseline_reports = []
    for p_str in args.compare:
        p = Path(p_str)
        if p.is_file():
            baseline_reports.append(json.loads(p.read_text(encoding="utf-8")))

    assessment = assess_acceptance_and_stop_criteria(
        arm=arm,
        ckpt=ckpt,
        splits_results=splits_results,
        probes=probes,
        baseline_reports=baseline_reports,
    )

    report: dict[str, Any] = {
        "schema_version": "zyrquen.eval-v9.report.v1",
        "environment": collect_runtime_environment(torch_mod, device),
        "checkpoint": {
            "path": str(ckpt_path),
            "sha256": sha256_file(ckpt_path),
            "arm": arm,
            "description": ARM_DESCRIPTIONS[arm],
            "params": int(ckpt.get("params") or sum(p.numel() for p in model.parameters())),
            "vocab_size": len(vocab),
            "use_slots": use_slots,
            "step": ckpt.get("step"),
            "best_step": ckpt.get("best_step"),
            "best_val_loss": ckpt.get("best_val_loss"),
            "seed": ckpt.get("seed"),
            "train_elapsed_sec": ckpt.get("elapsed_sec"),
            "train_max_rss_kb": ckpt.get("max_rss_kb"),
        },
        "data_integrity": {
            "dataset": str(data_dir),
            "leakage_audit_status": audit_report["overall_status"],
            "el05_checkpoint_vocab_leakage": 0,
            "max_seq": max_seq,
            "max_gen_len": args.max_len,
        },
        "splits": splits_results,
        "novel_structure_evaluation": build_novel_structure_evaluation(splits_results, probes, audit_report),
        "principle_probes": probes,
        "acceptance_assessment": assessment,
        "arm_comparison": [],
        "regression_comparison": [],
    }
    if args.compare:
        report["arm_comparison"] = build_arm_comparison_rows(report, args.compare)
        report["regression_comparison"] = build_regression_comparison(report, baseline_reports)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "report.json"
    md_path = out_dir / "report.md"

    atomic_write_text(json_path, json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    atomic_write_text(md_path, format_markdown_report(report))

    tu_fg = splits_results["test_unseen"]["overall"]["free_generation"]
    to_fg = splits_results["test_ood"]["overall"]["free_generation"]
    print(f"OK evaluation report written to {json_path} and {md_path}")
    print(
        f"[{arm}] Test-Unseen FG={tu_fg['exact_match']:.4f} | Test-OOD FG={to_fg['exact_match']:.4f} | "
        f"Unseen-Copy={tu_fg['unseen_entity_copy_acc']} | StopTriggers={len(assessment['stop_criteria_triggered'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
