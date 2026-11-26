#!/usr/bin/env python3
"""
ZYRQUEN - Fix Trainer v5 Best Checkpoint
Creates train_nagi_500_v5_fixed.py
Preserves original v5 as evidence
"""
import pathlib

src = pathlib.Path("tools/train_nagi_500_v5.py")
txt = src.read_text(encoding="utf-8")
# 1. Empty dataset + EOS target check after load
old_load = '    print(f"Train {len(train)} Val {len(val)} Test {len(test)}")'
new_load = '''    print(f"Train {len(train)} Val {len(val)} Test {len(test)}")
    if len(train) == 0 or len(val) == 0:
        print("BLOCKED empty train or val")
        return
    empty_tgt = sum(1 for r in train + val if not r.get("target", "").strip())
    print(f"Empty target count {empty_tgt}")
    assert empty_tgt == 0, "empty target found"
    print("OK no empty target, EOS will be added by encoder")'''
assert old_load in txt
txt = txt.replace(old_load, new_load)
# 2. Init best_state
old_init = '    best_val = float("inf")\n    best_step = 0\n    no_improve = 0'
new_init = '    best_val = float("inf")\n    best_step = 0\n    no_improve = 0\n    best_state = None'
assert old_init in txt
txt = txt.replace(old_init, new_init)
# 3. Save best_state copy when val improves
old_best = '            if vl < best_val:\n                best_val = vl\n                best_step = step\n                no_improve = 0'
new_best = '            if vl < best_val:\n                best_val = vl\n                best_step = step\n                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}\n                no_improve = 0'
assert old_best in txt
txt = txt.replace(old_best, new_best)
# 4. Restore best_state before save
old_ckpt = '    ckpt = {\n        "model": model.state_dict(),'
new_ckpt = '''    if best_state is not None:
        model.load_state_dict(best_state)
        print(f"Restored best weights from step {best_step} val {best_val:.4f}")
    else:
        print("WARNING no best_state, using last weights")
    ckpt = {
        "model": model.state_dict(),'''
assert old_ckpt in txt
txt = txt.replace(old_ckpt, new_ckpt)
# 5. Mark fixed version
txt = txt.replace(
    "ZYRQUEN - Train v5 Token-level",
    "ZYRQUEN - Train v5 Fixed Best Checkpoint"
)
out = pathlib.Path("tools/train_nagi_500_v5_fixed.py")
out.write_text(txt, encoding="utf-8")
print(f"fixed -> {out}")
print("OK best_state + empty + EOS checks added")
