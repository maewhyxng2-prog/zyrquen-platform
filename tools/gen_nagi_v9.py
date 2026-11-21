#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — v9 Dataset Generator (Pure Python)
Step 1 ONLY: Deterministic rule-based dataset generation for v9 Generalization.
Generates 1,440 examples across 5 splits and 8 capabilities in data/nagi_v9/:
  - train.jsonl       (960 = 120 x 8)
  - val_unseen.jsonl  (120 =  15 x 8)
  - val_ood.jsonl     (120 =  15 x 8)
  - test_unseen.jsonl (120 =  15 x 8)
  - test_ood.jsonl    (120 =  15 x 8)
  - manifest.json

No external AI models, no pretrained models, no training, no evaluation execution.
Does NOT modify v7/v8 files or checkpoints.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter, deque
from pathlib import Path

PROVENANCE = "synthetic_rule_based_v9"
GENERATOR_VERSION = "gen_nagi_v9_v1"

CAPABILITIES = (
    "native_representation",
    "knowledge_acquisition",
    "relational_reasoning",
    "planning_decomposition",
    "verification",
    "adaptive_learning",
    "knowledge_integration",
    "generalization",
)

CAP_PREFIX = {
    "native_representation": "NR",
    "knowledge_acquisition": "KA",
    "relational_reasoning": "RR",
    "planning_decomposition": "PD",
    "verification": "VF",
    "adaptive_learning": "AL",
    "knowledge_integration": "KI",
    "generalization": "GN",
}

SPLIT_PER_CAP = {
    "train": 120,
    "val_unseen": 15,
    "val_ood": 15,
    "test_unseen": 15,
    "test_ood": 15,
}

# Disjoint entity pools across Train / Val / Test (5 distinct formats per split).
ENTITY_POOLS: dict[str, list[str]] = {
    "train": (
        [f"TR_E{i:03d}" for i in range(180)]
        + [f"node_tr_{i:02d}" for i in range(30)]
        + [f"item_tr_{i:02d}" for i in range(30)]
        + [f"step_tr_{i:02d}" for i in range(30)]
        + [f"rec_tr_e{i:02d}" for i in range(30)]
    ),
    "val": (
        [f"VA_E{i:03d}" for i in range(40)]
        + [f"node_va_{i:02d}" for i in range(10)]
        + [f"item_va_{i:02d}" for i in range(10)]
        + [f"step_va_{i:02d}" for i in range(10)]
        + [f"rec_va_e{i:02d}" for i in range(10)]
    ),
    "test": (
        [f"TE_E{i:03d}" for i in range(40)]
        + [f"node_te_{i:02d}" for i in range(10)]
        + [f"item_te_{i:02d}" for i in range(10)]
        + [f"step_te_{i:02d}" for i in range(10)]
        + [f"rec_te_e{i:02d}" for i in range(10)]
    ),
}

SPLIT_TO_POOL = {
    "train": "train",
    "val_unseen": "val",
    "val_ood": "val",
    "test_unseen": "test",
    "test_ood": "test",
}

ENTITY_TOKEN_RE = re.compile(
    r"^(?:(?:TR|VA|TE)_E\d+|(?:node|item|step)_(?:tr|va|te)_\d+|rec_(?:tr|va|te)_e\d+)$"
)


def extract_entities(text: str) -> list[str]:
    seen: list[str] = []
    seen_set: set[str] = set()
    for tok in text.split():
        if ENTITY_TOKEN_RE.match(tok) and tok not in seen_set:
            seen_set.add(tok)
            seen.append(tok)
    return seen


def canonicalize_abstract_pattern(text: str) -> str:
    mapping: dict[str, str] = {}
    out_tokens: list[str] = []
    for tok in text.split():
        if ENTITY_TOKEN_RE.match(tok):
            if tok not in mapping:
                mapping[tok] = f"<E{len(mapping)}>"
            out_tokens.append(mapping[tok])
        else:
            out_tokens.append(tok)
    return " ".join(out_tokens)


def sample_entities(rng: random.Random, pool: list[str], k: int, cursor: int) -> list[str]:
    """Deterministically pick k distinct entities while mixing all 5 formats."""
    if k > len(pool):
        raise ValueError(f"Requested {k} entities from pool of size {len(pool)}")
    # Group by format prefix bucket so every sample mixes formats naturally.
    buckets = [
        [e for e in pool if e.startswith(("TR_E", "VA_E", "TE_E"))],
        [e for e in pool if e.startswith("node_")],
        [e for e in pool if e.startswith("item_")],
        [e for e in pool if e.startswith("step_")],
        [e for e in pool if e.startswith("rec_")],
    ]
    chosen: list[str] = []
    chosen_set: set[str] = set()
    # First pick across rotated buckets to guarantee format diversity
    offset = cursor % len(buckets)
    for b_idx in range(k):
        bucket = buckets[(offset + b_idx) % len(buckets)]
        candidate = bucket[(cursor + b_idx * 7 + rng.randrange(len(bucket))) % len(bucket)]
        if candidate not in chosen_set:
            chosen.append(candidate)
            chosen_set.add(candidate)
    # Fill remaining if any bucket collided
    shuffled_pool = list(pool)
    rng.shuffle(shuffled_pool)
    for candidate in shuffled_pool:
        if len(chosen) >= k:
            break
        if candidate not in chosen_set:
            chosen.append(candidate)
            chosen_set.add(candidate)
    rng.shuffle(chosen)
    return chosen


def solve_relation_graph(
    gt_edges: list[tuple[str, str]], eq_edges: list[tuple[str, str]], u: str, v: str
) -> str:
    """Compute exact transitive relation (> , < , = , conflict, unknown) between u and v."""
    if u == v:
        return "="

    # Union-Find / connected components for equality
    eq_adj: dict[str, set[str]] = {}
    for a, b in eq_edges:
        eq_adj.setdefault(a, set()).add(b)
        eq_adj.setdefault(b, set()).add(a)

    def eq_component(start: str) -> set[str]:
        visited = {start}
        q = deque([start])
        while q:
            cur = q.popleft()
            for nxt in eq_adj.get(cur, ()):
                if nxt not in visited:
                    visited.add(nxt)
                    q.append(nxt)
        return visited

    comp_u = eq_component(u)
    if v in comp_u:
        # Check if any strict gt edge lies inside the eq component (contradiction)
        for a, b in gt_edges:
            if a in comp_u and b in comp_u:
                return "conflict"
        return "="

    # Build strict directed graph collapsing equality components
    nodes = set()
    for a, b in gt_edges:
        nodes.add(a)
        nodes.add(b)
    for a, b in eq_edges:
        nodes.add(a)
        nodes.add(b)
    nodes.update([u, v])

    adj: dict[str, set[str]] = {n: set() for n in nodes}
    for a, b in gt_edges:
        adj[a].add(b)
    for a, b in eq_edges:
        adj[a].add(b)
        adj[b].add(a)

    def strictly_reaches(src: str, dst: str) -> bool:
        # True if there is a path from src to dst using at least one strict gt edge
        gt_set = set(gt_edges)
        visited: set[tuple[str, bool]] = {(src, False)}
        q = deque([(src, False)])
        while q:
            cur, used_gt = q.popleft()
            if cur == dst and used_gt:
                return True
            for nxt in adj.get(cur, ()):
                nxt_used = used_gt or ((cur, nxt) in gt_set)
                state = (nxt, nxt_used)
                if state not in visited:
                    visited.add(state)
                    q.append(state)
        return False

    u_gt_v = strictly_reaches(u, v)
    v_gt_u = strictly_reaches(v, u)
    if u_gt_v and v_gt_u:
        return "conflict"
    if u_gt_v:
        return ">"
    if v_gt_u:
        return "<"
    return "unknown"


def solve_topological_plan(
    goal: str, deps: list[tuple[str, str]], missing_nodes: set[str] | None = None
) -> tuple[str, str]:
    """
    deps contains pairs (later, earlier) meaning `later after earlier`.
    Returns (status, plan_str) where status in {'valid', 'cycle', 'missing'}
    """
    missing_nodes = missing_nodes or set()
    prereqs: dict[str, list[str]] = {}
    for later, earlier in deps:
        prereqs.setdefault(later, []).append(earlier)

    # Collect ancestor closure required to reach `goal`
    needed: set[str] = {goal}
    stack = [goal]
    visiting_seen: set[str] = set()
    while stack:
        cur = stack.pop()
        if cur in missing_nodes:
            return "missing", "impossible"
        if cur in visiting_seen:
            continue
        visiting_seen.add(cur)
        for pre in prereqs.get(cur, ()):
            if pre in missing_nodes:
                return "missing", "impossible"
            needed.add(pre)
            stack.append(pre)

    # Build induced subgraph on `needed`: edge earlier -> later
    indeg: dict[str, int] = {n: 0 for n in needed}
    fwd: dict[str, list[str]] = {n: [] for n in needed}
    for later, earlier in deps:
        if later in needed and earlier in needed:
            fwd[earlier].append(later)
            indeg[later] += 1

    ready = [n for n, d in indeg.items() if d == 0]
    order: list[str] = []
    while ready:
        ready.sort()
        cur = ready.pop(0)
        order.append(cur)
        for nxt in fwd[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)

    if len(order) != len(needed):
        return "cycle", "impossible"
    return "valid", " -> ".join(order)


def make_native_representation(
    rng: random.Random, pool: list[str], split: str, idx: int
) -> tuple[str, str, str, int, int, bool]:
    if split in ("train", "val_unseen", "test_unseen"):
        sub = idx % 4
        if sub == 0:
            ents = sample_entities(rng, pool, 4, idx)
            pos = idx % 4
            inp = f"seq: {ents[0]} , {ents[1]} , {ents[2]} , {ents[3]} | idx {pos} ?"
            return "NR_TR_01", inp, ents[pos], 1, 3, True
        if sub == 1:
            ents = sample_entities(rng, pool, 4, idx)
            rm_idx = (idx % 3) + 1
            rem = [e for j, e in enumerate(ents) if j != rm_idx]
            inp = f"set: {ents[0]} , {ents[1]} , {ents[2]} , {ents[3]} minus {ents[rm_idx]} | first_rem ?"
            return "NR_TR_02", inp, rem[0], 1, 3, True
        if sub == 2:
            ents = sample_entities(rng, pool, 6, idx)
            pairs = [(ents[0], ents[1]), (ents[2], ents[3]), (ents[4], ents[5])]
            q_pair = pairs[idx % 3]
            rng.shuffle(pairs)
            body = " ; ".join(f"{a} : {b}" for a, b in pairs)
            inp = f"pair_list: {body} | pair_right {q_pair[0]} ?"
            return "NR_TR_03", inp, q_pair[1], 1, 4, True
        ents = sample_entities(rng, pool, 5, idx)
        if idx % 2 == 0:
            anchor = 1 + (idx % 3)
            inp = f"window: {ents[0]} , {ents[1]} , {ents[2]} , {ents[3]} , {ents[4]} | after {ents[anchor]} ?"
            tgt = ents[anchor + 1]
        else:
            anchor = 1 + (idx % 3)
            inp = f"window: {ents[0]} , {ents[1]} , {ents[2]} , {ents[3]} , {ents[4]} | before {ents[anchor]} ?"
            tgt = ents[anchor - 1]
        return "NR_TR_04", inp, tgt, 1, 4, True

    if split == "val_ood":
        sub = idx % 3
        if sub == 0:
            ents = sample_entities(rng, pool, 6, idx)
            pos = idx % 6
            inp = f"buffer [ {ents[0]} | {ents[1]} | {ents[2]} | {ents[3]} | {ents[4]} | {ents[5]} ] >> pick_pos {pos}"
            return "NR_VA_OOD_01", inp, ents[pos], 1, 5, True
        if sub == 1:
            ents = sample_entities(rng, pool, 6, idx)
            rm_a, rm_b = ents[1], ents[3]
            rem = [e for e in ents if e not in (rm_a, rm_b)]
            pick = idx % len(rem)
            inp = f"stream < {ents[0]} ; {ents[1]} ; {ents[2]} ; {ents[3]} ; {ents[4]} ; {ents[5]} > without {rm_a} , {rm_b} >> rem_at {pick}"
            return "NR_VA_OOD_02", inp, rem[pick], 1, 5, True
        ents = sample_entities(rng, pool, 8, idx)
        pairs = [(ents[0], ents[1]), (ents[2], ents[3]), (ents[4], ents[5]), (ents[6], ents[7])]
        q_pair = pairs[idx % 4]
        rng.shuffle(pairs)
        body = " ".join(f"( {a} / {b} )" for a, b in pairs)
        inp = f"ring_map {body} >> mate_of {q_pair[0]}"
        return "NR_VA_OOD_03", inp, q_pair[1], 1, 6, True

    # test_ood
    sub = idx % 3
    if sub == 0:
        ents = sample_entities(rng, pool, 7, idx)
        pos = idx % 7
        inp = f"array {{ {ents[0]} , {ents[1]} , {ents[2]} , {ents[3]} , {ents[4]} , {ents[5]} , {ents[6]} }} :: select_slot {pos}"
        return "NR_TE_OOD_01", inp, ents[pos], 1, 6, True
    if sub == 1:
        ents = sample_entities(rng, pool, 6, idx)
        rm_a, rm_b = ents[0], ents[2]
        rem = [e for e in ents if e not in (rm_a, rm_b)]
        anchor_pos = idx % (len(rem) - 1)
        inp = f"ordered {ents[0]} .. {ents[1]} .. {ents[2]} .. {ents[3]} .. {ents[4]} .. {ents[5]} :: skip {rm_a} , {rm_b} :: next_after {rem[anchor_pos]}"
        return "NR_TE_OOD_02", inp, rem[anchor_pos + 1], 1, 5, True
    ents = sample_entities(rng, pool, 8, idx)
    pairs = [(ents[0], ents[1]), (ents[2], ents[3]), (ents[4], ents[5]), (ents[6], ents[7])]
    q_pair = pairs[idx % 4]
    rng.shuffle(pairs)
    body = " , ".join(f"{a} @ {b}" for a, b in pairs)
    inp = f"zipped {body} :: partner {q_pair[0]}"
    return "NR_TE_OOD_03", inp, q_pair[1], 1, 6, True


def make_knowledge_acquisition(
    rng: random.Random, pool: list[str], split: str, idx: int
) -> tuple[str, str, str, int, int, bool]:
    if split in ("train", "val_unseen", "test_unseen"):
        n_pairs = 4 if split == "train" else 5
        ents = sample_entities(rng, pool, n_pairs * 2, idx)
        pairs = [(ents[2 * j], ents[2 * j + 1]) for j in range(n_pairs)]
        q_pair = pairs[idx % n_pairs]
        rng.shuffle(pairs)
        sub = idx % 3
        if sub == 0:
            body = " ; ".join(f"{a} -> {b}" for a, b in pairs)
            inp = f"facts: {body} | lookup {q_pair[0]} ?"
            return "KA_TR_01", inp, q_pair[1], 1, n_pairs - 1, True
        if sub == 1:
            body = " ; ".join(f"{a} has {b}" for a, b in pairs)
            inp = f"kb: {body} | what_has {q_pair[1]} ?"
            return "KA_TR_02", inp, q_pair[0], 1, n_pairs - 1, True
        body = " ; ".join(f"{a} = {b}" for a, b in pairs)
        inp = f"bind: {body} | recall {q_pair[0]} ?"
        return "KA_TR_03", inp, q_pair[1], 1, n_pairs - 1, True

    if split == "val_ood":
        n_pairs = 5
        ents = sample_entities(rng, pool, n_pairs * 2, idx)
        pairs = [(ents[2 * j], ents[2 * j + 1]) for j in range(n_pairs)]
        q_pair = pairs[idx % n_pairs]
        rng.shuffle(pairs)
        if idx % 2 == 0:
            body = " | ".join(f"{a} maps {b}" for a, b in pairs)
            inp = f"ledger [ {body} ] >> fetch {q_pair[0]}"
            return "KA_VA_OOD_01", inp, q_pair[1], 1, 4, True
        body = " ; ".join(f"{a} owns {b}" for a, b in pairs)
        inp = f"vault {{ {body} }} >> owner_of {q_pair[1]}"
        return "KA_VA_OOD_02", inp, q_pair[0], 1, 4, True

    # test_ood
    n_pairs = 6
    ents = sample_entities(rng, pool, n_pairs * 2, idx)
    pairs = [(ents[2 * j], ents[2 * j + 1]) for j in range(n_pairs)]
    q_pair = pairs[idx % n_pairs]
    rng.shuffle(pairs)
    if idx % 2 == 0:
        body = " ".join(f"( {a} links {b} )" for a, b in pairs)
        inp = f"register {body} :: resolve {q_pair[0]}"
        return "KA_TE_OOD_01", inp, q_pair[1], 1, 5, True
    body = " , ".join(f"{a} holds {b}" for a, b in pairs)
    inp = f"atlas < {body} > :: holder {q_pair[1]}"
    return "KA_TE_OOD_02", inp, q_pair[0], 1, 5, True


def make_relational_reasoning(
    rng: random.Random, pool: list[str], split: str, idx: int
) -> tuple[str, str, str, int, int, bool]:
    # Balanced across >, <, =, unknown (mod 4)
    label_mode = idx % 4  # 0: >, 1: <, 2: =, 3: unknown

    if split in ("train", "val_unseen", "test_unseen"):
        hops = 2 if (split == "train" and idx % 2 == 0) else 3
        need = hops + 1 + 2  # main chain + 2 distractor nodes
        ents = sample_entities(rng, pool, need, idx)
        chain = ents[: hops + 1]
        dist = ents[hops + 1 :]
        gt_edges: list[tuple[str, str]] = []
        eq_edges: list[tuple[str, str]] = []
        if label_mode == 2:
            eq_edges = [(chain[j], chain[j + 1]) for j in range(hops)]
            gt_edges = [(dist[0], dist[1])]
            u, v = chain[0], chain[-1]
        else:
            gt_edges = [(chain[j], chain[j + 1]) for j in range(hops)]
            gt_edges.append((dist[0], dist[1]))
            if label_mode == 0:
                u, v = chain[0], chain[-1]
            elif label_mode == 1:
                u, v = chain[-1], chain[0]
            else:
                u, v = chain[0], dist[0]
        all_clauses = [f"{a} > {b}" for a, b in gt_edges] + [f"{a} = {b}" for a, b in eq_edges]
        rng.shuffle(all_clauses)
        tgt = solve_relation_graph(gt_edges, eq_edges, u, v)
        sub = idx % 3
        if sub == 0:
            inp = f"rel: {' , '.join(all_clauses)} | query {u} ? {v}"
            return "RR_TR_01", inp, tgt, hops, 2, False
        if sub == 1:
            inp = f"graph: {' , '.join(all_clauses)} | compare {u} vs {v} ?"
            return "RR_TR_02", inp, tgt, hops, 2, False
        inp = f"chain: {' , '.join(all_clauses)} | relation {u} , {v} ?"
        return "RR_TR_03", inp, tgt, hops, 2, False

    if split == "val_ood":
        hops = 4
        ents = sample_entities(rng, pool, hops + 1 + 3, idx)
        chain = ents[: hops + 1]
        dist = ents[hops + 1 :]
        gt_edges = []
        eq_edges = []
        if label_mode == 2:
            eq_edges = [(chain[j], chain[j + 1]) for j in range(hops)]
            gt_edges = [(dist[0], dist[1]), (dist[1], dist[2])]
            u, v = chain[0], chain[-1]
        else:
            gt_edges = [(chain[j], chain[j + 1]) for j in range(hops)]
            gt_edges.extend([(dist[0], dist[1]), (dist[1], dist[2])])
            if label_mode == 0:
                u, v = chain[0], chain[-1]
            elif label_mode == 1:
                u, v = chain[-1], chain[0]
            else:
                u, v = chain[1], dist[0]
        tgt = solve_relation_graph(gt_edges, eq_edges, u, v)
        if idx % 2 == 0:
            clauses = [f"{a} gt {b}" for a, b in gt_edges] + [f"{a} eq {b}" for a, b in eq_edges]
            rng.shuffle(clauses)
            inp = f"edges [ {' ; '.join(clauses)} ] >> cmp {u} / {v}"
            return "RR_VA_OOD_01", inp, tgt, hops, 2, False
        clauses = [f"{a} above {b}" for a, b in gt_edges] + [f"{a} same {b}" for a, b in eq_edges]
        rng.shuffle(clauses)
        inp = f"network {{ {' , '.join(clauses)} }} >> deduce {u} to {v}"
        return "RR_VA_OOD_02", inp, tgt, hops, 2, False

    # test_ood: 4-5 hops
    hops = 4 if idx % 2 == 0 else 5
    ents = sample_entities(rng, pool, hops + 1 + 3, idx)
    chain = ents[: hops + 1]
    dist = ents[hops + 1 :]
    gt_edges = []
    eq_edges = []
    if label_mode == 2:
        eq_edges = [(chain[j], chain[j + 1]) for j in range(hops)]
        gt_edges = [(dist[0], dist[1]), (dist[1], dist[2])]
        u, v = chain[0], chain[-1]
    else:
        gt_edges = [(chain[j], chain[j + 1]) for j in range(hops)]
        gt_edges.extend([(dist[0], dist[1]), (dist[1], dist[2])])
        if label_mode == 0:
            u, v = chain[0], chain[-1]
        elif label_mode == 1:
            u, v = chain[-1], chain[0]
        else:
            u, v = chain[0], dist[1]
    tgt = solve_relation_graph(gt_edges, eq_edges, u, v)
    if idx % 2 == 0:
        clauses = [f"{a} beats {b}" for a, b in gt_edges] + [f"{a} matches {b}" for a, b in eq_edges]
        rng.shuffle(clauses)
        inp = f"topology ( {' ; '.join(clauses)} ) :: infer {u} vs {v}"
        return "RR_TE_OOD_01", inp, tgt, hops, 2, False
    clauses = [f"{a} over {b}" for a, b in gt_edges] + [f"{a} tied {b}" for a, b in eq_edges]
    rng.shuffle(clauses)
    inp = f"dag < {' , '.join(clauses)} > :: path_rel {u} ? {v}"
    return "RR_TE_OOD_02", inp, tgt, hops, 2, False


def make_planning_decomposition(
    rng: random.Random, pool: list[str], split: str, idx: int
) -> tuple[str, str, str, int, int, bool]:
    # ~75% feasible topological plans (entity targets), ~25% impossible (cycle or missing)
    impossible_mode = (idx % 4 == 3)
    if split in ("train", "val_unseen", "test_unseen"):
        steps = 3 if (split == "train" and idx % 2 == 0) else 4
        ents = sample_entities(rng, pool, steps + 2, idx)
        chain = ents[:steps]  # p0 -> p1 -> ... -> goal
        dist = ents[steps:]
        goal = chain[-1]
        deps = [(chain[j + 1], chain[j]) for j in range(steps - 1)]
        deps.append((dist[0], goal))  # post-goal distractor
        deps.append((dist[1], dist[0]))
        missing: set[str] = set()
        if impossible_mode:
            if idx % 8 == 3:
                deps.append((chain[0], chain[-1]))  # cycle
            else:
                missing.add(chain[0])
        status, tgt = solve_topological_plan(goal, deps, missing)
        clauses = [f"{later} after {earlier}" for later, earlier in deps]
        rng.shuffle(clauses)
        miss_clause = f" ; missing: {' '.join(sorted(missing))}" if missing else ""
        entity_target = status == "valid"
        if idx % 2 == 0:
            inp = f"goal: {goal} | deps: {' , '.join(clauses)}{miss_clause} | plan ?"
            return "PD_TR_01", inp, tgt, steps - 1, 2, entity_target
        inp = f"task_goal: {goal} | reqs: {' , '.join(clauses)}{miss_clause} | steps ?"
        return "PD_TR_02", inp, tgt, steps - 1, 2, entity_target

    if split == "val_ood":
        steps = 5  # 4 dependency edges
        ents = sample_entities(rng, pool, steps + 2, idx)
        chain = ents[:steps]
        dist = ents[steps:]
        goal = chain[-1]
        deps = [(chain[j + 1], chain[j]) for j in range(steps - 1)]
        deps.append((dist[0], goal))
        deps.append((dist[1], dist[0]))
        missing = set()
        if impossible_mode:
            if idx % 8 == 3:
                deps.append((chain[1], chain[-1]))
            else:
                missing.add(chain[0])
        status, tgt = solve_topological_plan(goal, deps, missing)
        entity_target = status == "valid"
        if idx % 2 == 0:
            clauses = [f"{later} needs {earlier}" for later, earlier in deps]
            rng.shuffle(clauses)
            miss_clause = f" | unavailable {next(iter(missing))}" if missing else ""
            inp = f"objective {goal} :: prereq [ {' ; '.join(clauses)}{miss_clause} ] >> build_plan"
            return "PD_VA_OOD_01", inp, tgt, steps - 1, 2, entity_target
        clauses = [f"{earlier} precedes {later}" for later, earlier in deps]
        rng.shuffle(clauses)
        miss_clause = f" | absent {next(iter(missing))}" if missing else ""
        inp = f"finish {goal} :: rules {{ {' , '.join(clauses)}{miss_clause} }} >> sequence"
        return "PD_VA_OOD_02", inp, tgt, steps - 1, 2, entity_target

    # test_ood: 5-6 steps (4-5 dependency edges)
    steps = 5 if idx % 2 == 0 else 6
    ents = sample_entities(rng, pool, steps + 2, idx)
    chain = ents[:steps]
    dist = ents[steps:]
    goal = chain[-1]
    deps = [(chain[j + 1], chain[j]) for j in range(steps - 1)]
    deps.append((dist[0], goal))
    deps.append((dist[1], dist[0]))
    missing = set()
    if impossible_mode:
        if idx % 8 == 3:
            deps.append((chain[0], chain[-2]))
        else:
            missing.add(chain[0])
    status, tgt = solve_topological_plan(goal, deps, missing)
    entity_target = status == "valid"
    if idx % 2 == 0:
        clauses = [f"{later} requires {earlier}" for later, earlier in deps]
        rng.shuffle(clauses)
        miss_clause = f" | blocked {next(iter(missing))}" if missing else ""
        inp = f"deliver {goal} :: graph ( {' ; '.join(clauses)}{miss_clause} ) :: route"
        return "PD_TE_OOD_01", inp, tgt, steps - 1, 2, entity_target
    clauses = [f"{earlier} unlocks {later}" for later, earlier in deps]
    rng.shuffle(clauses)
    miss_clause = f" | lacking {next(iter(missing))}" if missing else ""
    inp = f"achieve {goal} :: constraints < {' , '.join(clauses)}{miss_clause} > :: order"
    return "PD_TE_OOD_02", inp, tgt, steps - 1, 2, entity_target


def check_plan_feasibility(
    proposed: list[str], goal: str, deps: list[tuple[str, str]], missing: set[str]
) -> str:
    """Deterministic verifier for proposed plans."""
    status, _ = solve_topological_plan(goal, deps, missing)
    if status == "cycle":
        return "invalid_cycle"
    if status == "missing":
        return "invalid_missing"
    # Collect required nodes
    prereqs: dict[str, list[str]] = {}
    for later, earlier in deps:
        prereqs.setdefault(later, []).append(earlier)
    needed: set[str] = {goal}
    stack = [goal]
    while stack:
        cur = stack.pop()
        for pre in prereqs.get(cur, ()):
            if pre not in needed:
                needed.add(pre)
                stack.append(pre)
    pos = {node: i for i, node in enumerate(proposed)}
    if not needed.issubset(pos.keys()):
        return "invalid_missing"
    for later, earlier in deps:
        if later in needed and earlier in needed:
            if pos[earlier] >= pos[later]:
                return "invalid_order"
    return "valid"


def make_verification(
    rng: random.Random, pool: list[str], split: str, idx: int
) -> tuple[str, str, str, int, int, bool]:
    # Cycle through 6 balanced verdict types:
    # 0: true, 1: false, 2: unknown, 3: valid, 4: invalid_order, 5: invalid_missing/invalid_cycle
    mode = idx % 6
    if split in ("train", "val_unseen", "test_unseen"):
        hops = 2 if (split == "train" and idx % 2 == 0) else 3
        if mode in (0, 1, 2):
            ents = sample_entities(rng, pool, hops + 1 + 2, idx)
            chain = ents[: hops + 1]
            dist = ents[hops + 1 :]
            gt_edges = [(chain[j], chain[j + 1]) for j in range(hops)] + [(dist[0], dist[1])]
            rng.shuffle(gt_edges)
            if mode == 0:
                cu, cv = chain[0], chain[-1]
            elif mode == 1:
                cu, cv = chain[-1], chain[0]
            else:
                cu, cv = chain[0], dist[0]
            rel = solve_relation_graph(gt_edges, [], cu, cv)
            tgt = "true" if rel == ">" else ("false" if rel == "<" else "unknown")
            facts_str = " , ".join(f"{a} > {b}" for a, b in gt_edges)
            inp = f"claim: {cu} > {cv} | facts: {facts_str} | verdict ?"
            return "VF_TR_01", inp, tgt, hops, 2, False

        steps = hops + 1
        ents = sample_entities(rng, pool, steps + 1, idx)
        chain = ents[:steps]
        goal = chain[-1]
        deps = [(chain[j + 1], chain[j]) for j in range(steps - 1)]
        deps.append((ents[-1], goal))
        missing: set[str] = set()
        proposed = list(chain)
        if mode == 4:
            proposed[0], proposed[1] = proposed[1], proposed[0]
        elif mode == 5:
            if (idx // 6) % 2 == 0:
                proposed = proposed[1:]  # missing step
            else:
                deps.append((chain[0], chain[-1]))  # cycle
        tgt = check_plan_feasibility(proposed, goal, deps, missing)
        clauses = [f"{later} after {earlier}" for later, earlier in deps]
        rng.shuffle(clauses)
        inp = f"check_plan: {' -> '.join(proposed)} | goal: {goal} | deps: {' , '.join(clauses)} | status ?"
        return "VF_TR_02", inp, tgt, hops, 1, False

    if split == "val_ood":
        hops = 4
        if mode in (0, 1, 2):
            ents = sample_entities(rng, pool, hops + 1 + 2, idx)
            chain = ents[: hops + 1]
            dist = ents[hops + 1 :]
            gt_edges = [(chain[j], chain[j + 1]) for j in range(hops)] + [(dist[0], dist[1])]
            rng.shuffle(gt_edges)
            if mode == 0:
                cu, cv = chain[0], chain[-1]
            elif mode == 1:
                cu, cv = chain[-1], chain[0]
            else:
                cu, cv = chain[1], dist[0]
            rel = solve_relation_graph(gt_edges, [], cu, cv)
            tgt = "true" if rel == ">" else ("false" if rel == "<" else "unknown")
            facts_str = " ; ".join(f"{a} gt {b}" for a, b in gt_edges)
            inp = f"assert ( {cu} gt {cv} ) given [ {facts_str} ] >> judge"
            return "VF_VA_OOD_01", inp, tgt, hops, 2, False

        steps = 5
        ents = sample_entities(rng, pool, steps + 1, idx)
        chain = ents[:steps]
        goal = chain[-1]
        deps = [(chain[j + 1], chain[j]) for j in range(steps - 1)]
        deps.append((ents[-1], goal))
        proposed = list(chain)
        if mode == 4:
            proposed[1], proposed[2] = proposed[2], proposed[1]
        elif mode == 5:
            if (idx // 6) % 2 == 0:
                proposed = proposed[1:]
            else:
                deps.append((chain[0], chain[-1]))
        tgt = check_plan_feasibility(proposed, goal, deps, set())
        clauses = [f"{later} needs {earlier}" for later, earlier in deps]
        rng.shuffle(clauses)
        inp = f"audit_route [ {' -> '.join(proposed)} ] goal {goal} against {{ {' ; '.join(clauses)} }} >> check"
        return "VF_VA_OOD_02", inp, tgt, hops, 1, False

    # test_ood
    hops = 4 if idx % 2 == 0 else 5
    if mode in (0, 1, 2):
        ents = sample_entities(rng, pool, hops + 1 + 2, idx)
        chain = ents[: hops + 1]
        dist = ents[hops + 1 :]
        gt_edges = [(chain[j], chain[j + 1]) for j in range(hops)] + [(dist[0], dist[1])]
        rng.shuffle(gt_edges)
        if mode == 0:
            cu, cv = chain[0], chain[-1]
        elif mode == 1:
            cu, cv = chain[-1], chain[0]
        else:
            cu, cv = chain[0], dist[1]
        rel = solve_relation_graph(gt_edges, [], cu, cv)
        tgt = "true" if rel == ">" else ("false" if rel == "<" else "unknown")
        facts_str = " ; ".join(f"{a} beats {b}" for a, b in gt_edges)
        inp = f"hypothesis {{ {cu} beats {cv} }} over < {facts_str} > :: decide"
        return "VF_TE_OOD_01", inp, tgt, hops, 2, False

    steps = hops + 1
    ents = sample_entities(rng, pool, steps + 1, idx)
    chain = ents[:steps]
    goal = chain[-1]
    deps = [(chain[j + 1], chain[j]) for j in range(steps - 1)]
    deps.append((ents[-1], goal))
    proposed = list(chain)
    if mode == 4:
        proposed[1], proposed[2] = proposed[2], proposed[1]
    elif mode == 5:
        if (idx // 6) % 2 == 0:
            proposed = proposed[1:]
        else:
            deps.append((chain[0], chain[-1]))
    tgt = check_plan_feasibility(proposed, goal, deps, set())
    clauses = [f"{later} requires {earlier}" for later, earlier in deps]
    rng.shuffle(clauses)
    inp = f"inspect_steps ( {' -> '.join(proposed)} ) target {goal} under ( {' ; '.join(clauses)} ) :: outcome"
    return "VF_TE_OOD_02", inp, tgt, hops, 1, False


def make_adaptive_learning(
    rng: random.Random, pool: list[str], split: str, idx: int
) -> tuple[str, str, str, int, int, bool]:
    # 0: override, 1: retention, 2: chained adaptation, 3: retraction -> unknown
    sub = idx % 4
    if split in ("train", "val_unseen", "test_unseen"):
        if sub in (0, 1):
            ents = sample_entities(rng, pool, 7, idx)
            k1, v1, k2, v2, k3, v3, v_new = ents
            mem = {k1: v1, k2: v2, k3: v3}
            mem[k1] = v_new
            q_key = k1 if sub == 0 else k2
            base_clauses = [f"{k1} -> {v1}", f"{k2} -> {v2}", f"{k3} -> {v3}"]
            rng.shuffle(base_clauses)
            inp = f"base: {' ; '.join(base_clauses)} | update: {k1} -> {v_new} | query {q_key} ?"
            return ("AL_TR_01" if sub == 0 else "AL_TR_02"), inp, mem[q_key], 1, 3, True
        if sub == 2:
            hops = 2 if (split == "train" and idx % 8 == 2) else 3
            ents = sample_entities(rng, pool, hops + 3, idx)
            chain = ents[: hops + 1]
            dist = ents[hops + 1 :]
            base_pairs = [(chain[j], chain[j + 1]) for j in range(1, hops)] + [(dist[0], dist[1])]
            rng.shuffle(base_pairs)
            mem = dict(base_pairs)
            mem[chain[0]] = chain[1]
            cur = chain[0]
            for _ in range(hops):
                cur = mem[cur]
            base_str = " ; ".join(f"{a} -> {b}" for a, b in base_pairs)
            inp = f"base: {base_str} | learn: {chain[0]} -> {chain[1]} | chain_query {chain[0]} ?"
            return "AL_TR_03", inp, cur, hops, 2, True
        ents = sample_entities(rng, pool, 6, idx)
        k1, v1, k2, v2, k3, v3 = ents
        mem = {k1: v1, k2: v2, k3: v3}
        del mem[k1]
        base_clauses = [f"{k1} -> {v1}", f"{k2} -> {v2}", f"{k3} -> {v3}"]
        rng.shuffle(base_clauses)
        inp = f"base: {' ; '.join(base_clauses)} | retract: {k1} -> {v1} | query {k1} ?"
        return "AL_TR_04", inp, mem.get(k1, "unknown"), 1, 2, False

    if split == "val_ood":
        if sub in (0, 1, 3):
            ents = sample_entities(rng, pool, 9, idx)
            pairs = [(ents[0], ents[1]), (ents[2], ents[3]), (ents[4], ents[5]), (ents[6], ents[7])]
            v_new = ents[8]
            mem = dict(pairs)
            shuffled_pairs = list(pairs)
            rng.shuffle(shuffled_pairs)
            init_str = " ; ".join(f"{a} := {b}" for a, b in shuffled_pairs)
            if sub == 3:
                del mem[pairs[0][0]]
                inp = f"init [ {init_str} ] | drop [ {pairs[0][0]} ] >> read {pairs[0][0]}"
                return "AL_VA_OOD_01", inp, mem.get(pairs[0][0], "unknown"), 1, 3, False
            mem[pairs[0][0]] = v_new
            q_key = pairs[0][0] if sub == 0 else pairs[2][0]
            inp = f"init [ {init_str} ] | patch [ {pairs[0][0]} := {v_new} ] >> read {q_key}"
            return "AL_VA_OOD_01", inp, mem[q_key], 1, 3, True
        hops = 4
        ents = sample_entities(rng, pool, hops + 3, idx)
        chain = ents[: hops + 1]
        dist = ents[hops + 1 :]
        base_pairs = [(chain[j], chain[j + 1]) for j in range(1, hops)] + [(dist[0], dist[1])]
        rng.shuffle(base_pairs)
        mem = dict(base_pairs)
        mem[chain[0]] = chain[1]
        cur = chain[0]
        for _ in range(hops):
            cur = mem[cur]
        base_str = " ; ".join(f"{a} := {b}" for a, b in base_pairs)
        inp = f"prior {{ {base_str} }} | revise {{ {chain[0]} := {chain[1]} }} >> trace_chain {chain[0]}"
        return "AL_VA_OOD_02", inp, cur, hops, 2, True

    # test_ood
    if sub in (0, 1, 3):
        ents = sample_entities(rng, pool, 9, idx)
        pairs = [(ents[0], ents[1]), (ents[2], ents[3]), (ents[4], ents[5]), (ents[6], ents[7])]
        v_new = ents[8]
        mem = dict(pairs)
        shuffled_pairs = list(pairs)
        rng.shuffle(shuffled_pairs)
        init_str = " , ".join(f"{a} maps {b}" for a, b in shuffled_pairs)
        if sub == 3:
            del mem[pairs[0][0]]
            inp = f"memory_init ( {init_str} ) | erase ( {pairs[0][0]} ) :: state_of {pairs[0][0]}"
            return "AL_TE_OOD_01", inp, mem.get(pairs[0][0], "unknown"), 1, 3, False
        mem[pairs[0][0]] = v_new
        q_key = pairs[0][0] if sub == 0 else pairs[1][0]
        inp = f"memory_init ( {init_str} ) | delta ( {pairs[0][0]} maps {v_new} ) :: state_of {q_key}"
        return "AL_TE_OOD_01", inp, mem[q_key], 1, 3, True
    hops = 4 if idx % 2 == 0 else 5
    ents = sample_entities(rng, pool, hops + 3, idx)
    chain = ents[: hops + 1]
    dist = ents[hops + 1 :]
    base_pairs = [(chain[j], chain[j + 1]) for j in range(1, hops)] + [(dist[0], dist[1])]
    rng.shuffle(base_pairs)
    mem = dict(base_pairs)
    mem[chain[0]] = chain[1]
    cur = chain[0]
    for _ in range(hops):
        cur = mem[cur]
    base_str = " , ".join(f"{a} maps {b}" for a, b in base_pairs)
    inp = f"store < {base_str} > | amend < {chain[0]} maps {chain[1]} > :: follow_chain {chain[0]}"
    return "AL_TE_OOD_02", inp, cur, hops, 2, True


def make_knowledge_integration(
    rng: random.Random, pool: list[str], split: str, idx: int
) -> tuple[str, str, str, int, int, bool]:
    # 0: consistent synthesis -> entity, 1: conflict (fact vs obs), 2: cycle conflict vs consistent/false equivalence
    sub = idx % 3
    if split in ("train", "val_unseen", "test_unseen"):
        if sub == 0:
            # Override vs synthesis -> entity target
            ents = sample_entities(rng, pool, 7, idx)
            a, b, c, d, e, f, g = ents
            inp = f"fact: {a} -> {b} ; {c} -> {d} | obs: {e} -> {f} | update: {a} -> {g} | integrate {a} ?"
            return "KI_TR_01", inp, g, 1, 3, True
        if sub == 1:
            # Direct conflict between fact and obs (no update) -> conflict
            ents = sample_entities(rng, pool, 6, idx)
            a, b, c, d, e, f = ents
            if idx % 2 == 0:
                inp = f"fact: {a} -> {b} ; {c} -> {d} | obs: {a} -> {e} ; {f} -> {c} | integrate {a} ?"
            else:
                inp = f"fact: {a} = {b} ; {b} = {c} | obs: {a} neq {c} ; {d} = {e} | integrate {a} , {c} ?"
            return "KI_TR_02", inp, "conflict", 2, 2, False
        # sub == 2: cycle conflict vs true vs false
        ents = sample_entities(rng, pool, 5, idx)
        a, b, c, d, e = ents
        mode3 = (idx // 3) % 3
        if mode3 == 0:
            gt_edges = [(a, b), (b, c), (c, a)]
            rel = solve_relation_graph(gt_edges, [], a, c)
            inp = f"fact: {a} > {b} ; {d} > {e} | obs: {b} > {c} | rule: {c} > {a} | integrate {a} , {c} ?"
            return "KI_TR_03", inp, rel, 3, 2, False
        if mode3 == 1:
            inp = f"fact: {a} = {b} ; {d} = {e} | obs: {b} = {c} | rule: {a} = {c} | integrate {a} , {c} ?"
            return "KI_TR_03", inp, "true", 2, 2, False
        inp = f"fact: {a} > {b} ; {d} > {e} | obs: {b} > {c} | rule: {c} > {a} ? | check {c} > {a} ?"
        return "KI_TR_03", inp, "false", 2, 2, False

    if split == "val_ood":
        if sub == 0:
            ents = sample_entities(rng, pool, 8, idx)
            a, b, c, d, e, f, g, h = ents
            inp = f"src1 [ {a} := {b} ; {c} := {d} ] ; src2 [ {e} := {f} ] ; patch [ {a} := {g} ; {h} := {c} ] >> reconcile {a}"
            return "KI_VA_OOD_01", inp, g, 1, 4, True
        if sub == 1:
            ents = sample_entities(rng, pool, 6, idx)
            a, b, c, d, e, f = ents
            inp = f"src1 [ {a} := {b} ; {c} := {d} ] ; src2 [ {a} := {e} ; {f} := {c} ] >> reconcile {a}"
            return "KI_VA_OOD_01", inp, "conflict", 2, 3, False
        ents = sample_entities(rng, pool, 7, idx)
        a, b, c, d, e, f, g = ents
        mode3 = (idx // 3) % 3
        if mode3 == 0:
            inp = f"stream_a {{ {a} gt {b} ; {b} gt {c} ; {f} gt {g} }} ; stream_b {{ {c} gt {d} ; {d} gt {a} ; {e} gt {f} }} >> check_consistency {a} , {d}"
            return "KI_VA_OOD_02", inp, "conflict", 4, 3, False
        if mode3 == 1:
            inp = f"stream_a {{ {a} eq {b} ; {b} eq {c} ; {f} eq {g} }} ; stream_b {{ {c} eq {d} ; {d} eq {e} }} >> check_consistency {a} , {e}"
            return "KI_VA_OOD_02", inp, "true", 4, 2, False
        inp = f"stream_a {{ {a} gt {b} ; {b} gt {c} ; {f} gt {g} }} ; stream_b {{ {c} gt {d} ; {d} gt {e} }} >> check_order {e} gt {a}"
        return "KI_VA_OOD_02", inp, "false", 4, 2, False

    # test_ood
    if sub == 0:
        ents = sample_entities(rng, pool, 8, idx)
        a, b, c, d, e, f, g, h = ents
        inp = f"feed_1 ( {a} maps {b} , {c} maps {d} ) & feed_2 ( {e} maps {f} ) & amend ( {a} maps {g} , {h} maps {d} ) :: unify {a}"
        return "KI_TE_OOD_01", inp, g, 1, 4, True
    if sub == 1:
        ents = sample_entities(rng, pool, 6, idx)
        a, b, c, d, e, f = ents
        inp = f"feed_1 ( {a} maps {b} , {c} maps {d} ) & feed_2 ( {a} maps {e} , {f} maps {c} ) :: unify {a}"
        return "KI_TE_OOD_01", inp, "conflict", 2, 3, False
    ents = sample_entities(rng, pool, 8, idx)
    a, b, c, d, e, f, g, h = ents
    mode3 = (idx // 3) % 3
    if mode3 == 0:
        inp = f"report_x < {a} beats {b} ; {b} beats {c} ; {g} beats {h} > & report_y < {c} beats {d} ; {d} beats {e} ; {e} beats {a} > :: adjudicate {a} , {e}"
        return "KI_TE_OOD_02", inp, "conflict", 5, 2, False
    if mode3 == 1:
        inp = f"report_x < {a} matches {b} ; {b} matches {c} ; {g} matches {h} > & report_y < {c} matches {d} ; {d} matches {e} ; {e} matches {f} > :: adjudicate {a} , {f}"
        return "KI_TE_OOD_02", inp, "true", 5, 2, False
    inp = f"report_x < {a} beats {b} ; {b} beats {c} ; {g} beats {h} > & report_y < {c} beats {d} ; {d} beats {e} ; {e} beats {f} > :: adjudicate_gt {f} beats {a}"
    return "KI_TE_OOD_02", inp, "false", 5, 2, False


def make_generalization(
    rng: random.Random, pool: list[str], split: str, idx: int
) -> tuple[str, str, str, int, int, bool]:
    # Compositional multi-skill: 0 -> verify after update (true/false), 1 -> update + multi-hop trace (entity), 2 -> conflict vs plan compose
    sub = idx % 3
    if split in ("train", "val_unseen", "test_unseen"):
        if sub == 0:
            ents = sample_entities(rng, pool, 6, idx)
            a, b, c, d, e, f = ents
            if idx % 2 == 0:
                inp = f"base: {a} > {b} ; {d} > {e} | update: {b} > {c} ; {e} > {f} | verify {a} > {c} ?"
                tgt = "true"
            else:
                inp = f"base: {a} > {b} ; {d} > {e} | update: {b} > {c} ; {e} > {f} | verify {c} > {a} ?"
                tgt = "false"
            return "GN_TR_01", inp, tgt, 2, 2, False
        if sub == 1:
            ents = sample_entities(rng, pool, 6, idx)
            a, b, c, d, e, f = ents
            inp = f"base: {a} -> {b} ; {b} -> {c} ; {d} -> {e} | update: {b} -> {f} | chain: {f} -> {d} | trace {a} ?"
            return "GN_TR_02", inp, d, 3, 2, True
        ents = sample_entities(rng, pool, 5, idx)
        a, b, c, d, e = ents
        if idx % 2 == 0:
            deps = [(d, c), (c, b), (b, a), (e, d)]
            _, tgt = solve_topological_plan(d, deps, set())
            inp = f"goal: {d} | base_deps: {d} after {c} , {c} after {b} , {e} after {d} | add_dep: {b} after {a} | plan ?"
            return "GN_TR_03", inp, tgt, 3, 1, True
        inp = f"goal: {d} | base_deps: {d} after {c} , {c} after {b} , {e} after {d} | add_dep: {b} after {d} | plan ?"
        return "GN_TR_03", inp, "impossible", 3, 1, False

    if split == "val_ood":
        if sub == 0:
            ents = sample_entities(rng, pool, 7, idx)
            a, b, c, d, e, f, g = ents
            if idx % 2 == 0:
                inp = f"context [ {a} gt {b} ; {b} gt {c} ; {f} gt {g} ] ; patch [ {c} gt {d} ; {d} gt {e} ] >> prove {a} gt {e}"
                tgt = "true"
            else:
                inp = f"context [ {a} gt {b} ; {b} gt {c} ; {f} gt {g} ] ; patch [ {c} gt {d} ; {d} gt {e} ] >> prove {e} gt {a}"
                tgt = "false"
            return "GN_VA_OOD_01", inp, tgt, 4, 2, False
        if sub == 1:
            ents = sample_entities(rng, pool, 7, idx)
            a, b, c, d, e, f, g = ents
            inp = f"state {{ {a} := {b} ; {b} := {c} ; {c} := {d} }} ; new_rule {{ {c} := {e} ; {e} := {f} ; {f} := {g} }} >> compose_trace {a}"
            return "GN_VA_OOD_02", inp, g, 4, 1, True
        ents = sample_entities(rng, pool, 6, idx)
        a, b, c, d, e, f = ents
        if idx % 2 == 0:
            deps = [(e, d), (d, c), (c, b), (b, a), (f, e)]
            _, tgt = solve_topological_plan(e, deps, set())
            inp = f"state {{ target {e} ; {e} needs {d} ; {d} needs {c} ; {f} needs {e} }} ; new_rule {{ {c} needs {b} ; {b} needs {a} }} >> compose_plan {e}"
            return "GN_VA_OOD_02", inp, tgt, 4, 1, True
        inp = f"state {{ target {e} ; {e} needs {d} ; {d} needs {c} ; {f} needs {e} }} ; new_rule {{ {c} needs {e} ; {b} needs {a} }} >> compose_plan {e}"
        return "GN_VA_OOD_02", inp, "impossible", 4, 1, False

    # test_ood: 4-5 hops
    if sub == 0:
        ents = sample_entities(rng, pool, 8, idx)
        a, b, c, d, e, f, g, h = ents
        if idx % 2 == 0:
            inp = f"world ( {a} beats {b} ; {b} beats {c} ; {c} beats {d} ; {g} beats {h} ) + change ( {d} beats {e} ; {e} beats {f} ) :: validate {a} beats {f}"
            tgt = "true"
        else:
            inp = f"world ( {a} beats {b} ; {b} beats {c} ; {c} beats {d} ; {g} beats {h} ) + change ( {d} beats {e} ; {e} beats {f} ) :: validate {f} beats {a}"
            tgt = "false"
        return "GN_TE_OOD_01", inp, tgt, 5, 2, False
    if sub == 1:
        ents = sample_entities(rng, pool, 8, idx)
        a, b, c, d, e, f, g, h = ents
        inp = f"kb < {a} maps {b} , {b} maps {c} , {c} maps {d} , {d} maps {e} > + shift < {d} maps {f} , {f} maps {g} , {g} maps {h} > :: derive {a}"
        return "GN_TE_OOD_02", inp, h, 5, 1, True
    ents = sample_entities(rng, pool, 7, idx)
    a, b, c, d, e, f, g = ents
    if idx % 2 == 0:
        deps = [(f, e), (e, d), (d, c), (c, b), (b, a), (g, f)]
        _, tgt = solve_topological_plan(f, deps, set())
        inp = f"kb < goal {f} , {f} requires {e} , {e} requires {d} , {d} requires {c} , {g} requires {f} > + shift < {c} requires {b} , {b} requires {a} > :: derive_plan {f}"
        return "GN_TE_OOD_02", inp, tgt, 5, 1, True
    inp = f"kb < goal {f} , {f} requires {e} , {e} requires {d} , {d} requires {c} , {g} requires {f} > + shift < {c} requires {f} , {b} requires {a} > :: derive_plan {f}"
    return "GN_TE_OOD_02", inp, "impossible", 5, 1, False


BUILDERS = {
    "native_representation": make_native_representation,
    "knowledge_acquisition": make_knowledge_acquisition,
    "relational_reasoning": make_relational_reasoning,
    "planning_decomposition": make_planning_decomposition,
    "verification": make_verification,
    "adaptive_learning": make_adaptive_learning,
    "knowledge_integration": make_knowledge_integration,
    "generalization": make_generalization,
}


def generate_dataset(seed: int) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    by_split: dict[str, list[dict]] = {split: [] for split in SPLIT_PER_CAP}
    seen_norm_inputs: set[str] = set()

    for cap in CAPABILITIES:
        builder = BUILDERS[cap]
        prefix = CAP_PREFIX[cap]
        for split, count in SPLIT_PER_CAP.items():
            pool = ENTITY_POOLS[SPLIT_TO_POOL[split]]
            for i in range(count):
                # Retry deterministic salt if normalized input ever collides
                attempt = 0
                while True:
                    ex_rng = random.Random(f"{seed}:{cap}:{split}:{i}:{attempt}")
                    tmpl_id, inp, tgt, hop_depth, dist_cnt, is_ent_tgt = builder(
                        ex_rng, pool, split, i + attempt * count
                    )
                    norm = " ".join(inp.lower().split())
                    if norm not in seen_norm_inputs:
                        seen_norm_inputs.add(norm)
                        break
                    attempt += 1
                    if attempt > 25:
                        raise RuntimeError(f"Failed to produce unique input for {cap}/{split}/{i}")

                abs_pat = f"{cap}::{canonicalize_abstract_pattern(inp)}"
                sig = f"{cap}::{tmpl_id}::{canonicalize_abstract_pattern(inp)}"
                ents_used = extract_entities(inp + " " + tgt)
                if not tgt.strip():
                    raise ValueError(f"Empty target generated for {cap}/{split}/{i}")
                if len(inp.split()) > 220 or len(tgt.split()) > 64:
                    raise ValueError(f"Token budget exceeded for {cap}/{split}/{i}: {len(inp.split())}")

                by_split[split].append(
                    {
                        "id": f"{prefix}-{split}-{i:04d}",
                        "capability": cap,
                        "split": split,
                        "template_id": tmpl_id,
                        "structural_signature": sig,
                        "abstract_pattern": abs_pat,
                        "hop_depth": hop_depth,
                        "distractor_count": dist_cnt,
                        "entities_used": ents_used,
                        "entity_target": bool(is_ent_tgt),
                        "input": inp,
                        "target": tgt,
                        "provenance": PROVENANCE,
                        "seed": seed,
                    }
                )
    # Deterministic per-split shuffle for train so batches aren't grouped by capability
    rng.shuffle(by_split["train"])
    return by_split


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate ZYRQUEN v9 dataset (Step 1)")
    ap.add_argument("--out", default="data/nagi_v9", help="Output directory")
    ap.add_argument("--seed", type=int, default=42, help="Deterministic generation seed")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    by_split = generate_dataset(args.seed)

    files: dict[str, dict] = {}
    for split, rows in by_split.items():
        p = out / f"{split}.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        files[f"{split}.jsonl"] = {
            "path": str(p),
            "count": len(rows),
            "sha256": sha256_file(p),
        }

    per_capability: dict[str, dict[str, int]] = {}
    for cap in CAPABILITIES:
        cap_counts = {
            split: sum(1 for r in rows if r["capability"] == cap)
            for split, rows in by_split.items()
        }
        cap_counts["total"] = sum(cap_counts.values())
        per_capability[cap] = cap_counts

    manifest = {
        "generator": GENERATOR_VERSION,
        "version": "v9",
        "seed": args.seed,
        "provenance": PROVENANCE,
        "deterministic": True,
        "total": sum(len(rows) for rows in by_split.values()),
        "per_split": {split: len(rows) for split, rows in by_split.items()},
        "per_capability": per_capability,
        "entity_pools": {
            "train_count": len(ENTITY_POOLS["train"]),
            "val_count": len(ENTITY_POOLS["val"]),
            "test_count": len(ENTITY_POOLS["test"]),
            "formats_per_pool": 5,
        },
        "files": files,
    }
    manifest_path = out / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"OK - generated {manifest['total']} examples in {out} (seed={args.seed})")
    for split, count in manifest["per_split"].items():
        print(f"  {split}: {count} (sha256={files[f'{split}.jsonl']['sha256'][:16]}...)")
    print(f"  manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
