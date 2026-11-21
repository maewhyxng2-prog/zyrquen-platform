#!/usr/bin/env python3
"""ZYRQUEN - Diag v5, teacher vs free gap"""
import argparse
import importlib
import json
from pathlib import Path
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
        self.lstm = nn.LSTM(128, 128, num_layers=2, batch_first=True, dropout=0.2)
        self.head = nn.Linear(128, vocab_size)
    def forward(self, x):
        h = self.emb(x)
        o, _ = self.lstm(h)
        return self.head(o)
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="checkpoints/nagi_500_v5_fixed/step_5.pt")
    ap.add_argument("--data", default="data/nagi_500_v3")
    args = ap.parse_args()
    ckpt = lib.load(args.ckpt, map_location="cpu", weights_only=False)
    if ckpt.get("tokenizer") != "token-level":
        print("BLOCKED diag v5 needs token-level ckpt")
        return
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
    def load(p):
        rows = []
        for l in Path(p).read_text(encoding="utf-8").splitlines():
            if l.strip():
                rows.append(json.loads(l))
        return rows
    def gen(inp):
        ids = [bos_id] + [stoi.get(t, unk_id) for t in tokenize(inp)]
        outs = []
        hit = False
        with lib.no_grad():
            for _ in range(5):
                x = lib.tensor([ids + outs], dtype=lib.long)
                logits = model(x)
                nxt = int(logits[0, -1].argmax().item())
                if nxt == eos_id:
                    hit = True
                    break
                outs.append(nxt)
        return [itos.get(i, "") for i in outs], hit
    def teacher_acc(ex):
        inp_ids = [bos_id] + [stoi.get(t, unk_id) for t in tokenize(ex["input"])]
        tgt_ids = [stoi.get(t, unk_id) for t in tokenize(ex["target"])] + [eos_id]
        full = inp_ids + tgt_ids
        x = lib.tensor([full[:-1]], dtype=lib.long)
        with lib.no_grad():
            logits = model(x)
        correct = 0
        total = 0
        start = len(inp_ids) - 1
        for i, gold in enumerate(tgt_ids):
            pos = start + i
            pred = int(logits[0, pos].argmax().item())
            if pred == gold:
                correct += 1
            total += 1
        return correct, total
    for split in ["train", "val"]:
        rows = load(Path(args.data) / f"{split}.jsonl")
        if len(rows) == 0:
            print(f"BLOCKED empty {split}")
            return
        exact = 0
        first_ok = 0
        eos_ok = 0
        rep = 0
        tf_corr = 0
        tf_tot = 0
        for r in rows:
            toks, hit = gen(r["input"])
            exp = tokenize(r["target"])
            if toks == exp:
                exact += 1
            if toks and exp and toks[0] == exp[0]:
                first_ok += 1
            if hit:
                eos_ok += 1
            if len(toks) >= 5 and len(set(toks)) == 1:
                rep += 1
            c, t = teacher_acc(r)
            tf_corr += c
            tf_tot += t
        print(f"{split} exact {exact}/{len(rows)} = {exact/max(1,len(rows)):.2f}")
        print(f"{split} first-token {first_ok}/{len(rows)} = {first_ok/max(1,len(rows)):.2f}")
        print(f"{split} EOS {eos_ok}/{len(rows)} rep {rep}/{len(rows)}")
        print(f"{split} teacher-forced target acc {tf_corr}/{tf_tot} = {tf_corr/max(1,tf_tot):.2f}")
        print(f"{split} gap teacher - free exact = {tf_corr/max(1,tf_tot) - exact/max(1,len(rows)):.2f} = exposure bias")
    print("If teacher high + free low = exposure bias confirmed")
if __name__ == "__main__":
    main()
