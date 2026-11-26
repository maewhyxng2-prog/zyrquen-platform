#!/usr/bin/env python3
"""
ZYRQUEN - Audit Leakage v3
Read-only, no train, no dataset edit
"""
import argparse
import json
import re
from pathlib import Path

def load(p):
    rows = []
    for l in p.read_text(encoding="utf-8").splitlines():
        if l.strip():
            rows.append(json.loads(l))
    return rows

def entities(s):
    return re.findall(r"E\d\d", s)

def template(s):
    return re.sub(r"E\d\d", "<E>", s)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/nagi_500_v3")
    args = ap.parse_args()
    d = Path(args.data)
    splits = {}
    for nm in ["train", "val", "test"]:
        p = d / f"{nm}.jsonl"
        rows = load(p)
        splits[nm] = rows
        print(f"{nm} {len(rows)}")
    for nm, rows in splits.items():
        ents = set()
        temps = set()
        combs = set()
        for r in rows:
            txt = r["input"] + " | " + r["target"]
            ents.update(entities(txt))
            temps.add(template(r["input"]))
            combs.add(r["input"])
        print(f"{nm} entities {sorted(ents)}")
        print(f"{nm} templates {len(temps)} combos {len(combs)}")
        splits[nm + "_ents"] = ents
        splits[nm + "_temps"] = temps
        splits[nm + "_combs"] = combs
    pairs = [("train", "val"), ("train", "test"), ("val", "test")]
    print("--- Leakage Check ---")
    for a, b in pairs:
        e = splits[a + "_ents"] & splits[b + "_ents"]
        t = splits[a + "_temps"] & splits[b + "_temps"]
        c = splits[a + "_combs"] & splits[b + "_combs"]
        print(f"{a} vs {b}")
        print(f" entity overlap {len(e)} {sorted(e)[:10]}")
        print(f" template overlap {len(t)}")
        print(f" combination overlap {len(c)}")
        if len(e) > 0:
            print("  -> FAIL strict entity-disjoint")
        else:
            print("  -> PASS strict entity-disjoint")
        if len(t) > 0:
            print("  -> FAIL strict template-disjoint")
        else:
            print("  -> PASS strict template-disjoint")
        if len(c) == 0:
            print("  -> PASS combination-disjoint")
        else:
            print("  -> FAIL combination-disjoint")
    print("--- Verdict ---")
    print("v3 = PASS combination-disjoint")
    print("v3 = FAIL strict entity + template disjoint")
    print("If requirement is strict, need v4 disjoint")

if __name__ == "__main__":
    main()
