# ZYRQUEN Ω∞ — V11 Model Specification

- **Document ID:** `V11-DOC-03`
- **Status:** `BLUEPRINT ONLY — LOCKED UNTIL V10 FINAL GATE PASS`
- **Config Class:** `ZyrquenConfig` (`apps/core/native/config.py`)
- **Parameter Formula (Exact Code Match):**
  $$\text{params} = V \cdot d + L \cdot (4 d^2 + 3 d \cdot d_{ff} + 2 d) + d$$
  (เมื่อ `tie_embeddings=True`; หาก `False` คูณส่วน embedding ด้วย 2)

---

## 1. Evidence-Based Parameter & Memory Tiers

> **ข้อบังคับความซื่อสัตย์ด้านทรัพยากร:** เนื่องจาก Container ปัจจุบันยังไม่มี `torch` สำหรับรัน Benchmark RAM/Throughput จริง ตัวเลข Static Memory ด้านล่างคำนวณจาก `params * 4 bytes` (FP32 Weights) และ `params * 16 bytes` (Weights + Gradients + AdamW `m, v` ใน FP32) เท่านั้น **ไม่รวม** PyTorch Runtime Baseline (~200–400 MiB) และ Activation Memory ระหว่าง Backward Pass

| Tier ID | Approval Status | `vocab_size` | `max_seq_len` | `n_layers` | `n_heads` | `head_dim` | `d_model` | `d_ff` | Exact `estimated_num_parameters` | FP32 Weights Only | AdamW Static FP32 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **V11-Tier0-Default** | **ACTIVE CPU CAP COMPLIANT** (`<= 5M`) | `2048` | `256` | `4` | `4` | `64` | `256` | `704` | `3,737,856` | `14.26 MiB` | `57.04 MiB` |
| **V11-Tier0-Vocab4096** | **ACTIVE CPU CAP COMPLIANT** (`<= 5M`) | `4096` | `256` | `4` | `4` | `64` | `256` | `704` | `4,262,144` | `16.26 MiB` | `65.04 MiB` |
| **V11-Tier0-Deep6L** | **ACTIVE CPU CAP COMPLIANT** (`<= 5M`) | `2048` | `256` | `6` | `4` | `64` | `256` | `576` | `4,754,688` | `18.14 MiB` | `72.55 MiB` |
| **V11-Tier1-Candidate** | **LOCKED / REQUIRES BENCHMARK** | `4096` | `512` | `6` | `6` | `64` | `384` | `1024` | `12,194,688` | `46.52 MiB` | `186.08 MiB` |
| **V11-Tier2-Candidate** | **LOCKED / REQUIRES BENCHMARK** | `4096` | `512` | `8` | `8` | `64` | `512` | `1408` | `27,795,968` | `106.03 MiB` | `424.13 MiB` |

*หมายเหตุ:* ตัวเลข `V11-Tier0-Default` (`3,737,856`) และ `V11-Tier0-Vocab4096` (`4,262,144`) ตรงกับ Unit Test `tests/test_v10a_contracts.py` ทุกประการ

---

## 2. Hyperparameter Constraints (Code-Enforced Invariants)

1. `d_model % n_heads == 0`
2. `(d_model // n_heads) % 2 == 0` (จำเป็นสำหรับ RoPE pairing)
3. ค่า `vocab_size`, `max_seq_len`, `n_layers`, `n_heads`, `d_model`, `d_ff` ต้องเป็นจำนวนเต็มบวกทั้งหมด
4. `model.cfg.vocab_size == tokenizer.vocab_size` เสมอเมื่อฝึกและประเมิน (`EvaluationEngine` และ `handle_training_execute` บังคับตรวจ)
5. `ZyrquenConfig.validate_parameter_budget(max_parameters)` ต้องรันก่อน Instantiate `ZyrquenModel` และตรวจสอบซ้ำหลังสร้างโมเดลด้วย `model.num_parameters()`

---

## 3. Weight Initialization & Precision Contract

- **Weights Init:**
  - `nn.Linear`, `nn.Embedding`: `Normal(0.0, 0.02)`
  - Residual out projections (`attn.proj.weight`, `ffn.down.weight`): `Normal(0.0, 0.02 / sqrt(2 * n_layers))`
- **RMSNorm Scale:** `torch.ones(dim)`, `norm_eps = 1e-5`
- **Compute Precision:** `float32` บน CPU-only (คงความแม่นยำและหลีกเลี่ยงความไม่เสถียรของ half-precision บน CPU ที่ไม่รองรับ bfloat16/CUDA; รองรับ Mixed Precision เฉพาะเมื่อ Hardware รองรับในอนาคตตาม `SCALING_POLICY.md`)
- **Serialization Integrity:** Checkpoints เก็บ `"model_config": model.cfg.to_dict()` ซึ่ง `ModelRegistry.check_compatibility` ใช้ตรวจโครงสร้าง `zyrquen-decoder`

---

## 4. Selection Policy for First V11 Run

- **รอบเริ่มต้นหลัง V10 Gate ผ่าน:** บังคับใช้ **V11-Tier0** (`<= 5M`) เท่านั้น เพื่อทดสอบ 6-Stage Curriculum 10,000 Steps ภายในเพดาน `MAX_V10_PARAMETERS` / `MAX_CPU_MODEL_PARAMETERS` ที่มีอยู่แล้ว
- **การเลือก Config ย่อยใน Tier0:** เปรียบเทียบเชิงทดลอง (Ablation) ระหว่าง `V11-Tier0-Default (4L, d=256, d_ff=704)` กับ `V11-Tier0-Deep6L (6L, d=256, d_ff=576)` เนื่องจากความลึก `6` layers อาจรองรับ multi-hop reasoning (4–5+ hops) ได้ดีกว่า `4` layers ขณะยังอยู่ใต้เพดาน `5,000,000` พารามิเตอร์

---

## 5. Mandatory Truthfulness Sections

### ASSUMPTIONS
- สูตร `estimated_num_parameters` ใน `ZyrquenConfig` สอดคล้องกับ `ZyrquenModel.num_parameters()` จริง (100% ตรงเมื่อ `tie_embeddings=True` และ `rope_cos`/`rope_sin` เป็น non-persistent buffer ไม่ใช่ parameter)
- โครงสร้าง BPE Vocabulary `2048` ถึง `4096` โทเคนเพียงพอสำหรับ SFT Symbolic + Grounded Memory Prompts ของ V11

### OPEN DECISIONS
- **OD-MS-01:** จะตั้งค่า Baseline แรกของ V11 เป็น `V11-Tier0-Default (3.74M)` หรือ `V11-Tier0-Deep6L (4.75M)` (หรือรันคู่เปรียบเทียบ 1,000-step probe ก่อนตัดสินใจ)
- **OD-MS-02:** ค่า `dropout` ที่เหมาะสมสำหรับ 10,000 Steps (`0.0` vs `0.05` vs `0.1`)
- **OD-MS-03:** เงื่อนไข Benchmark ขั้นต่ำที่จะอนุญาตให้ขอ Tier-2 Approval ปลดล็อก `V11-Tier1-Candidate (12.19M)`

### NOT VERIFIED
- ความแตกต่างระหว่าง `ZyrquenConfig.estimated_num_parameters` กับ `model.num_parameters()` ใน runtime จริง (ยังไม่มี `torch` ใน container)
- Peak RSS และ Step Latency จริงของ `V11-Tier0-Deep6L`, `V11-Tier1-Candidate`, และ `V11-Tier2-Candidate` บน CPU host และ HONOR X6b ยัง **NOT VERIFIED**
