# ZYRQUEN Ω∞ — V12 Model Specification

- **Document ID:** `V12-DOC-03`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Architecture Class:** `ZyrquenConfig` / `ZyrquenModel` (`apps/core/native/config.py`, `model.py`)
- **Parameter Ceiling Rule:** `V12-Tier0 <= 5,000,000` (`MAX_V10_PARAMETERS = 5_000_000`)

---

## 1. Exact Parameter Formula (Weight-Tied `zyrquen-decoder`)

ตาม `ZyrquenConfig` และ `ZyrquenModel` จริง:
- Embedding (weight-tied กับ LM head): `V * D`
- ต่อ 1 Transformer Layer (`n_layers`):
  - Pre-Attention RMSNorm: `D`
  - Q, K, V, O Projections (`4` matrices without bias): `4 * D * D`
  - Pre-FFN RMSNorm: `D`
  - SwiGLU (`gate`, `up`, `down` without bias): `3 * D * F`
  - รวมต่อ Layer: `4 * D^2 + 3 * D * F + 2 * D`
- Final RMSNorm: `D`
- **Total Parameters:**

$$P = V \cdot D + L \cdot (4D^2 + 3DF + 2D) + D$$

---

## 2. Configuration Tiers Matrix

| Tier ID | Approval Status | `vocab_size (V)` | `max_seq_len` | `n_layers (L)` | `n_heads (H)` | `d_model (D)` | `d_ff (F)` | Exact Params (`P`) | FP32 Weights | Est. AdamW Runtime State |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **`V12-Tier0-Base`** | **Default Entry** | `2048` | `256` | `4` | `4` | `256` | `704` | **`3,737,856`** | `14.26 MB` | `~57 MB` + activations (Est.) |
| **`V12-Tier0-Vocab`** | **Allowed <=5M** | `4096` | `256` | `4` | `4` | `256` | `704` | **`4,262,144`** | `16.26 MB` | `~65 MB` + activations (Est.) |
| **`V12-Tier0-Deep6L`** | **Allowed <=5M** | `2048` | `256` | `6` | `4` | `256` | `512` | **`4,462,848`** | `17.02 MB` | `~68 MB` + activations (Est.) |
| **`V12-Tier0-Deep6L-704`** | **Allowed <=5M** | `2048` | `256` | `6` | `4` | `256` | `640` | **`4,954,368`** | `18.90 MB` | `~76 MB` + activations (Est.) |
| **`V12-Tier1`** | **LOCKED (Needs Benchmark + Tier-2)** | `4096` | `512` | `6` | `6` | `384` | `1024` | **`12,194,688`** | `46.52 MB` | `~186 MB` + activations (Est.) |
| **`V12-Tier2`** | **LOCKED (Needs Benchmark + Tier-2)** | `4096` | `512` | `8` | `8` | `512` | `1408` | **`27,795,968`** | `106.03 MB` | `~424 MB` + activations (Est.) |

> **ข้อบังคับ:** ห้ามเปิด `V12-Tier1` หรือ `V12-Tier2` จนกว่า `WorkflowResourceGuard` และ Real PyTorch Benchmark จะยืนยันว่า Peak RSS ต่ำกว่า `3.0 GB` (Soft Limit) และ Wall-Clock Throughput ต่อ 500-step Experiment อยู่ในงบเวลาที่อนุมัติ

---

## 3. Structural Alignment Rules Across Stages (`1–50,000`)

1. **Architecture Immutability Within a Lineage:** การฝึกต่อเนื่อง `1 -> 50,000` Steps ในหนึ่ง Lineage ต้องคงค่า `(V, L, H, D, F, tie_embeddings)` เท่าเดิมทุก Stage เพื่อไม่ให้ Checkpoint Incompatible
2. **Tier Escalation Protocol:** หากต้องขยับจาก `V12-Tier0` ไป `V12-Tier1` ต้องเปิดเป็น **New Versioned Lineage (`v12.1-tier1`)** พร้อม New Random Initialization หรือ Approved Weight Transfer Proof และเริ่มนับ Cumulative Evaluation Integrity ใหม่สำหรับ Lineage นั้น (ห้ามปะปน Checkpoint ต่างขนาดในเส้นทางเดียว)
3. **RoPE & Sequence Length:** `rope_theta = 10000.0` (ค่าเริ่มต้นของ `ZyrquenConfig`), `dropout = 0.0` ถึง `0.05` (กำหนดเฉพาะตาม Stage Config และบันทึกใน Checkpoint Manifest)
4. **Code & Multi-Module Representation (`Native Software Engineering`):**
   - ใช้ Byte-level BPE (`zyrquen.tokenizer.v2`) ที่รองรับทั้งโค้ด (TypeScript, Python, SQL, JSON, CSS), Unicode/Thai Requirements, และ Entity/Identifier Slot Tokens (`<slot_0>..<slot_31>`) แบบ Lossless
   - งาน Multi-File Application Generation ต้องใช้วิธี **Modular File-by-File & Contract-Grounded Generation** (Spec -> Schema -> API -> Module -> Tests) เพื่อให้อยู่ภายในงบ Context Window (`max_seq_len = 256..512`) และ `Tier0 <= 5M` หรือ `Tier1` เฉพาะเมื่อ Benchmark ยืนยันความจำเป็น

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- `ZyrquenConfig.validate()` ใน `apps/core/native/config.py` ยังคงเป็น Single Source of Truth สำหรับตรวจสอบ `d_model % n_heads == 0`, `(d_model // n_heads) % 2 == 0` (สำหรับ RoPE) และเพดาน Parameter

### OPEN DECISIONS
- **OD-V12-MOD-01:** เลือกรุ่นหลักสำหรับ V12 ระหว่าง `V12-Tier0-Deep6L-704` (`4.95M`, เน้นความลึก 6 Layers สำหรับ Multi-hop Reasoning) กับ `V12-Tier1` (`12.19M`) หลังวิเคราะห์ผล Loss/Accuracy ของ V11 ครบ 10,000 Steps

### NOT VERIFIED
- ตัวเลข Peak RSS จริงของ PyTorch CPU Autograd สำหรับ `max_seq_len=256` และ `512` ในทุก Tier ด้านบนเป็น **ค่าประมาณเชิงคำนวณเท่านั้น — NOT VERIFIED**
- การอ้างอิง `V12-Tier0-Deep6L-704` (`4,954,368` params) ยังไม่ได้รันทดสอบจริงกับ `ZyrquenConfig` runtime benchmark
