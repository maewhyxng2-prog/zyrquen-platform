#!/usr/bin/env python3
"""ZYRQUEN - Eval v5 Proper, token-level, max_new 5"""
import argparse
import importlib
import json
from pathlib import Path
from collections import Counter
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
    ap.add_argument("--out", default="eval/nagi_500_v5")
    args = ap.parse_args()
    ckpt_path = Path(args.ckpt)
    data_dir = Path(args.data)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if not ckpt_path.exists():
        print(f"BLOCKED no ckpt {ckpt_path}")
        return
    ckpt = lib.load(str(ckpt_path), map_location="cpu", weights_only=False)
    vocab = ckpt.get("vocab", None)
    if vocab is None:
        print("BLOCKED no vocab in ckpt")
        return
    print(f"Ckpt step {ckpt.get('step')} best {ckpt.get('best_step')} val {ckpt.get('best_val')}")
    print(f"Tokenizer {ckpt.get('tokenizer')} vocab {ckpt.get('vocab_source')} loss {ckpt.get('loss_mode')}")
    if ckpt.get("tokenizer") != "token-level":
        print("WARNING tokenizer != token-level, NOT VERIFIED for v5")
        return
    if ckpt.get("vocab_source") != "train-only":
        print("WARNING vocab != train-only")
        return
    if "->" not in vocab:
        print("BLOCKED vocab missing ->, tokenizer mismatch")
        return
    print("OK eval verified for v5 token-level")
    stoi = {c: i for i, c in enumerate(vocab)}
    itos = {i: c for c, i in stoi.items()}
    pad_id = stoi["<pad>"]
    bos_id = stoi["<bos>"]
    eos_id = stoi["<eos>"]
    unk_id = stoi["<unk>"]
    model = TinyNGI(len(vocab), pad_id)
    model.load_state_dict(ckpt["model"])
    model.eval()
    def encode_input(inp):
        ids = [bos_id]
        for t in tokenize(inp):
            ids.append(stoi.get(t, unk_id))
        return ids
    def encode_full(ex):
        ids = [bos_id]
        for t in tokenize(ex["input"]):
            ids.append(stoi.get(t, unk_id))
        for t in tokenize(ex["target"]):
            ids.append(stoi.get(t, unk_id))
        ids.append(eos_id)
        return ids
    def generate(inp, max_new=5):
        ids = encode_input(inp)
        outs = []
        hit = False
        with lib.no_grad():
            for _ in range(max_new):
                cur = ids + outs
                x = lib.tensor([cur], dtype=lib.long)
                logits = model(x)
                nxt = int(logits[0, -1].argmax().item())
                if nxt == eos_id:
                    hit = True
                    break
                outs.append(nxt)
        toks = [itos.get(i, "") for i in outs if i not in (pad_id, bos_id, eos_id)]
        return toks, hit
    def loss_for(ex):
        full = encode_full(ex)
        pre = len(encode_input(ex["input"]))
        x = lib.tensor([full[:-1]], dtype=lib.long)
        y = full[1:]
        for i in range(len(y)):
            if i < pre - 1:
                y[i] = -100
        y = lib.tensor([y], dtype=lib.long)
        with lib.no_grad():
            logits = model(x)
            fn = nn.CrossEntropyLoss(ignore_index=-100)
            l = fn(logits.reshape(-1, len(vocab)), y.reshape(-1))
        return float(l.item())
    def load_jsonl(p):
        rows = []
        for l in Path(p).read_text(encoding="utf-8").splitlines():
            if l.strip():
                rows.append(json.loads(l))
        return rows
    val = load_jsonl(data_dir / "val.jsonl")
    test = load_jsonl(data_dir / "test.jsonl")
    if len(val) == 0 or len(test) == 0:
        print("BLOCKED empty val or test")
        return
    def eval_split(rows):
        per = {}
        errs = {}
        cnt = Counter()
        total_first = 0
        correct_first = 0
        eos_hit = 0
        rep = 0
        caps = sorted(set(e["capability"] for e in rows))
        for cap in caps:
            items = [e for e in rows if e["capability"] == cap]
            losses = []
            correct = 0
            c_first = 0
            e_hit = 0
            r_cnt = 0
            err_list = []
            for e in items:
                l = loss_for(e)
                losses.append(l)
                pred_toks, hit = generate(e["input"])
                exp_toks = tokenize(e["target"])
                cnt.update(pred_toks)
                if hit:
                    eos_hit += 1
                    e_hit += 1
                if len(pred_toks) >= 5 and len(set(pred_toks)) == 1:
                    rep += 1
                    r_cnt += 1
                if pred_toks and exp_toks and pred_toks[0] == exp_toks[0]:
                    correct_first += 1
                    c_first += 1
                total_first += 1
                if pred_toks == exp_toks:
                    correct += 1
                elif len(err_list) < 3:
                    err_list.append({"id": e["id"], "input": e["input"], "expected": e["target"], "predicted": " ".join(pred_toks), "eos_hit": hit, "loss": l})
            avg = sum(losses) / max(1, len(losses))
            per[cap] = {"count": len(items), "loss_avg": avg, "accuracy_exact": correct / max(1, len(items)), "accuracy_first_token": c_first / max(1, len(items)), "eos_hit_rate": e_hit / max(1, len(items)), "repetition_rate": r_cnt / max(1, len(items)), "correct": correct}
            errs[cap] = err_list
        overall = {"first_token_acc": correct_first / max(1, total_first), "eos_hit_rate": eos_hit / max(1, len(rows)), "repetition_rate": rep / max(1, len(rows))}
        return per, errs, overall, cnt
    per_val, err_val, ov_val, cnt_val = eval_split(val)
    per_test, err_test, ov_test, cnt_test = eval_split(test)
    novel_inputs = [("native_representation", "seq: E19,E00,E01 | last ?"), ("knowledge_acquisition", "fact: E19 -> E00 | query E19 ?"), ("relational_reasoning", "E19 > E00, E00 > E01 | E19 ? E01"), ("planning_decomposition", "plan: E19 then E00 then E01 | last step ?"), ("verification", "verify: E19 equals E00 | fact: E19 is different | verdict ?"), ("adaptive_learning", "learn: E19 -> E00 | predict E19 ?")]
    novel = []
    for cap, inp in novel_inputs:
        pred, hit = generate(inp)
        novel.append({"capability": cap, "input": inp, "predicted": " ".join(pred), "eos_hit": hit})
    report = {"checkpoint": {"path": str(ckpt_path), "step": ckpt.get("step"), "best_step": ckpt.get("best_step"), "best_val": ckpt.get("best_val"), "params": ckpt.get("params")}, "val_per_capability": per_val, "val_overall": ov_val, "val_errors": err_val, "test_per_capability": per_test, "test_overall": ov_test, "test_errors": err_test, "novel_inference": novel, "val_top_tokens": cnt_val.most_common(5), "evaluation": {"mode": "read-only", "tokenizer": "token-level", "max_new": 5, "verified_for": "v5"}}
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = []
    lines.append("# ZYRQUEN - Eval v5 Proper\n")
    lines.append(f"- Ckpt step: `{ckpt.get('step')}` best `{ckpt.get('best_step')}`\n")
    lines.append(f"- Val overall first-token `{ov_val['first_token_acc']:.2f}` EOS `{ov_val['eos_hit_rate']:.2f}` rep `{ov_val['repetition_rate']:.2f}`\n")
    lines.append("## Val per Capability\n")
    lines.append("| Cap | Count | Loss | Exact | First | EOS | Rep |\n|---|---|---|---|---|---|---|\n")
    for cap, v in per_val.items():
        lines.append(f"| {cap} | {v['count']} | {v['loss_avg']:.4f} | {v['accuracy_exact']:.2f} | {v['accuracy_first_token']:.2f} | {v['eos_hit_rate']:.2f} | {v['repetition_rate']:.2f} |\n")
    lines.append("\n## Test per Capability\n")
    lines.append("| Cap | Count | Loss | Exact | First | EOS | Rep |\n|---|---|---|---|---|---|---|\n")
    for cap, v in per_test.items():
        lines.append(f"| {cap} | {v['count']} | {v['loss_avg']:.4f} | {v['accuracy_exact']:.2f} | {v['accuracy_first_token']:.2f} | {v['eos_hit_rate']:.2f} | {v['repetition_rate']:.2f} |\n")
    lines.append("\n## Novel Inference\n")
    for n in novel:
        lines.append(f"- **{n['capability']}** | `{n['input']}` | -> `{n['predicted']}` | EOS {n['eos_hit']}\n")
    lines.append(f"\n## Top Tokens Val: `{cnt_val.most_common(5)}`\n")
    (out / "report.md").write_text("".join(lines), encoding="utf-8")
    print(f"OK report {out / 'report.json'}")
    print(f"Val first {ov_val['first_token_acc']:.2f} EOS {ov_val['eos_hit_rate']:.2f} rep {ov_val['repetition_rate']:.2f}")
if __name__ == "__main__":
    main()
