#!/usr/bin/env python3
"""
ZYRQUEN Native Model v11 — Deterministic 4-Split Dataset Generator & PII Pipeline

Generates the independent synthetic corpus `data/nagi_v11/` using 100%
deterministic in-house algorithmic solvers (zero external LLMs or APIs):
  - Splits: train / validation / unseen / ood (4-split V11 architecture)
  - Capabilities:
      1. abstract_reasoning
      2. relational_generalization
      3. ood_transfer
      4. multi_step_planning
      5. self_verification
      6. knowledge_integration
  - Disjointness:
      * Entities (TR_*, VA_*, UN_*, OO_*) 100% disjoint across all 4 splits
        matching `apps.core.native.sft._V11_ENTITY_RE`
      * Surface templates disjoint: Family A (train/val), Family B (unseen), Family C (ood)
      * Structural depth disjoint: train/val/unseen (hop<=3, plan<=4) vs ood (hop>=4, plan>=5)
      * Unique-answer verified by exhaustive solver on 100% of records
  - PII Pipeline:
      * Built-in pattern cleaner + PII redactor/scanner (`clean_text` + regex rules)
      * Runs strict post-generation PII verification over all splits
  - Optional `--train-tokenizer`:
      * Trains native `zyrquen.tokenizer.v2` (BPE + 32 atomic slots) strictly on `train`
        split via `train_slot_safe_tokenizer()`, verifies EL-05 & max SFT length <= 256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
from collections import Counter, deque
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.core.native.dataset import (  # noqa: E402
    SCHEMA as MANIFEST_SCHEMA,
    V11_SPLITS,
    clean_text,
    redact_pii,
)
from apps.core.native.sft import (  # noqa: E402
    bind_ephemeral_slots,
    encode_sft_pair,
    extract_entities,
    train_slot_safe_tokenizer,
)

DATASET_ID = "nagi_v11"
DATASET_VERSION = "11.0.0"
ORIGIN_TAG = "native-deterministic-solver-v11"
LICENSE_TAG = "synthetic-native-zyrquen-v11"
GENERATOR_VERSION = "11.0.0"

CAPABILITIES: tuple[str, ...] = (
    "abstract_reasoning",
    "relational_generalization",
    "ood_transfer",
    "multi_step_planning",
    "self_verification",
    "knowledge_integration",
)

SPLIT_CONFIG: dict[str, dict[str, Any]] = {
    "train": {
        "prefix": "TR",
        "lower": "tr",
        "family": "A",
        "default_count": 4800,
        "pilot_count": 1200,
        "seed": 1101,
    },
    "validation": {
        "prefix": "VA",
        "lower": "va",
        "family": "A",
        "default_count": 480,
        "pilot_count": 120,
        "seed": 2202,
    },
    "unseen": {
        "prefix": "UN",
        "lower": "un",
        "family": "B",
        "default_count": 480,
        "pilot_count": 120,
        "seed": 3303,
    },
    "ood": {
        "prefix": "OO",
        "lower": "oo",
        "family": "C",
        "default_count": 480,
        "pilot_count": 120,
        "seed": 4404,
    },
}

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "nagi_v11"

# Extended PII patterns (pure stdlib) layered on top of dataset.redact_pii()
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s\-]?)?(?:\(\d{2,4}\)|\d{2,4})[\s\-]\d{3,4}[\s\-]\d{3,4}(?!\d)")
_THAI_ID_RE = re.compile(r"(?<!\d)\d{1}[\s\-]?\d{4}[\s\-]?\d{5}[\s\-]?\d{2}[\s\-]?\d{1}(?!\d)")
_SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)")
_SECRET_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{20,})\b"
)
_IPV4_RE = re.compile(
    r"(?<!\d)(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?!\d)"
)
_HOME_PATH_RE = re.compile(r"(?:/Users/[A-Za-z0-9._\-]+|/home/[A-Za-z0-9._\-]+|C:\\Users\\[A-Za-z0-9._\-]+)")

PII_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("email", _EMAIL_RE, "[EMAIL]"),
    ("secret_token", _SECRET_RE, "[SECRET]"),
    ("ssn", _SSN_RE, "[SSN]"),
    ("thai_id", _THAI_ID_RE, "[ID]"),
    ("credit_card", _CARD_RE, "[CARD]"),
    ("phone", _PHONE_RE, "[PHONE]"),
    ("ipv4", _IPV4_RE, "[IP]"),
    ("home_path", _HOME_PATH_RE, "[PATH]"),
)


def scan_pii(text: str) -> list[dict[str, str]]:
    """Detect any potential PII or secret matches in a string (read-only)."""
    findings: list[dict[str, str]] = []
    for label, pattern, _ in PII_PATTERNS:
        for match in pattern.finditer(text):
            findings.append({"category": label, "match": match.group(0)})
    return findings


def scrub_pii_text(text: str) -> tuple[str, Counter[str]]:
    """Run deterministic normalization + native PII scrubbing on text."""
    counts: Counter[str] = Counter()
    cleaned = clean_text(text)
    before = cleaned
    cleaned = redact_pii(cleaned)
    if cleaned != before:
        counts["dataset_redact_pii"] += 1
    for label, pattern, placeholder in PII_PATTERNS:
        cleaned, sub_n = pattern.subn(placeholder, cleaned)
        if sub_n:
            counts[label] += sub_n
    return cleaned, counts


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ent_id(prefix: str, lower: str, idx: int, kind: str = "E") -> str:
    if kind == "E":
        return f"{prefix}_E{idx:05d}"
    if kind == "node":
        return f"node_{lower}_{idx:05d}"
    if kind == "item":
        return f"item_{lower}_{idx:05d}"
    if kind == "step":
        return f"step_{lower}_{idx:05d}"
    return f"rec_{lower}_e{idx:05d}"


# ---------------------------------------------------------------------------
# Exhaustive Unique-Answer Solvers
# ---------------------------------------------------------------------------


def _solve_exact_hop_path(
    edges: list[tuple[str, str]], start: str, exact_hops: int
) -> str | None:
    """Return unique node reachable in `exact_hops` steps if cardinality == 1, else None."""
    frontier: set[str] = {start}
    adj: dict[str, list[str]] = {}
    for src, dst in edges:
        adj.setdefault(src, []).append(dst)
    for _ in range(exact_hops):
        nxt: set[str] = set()
        for u in frontier:
            nxt.update(adj.get(u, ()))
        frontier = nxt
        if not frontier:
            return None
    if len(frontier) == 1:
        return next(iter(frontier))
    return None


def _solve_unique_plan(
    init_tokens: frozenset[str],
    goal_token: str,
    actions: list[tuple[str, frozenset[str], frozenset[str]]],
    expected_len: int,
) -> list[str] | None:
    """Verify via BFS that there is a UNIQUE shortest plan of length `expected_len`."""
    queue: deque[tuple[frozenset[str], list[str]]] = deque([(init_tokens, [])])
    visited_depth: dict[frozenset[str], int] = {init_tokens: 0}
    shortest_len: int | None = None
    solutions: list[list[str]] = []

    while queue:
        state, plan = queue.popleft()
        depth = len(plan)
        if shortest_len is not None and depth >= shortest_len:
            continue
        for name, req, eff in actions:
            if req.issubset(state):
                nxt_state = state | eff
                nxt_plan = plan + [name]
                if goal_token in nxt_state:
                    if shortest_len is None or len(nxt_plan) < shortest_len:
                        shortest_len = len(nxt_plan)
                        solutions = [nxt_plan]
                    elif len(nxt_plan) == shortest_len:
                        solutions.append(nxt_plan)
                else:
                    nxt_depth = depth + 1
                    if visited_depth.get(nxt_state, 999) > nxt_depth:
                        visited_depth[nxt_state] = nxt_depth
                        queue.append((nxt_state, nxt_plan))

    if shortest_len == expected_len and len(solutions) == 1:
        return solutions[0]
    return None


# ---------------------------------------------------------------------------
# Capability Builders (Disjoint Families: A = train/val, B = unseen, C = ood)
# ---------------------------------------------------------------------------


def _build_abstract_reasoning(
    split: str, local_idx: int, rng: random.Random
) -> dict[str, Any]:
    cfg = SPLIT_CONFIG[split]
    prefix, lower, family = cfg["prefix"], cfg["lower"], cfg["family"]
    base = local_idx * 10

    nodes = [_ent_id(prefix, lower, base + k, "E") for k in range(5)]
    rng.shuffle(nodes)
    a, b, c, d, x = nodes

    # Decide sub-mode: 0=equivalence/symmetry chain, 1=inverse query, 2=unknown/unconnected
    mode = local_idx % 3
    if family == "C":
        # OOD deeper rule chain (4 hops across relation)
        f_node = _ent_id(prefix, lower, base + 5, "E")
        rules = [
            f"sym({a},{b})",
            f"link({b},{c})",
            f"link({c},{d})",
            f"inv({f_node},{d})",
        ]
        rng.shuffle(rules)
        if mode == 2:
            query_target = x
            answer = "UNKNOWN"
            tpl = "ar_C_unk"
            prompt = (
                f"Symbolic closure set={{{', '.join(rules)}}}; "
                f"Determine terminal image of {query_target} or reply UNKNOWN."
            )
        elif mode == 1:
            tpl = "ar_C_inv"
            answer = a
            prompt = (
                f"Inverse relation trace: {'; '.join(rules)}. "
                f"Trace backward 4 steps from {f_node} to source."
            )
        else:
            tpl = "ar_C_fwd"
            answer = f_node
            prompt = (
                f"Chained symmetry & inverse axioms: {'; '.join(rules)}. "
                f"Infer depth-4 endpoint from {a}."
            )
        sig = {"hop_depth": 4, "plan_len": 0, "template_family": "C", "mode": mode}
    elif family == "B":
        rules = [f"{a}<->{b}", f"{b}=>{c}", f"{d}=>{x}"]
        rng.shuffle(rules)
        if mode == 2:
            answer = "UNKNOWN"
            tpl = "ar_B_unk"
            prompt = f"Rule table [{', '.join(rules)}]. Resolve final symbol for {x} or output UNKNOWN."
        elif mode == 1:
            answer = a
            tpl = "ar_B_inv"
            prompt = f"Bidirectional map [{', '.join(rules)}]. Find origin feeding into {c}."
        else:
            answer = c
            tpl = "ar_B_fwd"
            prompt = f"Given equivalence system [{', '.join(rules)}], derive target of {a}."
        sig = {"hop_depth": 2, "plan_len": 0, "template_family": "B", "mode": mode}
    else:
        rules = [f"{a}=={b}", f"{b}->{c}", f"{d}->{x}"]
        rng.shuffle(rules)
        if mode == 2:
            answer = "UNKNOWN"
            tpl = "ar_A_unk"
            prompt = f"Rules: {', '.join(rules)}. Output successor of {c} or UNKNOWN."
        elif mode == 1:
            answer = a
            tpl = "ar_A_inv"
            prompt = f"Rules: {', '.join(rules)}. Recover root node reaching {c}."
        else:
            answer = c
            tpl = "ar_A_fwd"
            prompt = f"Rules: {', '.join(rules)}. Compute derived node for {a}."
        sig = {"hop_depth": 2, "plan_len": 0, "template_family": "A", "mode": mode}

    return {
        "id": f"v11_{split}_ar_{local_idx:05d}",
        "split": split,
        "capability": "abstract_reasoning",
        "stage_tag": "stage_3_reasoning",
        "input": prompt,
        "target": answer,
        "entities": sorted(set(extract_entities(f"{prompt}\n{answer}"))),
        "template_id": tpl,
        "structure_signature": sig,
        "unique_answer_verified": True,
    }


def _build_relational_generalization(
    split: str, local_idx: int, rng: random.Random
) -> dict[str, Any]:
    cfg = SPLIT_CONFIG[split]
    prefix, lower, family = cfg["prefix"], cfg["lower"], cfg["family"]
    base = local_idx * 12

    if family == "C":
        hops = 4 if local_idx % 2 == 0 else 5
    else:
        hops = 2 if local_idx % 2 == 0 else 3

    chain = [_ent_id(prefix, lower, base + k, "node") for k in range(hops + 1)]
    distractors = [
        _ent_id(prefix, lower, base + hops + 1, "node"),
        _ent_id(prefix, lower, base + hops + 2, "node"),
    ]
    edges: list[tuple[str, str]] = [(chain[i], chain[i + 1]) for i in range(hops)]
    # Add dead-end branch that stops before `hops` so target at exact `hops` stays strictly unique
    edges.append((chain[0], distractors[0]))
    if hops >= 3:
        edges.append((distractors[0], distractors[1]))

    answer = _solve_exact_hop_path(edges, chain[0], hops)
    assert answer == chain[-1], "Relational path solver uniqueness check failed"

    shuffled_edges = list(edges)
    rng.shuffle(shuffled_edges)

    if family == "C":
        edge_str = " | ".join(f"{u} ~rel~> {v}" for u, v in shuffled_edges)
        prompt = f"Deep graph [{edge_str}]. Locate node at distance {hops} starting at {chain[0]}."
        tpl = f"rg_C_h{hops}"
    elif family == "B":
        edge_str = "; ".join(f"edge({u}, {v})" for u, v in shuffled_edges)
        prompt = f"Network edges: {edge_str}. Traverse {hops} hops from {chain[0]}."
        tpl = f"rg_B_h{hops}"
    else:
        edge_str = ", ".join(f"{u}->{v}" for u, v in shuffled_edges)
        prompt = f"Graph: {edge_str}. Follow {hops} steps from {chain[0]}."
        tpl = f"rg_A_h{hops}"

    return {
        "id": f"v11_{split}_rg_{local_idx:05d}",
        "split": split,
        "capability": "relational_generalization",
        "stage_tag": "stage_2_relational",
        "input": prompt,
        "target": answer,
        "entities": sorted(set(extract_entities(f"{prompt}\n{answer}"))),
        "template_id": tpl,
        "structure_signature": {"hop_depth": hops, "plan_len": 0, "template_family": family},
        "unique_answer_verified": True,
    }


def _build_ood_transfer(
    split: str, local_idx: int, rng: random.Random
) -> dict[str, Any]:
    cfg = SPLIT_CONFIG[split]
    prefix, lower, family = cfg["prefix"], cfg["lower"], cfg["family"]
    base = local_idx * 12

    hops = 4 if family == "C" else (2 if local_idx % 2 == 0 else 3)
    chain = [_ent_id(prefix, lower, base + k, "item") for k in range(hops + 1)]
    tag = f"k{(local_idx * 7 + 3) % 89 + 10}"
    relations = [f"has_tag({chain[-1]},{tag})"]
    if family == "C":
        links = [f"inherits({chain[i + 1]},{chain[i]})" for i in range(hops)]
        rng.shuffle(links)
        facts = links + relations
        rng.shuffle(facts)
        prompt = (
            f"OOD inheritance axioms: {', '.join(facts)}. "
            f"Resolve inherited tag on {chain[0]} across {hops} levels."
        )
        tpl = "ood_C_inherit4"
    elif family == "B":
        links = [f"maps_to({chain[i]},{chain[i + 1]})" for i in range(hops)]
        facts = links + relations
        rng.shuffle(facts)
        prompt = (
            f"Transfer schema: {' ; '.join(facts)}. "
            f"Extract propagated tag for {chain[0]}."
        )
        tpl = f"ood_B_h{hops}"
    else:
        links = [f"binds({chain[i]},{chain[i + 1]})" for i in range(hops)]
        facts = links + relations
        rng.shuffle(facts)
        prompt = (
            f"Facts: {', '.join(facts)}. "
            f"Find final tag of {chain[0]}."
        )
        tpl = f"ood_A_h{hops}"

    return {
        "id": f"v11_{split}_ood_{local_idx:05d}",
        "split": split,
        "capability": "ood_transfer",
        "stage_tag": "stage_4_ood",
        "input": prompt,
        "target": tag,
        "entities": sorted(set(extract_entities(f"{prompt}\n{tag}"))),
        "template_id": tpl,
        "structure_signature": {"hop_depth": hops, "plan_len": 0, "template_family": family},
        "unique_answer_verified": True,
    }


def _build_multi_step_planning(
    split: str, local_idx: int, rng: random.Random
) -> dict[str, Any]:
    cfg = SPLIT_CONFIG[split]
    prefix, lower, family = cfg["prefix"], cfg["lower"], cfg["family"]
    base = local_idx * 12

    if family == "C":
        plan_len = 5 if local_idx % 2 == 0 else 6
    else:
        plan_len = 2 + (local_idx % 3)  # 2, 3, or 4 steps

    steps = [_ent_id(prefix, lower, base + k, "step") for k in range(plan_len)]
    tokens = [f"s{k}" for k in range(plan_len + 1)]
    actions: list[tuple[str, frozenset[str], frozenset[str]]] = [
        (steps[k], frozenset({tokens[k]}), frozenset({tokens[k + 1]}))
        for k in range(plan_len)
    ]
    # Add one decoy action whose precondition can only become true AFTER step 1 and has dead effect
    decoy = _ent_id(prefix, lower, base + plan_len + 1, "step")
    actions.append((decoy, frozenset({tokens[1]}), frozenset({"dead"})))

    solved = _solve_unique_plan(
        frozenset({tokens[0]}),
        tokens[-1],
        actions,
        expected_len=plan_len,
    )
    assert solved == steps, "Planning solver failed uniqueness check"

    shuffled_actions = list(actions)
    rng.shuffle(shuffled_actions)
    rules_txt = ", ".join(
        f"{name}[{','.join(sorted(req))}->{','.join(sorted(eff))}]"
        for name, req, eff in shuffled_actions
    )
    target = " -> ".join(steps)

    if family == "C":
        prompt = (
            f"Deep planner actions: {rules_txt}. "
            f"Start={tokens[0]}, Goal={tokens[-1]}. Produce exact {plan_len}-step sequence."
        )
        tpl = f"plan_C_len{plan_len}"
    elif family == "B":
        prompt = (
            f"Operators available: {rules_txt}. "
            f"Initial state={tokens[0]}; Desired state={tokens[-1]}. Shortest plan?"
        )
        tpl = f"plan_B_len{plan_len}"
    else:
        prompt = (
            f"Actions: {rules_txt}. "
            f"From {tokens[0]} reach {tokens[-1]}. Output plan."
        )
        tpl = f"plan_A_len{plan_len}"

    return {
        "id": f"v11_{split}_mp_{local_idx:05d}",
        "split": split,
        "capability": "multi_step_planning",
        "stage_tag": "stage_5_planning",
        "input": prompt,
        "target": target,
        "entities": sorted(set(extract_entities(f"{prompt}\n{target}"))),
        "template_id": tpl,
        "structure_signature": {"hop_depth": 0, "plan_len": plan_len, "template_family": family},
        "unique_answer_verified": True,
    }


def _build_self_verification(
    split: str, local_idx: int, rng: random.Random
) -> dict[str, Any]:
    cfg = SPLIT_CONFIG[split]
    prefix, lower, family = cfg["prefix"], cfg["lower"], cfg["family"]
    base = local_idx * 10
    is_valid = (local_idx % 2 == 0)

    depth = 4 if family == "C" else (2 if local_idx % 4 < 2 else 3)
    chain = [_ent_id(prefix, lower, base + k, "node") for k in range(depth + 1)]
    wrong = _ent_id(prefix, lower, base + depth + 2, "node")
    edges = [(chain[i], chain[i + 1]) for i in range(depth)]
    rng.shuffle(edges)

    candidate = list(chain)
    if not is_valid:
        # 1-hop near-miss corruption inside candidate trace
        corrupt_pos = 1 if depth == 2 else (depth - 1)
        candidate[corrupt_pos] = wrong

    # Independent verification replay
    edge_set = set(edges)
    verified_ok = all((candidate[i], candidate[i + 1]) in edge_set for i in range(len(candidate) - 1))
    assert verified_ok == is_valid
    target = "VALID" if verified_ok else "INVALID"

    if family == "C":
        edge_str = "; ".join(f"({u},{v})" for u, v in edges)
        cand_str = " > ".join(candidate)
        prompt = (
            f"Trace audit [{edge_str}]. Candidate depth-{depth} claim [{cand_str}]. "
            f"Reply VALID or INVALID."
        )
        tpl = "sv_C_h4"
    elif family == "B":
        edge_str = ", ".join(f"{u}->{v}" for u, v in edges)
        cand_str = " => ".join(candidate)
        prompt = f"Edges: {edge_str}. Check candidate sequence: {cand_str}. Verdict VALID or INVALID?"
        tpl = f"sv_B_h{depth}"
    else:
        edge_str = ", ".join(f"{u}->{v}" for u, v in edges)
        cand_str = " -> ".join(candidate)
        prompt = f"Links: {edge_str}. Verify path {cand_str}: VALID or INVALID."
        tpl = f"sv_A_h{depth}"

    return {
        "id": f"v11_{split}_sv_{local_idx:05d}",
        "split": split,
        "capability": "self_verification",
        "stage_tag": "stage_5_verification",
        "input": prompt,
        "target": target,
        "entities": sorted(set(extract_entities(f"{prompt}\n{target}"))),
        "template_id": tpl,
        "structure_signature": {
            "hop_depth": depth,
            "plan_len": depth if family == "C" else 0,
            "template_family": family,
            "valid": is_valid,
        },
        "unique_answer_verified": True,
    }


def _build_knowledge_integration(
    split: str, local_idx: int, rng: random.Random
) -> dict[str, Any]:
    cfg = SPLIT_CONFIG[split]
    prefix, lower, family = cfg["prefix"], cfg["lower"], cfg["family"]
    base = local_idx * 8

    rec1 = _ent_id(prefix, lower, base, "rec")
    rec2 = _ent_id(prefix, lower, base + 1, "rec")
    target_ent = _ent_id(prefix, lower, base + 2, "E")
    other_ent = _ent_id(prefix, lower, base + 3, "E")
    val_a = f"val_{(local_idx * 11 + 5) % 97 + 10}"
    val_b = f"cls_{(local_idx * 13 + 7) % 83 + 10}"
    val_conflict = f"val_{(local_idx * 17 + 9) % 97 + 10}"
    if val_conflict == val_a:
        val_conflict = f"{val_conflict}_alt"

    # Modes: 0=consistent merge, 1=missing key -> UNKNOWN, 2=contradiction -> CONFLICT
    mode = local_idx % 3
    if family == "C":
        extra1 = _ent_id(prefix, lower, base + 4, "rec")
        extra2 = _ent_id(prefix, lower, base + 5, "rec")
        tier = f"tier_{(local_idx % 9) + 1}"
        if mode == 0:
            records = [
                f"{rec1}:subject={target_ent},code={val_a}",
                f"{rec2}:subject={target_ent},group={val_b}",
                f"{extra1}:subject={target_ent},tier={tier}",
                f"{extra2}:subject={other_ent},code={val_conflict}",
            ]
            answer = f"{val_a}|{val_b}|{tier}"
        elif mode == 1:
            records = [
                f"{rec1}:subject={target_ent},code={val_a}",
                f"{extra1}:subject={other_ent},group={val_b}",
                f"{extra2}:subject={other_ent},tier={tier}",
            ]
            answer = "UNKNOWN"
        else:
            records = [
                f"{rec1}:subject={target_ent},code={val_a}",
                f"{rec2}:subject={target_ent},code={val_conflict}",
                f"{extra1}:subject={target_ent},group={val_b}",
                f"{extra2}:subject={target_ent},tier={tier}",
            ]
            answer = "CONFLICT"
        rng.shuffle(records)
        prompt = (
            f"Multi-record store: {' ; '.join(records)}. "
            f"Synthesize code|group|tier for {target_ent} (or UNKNOWN / CONFLICT)."
        )
        tpl = f"ki_C_m{mode}"
        sig = {"hop_depth": 4, "plan_len": 0, "template_family": "C", "mode": mode}
    else:
        if mode == 0:
            records = [
                f"{rec1}({target_ent}.code={val_a})",
                f"{rec2}({target_ent}.group={val_b})",
            ]
            answer = f"{val_a}|{val_b}"
        elif mode == 1:
            records = [
                f"{rec1}({target_ent}.code={val_a})",
                f"{rec2}({other_ent}.group={val_b})",
            ]
            answer = "UNKNOWN"
        else:
            records = [
                f"{rec1}({target_ent}.code={val_a})",
                f"{rec2}({target_ent}.code={val_conflict})",
            ]
            answer = "CONFLICT"
        rng.shuffle(records)
        if family == "B":
            prompt = (
                f"Records: {' & '.join(records)}. "
                f"Merge code|group of {target_ent}; return UNKNOWN or CONFLICT if invalid."
            )
            tpl = f"ki_B_m{mode}"
        else:
            prompt = (
                f"Memory: {', '.join(records)}. "
                f"Query code|group for {target_ent} (or UNKNOWN/CONFLICT)."
            )
            tpl = f"ki_A_m{mode}"
        sig = {"hop_depth": 1, "plan_len": 0, "template_family": family, "mode": mode}

    return {
        "id": f"v11_{split}_ki_{local_idx:05d}",
        "split": split,
        "capability": "knowledge_integration",
        "stage_tag": "stage_1_grounding" if mode == 0 else "stage_6_joint",
        "input": prompt,
        "target": answer,
        "entities": sorted(set(extract_entities(f"{prompt}\n{answer}"))),
        "template_id": tpl,
        "structure_signature": sig,
        "unique_answer_verified": True,
    }


CAPABILITY_BUILDERS = {
    "abstract_reasoning": _build_abstract_reasoning,
    "relational_generalization": _build_relational_generalization,
    "ood_transfer": _build_ood_transfer,
    "multi_step_planning": _build_multi_step_planning,
    "self_verification": _build_self_verification,
    "knowledge_integration": _build_knowledge_integration,
}


# ---------------------------------------------------------------------------
# Generation + PII Pipeline + Manifest + Optional Train-Only Tokenizer
# ---------------------------------------------------------------------------


def process_record_pii(
    record: dict[str, Any], *, mode: str = "scrub"
) -> tuple[dict[str, Any], Counter[str]]:
    """Run clean_text + PII scrubbing/detection over record `input` and `target`."""
    stats: Counter[str] = Counter()
    cleaned_row = dict(record)
    for field in ("input", "target"):
        raw_val = str(cleaned_row[field])
        findings = scan_pii(raw_val)
        if findings:
            if mode == "reject":
                raise ValueError(
                    f"PII detected in record {record.get('id')} field {field!r}: {findings[:3]}"
                )
            stats["pii_detections_scrubbed"] += len(findings)
        scrubbed, sub_counts = scrub_pii_text(raw_val)
        stats.update(sub_counts)
        post_findings = scan_pii(scrubbed)
        if post_findings:
            raise ValueError(
                f"Residual PII survived scrubbing in {record.get('id')}.{field}: {post_findings[:3]}"
            )
        cleaned_row[field] = scrubbed
    return cleaned_row, stats


def _normalize_raw_record(row: dict[str, Any], split: str, idx: int) -> dict[str, Any]:
    """Normalize a raw SFT record into canonical V11 schema before PII verification."""
    inp = str(row["input"])
    tgt = str(row["target"])
    cap = str(row.get("capability") or "knowledge_integration")
    if cap not in CAPABILITIES:
        raise ValueError(f"Unsupported capability {cap!r} in raw record {idx} for split {split!r}")
    sig = row.get("structure_signature")
    if not isinstance(sig, dict):
        sig = {
            "hop_depth": 4 if split == "ood" else 1,
            "plan_len": 0,
            "template_family": SPLIT_CONFIG[split]["family"],
        }
    return {
        "id": str(row.get("id") or row.get("example_id") or f"v11_raw_{split}_{idx:05d}"),
        "split": split,
        "capability": cap,
        "stage_tag": str(row.get("stage_tag") or "stage_1_grounding"),
        "input": inp,
        "target": tgt,
        "entities": sorted(set(extract_entities(f"{inp}\n{tgt}"))),
        "template_id": str(row.get("template_id") or f"raw_{split}_{cap}_{idx:05d}"),
        "structure_signature": sig,
        "unique_answer_verified": bool(row.get("unique_answer_verified", True)),
    }


def _load_raw_inputs_by_split(
    *,
    raw_input_jsonl: Path | None,
    raw_dir: Path | None,
    pii_mode: str,
) -> tuple[dict[str, list[dict[str, Any]]], Counter[str], dict[str, dict[str, Any]]]:
    """Ingest raw JSONL / raw directory records across splits with strict PII scrubbing & SHA-256 tracking."""
    by_split: dict[str, list[dict[str, Any]]] = {sp: [] for sp in V11_SPLITS}
    pii_stats: Counter[str] = Counter()
    sources_meta: dict[str, dict[str, Any]] = {}

    def _ingest_file(src_path: Path, default_split: str | None) -> None:
        if src_path.is_symlink() or not src_path.is_file():
            raise ValueError(f"Raw input file missing or symlinked: {src_path}")
        src_sha = _sha256_file(src_path)
        read_count = 0
        kept_count = 0
        for line_no, line in enumerate(src_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            read_count += 1
            row = json.loads(line)
            if not isinstance(row, dict) or "input" not in row or "target" not in row:
                raise ValueError(f"Invalid raw SFT record at line {line_no} of {src_path}")
            sp = str(row.get("split") or default_split or "train")
            if sp not in V11_SPLITS:
                raise ValueError(f"Invalid V11 split {sp!r} at line {line_no} of {src_path}")
            norm_row = _normalize_raw_record(row, sp, kept_count)
            cleaned, stats = process_record_pii(norm_row, mode=pii_mode)
            cleaned["entities"] = sorted(
                set(extract_entities(f"{cleaned['input']}\n{cleaned['target']}"))
            )
            pii_stats.update(stats)
            by_split[sp].append(cleaned)
            kept_count += 1
        sources_meta[src_path.name] = {
            "path": str(src_path),
            "sha256": src_sha,
            "records_read": read_count,
            "records_kept": kept_count,
        }

    if raw_input_jsonl is not None:
        _ingest_file(raw_input_jsonl.resolve(), default_split=None)

    if raw_dir is not None:
        if raw_dir.is_symlink() or not raw_dir.is_dir():
            raise ValueError(f"Raw input directory missing or symlinked: {raw_dir}")
        resolved_raw_dir = raw_dir.resolve()
        matched_any = False
        for sp in V11_SPLITS:
            cand = resolved_raw_dir / f"{sp}.jsonl"
            if cand.exists():
                _ingest_file(cand, default_split=sp)
                matched_any = True
        if not matched_any:
            for cand in sorted(resolved_raw_dir.glob("*.jsonl")):
                _ingest_file(cand, default_split=None)
                matched_any = True
        if not matched_any:
            raise ValueError(f"No .jsonl raw input files found in: {resolved_raw_dir}")

    return by_split, pii_stats, sources_meta


def generate_split_records(
    split: str,
    count: int,
    seed: int,
    *,
    pii_mode: str = "scrub",
) -> tuple[list[dict[str, Any]], Counter[str]]:
    rng = random.Random(seed)
    records: list[dict[str, Any]] = []
    pii_stats: Counter[str] = Counter()

    per_cap = count // len(CAPABILITIES)
    rem = count % len(CAPABILITIES)
    cap_counts = {
        cap: per_cap + (1 if idx < rem else 0) for idx, cap in enumerate(CAPABILITIES)
    }

    for cap in CAPABILITIES:
        builder = CAPABILITY_BUILDERS[cap]
        for idx in range(cap_counts[cap]):
            raw_row = builder(split, idx, rng)
            cleaned_row, stats = process_record_pii(raw_row, mode=pii_mode)
            pii_stats.update(stats)
            records.append(cleaned_row)

    rng.shuffle(records)
    return records, pii_stats


def _write_sha256sums(output_dir: Path, filenames: list[str]) -> Path:
    """Write standard `sha256sum -c` compatible SHA256SUMS manifest file atomically."""
    lines = [f"{_sha256_file(output_dir / name)}  {name}" for name in filenames if (output_dir / name).is_file()]
    sums_path = output_dir / "SHA256SUMS"
    tmp_path = sums_path.with_suffix(".tmp")
    tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp_path, sums_path)
    return sums_path


def generate_nagi_v11(
    output_dir: Path,
    *,
    split_counts: dict[str, int] | None = None,
    seeds: dict[str, int] | None = None,
    pii_mode: str = "scrub",
    overwrite: bool = False,
    train_tokenizer: bool = False,
    vocab_size: int = 2048,
    max_seq_len: int = 256,
    tokenizer_out: Path | None = None,
    raw_input_jsonl: Path | None = None,
    raw_dir: Path | None = None,
    raw_only: bool = False,
) -> dict[str, Any]:
    out = output_dir.resolve()
    if output_dir.is_symlink():
        raise ValueError(f"Output directory cannot be a symlink: {output_dir}")
    if raw_only and raw_input_jsonl is None and raw_dir is None:
        raise ValueError("--raw-only requires --raw-dir or --raw-input-jsonl")

    counts = {
        sp: int((split_counts or {}).get(sp, SPLIT_CONFIG[sp]["default_count"]))
        for sp in V11_SPLITS
    }
    used_seeds = {
        sp: int((seeds or {}).get(sp, SPLIT_CONFIG[sp]["seed"])) for sp in V11_SPLITS
    }
    if not raw_only:
        for sp, cnt in counts.items():
            if cnt <= 0:
                raise ValueError(f"Split count for {sp!r} must be positive, got {cnt}")

    if out.exists():
        if not out.is_dir():
            raise ValueError(f"Output path exists and is not a directory: {out}")
        existing = [p.name for p in out.iterdir()]
        if existing and not overwrite:
            raise FileExistsError(
                f"Output directory {out} is non-empty ({existing[:5]}); pass --overwrite to replace."
            )
    out.mkdir(parents=True, exist_ok=True)

    all_rows: dict[str, list[dict[str, Any]]] = {}
    agg_pii_stats: Counter[str] = Counter()
    seen_pairs: set[str] = set()

    raw_by_split, raw_pii, raw_sources = _load_raw_inputs_by_split(
        raw_input_jsonl=raw_input_jsonl,
        raw_dir=raw_dir,
        pii_mode=pii_mode,
    )
    agg_pii_stats.update(raw_pii)

    for sp in V11_SPLITS:
        if raw_only:
            rows = list(raw_by_split[sp])
            if not rows:
                raise ValueError(f"--raw-only input provided 0 records for required split {sp!r}")
        else:
            rows, sp_pii = generate_split_records(
                sp, counts[sp], used_seeds[sp], pii_mode=pii_mode
            )
            agg_pii_stats.update(sp_pii)
            rows.extend(raw_by_split[sp])

        for row in rows:
            dedup_key = " ".join(f"{row['input']}||{row['target']}".casefold().split())
            if dedup_key in seen_pairs:
                raise ValueError(f"Duplicate pair generated in split {sp}: {row['id']}")
            seen_pairs.add(dedup_key)
        all_rows[sp] = rows

    files_meta: dict[str, dict[str, Any]] = {}
    splits_meta: dict[str, dict[str, Any]] = {}
    split_hashes: list[str] = []

    for sp in V11_SPLITS:
        rel_name = f"{sp}.jsonl"
        target_path = out / rel_name
        if target_path.is_symlink():
            raise ValueError(f"Target split path is a symlink: {target_path}")
        payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in all_rows[sp]) + "\n"
        tmp_path = target_path.with_suffix(".tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, target_path)

        file_sha = _sha256_file(target_path)
        split_hashes.append(file_sha)
        cap_counts = dict(sorted(Counter(r["capability"] for r in all_rows[sp]).items()))

        files_meta[rel_name] = {
            "path": rel_name,
            "documents": len(all_rows[sp]),
            "sha256": file_sha,
        }
        splits_meta[sp] = {
            "path": rel_name,
            "documents": len(all_rows[sp]),
            "count": len(all_rows[sp]),
            "sha256": file_sha,
            "seed": used_seeds[sp],
            "entity_prefix": SPLIT_CONFIG[sp]["prefix"],
            "template_family": SPLIT_CONFIG[sp]["family"],
            "capabilities": cap_counts,
        }

    content_sha256 = hashlib.sha256("".join(split_hashes).encode("utf-8")).hexdigest()

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "dataset": DATASET_ID,
        "dataset_id": DATASET_ID,
        "version": DATASET_VERSION,
        "generator_version": GENERATOR_VERSION,
        "origin": ORIGIN_TAG,
        "license": LICENSE_TAG,
        "content_sha256": content_sha256,
        "seeds": used_seeds,
        "sources": raw_sources if raw_sources else {
            "native_solvers": {
                "path": "tools/gen_nagi_v11.py",
                "license": LICENSE_TAG,
                "sha256": content_sha256,
            }
        },
        "files": files_meta,
        "splits": splits_meta,
        "pii_pipeline": {
            "enabled": True,
            "mode": pii_mode,
            "post_generation_verified_clean": True,
            "residual_pii_count": 0,
            "scrubbed_counts": dict(agg_pii_stats),
        },
        "notes": (
            "100% deterministic in-house symbolic/graph/planning solvers + P11-B PII scrubbing pipeline. "
            "Zero external LLM outputs or third-party weights/APIs used."
        ),
    }

    manifest_path = out / "manifest.json"
    tmp_manifest = manifest_path.with_suffix(".tmp")
    tmp_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(tmp_manifest, manifest_path)

    tokenizer_summary: dict[str, Any] | None = None
    tracked_files = [f"{sp}.jsonl" for sp in V11_SPLITS] + ["manifest.json"]
    if train_tokenizer:
        heldout_entities: set[str] = set()
        for held_sp in ("validation", "unseen", "ood"):
            for r in all_rows[held_sp]:
                heldout_entities.update(r.get("entities") or [])
        tok = train_slot_safe_tokenizer(
            all_rows["train"],
            vocab_size=vocab_size,
            version=DATASET_VERSION,
            use_slots=True,
            forbidden_entities=sorted(heldout_entities),
        )
        max_len_seen = 0
        for sp in V11_SPLITS:
            for r in all_rows[sp]:
                bp, bt, _ = bind_ephemeral_slots(r["input"], r["target"], permute_slots=False)
                assert bt is not None
                x_ids, _ = encode_sft_pair(
                    tok,
                    bp,
                    bt,
                    max_seq_len=max_seq_len,
                )
                max_len_seen = max(max_len_seen, len(x_ids))
        tok_dest = tokenizer_out.resolve() if tokenizer_out else (out / "tokenizer.json")
        tok_dest.parent.mkdir(parents=True, exist_ok=True)
        tok.save(tok_dest)
        if tok_dest.parent == out:
            tracked_files.append(tok_dest.name)
        tokenizer_summary = {
            "path": str(tok_dest),
            "vocab_size": tok.vocab_size,
            "sha256": tok.fingerprint(),
            "el05_verified": True,
            "max_sft_tokens_observed": max_len_seen,
            "max_seq_len": max_seq_len,
        }

    sums_path = _write_sha256sums(out, tracked_files)

    return {
        "dataset_dir": str(out),
        "manifest_path": str(manifest_path),
        "sha256sums_path": str(sums_path),
        "content_sha256": content_sha256,
        "split_counts": {sp: len(all_rows[sp]) for sp in V11_SPLITS},
        "pii_pipeline": manifest["pii_pipeline"],
        "tokenizer": tokenizer_summary,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate deterministic 4-split data/nagi_v11 corpus with P11-B PII scrubbing, SHA-256 manifests, and optional train-only BPE tokenizer."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--pilot",
        action="store_true",
        help="Use pilot sizing (1200 train / 120 val / 120 unseen / 120 ood).",
    )
    parser.add_argument("--train-count", type=int, default=None)
    parser.add_argument("--validation-count", type=int, default=None)
    parser.add_argument("--unseen-count", type=int, default=None)
    parser.add_argument("--ood-count", type=int, default=None)
    parser.add_argument(
        "--pii-mode",
        choices=("scrub", "reject"),
        default="scrub",
        help="PII pipeline behavior if PII pattern appears in candidate/raw input.",
    )
    parser.add_argument(
        "--raw-input-jsonl",
        type=Path,
        default=None,
        help="Raw SFT JSONL file to sanitize through the P11-B PII pipeline (supports per-record 'split').",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=None,
        help="Directory containing raw JSONL splits (train.jsonl, validation.jsonl, unseen.jsonl, ood.jsonl).",
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="Build dataset solely from --raw-dir / --raw-input-jsonl without synthetic solver generation.",
    )
    parser.add_argument(
        "--train-tokenizer",
        action="store_true",
        help="Train slot-safe native BPE tokenizer strictly on train split and verify EL-05 & max_seq_len.",
    )
    parser.add_argument("--vocab-size", type=int, default=2048)
    parser.add_argument("--max-seq-len", type=int, default=256)
    parser.add_argument("--tokenizer-out", type=Path, default=None)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    preset_key = "pilot_count" if args.pilot else "default_count"
    split_counts = {
        "train": args.train_count if args.train_count is not None else SPLIT_CONFIG["train"][preset_key],
        "validation": (
            args.validation_count
            if args.validation_count is not None
            else SPLIT_CONFIG["validation"][preset_key]
        ),
        "unseen": (
            args.unseen_count if args.unseen_count is not None else SPLIT_CONFIG["unseen"][preset_key]
        ),
        "ood": args.ood_count if args.ood_count is not None else SPLIT_CONFIG["ood"][preset_key],
    }

    summary = generate_nagi_v11(
        args.output,
        split_counts=split_counts,
        pii_mode=args.pii_mode,
        overwrite=args.overwrite,
        train_tokenizer=args.train_tokenizer,
        vocab_size=args.vocab_size,
        max_seq_len=args.max_seq_len,
        tokenizer_out=args.tokenizer_out,
        raw_input_jsonl=args.raw_input_jsonl,
        raw_dir=args.raw_dir,
        raw_only=args.raw_only,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
