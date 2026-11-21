#!/usr/bin/env python3
"""
ZYRQUEN - Native Training 500 v2 Generator
Fix v1: Shared templates across splits + Strictly disjoint entities + Balanced labels
No training, no weights, no deploy in this file.
"""
import json, random, hashlib
from pathlib import Path
from collections import Counter

SEED = 42
OUT = Path("data/nagi_500_v2")
OUT.mkdir(parents=True, exist_ok=True)

rng = random.Random(SEED)

# Entity pools - strictly disjoint by prefix
def make_entities(prefix, n):
    return [f"{prefix}_e{i:03d}" for i in range(n)]

train_pool = make_entities("TR", 400)
val_pool = make_entities("VA", 200)
test_pool = make_entities("TE", 200)

# Counts: Train 400 / Val 50 / Test 50
counts = {
    "train": {"native_representation": 66, "knowledge_acquisition": 67, "relational_reasoning": 67, "planning_decomposition": 67, "verification": 67, "adaptive_learning": 66},
    "val": {"native_representation": 8, "knowledge_acquisition": 8, "relational_reasoning": 9, "planning_decomposition": 8, "verification": 9, "adaptive_learning": 8},
    "test": {"native_representation": 8, "knowledge_acquisition": 8, "relational_reasoning": 9, "planning_decomposition": 8, "verification": 9, "adaptive_learning": 8},
}

# --- Template builders: SAME templates in all splits, only entities change ---
def build_native(a,b,c, variant):
    if variant == 0:
        return f"seq: {a},{b},{c} | first ?", a
    if variant == 1:
        return f"seq: {a},{b},{c} | last ?", c
    if variant == 2:
        return f"seq: {a},{b},{c} | middle ?", b
    # reverse
    return f"seq: {a},{b},{c} | reverse ?", f"{c},{b},{a}"

def build_knowledge(a,b,c, variant):
    if variant == 0:
        return f"fact: {a} -> {b} | query {a} ?", b
    # two-hop, query middle
    return f"fact: {a} -> {b}, {b} -> {c} | query {b} ?", c

def build_relational(a,b,c, variant):
    # 0: > symbol, 1: < symbol, 2: greater word, 3: less word, 4: = symbol, 5: equals word
    if variant == 0:
        return f"{a} > {b}, {b} > {c} | {a} ? {c}", ">"
    if variant == 1:
        return f"{a} < {b}, {b} < {c} | {a} ? {c}", "<"
    if variant == 2:
        return f"{a} greater than {b}, {b} greater than {c} | {a} vs {c}", "greater"
    if variant == 3:
        return f"{a} less than {b}, {b} less than {c} | {a} vs {c}", "less"
    if variant == 4:
        return f"{a} = {b}, {b} = {c} | {a} ? {c}", "="
    return f"{a} equals {b}, {b} equals {c} | {a} vs {c}", "equals"

def build_planning(a,b,c, variant):
    base = f"plan: {a} then {b} then {c} |"
    if variant == 0:
        return f"{base} first step ?", a
    if variant == 1:
        return f"{base} middle step ?", b
    if variant == 2:
        return f"{base} last step ?", c
    return f"{base} second step ?", b

def build_verification(a,b, variant):
    # Even variants = true, odd = false -> 50/50 balanced
    if variant % 2 == 0:
        # true cases: claim matches fact
        if variant == 0:
            return f"verify: {a} equals {b} | fact: {a} is same as {b} | verdict ?", "true"
        if variant == 2:
            return f"verify: {a} greater than {b} | fact: {a} is greater | verdict ?", "true"
        return f"verify: {a} less than {b} | fact: {a} is smaller | verdict ?", "true"
    else:
        # false cases: claim contradicts fact
        if variant == 1:
            return f"verify: {a} equals {b} | fact: {a} is different | verdict ?", "false"
        if variant == 3:
            return f"verify: {a} greater than {b} | fact: {a} is smaller | verdict ?", "false"
        return f"verify: {a} less than {b} | fact: {a} is greater | verdict ?", "false"

def build_adaptive(a,b,c, variant):
    if variant == 0:
        return f"learn: {a} -> {b} | predict {a} ?", b
    return f"learn: {a} -> {b}, {b} -> {c} | predict {a} ?", b

BUILDERS = {
    "native_representation": (build_native, 4),
    "knowledge_acquisition": (build_knowledge, 2),
    "relational_reasoning": (build_relational, 6),
    "planning_decomposition": (build_planning, 4),
    "verification": (build_verification, 6),
    "adaptive_learning": (build_adaptive, 2),
}

def gen_split(split_name, pool, count_map):
    rows = []
    # Use pool without reuse within split as much as possible
    idx = 0
    def next_entities(n):
        nonlocal idx
        # cycle through pool, ensure distinct entities per example
        ents = []
        for _ in range(n):
            ents.append(pool[idx % len(pool)])
            idx += 1
        return ents

    for cap, n in count_map.items():
        fn, n_variants = BUILDERS[cap]
        for i in range(n):
            variant = i % n_variants  # round-robin -> balanced templates
            if cap == "verification":
                a, b = next_entities(2)
                inp, tgt = fn(a, b, variant)
            else:
                a, b, c = next_entities(3)
                inp, tgt = fn(a, b, c, variant)
            rows.append({"id": f"{cap[:2].upper()}-{split_name[:3]}-{i:03d}", "capability": cap, "input": inp, "target": tgt, "split": split_name})
    rng.shuffle(rows)
    # Re-assign IDs after shuffle to keep order stable
    for j, r in enumerate(rows):
        r["id"] = f"{r['capability'][:2].upper()}-{split_name[:3]}-{j:03d}"
    return rows

all_rows = {}
for split in ["train", "val", "test"]:
    pool = {"train": train_pool, "val": val_pool, "test": test_pool}[split]
    rows = gen_split(split, pool, counts[split])
    all_rows[split] = rows
    p = OUT / f"{split}.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print(f"{split}: {len(rows)} rows -> {p}")

# Manifest + checks
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

# Entity disjoint check
def entities_in(rows):
    s = set()
    for r in rows:
        # extract TR_/VA_/TE_ tokens
        for tok in r["input"].replace(",", " ").replace("|", " ").replace("?", " ").split():
            if tok.startswith(("TR_", "VA_", "TE_")):
                s.add(tok)
    return s

tr_e = entities_in(all_rows["train"])
va_e = entities_in(all_rows["val"])
te_e = entities_in(all_rows["test"])
disjoint = len(tr_e & va_e) == 0 and len(tr_e & te_e) == 0 and len(va_e & te_e) == 0

# Balance check
balance = {}
for split, rows in all_rows.items():
    balance[split] = {}
    for cap in counts[split]:
        c = Counter(r["target"] for r in rows if r["capability"] == cap)
        balance[split][cap] = dict(c)

manifest = {
    "dataset": "nagi_500_v2",
    "version": "v2",
    "seed": SEED,
    "total": 500,
    "splits": {"train": 400, "val": 50, "test": 50},
    "design": {
        "templates": "SHARED across splits - same template pool in train/val/test",
        "entities": "STRICTLY DISJOINT - TR_ / VA_ / TE_ never overlap",
        "relational_balance": ">, <, greater, less, =, equals in every split",
        "verification_balance": "true/false 50/50 in every split",
        "planning_coverage": "first/middle/last/second in every split",
    },
    "entity_disjoint": disjoint,
    "entity_counts": {"train": len(tr_e), "val": len(va_e), "test": len(te_e)},
    "balance": balance,
    "files": {f"{s}.jsonl": sha(OUT / f"{s}.jsonl") for s in ["train", "val", "test"]},
    "notes": "Retrain from scratch on v2, do NOT continue from 500-step v1 checkpoint. 1000 steps not approved yet.",
}
(OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Entity disjoint: {disjoint} | train entities {len(tr_e)} val {len(va_e)} test {len(te_e)}")
print("Balance per split:")
for s, b in balance.items():
    print(f" {s}: {b}")
print(f"Manifest -> {OUT / 'manifest.json'}")
