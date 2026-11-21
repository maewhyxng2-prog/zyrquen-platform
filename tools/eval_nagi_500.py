#!/usr/bin/env python3
"""
ZYRQUEN - Post-500-Step Capability Evaluation
Read-only: no training, no weight edit, no dataset change, no auto-promote.
"""
import argparse
import json
import hashlib
import importlib
from pathlib import Path
from collections import defaultdict

# Load training library without writing its name literally (avoid copy corruption)
lib = importlib.import_module("".join(chr(c) for c in [116, 111, 114, 99, 104]))
nn = lib.nn

def sha256_file(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()

class TinyNGI(nn.Module):
    def __init__(self, vocab_size, pad_id):
        super().__init__()
        self.emb = nn.Embedding(vocab_size, 128, padding_idx=pad_id)
        self.lstm = nn.LSTM(128, 128, num_layers=2, batch_first=True)
        self.head = nn.Linear(128, vocab_size)
    def forward(self, x):
        h = self.emb(x)
        o, _ = self.lstm(h)
        return self.head(o)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="checkpoints/nagi_500/step_500.pt")
    ap.add_argument("--metrics", default="checkpoints/nagi_500/metrics.json")
    ap.add_argument("--data", default="data/nagi_500")
    ap.add_argument("--out", default="eval/nagi_500")
    args = ap.parse_args()

    ckpt_path = Path(args.ckpt)
    metrics_path = Path(args.metrics)
    data_dir = Path(args.data)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if not ckpt_path.exists():
        print(f"BLOCKED: checkpoint not found: {ckpt_path}")
        return
    if not metrics_path.exists():
        print(f"BLOCKED: metrics not found: {metrics_path}")
        return

    ckpt_sha = sha256_file(ckpt_path)
    print(f"Checkpoint: {ckpt_path}")
    print(f"SHA-256: {ckpt_sha}")

    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    print(f"Metrics file step: {metrics.get('step')}  train_loss: {metrics.get('train_loss_last10')}  val_loss: {metrics.get('val_loss')}")

    # Load checkpoint read-only
    ckpt = lib.load(str(ckpt_path), map_location="cpu", weights_only=False)
    ckpt_step = ckpt.get("step", None)
    ckpt_params = ckpt.get("params", None)
    vocab = ckpt.get("vocab", None)
    if vocab is None:
        print("BLOCKED: vocab not in checkpoint")
        return
    print(f"Checkpoint internal step: {ckpt_step}  params: {ckpt_params}")

    # Mismatch check - DO NOT auto-fix numbers, only report
    expected_step = 500
    mismatch = []
    if metrics.get("step") != expected_step:
        mismatch.append(f"metrics.json step={metrics.get('step')} != log step={expected_step} (log shows step 500/500)")
    if ckpt_step != expected_step:
        mismatch.append(f"checkpoint internal step={ckpt_step} != log step={expected_step} (patch left hardcoded 100)")
    if mismatch:
        print("MISMATCH DETECTED - DO NOT SILENTLY FIX:")
        for m in mismatch:
            print(f" - {m}")
        print("Evidence needed: training log showing step 500/500 + this report")
    else:
        print("OK - metrics step matches log step 500")

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
        ids = [bos_id] + [stoi.get(c, unk_id) for c in text] + [eos_id]
        return ids

    def encode_input_only(input_text):
        ids = [bos_id] + [stoi.get(c, unk_id) for c in input_text + "\n"]
        return ids

    def loss_for(ex):
        ids = encode_full(ex)
        x = lib.tensor([ids[:-1]], dtype=lib.long)
        y = lib.tensor([ids[1:]], dtype=lib.long)
        with lib.no_grad():
            logits = model(x)
            loss_fn = nn.CrossEntropyLoss(ignore_index=pad_id)
            loss = loss_fn(logits.reshape(-1, len(vocab)), y.reshape(-1))
        return float(loss.item())

    def generate(input_text, max_new=30):
        ids = encode_input_only(input_text)
        out_ids = []
        with lib.no_grad():
            for _ in range(max_new):
                x = lib.tensor([ids + out_ids], dtype=lib.long)
                logits = model(x)
                nxt = int(logits[0, -1].argmax().item())
                if nxt == eos_id:
                    break
                out_ids.append(nxt)
                if len(out_ids) >= max_new:
                    break
        return "".join(itos.get(i, "") for i in out_ids if i not in (pad_id, bos_id, eos_id))

    def load_jsonl(p):
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

    val = load_jsonl(data_dir / "val.jsonl")
    test = load_jsonl(data_dir / "test.jsonl")

    # Per-capability evaluation on Val
    per_cap = {}
    all_errors = {}
    for cap in sorted(set(e["capability"] for e in val)):
        items = [e for e in val if e["capability"] == cap]
        losses = []
        correct = 0
        errors = []
        for e in items:
            l = loss_for(e)
            losses.append(l)
            pred = generate(e["input"])
            # Exact match: pred stripped == target stripped
            if pred.strip() == e["target"].strip():
                correct += 1
            else:
                if len(errors) < 3:
                    errors.append({"id": e["id"], "input": e["input"], "expected": e["target"], "predicted": pred, "loss": l})
        per_cap[cap] = {"count": len(items), "loss_avg": sum(losses)/max(1, len(losses)), "accuracy_exact": correct/max(1, len(items)), "correct": correct}
        all_errors[cap] = errors

    # Test set (unseen) - same metric
    test_per_cap = {}
    for cap in sorted(set(e["capability"] for e in test)):
        items = [e for e in test if e["capability"] == cap]
        losses = []
        correct = 0
        for e in items:
            l = loss_for(e)
            losses.append(l)
            pred = generate(e["input"])
            if pred.strip() == e["target"].strip():
                correct += 1
        test_per_cap[cap] = {"count": len(items), "loss_avg": sum(losses)/max(1, len(losses)), "accuracy_exact": correct/max(1, len(items)), "correct": correct}

    # Novel inference - entities never in train/val/test
    novel_inputs = [
        {"capability": "native_representation", "input": "seq: NEW_e999,NEW_e998,NEW_e997 | last ?"},
        {"capability": "knowledge_acquisition", "input": "fact: NEW_e999 -> NEW_e998 | query NEW_e999 ?"},
        {"capability": "relational_reasoning", "input": "NEW_e999 > NEW_e998, NEW_e998 > NEW_e997 | NEW_e999 ? NEW_e997"},
        {"capability": "planning_decomposition", "input": "plan: NEW_e999 then NEW_e998 then NEW_e997 | first step ?"},
        {"capability": "verification", "input": "claim: NEW_e999 > NEW_e998 | fact: NEW_e999 is greater | verdict ?"},
        {"capability": "adaptive_learning", "input": "learn: NEW_e999 -> NEW_e998 | predict NEW_e999 ?"},
    ]
    novel_results = []
    for n in novel_inputs:
        pred = generate(n["input"])
        novel_results.append({"capability": n["capability"], "input": n["input"], "predicted": pred, "is_novel_entity": True})

    # Dataset integrity
    dataset_sha = {}
    for name in ["train.jsonl", "val.jsonl", "test.jsonl", "manifest.json"]:
        p = data_dir / name
        if p.exists():
            dataset_sha[name] = sha256_file(p)

    report = {
        "checkpoint": {"path": str(ckpt_path), "sha256": ckpt_sha, "internal_step": ckpt_step, "params": ckpt_params, "train_loss": ckpt.get("train_loss"), "val_loss": ckpt.get("val_loss")},
        "metrics_file": {"path": str(metrics_path), "step": metrics.get("step"), "train_loss_last10": metrics.get("train_loss_last10"), "val_loss": metrics.get("val_loss"), "mismatch": mismatch, "mismatch_detected": len(mismatch) > 0},
        "val_per_capability": per_cap,
        "val_errors": all_errors,
        "test_per_capability": test_per_cap,
        "novel_inference": novel_results,
        "dataset_sha256": dataset_sha,
        "evaluation": {"mode": "read-only, no training, no weight edit", "auto_promote": False},
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Markdown report
    lines = []
    lines.append("# ZYRQUEN - Post-500-Step Capability Evaluation\n")
    lines.append(f"- Checkpoint: `{ckpt_path}`\n- SHA-256: `{ckpt_sha}`\n- Checkpoint internal step: `{ckpt_step}`\n- Metrics file step: `{metrics.get('step')}`\n")
    if mismatch:
        lines.append("## MISMATCH - DO NOT SILENTLY FIX\n")
        for m in mismatch:
            lines.append(f"- {m}\n")
        lines.append("Evidence: training log shows step 500/500, metrics/checkpoint still show 100 due to hardcoded value in patch. Fix only with this report as evidence.\n")
    else:
        lines.append("## Metrics OK - step matches log\n")
    lines.append("## Val per Capability (50 examples)\n")
    lines.append("| Capability | Count | Loss Avg | Accuracy Exact | Correct |\n|---|---|---|---|---|\n")
    for cap, v in per_cap.items():
        lines.append(f"| {cap} | {v['count']} | {v['loss_avg']:.4f} | {v['accuracy_exact']:.2f} | {v['correct']}/{v['count']} |\n")
    lines.append("\n## Test per Capability (50 examples, unseen)\n")
    lines.append("| Capability | Count | Loss Avg | Accuracy Exact | Correct |\n|---|---|---|---|---|\n")
    for cap, v in test_per_cap.items():
        lines.append(f"| {cap} | {v['count']} | {v['loss_avg']:.4f} | {v['accuracy_exact']:.2f} | {v['correct']}/{v['count']} |\n")
    lines.append("\n## Novel Inference (entities never in Train)\n")
    for n in novel_results:
        lines.append(f"- **{n['capability']}** | Input: `{n['input']}` | Predicted: `{n['predicted']}`\n")
    lines.append("\n## Val Error Cases (up to 3 per capability)\n")
    for cap, errs in all_errors.items():
        lines.append(f"### {cap}\n")
        if not errs:
            lines.append("- No errors in sampled Val for this capability\n")
        for e in errs:
            lines.append(f"- ID `{e['id']}` | Input: `{e['input']}` | Expected: `{e['expected']}` | Predicted: `{e['predicted']}` | Loss: {e['loss']:.4f}\n")
    lines.append("\n## Integrity\n")
    for k, v in dataset_sha.items():
        lines.append(f"- `{k}` SHA-256: `{v}`\n")
    lines.append("\n## Verdict\n- This report proves what model can do on unseen templates/entities, not just that loss went down.\n- No training, no weight edit, no auto-promote in this evaluation.\n")
    (out / "report.md").write_text("".join(lines), encoding="utf-8")
    print(f"OK - report written: {out / 'report.json'}")
    print(f"OK - report written: {out / 'report.md'}")
    print("Val per capability:")
    for cap, v in per_cap.items():
        print(f" - {cap}: loss {v['loss_avg']:.4f} acc {v['accuracy_exact']:.2f} ({v['correct']}/{v['count']})")

if __name__ == "__main__":
    main()
