#!/usr/bin/env python3
"""
ZYRQUEN - Native 500 v3
Fix v2 copy problem
Entities reused, combos disjoint
No training, no weights
Short lines only
"""
import json
import random
import hashlib
from pathlib import Path

SEED = 42
OUT = Path("data/nagi_500_v3")
OUT.mkdir(parents=True, exist_ok=True)
rng = random.Random(SEED)
pool = [f"E{i:02d}" for i in range(20)]
seen = set()

def build_native(a, b, c, v):
    base = f"seq: {a},{b},{c} |"
    if v == 0:
        return f"{base} first ?", a
    if v == 1:
        return f"{base} last ?", c
    if v == 2:
        return f"{base} middle ?", b
    return f"{base} reverse ?", f"{c},{b},{a}"

def build_know(a, b, c, v):
    if v == 0:
        return f"fact: {a} -> {b} | query {a} ?", b
    return f"fact: {a} -> {b}, {b} -> {c} | query {b} ?", c

def build_rel(a, b, c, v):
    if v == 0:
        return f"{a} > {b}, {b} > {c} | {a} ? {c}", ">"
    if v == 1:
        return f"{a} < {b}, {b} < {c} | {a} ? {c}", "<"
    if v == 2:
        return f"{a} greater than {b}, {b} greater than {c} | {a} vs {c}", "greater"
    if v == 3:
        return f"{a} less than {b}, {b} less than {c} | {a} vs {c}", "less"
    if v == 4:
        return f"{a} = {b}, {b} = {c} | {a} ? {c}", "="
    return f"{a} equals {b}, {b} equals {c} | {a} vs {c}", "equals"

def build_plan(a, b, c, v):
    base = f"plan: {a} then {b} then {c} |"
    if v == 0:
        return f"{base} first step ?", a
    if v == 1:
        return f"{base} middle step ?", b
    if v == 2:
        return f"{base} last step ?", c
    return f"{base} second step ?", b

def build_ver(a, b, v):
    if v == 0:
        return f"verify: {a} equals {b} | fact: {a} is same as {b} | verdict ?", "true"
    if v == 1:
        return f"verify: {a} equals {b} | fact: {a} is different | verdict ?", "false"
    if v == 2:
        return f"verify: {a} greater than {b} | fact: {a} is greater | verdict ?", "true"
    if v == 3:
        return f"verify: {a} greater than {b} | fact: {a} is smaller | verdict ?", "false"
    if v == 4:
        return f"verify: {a} less than {b} | fact: {a} is smaller | verdict ?", "true"
    return f"verify: {a} less than {b} | fact: {a} is greater | verdict ?", "false"

def build_adapt(a, b, c, v):
    if v == 0:
        return f"learn: {a} -> {b} | predict {a} ?", b
    return f"learn: {a} -> {b}, {b} -> {c} | predict {a} ?", b

BUILD = {
    "native_representation": (build_native, 4),
    "knowledge_acquisition": (build_know, 2),
    "relational_reasoning": (build_rel, 6),
    "planning_decomposition": (build_plan, 4),
    "verification": (build_ver, 6),
    "adaptive_learning": (build_adapt, 2),
}

COUNTS = {
    "train": {
        "native_representation": 66,
        "knowledge_acquisition": 67,
        "relational_reasoning": 67,
        "planning_decomposition": 67,
        "verification": 67,
        "adaptive_learning": 66,
    },
    "val": {
        "native_representation": 8,
        "knowledge_acquisition": 8,
        "relational_reasoning": 9,
        "planning_decomposition": 8,
        "verification": 9,
        "adaptive_learning": 8,
    },
    "test": {
        "native_representation": 8,
        "knowledge_acquisition": 8,
        "relational_reasoning": 9,
        "planning_decomposition": 8,
        "verification": 9,
        "adaptive_learning": 8,
    },
}

def gen_split(name, cmap):
    rows = []
    for cap, n in cmap.items():
        fn, nv = BUILD[cap]
        for i in range(n):
            v = i % nv
            done = False
            for _ in range(30):
                if cap == "verification":
                    a, b = rng.sample(pool, 2)
                    inp, tgt = fn(a, b, v)
                else:
                    a, b, c = rng.sample(pool, 3)
                    inp, tgt = fn(a, b, c, v)
                if inp not in seen:
                    seen.add(inp)
                    done = True
                    break
            if not done:
                continue
            rows.append(
                {
                    "id": f"{cap[:2].upper()}-{name[:3]}-{len(rows):03d}",
                    "capability": cap,
                    "input": inp,
                    "target": tgt,
                    "split": name,
                }
            )
    rng.shuffle(rows)
    for j, r in enumerate(rows):
        r["id"] = f"{r['capability'][:2].upper()}-{name[:3]}-{j:03d}"
    return rows

all_rows = {}
for split in ["train", "val", "test"]:
    rows = gen_split(split, COUNTS[split])
    all_rows[split] = rows
    p = OUT / f"{split}.jsonl"
    txt = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    p.write_text(txt + "\n", encoding="utf-8")
    print(f"{split}: {len(rows)} -> {p}")

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

from collections import Counter
balance = {}
for s, rows in all_rows.items():
    balance[s] = {}
    for cap in COUNTS[s]:
        c = Counter(r["target"] for r in rows if r["capability"] == cap)
        balance[s][cap] = dict(c)
manifest = {
    "dataset": "nagi_500_v3",
    "version": "v3",
    "seed": SEED,
    "total": 500,
    "splits": {"train": 400, "val": 50, "test": 50},
    "design": {
        "entities": "REUSED 20 E00-E19 in all splits",
        "combos": "DISJOINT inputs, no input repeats across splits",
        "templates": "SHARED",
        "balance": "relational + verification + planning balanced",
    },
    "balance": balance,
    "files": {f"{s}.jsonl": sha(OUT / f"{s}.jsonl") for s in ["train", "val", "test"]},
    "notes": "Retrain from scratch on v3, do NOT continue from v1/v2 ckpt. 1000 steps not approved yet.",
}
(OUT / "manifest.json").write_text(
    json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
print("Balance:")
for s, b in balance.items():
    print(f" {s}: {b}")
print(f"Manifest -> {OUT / 'manifest.json'}")
