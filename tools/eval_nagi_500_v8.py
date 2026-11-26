#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from pathlib import Path

import torch
import torch.nn as nn


def tokenize(text: str):
    t = text.replace("->", " __ARROW__ ")
    for s in [",", "|", ":", "?", ">", "<", "="]:
        t = t.replace(s, f" {s} ")
    return ["->" if x == "__ARROW__" else x for x in t.split()]


def load_jsonl(p: Path):
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def is_entity_token(tok: str) -> bool:
    if len(tok) >= 2 and tok[0] == "E" and tok[1:].isdigit():
        return True
    parts = tok.rsplit("_e", 1)
    return len(parts) == 2 and parts[1].isdigit()


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

    def forward(self, src, trg, teacher_forcing_ratio=1.0):
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
            top1 = output.argmax(1)
            input_tok = trg[:, t] if teacher_forcing_ratio >= 1.0 else top1

        return outputs


def main():
    ap = argparse.ArgumentParser(description="Evaluate ZYRQUEN v8 Checkpoint")
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--v7_report", default="eval/nagi_500_v7_500/report.json")
    ap.add_argument("--max_len", type=int, default=20)
    args = ap.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ckpt_path = Path(args.ckpt)
    if not ckpt_path.exists():
        print(f"BLOCKED no checkpoint found at {ckpt_path}")
        return

    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    if ckpt.get("arch") != "seq2seq_attn_pointer":
        print(f"BLOCKED invalid checkpoint architecture: {ckpt.get('arch')}")
        return

    vocab = ckpt.get("vocab")
    if not vocab:
        print("BLOCKED checkpoint missing vocab")
        return

    stoi = {tok: idx for idx, tok in enumerate(vocab)}
    itos = {idx: tok for tok, idx in stoi.items()}
    pad_id = stoi["<pad>"]   # 0
    unk_id = stoi["<unk>"]   # 1
    bos_id = stoi["<bos>"]   # 2
    eos_id = stoi["<eos>"]   # 3

    hid_dim = ckpt.get("hid_dim", 128)
    emb_dim = ckpt.get("emb_dim", 128)
    enc = Encoder(len(vocab), emb_dim, hid_dim)
    dec = PointerDecoder(len(vocab), emb_dim, hid_dim)
    model = Seq2Seq(enc, dec, device).to(device)
    model_state = ckpt.get("model_state") or ckpt.get("model")
    if model_state is None:
        print("BLOCKED checkpoint missing model_state")
        return
    model.load_state_dict(model_state)
    model.eval()

    data_dir = Path(args.data)
    train_rows = load_jsonl(data_dir / "train.jsonl")
    val_rows = load_jsonl(data_dir / "val.jsonl")
    test_rows = load_jsonl(data_dir / "test.jsonl")

    if not val_rows or not test_rows:
        print(f"BLOCKED empty val or test dataset in {data_dir}")
        return

    train_target_entities = {
        tok for r in train_rows for tok in tokenize(r["target"]) if is_entity_token(tok)
    }

    criterion = nn.NLLLoss(ignore_index=pad_id)

    def calc_repetition(toks):
        return len(toks) >= 2 and (
            len(set(toks)) == 1
            or any(toks[i] == toks[i + 1] for i in range(len(toks) - 1))
        )

    def teacher_forced_eval(ex):
        exp_toks = tokenize(ex["target"])
        src_ids = [bos_id] + [stoi.get(t, unk_id) for t in tokenize(ex["input"])] + [eos_id]
        trg_ids = [bos_id] + [stoi.get(t, unk_id) for t in exp_toks] + [eos_id]
        src_t = torch.tensor([src_ids], dtype=torch.long, device=device)
        trg_t = torch.tensor([trg_ids], dtype=torch.long, device=device)
        with torch.no_grad():
            probs = model(src_t, trg_t, teacher_forcing_ratio=1.0)
            log_probs = torch.log(probs[:, 1:, :].clamp(min=1e-12))
            loss = criterion(log_probs.reshape(-1, len(vocab)), trg_t[:, 1:].reshape(-1))
            preds = probs[:, 1:, :].argmax(dim=2).squeeze(0).tolist()
        gold = trg_ids[1:]
        corr = sum(1 for p, g in zip(preds, gold) if p == g)
        eos_pos = preds.index(eos_id) if eos_id in preds else -1
        pred_body_ids = preds[:eos_pos] if eos_pos >= 0 else preds
        pred_toks = [itos.get(p, "<unk>") for p in pred_body_ids]
        return {
            "token_corr": corr,
            "token_tot": len(gold),
            "loss": float(loss.item()),
            "pred_toks": pred_toks,
            "eos_pos": eos_pos,
            "exact": pred_toks == exp_toks,
            "first": bool(pred_toks and exp_toks and pred_toks[0] == exp_toks[0]),
            "premature_eos": 0 <= eos_pos < len(exp_toks),
            "rep": calc_repetition(pred_toks),
        }

    def free_generate(inp_text: str):
        inp_toks = tokenize(inp_text)
        # Build dynamic local vocab so pointer-copy can copy unseen entities (e.g. E19, E20, E21)
        local_stoi = dict(stoi)
        local_itos = dict(itos)
        next_idx = len(vocab)
        dyn_src_ids = [bos_id]
        for t in inp_toks:
            if t not in local_stoi:
                local_stoi[t] = next_idx
                local_itos[next_idx] = t
                next_idx += 1
            dyn_src_ids.append(local_stoi[t])
        dyn_src_ids.append(eos_id)

        model_src_ids = [bos_id] + [stoi.get(t, unk_id) for t in inp_toks] + [eos_id]
        src_t = torch.tensor([model_src_ids], dtype=torch.long, device=device)
        src_mask = src_t != pad_id

        outs = []
        eos_pos = -1
        p_gens = []

        with torch.no_grad():
            encoder_outputs, hidden = model.encoder(src_t)
            cur_tok = torch.tensor([bos_id], dtype=torch.long, device=device)

            for step_i in range(args.max_len):
                input_step = cur_tok.unsqueeze(1)
                embedded = model.decoder.embedding(input_step)
                a = model.decoder.attention(hidden, encoder_outputs, src_mask=src_mask).unsqueeze(1)
                context = torch.bmm(a, encoder_outputs)

                rnn_input = torch.cat((embedded, context), dim=2)
                output, hidden_next = model.decoder.rnn(rnn_input, hidden.unsqueeze(0))
                output = output.squeeze(1)
                context = context.squeeze(1)
                embedded = embedded.squeeze(1)
                hidden = hidden_next.squeeze(0)

                pred = model.decoder.fc_out(torch.cat((output, context, embedded), dim=1))
                vocab_dist = torch.softmax(pred, dim=1).squeeze(0)  # [V]
                p_gen_val = float(
                    torch.sigmoid(
                        model.decoder.p_gen(torch.cat((context, hidden, embedded), dim=1))
                    ).item()
                )
                p_gens.append(p_gen_val)

                attn_w = a.squeeze(0).squeeze(0)  # [src_len]
                ext_dist = torch.zeros(next_idx, device=device)
                ext_dist[: len(vocab)] = p_gen_val * vocab_dist
                for pos, dyn_id in enumerate(dyn_src_ids):
                    ext_dist[dyn_id] += (1.0 - p_gen_val) * attn_w[pos]

                nxt = int(ext_dist.argmax().item())
                if nxt == eos_id:
                    eos_pos = step_i
                    break
                outs.append(nxt)
                mapped_id = stoi.get(local_itos.get(nxt, "<unk>"), unk_id)
                cur_tok = torch.tensor([mapped_id], dtype=torch.long, device=device)

        pred_toks = [local_itos.get(i, "<unk>") for i in outs]
        mean_pgen = sum(p_gens) / len(p_gens) if p_gens else 0.0
        return pred_toks, eos_pos, mean_pgen

    def new_mode_acc():
        return {
            "exact": 0,
            "first": 0,
            "eos": 0,
            "prem": 0,
            "rep": 0,
            "eos_positions": [],
            "ent_tot": 0,
            "ent_hit": 0,
            "unseen_tot": 0,
            "unseen_hit": 0,
        }

    def update_mode_acc(acc, pred_toks, exp_toks, eos_pos, is_exact, is_first, is_prem, is_rep):
        if is_exact:
            acc["exact"] += 1
        if is_first:
            acc["first"] += 1
        if eos_pos >= 0:
            acc["eos"] += 1
            acc["eos_positions"].append(eos_pos)
            if is_prem:
                acc["prem"] += 1
        if is_rep:
            acc["rep"] += 1
        for idx, tok in enumerate(exp_toks):
            if is_entity_token(tok):
                acc["ent_tot"] += 1
                matched = idx < len(pred_toks) and pred_toks[idx] == tok
                if matched:
                    acc["ent_hit"] += 1
                if tok not in train_target_entities:
                    acc["unseen_tot"] += 1
                    if matched:
                        acc["unseen_hit"] += 1

    def finalize_mode(acc, n_items):
        n = max(1, n_items)
        eos_pos_list = acc["eos_positions"]
        return {
            "exact_match": acc["exact"] / n,
            "correct": acc["exact"],
            "first_token_acc": acc["first"] / n,
            "eos_hit_rate": acc["eos"] / n,
            "avg_eos_position": (sum(eos_pos_list) / len(eos_pos_list)) if eos_pos_list else None,
            "premature_eos_rate": acc["prem"] / n,
            "repetition_rate": acc["rep"] / n,
            "entity_copy_acc": (acc["ent_hit"] / acc["ent_tot"]) if acc["ent_tot"] > 0 else None,
            "entity_count": acc["ent_tot"],
            "unseen_entity_copy_acc": (acc["unseen_hit"] / acc["unseen_tot"]) if acc["unseen_tot"] > 0 else None,
            "unseen_entity_count": acc["unseen_tot"],
        }

    def eval_split(rows):
        per_cap = {}
        err_cases = {}
        tok_counter = Counter()

        tot_fg = new_mode_acc()
        tot_tf = new_mode_acc()
        pgen_means = []
        tf_corr = tf_tot = 0
        tf_losses = []

        caps = sorted(set(r["capability"] for r in rows))
        for cap in caps:
            items = [r for r in rows if r["capability"] == cap]
            c_fg = new_mode_acc()
            c_tf = new_mode_acc()
            c_pgens = []
            c_tf_corr = c_tf_tot = 0
            c_tf_losses = []
            err_list = []

            for r in items:
                exp_toks = tokenize(r["target"])
                tf = teacher_forced_eval(r)
                tf_corr += tf["token_corr"]
                tf_tot += tf["token_tot"]
                tf_losses.append(tf["loss"])
                c_tf_corr += tf["token_corr"]
                c_tf_tot += tf["token_tot"]
                c_tf_losses.append(tf["loss"])

                update_mode_acc(
                    c_tf, tf["pred_toks"], exp_toks, tf["eos_pos"],
                    tf["exact"], tf["first"], tf["premature_eos"], tf["rep"],
                )
                update_mode_acc(
                    tot_tf, tf["pred_toks"], exp_toks, tf["eos_pos"],
                    tf["exact"], tf["first"], tf["premature_eos"], tf["rep"],
                )

                pred_toks, eos_pos, mean_pgen = free_generate(r["input"])
                tok_counter.update(pred_toks)
                pgen_means.append(mean_pgen)
                c_pgens.append(mean_pgen)

                is_exact = pred_toks == exp_toks
                is_first = bool(pred_toks and exp_toks and pred_toks[0] == exp_toks[0])
                is_prem = 0 <= eos_pos < len(exp_toks)
                is_rep = calc_repetition(pred_toks)

                update_mode_acc(c_fg, pred_toks, exp_toks, eos_pos, is_exact, is_first, is_prem, is_rep)
                update_mode_acc(tot_fg, pred_toks, exp_toks, eos_pos, is_exact, is_first, is_prem, is_rep)

                if not is_exact and len(err_list) < 5:
                    err_list.append(
                        {
                            "id": r.get("id"),
                            "input": r["input"],
                            "expected": r["target"],
                            "predicted": " ".join(pred_toks),
                            "teacher_forced_predicted": " ".join(tf["pred_toks"]),
                            "eos_pos": eos_pos,
                            "premature_eos": is_prem,
                            "mean_p_gen": round(mean_pgen, 4),
                            "teacher_forced_loss": round(tf["loss"], 4),
                        }
                    )

            tf_metrics = finalize_mode(c_tf, len(items))
            tf_metrics["token_acc"] = c_tf_corr / max(1, c_tf_tot)
            tf_metrics["loss_avg"] = sum(c_tf_losses) / max(1, len(c_tf_losses))

            fg_metrics = finalize_mode(c_fg, len(items))
            fg_metrics["mean_p_gen"] = sum(c_pgens) / max(1, len(c_pgens))

            per_cap[cap] = {
                "count": len(items),
                "teacher_forced": tf_metrics,
                "free_generation": fg_metrics,
                "exposure_bias_gap": tf_metrics["exact_match"] - fg_metrics["exact_match"],
            }
            err_cases[cap] = err_list

        ov_tf = finalize_mode(tot_tf, len(rows))
        ov_tf["token_acc"] = tf_corr / max(1, tf_tot)
        ov_tf["loss_avg"] = sum(tf_losses) / max(1, len(tf_losses))

        ov_fg = finalize_mode(tot_fg, len(rows))
        ov_fg["mean_p_gen"] = sum(pgen_means) / max(1, len(pgen_means))

        overall = {
            "count": len(rows),
            "teacher_forced": ov_tf,
            "free_generation": ov_fg,
            "exposure_bias_gap": ov_tf["exact_match"] - ov_fg["exact_match"],
        }
        return per_cap, err_cases, overall, tok_counter

    per_val, err_val, ov_val, cnt_val = eval_split(val_rows)
    per_test, err_test, ov_test, cnt_test = eval_split(test_rows)

    novel_cases = [
        ("native_representation", "seq: E19,E00,E01 | last ?", "E01"),
        ("native_representation", "seq: E77,E88,E99 | first ?", "E77"),
        ("knowledge_acquisition", "fact: E19 -> E91 | query E19 ?", "E91"),
        ("relational_reasoning", "E19 > E20, E20 > E21 | E19 ? E21", ">"),
        ("planning_decomposition", "plan: E19 then E20 then E21 | last step ?", "E21"),
        ("verification", "verify: E19 equals E20 | fact: E19 is different | verdict ?", "false"),
        ("adaptive_learning", "learn: E19 -> E42 | predict E19 ?", "E42"),
    ]
    novel_results = []
    for cap, inp, expected in novel_cases:
        pred_toks, eos_pos, mean_pgen = free_generate(inp)
        exp_toks = tokenize(expected)
        novel_results.append(
            {
                "capability": cap,
                "input": inp,
                "expected": expected,
                "predicted": " ".join(pred_toks),
                "exact_match": pred_toks == exp_toks,
                "eos_pos": eos_pos,
                "mean_p_gen": round(mean_pgen, 4),
            }
        )

    v7_comparison = None
    v7_path = Path(args.v7_report)
    if v7_path.exists():
        try:
            v7_data = json.loads(v7_path.read_text(encoding="utf-8"))
            v7_val_ov = v7_data.get("val_overall", {})
            v7_test_ov = v7_data.get("test_overall", {})
            v7_ckpt = v7_data.get("checkpoint", {})

            def _v7_exact(per_cap_dict):
                if not isinstance(per_cap_dict, dict) or not per_cap_dict:
                    return None
                tot_c = sum(v.get("count", 0) for v in per_cap_dict.values())
                tot_ok = sum(v.get("correct", 0) for v in per_cap_dict.values())
                return (tot_ok / tot_c) if tot_c > 0 else None

            v7_val_exact = v7_val_ov.get("exact_match", _v7_exact(v7_data.get("val_per_capability")))
            v7_test_exact = v7_test_ov.get("exact_match", _v7_exact(v7_data.get("test_per_capability")))

            v7_comparison = {
                "v7_report_path": str(v7_path),
                "v7_params": v7_ckpt.get("params"),
                "v8_params": ckpt.get("params"),
                "val_exact_match": {
                    "v7": v7_val_exact,
                    "v8": ov_val["free_generation"]["exact_match"],
                    "delta": (ov_val["free_generation"]["exact_match"] - v7_val_exact)
                    if v7_val_exact is not None
                    else None,
                },
                "test_exact_match": {
                    "v7": v7_test_exact,
                    "v8": ov_test["free_generation"]["exact_match"],
                    "delta": (ov_test["free_generation"]["exact_match"] - v7_test_exact)
                    if v7_test_exact is not None
                    else None,
                },
                "val_first_token_acc": {
                    "v7": v7_val_ov.get("first_token_acc"),
                    "v8": ov_val["free_generation"]["first_token_acc"],
                },
                "test_first_token_acc": {
                    "v7": v7_test_ov.get("first_token_acc"),
                    "v8": ov_test["free_generation"]["first_token_acc"],
                },
                "val_eos_hit_rate": {
                    "v7": v7_val_ov.get("eos_hit_rate"),
                    "v8": ov_val["free_generation"]["eos_hit_rate"],
                },
                "test_eos_hit_rate": {
                    "v7": v7_test_ov.get("eos_hit_rate"),
                    "v8": ov_test["free_generation"]["eos_hit_rate"],
                },
                "val_repetition_rate": {
                    "v7": v7_val_ov.get("repetition_rate"),
                    "v8": ov_val["free_generation"]["repetition_rate"],
                },
                "test_repetition_rate": {
                    "v7": v7_test_ov.get("repetition_rate"),
                    "v8": ov_test["free_generation"]["repetition_rate"],
                },
            }
        except Exception as exc:
            v7_comparison = {"error": f"Failed to parse v7 report at {v7_path}: {exc}"}

    report = {
        "checkpoint": {
            "path": str(ckpt_path),
            "arch": ckpt.get("arch"),
            "hid_dim": hid_dim,
            "emb_dim": emb_dim,
            "step": ckpt.get("step"),
            "best_step": ckpt.get("best_step"),
            "best_val_loss": ckpt.get("best_val_loss"),
            "seed": ckpt.get("seed"),
            "params": ckpt.get("params"),
            "train_elapsed_sec": ckpt.get("elapsed_sec"),
            "peak_memory_kb": ckpt.get("max_rss_kb"),
            "vocab_size": len(vocab),
        },
        "evaluation": {
            "mode": "read-only",
            "verified_for": "v8",
            "max_len": args.max_len,
            "dataset": str(data_dir),
            "train_target_entity_count": len(train_target_entities),
        },
        "val_overall": ov_val,
        "val_per_capability": per_val,
        "val_errors": err_val,
        "val_top_tokens": cnt_val.most_common(10),
        "test_overall": ov_test,
        "test_per_capability": per_test,
        "test_errors": err_test,
        "test_top_tokens": cnt_test.most_common(10),
        "novel_unseen_entity_inference": novel_results,
        "v7_baseline_comparison": v7_comparison,
    }

    out_arg = Path(args.out)
    if out_arg.suffix == ".json":
        out_arg.parent.mkdir(parents=True, exist_ok=True)
        json_path = out_arg
        md_path = out_arg.with_suffix(".md")
    else:
        out_arg.mkdir(parents=True, exist_ok=True)
        json_path = out_arg / "report.json"
        md_path = out_arg / "report.md"

    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _fmt(val):
        return "N/A" if val is None else f"{val:.4f}"

    lines = [
        "# ZYRQUEN - Eval v8 (Seq2Seq + Attention + Pointer-Copy)\n\n",
        f"- Checkpoint: `{ckpt_path}` (arch=`{ckpt.get('arch')}`, step=`{ckpt.get('step')}`, best_step=`{ckpt.get('best_step')}`)\n",
        f"- Params: `{ckpt.get('params')}` | Train time: `{ckpt.get('elapsed_sec')}`s | Peak RAM KB: `{ckpt.get('max_rss_kb')}`\n\n",
        "## Overall Summary (Teacher-Forced vs Free-Generation)\n\n",
        "| Split | Mode | Exact Match | Tok Acc | Loss | First Token | EOS Hit | Avg EOS Pos | Prem EOS | Rep Rate | Entity Copy | Unseen Copy | Mean p_gen |\n",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n",
    ]
    for split_name, ov in [("val", ov_val), ("test", ov_test)]:
        tf = ov["teacher_forced"]
        fg = ov["free_generation"]
        lines.append(
            f"| {split_name} | teacher_forced | {_fmt(tf['exact_match'])} | {_fmt(tf['token_acc'])} | {_fmt(tf['loss_avg'])} | "
            f"{_fmt(tf['first_token_acc'])} | {_fmt(tf['eos_hit_rate'])} | {_fmt(tf['avg_eos_position'])} | "
            f"{_fmt(tf['premature_eos_rate'])} | {_fmt(tf['repetition_rate'])} | {_fmt(tf['entity_copy_acc'])} | "
            f"{_fmt(tf['unseen_entity_copy_acc'])} | N/A |\n"
        )
        lines.append(
            f"| {split_name} | free_generation | {_fmt(fg['exact_match'])} | N/A | N/A | "
            f"{_fmt(fg['first_token_acc'])} | {_fmt(fg['eos_hit_rate'])} | {_fmt(fg['avg_eos_position'])} | "
            f"{_fmt(fg['premature_eos_rate'])} | {_fmt(fg['repetition_rate'])} | {_fmt(fg['entity_copy_acc'])} | "
            f"{_fmt(fg['unseen_entity_copy_acc'])} | {_fmt(fg['mean_p_gen'])} |\n"
        )

    for split_name, per_cap in [("Validation", per_val), ("Test", per_test)]:
        lines.append(f"\n## {split_name} per Capability (Teacher-Forced vs Free-Generation)\n\n")
        lines.append(
            "| Capability | Mode | Count | Exact | Tok Acc | Loss | First | EOS Pos | Rep | Entity Copy | Unseen Copy |\n"
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
        )
        for cap, v in per_cap.items():
            tf = v["teacher_forced"]
            fg = v["free_generation"]
            lines.append(
                f"| {cap} | teacher_forced | {v['count']} | {_fmt(tf['exact_match'])} | {_fmt(tf['token_acc'])} | {_fmt(tf['loss_avg'])} | "
                f"{_fmt(tf['first_token_acc'])} | {_fmt(tf['avg_eos_position'])} | {_fmt(tf['repetition_rate'])} | "
                f"{_fmt(tf['entity_copy_acc'])} | {_fmt(tf['unseen_entity_copy_acc'])} |\n"
            )
            lines.append(
                f"| {cap} | free_generation | {v['count']} | {_fmt(fg['exact_match'])} | N/A | N/A | "
                f"{_fmt(fg['first_token_acc'])} | {_fmt(fg['avg_eos_position'])} | {_fmt(fg['repetition_rate'])} | "
                f"{_fmt(fg['entity_copy_acc'])} | {_fmt(fg['unseen_entity_copy_acc'])} |\n"
            )

    lines.append("\n## Novel Unseen-Entity Inference (Not in Train Targets)\n\n")
    for item in novel_results:
        lines.append(
            f"- **{item['capability']}** | `{item['input']}` | expected `{item['expected']}` | "
            f"predicted `{item['predicted']}` | exact={item['exact_match']} | eos_pos={item['eos_pos']} | p_gen={item['mean_p_gen']}\n"
        )

    if v7_comparison is not None:
        lines.append("\n## Baseline Comparison (v8 vs v7)\n\n")
        lines.append(f"```json\n{json.dumps(v7_comparison, indent=2, ensure_ascii=False)}\n```\n")

    md_path.write_text("".join(lines), encoding="utf-8")
    print(f"OK report written to {json_path} and {md_path}")
    print(
        f"VAL  TF_exact={ov_val['teacher_forced']['exact_match']:.4f} | "
        f"Free_exact={ov_val['free_generation']['exact_match']:.4f} | "
        f"Entity_copy={_fmt(ov_val['free_generation']['entity_copy_acc'])} | "
        f"Unseen_copy={_fmt(ov_val['free_generation']['unseen_entity_copy_acc'])}"
    )
    print(
        f"TEST TF_exact={ov_test['teacher_forced']['exact_match']:.4f} | "
        f"Free_exact={ov_test['free_generation']['exact_match']:.4f} | "
        f"Entity_copy={_fmt(ov_test['free_generation']['entity_copy_acc'])} | "
        f"Unseen_copy={_fmt(ov_test['free_generation']['unseen_entity_copy_acc'])}"
    )


if __name__ == "__main__":
    main()

