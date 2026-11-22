# ZYRQUEN Ω∞ — V11 Training Objective Specification

- **Document ID:** `V11-DOC-06`
- **Status:** `BLUEPRINT ONLY — LOCKED UNTIL V10 FINAL GATE PASS`
- **Canonical Training Function:** `apps/core/native/train.py::train_sft`
- **Prompt/Label Contract:** `apps/core/native/sft.py` (`zyrquen.sft.v1`)

---

## 1. Primary Loss Function (Canonical Masked SFT Cross-Entropy)

V11 ใช้ **Causal-Shifted Masked Cross-Entropy Loss** ที่ implement อยู่จริงใน `apps/core/native/model.py` (`F.cross_entropy(..., ignore_index=-100)`) ร่วมกับ `apps/core/native/sft.py::encode_sft_pair`:

$$\mathcal{L}_{\text{SFT}}(\theta) = -\frac{1}{|T|} \sum_{t \in T} \log P_\theta(y_t \mid x_{\le t})$$

โดยที่:
- `prefix_ids = [bos_id] + encode(bound_prompt + SFT_SEP)` (`SFT_SEP = "\n### Response:\n"`)
- `target_ids = encode(bound_target) + [eos_id]`
- `full_ids = prefix_ids + target_ids`
- `full_labels = [-100] * len(prefix_ids) + target_ids`
- **Causal Shift:** `x = full_ids[:-1]`, `y = full_labels[1:]`
  - ตำแหน่งสุดท้ายของ `SFT_SEP` ทำนายโทเคนแรกของคำตอบ
  - ตำแหน่งสุดท้ายของคำตอบทำนาย `eos_id`
  - โทเคน Prompt และ Right-Padding (`collate_sft_batch`) มี Label `-100` (`IGNORE_INDEX`) ทั้งหมด เพื่อไม่ให้โมเดลเสียความจุไปกับการท่องจำรูปแบบ Prompt Input

---

## 2. Structural Learning Objectives Across Capabilities

1. **Exact Target & EOS Termination Learning:** เพราะ `eos_id` อยู่ใน `target_ids` โมเดลถูกบังคับให้เรียนรู้จุดสิ้นสุดคำตอบที่แน่นอน ลดปัญหา repetition loop
2. **Slot-Equivariance Induction:** ด้วยการเปิด `permute_slots=True` ใน Training (สุ่มสลับ mapping `<slot_0>..<slot_31>`) โมเดลไม่สามารถอาศัยค่า Embedding ID ของ Slot คงที่ได้ แต่ต้องอาศัย **Attention Pattern ระหว่างตำแหน่ง Slot ใน Context** เพื่อเชื่อมโยงเหตุผลและ Copy คำตอบจาก Input Slot ไปยัง Target Slot
3. **Abstention & Conflict Calibration:** ตัวอย่าง `"unknown"`, `"conflict"`, `"impossible"`, `"invalid_*"` ถูกถ่วงน้ำหนักรวมใน SFT Loss พร้อม Distractor Context เพื่อลดพฤติกรรม Copy Bias / Confident Guessing
4. **Exposure Bias Mitigation:** วัดค่า `TF Exact - FG Exact` (Teacher-Forced vs Free-Generation) ทุก Stage เพื่อตรวจจับ Exposure Bias ในคำตอบแบบ Multi-Token (เช่น `multi_step_planning` sequence `E_a -> E_b -> E_c`)

---

## 3. Optimizer & Gradient Controls

- **Optimizer:** `AdamW` แยก 2 Parameter Groups:
  - `decay` (`p.dim() >= 2`): `weight_decay = cfg.weight_decay`
  - `no_decay` (`p.dim() < 2`, i.e., RMSNorm weights): `weight_decay = 0.0`
  - `betas = (0.9, 0.95)`
- **Gradient Clipping:** `torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)` (`grad_clip = 1.0`)
- **NaN / Inf Fail-Closed Guard:** หาก `not math.isfinite(total_loss)` ให้ `optimizer.zero_grad(set_to_none=True)` และหยุดทันทีด้วย `stopped_reason = "loss_diverged"` โดยไม่เซฟ Checkpoint ที่เสียหาย

---

## 4. Potential Future Objective Extensions (Requires Separate Approval)

รายการต่อไปนี้ **ยังไม่เปิดใช้งาน** ใน V11 Baseline แรก แต่เตรียมไว้เป็นทางเลือกใน Phase หลัง Stage 3 หากพบข้อจำกัด:
- **Length-Normalized / Sequence-Level Contrastive Margin** สำหรับ `multi_step_planning` หาก Free-Generation สับสนลำดับขั้นตอน
- **Token-Type Loss Reweighting** สำหรับคำตอบสั้น (`>`, `<`, `unknown`) เทียบกับคำตอบยาว (`E_a -> E_b -> E_c`) เพื่อป้องกัน gradient imbalance ระหว่าง 6 capabilities

---

## 5. Mandatory Truthfulness Sections

### ASSUMPTIONS
- การใช้ Masked SFT Cross-Entropy เพียงอย่างเดียวร่วมกับ `permute_slots=True` สามารถสอนทั้ง single-token classification (`>`, `<`, `true`) และ multi-token topological planning บน `ZyrquenModel` ได้
- `SFT_SEP = "\n### Response:\n"` และ `eos_id` เพียงพอในการแบ่งขอบเขต Input/Output ทั้งขณะ Train และ Inference

### OPEN DECISIONS
- **OD-TO-01:** ควรปรับสมดุลจำนวนตัวอย่าง/น้ำหนักของ Multi-token planning examples กับ Single-token classification examples หรือไม่ (เพราะ single-token output มี 2 tokens คือ answer + `<|eos|>`, ขณะที่ multi-step plan มี `~8–25` tokens)
- **OD-TO-02:** จะเพิ่ม Curriculum Scheduled Sampling (ลด TF gap สำหรับ multi-step plan) ใน Stage 5–6 หรือคง Pure Masked SFT ตลอด 10,000 Steps

### NOT VERIFIED
- พฤติกรรมการเรียนรู้ของ `eos_id` และ Loss curve ของทั้ง 6 capabilities ภายใต้ Masked SFT Loss บน `ZyrquenModel` ยัง **NOT VERIFIED** ใน runtime จริง
- ขนาดของ Exposure Bias (`TF exact - FG exact`) บน `multi_step_planning` ยัง **NOT VERIFIED**
