#!/usr/bin/env python3
"""
ZYRQUEN - Native Training 100 Steps (Experiment Only)
Approved: 100 Steps only. CPU only. No auto-promote. No deploy.
Weights are local only - DO NOT commit/push checkpoints.
"""
import argparse
import json
import hashlib
import sys
from pathlib import Path

# Hard caps - approved scope
MAX_PARAMS = 5_000_000
MAX_SEQ = 256
MAX_BATCH = 4
APPROVED_STEPS = 100

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/nagi_500")
    ap.add_argument("--steps", type=int, default=100)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--seq", type=int, default=256)
    ap.add_argument("--out", default="checkpoints/nagi_100")
    args = ap.parse_args()

    if args.steps != APPROVED_STEPS:
        print(f"BLOCKED: Approved only {APPROVED_STEPS} steps, got {args.steps}")
        print("Do not run 200/300/400/500 until 100-step evaluation is approved.")
        sys.exit(1)
    if args.batch > MAX_BATCH:
        print(f"BLOCKED: batch {args.batch} > cap {MAX_BATCH}")
        sys.exit(1)
    if args.seq > MAX_SEQ:
        print(f"BLOCKED: seq {args.seq} > cap {MAX_SEQ}")
        sys.exit(1)

    try:
        import torch
        import torch.nn as nn
    except ImportError:
        print("BLOCKED: torch not found in this environment.")
        print("Do NOT pip install automatically. Check Codespaces environment first.")
        print("Run: python3 -c 'import torch; print(torch.__version__)' to verify.")
        sys.exit(1)

    device = torch.device("cpu")
    print(f"Device: CPU only | Steps: {args.steps} | Batch: {args.batch} | Seq: {args.seq}")

    data_dir = Path(args.data)
    train_path = data_dir / "train.jsonl"
    val_path = data_dir / "val.jsonl"
    if not train_path.exists() or not val_path.exists():
        print(f"BLOCKED: Dataset not found in {data_dir}. Run tools/gen_ngi_500.py first.")
        sys.exit(1)

    def load(p):
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    train = load(train_path)
    val = load(val_path)
    print(f"Train: {len(train)}  Val: {len(val)}")

    # Vocab - char-level from dataset only, no external data
    chars = set()
    for ex in train + val:
        chars.update(ex["input"])
        chars.update(ex["target"])
    vocab = ["<pad>", "<bos>", "<eos>", "<unk>"] + sorted(chars)
    stoi = {c: i for i, c in enumerate(vocab)}
    pad_id = stoi["<pad>"]

    def encode(ex):
        text = ex["input"] + "\n" + ex["target"]
        ids = [stoi["<bos>"]] + [stoi.get(c, stoi["<unk>"]) for c in text] + [stoi["<eos>"]]
        ids = ids[:args.seq]
        ids = ids + [pad_id] * (args.seq - len(ids)) if len(ids) < args.seq else ids
        return ids[:args.seq]

    train_ids = [encode(e) for e in train]
    val_ids = [encode(e) for e in val]

    # Tiny model - must stay under 5M params
    class TinyNGI(nn.Module):
        def __init__(self, vocab_size):
            super().__init__()
            self.emb = nn.Embedding(vocab_size, 128, padding_idx=pad_id)
            self.lstm = nn.LSTM(128, 128, num_layers=2, batch_first=True)
            self.head = nn.Linear(128, vocab_size)
        def forward(self, x):
            h = self.emb(x)
            o, _ = self.lstm(h)
            return self.head(o)

    model = TinyNGI(len(vocab)).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"Params: {n_params} / {MAX_PARAMS}")
    if n_params > MAX_PARAMS:
        print(f"BLOCKED: Params {n_params} > cap {MAX_PARAMS}")
        sys.exit(1)

    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.CrossEntropyLoss(ignore_index=pad_id)
    g = torch.Generator().manual_seed(42)

    model.train()
    train_losses = []
    for step in range(1, args.steps + 1):
        idx = torch.randint(0, len(train_ids), (args.batch,), generator=g)
        batch = torch.tensor([train_ids[i] for i in idx], dtype=torch.long)
        x = batch[:, :-1].to(device)
        y = batch[:, 1:].to(device)
        logits = model(x)
        loss = loss_fn(logits.reshape(-1, len(vocab)), y.reshape(-1))
        opt.zero_grad()
        loss.backward()
        opt.step()
        train_losses.append(float(loss.item()))
        if step % 10 == 0 or step == 1:
            print(f"step {step:3d}/{args.steps}  loss {float(loss.item()):.4f}")

    # Val evaluation - no training on val
    model.eval()
    val_losses = []
    with torch.no_grad():
        for i in range(0, len(val_ids), args.batch):
            chunk = val_ids[i:i+args.batch]
            batch = torch.tensor(chunk, dtype=torch.long)
            # pad to batch max already seq length
            x = batch[:, :-1].to(device)
            y = batch[:, 1:].to(device)
            logits = model(x)
            loss = loss_fn(logits.reshape(-1, len(vocab)), y.reshape(-1))
            val_losses.append(float(loss.item()))
    val_loss = sum(val_losses) / max(1, len(val_losses))
    train_loss = sum(train_losses[-10:]) / min(10, len(train_losses))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ckpt = out / "step_100.pt"
    torch.save({"model": model.state_dict(), "vocab": vocab, "step": 100, "params": n_params, "train_loss": train_loss, "val_loss": val_loss}, ckpt)
    metrics = {"step": 100, "params": n_params, "train_loss_last10": train_loss, "val_loss": val_loss, "batch": args.batch, "seq": args.seq, "device": "cpu", "approved_scope": "100 steps only", "auto_promote": False, "checkpoint": str(ckpt)}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"OK - 100 steps done. Train loss (last10): {train_loss:.4f}  Val loss: {val_loss:.4f}")
    print(f"Checkpoint (LOCAL ONLY, DO NOT PUSH): {ckpt}")
    print(f"Metrics: {out / 'metrics.json'}")

if __name__ == "__main__":
    main()
