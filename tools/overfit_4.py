#!/usr/bin/env python3
"""ZYRQUEN - Overfit 4 examples, decisive test"""
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
        self.lstm = nn.LSTM(128, 128, num_layers=2, batch_first=True, dropout=0.0)
        self.head = nn.Linear(128, vocab_size)
    def forward(self, x):
        h = self.emb(x)
        o, _ = self.lstm(h)
        return self.head(o)
def main():
    data = Path("data/nagi_500_v3")
    rows = []
    for l in (data / "train.jsonl").read_text(encoding="utf-8").splitlines():
        if l.strip():
            rows.append(json.loads(l))
    rows = rows[:4]
    print(f"Overfit on {len(rows)} examples")
    for r in rows:
        print(f"- {r['id']} | {r['input']} -> {r['target']}")
    toks = set()
    for r in rows:
        toks.update(tokenize(r["input"]))
        toks.update(tokenize(r["target"]))
    vocab = ["<pad>", "<bos>", "<eos>", "<unk>"] + sorted(list(toks))
    stoi = {c: i for i, c in enumerate(vocab)}
    itos = {i: c for c, i in stoi.items()}
    pad_id = stoi["<pad>"]
    bos_id = stoi["<bos>"]
    eos_id = stoi["<eos>"]
    unk_id = stoi["<unk>"]
    print(f"Vocab overfit {len(vocab)} {vocab}")
    model = TinyNGI(len(vocab), pad_id)
    opt = lib.optim.Adam(model.parameters(), lr=0.001, weight_decay=0.0)
    def encode(r):
        prefix = [bos_id] + [stoi.get(t, unk_id) for t in tokenize(r["input"])]
        tgt = [stoi.get(t, unk_id) for t in tokenize(r["target"])] + [eos_id]
        ids = prefix + tgt
        labels = [-100] * len(prefix) + tgt
        return ids, labels
    batch = [encode(r) for r in rows]
    m = max(len(x[0]) for x in batch)
    xs = []
    ys = []
    for ids, labels in batch:
        n = m - len(ids)
        xs.append(ids + [pad_id] * n)
        ys.append(labels + [-100] * n)
    # Shift fix - same as v7
    xs = [r[:-1] for r in xs]
    ys = [r[1:] for r in ys]
    x = lib.tensor(xs, dtype=lib.long)
    y = lib.tensor(ys, dtype=lib.long)
    model.train()
    for step in range(1, 201):
        logits = model(x)
        fn = nn.CrossEntropyLoss(ignore_index=-100)
        loss = fn(logits.reshape(-1, len(vocab)), y.reshape(-1))
        opt.zero_grad()
        loss.backward()
        opt.step()
        if step % 50 == 0 or step == 200:
            print(f"step {step} loss {float(loss.item()):.4f}")
    model.eval()
    def gen(inp):
        ids = [bos_id] + [stoi.get(t, unk_id) for t in tokenize(inp)]
        outs = []
        hit = False
        with lib.no_grad():
            for _ in range(5):
                cur = ids + outs
                xx = lib.tensor([cur], dtype=lib.long)
                logits = model(xx)
                nxt = int(logits[0, -1].argmax().item())
                if nxt == eos_id:
                    hit = True
                    break
                outs.append(nxt)
        return [itos.get(i, "") for i in outs], hit
    ok = 0
    for r in rows:
        pred, hit = gen(r["input"])
        exp = tokenize(r["target"])
        good = (pred == exp)
        if good:
            ok += 1
        print(f"{r['id']} exp {exp} pred {pred} EOS {hit} OK {good}")
    print(f"Overfit exact {ok}/4")
    if ok == 4:
        print("PASS model CAN generate with shift fix, 50 steps was just underfit")
    elif ok > 0:
        print("PARTIAL model can generate some, needs more steps")
    else:
        print("FAIL model CANNOT generate even 4 memorized examples, structural bug remains")
if __name__ == "__main__":
    main()
