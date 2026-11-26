import pathlib
p = pathlib.Path("tools/train_nagi_500_v6.py")
t = p.read_text()
t = t.replace("loss_w[eos_id] = 2.0", "loss_w[eos_id] = 1.0")
t = t.replace("EOS weight 2.0", "EOS weight 1.0")
t = t.replace("target-only-eos-x2", "target-only-shift-fix")
t = t.replace("Train v6 EOS x2", "Train v7 Shift Fix")
old = "        xs, ys = pad_batch(batch)\n        x = lib.tensor(xs, dtype=lib.long)\n        y = lib.tensor(ys, dtype=lib.long)"
new = "        xs, ys = pad_batch(batch)\n        xs = [r[:-1] for r in xs]\n        ys = [r[1:] for r in ys]\n        x = lib.tensor(xs, dtype=lib.long)\n        y = lib.tensor(ys, dtype=lib.long)"
assert old in t, "train shift block not found"
t = t.replace(old, new)
pathlib.Path("tools/train_nagi_500_v7.py").write_text(t)
print("created v7 shift fix + EOS 1.0")
