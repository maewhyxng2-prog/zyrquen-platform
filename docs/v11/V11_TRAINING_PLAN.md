# ZYRQUEN Ω∞ — V11 Training Plan (10,000 Steps / 6 Stages)

- **Document ID:** `V11-DOC-05`
- **Status:** `BLUEPRINT ONLY — LOCKED UNTIL V10 FINAL GATE PASS`
- **Total Training Horizon:** `10,000` optimizer steps across `6` sequential stages
- **Execution Engine:** `apps/core/native/train.py::train_sft` invoked via `CentralWorkflowOrchestrator` + `handle_training_execute`
- **Initialization:** Random Initialization (`ZyrquenModel`), strictly CPU-only under Tier-2 HMAC Approval Gate

---

## 1. Six-Stage 10,000-Step Curriculum Schedule

| Stage | Global Steps | Stage Steps | Capability / Data Mixture | LR Regime (AdamW, betas=(0.9, 0.95), wd=0.01–0.1) | Eval & Checkpoint Cadence |
|---|---:|---:|---|---|---|
| **Stage 1: Token & Slot Alignment** | `1 – 1,000` | `1,000` | Simple 1–2 hop `abstract_reasoning` + `relational_generalization` (slot permutation ON), focus on `<slot_k>`, `SFT_SEP`, `<|eos|>` | Warmup `100` steps `0 -> 3e-4`, hold/gentle cosine `3e-4 -> 2.7e-4` | Eval/Ckpt every `250` steps |
| **Stage 2: Abstract & Relational Core** | `1,001 – 3,000` | `2,000` | `40%` `abstract_reasoning` + `45%` `relational_generalization` (2–3 hops, distractors, shuffled facts) + `15%` Stage 1 retention | Cosine `2.7e-4 -> 2.2e-4` | Eval/Ckpt every `500` steps |
| **Stage 3: Multi-Step Planning** | `3,001 – 5,000` | `2,000` | `50%` `multi_step_planning` (unique Kahn topological + `impossible`) + `25%` `abstract_reasoning` + `25%` `relational_generalization` | Cosine `2.2e-4 -> 1.6e-4` | Eval/Ckpt every `500` steps |
| **Stage 4: Knowledge & Grounded Memory** | `5,001 – 7,000` | `2,000` | `50%` `knowledge_integration` (`base`/`update`/`retract`/`conflict` + `[source=...]`) + `50%` replay Stages 1–3 | Cosine `1.6e-4 -> 1.1e-4` | Eval/Ckpt every `500` steps |
| **Stage 5: Self-Verification** | `7,001 – 9,000` | `2,000` | `45%` `self_verification` (claim + plan defects + `fact`/`assumption`/`unverified`) + `55%` replay Stages 2–4 | Cosine `1.1e-4 -> 7e-5` | Eval/Ckpt every `500` steps |
| **Stage 6: Joint OOD & Consolidation** | `9,001 – 10,000` | `1,000` | Balanced mix across all 6 capabilities (`~16.7%` each) incl. harder `ood_transfer` train compositions (2–3+ hop mixed relations) | Cosine decay `7e-5 -> min_lr (3e-5)` | Eval/Ckpt every `250` steps + Final Stage Gate |

**Exact Sum:** `1,000 + 2,000 + 2,000 + 2,000 + 2,000 + 1,000 = 10,000` cumulative global optimizer steps (`1,000 → 3,000 → 5,000 → 7,000 → 9,000 → 10,000`).

---

## 2. Global Steps vs. Experiment Steps Accounting (`<= 500` Steps/Experiment Lock)

โค้ดปัจจุบันใน `apps/core/workflow/autonomous_training_loop.py` ล็อก `MAX_STEPS = 500` ต่อหนึ่ง Experiment และ `apps/core/workflow/resource_guard.py` ล็อก `MAX_CPU_TRAINING_STEPS = 1_000` เพื่อความปลอดภัยของ CPU และเวลาต่อรอบ (`EXPERIMENT_TIMEOUT_SECONDS = 1200s`)

ดังนั้น V11 บังคับใช้ **การแยกบัญชี Global Steps กับ Experiment Steps อย่างเคร่งครัด**:
1. **Per-Experiment Ceiling:** ทุก Run ต้องมี `experiment_steps <= 500` (`MAX_STEPS = 500`) ดังนั้น `10,000` Global Steps ต้องประกอบด้วย **อย่างน้อย `20` Experiments ต่อเนื่อง (`EXP-01` ถึง `EXP-20`)** — Stage 1 (`2×500`), Stage 2 (`4×500`), Stage 3 (`4×500`), Stage 4 (`4×500`), Stage 5 (`4×500`), Stage 6 (`2×500`)
2. **Disjoint Step Window Accounting:** แต่ละ Experiment ต้องบันทึก `[global_step_start, global_step_end]` ต่อจาก Checkpoint ล่าสุด (`global_step_start == resumed_from_step`, `global_step_end == global_step_start + actual_steps_executed`) **ห้ามนับซ้ำ (double-counting) หรือข้ามช่วง step (gap)** และหาก Experiment หยุดก่อนครบ 500 steps Experiment ถัดไปต้องต่อจาก `actual_step_reached` เท่านั้น
3. **Checkpoint Lineage & Evaluation History Continuity:** ทุก Experiment ที่ปิดรอบต้องเชื่อม `parent_version` / `resumed_from_checkpoint_sha256` และบันทึกผลเข้า `EvaluationHistory` / `ModelRegistry` ก่อนอนุญาตให้ Tier-2 Approval เปิด Experiment ถัดไป
4. **Stage Transition Gate:** ห้ามเริ่ม Stage N+1 อัตโนมัติหาก Stage N ยังไม่ผ่าน Stage Evaluation Gate ที่ `Step 1,000 / 3,000 / 5,000 / 7,000 / 9,000 / 10,000` (ห้ามทำ Blind Continuous Training โดยไม่วัดผล `validation`, `unseen`, `ood`)

---

## 3. Baseline Hyperparameters (`V11-Tier0` Compliant)

- `block_size`: `256` (`<= MAX_CPU_SEQUENCE_LENGTH`)
- `batch_size`: `4` (`<= MAX_CPU_BATCH_SIZE`)
- `grad_accum_steps`: `1` (หรือ `2–4` หลังวัด CPU time/step; `<= MAX_CPU_GRAD_ACCUM_STEPS = 8`)
- `grad_clip`: `1.0`
- `weight_decay`: `0.1` (บน weight tensors `dim >= 2`; `0.0` บน RMSNorm / `dim < 2`)
- `permute_slots`: `True` ระหว่าง Training (สุ่มสลับ `<slot_0>..<slot_31>` เพื่อบังคับ Permutation Equivariance), `False` ระหว่าง Evaluation

---

## 4. Mandatory Stop & Abort Triggers

หยุดการฝึกทันที (Emergency Halt) และเก็บ Diagnostic Snapshot หากเกิดเหตุการณ์ใดเหตุการณ์หนึ่ง:
1. `loss_diverged`: `not math.isfinite(total_loss)` หรือ `TrainingMonitor.log(..., diverged=True)` — ห้ามบันทึก Checkpoint ที่ diverge (`train.py` lines 186/348)
2. `ram_hard_stop`: Peak RSS `>= 3.5 GB` (`RAM_HARD_GB`)
3. `disk_reserve_violated`: Free disk `< 2.0 GB` (`DISK_RESERVE_GB`)
4. `cost_controller.should_stop()`: เกิน Runtime / Budget Limit
5. `Stage Regression`: Validation accuracy ของ Stage ก่อนหน้าลดลงเกิน tolerance โดยไม่ฟื้นใน 2 eval intervals

---

## 5. Mandatory Truthfulness Sections

### ASSUMPTIONS
- การ Resume ระหว่าง Stage ที่เปลี่ยน Mixture ของ Dataset จะจัดการ Learning Rate continuity และ Checkpoint `step` counter ให้สอดคล้องกับ Global Step `1..10,000` (ดู `V11_CHECKPOINT_AND_RECOVERY.md`)
- `grad_accum_steps` ที่เหมาะสมจะถูกกำหนดหลังวัด Step Latency จริงบน CPU Host

### OPEN DECISIONS
- **OD-TP-01:** เลือกแนวทาง Segmented Run (`20 × 500 steps`, ต้องขอ Tier-2 approval ต่อ segment หรือต่อ stage?) กับการสร้าง `stage_max_steps` policy หลังมี benchmark
- **OD-TP-02:** จะใช้ Global Cosine LR Schedule ยาวตลอด `10,000` steps หรือ Warm-Restart / Per-Stage LR schedule เมื่อเปลี่ยน Stage Dataset

### NOT VERIFIED
- เวลาที่ใช้จริงต่อ `500` หรือ `10,000` steps บน CPU (4 cores host และ HONOR X6b) ยัง **NOT VERIFIED**
- อัตราการลืมความรู้เก่า (Catastrophic Forgetting) ระหว่าง Stage 2 → Stage 5 ที่ replay ratio ปัจจุบันยัง **NOT VERIFIED**
