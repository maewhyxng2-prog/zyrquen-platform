#!/usr/bin/env python3
"""
ZYRQUEN - Native Training 500 Generator
SPEC ONLY - Deterministic, rule-based, no external dataset, no AI API.
Generates 500 examples: Train 400 / Val 50 / Test 50
Prevents Entity + Template + Structural Leakage.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

PROVENANCE = "synthetic_rule_based_v1"
GENERATOR_VERSION = "gen_ngi_500_v1"

CAP_CONFIG = {
    "native_representation": {"train": 80, "val": 10, "test": 10, "prefix": "NR"},
    "knowledge_acquisition": {"train": 64, "val": 8, "test": 8, "prefix": "KA"},
    "relational_reasoning": {"train": 80, "val": 10, "test": 10, "prefix": "RR"},
    "planning_decomposition": {"train": 64, "val": 8, "test": 8, "prefix": "PD"},
    "verification": {"train": 64, "val": 8, "test": 8, "prefix": "VF"},
    "adaptive_learning": {"train": 48, "val": 6, "test": 6, "prefix": "AL"},
}

# template_id sets are disjoint across splits by design (TRAIN / VAL / TEST prefix)
TEMPLATES = {
    "native_representation": {
        "train": [
            ("NR_TRAIN_01", "seq: {e0},{e1},{e2} | len ?", "3"),
            ("NR_TRAIN_02", "seq: {e0},{e1},{e2} | first ?", "{e0}"),
            ("NR_TRAIN_03", "seq: {e0},{e1},{e2} | last ?", "{e2}"),
        ],
        "val": [
            ("NR_VAL_01", "seq: {e0},{e1},{e2} | middle ?", "{e1}"),
            ("NR_VAL_02", "seq: {e0},{e1},{e2} | reverse_first ?", "{e2}"),
        ],
        "test": [
            ("NR_TEST_01", "seq: {e0},{e1},{e2} | count ?", "3"),
            ("NR_TEST_02", "seq: {e0},{e1},{e2} | element_at_1 ?", "{e1}"),
        ],
    },
    "knowledge_acquisition": {
        "train": [
            ("KA_TRAIN_01", "fact: {e0} -> {e1} | query {e0} ?", "{e1}"),
            ("KA_TRAIN_02", "fact: {e0} has {e1} | what does {e0} have ?", "{e1}"),
            ("KA_TRAIN_03", "know: {e0} = {e1} | recall {e0} ?", "{e1}"),
        ],
        "val": [
            ("KA_VAL_01", "learned: {e0} maps to {e1} | map {e0} ?", "{e1}"),
            ("KA_VAL_02", "store: {e0} : {e1} | retrieve {e0} ?", "{e1}"),
        ],
        "test": [
            ("KA_TEST_01", "memory: {e0} linked to {e1} | linked to {e0} ?", "{e1}"),
            ("KA_TEST_02", "record: {e0} => {e1} | lookup {e0} ?", "{e1}"),
        ],
    },
    "relational_reasoning": {
        "train": [
            ("RR_TRAIN_01", "{e0} > {e1}, {e1} > {e2} | {e0} ? {e2}", ">"),
            ("RR_TRAIN_02", "{e0} greater than {e1}, {e1} greater than {e2} | {e0} vs {e2}", "greater"),
            ("RR_TRAIN_03", "if {e0} > {e1} and {e1} > {e2} then {e0} > {e2} ? true/false", "true"),
        ],
        "val": [
            ("RR_VAL_01", "{e0} < {e1}, {e1} < {e2} | {e0} ? {e2}", "<"),
            ("RR_VAL_02", "{e0} less than {e1}, {e1} less than {e2} | {e0} vs {e2}", "less"),
        ],
        "test": [
            ("RR_TEST_01", "{e0} = {e1}, {e1} = {e2} | {e0} ? {e2}", "="),
            ("RR_TEST_02", "{e0} equals {e1}, {e1} equals {e2} | {e0} vs {e2}", "equals"),
        ],
    },
    "planning_decomposition": {
        "train": [
            ("PD_TRAIN_01", "plan: {e0} then {e1} then {e2} | first step ?", "{e0}"),
            ("PD_TRAIN_02", "goal: {e2} needs {e0} then {e1} | step 1 ?", "{e0}"),
            ("PD_TRAIN_03", "task: {e0} -> {e1} -> {e2} | start ?", "{e0}"),
        ],
        "val": [
            ("PD_VAL_01", "plan: {e0} then {e1} then {e2} | last step ?", "{e2}"),
            ("PD_VAL_02", "goal: {e2} needs {e0} then {e1} | final step ?", "{e2}"),
        ],
        "test": [
            ("PD_TEST_01", "plan: {e0} then {e1} then {e2} | middle step ?", "{e1}"),
            ("PD_TEST_02", "task: {e0} -> {e1} -> {e2} | step 2 ?", "{e1}"),
        ],
    },
    "verification": {
        "train": [
            ("VF_TRAIN_01", "claim: {e0} > {e1} | fact: {e0} is greater | verdict ?", "true"),
            ("VF_TRAIN_02", "claim: {e0} equals {e1} | fact: {e0} is not equal | verdict ?", "false"),
            ("VF_TRAIN_03", "check: {e0} > {e1} given {e0} greater | correct ?", "true"),
        ],
        "val": [
            ("VF_VAL_01", "verify: {e0} < {e1} | fact: {e0} is smaller | verdict ?", "true"),
            ("VF_VAL_02", "verify: {e0} equals {e1} | fact: {e0} is different | verdict ?", "false"),
        ],
        "test": [
            ("VF_TEST_01", "audit: {e0} > {e1} | evidence: {e0} greater | verdict ?", "true"),
            ("VF_TEST_02", "audit: {e0} < {e1} | evidence: {e0} greater | verdict ?", "false"),
        ],
    },
    "adaptive_learning": {
        "train": [
            ("AL_TRAIN_01", "learn: {e0} -> {e1} | predict {e0} ?", "{e1}"),
            ("AL_TRAIN_02", "old: {e0} -> {e1} | new: {e0} -> {e1} | predict {e0} ?", "{e1}"),
            ("AL_TRAIN_03", "update: {e0} maps to {e1} | map {e0} ?", "{e1}"),
        ],
        "val": [
            ("AL_VAL_01", "correct: {e0} was {e1}, now {e1} | predict {e0} ?", "{e1}"),
            ("AL_VAL_02", "revise: {e0} -> {e1} | after revision {e0} ?", "{e1}"),
        ],
        "test": [
            ("AL_TEST_01", "adapt: {e0} -> {e1}, {e0} -> {e1} | adapted {e0} ?", "{e1}"),
            ("AL_TEST_02", "feedback: {e0} should be {e1} | after feedback {e0} ?", "{e1}"),
        ],
    },
}

ENTITY_RE = re.compile(r"(NR|KA|RR|PD|VF|AL)_(train|val|test)_e\d+")

def make_pool(prefix, split, n=300):
    return [f"{prefix}_{split}_e{i:03d}" for i in range(n)]

def abstract_pattern(input_template):
    return input_template.replace("{e0}", "<E0>").replace("{e1}", "<E1>").replace("{e2}", "<E2>")

def sha256_file(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def generate():
    by_split = {"train": [], "val": [], "test": []}
    for cap, cfg in CAP_CONFIG.items():
        prefix = cfg["prefix"]
        for split in ["train", "val", "test"]:
            count = cfg[split]
            pool = make_pool(prefix, split)
            templates = TEMPLATES[cap][split]
            for i in range(count):
                tmpl_id, in_tmpl, out_tmpl = templates[i % len(templates)]
                e0 = pool[(i * 3) % len(pool)]
                e1 = pool[(i * 3 + 1) % len(pool)]
                e2 = pool[(i * 3 + 2) % len(pool)]
                inp = in_tmpl.format(e0=e0, e1=e1, e2=e2)
                tgt = out_tmpl.format(e0=e0, e1=e1, e2=e2)
                sig = f"{cap}::{tmpl_id}::{abstract_pattern(in_tmpl)}"
                ex = {
                    "id": f"{prefix}-{split}-{i:03d}",
                    "capability": cap,
                    "split": split,
                    "template_id": tmpl_id,
                    "structural_signature": sig,
                    "input": inp,
                    "target": tgt,
                    "provenance": PROVENANCE,
                }
                by_split[split].append(ex)
    return by_split

def check(by_split):
    errors = []
    # Count checks
    expected_split = {"train": 400, "val": 50, "test": 50}
    for split, exp in expected_split.items():
        if len(by_split[split]) != exp:
            errors.append(f"count {split}: got {len(by_split[split])} expected {exp}")
    total = sum(len(v) for v in by_split.values())
    if total != 500:
        errors.append(f"total: got {total} expected 500")
    # Per-capability counts
    for cap, cfg in CAP_CONFIG.items():
        for split in ["train", "val", "test"]:
            got = sum(1 for e in by_split[split] if e["capability"] == cap)
            if got != cfg[split]:
                errors.append(f"cap {cap} {split}: got {got} expected {cfg[split]}")
    # Exact + normalized duplicate
    seen_exact = set()
    seen_norm = set()
    for split, items in by_split.items():
        for e in items:
            if e["input"] in seen_exact:
                errors.append(f"exact duplicate input: {e['input']}")
            seen_exact.add(e["input"])
            norm = " ".join(e["input"].lower().split())
            if norm in seen_norm:
                errors.append(f"normalized duplicate input: {e['input']}")
            seen_norm.add(norm)
    # Template overlap
    tmpl_by_split = {s: set(e["template_id"] for e in items) for s, items in by_split.items()}
    for a, b in [("train", "val"), ("train", "test"), ("val", "test")]:
        inter = tmpl_by_split[a] & tmpl_by_split[b]
        if inter:
            errors.append(f"template overlap {a}-{b}: {inter}")
    # Entity overlap
    ent_by_split = {}
    for split, items in by_split.items():
        s = set()
        for e in items:
            s.update(ENTITY_RE.findall(e["input"]))
            # findall returns tuples, convert to string
            for m in ENTITY_RE.finditer(e["input"]):
                s.add(m.group(0))
        ent_by_split[split] = s
    for a, b in [("train", "val"), ("train", "test"), ("val", "test")]:
        inter = ent_by_split[a] & ent_by_split[b]
        if inter:
            errors.append(f"entity overlap {a}-{b}: {sorted(list(inter))[:5]}")
    # Structural signature overlap
    sig_by_split = {s: set(e["structural_signature"] for e in items) for s, items in by_split.items()}
    for a, b in [("train", "val"), ("train", "test"), ("val", "test")]:
        inter = sig_by_split[a] & sig_by_split[b]
        if inter:
            errors.append(f"structural_signature overlap {a}-{b}: {sorted(list(inter))[:3]}")
    # Abstract pattern overlap (hidden leakage: same pattern, different template_id)
    def abstract_set(items):
        s = set()
        for e in items:
            # strip template_id from signature -> cap + abstract pattern
            parts = e["structural_signature"].split("::", 2)
            if len(parts) == 3:
                s.add(f"{parts[0]}::{parts[2]}")
        return s
    abs_by_split = {s: abstract_set(items) for s, items in by_split.items()}
    for a, b in [("train", "val"), ("train", "test"), ("val", "test")]:
        inter = abs_by_split[a] & abs_by_split[b]
        if inter:
            errors.append(f"abstract pattern overlap {a}-{b}: {sorted(list(inter))[:3]}")
    return errors

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/nagi_500")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    by_split = generate()
    errors = check(by_split)
    if errors:
        print("FAIL - integrity checks failed:")
        for er in errors:
            print(f" - {er}")
        sys.exit(1)
    files = {}
    for split in ["train", "val", "test"]:
        p = out / f"{split}.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for e in by_split[split]:
                f.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
        files[f"{split}.jsonl"] = {"path": str(p), "count": len(by_split[split]), "sha256": sha256_file(p)}
    manifest = {
        "generator": GENERATOR_VERSION,
        "provenance": PROVENANCE,
        "deterministic": True,
        "total": 500,
        "per_split": {"train": 400, "val": 50, "test": 50},
        "per_capability": {k: {"train": v["train"], "val": v["val"], "test": v["test"], "total": v["train"] + v["val"] + v["test"]} for k, v in CAP_CONFIG.items()},
        "files": files,
        "checks": ["count", "exact_duplicate", "normalized_duplicate", "template_overlap", "entity_overlap", "structural_signature_overlap", "abstract_pattern_overlap"],
        "checks_passed": True,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("OK - 500 generated")
    print(f"train: {len(by_split['train'])}  val: {len(by_split['val'])}  test: {len(by_split['test'])}")
    print(f"manifest: {out / 'manifest.json'}")

if __name__ == "__main__":
    main()
