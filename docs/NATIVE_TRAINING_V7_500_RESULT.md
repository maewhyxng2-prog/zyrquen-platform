# ZYRQUEN Ω∞ — Native Training v7 500 Steps RESULT

**Status:** PASS — 21/11/2569
**Dataset:** data/nagi_500_v3 — Train 400 / Val 50 / Test 50
**Trainer:** tools/train_nagi_500_v7.py — Shift Fix + EOS 1.0
**Eval:** tools/eval_nagi_500_v5.py + tools/diag_v5.py
**Overfit Test:** tools/overfit_4.py — 4/4 PASS
**Commit (code only, no weights):** `a25361d`
**Scaling Policy:** docs/SCALING_POLICY.md

## 1. ผล Eval Test — v7 500 Steps

| Capability | N | Loss | Exact | First-Token | EOS | Rep |
|---|---|---|---|---|---|---|
| adaptive_learning | 8 | 1.57 | 0.00 | 0.00 | 1.00 | 0.00 |
| knowledge_acquisition | 8 | 1.60 | 0.00 | 0.00 | 1.00 | 0.00 |
| native_representation | 8 | 1.63 | 0.12 | 0.12 | 1.00 | 0.00 |
| planning_decomposition | 8 | 1.51 | 0.12 | 0.12 | 1.00 | 0.00 |
| relational_reasoning | 9 | 1.37 | 0.22 | 0.22 | 1.00 | 0.00 |
| verification | 9 | 0.50 | 0.56 | 0.56 | 1.00 | 0.00 |

**Novel Inference — ไม่ว่างแล้ว:**
- native: `seq: E19,E00,E01 | last ?` -> `E07` | EOS True
- knowledge: `fact: E19 -> E00 | query E19 ?` -> `E08` | EOS True
- relational: `E19 > E00, E00 > E01 | E19 ? E01` -> `greater` | EOS True
- planning: `plan: E19 then E00 then E01 | last step ?` -> `E08` | EOS True
- verification: `verify: E19 equals E00 | fact: E19 is different` -> `true` | EOS True
- adaptive: `learn: E19 -> E00 | predict E19 ?` -> `E04` | EOS True

**Top Tokens Val:** `E07:21, E08:17, true:9, =:8, greater:3`

## 2. ผล Diag v5
