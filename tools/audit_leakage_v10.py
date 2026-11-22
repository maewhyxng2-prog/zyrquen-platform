#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — NAGI v10 Leakage Gate & Integrity Auditor (Read-Only)

Purpose:
  Independently inspect a generated data/nagi_v10/ dataset and verify:
  - Manifest schema, split presence, non-symlink/path safety, SHA-256 & content_sha256
  - JSONL record schema & field integrity
  - Unique single-answer verification for every reasoning example (no multi-answer ambiguity)
  - EL-01..EL-06 Entity disjointness across train / validation / test & static train vocab
  - TL-01 Template ID & raw phrasing disjointness across splits
  - SL-01 Abstract structural pattern separation on OOD examples
  - DL-01 Duplicate ID / input / empty target checks
  - SEQ_BUDGET Sequence token budget <= 256 (<= 250 before <bos>/<eos>)

Safety:
  - Strictly read-only on the dataset directory (never modifies dataset or manifest).
  - Pure Python standard library.
  - Does not touch v7, v8, or v9 artifacts.
  - Does not start training or evaluation inference.

Exit codes:
  0 = PASS (all gates passed)
  1 = FAIL (one or more audit gates failed)
  2 = INVALID ARGUMENTS / MISSING DIRECTORY
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, deque
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_DIR = PROJECT_ROOT / "data" / "nagi_v10"

SPLITS = ("train", "validation", "test")
EVAL_SPLITS = ("validation", "test")
MANIFEST_SCHEMA = "zyrquen.dataset-manifest.v1"
MAX_SEQUENCE_TOKENS = 250

EXPECTED_CAPABILITIES = (
    "abstract_reasoning",
    "relational_generalization",
    "ood_transfer",
    "multi_step_planning",
    "self_verification",
    "knowledge_integration",
)

REQUIRED_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "example_id",
        "split",
        "capability",
        "task_type",
        "reasoning_operator",
        "template_id",
        "instruction",
        "input",
        "target",
        "facts",
        "query",
        "answer",
        "unique_answer_verified",
        "metadata",
    }
)

ENTITY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("TR_E_prefix", re.compile(r"^TR_E\d+$")),
    ("VA_E_prefix", re.compile(r"^VA_E\d+$")),
    ("TE_E_prefix", re.compile(r"^TE_E\d+$")),
    ("node_scoped_id", re.compile(r"^node_(?:tr|va|te)_\d+$")),
    ("item_scoped_id", re.compile(r"^item_(?:tr|va|te)_\d+$")),
    ("step_scoped_id", re.compile(r"^step_(?:tr|va|te)_\d+$")),
    ("rec_scoped_e_id", re.compile(r"^rec_(?:tr|va|te)_e\d+$")),
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tokenize_structural_text(text: str) -> list[str]:
    t = text
    placeholders = (
        ("->", " __ARROW__ "),
        (":=", " __ASSIGN__ "),
        (">>", " __RSHIFT__ "),
        ("::", " __DCOLON__ "),
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


def extract_entities_from_text(text: str) -> set[str]:
    found: set[str] = set()
    for tok in tokenize_structural_text(text):
        if classify_entity_format(tok) is not None:
            found.add(tok)
    return found


def extract_entities_from_row(row: dict[str, Any]) -> set[str]:
    found = extract_entities_from_text(f"{row.get('input', '')} {row.get('target', '')}")
    for fact in row.get("facts", []) if isinstance(row.get("facts"), list) else []:
        if isinstance(fact, dict):
            for key in ("source", "target"):
                val = str(fact.get(key, ""))
                if classify_entity_format(val) is not None:
                    found.add(val)
    return found


def raw_phrasing_signature(cap: str, text: str) -> str:
    out: list[str] = []
    for tok in tokenize_structural_text(text):
        if classify_entity_format(tok) is not None:
            out.append("<E>")
        elif tok.isdigit():
            out.append("<N>")
        else:
            out.append(tok)
    return f"{cap}::{' '.join(out)}"


def recompute_abstract_pattern(cap: str, text: str) -> str:
    mapping: dict[str, str] = {}
    out: list[str] = []
    for tok in tokenize_structural_text(text):
        if classify_entity_format(tok) is not None:
            if tok not in mapping:
                mapping[tok] = f"<E{len(mapping)}>"
            out.append(mapping[tok])
        else:
            out.append(tok)
    return f"{cap}::{' '.join(out)}"


def safe_resolve_file(root: Path, rel_path: str) -> Path:
    rel = Path(rel_path)
    if rel.is_absolute():
        raise ValueError(f"Absolute path forbidden in manifest: {rel_path}")
    candidate = root / rel
    if candidate.is_symlink():
        raise ValueError(f"Symlink file forbidden in dataset: {rel_path}")
    root_resolved = root.resolve(strict=True)
    resolved = candidate.resolve(strict=True)
    resolved.relative_to(root_resolved)
    if not resolved.is_file():
        raise ValueError(f"Not a regular file: {rel_path}")
    return resolved


# ---------------------------------------------------------------------------
# Independent reasoning uniqueness verifiers (prevents multi-answer ambiguity)
# ---------------------------------------------------------------------------


def _verify_exact_hop_path(facts: list[dict[str, Any]], query: dict[str, Any], answer: str) -> tuple[bool, str]:
    relation = str(query.get("relation", ""))
    start = str(query.get("source", ""))
    hops = int(query.get("hops", 0))
    if hops < 1:
        return False, "hops must be >= 1"

    adj: dict[str, list[str]] = {}
    for fact in facts:
        if fact.get("relation") == relation:
            adj.setdefault(str(fact["source"]), []).append(str(fact["target"]))

    walk_counts: dict[str, int] = {start: 1}
    shortcuts: set[str] = set()
    for hop_idx in range(1, hops + 1):
        nxt_counts: dict[str, int] = {}
        for node, cnt in walk_counts.items():
            for nxt in adj.get(node, ()):
                nxt_counts[nxt] = nxt_counts.get(nxt, 0) + cnt
        walk_counts = nxt_counts
        if hop_idx < hops:
            shortcuts.update(walk_counts.keys())

    endpoints = sorted(walk_counts.keys())
    if len(endpoints) != 1:
        return False, f"multi-answer or dead-end at {hops} hops: {endpoints}"
    if endpoints[0] != answer:
        return False, f"expected endpoint {endpoints[0]} != {answer}"
    if walk_counts[answer] != 1:
        return False, f"multiple {hops}-hop paths ({walk_counts[answer]}) to {answer}"
    if answer in shortcuts:
        return False, f"shorter (<{hops}) shortcut path reaches {answer}"
    return True, "ok"


def _verify_order_dag(facts: list[dict[str, Any]], left: str, right: str) -> tuple[bool, str]:
    adj: dict[str, set[str]] = {}
    nodes: set[str] = set()
    for fact in facts:
        if fact.get("relation") == "greater_than":
            s = str(fact["source"])
            t = str(fact["target"])
            adj.setdefault(s, set()).add(t)
            nodes.add(s)
            nodes.add(t)

    color: dict[str, int] = {}

    def has_cycle_from(u: str) -> bool:
        color[u] = 1
        for v in adj.get(u, ()):
            if color.get(v, 0) == 1:
                return True
            if color.get(v, 0) == 0 and has_cycle_from(v):
                return True
        color[u] = 2
        return False

    for n in sorted(nodes):
        if color.get(n, 0) == 0 and has_cycle_from(n):
            return False, "cycle_in_order_graph"

    def reachable(src: str, dst: str) -> bool:
        if src == dst:
            return False
        seen = {src}
        q = deque([src])
        while q:
            cur = q.popleft()
            for nxt in adj.get(cur, ()):
                if nxt == dst:
                    return True
                if nxt not in seen:
                    seen.add(nxt)
                    q.append(nxt)
        return False

    l_gt_r = reachable(left, right)
    r_gt_l = reachable(right, left)
    if l_gt_r and r_gt_l:
        return False, "contradictory_order"
    if l_gt_r:
        return True, ">"
    if r_gt_l:
        return True, "<"
    return True, "unknown"


def _verify_unique_plan(facts: list[dict[str, Any]], goal: str, answer: str) -> tuple[bool, str]:
    prereqs_of: dict[str, set[str]] = {}
    for fact in facts:
        if fact.get("relation") == "requires":
            prereqs_of.setdefault(str(fact["source"]), set()).add(str(fact["target"]))

    closure: set[str] = {goal}
    q = deque([goal])
    while q:
        cur = q.popleft()
        for pre in prereqs_of.get(cur, ()):
            if pre not in closure:
                closure.add(pre)
                q.append(pre)

    fwd: dict[str, set[str]] = {n: set() for n in closure}
    indeg: dict[str, int] = {n: 0 for n in closure}
    for node in closure:
        for pre in prereqs_of.get(node, ()):
            if pre in closure and node not in fwd[pre]:
                fwd[pre].add(node)
                indeg[node] += 1

    ready = sorted(n for n, d in indeg.items() if d == 0)
    order: list[str] = []
    while ready:
        if len(ready) != 1:
            return False, f"ambiguous topological branch: {ready}"
        cur = ready.pop(0)
        order.append(cur)
        for nxt in sorted(fwd[cur]):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
        ready.sort()

    expected = "impossible" if len(order) != len(closure) else " -> ".join(order)
    if expected != answer:
        return False, f"expected plan '{expected}' != '{answer}'"
    return True, "ok"


def _verify_self_verification(facts: list[dict[str, Any]], query: dict[str, Any], answer: str) -> tuple[bool, str]:
    subtype = query.get("subtype")
    if subtype == "claim_check":
        ok, actual = _verify_order_dag(facts, str(query.get("left", "")), str(query.get("right", "")))
        if not ok:
            return False, actual
        claimed = str(query.get("claimed_relation", ""))
        expected = "unknown" if actual == "unknown" else ("true" if actual == claimed else "false")
        return (expected == answer, f"expected {expected} != {answer}")

    if subtype == "plan_check":
        goal = str(query.get("goal", ""))
        proposed = [str(x) for x in query.get("proposed_plan", [])]
        prereqs_of: dict[str, set[str]] = {}
        for fact in facts:
            if fact.get("relation") == "requires":
                prereqs_of.setdefault(str(fact["source"]), set()).add(str(fact["target"]))
        closure: set[str] = {goal}
        q = deque([goal])
        while q:
            cur = q.popleft()
            for pre in prereqs_of.get(cur, ()):
                if pre not in closure:
                    closure.add(pre)
                    q.append(pre)

        # Check cycle first
        indeg = {n: 0 for n in closure}
        fwd: dict[str, set[str]] = {n: set() for n in closure}
        for node in closure:
            for pre in prereqs_of.get(node, ()):
                if pre in closure and node not in fwd[pre]:
                    fwd[pre].add(node)
                    indeg[node] += 1
        dq = deque([n for n, d in indeg.items() if d == 0])
        visited = 0
        while dq:
            cur = dq.popleft()
            visited += 1
            for nxt in fwd[cur]:
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    dq.append(nxt)
        if visited != len(closure):
            expected = "invalid_cycle"
        elif len(proposed) != len(set(proposed)) or set(proposed) != closure:
            expected = "invalid_missing"
        else:
            pos = {s: i for i, s in enumerate(proposed)}
            order_ok = all(pos[pre] < pos[s] for s in closure for pre in prereqs_of.get(s, ()))
            expected = "valid" if order_ok else "invalid_order"
        return (expected == answer, f"expected {expected} != {answer}")

    return False, f"unknown verification subtype: {subtype}"


def _verify_knowledge_integration(facts: list[dict[str, Any]], query: dict[str, Any], answer: str) -> tuple[bool, str]:
    entity = str(query.get("entity", ""))
    base: dict[str, str] = {}
    updates: list[tuple[str, str]] = []
    asserted: set[str] = set()
    observed: set[str] = set()
    for fact in facts:
        rel = fact.get("relation")
        s = str(fact["source"])
        t = str(fact["target"])
        if rel == "base_maps_to":
            base[s] = t
        elif rel == "update_maps_to":
            updates.append((s, t))
        elif rel == "assert_maps_to" and s == entity:
            asserted.add(t)
        elif rel == "observe_maps_to" and s == entity:
            observed.add(t)

    if asserted or observed:
        combined = asserted | observed
        expected = "conflict" if len(combined) > 1 else next(iter(combined))
    else:
        state = dict(base)
        for s, t in updates:
            state[s] = t
        expected = state.get(entity, "unknown")
    return (expected == answer, f"expected {expected} != {answer}")


def audit_unique_answer(row: dict[str, Any]) -> tuple[bool, str]:
    cap = row.get("capability")
    facts = row.get("facts", [])
    query = row.get("query", {})
    answer = str(row.get("answer", ""))
    if not isinstance(facts, list) or not isinstance(query, dict):
        return False, "invalid facts or query type"

    if cap in ("relational_generalization", "ood_transfer"):
        return _verify_exact_hop_path(facts, query, answer)
    if cap == "abstract_reasoning":
        ok, res = _verify_order_dag(facts, str(query.get("left", "")), str(query.get("right", "")))
        if not ok:
            return False, res
        return (res == answer, f"expected {res} != {answer}")
    if cap == "multi_step_planning":
        return _verify_unique_plan(facts, str(query.get("goal", "")), answer)
    if cap == "self_verification":
        return _verify_self_verification(facts, query, answer)
    if cap == "knowledge_integration":
        return _verify_knowledge_integration(facts, query, answer)
    return False, f"unsupported capability: {cap}"


# ---------------------------------------------------------------------------
# Main Audit Entrypoint
# ---------------------------------------------------------------------------


def run_audit(dataset_dir: Path) -> dict[str, Any]:
    if not dataset_dir.exists() or dataset_dir.is_symlink() or not dataset_dir.is_dir():
        raise FileNotFoundError(f"Dataset directory is missing or invalid: {dataset_dir}")

    manifest_path = dataset_dir / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise FileNotFoundError(f"Manifest file missing or symlinked: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json must be a JSON object")

    gates: dict[str, dict[str, Any]] = {}
    manifest_errors: list[str] = []

    if manifest.get("dataset") != "nagi_v10":
        manifest_errors.append(f"unexpected dataset id: {manifest.get('dataset')!r}")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        manifest_errors.append(f"unexpected manifest schema: {manifest.get('schema')!r}")

    rows_by_split: dict[str, list[dict[str, Any]]] = {}
    split_hashes: dict[str, str] = {}

    splits_meta = manifest.get("splits") if isinstance(manifest.get("splits"), dict) else {}
    files_meta = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}

    for split in SPLITS:
        split_entry = splits_meta.get(split) or files_meta.get(f"{split}.jsonl")
        if not isinstance(split_entry, dict):
            manifest_errors.append(f"manifest missing entry for split {split}")
            rows_by_split[split] = []
            continue

        rel_file = str(split_entry.get("path") or split_entry.get("file") or f"{split}.jsonl")
        try:
            split_path = safe_resolve_file(dataset_dir, rel_file)
        except Exception as exc:
            manifest_errors.append(f"{split} path resolution failed: {exc}")
            rows_by_split[split] = []
            continue

        actual_sha = sha256_file(split_path)
        split_hashes[split] = actual_sha
        expected_sha = str(split_entry.get("sha256", "")).lower()
        if expected_sha != actual_sha:
            manifest_errors.append(f"{split} sha256 mismatch")

        file_entry = files_meta.get(f"{split}.jsonl")
        if isinstance(file_entry, dict) and str(file_entry.get("sha256", "")).lower() != actual_sha:
            manifest_errors.append(f"{split} files entry sha256 mismatch")

        rows: list[dict[str, Any]] = []
        invalid_lines: list[int] = []
        for idx, line in enumerate(split_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                invalid_lines.append(idx)
                continue
            if not isinstance(obj, dict):
                invalid_lines.append(idx)
                continue
            rows.append(obj)

        if invalid_lines:
            manifest_errors.append(f"{split} invalid JSONL lines: {invalid_lines[:5]}")
        if not rows:
            manifest_errors.append(f"{split} contains zero records")

        expected_count = split_entry.get("example_count", split_entry.get("count", split_entry.get("documents")))
        if expected_count is not None and int(expected_count) != len(rows):
            manifest_errors.append(f"{split} count mismatch: manifest={expected_count} actual={len(rows)}")

        rows_by_split[split] = rows

    if len(split_hashes) == len(SPLITS):
        combined_sha = hashlib.sha256(
            "".join(split_hashes[s] for s in SPLITS).encode("utf-8")
        ).hexdigest()
        if manifest.get("content_sha256") != combined_sha:
            manifest_errors.append("manifest content_sha256 mismatch")

    gates["INTEGRITY_MANIFEST"] = {
        "description": "Manifest Schema, Split File Presence, and SHA-256 Integrity",
        "errors": manifest_errors,
        "total_examples": sum(len(v) for v in rows_by_split.values()),
        "split_counts": {s: len(v) for s, v in rows_by_split.items()},
        "passed": len(manifest_errors) == 0,
    }

    # Schema validation & Unique-answer verification
    schema_errors: list[dict[str, Any]] = []
    ambiguous_examples: list[dict[str, Any]] = []
    max_tokens = 0
    ents_by_split: dict[str, set[str]] = {s: set() for s in SPLITS}
    templates_by_split: dict[str, set[str]] = {s: set() for s in SPLITS}
    phrasings_by_split: dict[str, set[str]] = {s: set() for s in SPLITS}
    ood_patterns_by_split: dict[str, set[str]] = {s: set() for s in SPLITS}
    operators: set[str] = set()
    capabilities_seen: Counter[str] = Counter()

    for split in SPLITS:
        for row in rows_by_split[split]:
            missing = sorted(REQUIRED_RECORD_FIELDS - set(row))
            if missing:
                schema_errors.append({"split": split, "id": row.get("example_id"), "missing": missing})
                continue
            if row.get("split") != split:
                schema_errors.append({"split": split, "id": row.get("example_id"), "error": "split_mismatch"})
            if row.get("capability") not in EXPECTED_CAPABILITIES:
                schema_errors.append({"split": split, "id": row.get("example_id"), "error": "invalid_capability"})
            if str(row.get("target", "")) != str(row.get("answer", "")):
                schema_errors.append({"split": split, "id": row.get("example_id"), "error": "target_answer_mismatch"})

            capabilities_seen[str(row.get("capability"))] += 1
            operators.add(str(row.get("reasoning_operator")))

            ok_unique, unique_reason = audit_unique_answer(row)
            if not ok_unique:
                ambiguous_examples.append(
                    {
                        "split": split,
                        "example_id": row.get("example_id"),
                        "capability": row.get("capability"),
                        "reason": unique_reason,
                    }
                )

            inp = str(row.get("input", ""))
            tgt = str(row.get("target", ""))
            tok_len = len(tokenize_structural_text(inp)) + len(tokenize_structural_text(tgt))
            if tok_len > max_tokens:
                max_tokens = tok_len

            ents_by_split[split].update(extract_entities_from_row(row))
            templates_by_split[split].add(str(row.get("template_id")))
            phrasings_by_split[split].add(raw_phrasing_signature(str(row.get("capability")), inp))
            if row.get("capability") == "ood_transfer":
                ood_patterns_by_split[split].add(recompute_abstract_pattern("ood_transfer", inp))

    gates["SCHEMA_VALIDATION"] = {
        "description": "Record Schema & Split Consistency Check",
        "error_count": len(schema_errors),
        "sample_errors": schema_errors[:10],
        "passed": len(schema_errors) == 0,
    }

    gates["UNIQUE_ANSWER"] = {
        "description": "Exhaustive Solver Unique-Answer Verification (Anti-Ambiguity)",
        "ambiguous_count": len(ambiguous_examples),
        "sample_ambiguous": ambiguous_examples[:10],
        "passed": len(ambiguous_examples) == 0,
    }

    e_train = ents_by_split["train"]
    e_val = ents_by_split["validation"]
    e_test = ents_by_split["test"]

    el01 = sorted(e_train & e_val)
    el02 = sorted(e_train & e_test)
    el03 = sorted(e_val & e_test)

    gates["EL-01"] = {
        "description": "Train-Validation Entity Overlap",
        "overlap_count": len(el01),
        "sample_overlap": el01[:10],
        "passed": len(el01) == 0 and len(e_train) > 0 and len(e_val) > 0,
    }
    gates["EL-02"] = {
        "description": "Train-Test Entity Overlap",
        "overlap_count": len(el02),
        "sample_overlap": el02[:10],
        "passed": len(el02) == 0 and len(e_train) > 0 and len(e_test) > 0,
    }
    gates["EL-03"] = {
        "description": "Validation-Test Entity Overlap",
        "overlap_count": len(el03),
        "sample_overlap": el03[:10],
        "passed": len(el03) == 0 and len(e_val) > 0 and len(e_test) > 0,
    }

    leaked_eval: dict[str, int] = {}
    unseen_eval: dict[str, int] = {}
    for split in EVAL_SPLITS:
        leaked = 0
        unseen = 0
        for row in rows_by_split[split]:
            row_ents = extract_entities_from_row(row)
            if row_ents & e_train:
                leaked += 1
            elif row_ents:
                unseen += 1
        leaked_eval[split] = leaked
        unseen_eval[split] = unseen

    total_eval = sum(len(rows_by_split[s]) for s in EVAL_SPLITS)
    total_leaked = sum(leaked_eval.values())
    total_unseen = sum(unseen_eval.values())
    gates["EL-04"] = {
        "description": "Eval Example Entity Leakage Rate",
        "leaked_per_split": leaked_eval,
        "entity_leakage_rate": (total_leaked / total_eval) if total_eval else 1.0,
        "passed": total_leaked == 0 and total_eval > 0,
    }

    vocab_train: set[str] = set()
    for row in rows_by_split["train"]:
        vocab_train.update(tokenize_structural_text(str(row.get("input", ""))))
        vocab_train.update(tokenize_structural_text(str(row.get("target", ""))))
    el05 = sorted(vocab_train & (e_val | e_test))
    gates["EL-05"] = {
        "description": "Static Train Vocabulary Entity Leakage",
        "train_vocab_size": len(vocab_train),
        "overlap_count": len(el05),
        "sample_overlap": el05[:10],
        "passed": len(el05) == 0,
    }

    gates["EL-06"] = {
        "description": "Unseen Entity Eval Coverage",
        "unseen_per_split": unseen_eval,
        "unseen_entity_ratio": (total_unseen / total_eval) if total_eval else 0.0,
        "passed": total_unseen == total_eval and total_eval > 0,
    }

    # TL-01: Template ID & Raw Phrasing Disjointness across all 3 splits
    tid_tr_va = sorted(templates_by_split["train"] & templates_by_split["validation"])
    tid_tr_te = sorted(templates_by_split["train"] & templates_by_split["test"])
    tid_va_te = sorted(templates_by_split["validation"] & templates_by_split["test"])
    phr_tr_va = sorted(phrasings_by_split["train"] & phrasings_by_split["validation"])
    phr_tr_te = sorted(phrasings_by_split["train"] & phrasings_by_split["test"])
    phr_va_te = sorted(phrasings_by_split["validation"] & phrasings_by_split["test"])
    tl_pass = all(len(x) == 0 for x in (tid_tr_va, tid_tr_te, tid_va_te, phr_tr_va, phr_tr_te, phr_va_te))
    gates["TL-01"] = {
        "description": "Template ID & Raw Phrasing Disjointness Across Splits",
        "template_id_overlaps": {
            "train_vs_validation": len(tid_tr_va),
            "train_vs_test": len(tid_tr_te),
            "validation_vs_test": len(tid_va_te),
        },
        "raw_phrasing_overlaps": {
            "train_vs_validation": len(phr_tr_va),
            "train_vs_test": len(phr_tr_te),
            "validation_vs_test": len(phr_va_te),
        },
        "passed": tl_pass,
    }

    # SL-01: OOD structural abstract-pattern disjointness
    sl_tr_va = sorted(ood_patterns_by_split["train"] & ood_patterns_by_split["validation"])
    sl_tr_te = sorted(ood_patterns_by_split["train"] & ood_patterns_by_split["test"])
    sl_va_te = sorted(ood_patterns_by_split["validation"] & ood_patterns_by_split["test"])
    gates["SL-01"] = {
        "description": "OOD Abstract Structural Pattern Disjointness",
        "overlaps": {
            "train_vs_validation": len(sl_tr_va),
            "train_vs_test": len(sl_tr_te),
            "validation_vs_test": len(sl_va_te),
        },
        "passed": len(sl_tr_va) == 0 and len(sl_tr_te) == 0 and len(sl_va_te) == 0,
    }

    # DL-01: Duplicates & Empty Answers
    seen_ids: set[str] = set()
    seen_exact: set[str] = set()
    seen_norm: set[str] = set()
    dup_ids = 0
    dup_exact = 0
    dup_norm = 0
    empty_targets = 0
    for split in SPLITS:
        for row in rows_by_split[split]:
            eid = str(row.get("example_id", ""))
            inp = str(row.get("input", ""))
            tgt = str(row.get("target", ""))
            norm = " ".join(inp.lower().split())
            if eid in seen_ids:
                dup_ids += 1
            seen_ids.add(eid)
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

    gates["SEQ_BUDGET"] = {
        "description": "Max Sequence Budget <= 256 (<= 250 structural tokens)",
        "max_structural_tokens": max_tokens,
        "passed": 0 < max_tokens <= MAX_SEQUENCE_TOKENS,
    }

    all_passed = all(g["passed"] for g in gates.values())
    status = "PASS" if all_passed else "FAIL"
    unseen_abstract_ops = bool(
        (manifest.get("generalization_scope") or {}).get("unseen_abstract_operators", False)
    )

    return {
        "schema_version": "1.0",
        "project": "ZYRQUEN Ω∞",
        "dataset": "nagi_v10",
        "dataset_dir": str(dataset_dir),
        "read_only": True,
        "status": status,
        "overall_status": status,
        "total_examples": sum(len(v) for v in rows_by_split.values()),
        "split_counts": {s: len(v) for s, v in rows_by_split.items()},
        "capabilities": dict(sorted(capabilities_seen.items())),
        "reasoning_operators": sorted(operators),
        "unseen_abstract_operator_generalization": unseen_abstract_ops,
        "content_sha256": manifest.get("content_sha256"),
        "gates": gates,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only ZYRQUEN NAGI v10 Leakage & Integrity Auditor."
    )
    parser.add_argument(
        "--dataset-dir",
        "--data",
        dest="dataset_dir",
        type=Path,
        default=DEFAULT_DATASET_DIR,
        help="Path to data/nagi_v10 directory.",
    )
    parser.add_argument(
        "--out-report",
        type=Path,
        default=None,
        help="Optional external path to write JSON audit report (never overwrites existing file).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_dir = args.dataset_dir.expanduser().resolve()
    try:
        report = run_audit(dataset_dir)
    except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as exc:
        err_report = {
            "schema_version": "1.0",
            "project": "ZYRQUEN Ω∞",
            "dataset": "nagi_v10",
            "dataset_dir": str(dataset_dir),
            "read_only": True,
            "status": "FAIL",
            "overall_status": "FAIL",
            "error": str(exc),
        }
        print(json.dumps(err_report, ensure_ascii=False, indent=2, sort_keys=True))
        print(f"AUDIT FAILED: {exc}", file=sys.stderr)
        return 2 if isinstance(exc, FileNotFoundError) else 1

    if args.out_report is not None:
        out_path = args.out_report.expanduser().resolve()
        if out_path.exists():
            print(f"BLOCKED: audit report already exists: {out_path}", file=sys.stderr)
            return 2
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
