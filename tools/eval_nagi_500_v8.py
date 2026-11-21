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
    return len(tok) >= 2 and tok[0] == "E" and tok[1:].isdigit()


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
    model.load_state_dict(ckpt["model_state"])
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

    def teacher_forced_eval(ex):
        src_ids = [bos_id] + [stoi.get(t, unk_id) for t in tokenize(ex["input"])] + [eos_id]
        trg_ids = [bos_id] + [stoi.get(t, unk_id) for t in tokenize(ex["target"])] + [eos_id]
        src_t = torch.tensor([src_ids], dtype=torch.long, device=device)
        trg_t = torch.tensor([trg_ids], dtype=torch.long, device=device)
        with torch.no_grad():
            probs = model(src_t, trg_t, teacher_forcing_ratio=1.0)
            preds = probs[:, 1:, :].argmax(dim=2).squeeze(0).tolist()
        gold = trg_ids[1:]
        corr = sum(1 for p, g in zip(preds, gold) if p == g)
        return corr, len(gold)

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

    def eval_split(rows):
        per_cap = {}
        err_cases = {}
        tok_counter = Counter()

        tot_exact = tot_first = tot_eos = tot_prem = tot_rep = 0
        tf_corr = tf_tot = 0
        ent_tot = ent_hit = unseen_tot = unseen_hit = 0

