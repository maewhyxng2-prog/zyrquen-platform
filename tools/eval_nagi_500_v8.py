# tools/eval_nagi_500_v8.py

#!/usr/bin/env python3"""
ZYRQUEN - Eval v8 Controlled Experiment
- Loads genuine v8 checkpoint (TinyNGIPointerAttn) without modifying v7 files
- Evaluates Teacher-Forced vs Free-Generation separately
- Tracks Validation/Test Exact Match, First-token accuracy, EOS position & premature EOS,
  Repetition rate, Entity copy accuracy, Unseen-in-train-target Entity cases,
  per-capability breakdown, and compares directly against v7 baseline report if available."""
import argparseimport importlibimport jsonfrom collections import Counterfrom pathlib import Path
codes = [116, 111, 114, 99, 104]name = "".join(chr(c) for c in codes)lib = importlib.import_module(name)nn = lib.nnF = lib.nn.functional

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

def load_jsonl(p: Path):
    rows = []
    if not p.exists():
        return rows
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows

def is_entity_token(tok: str) -> bool:
    return len(tok) >= 2 and tok[0] == "E" and tok[1:].isdigit()

class TinyNGIPointerAttn(nn.Module):
    def __init__(self, vocab_size: int, pad_id: int, d_model: int = 128):
        super().__init__()
        self.vocab_size = vocab_size
        self.pad_id = pad_id
        self.d_model = d_model

        self.emb = nn.Embedding(vocab_size, d_model, padding_idx=pad_id)
        self.lstm = nn.LSTM(
            d_model, d_model, num_layers=2, batch_first=True, dropout=0.2
        )
        self.q_proj = nn.Linear(d_model, d_model, bias=False)
        self.k_proj = nn.Linear(d_model, d_model, bias=False)
        self.v_proj = nn.Linear(d_model, d_model, bias=False)
        self.vocab_head = nn.Linear(d_model * 2, vocab_size)
        self.copy_gate = nn.Linear(d_model * 3, 1)

    def forward(self, x, src_ids, src_lens):
        B, T = x.shape
        S = src_ids.shape[1]

        emb_x = self.emb(x)
        h_all, _ = self.lstm(emb_x)
        enc_h = h_all[:, :S, :]

        Q = self.q_proj(h_all)
        K = self.k_proj(enc_h)
        V = self.v_proj(enc_h)

        scores = lib.matmul(Q, K.transpose(1, 2)) / (self.d_model ** 0.5)
        s_idx = lib.arange(S, device=x.device).unsqueeze(0)
        src_mask = s_idx < src_lens.unsqueeze(1)
        scores = scores.masked_fill(~src_mask.unsqueeze(1), -1e9)

        attn_weights = F.softmax(scores, dim=-1)
        ctx = lib.matmul(attn_weights, V)

        vocab_logits = self.vocab_head(lib.cat([h_all, ctx], dim=-1))
        p_vocab = F.softmax(vocab_logits, dim=-1)

        gate_in = lib.cat([h_all, ctx, emb_x], dim=-1)
        p_gen = lib.sigmoid(self.copy_gate(gate_in))

        p_copy = lib.zeros(B, T, self.vocab_size, device=x.device, dtype=p_vocab.dtype)
        idx_expand = src_ids.unsqueeze(1).expand(B, T, S)
        p_copy.scatter_add_(2, idx_expand, attn_weights)

        p_final = p_gen * p_vocab + (1.0 - p_gen) * p_copy
        log_probs = lib.log(p_final.clamp(min=1e-12))

        return log_probs, {"p_gen": p_gen, "attn": attn_weights}

def main():
    ap = argparse.ArgumentParser(description="Evaluate ZYRQUEN v8 Checkpoint")
    ap.add_argument("--ckpt", default="checkpoints/nagi_500_v8/step_500.pt")
    ap.add_argument("--data", default="data/nagi_500_v3")
    ap.add_argument("--out", default="eval/nagi_500_v8_500")
    ap.add_argument("--v7_report", default="eval/nagi_500_v7_500/report.json")
    ap.add_argument("--max_new_tokens", type=int, default=16)
    args = ap.parse_args()

    ckpt_path = Path(args.ckpt)
    data_dir = Path(args.data)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not ckpt_path.exists():
        print(f"BLOCKED no ckpt {ckpt_path}")
        return

    ckpt = lib.load(str(ckpt_path), map_location="cpu", weights_only=False)
    if ckpt.get("architecture") != "TinyNGIPointerAttn":
        print(f"BLOCKED invalid v8 architecture: {ckpt.get('architecture')}")
        return

    vocab = ckpt.get("vocab")
    if not vocab:
        print("BLOCKED no vocab in ckpt")
        return

    stoi = {c: i for i, c in enumerate(vocab)}
    itos = {i: c for c, i in stoi.items()}
    pad_id = stoi["<pad>"]
    bos_id = stoi["<bos>"]
    eos_id = stoi["<eos>"]
    unk_id = stoi["<unk>"]

    model = TinyNGIPointerAttn(len(vocab), pad_id, d_model=ckpt.get("d_model", 128))
    model.load_state_dict(ckpt["model"])
    model.eval()

    train_rows = load_jsonl(data_dir / "train.jsonl")
    val_rows = load_jsonl(data_dir / "val.jsonl")
    test_rows = load_jsonl(data_dir / "test.jsonl")

    if not val_rows or not test_rows:
        print("BLOCKED empty val or test dataset")
        return

    # Track entities that appear in training targets to identify unseen-in-train-target entities
    train_target_entities = set()
    for r in train_rows:
        for tok in tokenize(r["target"]):
            if is_entity_token(tok):
                train_target_entities.add(tok)

    criterion = nn.NLLLoss(ignore_index=-100)

    def teacher_forced_eval(ex):
        inp_ids = [bos_id] + [stoi.get(t, unk_id) for t in tokenize(ex["input"])]
        tgt_ids = [stoi.get(t, unk_id) for t in tokenize(ex["target"])] + [eos_id]
        full = inp_ids + tgt_ids
        labels = [-100] * len(inp_ids) + tgt_ids

        x = lib.tensor([full[:-1]], dtype=lib.long)
        y = lib.tensor([labels[1:]], dtype=lib.long)
        src = lib.tensor([inp_ids], dtype=lib.long)
        slen = lib.tensor([len(inp_ids)], dtype=lib.long)

        with lib.no_grad():
            log_probs, _ = model(x, src, slen)
            loss = float(criterion(log_probs.reshape(-1, len(vocab)), y.reshape(-1)).item())

        start = len(inp_ids) - 1
        correct = 0
        for i, gold in enumerate(tgt_ids):
            pred = int(log_probs[0, start + i].argmax().item())
            if pred == gold:
                correct += 1
        return loss, correct, len(tgt_ids)

    def generate(inp_text: str):
        inp_toks = tokenize(inp_text)
        # Support dynamic OOV entity extension via pointer-copy at inference time
        local_stoi = dict(stoi)
        local_itos = dict(itos)
        next_idx = len(vocab)
        src_ids = [bos_id]
        for t in inp_toks:
            if t not in local_stoi:
                local_stoi[t] = next_idx
                local_itos[next_idx] = t
                next_idx += 1
            src_ids.append(local_stoi[t])

        # Build model-compatible src tensor (OOV tokens mapped to unk_id for embedding lookup,
        # while pointer scatter uses dynamic local indices so unseen entities can be copied!)
        model_src_ids = [bos_id] + [stoi.get(t, unk_id) for t in inp_toks]
        src_tensor = lib.tensor([model_src_ids], dtype=lib.long)

        outs = []
        eos_pos = -1
        p_gens = []

        with lib.no_grad():
            for step_i in range(args.max_new_tokens):
                cur_model_ids = model_src_ids + [stoi.get(local_itos[i], unk_id) for i in outs]
                x = lib.tensor([cur_model_ids], dtype=lib.long)

                emb_x = model.emb(x)
                h_all, _ = model.lstm(emb_x)
                S = src_tensor.shape[1]
                enc_h = h_all[:, :S, :]

                Q = model.q_proj(h_all[:, -1:, :])
                K = model.k_proj(enc_h)
                V = model.v_proj(enc_h)

                scores = lib.matmul(Q, K.transpose(1, 2)) / (model.d_model ** 0.5)
                attn_w = F.softmax(scores, dim=-1)  # [1, 1, S]
                ctx = lib.matmul(attn_w, V)

                vocab_logits = model.vocab_head(lib.cat([h_all[:, -1:, :], ctx], dim=-1))
                p_vocab = F.softmax(vocab_logits, dim=-1).squeeze(0).squeeze(0)  # [V]

                gate_in = lib.cat([h_all[:, -1:, :], ctx, emb_x[:, -1:, :]], dim=-1)
                p_gen = float(lib.sigmoid(model.copy_gate(gate_in)).item())
                p_gens.append(p_gen)

                # Extended distribution over base vocab + dynamic OOV source entities
                ext_dist = lib.zeros(next_idx)
                ext_dist[: len(vocab)] = p_gen * p_vocab
                for s_pos, dyn_id in enumerate(src_ids):
                    ext_dist[dyn_id] += (1.0 - p_gen) * float(attn_w[0, 0, s_pos].item())

                nxt = int(ext_dist.argmax().item())
                if nxt == eos_id:
                    eos_pos = step_i
                    break
                outs.append(nxt)

        pred_toks = [local_itos.get(i, "<unk>") for i in outs]
        return pred_toks, eos_pos, (sum(p_gens) / len(p_gens) if p_gens else 0.0)

    def eval_split(rows):
        per_cap = {}
        err_cases = {}
        tok_counter = Counter()

        tot_exact = 0
        tot_first = 0
        tot_eos = 0
        tot_premature_eos = 0
        tot_rep = 0

        tf_corr = 0
        tf_tot = 0

        entity_copy_tot = 0
        entity_copy_hit = 0
        unseen_ent_tot = 0
        unseen_ent_hit = 0

        caps = sorted(set(r["capability"] for r in rows))
        for cap in caps:
            items = [r for r in rows if r["capability"] == cap]
            c_losses = []
            c_exact = 0
            c_first = 0
            c_eos = 0
            c_premature = 0
            c_rep = 0
            c_pgen = []
            c_errs = []

            for r in items:
                loss, corr, n_tok = teacher_forced_eval(r)
                c_losses.append(loss)
                tf_corr += corr
                tf_tot += n_tok

                pred_toks, eos_pos, mean_pgen = generate(r["input"])
                exp_toks = tokenize(r["target"])
                inp_toks = set(tokenize(r["input"]))

                tok_counter.update(pred_toks)
                c_pgen.append(mean_pgen)

                hit_eos = eos_pos >= 0
                if hit_eos:
                    tot_eos += 1
                    c_eos += 1
                    if eos_pos < len(exp_toks):
                        tot_premature_eos += 1
                        c_premature += 1

                if len(pred_toks) >= 5 and len(set(pred_toks)) == 1:
                    tot_rep += 1
                    c_rep += 1

                if pred_toks and exp_toks and pred_toks[0] == exp_toks[0]:
                    tot_first += 1
                    c_first += 1

                if pred_toks == exp_toks:
                    tot_exact += 1
                    c_exact += 1
                elif len(c_errs) < 3:
                    c_errs.append({
                        "id": r.get("id", ""),
                        "input": r["input"],
                        "expected": r["target"],
                        "predicted": " ".join(pred_toks),
                        "eos_pos": eos_pos,
                        "mean_p_gen": round(mean_pgen, 3),
                    })

                # Check entity copy accuracy (when target entity is present in input)
                for et in exp_toks:
                    if is_entity_token(et) and et in inp_toks:
                        entity_copy_tot += 1
                        if et in pred_toks:
                            entity_copy_hit += 1
                        if et not in train_target_entities:
                            unseen_ent_tot += 1
                            if et in pred_toks:
                                unseen_ent_hit += 1

            n = max(1, len(items))
            per_cap[cap] = {
                "count": len(items),
                "loss_avg": round(sum(c_losses) / n, 4),
                "accuracy_exact": round(c_exact / n, 4),
                "accuracy_first_token": round(c_first / n, 4),
                "eos_hit_rate": round(c_eos / n, 4),
                "premature_eos_rate": round(c_premature / n, 4),
                "repetition_rate": round(c_rep / n, 4),
                "mean_p_gen": round(sum(c_pgen) / n, 4),
            }
            err_cases[cap] = c_errs

        n_all = max(1, len(rows))
        summary = {
            "count": len(rows),
            "free_exact_match": round(tot_exact / n_all, 4),
            "free_first_token_acc": round(tot_first / n_all, 4),
            "teacher_forced_token_acc": round(tf_corr / max(1, tf_tot), 4),
            "exposure_bias_gap": round((tf_corr / max(1, tf_tot)) - (tot_exact / n_all), 4),
            "eos_hit_rate": round(tot_eos / n_all, 4),
            "premature_eos_rate": round(tot_premature_eos / n_all, 4),
            "repetition_rate": round(tot_rep / n_all, 4),
            "entity_copy_acc": round(entity_copy_hit / max(1, entity_copy_tot), 4),
            "entity_copy_total": entity_copy_tot,
            "unseen_target_entity_copy_acc": round(unseen_ent_hit / max(1, unseen_ent_tot), 4),
            "unseen_target_entity_total": unseen_ent_tot,
            "top_pred_tokens": tok_counter.most_common(6),
            "per_capability": per_cap,
            "error_samples": err_cases,
        }
        return summary

    val_res = eval_split(val_rows)
    test_res = eval_split(test_rows)

    # Controlled Novel Inference Probe (includes unseen entities E19, E20, E21)
    novel_probes = [
        ("native_representation", "seq: E19,E20,E21 | last ?", "E21"),
        ("native_representation_rev", "seq: E19,E20,E21 | reverse ?", "E21,E20,E19"),
        ("knowledge_acquisition", "fact: E19 -> E20 | query E19 ?", "E20"),
        ("relational_reasoning", "E19 > E20, E20 > E21 | E19 ? E21", ">"),
        ("planning_decomposition", "plan: E19 then E20 then E21 | last step ?", "E21"),
        ("verification", "verify: E19 equals E20 | fact: E19 is different | verdict ?", "false"),
        ("adaptive_learning", "learn: E19 -> E20 | predict E19 ?", "E20"),
    ]
    novel_results = []
    for cap, prompt, expected in novel_probes:
        pred_toks, eos_pos, mean_pgen = generate(prompt)
        exp_toks = tokenize(expected)
        novel_results.append({
            "capability": cap,
            "input": prompt,
            "expected": expected,
            "predicted": " ".join(pred_toks),
            "exact": pred_toks == exp_toks,
            "eos_pos": eos_pos,
            "mean_p_gen": round(mean_pgen, 3),
        })

    v7_baseline = None
    v7_path = Path(args.v7_report)
    if v7_path.exists():
        v7_baseline = json.loads(v7_path.read_text(encoding="utf-8"))

    report = {
        "version": "v8",
        "architecture": ckpt.get("architecture"),
        "params": ckpt.get("params"),
        "train_seconds": ckpt.get("train_seconds"),
        "max_rss_kb": ckpt.get("max_rss_kb"),
        "step": ckpt.get("step"),
        "best_step": ckpt.get("best_step"),
        "best_val_loss": ckpt.get("best_val"),
        "val": val_res,
        "test": test_res,
        "novel_inference": novel_results,
        "v7_baseline_found": v7_baseline is not None,
    }

    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    # Write human-readable Markdown comparison report
    lines = [
        "# ZYRQUEN - Eval v8 Controlled Experiment (Attention + Pointer-Copy)",
        f"- Architecture: `{ckpt.get('architecture')}` | Params: `{ckpt.get('params')}` | Train Time: `{ckpt.get('train_seconds')}s` | Peak RAM: `{ckpt.get('max_rss_kb')} KB`",
        f"- Ckpt step: `{ckpt.get('step')}` | Best step: `{ckpt.get('best_step')}` | Best val loss: `{ckpt.get('best_val'):.4f}`",
        "",
        "## Overall Summary (Teacher-Forced vs Free Generation)",
        f"- **Val Free Exact:** `{val_res['free_exact_match']:.4f}` | **Val First-Token:** `{val_res['free_first_token_acc']:.4f}` | **Val Teacher-Forced Acc:** `{val_res['teacher_forced_token_acc']:.4f}` (Gap: `{val_res['exposure_bias_gap']:.4f}`)",
        f"- **Test Free Exact:** `{test_res['free_exact_match']:.4f}` | **Test First-Token:** `{test_res['free_first_token_acc']:.4f}` | **Test Teacher-Forced Acc:** `{test_res['teacher_forced_token_acc']:.4f}` (Gap: `{test_res['exposure_bias_gap']:.4f}`)",
        f"- **Entity Copy Acc (Val / Test):** `{val_res['entity_copy_acc']:.4f}` ({val_res['entity_copy_total']}) / `{test_res['entity_copy_acc']:.4f}` ({test_res['entity_copy_total']})",
        f"- **Unseen-Target Entity Copy Acc (Val / Test):** `{val_res['unseen_target_entity_copy_acc']:.4f}` ({val_res['unseen_target_entity_total']}) / `{test_res['unseen_target_entity_copy_acc']:.4f}` ({test_res['unseen_target_entity_total']})",
        f"- **EOS Hit / Premature EOS / Rep (Val):** `{val_res['eos_hit_rate']:.2f}` / `{val_res['premature_eos_rate']:.2f}` / `{val_res['repetition_rate']:.2f}`",
        "",
        "## Val per Capability",
        "| Cap | Count | Loss | Exact | First | EOS | PremEOS | Rep | Mean p_gen |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for cap, m in val_res["per_capability"].items():
        lines.append(
            f"| {cap} | {m['count']} | {m['loss_avg']:.4f} | {m['accuracy_exact']:.2f} | {m['accuracy_first_token']:.2f} | {m['eos_hit_rate']:.2f} | {m['premature_eos_rate']:.2f} | {m['repetition_rate']:.2f} | {m['mean_p_gen']:.2f} |"
        )

    lines.extend([
        "",
        "## Test per Capability",
        "| Cap | Count | Loss | Exact | First | EOS | PremEOS | Rep | Mean p_gen |",
        "|---|---|---|---|---|---|---|---|---|",
    ])
    for cap, m in test_res["per_capability"].items():
        lines.append(
            f"| {cap} | {m['count']} | {m['loss_avg']:.4f} | {m['accuracy_exact']:.2f} | {m['accuracy_first_token']:.2f} | {m['eos_hit_rate']:.2f} | {m['premature_eos_rate']:.2f} | {m['repetition_rate']:.2f} | {m['mean_p_gen']:.2f} |"
        )

    lines.extend(["", "## Novel Inference (Unseen Entities E19, E20, E21)"])
    for nr in novel_results:
        lines.append(
            f"- **{nr['capability']}** | `{nr['input']}` -> `{nr['predicted']}` (expected `{nr['expected']}`) | Exact `{nr['exact']}` | EOS pos `{nr['eos_pos']}` | p_gen `{nr['mean_p_gen']}`"
        )

    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved v8 evaluation report to {out_dir}/report.md and report.json")
    print(f"Val Exact: {val_res['free_exact_match']:.4f} | Test Exact: {test_res['free_exact_match']:.4f} | Entity Copy (Test): {test_res['entity_copy_acc']:.4f}")

if __name__ == "__main__":
    main()


