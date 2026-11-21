#!/usr/bin/env python3
"""
ZYRQUEN - Fix arrow tokenizer v4
Makes -> one token, not - + >
"""
import pathlib

files = [
    "tools/preflight_v4.py",
    "tools/train_nagi_500_v4.py",
    "tools/eval_nagi_500_v4.py",
]
for fname in files:
    p = pathlib.Path(fname)
    txt = p.read_text(encoding="utf-8")
    old1 = 't = text.replace("->", " -> ")'
    new1 = 't = text.replace("->", " __ARROW__ ")'
    txt = txt.replace(old1, new1)
    old2 = "    return t.split()"
    new2 = "    toks = t.split()\n    toks = [\"->\" if x == \"__ARROW__\" else x for x in toks]\n    return toks"
    txt = txt.replace(old2, new2)
    p.write_text(txt, encoding="utf-8")
    print(f"fixed {fname}")
print("OK arrow fix done")
