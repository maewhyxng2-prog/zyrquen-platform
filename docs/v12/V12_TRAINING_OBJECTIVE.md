# ZYRQUEN Ω∞ — V12 Training Objective & Loss Design

- **Document ID:** `V12-DOC-06`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Core Objective:** Masked Supervised Fine-Tuning Cross-Entropy (`IGNORE_INDEX = -100`)
- **Contract Anchor:** `apps/core/native/sft.py`, `apps/core/native/train.py`

---

## 1. Primary Loss Function: Masked Causal SFT Cross-Entropy

V12 ใช้เป้าหมายการเรียนรู้แบบ **Prompt-Masked Causal Cross-Entropy** ที่สืบทอดสัญญา `zyrquen.sft.v1` อย่างเคร่งครัด:

$$\mathcal{L}_{\text{SFT}}(\theta) = -\frac{1}{|M|} \sum_{t \in M} \log P_\theta(y_t \mid x_{<t})$$

โดยที่:
- Token ก่อนและรวมถึงตัวคั่น `SFT_SEP = "\n### Response:\n"` ถูกกำหนด Label = `IGNORE_INDEX (-100)` ทั้งหมด เพื่อไม่ให้โมเดลเสียความจุไปกับการจำ Prompt Templates (ลด Template Memorization)
- $M$ คือตำแหน่ง Token ของ Response **รวม `<eos>` Token ปิดท้าย** เพื่อบังคับให้โมเดลเรียนรู้การหยุดสร้างข้อความอย่างแม่นยำ

---

## 2. Diagnostic Auxiliary Signals (Telemetry Only — Non-Fake)

เพื่อตรวจจับความผิดปกติตลอด `50,000` Steps โดยไม่บิดเบือน Loss หลัก:

| Metric | Definition | Purpose in 50K Plan |
|---|---|---|
| **`response_token_ce`** | Mean Cross-Entropy เฉพาะ Token คำตอบ (ไม่รวม `<eos>`) | วัดความแม่นยำเนื้อหาเชิงเหตุผลแยกจาก Formatting |
| **`eos_ce_loss`** | Cross-Entropy เฉพาะตำแหน่ง `<eos>` | ตรวจจับปัญหา Runaway Generation ตั้งแต่ Stage 1 |
| **`slot_token_acc`** | Token-level Accuracy เฉพาะ Token `<slot_0>..<slot_31>` | ตรวจสอบ Entity Binding Fidelity (V12 Stage 1–4) |
| **`tf_fg_gap` (Teacher-Forcing vs Free-Generation Gap)** | ผลต่าง Exact Match ระหว่าง Teacher-Forced Next-Token กับ Free Autoregressive Decoding | ป้องกัน Exposure Bias ที่มักซ่อนตัวหลัง Loss ต่ำ |
| **`entropy_collapse_flag`** | ตรวจจับ Logit Entropy ต่ำผิดปกติร่วมกับ `unseen`/`ood` ตกต่ำ | หยุด Training เมื่อเกิด Mode/Loss Collapse |
| **`ast_syntax_valid_rate`** *(SE Diagnostic)* | สัดส่วนโค้ด/Schema/SQL ที่โมเดลสร้างแล้ว Parse ผ่าน AST/Syntax Parser จริง | วัดความถูกต้องเชิงไวยากรณ์แยกจาก Cross-Entropy Loss |
| **`repair_patch_convergence`** *(SE Diagnostic)* | อัตราที่ Debugging Prompt พร้อม Error Trace ทำให้ Loss/Test Status ดีขึ้นโดยไม่ทำลายส่วนอื่น | วัดความสามารถ Debugging จริงโดยไม่ใช้อีกโมเดลช่วยแก้ |

---

## 3. Gradient Stability & Regularization Controls

1. **Gradient Clipping:** บังคับ `clip_grad_norm_(model.parameters(), max_norm=1.0)` ทุก Optimizer Step
2. **Weight Decay Exclusion:** ไม่ใส่ Weight Decay กับ `RMSNorm` weights และ `1D` bias/norm tensors; ใส่เฉพาะ Projection/Linear weight matrices (`weight_decay = 0.01` ถึง `0.05`)
3. **Deterministic Seeding:** ทุก Run บันทึก `seed`, `data_shuffle_seed`, `torch.manual_seed` ลงใน Checkpoint Manifest เพื่อทำซ้ำ (Reproducibility) ได้ 100%
4. **No Fake Regularizers / No External Teacher KL:** ห้ามเพิ่ม KL-Divergence หรือ Cosine Distillation Loss จากโมเดลภายนอกเด็ดขาด

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- `apps/core/native/train.py` รองรับการบันทึก Sub-metrics (`eos_ce_loss`, `grad_norm`, `lr`) ใน Training History ของแต่ละ Run เมื่อเข้าสู่การพัฒนาจริงของ V11/V12

### OPEN DECISIONS
- **OD-V12-OBJ-01:** การปรับใช้ Label Smoothing เล็กน้อย (`0.0` vs `0.02`) ใน Stage 2–5 เพื่อชะลอ Over-Confidence บน 50K steps จะตัดสินหลังผล Calibration Test ของ V11

### NOT VERIFIED
- พฤติกรรมของ `tf_fg_gap` และ `slot_token_acc` ตลอด `50,000` Steps บน PyTorch CPU ยัง **NOT VERIFIED / NOT RUN**
