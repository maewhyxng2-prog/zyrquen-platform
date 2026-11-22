#!/usr/bin/env python3
"""
ZYRQUEN Ω∞ — NAGI v10 Dataset Generator

Purpose:
  Generate a deterministic, multi-capability symbolic reasoning and
  generalization dataset in data/nagi_v10/ with strict unique-answer
  verification and zero train/validation/test entity or template leakage.

Outputs:
  data/nagi_v10/train.jsonl
  data/nagi_v10/validation.jsonl
  data/nagi_v10/test.jsonl
  data/nagi_v10/manifest.json

Safety:
  - Does not modify v7, v8, or v9 files, datasets, or checkpoints.
  - Does not overwrite an existing v10 dataset directory.
  - Uses only the Python standard library.
  - Does not start model training or evaluation.
  - Dataset is a symbolic benchmark, not proof of general intelligence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "nagi_v10"

GENERATOR_VERSION = "1.0.0"
MANIFEST_SCHEMA = "zyrquen.dataset-manifest.v1"
DATASET_VERSION = "10.0.0"
EXAMPLE_SCHEMA_VERSION = "1.0"
DEFAULT_SEED = 42
MAX_SEQUENCE_TOKENS = 250  # <= 256 with <bos>/<eos> margin

SPLITS = ("train", "validation", "test")

DEFAULT_COUNTS = {
    "train": 480,
    "validation": 60,
    "test": 60,
}

CAPABILITIES = (
    "abstract_reasoning",
    "relational_generalization",
    "ood_transfer",
    "multi_step_planning",
    "self_verification",
    "knowledge_integration",
)

# Each split uses disjoint entity prefixes/markers across 5 distinct formats.
ENTITY_FORMAT_TEMPLATES: dict[str, tuple[str, ...]] = {
    "train": (
        "TR_E{code}",
        "node_tr_{code}",
        "item_tr_{code}",
        "step_tr_{code}",
        "rec_tr_e{code}",
    ),
    "validation": (
        "VA_E{code}",
        "node_va_{code}",
        "item_va_{code}",
        "step_va_{code}",
        "rec_va_e{code}",
    ),
    "test": (
        "TE_E{code}",
        "node_te_{code}",
        "item_te_{code}",
        "step_te_{code}",
        "rec_te_e{code}",
    ),
}

ENTITY_TOKEN_RE = re.compile(
    r"^(?:(?:TR|VA|TE)_E\d+|(?:node|item|step)_(?:tr|va|te)_\d+|rec_(?:tr|va|te)_e\d+)$"
)

# Disjoint instruction templates per (split, capability) so template_id and
# raw phrasing never overlap across train, validation, and test.
TEMPLATES: dict[str, dict[str, list[str]]] = {
    "train": {
        "abstract_reasoning": [
            "Determine the strict order relation between the queried entities.",
            "Infer whether the left entity is above, below, or unrelated to the right entity.",
        ],
        "relational_generalization": [
            "Follow the linked_to relations for exact hops to find the destination.",
            "Determine the single entity reached after the specified number of links.",
        ],
        "ood_transfer": [
            "Traverse the connects_to links over the given hop depth.",
            "Resolve the target node reachable along connects_to in exact steps.",
        ],
        "multi_step_planning": [
            "Produce the unique ordered action sequence required to reach the goal.",
            "Order all prerequisite steps needed to complete the target objective.",
        ],
        "self_verification": [
            "Verify whether the proposed claim or plan is consistent with the evidence.",
            "Check the given assertion or route against all listed constraints.",
        ],
        "knowledge_integration": [
            "Combine base records, updates, and observations to resolve the query.",
            "Reconcile all knowledge entries and output the resolved value or conflict.",
        ],
    },
    "validation": {
        "abstract_reasoning": [
            "Evaluate the transitive dominance graph and report the comparison symbol.",
            "Resolve the ordering relationship from the acyclic comparison pairs.",
        ],
        "relational_generalization": [
            "Trace the directed connection graph for the exact hop count and return the endpoint.",
            "Identify the unique terminal entity reached by the multi-hop link chain.",
        ],
        "ood_transfer": [
            "Execute four-step routes_to composition and return the destination entity.",
            "Track routes_to edges through four transitions to pinpoint the endpoint.",
        ],
        "multi_step_planning": [
            "Compute the complete prerequisite execution chain ending at the goal step.",
            "Derive the valid topological sequence that satisfies all goal dependencies.",
        ],
        "self_verification": [
            "Audit the stated hypothesis or step sequence using the provided facts.",
            "Inspect the candidate claim or plan and classify its validity status.",
        ],
        "knowledge_integration": [
            "Merge primary facts with revision updates and check for contradiction.",
            "Synthesize the multi-source ledger entries to determine the final state.",
        ],
    },
    "test": {
        "abstract_reasoning": [
            "Establish the comparative ordering outcome for the target entity pair.",
            "Deduce whether the first entity outranks, trails, or is incomparable to the second.",
        ],
        "relational_generalization": [
            "Compose the directed linked_to transitions to locate the exact-hop endpoint.",
            "Resolve the full relational path from the source node at the requested depth.",
        ],
        "ood_transfer": [
            "Propagate across five transfers_to transitions to isolate the final node.",
            "Compute the unique five-hop transfers_to destination from the initial entity.",
        ],
        "multi_step_planning": [
            "Synthesize the minimal dependency-ordered plan that achieves the goal.",
            "Construct the exact step ordering required by the goal dependency closure.",
        ],
        "self_verification": [
            "Adjudicate the proposed statement or execution plan against ground evidence.",
            "Assess consistency of the candidate assertion or plan under the given rules.",
        ],
        "knowledge_integration": [
            "Integrate baseline assertions, amendments, and sensor reports for the query.",
            "Determine the authoritative target or detect conflict across combined sources.",
        ],
    },
}

OOD_DEPTH_AND_RELATION: dict[str, tuple[int, str]] = {
    "train": (2, "connects_to"),
    "validation": (4, "routes_to"),
    "test": (5, "transfers_to"),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_entity(split: str, example_index: int, node_index: int) -> str:
    formats = ENTITY_FORMAT_TEMPLATES[split]
    fmt = formats[(example_index + node_index) % len(formats)]
    code = f"{example_index:04d}{node_index:02d}"
    return fmt.format(code=code)


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


# ---------------------------------------------------------------------------
# Exhaustive unique-answer solvers (used both at generation & independent audit)
# ---------------------------------------------------------------------------


def solve_exact_hop_path(
    facts: list[dict[str, Any]],
    relation: str,
    start: str,
    hops: int,
) -> dict[str, Any]:
    """Compute exact-hop walk counts and shortest distances from start."""
    adjacency: dict[str, list[str]] = {}
    for fact in facts:
        if fact.get("relation") == relation:
            adjacency.setdefault(str(fact["source"]), []).append(str(fact["target"]))

    walk_counts: dict[str, int] = {start: 1}
    visited_earlier: set[str] = {start}
    shortcut_targets: set[str] = set()

    for hop_idx in range(1, hops + 1):
        next_counts: dict[str, int] = {}
        for node, cnt in walk_counts.items():
            for nxt in adjacency.get(node, ()):
                next_counts[nxt] = next_counts.get(nxt, 0) + cnt
        walk_counts = next_counts
        if hop_idx < hops:
            shortcut_targets.update(walk_counts.keys())
            visited_earlier.update(walk_counts.keys())

    endpoints = sorted(walk_counts.keys())
    return {
        "endpoints": endpoints,
        "walk_counts": walk_counts,
        "shortcut_targets": shortcut_targets,
    }


def solve_order_dag(
    facts: list[dict[str, Any]],
    left: str,
    right: str,
) -> dict[str, Any]:
    """Verify acyclicity and compute unique order relation between left and right."""
    adj: dict[str, set[str]] = {}
    nodes: set[str] = set()
    for fact in facts:
        if fact.get("relation") == "greater_than":
            src = str(fact["source"])
            dst = str(fact["target"])
            adj.setdefault(src, set()).add(dst)
            nodes.add(src)
            nodes.add(dst)

    # Detect cycles via DFS 3-color marking
    color: dict[str, int] = {}
    has_cycle = False

    def dfs(u: str) -> None:
        nonlocal has_cycle
        color[u] = 1
        for v in adj.get(u, ()):
            if color.get(v, 0) == 1:
                has_cycle = True
                return
            if color.get(v, 0) == 0:
                dfs(v)
                if has_cycle:
                    return
        color[u] = 2

    for n in sorted(nodes):
        if color.get(n, 0) == 0:
            dfs(n)
            if has_cycle:
                break

    def reachable(src: str, target: str) -> bool:
        seen = {src}
        q = deque([src])
        while q:
            cur = q.popleft()
            if cur == target and cur != src:
                return True
            for nxt in adj.get(cur, ()):
                if nxt == target:
                    return True
                if nxt not in seen:
                    seen.add(nxt)
                    q.append(nxt)
        return False

    if has_cycle:
        return {"acyclic": False, "answers": []}

    left_gt_right = left != right and reachable(left, right)
    right_gt_left = left != right and reachable(right, left)

    if left_gt_right and right_gt_left:
        return {"acyclic": False, "answers": []}
    if left_gt_right:
        return {"acyclic": True, "answers": [">"]}
    if right_gt_left:
        return {"acyclic": True, "answers": ["<"]}
    return {"acyclic": True, "answers": ["unknown"]}


def solve_unique_plan(
    facts: list[dict[str, Any]],
    goal: str,
) -> dict[str, Any]:
    """Solve prerequisite closure for goal and verify a unique topological plan or cycle."""
    # fact: source requires target (target must precede source)
    prereqs_of: dict[str, set[str]] = {}
    for fact in facts:
        if fact.get("relation") == "requires":
            step = str(fact["source"])
            prereq = str(fact["target"])
            prereqs_of.setdefault(step, set()).add(prereq)

    closure: set[str] = {goal}
    q = deque([goal])
    while q:
        cur = q.popleft()
        for pre in prereqs_of.get(cur, ()):
            if pre not in closure:
                closure.add(pre)
                q.append(pre)

    # Build forward edges prereq -> step restricted to closure
    fwd: dict[str, set[str]] = {n: set() for n in closure}
    indeg: dict[str, int] = {n: 0 for n in closure}
    for node in closure:
        for pre in prereqs_of.get(node, ()):
            if pre in closure and node not in fwd[pre]:
                fwd[pre].add(node)
                indeg[node] += 1

    ready = sorted(n for n, d in indeg.items() if d == 0)
    order: list[str] = []
    ambiguous = False
    while ready:
        if len(ready) != 1:
            ambiguous = True
            break
        cur = ready.pop(0)
        order.append(cur)
        for nxt in sorted(fwd[cur]):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
        ready.sort()

    if ambiguous:
        return {"unique": False, "answers": []}
    if len(order) != len(closure):
        return {"unique": True, "answers": ["impossible"]}
    return {"unique": True, "answers": [" -> ".join(order)]}


def solve_verification(
    facts: list[dict[str, Any]],
    query: dict[str, Any],
) -> dict[str, Any]:
    subtype = query.get("subtype")
    if subtype == "claim_check":
        res = solve_order_dag(facts, str(query["left"]), str(query["right"]))
        if not res["acyclic"] or len(res["answers"]) != 1:
            return {"unique": False, "answers": []}
        actual = res["answers"][0]
        claimed = str(query["claimed_relation"])
        if actual == "unknown":
            return {"unique": True, "answers": ["unknown"]}
        return {"unique": True, "answers": ["true" if actual == claimed else "false"]}

    if subtype == "plan_check":
        goal = str(query["goal"])
        proposed = [str(s) for s in query["proposed_plan"]]
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

        plan_res = solve_unique_plan(facts, goal)
        if plan_res["answers"] == ["impossible"]:
            return {"unique": True, "answers": ["invalid_cycle"]}

        if len(proposed) != len(set(proposed)) or set(proposed) != closure:
            return {"unique": True, "answers": ["invalid_missing"]}

        pos = {step: idx for idx, step in enumerate(proposed)}
        for step in closure:
            for pre in prereqs_of.get(step, ()):
                if pos[pre] >= pos[step]:
                    return {"unique": True, "answers": ["invalid_order"]}

        return {"unique": True, "answers": ["valid"]}

    return {"unique": False, "answers": []}


def solve_knowledge_integration(
    facts: list[dict[str, Any]],
    query: dict[str, Any],
) -> dict[str, Any]:
    target_entity = str(query["entity"])
    base_map: dict[str, str] = {}
    updates: list[tuple[str, str]] = []
    primary_fact_vals: set[str] = set()
    obs_vals: set[str] = set()

    for fact in facts:
        rel = fact.get("relation")
        src = str(fact["source"])
        dst = str(fact["target"])
        if rel == "base_maps_to":
            base_map[src] = dst
        elif rel == "update_maps_to":
            updates.append((src, dst))
        elif rel == "assert_maps_to" and src == target_entity:
            primary_fact_vals.add(dst)
        elif rel == "observe_maps_to" and src == target_entity:
            obs_vals.add(dst)

    if primary_fact_vals or obs_vals:
        combined = primary_fact_vals | obs_vals
        if len(combined) > 1:
            return {"unique": True, "answers": ["conflict"]}
        if len(combined) == 1:
            return {"unique": True, "answers": [next(iter(combined))]}
        return {"unique": False, "answers": []}

    state = dict(base_map)
    for src, dst in updates:
        state[src] = dst
    if target_entity not in state:
        return {"unique": True, "answers": ["unknown"]}
    return {"unique": True, "answers": [state[target_entity]]}


def verify_unique_answer(example: dict[str, Any]) -> tuple[bool, str]:
    cap = example.get("capability")
    facts = example.get("facts", [])
    query = example.get("query", {})
    answer = str(example.get("answer", ""))

    if cap in ("relational_generalization", "ood_transfer"):
        relation = str(query.get("relation", ""))
        start = str(query.get("source", ""))
        hops = int(query.get("hops", 0))
        res = solve_exact_hop_path(facts, relation, start, hops)
        endpoints = res["endpoints"]
        if len(endpoints) != 1 or endpoints[0] != answer:
            return False, f"non-unique or mismatched hop endpoints: {endpoints}"
        if res["walk_counts"].get(answer) != 1:
            return False, f"multiple {hops}-hop walks to {answer}"
        if answer in res["shortcut_targets"]:
            return False, f"shortcut path < {hops} hops exists to {answer}"
        return True, "ok"

    if cap == "abstract_reasoning":
        res = solve_order_dag(facts, str(query.get("left", "")), str(query.get("right", "")))
        if not res["acyclic"]:
            return False, "order graph contains cycle"
        if res["answers"] != [answer]:
            return False, f"order solver expected {res['answers']}, got {answer}"
        return True, "ok"

    if cap == "multi_step_planning":
        res = solve_unique_plan(facts, str(query.get("goal", "")))
        if not res["unique"] or res["answers"] != [answer]:
            return False, f"plan solver expected {res}, got {answer}"
        return True, "ok"

    if cap == "self_verification":
        res = solve_verification(facts, query)
        if not res["unique"] or res["answers"] != [answer]:
            return False, f"verification solver expected {res}, got {answer}"
        return True, "ok"

    if cap == "knowledge_integration":
        res = solve_knowledge_integration(facts, query)
        if not res["unique"] or res["answers"] != [answer]:
            return False, f"knowledge integration solver expected {res}, got {answer}"
        return True, "ok"

    return False, f"unknown capability: {cap}"


# ---------------------------------------------------------------------------
# Example generators per capability
# ---------------------------------------------------------------------------


def _build_unique_path_facts(
    entities: list[str],
    relation: str,
    hops: int,
    rng: random.Random,
    max_distractors: int = 4,
) -> tuple[list[dict[str, Any]], str, str]:
    path_indices = rng.sample(range(len(entities)), hops + 1)
    path_edges = [(path_indices[i], path_indices[i + 1]) for i in range(hops)]
    edges: set[tuple[int, int]] = set(path_edges)

    start_ent = entities[path_indices[0]]
    answer_ent = entities[path_indices[-1]]

    candidates = [
        (u, v)
        for u in range(len(entities))
        for v in range(len(entities))
        if u != v and (u, v) not in edges
    ]
    rng.shuffle(candidates)

    added = 0
    for u, v in candidates:
        if added >= max_distractors:
            break
        trial_edges = list(edges) + [(u, v)]
        trial_facts = [
            {"relation": relation, "source": entities[s], "target": entities[t]}
            for s, t in trial_edges
        ]
        res = solve_exact_hop_path(trial_facts, relation, start_ent, hops)
        if (
            res["endpoints"] == [answer_ent]
            and res["walk_counts"].get(answer_ent) == 1
            and answer_ent not in res["shortcut_targets"]
        ):
            edges.add((u, v))
            added += 1

    edge_list = list(edges)
    rng.shuffle(edge_list)
    facts = [
        {"relation": relation, "source": entities[s], "target": entities[t]}
        for s, t in edge_list
    ]
    return facts, start_ent, answer_ent


def _pick_template(split: str, capability: str, rng: random.Random) -> tuple[str, str]:
    pool = TEMPLATES[split][capability]
    t_idx = rng.randrange(len(pool))
    template_id = f"{split}_{capability}_t{t_idx:02d}"
    return template_id, pool[t_idx]


def generate_example(
    split: str,
    example_index: int,
    rng: random.Random,
    seed: int,
) -> dict[str, Any]:
    capability = CAPABILITIES[example_index % len(CAPABILITIES)]
    template_id, instruction = _pick_template(split, capability, rng)

    if capability in ("relational_generalization", "ood_transfer"):
        if capability == "relational_generalization":
            hops = 3
            relation = "linked_to"
            node_count = 8
            task_type = "relational_chain"
            operator = "directed_path_composition"
            split_tag = "rel"
        else:
            hops, relation = OOD_DEPTH_AND_RELATION[split]
            node_count = max(8, hops + 4)
            task_type = "ood_relational_chain"
            operator = f"ood_{hops}hop_{relation}"
            split_tag = f"ood_{split}_{hops}h"

        entities = [make_entity(split, example_index, i) for i in range(node_count)]
        facts, start_ent, answer = _build_unique_path_facts(entities, relation, hops, rng)
        query: dict[str, Any] = {"relation": relation, "source": start_ent, "hops": hops}
        fact_str = " ; ".join(f"{f['source']} {relation} {f['target']}" for f in facts)
        input_text = f"{instruction} | {split_tag}: {fact_str} | query {start_ent} hops {hops} ?"

    elif capability == "abstract_reasoning":
        entities = [make_entity(split, example_index, i) for i in range(6)]
        order_nodes = rng.sample(entities, 6)
        chain_a = order_nodes[:4]
        chain_b = order_nodes[4:]
        raw_edges = [
            (chain_a[0], chain_a[1]),
            (chain_a[1], chain_a[2]),
            (chain_a[2], chain_a[3]),
            (chain_b[0], chain_b[1]),
        ]
        rng.shuffle(raw_edges)
        facts = [
            {"relation": "greater_than", "source": u, "target": v}
            for u, v in raw_edges
        ]
        mode = example_index % 3
        if mode == 0:
            left, right, answer = chain_a[0], chain_a[3], ">"
        elif mode == 1:
            left, right, answer = chain_a[3], chain_a[1], "<"
        else:
            left, right, answer = chain_a[1], chain_b[0], "unknown"
        query = {"relation": "compare", "left": left, "right": right}
        task_type = "ordered_comparison"
        operator = "transitive_order_inference"
        fact_str = " , ".join(f"{f['source']} > {f['target']}" for f in facts)
        input_text = f"{instruction} | order_{split}: {fact_str} | compare {left} ? {right}"

    elif capability == "multi_step_planning":
        entities = [make_entity(split, example_index, i) for i in range(7)]
        shuffled = rng.sample(entities, 7)
        chain = shuffled[:4]  # chain[0] -> chain[1] -> chain[2] -> chain[3]=goal
        distractors = shuffled[4:]
        goal = chain[-1]

        # Build prerequisite edges: step requires prereq
        req_edges = [
            (chain[1], chain[0]),
            (chain[2], chain[1]),
            (chain[3], chain[2]),
            # Distractor downstream of goal + independent distractor pair (never ancestors of goal)
            (distractors[0], goal),
            (distractors[2], distractors[1]),
        ]
        make_cycle = (example_index % 4 == 3)
        if make_cycle:
            req_edges.append((chain[0], chain[2]))
            answer = "impossible"
        else:
            answer = " -> ".join(chain)

        rng.shuffle(req_edges)
        facts = [
            {"relation": "requires", "source": step, "target": pre}
            for step, pre in req_edges
        ]
        query = {"relation": "plan_for", "goal": goal}
        task_type = "dependency_planning"
        operator = "topological_plan_resolution"
        fact_str = " , ".join(f"{f['source']} requires {f['target']}" for f in facts)
        input_text = f"{instruction} | plan_{split}: goal {goal} | deps: {fact_str} ?"

    elif capability == "self_verification":
        if example_index % 2 == 0:
            entities = [make_entity(split, example_index, i) for i in range(5)]
            nodes = rng.sample(entities, 5)
            raw_edges = [(nodes[0], nodes[1]), (nodes[1], nodes[2]), (nodes[3], nodes[4])]
            rng.shuffle(raw_edges)
            facts = [{"relation": "greater_than", "source": u, "target": v} for u, v in raw_edges]
            sub = (example_index // 2) % 3
            if sub == 0:
                left, right, claimed, answer = nodes[0], nodes[2], ">", "true"
            elif sub == 1:
                left, right, claimed, answer = nodes[2], nodes[0], ">", "false"
            else:
                left, right, claimed, answer = nodes[0], nodes[3], ">", "unknown"
            query = {
                "subtype": "claim_check",
                "left": left,
                "right": right,
                "claimed_relation": claimed,
            }
            fact_str = " , ".join(f"{f['source']} > {f['target']}" for f in facts)
            input_text = f"{instruction} | verify_claim_{split}: {left} {claimed} {right} | facts: {fact_str} ?"
        else:
            entities = [make_entity(split, example_index, i) for i in range(5)]
            nodes = rng.sample(entities, 5)
            chain = nodes[:3]
            goal = chain[-1]
            req_edges = [(chain[1], chain[0]), (chain[2], chain[1]), (nodes[3], nodes[4])]
            sub = (example_index // 2) % 4
            if sub == 0:
                proposed = list(chain)
                answer = "valid"
            elif sub == 1:
                proposed = [chain[1], chain[0], chain[2]]
                answer = "invalid_order"
            elif sub == 2:
                proposed = [chain[1], chain[2]]
                answer = "invalid_missing"
            else:
                req_edges.append((chain[0], chain[1]))
                proposed = list(chain)
                answer = "invalid_cycle"
            rng.shuffle(req_edges)
            facts = [{"relation": "requires", "source": s, "target": p} for s, p in req_edges]
            query = {"subtype": "plan_check", "goal": goal, "proposed_plan": proposed}
            fact_str = " , ".join(f"{f['source']} requires {f['target']}" for f in facts)
            plan_str = " -> ".join(proposed)
            input_text = f"{instruction} | verify_plan_{split}: {plan_str} | goal {goal} | deps: {fact_str} ?"

        task_type = "claim_and_plan_verification"
        operator = "consistency_verification"

    else:  # knowledge_integration
        entities = [make_entity(split, example_index, i) for i in range(7)]
        keys = entities[:3]
        vals = entities[3:]
        sub = example_index % 3
        if sub == 0:
            # Update overrides base
            facts = [
                {"relation": "base_maps_to", "source": keys[0], "target": vals[0]},
                {"relation": "base_maps_to", "source": keys[1], "target": vals[1]},
                {"relation": "update_maps_to", "source": keys[0], "target": vals[2]},
            ]
            answer = vals[2]
        elif sub == 1:
            # Selective retention (unrelated key updated)
            facts = [
                {"relation": "base_maps_to", "source": keys[0], "target": vals[0]},
                {"relation": "base_maps_to", "source": keys[1], "target": vals[1]},
                {"relation": "update_maps_to", "source": keys[1], "target": vals[2]},
            ]
            answer = vals[0]
        else:
            # Conflict between primary assertion and observation
            facts = [
                {"relation": "assert_maps_to", "source": keys[0], "target": vals[0]},
                {"relation": "observe_maps_to", "source": keys[0], "target": vals[1]},
                {"relation": "base_maps_to", "source": keys[1], "target": vals[2]},
            ]
            answer = "conflict"
        rng.shuffle(facts)
        query = {"relation": "resolve", "entity": keys[0]}
        task_type = "multi_source_reconciliation"
        operator = "belief_revision_and_conflict"
        fact_str = " ; ".join(f"{f['relation']} {f['source']} -> {f['target']}" for f in facts)
        input_text = f"{instruction} | integrate_{split}: {fact_str} | query {keys[0]} ?"

    example = {
        "schema_version": EXAMPLE_SCHEMA_VERSION,
        "example_id": f"{split}_{example_index:06d}",
        "split": split,
        "capability": capability,
        "task_type": task_type,
        "reasoning_operator": operator,
        "template_id": template_id,
        "instruction": instruction,
        "input": input_text,
        "target": answer,
        "facts": facts,
        "query": query,
        "answer": answer,
        "unique_answer_verified": True,
        "metadata": {
            "entity_prefix": split,
            "fact_count": len(facts),
            "seed": seed,
            "example_index": example_index,
        },
    }
    return example


def validate_example(example: dict[str, Any]) -> None:
    required_fields = {
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
    missing = required_fields - set(example)
    if missing:
        raise ValueError(f"Example {example.get('example_id')} missing fields: {sorted(missing)}")
    if example["capability"] not in CAPABILITIES:
        raise ValueError(f"Unsupported capability: {example['capability']}")
    if not isinstance(example["facts"], list) or not example["facts"]:
        raise ValueError("facts must be a non-empty list")
    if not example["answer"] or example["target"] != example["answer"]:
        raise ValueError("answer/target mismatch or empty")
    tok_count = len(tokenize_structural_text(example["input"])) + len(tokenize_structural_text(example["target"]))
    if tok_count > MAX_SEQUENCE_TOKENS:
        raise ValueError(f"Example {example['example_id']} exceeds token budget ({tok_count} > {MAX_SEQUENCE_TOKENS})")
    ok, reason = verify_unique_answer(example)
    if not ok:
        raise ValueError(f"Unique-answer verification failed for {example['example_id']}: {reason}")


def generate_split(split: str, count: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    examples: list[dict[str, Any]] = []
    for index in range(count):
        example = generate_example(split=split, example_index=index, rng=rng, seed=seed)
        validate_example(example)
        examples.append(example)
    return examples


def write_jsonl(path: Path, examples: list[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        for example in examples:
            handle.write(json.dumps(example, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def extract_entities(example: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    for text in (str(example.get("input", "")), str(example.get("target", ""))):
        for tok in tokenize_structural_text(text):
            if ENTITY_TOKEN_RE.match(tok):
                found.add(tok)
    for fact in example.get("facts", []):
        for k in ("source", "target"):
            val = str(fact.get(k, ""))
            if ENTITY_TOKEN_RE.match(val):
                found.add(val)
    return found


def check_split_isolation(splits: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    entity_sets: dict[str, set[str]] = {}
    template_sets: dict[str, set[str]] = {}

    for split, examples in splits.items():
        entities: set[str] = set()
        templates: set[str] = set()
        for ex in examples:
            templates.add(str(ex["template_id"]))
            entities.update(extract_entities(ex))
        entity_sets[split] = entities
        template_sets[split] = templates

    isolation_results: dict[str, Any] = {}
    split_names = list(splits)
    for idx, left in enumerate(split_names):
        for right in split_names[idx + 1:]:
            entity_overlap = entity_sets[left] & entity_sets[right]
            template_overlap = template_sets[left] & template_sets[right]
            key = f"{left}__{right}"
            isolation_results[key] = {
                "entity_overlap_count": len(entity_overlap),
                "template_overlap_count": len(template_overlap),
                "entity_isolation_pass": not entity_overlap,
                "template_isolation_pass": not template_overlap,
            }
            if entity_overlap or template_overlap:
                raise ValueError(f"Split isolation failed for {key}")
    return isolation_results


def build_manifest(
    splits: dict[str, list[dict[str, Any]]],
    output_files: dict[str, Path],
    seed: int,
    isolation: dict[str, Any],
) -> dict[str, Any]:
    split_records: dict[str, Any] = {}
    file_records: dict[str, Any] = {}

    for split in SPLITS:
        path = output_files[split]
        digest = sha256_file(path)
        count = len(splits[split])
        size_bytes = path.stat().st_size
        entry = {
            "path": path.name,
            "file": path.name,
            "example_count": count,
            "count": count,
            "documents": count,
            "sha256": digest,
            "bytes": size_bytes,
        }
        split_records[split] = entry
        file_records[path.name] = entry

    content_sha256 = hashlib.sha256(
        "".join(split_records[s]["sha256"] for s in SPLITS).encode("utf-8")
    ).hexdigest()

    task_types = sorted({ex["task_type"] for exs in splits.values() for ex in exs})
    operators = sorted({ex["reasoning_operator"] for exs in splits.values() for ex in exs})

    return {
        "schema": MANIFEST_SCHEMA,
        "schema_version": EXAMPLE_SCHEMA_VERSION,
        "version": DATASET_VERSION,
        "project": "ZYRQUEN Ω∞",
        "dataset": "nagi_v10",
        "generator": "gen_nagi_v10.py",
        "generator_version": GENERATOR_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "total_examples": sum(len(v) for v in splits.values()),
        "capabilities": list(CAPABILITIES),
        "task_types": task_types,
        "reasoning_operators": operators,
        "generalization_scope": {
            "unseen_entities": True,
            "unseen_instruction_templates": True,
            "unseen_ood_depth_and_relations": True,
            "unseen_abstract_operators": False,
            "unique_answer_verified": True,
            "description": (
                "Disjoint entity namespaces and instruction templates across splits, "
                "OOD depth/relation shifts on ood_transfer, and solver-verified unique answers."
            ),
        },
        "split_isolation": isolation,
        "splits": split_records,
        "files": file_records,
        "content_sha256": content_sha256,
        "integrity": {
            "algorithm": "SHA-256",
            "content_sha256": content_sha256,
            "manifest_self_hash": "Not included; hash manifest externally if required.",
        },
        "limitations": [
            "This is a deterministic symbolic reasoning benchmark.",
            "It does not establish general intelligence.",
            "Independent leakage audit via tools/audit_leakage_v10.py is still required.",
            "Model training and evaluation remain NOT STARTED until approved.",
        ],
    }


def generate_dataset(
    output_dir: Path,
    *,
    seed: int = DEFAULT_SEED,
    counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    resolved_counts = counts or dict(DEFAULT_COUNTS)
    if seed < 0:
        raise ValueError("seed must be non-negative")
    if any(resolved_counts.get(s, 0) <= 0 for s in SPLITS):
        raise ValueError("all split counts must be positive")
    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")

    seed_offsets = {"train": 0, "validation": 100_000, "test": 200_000}
    splits: dict[str, list[dict[str, Any]]] = {}
    for split in SPLITS:
        splits[split] = generate_split(split, resolved_counts[split], seed + seed_offsets[split])

    isolation = check_split_isolation(splits)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=False, exist_ok=False)

    output_files: dict[str, Path] = {}
    for split in SPLITS:
        path = output_dir / f"{split}.jsonl"
        write_jsonl(path, splits[split])
        output_files[split] = path

    manifest = build_manifest(splits, output_files, seed, isolation)
    manifest_path = output_dir / "manifest.json"
    with manifest_path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the ZYRQUEN NAGI v10 dataset.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output directory (must not exist).")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--train-count", type=int, default=DEFAULT_COUNTS["train"])
    parser.add_argument("--validation-count", type=int, default=DEFAULT_COUNTS["validation"])
    parser.add_argument("--test-count", type=int, default=DEFAULT_COUNTS["test"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    counts = {
        "train": args.train_count,
        "validation": args.validation_count,
        "test": args.test_count,
    }
    if args.seed < 0 or any(c <= 0 for c in counts.values()):
        print("ERROR: seed must be >= 0 and all split counts must be positive", file=sys.stderr)
        return 2

    output_dir = args.output.expanduser().resolve()
    try:
        manifest = generate_dataset(output_dir, seed=args.seed, counts=counts)
    except FileExistsError as exc:
        print(f"BLOCKED: {exc}. Refusing to overwrite existing dataset artifacts.", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print("NAGI v10 DATASET GENERATION COMPLETED")
    print(f"Output: {output_dir}")
    print(f"Total examples: {manifest['total_examples']}")
    print(f"Content SHA-256: {manifest['content_sha256']}")
    for split, record in manifest["splits"].items():
        print(f"{split}: {record['example_count']} examples | SHA-256: {record['sha256']}")
    print("Unique-answer verification: PASS")
    print("Entity isolation: PASS")
    print("Template isolation: PASS")
    print("Training: NOT STARTED")
    print("Independent leakage audit: PENDING")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
