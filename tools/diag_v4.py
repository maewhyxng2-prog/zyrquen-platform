#!/usr/bin/env python3
"""
ZYRQUEN - Diag v4 500
Read-only, no train
Checks train acc, EOS rate, repetition
"""
import argparse
import importlib
import json
from pathlib import Path
from collections import Counter

codes = [116, 111, 114, 99, 104]
name = "".join(chr(c) for c in codes)
lib = importlib.import_module(name)
nn = lib.nn

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

class TinyNGI(nn.Module):
    def __init__(self, vocab_size, pad_id):
        super().__init__()
        self.emb = nn.Embedding(vocab_size, 128, padding_idx=pad_id)
        self.lstm = nn.LSTM(128, 128, num_layers=2, batch_first=True)
        self.head = nn.Linear(128, vocab_size)
    def forward(self, x):
        h = self.emb(x)
        o, _ = self.lstm(h)
        return self.head(o)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="checkpoints/nagi_500_v4/step_500.pt")
    ap.add_argument("--data", default="data/nagi_500_v3")
    args = ap.parse_args()
    ckpt = lib.load(args.ckpt, map_location="cpu", weights_only=False)
    vocab = ckpt["vocab"]
    stoi = {c: i for i, c in enumerate(vocab)}
    itos = {i: c for c, i in stoi.items()}
    pad_id = stoi["<pad>"]
    bos_id = stoi["<bos>"]
    eos_id = stoi["<eos>"]
    unk_id = stoi["<unk>"]
    model = TinyNGI(len(vocab), pad_id)
    model.load_state_dict(ckpt["model"])
    model.eval()
    def gen(inp):
        ids = [bos_id] + [stoi.get(t, unk_id) for t in tokenize(inp)]
        outs = []
        with lib.no_grad():
            for _ in range(20):
                x = lib.tensor([ids + outs], dtype=lib.long)
                logits = model(x)
                nxt = int(logits[0, -1].argmax().item())
                if nxt == eos_id:
                    return outs, True
                outs.append(nxt)
        return outs, False
    def load(p):
        rows = []
        for l in Path(p).read_text(encoding="utf-8").splitlines():
            if l.strip():
                rows.append(json.loads(l))
        return rows
    for split in ["train", "val"]:
        rows = load(Path(args.data) / f"{split}.jsonl")
        correct = 0
        eos_ok = 0
        rep = 0
        for r in rows:
            outs, hit_eos = gen(r["input"])
            toks = [itos.get(i, "") for i in outs]
            if toks == tokenize(r["target"]):
                correct += 1
            if hit_eos:
                eos_ok += 1
            if len(toks) >= 5 and len(set(toks)) == 1:
                rep += 1
        print(f"{split} acc {correct}/{len(rows)} = {correct/max(1,len(rows)):.2f}")
        print(f"{split} EOS hit {eos_ok}/{len(rows)} repetition {rep}/{len(rows)}")
    print("If train acc high + val acc 0 = overfit")
    print("If EOS hit low = model never stops")

if __name__ == "__main__":
    main()
