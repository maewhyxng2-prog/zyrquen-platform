#!/usr/bin/env python3
"""
ZYRQUEN - Preflight v4
Read-only, no train, no dataset edit
Token vocab from train only
"""
import argparse
import json
from pathlib import Path
from collections import Counter

def tokenize(text):
    t = text.replace("->", " __ARROW__ ")
    t = t.replace(",", " , ")
    t = t.replace("|", " | ")
    t = t.replace(":", " : ")
    t = t.replace("?", " ? ")
    t = t.replace(">", " > ")
    t = t.replace("<", " < ")
    t = t.replace("=", " = ")
    toks = t.split()
    toks = ["->" if x == "__ARROW__" else x for x in toks]
    return toks

def load(p):
    rows = []
    for l in Path(p).read_text(encoding="utf-8").splitlines():
        if l.strip():
            rows.append(json.loads(l))
    return rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/nagi_500_v3")
    args = ap.parse_args()
    d = Path(args.data)
    train = load(d / "train.jsonl")
    val = load(d / "val.jsonl")
    test = load(d / "test.jsonl")
    print(f"Train {len(train)} Val {len(val)} Test {len(test)}")
    train_ids = set(r["id"] for r in train)
    test_ids = set(r["id"] for r in test)
    print(f"Test leak into train: {len(train_ids & test_ids)}")
    assert len(train_ids & test_ids) == 0
    # Vocab train-only
    toks = set()
    for r in train:
        toks.update(tokenize(r["input"]))
        toks.update(tokenize(r["target"]))
    vocab = ["<pad>", "<bos>", "<eos>", "<unk>"] + sorted(list(toks))
    print(f"Vocab train-only {len(vocab)}")
    print(f"Vocab: {vocab}")
    # Max token len
    maxlen = 0
    for rows in [train, val, test]:
        for r in rows:
            n = len(tokenize(r["input"])) + len(tokenize(r["target"])) + 2
            maxlen = max(maxlen, n)
    print(f"Max token len {maxlen} cap 256")
    assert maxlen <= 256
    # Class balance - target tokens
    cnt = Counter()
    e12 = 0
    total_tgt = 0
    for r in train:
        tt = tokenize(r["target"])
        for t in tt:
            cnt[t] += 1
            total_tgt += 1
            if t == "E12":
                e12 += 1
    print(f"Target tokens {total_tgt} E12 {e12} rate {e12/max(1,total_tgt):.3f}")
    print("Top targets:")
    for k, v in cnt.most_common(10):
        print(f" - {k} {v}")
    # Per capability balance
    caps = sorted(set(r["capability"] for r in train))
    for c in caps:
        n = sum(1 for r in train if r["capability"] == c)
        print(f" - {c} train {n}")
    # Combination overlap
    tr = set(r["input"] for r in train)
    va = set(r["input"] for r in val)
    te = set(r["input"] for r in test)
    print(f"Comb overlap train-val {len(tr & va)} train-test {len(tr & te)}")
    print("Preflight v4: PASS - ready for 5-step trial")
    print("Next: create trainer v4, do NOT run 500 yet")

if __name__ == "__main__":
    main()
