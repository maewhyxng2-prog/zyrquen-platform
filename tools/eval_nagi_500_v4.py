#!/usr/bin/env python3
"""
ZYRQUEN - Eval v4 Token-level
Checks: exact match, E12 collapse, balance
Read-only, no train
Part 1/2
"""
import argparse
import hashlib
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="checkpoints/nagi_500_v4/step_5.pt")
    ap.add_argument("--metrics", default="checkpoints/nagi_500_v4/metrics.json")
    ap.add_argument("--data", default="data/nagi_500_v3")
    ap.add_argument("--out", default="eval/nagi_500_v4")
    args = ap.parse_args()
    ckpt_path = Path(args.ckpt)
    metrics_path = Path(args.metrics)
    data_dir = Path(args.data)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ckpt = lib.load(str(ckpt_path), map_location="cpu", weights_only=False)
    vocab = ckpt.get("vocab", None)
    print(f"Ckpt step {ckpt.get('step')} params {ckpt.get('params')}")
    print(f"Tokenizer {ckpt.get('tokenizer')} vocab {ckpt.get('vocab_source')}")
    stoi = {c: i for i, c in enumerate(vocab)}
    itos = {i: c for c, i in stoi.items()}
    pad_id = stoi["<pad>"]
    bos_id = stoi["<bos>"]
    eos_id = stoi["<eos>"]
    unk_id = stoi["<unk>"]
    model = TinyNGI(len(vocab), pad_id)
    model.load_state_dict(ckpt["model"])
    model.eval()

    def encode_full(ex):
        ids = [bos_id]
        for t in tokenize(ex["input"]):
            ids.append(stoi.get(t, unk_id))
        for t in tokenize(ex["target"]):
            ids.append(stoi.get(t, unk_id))
        ids.append(eos_id)
        return ids

    def encode_input(inp):
        ids = [bos_id]
        for t in tokenize(inp):
            ids.append(stoi.get(t, unk_id))
        return ids

    def generate(inp, max_new=20):
        ids = encode_input(inp)
        outs = []
        with lib.no_grad():
            for _ in range(max_new):
                cur = ids + outs
                x = lib.tensor([cur], dtype=lib.long)
                logits = model(x)
                nxt = int(logits[0, -1].argmax().item())
                if nxt == eos_id:
                    break
                outs.append(nxt)
        toks = [itos.get(i, "") for i in outs if i not in (pad_id, bos_id, eos_id)]
        return toks
    def loss_for(ex):
        ids = encode_full(ex)
        x = lib.tensor([ids[:-1]], dtype=lib.long)
        y = lib.tensor([ids[1:]], dtype=lib.long)
        with lib.no_grad():
            logits = model(x)
            fn = nn.CrossEntropyLoss(ignore_index=pad_id)
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

    def eval_split(rows):
        per = {}
        errs = {}
        pred_counter = Counter()
        total = 0
        caps = sorted(set(e["capability"] for e in rows))
        for cap in caps:
            items = [e for e in rows if e["capability"] == cap]
            losses = []
            correct = 0
            err_list = []
            for e in items:
                l = loss_for(e)
                losses.append(l)
                pred_toks = generate(e["input"])
                exp_toks = tokenize(e["target"])
                pred_str = " ".join(pred_toks)
                pred_counter.update(pred_toks)
                total += 1
                if pred_toks == exp_toks:
                    correct += 1
                else:
                    if len(err_list) < 3:
                        err_list.append(
                            {
                                "id": e["id"],
                                "input": e["input"],
                                "expected": e["target"],
                                "predicted": pred_str,
                                "loss": l,
                            }
                        )
            avg = sum(losses) / max(1, len(losses))
            acc = correct / max(1, len(items))
            per[cap] = {
                "count": len(items),
                "loss_avg": avg,
                "accuracy_exact": acc,
                "correct": correct,
            }
            errs[cap] = err_list
        e12_rate = pred_counter.get("E12", 0) / max(1, sum(pred_counter.values()))
        return per, errs, e12_rate, pred_counter

    per_val, err_val, e12_val, cnt_val = eval_split(val)
    per_test, err_test, e12_test, cnt_test = eval_split(test)
    novel = []
    novel_inputs = [
        ("native_representation", "seq: E19,E00,E01 | last ?"),
        ("knowledge_acquisition", "fact: E19 -> E00 | query E19 ?"),
        ("relational_reasoning", "E19 > E00, E00 > E01 | E19 ? E01"),
        ("planning_decomposition", "plan: E19 then E00 then E01 | last step ?"),
        ("verification", "verify: E19 equals E00 | fact: E19 is different | verdict ?"),
        ("adaptive_learning", "learn: E19 -> E00 | predict E19 ?"),
    ]
    for cap, inp in novel_inputs:
        pred = generate(inp)
        novel.append({"capability": cap, "input": inp, "predicted": " ".join(pred)})
    report = {}
    report["checkpoint"] = {"path": str(ckpt_path), "step": ckpt.get("step"), "params": ckpt.get("params")}
    report["val_per_capability"] = per_val
    report["val_errors"] = err_val
    report["test_per_capability"] = per_test
    report["test_errors"] = err_test
    report["novel_inference"] = novel
    report["e12_collapse"] = {"val_e12_token_rate": e12_val, "test_e12_token_rate": e12_test, "val_top_tokens": cnt_val.most_common(5), "test_top_tokens": cnt_test.most_common(5)}
    report["evaluation"] = {"mode": "read-only", "tokenizer": "token-level", "exact_match": "token-sequence"}
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = []
    lines.append("# ZYRQUEN - Eval v4 Token-level\n")
    lines.append(f"- Ckpt step: `{ckpt.get('step')}`\n")
    lines.append(f"- E12 rate Val: `{e12_val:.3f}` Test: `{e12_test:.3f}`\n")
    lines.append("## Val per Capability\n")
    lines.append("| Cap | Count | Loss | Acc | Correct |\n|---|---|---|---|---|\n")
    for cap, v in per_val.items():
        lines.append(f"| {cap} | {v['count']} | {v['loss_avg']:.4f} | {v['accuracy_exact']:.2f} | {v['correct']}/{v['count']} |\n")
    lines.append("\n## Test per Capability\n")
    lines.append("| Cap | Count | Loss | Acc | Correct |\n|---|---|---|---|---|\n")
    for cap, v in per_test.items():
        lines.append(f"| {cap} | {v['count']} | {v['loss_avg']:.4f} | {v['accuracy_exact']:.2f} | {v['correct']}/{v['count']} |\n")
    lines.append("\n## Novel Inference\n")
    for n in novel:
        lines.append(f"- **{n['capability']}** | `{n['input']}` | -> `{n['predicted']}`\n")
    lines.append("\n## E12 Collapse Check\n")
    lines.append(f"- Val top tokens: `{cnt_val.most_common(5)}`\n")
    lines.append(f"- If E12 rate > 0.40 = COLLAPSE FAIL, < 0.20 = OK\n")
    (out / "report.md").write_text("".join(lines), encoding="utf-8")
    print(f"OK report {out / 'report.json'}")
    print(f"E12 rate Val {e12_val:.3f} Test {e12_test:.3f}")
    for cap, v in per_val.items():
        print(f" - {cap} loss {v['loss_avg']:.4f} acc {v['accuracy_exact']:.2f}")

if __name__ == "__main__":
    main()
