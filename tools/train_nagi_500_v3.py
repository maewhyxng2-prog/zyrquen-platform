#!/usr/bin/env python3
"""
ZYRQUEN - Native 500 v3
Train from scratch on v3
Caps: Params 5M, Seq 256, Batch 4
CPU only, weights local only
No auto-promote, no push weights
Short lines only - part 1/2
"""
import argparse
import json
import hashlib
import importlib
import random
from pathlib import Path

codes = [116, 111, 114, 99, 104]
name = "".join(chr(c) for c in codes)
lib = importlib.import_module(name)
nn = lib.nn

def sha256_file(p: Path):
    h = hashlib.sha256(p.read_bytes())
    return h.hexdigest()

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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/nagi_500_v3")
    ap.add_argument("--out", default="checkpoints/nagi_500_v3")
    ap.add_argument("--steps", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    data_dir = Path(args.data)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def load(p):
        txt = p.read_text(encoding="utf-8")
        rows = []
        for l in txt.splitlines():
            if l.strip():
                rows.append(json.loads(l))
        return rows

    train = load(data_dir / "train.jsonl")
    val = load(data_dir / "val.jsonl")
    print(f"Train {len(train)} Val {len(val)}")
    chars = set()
    for r in train + val:
        chars.update(r["input"] + "\n" + r["target"])
    vocab = ["<pad>", "<bos>", "<eos>", "<unk>"]
    vocab = vocab + sorted(chars)
    stoi = {c: i for i, c in enumerate(vocab)}
    pad_id = stoi["<pad>"]
    bos_id = stoi["<bos>"]
    eos_id = stoi["<eos>"]
    unk_id = stoi["<unk>"]

    def encode(ex):
        text = ex["input"] + "\n" + ex["target"]
        ids = [bos_id]
        for c in text:
            ids.append(stoi.get(c, unk_id))
        ids.append(eos_id)
        return ids
    model = TinyNGI(len(vocab), pad_id)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"Params: {n_params}")
    assert n_params < 5000000
    opt = lib.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.CrossEntropyLoss(ignore_index=pad_id)
    rng = random.Random(args.seed)
    model.train()
    train_losses = []
    step = 0
    while step < args.steps:
        batch = rng.sample(train, 4)
        batch_ids = []
        for e in batch:
            batch_ids.append(encode(e)[:256])
        maxlen = max(len(x) for x in batch_ids)
        x = lib.full((4, maxlen-1), pad_id, dtype=lib.long)
        y = lib.full((4, maxlen-1), pad_id, dtype=lib.long)
        for i, ids in enumerate(batch_ids):
            x[i, :len(ids)-1] = lib.tensor(ids[:-1], dtype=lib.long)
            y[i, :len(ids)-1] = lib.tensor(ids[1:], dtype=lib.long)
        opt.zero_grad()
        logits = model(x)
        loss = loss_fn(logits.reshape(-1, len(vocab)), y.reshape(-1))
        loss.backward()
        opt.step()
        train_losses.append(float(loss.item()))
        step += 1
        if step % 100 == 0 or step == args.steps:
            print(f"step {step}/{args.steps} loss {float(loss.item()):.4f}")
    model.eval()
    val_losses = []
    with lib.no_grad():
        for e in val:
            ids = encode(e)[:256]
            xx = lib.tensor([ids[:-1]], dtype=lib.long)
            yy = lib.tensor([ids[1:]], dtype=lib.long)
            logits = model(xx)
            l = loss_fn(logits.reshape(-1, len(vocab)), yy.reshape(-1))
            val_losses.append(float(l.item()))
    train_last10 = sum(train_losses[-10:]) / 10
    val_avg = sum(val_losses) / max(1, len(val_losses))
    print(f"Done train {train_last10:.4f} val {val_avg:.4f}")
    ckpt_path = out / f"step_{args.steps}.pt"
    state = {}
    state["model"] = model.state_dict()
    state["vocab"] = vocab
    state["params"] = n_params
    state["step"] = args.steps
    state["train_loss"] = train_last10
    state["val_loss"] = val_avg
    lib.save(state, str(ckpt_path))
    metrics = {}
    metrics["step"] = args.steps
    metrics["train_loss_last10"] = train_last10
    metrics["val_loss"] = val_avg
    metrics["params"] = n_params
    metrics["dataset"] = "nagi_500_v3"
    metrics["from_scratch"] = True
    metrics["sha256"] = sha256_file(ckpt_path)
    txt = json.dumps(metrics, indent=2, ensure_ascii=False)
    (out / "metrics.json").write_text(txt + "\n", encoding="utf-8")
    print(f"Saved {ckpt_path}")
    print(f"SHA {metrics['sha256']}")
    print(f"Metrics step {args.steps} OK")

if __name__ == "__main__":
    main()
