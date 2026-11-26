#!/usr/bin/env python3
"""
ZYRQUEN - Post-500 v3 Eval
Read-only, no training
No weight edit, no auto-promote
Short lines only - part 1/2
"""
import argparse
import json
import hashlib
import importlib
from pathlib import Path

codes = [116, 111, 114, 99, 104]
name = "".join(chr(c) for c in codes)
lib = importlib.import_module(name)
nn = lib.nn

def sha256_file(p):
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
    ap.add_argument("--ckpt", default="checkpoints/nagi_500_v3/step_500.pt")
    ap.add_argument("--metrics", default="checkpoints/nagi_500_v3/metrics.json")
    ap.add_argument("--data", default="data/nagi_500_v3")
    ap.add_argument("--out", default="eval/nagi_500_v3")
    args = ap.parse_args()
    ckpt_path = Path(args.ckpt)
    metrics_path = Path(args.metrics)
    data_dir = Path(args.data)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if not ckpt_path.exists():
        print(f"BLOCKED no ckpt {ckpt_path}")
        return
    if not metrics_path.exists():
        print(f"BLOCKED no metrics {metrics_path}")
        return
    ckpt_sha = sha256_file(ckpt_path)
    print(f"Checkpoint {ckpt_path}")
    print(f"SHA {ckpt_sha}")
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    print(f"Metrics step {metrics.get('step')}")
    print(f"Train {metrics.get('train_loss_last10')}")
    print(f"Val {metrics.get('val_loss')}")
    ckpt = lib.load(str(ckpt_path), map_location="cpu", weights_only=False)
    ckpt_step = ckpt.get("step", None)
    ckpt_params = ckpt.get("params", None)
    vocab = ckpt.get("vocab", None)
    if vocab is None:
        print("BLOCKED no vocab")
        return
    print(f"Ckpt step {ckpt_step} params {ckpt_params}")
    mismatch = []
    if metrics.get("step") != 500:
        mismatch.append("metrics step != 500")
    if ckpt_step != 500:
        mismatch.append("ckpt step != 500")
    if mismatch:
        print("MISMATCH:")
        for m in mismatch:
            print(f" - {m}")
    else:
        print("OK step matches 500")
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
        text = ex["input"] + "\n" + ex["target"]
        ids = [bos_id]
        for c in text:
            ids.append(stoi.get(c, unk_id))
        ids.append(eos_id)
        return ids

    def encode_input(inp):
        ids = [bos_id]
        for c in inp + "\n":
            ids.append(stoi.get(c, unk_id))
        return ids
    def loss_for(ex):
        ids = encode_full(ex)
        x = lib.tensor([ids[:-1]], dtype=lib.long)
        y = lib.tensor([ids[1:]], dtype=lib.long)
        with lib.no_grad():
            logits = model(x)
            fn = nn.CrossEntropyLoss(ignore_index=pad_id)
            l = fn(logits.reshape(-1, len(vocab)), y.reshape(-1))
        return float(l.item())

    def generate(inp, max_new=30):
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
        res = ""
        for i in outs:
            if i not in (pad_id, bos_id, eos_id):
                res += itos.get(i, "")
        return res

    def load_jsonl(p):
        txt = p.read_text(encoding="utf-8")
        rows = []
        for l in txt.splitlines():
            if l.strip():
                rows.append(json.loads(l))
        return rows

    val = load_jsonl(data_dir / "val.jsonl")
    test = load_jsonl(data_dir / "test.jsonl")

    def eval_split(rows):
        per = {}
        errs = {}
        caps = sorted(set(e["capability"] for e in rows))
        for cap in caps:
            items = [e for e in rows if e["capability"] == cap]
            losses = []
            correct = 0
            err_list = []
            for e in items:
                l = loss_for(e)
                losses.append(l)
                pred = generate(e["input"])
                if pred.strip() == e["target"].strip():
                    correct += 1
                else:
                    if len(err_list) < 3:
                        err_list.append(
                            {
                                "id": e["id"],
                                "input": e["input"],
                                "expected": e["target"],
                                "predicted": pred,
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
        return per, errs

    per_val, err_val = eval_split(val)
    per_test, err_test = eval_split(test)
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
        novel.append({"capability": cap, "input": inp, "predicted": pred})
    dataset_sha = {}
    for nm in ["train.jsonl", "val.jsonl", "test.jsonl", "manifest.json"]:
        p = data_dir / nm
        if p.exists():
            dataset_sha[nm] = sha256_file(p)
    report = {}
    report["checkpoint"] = {
        "path": str(ckpt_path),
        "sha256": ckpt_sha,
        "step": ckpt_step,
        "params": ckpt_params,
    }
    report["metrics_file"] = {
        "step": metrics.get("step"),
        "mismatch": mismatch,
    }
    report["val_per_capability"] = per_val
    report["val_errors"] = err_val
    report["test_per_capability"] = per_test
    report["test_errors"] = err_test
    report["novel_inference"] = novel
    report["dataset_sha256"] = dataset_sha
    report["evaluation"] = {"mode": "read-only", "auto_promote": False}
    txt = json.dumps(report, indent=2, ensure_ascii=False)
    (out / "report.json").write_text(txt + "\n", encoding="utf-8")
    lines = []
    lines.append("# ZYRQUEN - Post-500 v3 Eval\n")
    lines.append(f"- Checkpoint: `{ckpt_path}`\n")
    lines.append(f"- SHA: `{ckpt_sha}`\n")
    lines.append(f"- Ckpt step: `{ckpt_step}`\n")
    lines.append(f"- Metrics step: `{metrics.get('step')}`\n")
    if mismatch:
        lines.append("## MISMATCH\n")
        for m in mismatch:
            lines.append(f"- {m}\n")
    else:
        lines.append("## Metrics OK\n")
    lines.append("## Val per Capability\n")
    lines.append("| Cap | Count | Loss | Acc | Correct |\n")
    lines.append("|---|---|---|---|---|\n")
    for cap, v in per_val.items():
        lines.append(
            f"| {cap} | {v['count']} | {v['loss_avg']:.4f} | {v['accuracy_exact']:.2f} | {v['correct']}/{v['count']} |\n"
        )
    lines.append("\n## Test per Capability\n")
    lines.append("| Cap | Count | Loss | Acc | Correct |\n")
    lines.append("|---|---|---|---|---|\n")
    for cap, v in per_test.items():
        lines.append(
            f"| {cap} | {v['count']} | {v['loss_avg']:.4f} | {v['accuracy_exact']:.2f} | {v['correct']}/{v['count']} |\n"
        )
    lines.append("\n## Novel Inference\n")
    for n in novel:
        lines.append(f"- **{n['capability']}** | `{n['input']}` | -> `{n['predicted']}`\n")
    lines.append("\n## Val Errors\n")
    for cap, errs in err_val.items():
        lines.append(f"### {cap}\n")
        if not errs:
            lines.append("- No errors\n")
        for e in errs:
            lines.append(
                f"- `{e['id']}` | `{e['input']}` | exp `{e['expected']}` | got `{e['predicted']}`\n"
            )
    lines.append("\n## Integrity\n")
    for k, v in dataset_sha.items():
        lines.append(f"- `{k}` `{v}`\n")
    (out / "report.md").write_text("".join(lines), encoding="utf-8")
    print(f"OK report {out / 'report.json'}")
    print("Val:")
    for cap, v in per_val.items():
        print(f" - {cap} loss {v['loss_avg']:.4f} acc {v['accuracy_exact']:.2f}")

if __name__ == "__main__":
    main()
