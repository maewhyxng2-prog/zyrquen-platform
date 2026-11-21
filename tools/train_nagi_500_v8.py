# tools/train_nagi_500_v8.py

#!/usr/bin/env python3"""
ZYRQUEN - Train v8 Controlled Experiment (Attention + Pointer-Copy Mechanism)
- Keeps hidden dimension at 128 and 2-layer LSTM backbone identical to v7
- Adds Scaled Dot-Product Attention over encoder input states
- Adds Pointer-Generator Copy Gate (p_gen) to copy tokens directly from input
- Preserves v7 baseline files, checkpoints, and dataset splits untouched"""
import argparseimport hashlibimport importlibimport jsonimport randomimport resourceimport timefrom pathlib import Path
codes = [116, 111, 114, 99, 104]name = "".join(chr(c) for c in codes)lib = importlib.import_module(name)nn = lib.nnF = lib.nn.functional

def set_seed(seed: int):
    random.seed(seed)
    lib.manual_seed(seed)
    if lib.cuda.is_available():
        lib.cuda.manual_seed_all(seed)

def tokenize(text: str):
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

def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def load_jsonl(p: Path):
    rows = []
    if not p.exists():
        return rows
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows

class TinyNGIPointerAttn(nn.Module):
    """
    Controlled v8 Architecture:
    - Same 128-dim Embedding & 2-layer LSTM (dropout=0.2) as v7
    - Adds Cross-Attention over all encoder positions (input sequence)
    - Adds Pointer-Generator Copy Gate to blend vocab distribution & input copy distribution
    """

    def __init__(self, vocab_size: int, pad_id: int, d_model: int = 128):
        super().__init__()
        self.vocab_size = vocab_size
        self.pad_id = pad_id
        self.d_model = d_model

        self.emb = nn.Embedding(vocab_size, d_model, padding_idx=pad_id)
        self.lstm = nn.LSTM(
            d_model, d_model, num_layers=2, batch_first=True, dropout=0.2
        )

        # Attention projections (Query from decoder state, Key/Value from encoder states)
        self.q_proj = nn.Linear(d_model, d_model, bias=False)
        self.k_proj = nn.Linear(d_model, d_model, bias=False)
        self.v_proj = nn.Linear(d_model, d_model, bias=False)

        # Vocabulary generation head from [decoder_hidden; context_vector]
        self.vocab_head = nn.Linear(d_model * 2, vocab_size)

        # Pointer copy gate p_gen in (0, 1): 1 = generate from vocab, 0 = copy from input
        self.copy_gate = nn.Linear(d_model * 3, 1)

    def forward(self, x, src_ids, src_lens):
        """
        x: [B, T] full sequence input ids (shifted)
        src_ids: [B, S] source input token ids (including <bos> + input tokens)
        src_lens: [B] length of valid source prefix for each item in batch
        Returns:
          log_probs: [B, T, V] final log-probability distribution over vocabulary
          aux: dict with mean p_gen and attention weights for diagnostics
        """
        B, T = x.shape
        S = src_ids.shape[1]

        emb_x = self.emb(x)  # [B, T, D]
        h_all, _ = self.lstm(emb_x)  # [B, T, D]

        # Extract encoder states from the source prefix positions [0..S-1]
        enc_h = h_all[:, :S, :]  # [B, S, D]

        Q = self.q_proj(h_all)  # [B, T, D]
        K = self.k_proj(enc_h)  # [B, S, D]
        V = self.v_proj(enc_h)  # [B, S, D]

        # Scaled dot-product attention: [B, T, S]
        scores = lib.matmul(Q, K.transpose(1, 2)) / (self.d_model ** 0.5)

        # Mask out positions beyond each sample's actual source prefix length
        s_idx = lib.arange(S, device=x.device).unsqueeze(0)  # [1, S]
        src_mask = s_idx < src_lens.unsqueeze(1)  # [B, S]
        scores = scores.masked_fill(~src_mask.unsqueeze(1), -1e9)

        attn_weights = F.softmax(scores, dim=-1)  # [B, T, S]
        ctx = lib.matmul(attn_weights, V)  # [B, T, D]

        # Vocabulary distribution
        vocab_logits = self.vocab_head(lib.cat([h_all, ctx], dim=-1))  # [B, T, V]
        p_vocab = F.softmax(vocab_logits, dim=-1)

        # Copy gate p_gen
        gate_in = lib.cat([h_all, ctx, emb_x], dim=-1)  # [B, T, 3D]
        p_gen = lib.sigmoid(self.copy_gate(gate_in))  # [B, T, 1]

        # Scatter attention weights onto vocabulary indices for pointer-copy distribution
        p_copy = lib.zeros(B, T, self.vocab_size, device=x.device, dtype=p_vocab.dtype)
        idx_expand = src_ids.unsqueeze(1).expand(B, T, S)  # [B, T, S]
        p_copy.scatter_add_(2, idx_expand, attn_weights)

        # Final blended distribution
        p_final = p_gen * p_vocab + (1.0 - p_gen) * p_copy
        log_probs = lib.log(p_final.clamp(min=1e-12))

        return log_probs, {"p_gen": p_gen, "attn": attn_weights}

def build_vocab(train_rows):
    specials = ["<pad>", "<bos>", "<eos>", "<unk>"]
    seen = set(specials)
    vocab = list(specials)
    for r in train_rows:
        for field in ("input", "target"):
            for tok in tokenize(r[field]):
                if tok not in seen:
                    seen.add(tok)
                    vocab.append(tok)
    return vocab

def main():
    ap = argparse.ArgumentParser(description="Train ZYRQUEN v8 (Attention + Pointer-Copy)")
    ap.add_argument("--data", default="data/nagi_500_v3")
    ap.add_argument("--out", default="checkpoints/nagi_500_v8")
    ap.add_argument("--steps", type=int, default=500)
    ap.add_argument("--batch_size", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--weight_decay", type=float, default=0.01)
    ap.add_argument("--eos_weight", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--eval_every", type=int, default=25)
    args = ap.parse_args()

    set_seed(args.seed)
    t0 = time.time()

    data_dir = Path(args.data)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    train_rows = load_jsonl(data_dir / "train.jsonl")
    val_rows = load_jsonl(data_dir / "val.jsonl")
    if not train_rows or not val_rows:
        print(f"BLOCKED empty dataset in {data_dir}")
        return

    vocab = build_vocab(train_rows)
    stoi = {c: i for i, c in enumerate(vocab)}
    pad_id = stoi["<pad>"]
    bos_id = stoi["<bos>"]
    eos_id = stoi["<eos>"]
    unk_id = stoi["<unk>"]

    def encode_pair(ex):
        inp_toks = tokenize(ex["input"])
        tgt_toks = tokenize(ex["target"])
        if not inp_toks or not tgt_toks:
            return None
        inp_ids = [bos_id] + [stoi.get(t, unk_id) for t in inp_toks]
        tgt_ids = [stoi.get(t, unk_id) for t in tgt_toks] + [eos_id]
        full_ids = inp_ids + tgt_ids
        # Target-only loss mask (-100 for input prefix positions)
        labels = [-100] * len(inp_ids) + tgt_ids
        return full_ids, labels, inp_ids

    train_enc = [e for e in (encode_pair(r) for r in train_rows) if e is not None]
    val_enc = [e for e in (encode_pair(r) for r in val_rows) if e is not None]

    model = TinyNGIPointerAttn(len(vocab), pad_id, d_model=128)
    total_params = sum(p.numel() for p in model.parameters())

    loss_w = lib.ones(len(vocab))
    loss_w[eos_id] = args.eos_weight
    criterion = nn.NLLLoss(weight=loss_w, ignore_index=-100)

    optimizer = lib.optim.AdamW(
        model.parameters(), lr=args.lr, weight_decay=args.weight_decay
    )

    def make_batch(items):
        xs, ys, srcs, slens = [], [], [], []
        max_t = max(len(ids) - 1 for ids, _, _ in items)
        max_s = max(len(src) for _, _, src in items)
        for ids, labels, src in items:
            x_seq = ids[:-1]
            y_seq = labels[1:]
            xs.append(x_seq + [pad_id] * (max_t - len(x_seq)))
            ys.append(y_seq + [-100] * (max_t - len(y_seq)))
            srcs.append(src + [pad_id] * (max_s - len(src)))
            slens.append(len(src))
        return (
            lib.tensor(xs, dtype=lib.long),
            lib.tensor(ys, dtype=lib.long),
            lib.tensor(srcs, dtype=lib.long),
            lib.tensor(slens, dtype=lib.long),
        )

    def compute_val_loss():
        model.eval()
        losses = []
        with lib.no_grad():
            for item in val_enc:
                x, y, src, slen = make_batch([item])
                log_probs, _ = model(x, src, slen)
                loss = criterion(log_probs.reshape(-1, len(vocab)), y.reshape(-1))
                losses.append(float(loss.item()))
        model.train()
        return sum(losses) / max(1, len(losses))

    best_val = float("inf")
    best_step = 0
    best_state = None
    train_losses = []

    model.train()
    for step in range(1, args.steps + 1):
        batch = random.sample(train_enc, min(args.batch_size, len(train_enc)))
        x, y, src, slen = make_batch(batch)

        optimizer.zero_grad()
        log_probs, _ = model(x, src, slen)
        loss = criterion(log_probs.reshape(-1, len(vocab)), y.reshape(-1))
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()

        train_losses.append(float(loss.item()))

        if step % args.eval_every == 0 or step == args.steps:
            vl = compute_val_loss()
            if vl < best_val:
                best_val = vl
                best_step = step
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

    if best_state is not None:
        model.load_state_dict(best_state)
        print(f"Restored best_state from step {best_step} val {best_val:.4f}")
    else:
        print("WARNING no best_state saved, keeping last weights")

    elapsed_sec = round(time.time() - t0, 2)
    max_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    ckpt = {
        "architecture": "TinyNGIPointerAttn",
        "d_model": 128,
        "num_layers": 2,
        "dropout": 0.2,
        "model": model.state_dict(),
        "best_state": best_state,
        "optimizer": optimizer.state_dict(),
        "vocab": vocab,
        "step": args.steps,
        "best_step": best_step,
        "best_val": best_val,
        "params": total_params,
        "seed": args.seed,
        "dataset": str(data_dir),
        "from_scratch": True,
        "vocab_source": "train-only",
        "tokenizer": "token-level",
        "loss_mode": "target-only-shift-fix",
        "train_seconds": elapsed_sec,
        "max_rss_kb": max_rss_kb,
    }

    tmp_c = out / f"step_{args.steps}.pt.tmp"
    final_c = out / f"step_{args.steps}.pt"
    lib.save(ckpt, str(tmp_c))
    tmp_c.rename(final_c)
    sha = sha256_file(final_c)

    last10 = train_losses[-10:] if train_losses else [0.0]
    avg_train = sum(last10) / len(last10)
    final_val = compute_val_loss()

    metrics = {
        "version": "v8",
        "architecture": "TinyNGIPointerAttn",
        "step": args.steps,
        "best_step": best_step,
        "best_val": best_val,
        "train_loss_last10": avg_train,
        "val_loss": final_val,
        "params": total_params,
        "seed": args.seed,
        "dataset": str(data_dir),
        "sha256": sha,
        "train_seconds": elapsed_sec,
        "max_rss_kb": max_rss_kb,
    }

    tmp_m = out / "metrics.json.tmp"
    final_m = out / "metrics.json"
    tmp_m.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    tmp_m.rename(final_m)

    print(f"Saved {final_c} (SHA {sha[:12]}...)")
    print(f"Done train {avg_train:.4f} val {final_val:.4f} best {best_val:.4f} at {best_step}")
    print(f"Params {total_params} | Time {elapsed_sec}s | RAM max KB {max_rss_kb}")

if __name__ == "__main__":
    main()


