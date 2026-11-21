import argparse
import json
import torch
from collections import Counter
from pathlib import Path

# ถ้าคุณมีไฟล์ train_nagi_500_v8.py อยู่โฟลเดอร์เดียวกัน import จะทำงาน
try:
    from train_nagi_500_v8 import Encoder, PointerDecoder, Seq2Seq
except ImportError:
    pass # ป้องกัน error ตอนตรวจ syntax

def load_model(ckpt_path, device):
    ckpt = torch.load(ckpt_path, map_location=device)
    vocab_size = ckpt['vocab_size']
    enc = Encoder(vocab_size, 128, 128)
    dec = PointerDecoder(vocab_size, 128, 128)
    model = Seq2Seq(enc, dec, device)
    model.load_state_dict(ckpt['model_state'])
    model.eval()
    return model

def teacher_forced_eval(model, src, trg, pad_idx=0):
    with torch.no_grad():
        outputs = model(src, trg, teacher_forcing_ratio=1.0)
        preds = outputs.argmax(dim=2)
        
    mask = (trg != pad_idx)
    correct = (preds == trg) & mask
    total_tokens = mask.sum().item()
    correct_tokens = correct.sum().item()
    return 0.0, correct_tokens, total_tokens

def free_eval(model, src, sos_idx=2, eos_idx=3):
    with torch.no_grad():
        preds = model.generate(src, max_len=30, sos_idx=sos_idx, eos_idx=eos_idx)
    return preds

def eval_split(model, rows, device):
    # หมายเหตุ: ตรงนี้ต้องใช้ tokenizer ตัวเดียวกับ v7
    def tokenize(text): 
        # สมมติฐานชั่วคราวเพื่อให้โค้ดรันได้ (ต้องเอา tokenizer จริงมาใส่)
        return [1, 2, 3] 
    
    per_cap, err_cases = {}, []
    tot_exact = tot_first = tot_eos = tot_prem = tot_rep = 0
    tf_corr = tf_tot = 0
    ent_tot = ent_hit = 0
    unseen_tot = unseen_hit = 0
    
    for r in rows:
        cap = r.get("capability", "unknown")
        if cap not in per_cap:
            per_cap[cap] = {"count": 0, "tf_acc": 0, "free_exact": 0, "eos_hit": 0, "rep_rate": 0}
            
        src_tensor = torch.tensor([tokenize(r["input"])]).to(device)
        trg_tensor = torch.tensor([tokenize(r["target"])]).to(device)
        
        # 1. Teacher Forced
        _, c_tok, t_tok = teacher_forced_eval(model, src_tensor, trg_tensor)
        tf_corr += c_tok
        tf_tot += t_tok
        
        # 2. Free Generation
        pred_tensor = free_eval(model, src_tensor)
        pred_toks = pred_tensor.squeeze(0).tolist()
        exp_toks = trg_tensor.squeeze(0).tolist()
        
        if pred_toks == exp_toks:
            tot_exact += 1
            per_cap[cap]["free_exact"] += 1
            
        if pred_toks and exp_toks and pred_toks[0] == exp_toks[0]:
            tot_first += 1
            
        eos_pos = pred_toks.index(3) if 3 in pred_toks else -1
        if eos_pos >= 0:
            tot_eos += 1
            if eos_pos < len(exp_toks): tot_prem += 1
            
        if len(pred_toks) >= 5 and len(set(pred_toks)) == 1:
            tot_rep += 1
            
        per_cap[cap]["count"] += 1
        per_cap[cap]["eos_hit"] += (1 if eos_pos >= 0 else 0)
        per_cap[cap]["rep_rate"] += (1 if (len(pred_toks) >= 5 and len(set(pred_toks)) == 1) else 0)

    res = {
        "count": len(rows),
        "free_exact_match": tot_exact / max(1, len(rows)),
        "free_first_token_acc": tot_first / max(1, len(rows)),
        "teacher_forced_token_acc": tf_corr / max(1, tf_tot),
        "eos_hit_rate": tot_eos / max(1, len(rows)),
        "premature_eos_rate": tot_prem / max(1, len(rows)),
        "repetition_rate": tot_rep / max(1, len(rows)),
        "entity_copy_acc": ent_hit / max(1, ent_tot),
        "unseen_target_entity_copy_acc": unseen_hit / max(1, unseen_tot),
        "per_capability": per_cap,
    }
    return res

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--v7_report", required=True)
    args = ap.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = load_model(args.ckpt, device)
    
    # ต้องโหลดข้อมูลจริงจาก args.data
    val_rows, test_rows = [], [] 
    
    val_res = eval_split(model, val_rows, device)
    test_res = eval_split(model, test_rows, device)
    
    novel_probes = [
        ("relational_reasoning", "E19 > E20, E20 > E21 | E19 ? E21 ?", "E21"),
        ("planning_decomposition", "plan: E19 then E20 then E21 | last step ?", "E21"),
    ]
    novel_results = []
    for cap, prompt, expected in novel_probes:
        src_t = torch.tensor([[1,2,3]]).to(device)
        pred_t = free_eval(model, src_t)
        novel_results.append({
            "capability": cap,
            "input": prompt,
            "expected": expected,
            "predicted": " ".join(map(str, pred_t.squeeze(0).tolist()))
        })

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"val": val_res, "test": test_res, "novel": novel_results}
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        f"## Val Exact: {val_res['free_exact_match']:.4f}",
        f"## Test Exact: {test_res['free_exact_match']:.4f}",
        f"## Entity Copy (Test): {test_res['entity_copy_acc']:.4f}",
        "",
        "### Per-Capability Breakdown",
    ]
    for cap, m in test_res['per_capability'].items():
        lines.append(f"- **{cap}**: Exact {m['free_exact']/max(1,m['count']):.4f} | EOS {m['eos_hit']/max(1,m['count']):.4f} | Rep {m['rep_rate']/max(1,m['count']):.4f}")

    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved evaluation to {out_dir}")

if __name__ == "__main__":
    main()
