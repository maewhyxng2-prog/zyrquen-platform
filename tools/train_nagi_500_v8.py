#!/usr/bin/env python3
import argparse
import hashlib
import json
import random
import resource
import time
from pathlib import Path

import torch
import torch.nn as nn
import torch.optim as optim


def set_seed(seed: int):
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def tokenize(text: str):
    t = text.replace("->", " __ARROW__ ")
    for s in [",", "|", ":", "?", ">", "<", "="]:
        t = t.replace(s, f" {s} ")
    return ["->" if x == "__ARROW__" else x for x in t.split()]


def load_jsonl(p: Path):
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build_vocab(train_rows):
    specials = ["<pad>", "<unk>", "<bos>", "<eos>"]
    seen = set(specials)
    vocab = list(specials)
    for r in train_rows:
        for field in ("input", "target"):
            for tok in tokenize(r[field]):
                if tok not in seen:
                    seen.add(tok)
                    vocab.append(tok)
    return vocab


class Encoder(nn.Module):
    def __init__(self, vocab_size, emb_dim, hid_dim):
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, emb_dim, padding_idx=0)
        self.rnn = nn.GRU(emb_dim, hid_dim, batch_first=True, bidirectional=True)
        self.fc = nn.Linear(hid_dim * 2, hid_dim)

    def forward(self, src):
        embedded = self.embedding(src)
        outputs, hidden = self.rnn(embedded)
        hidden = torch.tanh(self.fc(torch.cat((hidden[-2, :, :], hidden[-1, :, :]), dim=1)))
        return outputs, hidden


class Attention(nn.Module):
    def __init__(self, hid_dim):
        super().__init__()
        self.attn = nn.Linear(hid_dim * 3, hid_dim)
        self.v = nn.Linear(hid_dim, 1, bias=False)

    def forward(self, hidden, encoder_outputs, src_mask=None):
        src_len = encoder_outputs.shape[1]
        hidden_rep = hidden.unsqueeze(1).repeat(1, src_len, 1)
        energy = torch.tanh(self.attn(torch.cat((hidden_rep, encoder_outputs), dim=2)))
        attention = self.v(energy).squeeze(2)
        if src_mask is not None:
            attention = attention.masked_fill(~src_mask, -1e9)
        return torch.softmax(attention, dim=1)


class PointerDecoder(nn.Module):
    def __init__(self, vocab_size, emb_dim, hid_dim):
        super().__init__()
        self.vocab_size = vocab_size
        self.attention = Attention(hid_dim)
        self.embedding = nn.Embedding(vocab_size, emb_dim, padding_idx=0)
        self.rnn = nn.GRU(hid_dim * 2 + emb_dim, hid_dim, batch_first=True)
        self.fc_out = nn.Linear(hid_dim * 3 + emb_dim, vocab_size)
        self.p_gen = nn.Linear(hid_dim * 3 + emb_dim, 1)

    def forward(self, input_tok, hidden, encoder_outputs, src, src_mask=None):
        input_step = input_tok.unsqueeze(1)
        embedded = self.embedding(input_step)

        a = self.attention(hidden, encoder_outputs, src_mask=src_mask).unsqueeze(1)
        context = torch.bmm(a, encoder_outputs)

        rnn_input = torch.cat((embedded, context), dim=2)
        output, hidden = self.rnn(rnn_input, hidden.unsqueeze(0))
        output = output.squeeze(1)
        context = context.squeeze(1)
        embedded = embedded.squeeze(1)
        hidden_squeezed = hidden.squeeze(0)

        pred = self.fc_out(torch.cat((output, context, embedded), dim=1))
        vocab_dist = torch.softmax(pred, dim=1)

        p_gen = torch.sigmoid(self.p_gen(torch.cat((context, hidden_squeezed, embedded), dim=1)))

        attn_dist = a.squeeze(1)
        copy_dist = torch.zeros_like(vocab_dist).scatter_add(1, src, attn_dist)

        final_dist = p_gen * vocab_dist + (1.0 - p_gen) * copy_dist
        return final_dist, hidden_squeezed, p_gen


class Seq2Seq(nn.Module):
    def __init__(self, encoder, decoder, device):
        super().__init__()
        self.encoder = encoder
        self.decoder = decoder
        self.device = device

    def forward(self, src, trg, teacher_forcing_ratio=0.5):
        batch_size = src.shape[0]
        trg_len = trg.shape[1]
        vocab_size = self.decoder.vocab_size
        src_mask = src != 0

        outputs = torch.zeros(batch_size, trg_len, vocab_size, device=self.device)
        encoder_outputs, hidden = self.encoder(src)
        input_tok = trg[:, 0]

        for t in range(1, trg_len):
            output, hidden, _ = self.decoder(
                input_tok, hidden, encoder_outputs, src, src_mask=src_mask
            )
            outputs[:, t, :] = output
            teacher_force = random.random() < teacher_forcing_ratio
            top1 = output.argmax(1)
            input_tok = trg[:, t] if teacher_force else top1

        return outputs

    def generate(self, src, max_len=20, sos_idx=2, eos_idx=3):
        src_mask = src != 0
        encoder_outputs, hidden = self.encoder(src)
        input_tok = torch.tensor([sos_idx] * src.shape[0], device=self.device)

        preds = []
        for _ in range(max_len):
            output, hidden, _ = self.decoder(
                input_tok, hidden, encoder_outputs, src, src_mask=src_mask
            )
            top1 = output.argmax(1)
            preds.append(top1)
            input_tok = top1
            if (top1 == eos_idx).all():
                break

        return torch.stack(preds, dim=1)


def save_checkpoint(state, filename):
    torch.save(state, filename)


def main():
    ap = argparse.ArgumentParser(description="Train ZYRQUEN v8 (Seq2Seq + Attention + Pointer-Copy)")
    ap.add_argument("--data", type=str, default="data/nagi_500_v3")
    ap.add_argument("--out", type=str, default="checkpoints/nagi_500_v8")
    ap.add_argument("--steps", type=int, default=500)
    ap.add_argument("--batch_size", "--batch", dest="batch_size", type=int, default=4)
    ap.add_argument("--seq", type=int, default=256)
    ap.add_argument("--lr", type=float, default=0.001)
    ap.add_argument("--eval_every", type=int, default=50)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    set_seed(args.seed)
    t0 = time.time()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    data_dir = Path(args.data)
    train_rows = load_jsonl(data_dir / "train.jsonl")
    val_rows = load_jsonl(data_dir / "val.jsonl")
    test_rows = load_jsonl(data_dir / "test.jsonl")
    print(f"Train {len(train_rows)} Val {len(val_rows)} Test {len(test_rows)}")
    if not train_rows or not val_rows:
        print(f"BLOCKED empty dataset in {data_dir}")
        return

    empty_tgt = sum(1 for r in train_rows + val_rows if not r.get("target", "").strip())
    if empty_tgt > 0:
        print(f"BLOCKED empty target count: {empty_tgt}")
        return

    if test_rows:
        train_ids = {r["id"] for r in train_rows if "id" in r}
        test_ids = {r["id"] for r in test_rows if "id" in r}
        if train_ids & test_ids:
            print("BLOCKED train/test ID overlap detected")
            return

    vocab = build_vocab(train_rows)
    stoi = {tok: idx for idx, tok in enumerate(vocab)}
    pad_id = stoi["<pad>"]
    unk_id = stoi["<unk>"]
    bos_id = stoi["<bos>"]
    eos_id = stoi["<eos>"]
    print(f"Vocab token-level train-only {len(vocab)}")

    def encode_row(r):
        src_toks = [stoi.get(t, unk_id) for t in tokenize(r["input"])]
        trg_ids = [bos_id] + [stoi.get(t, unk_id) for t in tokenize(r["target"])] + [eos_id]
        if len(trg_ids) > args.seq:
            return None
        max_src_body = max(0, args.seq - 2)
        if len(src_toks) > max_src_body:
            src_toks = src_toks[:max_src_body]
        src_ids = [bos_id] + src_toks + [eos_id]
        return src_ids, trg_ids

    train_pairs = [p for p in (encode_row(r) for r in train_rows) if p is not None]
    val_pairs = [p for p in (encode_row(r) for r in val_rows) if p is not None]
    if not train_pairs or not val_pairs:
        print("BLOCKED no valid encoded examples within seq limit")
        return

    def make_batch(pairs):
        max_src = max(len(s) for s, _ in pairs)
        max_trg = max(len(t) for _, t in pairs)
        src_b = [s + [pad_id] * (max_src - len(s)) for s, _ in pairs]
        trg_b = [t + [pad_id] * (max_trg - len(t)) for _, t in pairs]
        return (
            torch.tensor(src_b, dtype=torch.long, device=device),
            torch.tensor(trg_b, dtype=torch.long, device=device),
        )

    HID_DIM = 128
    EMB_DIM = 128
    VOCAB_SIZE = len(vocab)
    enc = Encoder(VOCAB_SIZE, EMB_DIM, HID_DIM)
    dec = PointerDecoder(VOCAB_SIZE, EMB_DIM, HID_DIM)
    model = Seq2Seq(enc, dec, device).to(device)
    total_params = sum(p.numel() for p in model.parameters())
    assert total_params <= 5_000_000, f"Params {total_params} exceeds 5M cap"
    print(f"Model: seq2seq_attn_pointer | hid_dim={HID_DIM} | vocab={VOCAB_SIZE} | params={total_params}")

    optimizer = optim.Adam(model.parameters(), lr=args.lr, weight_decay=0.01)
    criterion = nn.NLLLoss(ignore_index=pad_id)

    def eval_val_loss():
        model.eval()
        losses = []
        with torch.no_grad():
            for pair in val_pairs:
                src, trg = make_batch([pair])
                probs = model(src, trg, teacher_forcing_ratio=1.0)
                log_probs = torch.log(probs[:, 1:, :].clamp(min=1e-12))
                loss = criterion(log_probs.reshape(-1, VOCAB_SIZE), trg[:, 1:].reshape(-1))
                losses.append(float(loss.item()))
        model.train()
        return sum(losses) / max(1, len(losses))

    global_step = 0
    best_val_loss = float("inf")
    best_step = 0
    no_improve = 0
    best_val_state = None
    best_optimizer_state = None
    train_losses = []

    for step in range(1, args.steps + 1):
        global_step = step
        model.train()
        batch = [
            train_pairs[((step - 1) * args.batch_size + i) % len(train_pairs)]
            for i in range(args.batch_size)
        ]
        src, trg = make_batch(batch)

        tf_ratio = max(0.5, 1.0 - 0.5 * (step / args.steps))
        probs = model(src, trg, teacher_forcing_ratio=tf_ratio)
        log_probs = torch.log(probs[:, 1:, :].clamp(min=1e-12))
        loss = criterion(log_probs.reshape(-1, VOCAB_SIZE), trg[:, 1:].reshape(-1))

        optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()

        train_losses.append(float(loss.item()))

        if step % args.eval_every == 0 or step == args.steps:
            val_loss = eval_val_loss()
            print(f"step {step}/{args.steps} | train_loss={float(loss.item()):.4f} | val_loss={val_loss:.4f}")
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_step = step
                best_val_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
                best_optimizer_state = optimizer.state_dict()
                no_improve = 0
            else:
                no_improve += 1
            if no_improve >= 2 and args.steps >= 500:
                print(f"Early stop at step {step}")
                break

    if best_val_state is not None:
        model.load_state_dict(best_val_state)
        print(f"Restored best_val_state from step {best_step} | best_val_loss: {best_val_loss:.4f}")
    else:
        best_val_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        best_optimizer_state = optimizer.state_dict()

    final_val_loss = eval_val_loss()
    last10 = train_losses[-10:] if train_losses else [0.0]
    avg_train_loss = sum(last10) / max(1, len(last10))

    elapsed_sec = round(time.time() - t0, 2)
    max_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_tmp = out_dir / f"step_{global_step}.pt.tmp"
    ckpt_path = out_dir / f"step_{global_step}.pt"

    save_checkpoint(
        {
            "arch": "seq2seq_attn_pointer",
            "hid_dim": HID_DIM,
            "emb_dim": EMB_DIM,
            "model": model.state_dict(),
            "model_state": model.state_dict(),
            "best_val_state": best_val_state,
            "optimizer_state": best_optimizer_state,
            "vocab": vocab,
            "vocab_source": "train-only",
            "tokenizer": "token-level",
            "loss_mode": "nll-pointer-copy",
            "dataset": str(data_dir),
            "seed": args.seed,
            "from_scratch": True,
            "step": global_step,
            "best_step": best_step,
            "best_val": best_val_loss,
            "best_val_loss": best_val_loss,
            "val_loss": final_val_loss,
            "train_loss_last10": avg_train_loss,
            "params": total_params,
            "elapsed_sec": elapsed_sec,
            "max_rss_kb": max_rss_kb,
        },
        ckpt_tmp,
    )
    ckpt_tmp.rename(ckpt_path)
    ckpt_sha = sha256_file(ckpt_path)

    metrics = {
        "arch": "seq2seq_attn_pointer",
        "hid_dim": HID_DIM,
        "emb_dim": EMB_DIM,
        "vocab_size": VOCAB_SIZE,
        "vocab_source": "train-only",
        "tokenizer": "token-level",
        "loss_mode": "nll-pointer-copy",
        "dataset": str(data_dir),
        "seed": args.seed,
        "from_scratch": True,
        "step": global_step,
        "best_step": best_step,
        "best_val": best_val_loss,
        "best_val_loss": best_val_loss,
        "val_loss": final_val_loss,
        "train_loss_last10": avg_train_loss,
        "params": total_params,
        "elapsed_sec": elapsed_sec,
        "max_rss_kb": max_rss_kb,
        "sha256": ckpt_sha,
    }
    metrics_tmp = out_dir / "metrics.json.tmp"
    metrics_path = out_dir / "metrics.json"
    metrics_tmp.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    metrics_tmp.rename(metrics_path)

    print(f"Saved {ckpt_path} (sha256={ckpt_sha})")
    print(f"Params: {total_params} | Elapsed: {elapsed_sec}s | Peak RAM KB: {max_rss_kb}")


if __name__ == "__main__":
    main()
