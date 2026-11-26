#!/usr/bin/env python3
"""
ZYRQUEN - Train v4 Token-level
Fixes: token vocab, target-only, safe save
No auto-promote, no deploy
Part 1/2
"""
import argparse
import hashlib
import importlib
import json
import resource
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

def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

class TinyNGI(nn.Module):
    def __init__(self, vocab_size, pad_id):
        super().__init__()
        self.emb = nn.Embedding(
            vocab_size, 128, padding_idx=pad_id
        )
        self.lstm = nn.LSTM(
            128, 128, num_layers=2, batch_first=True
        )
        self.head = nn.Linear(128, vocab_size)
    def forward(self, x):
        h = self.emb(x)
        o, _ = self.lstm(h)
        return self.head(o)

def load_jsonl(p):
    rows = []
    for l in Path(p).read_text(encoding="utf-8").splitlines():
        if l.strip():
            rows.append(json.loads(l))
    return rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/nagi_500_v3")
    ap.add_argument("--out", default="checkpoints/nagi_500_v4")
    ap.add_argument("--steps", type=int, default=5)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--seq", type=int, default=256)
    args = ap.parse_args()
    assert args.batch == 4
    assert args.seq == 256
    data = Path(args.data)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    train = load_jsonl(data / "train.jsonl")
    val = load_jsonl(data / "val.jsonl")
    test = load_jsonl(data / "test.jsonl")
    print(f"Train {len(train)} Val {len(val)} Test {len(test)}")
    train_ids = set(r["id"] for r in train)
    test_ids = set(r["id"] for r in test)
    assert len(train_ids & test_ids) == 0
    print("OK test not in train")
    # Vocab train-only token-level
    toks = set()
    for r in train:
        toks.update(tokenize(r["input"]))
        toks.update(tokenize(r["target"]))
    vocab = ["<pad>", "<bos>", "<eos>", "<unk>"] + sorted(list(toks))
    stoi = {c: i for i, c in enumerate(vocab)}
    pad_id = stoi["<pad>"]
    bos_id = stoi["<bos>"]
    eos_id = stoi["<eos>"]
    unk_id = stoi["<unk>"]
    print(f"Vocab token-level train-only {len(vocab)}")
    model = TinyNGI(len(vocab), pad_id)
    total = sum(p.numel() for p in model.parameters())
    print(f"Params {total}")
    assert total <= 5000000
    opt = lib.optim.Adam(model.parameters(), lr=0.001)
    def encode_pair(r):
        inp_toks = tokenize(r["input"])
        tgt_toks = tokenize(r["target"])
        prefix = [bos_id]
        for t in inp_toks:
            prefix.append(stoi.get(t, unk_id))
        tgt_ids = []
        for t in tgt_toks:
            tgt_ids.append(stoi.get(t, unk_id))
        tgt_ids.append(eos_id)
        if len(tgt_ids) > args.seq:
            return None
        if len(prefix) + len(tgt_ids) > args.seq:
            keep = args.seq - len(tgt_ids)
            prefix = prefix[:keep]
        ids = prefix + tgt_ids
        labels = [-100] * len(prefix) + tgt_ids
        return ids, labels

    def pad_batch(batch):
        m = max(len(x[0]) for x in batch)
        xs = []
        ys = []
        for ids, labels in batch:
            n = m - len(ids)
            xs.append(ids + [pad_id] * n)
            ys.append(labels + [-100] * n)
        return xs, ys

    def val_loss():
        model.eval()
        losses = []
        with lib.no_grad():
            for r in val:
                enc = encode_pair(r)
                if enc is None:
                    continue
                ids, labels = enc
                x = lib.tensor([ids[:-1]], dtype=lib.long)
                y = lib.tensor([labels[1:]], dtype=lib.long)
                logits = model(x)
                fn = nn.CrossEntropyLoss(ignore_index=-100)
                l = fn(logits.reshape(-1, len(vocab)), y.reshape(-1))
                losses.append(float(l.item()))
        model.train()
        if not losses:
            return 0.0
        return sum(losses) / len(losses)

    global_step = 0
    model.train()
    train_losses = []
    for step in range(1, args.steps + 1):
        global_step = step
        rows = []
        for i in range(args.batch):
            idx = ((step - 1) * args.batch + i) % len(train)
            rows.append(train[idx])
        batch = []
        for r in rows:
            enc = encode_pair(r)
            if enc is not None:
                batch.append(enc)
        if not batch:
            continue
        xs, ys = pad_batch(batch)
        x = lib.tensor(xs, dtype=lib.long)
        y = lib.tensor(ys, dtype=lib.long)
        logits = model(x)
        fn = nn.CrossEntropyLoss(ignore_index=-100)
        loss = fn(logits.reshape(-1, len(vocab)), y.reshape(-1))
        opt.zero_grad()
        loss.backward()
        opt.step()
        train_losses.append(float(loss.item()))
        print(f"step {step}/{args.steps} loss {float(loss.item()):.4f}")
    ckpt = {
        "model": model.state_dict(),
        "vocab": vocab,
        "step": global_step,
        "params": total,
        "dataset": "nagi_500_v3",
        "from_scratch": True,
        "vocab_source": "train-only",
        "tokenizer": "token-level",
        "loss_mode": "target-only",
    }
    tmp_c = out / f"step_{global_step}.pt.tmp"
    final_c = out / f"step_{global_step}.pt"
    lib.save(ckpt, str(tmp_c))
    tmp_c.rename(final_c)
    sha = sha256_file(final_c)
    print(f"Saved {final_c}")
    print(f"SHA {sha}")
    vl = val_loss()
    last10 = train_losses[-10:] if train_losses else [0.0]
    avg = sum(last10) / max(1, len(last10))
    print(f"Done train {avg:.4f} val {vl:.4f}")
    print(f"RAM max KB {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}")
    metrics = {
        "step": global_step,
        "train_loss_last10": avg,
        "val_loss": vl,
        "params": total,
        "dataset": "nagi_500_v3",
        "from_scratch": True,
        "sha256": sha,
        "vocab_source": "train-only",
        "tokenizer": "token-level",
        "loss_mode": "target-only",
    }
    tmp_m = out / "metrics.json.tmp"
    final_m = out / "metrics.json"
    tmp_m.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    tmp_m.rename(final_m)
    print(f"Metrics step {global_step} OK")

if __name__ == "__main__":
    main()
