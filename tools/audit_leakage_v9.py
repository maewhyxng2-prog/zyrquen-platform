#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — v9 Leakage Gate & Integrity Auditor (Pure Python, Read-Only Audit)
Step 1 ONLY: Independently reads generated JSONL splits + manifest.json from disk
and audits EL-01 through DL-01 without hardcoded expected results.

Exits 0 only if every single gate and integrity check passes; exits 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

SPLITS = ("train", "val_unseen", "val_ood", "test_unseen", "test_ood")
EVAL_SPLITS = ("val_unseen", "val_ood", "test_unseen", "test_ood")
OOD_SPLITS = ("val_ood", "test_ood")

EXPECTED_SPLIT_COUNTS = {
    "train": 960,
    "val_unseen": 120,
    "val_ood": 120,
    "test_unseen": 120,
    "test_ood": 120,
}

EXPECTED_CAPABILITIES = (
    "native_representation",
    "knowledge_acquisition",
    "relational_reasoning",
    "planning_decomposition",
    "verification",
    "adaptive_learning",
    "knowledge_integration",
    "generalization",
)

# Comprehensive entity format recognizers required by EL-08
ENTITY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("TR_E_prefix", re.compile(r"^TR_E\d+$")),
    ("VA_E_prefix", re.compile(r"^VA_E\d+$")),
    ("TE_E_prefix", re.compile(r"^TE_E\d+$")),
    ("node_scoped_id", re.compile(r"^node_(?:tr|va|te)_\d+$")),
    ("item_scoped_id", re.compile(r"^item_(?:tr|va|te)_\d+$")),
    ("step_scoped_id", re.compile(r"^step_(?:tr|va|te)_\d+$")),
    ("rec_scoped_e_id", re.compile(r"^rec_(?:tr|va|te)_e\d+$")),
    ("other_scoped_id", re.compile(r"^[a-z]+_(?:tr|va|te)_(?:e)?\d+$")),
    ("legacy_E_digits", re.compile(r"^E\d+$")),
    ("legacy_suffix_e", re.compile(r"^[a-z0-9_]+_e\d+$")),
    ("ephemeral_slot", re.compile(r"^<slot_\d+>$")),
]

# Closed whitelist of structural operators, delimiters, small numeric indices, and verdicts
STRUCTURAL_WHITELIST: frozenset[str] = frozenset(
    {
        ",", ";", ":", "|", "?", "->", ":=", ">", "<", "=", "(", ")", "[", "]", "{", "}",
        ">>", "::", "/", "..", "@", "&", "+",
        "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
        "seq", "idx", "set", "minus", "first_rem", "pair_list", "pair_right", "window",
        "after", "before", "buffer", "pick_pos", "stream", "without", "rem_at",
        "ring_map", "mate_of", "array", "select_slot", "ordered", "skip", "next_after",
        "zipped", "partner",
        "facts", "lookup", "kb", "has", "what_has", "bind", "recall", "ledger", "maps",
        "fetch", "vault", "owns", "owner_of", "register", "links", "resolve", "atlas",
        "holds", "holder",
        "rel", "query", "graph", "compare", "vs", "chain", "relation", "edges", "gt",
        "eq", "cmp", "network", "above", "same", "deduce", "to", "topology", "beats",
        "matches", "infer", "dag", "over", "tied", "path_rel",
        "goal", "deps", "plan", "task_goal", "reqs", "steps", "missing", "objective",
        "prereq", "needs", "unavailable", "build_plan", "finish", "rules", "precedes",
        "absent", "sequence", "deliver", "requires", "blocked", "route", "achieve",
        "constraints", "unlocks", "lacking", "order",
        "claim", "verdict", "check_plan", "status", "assert", "given", "judge",
        "audit_route", "against", "check", "hypothesis", "decide", "inspect_steps",
        "target", "under", "outcome",
        "base", "update", "learn", "chain_query", "retract", "init", "drop", "patch",
        "read", "prior", "revise", "trace_chain", "memory_init", "erase", "state_of",
        "delta", "store", "amend", "follow_chain",
        "fact", "obs", "rule", "neq", "integrate", "src1", "src2", "reconcile",
        "stream_a", "stream_b", "check_consistency", "check_order", "feed_1", "feed_2",
        "unify", "report_x", "report_y", "adjudicate", "adjudicate_gt",
        "verify", "trace", "base_deps", "add_dep", "context", "prove", "state",
        "new_rule", "compose_trace", "compose_plan", "world", "change", "validate",
        "shift", "derive", "derive_plan",
        "true", "false", "unknown", "conflict", "impossible", "valid",
        "invalid_order", "invalid_missing", "invalid_cycle",
    }
)


def tokenize_structural_text(text: str) -> list[str]:
    """Split punctuation delimiters (like trailing ':') while preserving multi-char operators."""
    t = text
    placeholders = (
        ("->", " __ARROW__ "),
        (":=", " __ASSIGN__ "),
        (">>", " __RSHIFT__ "),
        ("::", " __DCOLON__ "),
        ("..", " __DOTS__ "),
    )
    for op, ph in placeholders:
        t = t.replace(op, ph)
    for sym in (",", ";", ":", "|", "?", ">", "<", "="):
        t = t.replace(sym, f" {sym} ")
    restore = {ph.strip(): op for op, ph in placeholders}
    return [restore.get(tok, tok) for tok in t.split()]


def classify_entity_format(tok: str) -> str | None:
    for fmt_name, pat in ENTITY_PATTERNS:
        if pat.match(tok):
            return fmt_name
    return None


def tokenize_v8_compat(text: str) -> list[str]:
    """Also verify compatibility with v8's symbol-splitting tokenizer."""
    t = text.replace("->", " __ARROW__ ")
    for s in [",", "|", ":", "?", ">", "<", "="]:
        t = t.replace(s, f" {s} ")
    return ["->" if x == "__ARROW__" else x for x in t.split()]


def extract_entities_from_text(text: str) -> set[str]:
    found: set[str] = set()
    for tok in text.split():
        if classify_entity_format(tok) is not None:
            found.add(tok)
    return found


def recompute_abstract_pattern(cap: str, text: str) -> str:
    mapping: dict[str, str] = {}
    out: list[str] = []
    for tok in text.split():
        if classify_entity_format(tok) is not None:
            if tok not in mapping:
                mapping[tok] = f"<E{len(mapping)}>"
            out.append(mapping[tok])
        else:
            out.append(tok)
    return f"{cap}::{' '.join(out)}"


def raw_phrasing_signature(cap: str, text: str) -> str:
    """Replace all entity tokens and numeric slot indices with generic markers."""
    out: list[str] = []
    for tok in text.split():
        if classify_entity_format(tok) is not None:
            out.append("<E>")
        elif tok.isdigit():
            out.append("<N>")
        else:
            out.append(tok)
    return f"{cap}::{' '.join(out)}"


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_audit(data_dir: Path) -> dict:
    gates: dict[str, dict] = {}

    manifest_path = data_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing manifest.json in {data_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    rows_by_split: dict[str, list[dict]] = {}
    manifest_errors: list[str] = []

    for split in SPLITS:
        p = data_dir / f"{split}.jsonl"
        if not p.is_file():
            manifest_errors.append(f"missing {p.name}")
            rows_by_split[split] = []
            continue
        rows = load_jsonl(p)
        rows_by_split[split] = rows

        expected_cnt = EXPECTED_SPLIT_COUNTS[split]
        if len(rows) != expected_cnt:
            manifest_errors.append(f"{split} count={len(rows)} expected={expected_cnt}")

        file_meta = manifest.get("files", {}).get(f"{split}.jsonl", {})
        actual_sha = sha256_file(p)
        if file_meta.get("sha256") != actual_sha:
            manifest_errors.append(
                f"{split} sha256 mismatch: manifest={file_meta.get('sha256')} actual={actual_sha}"
            )
        if file_meta.get("count") != len(rows):
            manifest_errors.append(
                f"{split} count mismatch vs manifest: manifest={file_meta.get('count')} actual={len(rows)}"
            )

        for cap in EXPECTED_CAPABILITIES:
            cap_cnt = sum(1 for r in rows if r.get("capability") == cap)
            expected_cap = expected_cnt // len(EXPECTED_CAPABILITIES)
            if cap_cnt != expected_cap:
                manifest_errors.append(f"{split}/{cap} count={cap_cnt} expected={expected_cap}")

    gates["INTEGRITY_MANIFEST"] = {
        "passed": len(manifest_errors) == 0,
        "errors": manifest_errors,
        "total_examples": sum(len(v) for v in rows_by_split.values()),
        "split_counts": {s: len(v) for s, v in rows_by_split.items()},
    }

    # Extract entity sets independently from raw text
    ents_by_split: dict[str, set[str]] = {}
    formats_by_split: dict[str, set[str]] = {}
    entity_targets_by_split: dict[str, int] = {}
    entity_target_caps_by_split: dict[str, set[str]] = {}
    uncovered_tokens: list[dict] = []
    max_ws_tokens = 0
    max_v8_tokens = 0

    for split in SPLITS:
        s_ents: set[str] = set()
        s_fmts: set[str] = set()
        ent_tgt_cnt = 0
        ent_tgt_caps: set[str] = set()

        for row in rows_by_split[split]:
            inp = str(row.get("input", ""))
            tgt = str(row.get("target", ""))
            ws_len = len(inp.split()) + len(tgt.split())
            v8_len = len(tokenize_v8_compat(inp)) + len(tokenize_v8_compat(tgt))
            max_ws_tokens = max(max_ws_tokens, ws_len)
            max_v8_tokens = max(max_v8_tokens, v8_len)

            for field_name, txt in (("input", inp), ("target", tgt)):
                for tok in tokenize_structural_text(txt):
                    fmt = classify_entity_format(tok)
                    if fmt is not None:
                        s_ents.add(tok)
                        s_fmts.add(fmt)
                    elif tok not in STRUCTURAL_WHITELIST:
                        uncovered_tokens.append(
                            {
                                "split": split,
                                "id": row.get("id"),
                                "field": field_name,
                                "token": tok,
                            }
                        )

            tgt_ents = extract_entities_from_text(tgt)
            if tgt_ents:
                ent_tgt_cnt += 1
                ent_tgt_caps.add(str(row.get("capability")))

        ents_by_split[split] = s_ents
        formats_by_split[split] = s_fmts
        entity_targets_by_split[split] = ent_tgt_cnt
        entity_target_caps_by_split[split] = ent_tgt_caps

    e_train = ents_by_split["train"]
    e_val = ents_by_split["val_unseen"] | ents_by_split["val_ood"]
    e_test = ents_by_split["test_unseen"] | ents_by_split["test_ood"]

    # EL-01: |E_train ∩ E_val| == 0
    el01_overlap = sorted(e_train & e_val)
    gates["EL-01"] = {
        "description": "Train-Val Entity Overlap",
        "overlap_count": len(el01_overlap),
        "sample_overlap": el01_overlap[:10],
        "passed": len(el01_overlap) == 0,
    }

    # EL-02: |E_train ∩ E_test| == 0
    el02_overlap = sorted(e_train & e_test)
    gates["EL-02"] = {
        "description": "Train-Test Entity Overlap",
        "overlap_count": len(el02_overlap),
        "sample_overlap": el02_overlap[:10],
        "passed": len(el02_overlap) == 0,
    }

    # EL-03: |E_val ∩ E_test| == 0
    el03_overlap = sorted(e_val & e_test)
    gates["EL-03"] = {
        "description": "Val-Test Entity Overlap",
        "overlap_count": len(el03_overlap),
        "sample_overlap": el03_overlap[:10],
        "passed": len(el03_overlap) == 0,
    }

    # EL-04 & EL-06: Per-example leakage rate and unseen-entity ratio in eval splits
    leaked_examples: dict[str, int] = {}
    unseen_examples: dict[str, int] = {}
    for split in EVAL_SPLITS:
        leaked = 0
        unseen_ok = 0
        for row in rows_by_split[split]:
            row_ents = extract_entities_from_text(
                f"{row.get('input', '')} {row.get('target', '')}"
            )
            if row_ents & e_train:
                leaked += 1
            if len(row_ents) > 0 and not (row_ents & e_train):
                unseen_ok += 1
        leaked_examples[split] = leaked
        unseen_examples[split] = unseen_ok

    total_eval_examples = sum(len(rows_by_split[s]) for s in EVAL_SPLITS)
    total_leaked = sum(leaked_examples.values())
    total_unseen_ok = sum(unseen_examples.values())
    leakage_rate = (total_leaked / total_eval_examples) if total_eval_examples else 1.0
    unseen_ratio = (total_unseen_ok / total_eval_examples) if total_eval_examples else 0.0

    gates["EL-04"] = {
        "description": "Eval Example Entity Leakage Rate",
        "leaked_per_split": leaked_examples,
        "entity_leakage_rate": leakage_rate,
        "passed": total_leaked == 0 and total_eval_examples > 0,
    }

    # EL-05: Static Train Vocab vs Val/Test Entities
    vocab_train: set[str] = set()
    for row in rows_by_split["train"]:
        vocab_train.update(str(row.get("input", "")).split())
        vocab_train.update(str(row.get("target", "")).split())
        vocab_train.update(tokenize_v8_compat(str(row.get("input", ""))))
        vocab_train.update(tokenize_v8_compat(str(row.get("target", ""))))
    el05_overlap = sorted(vocab_train & (e_val | e_test))
    gates["EL-05"] = {
        "description": "Static Train Vocab Entity Leakage",
        "train_vocab_size": len(vocab_train),
        "overlap_count": len(el05_overlap),
        "sample_overlap": el05_overlap[:10],
        "passed": len(el05_overlap) == 0,
    }

    gates["EL-06"] = {
        "description": "Unseen Entity Sample Coverage",
        "unseen_per_split": unseen_examples,
        "unseen_entity_ratio": unseen_ratio,
        "passed": total_unseen_ok == total_eval_examples and total_eval_examples > 0,
    }

    # EL-07: Distinct unseen entities >= 30, >= 5 formats per split, >= 45 entity-targets per eval split
    el07_per_split = {}
    el07_pass = True
    for split in SPLITS:
        distinct_cnt = len(ents_by_split[split])
        fmt_cnt = len(formats_by_split[split])
        ent_tgt_cnt = entity_targets_by_split[split]
        cap_tgt_cnt = len(entity_target_caps_by_split[split])
        split_ok = distinct_cnt >= 30 and fmt_cnt >= 5
        if split in EVAL_SPLITS:
            split_ok = split_ok and (ent_tgt_cnt >= 45) and (cap_tgt_cnt >= 5)
        if not split_ok:
            el07_pass = False
        el07_per_split[split] = {
            "distinct_entities": distinct_cnt,
            "distinct_formats": fmt_cnt,
            "formats": sorted(formats_by_split[split]),
            "entity_target_examples": ent_tgt_cnt,
            "entity_target_capabilities": cap_tgt_cnt,
            "passed": split_ok,
        }
    gates["EL-07"] = {
        "description": "Minimum Distinct Unseen Entities, Formats, and Entity-Target Coverage",
        "per_split": el07_per_split,
        "passed": el07_pass,
    }

    # EL-08: Uncovered entity formats == 0
    gates["EL-08"] = {
        "description": "Entity Pattern Coverage (Uncovered Tokens Outside Whitelist)",
        "uncovered_count": len(uncovered_tokens),
        "sample_uncovered": uncovered_tokens[:10],
        "passed": len(uncovered_tokens) == 0,
    }

    # TL-01: Template ID & Raw Phrasing Overlap on OOD slices vs Train (and vs each other)
    train_tid = {str(r.get("template_id")) for r in rows_by_split["train"]}
    val_ood_tid = {str(r.get("template_id")) for r in rows_by_split["val_ood"]}
    test_ood_tid = {str(r.get("template_id")) for r in rows_by_split["test_ood"]}

    train_phrasing = {
        raw_phrasing_signature(str(r.get("capability")), str(r.get("input")))
        for r in rows_by_split["train"]
    }
    val_ood_phrasing = {
        raw_phrasing_signature(str(r.get("capability")), str(r.get("input")))
        for r in rows_by_split["val_ood"]
    }
    test_ood_phrasing = {
        raw_phrasing_signature(str(r.get("capability")), str(r.get("input")))
        for r in rows_by_split["test_ood"]
    }

    tl_tid_tr_vo = sorted(train_tid & val_ood_tid)
    tl_tid_tr_to = sorted(train_tid & test_ood_tid)
    tl_tid_vo_to = sorted(val_ood_tid & test_ood_tid)
    tl_phr_tr_vo = sorted(train_phrasing & val_ood_phrasing)
    tl_phr_tr_to = sorted(train_phrasing & test_ood_phrasing)
    tl_phr_vo_to = sorted(val_ood_phrasing & test_ood_phrasing)

    tl_pass = all(
        len(x) == 0
        for x in (
            tl_tid_tr_vo,
            tl_tid_tr_to,
            tl_tid_vo_to,
            tl_phr_tr_vo,
            tl_phr_tr_to,
            tl_phr_vo_to,
        )
    )
    gates["TL-01"] = {
        "description": "Template ID & Raw Phrasing Disjointness (OOD Slices)",
        "template_id_overlaps": {
            "train_vs_val_ood": len(tl_tid_tr_vo),
            "train_vs_test_ood": len(tl_tid_tr_to),
            "val_ood_vs_test_ood": len(tl_tid_vo_to),
        },
        "raw_phrasing_overlaps": {
            "train_vs_val_ood": len(tl_phr_tr_vo),
            "train_vs_test_ood": len(tl_phr_tr_to),
            "val_ood_vs_test_ood": len(tl_phr_vo_to),
        },
        "passed": tl_pass,
    }

    # SL-01: Recomputed Abstract Structural Pattern Overlap on OOD slices
    train_abs = {
        recompute_abstract_pattern(str(r.get("capability")), str(r.get("input")))
        for r in rows_by_split["train"]
    }
    val_unseen_abs = {
        recompute_abstract_pattern(str(r.get("capability")), str(r.get("input")))
        for r in rows_by_split["val_unseen"]
    }
    test_unseen_abs = {
        recompute_abstract_pattern(str(r.get("capability")), str(r.get("input")))
        for r in rows_by_split["test_unseen"]
    }
    seen_struct_pool = train_abs | val_unseen_abs | test_unseen_abs

    val_ood_abs = {
        recompute_abstract_pattern(str(r.get("capability")), str(r.get("input")))
        for r in rows_by_split["val_ood"]
    }
    test_ood_abs = {
        recompute_abstract_pattern(str(r.get("capability")), str(r.get("input")))
        for r in rows_by_split["test_ood"]
    }

    sl_tr_vo = sorted(seen_struct_pool & val_ood_abs)
    sl_tr_to = sorted(seen_struct_pool & test_ood_abs)
    sl_vo_to = sorted(val_ood_abs & test_ood_abs)
    sl_pass = len(sl_tr_vo) == 0 and len(sl_tr_to) == 0 and len(sl_vo_to) == 0
    gates["SL-01"] = {
        "description": "Abstract Structural Pattern Overlap (OOD Slices)",
        "overlaps": {
            "in_dist_vs_val_ood": len(sl_tr_vo),
            "in_dist_vs_test_ood": len(sl_tr_to),
            "val_ood_vs_test_ood": len(sl_vo_to),
        },
        "sample_overlaps": (sl_tr_vo + sl_tr_to + sl_vo_to)[:5],
        "passed": sl_pass,
    }

    # DL-01: Exact / Normalized Input Duplicates, ID Duplicates, Empty Targets
    seen_ids: set[str] = set()
    seen_exact: set[str] = set()
    seen_norm: set[str] = set()
    dup_ids = 0
    dup_exact = 0
    dup_norm = 0
    empty_targets = 0
    for split in SPLITS:
        for row in rows_by_split[split]:
            rid = str(row.get("id", ""))
            inp = str(row.get("input", ""))
            tgt = str(row.get("target", ""))
            norm = " ".join(inp.lower().split())
            if rid in seen_ids:
                dup_ids += 1
            seen_ids.add(rid)
            if inp in seen_exact:
                dup_exact += 1
            seen_exact.add(inp)
            if norm in seen_norm:
                dup_norm += 1
            seen_norm.add(norm)
            if not tgt.strip():
                empty_targets += 1

    gates["DL-01"] = {
        "description": "Duplicate ID / Input / Empty Target Check",
        "duplicate_ids": dup_ids,
        "duplicate_exact_inputs": dup_exact,
        "duplicate_normalized_inputs": dup_norm,
        "empty_targets": empty_targets,
        "passed": (dup_ids + dup_exact + dup_norm + empty_targets) == 0,
    }

    # Sequence Length & Label Balance Diagnostics
    seq_ok = max_ws_tokens <= 250 and max_v8_tokens <= 250
    gates["SEQ_BUDGET"] = {
        "description": "Max Token Budget <= 256 (with <bos>/<eos> margin)",
        "max_whitespace_tokens": max_ws_tokens,
        "max_v8_compat_tokens": max_v8_tokens,
        "passed": seq_ok,
    }

    label_balance: dict[str, dict] = {}
    for cap in ("relational_reasoning", "verification", "knowledge_integration", "adaptive_learning"):
        cap_counts: Counter[str] = Counter()
        for split in SPLITS:
            for row in rows_by_split[split]:
                if row.get("capability") == cap:
                    lbl = "<ENTITY>" if extract_entities_from_text(str(row.get("target"))) else str(row.get("target"))
                    cap_counts[lbl] += 1
        label_balance[cap] = dict(cap_counts)

    all_passed = all(g["passed"] for g in gates.values())
    return {
        "data_dir": str(data_dir),
        "seed": manifest.get("seed"),
        "overall_status": "PASS" if all_passed else "FAIL",
        "gates": gates,
        "label_balance_summary": label_balance,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit ZYRQUEN v9 Dataset Leakage Gates (EL-01..DL-01)")
    ap.add_argument("--data", default="data/nagi_v9", help="Dataset directory")
    ap.add_argument(
        "--out-report",
        default="data/nagi_v9/leakage_audit_report.json",
        help="Path to write JSON audit report (pass '' to skip)",
    )
    args = ap.parse_args()

    data_dir = Path(args.data)
    report = run_audit(data_dir)

    if args.out_report:
        report_path = Path(args.out_report)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"=== ZYRQUEN v9 Leakage Gate Audit ({data_dir}) ===")
    for gate_id, info in report["gates"].items():
        status = "PASS" if info["passed"] else "FAIL"
        print(f"  [{status}] {gate_id}: {info.get('description', gate_id)}")
    print(f"Overall Verdict: {report['overall_status']}")

    return 0 if report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
