# ZYRQUEN Ω∞ — V11 Master Plan

- **Document ID:** `V11-DOC-01`
- **Status:** `BLUEPRINT ONLY — LOCKED UNTIL V10 FINAL GATE PASS`
- **Target Horizon:** `10,000` Training Steps across `6` Progressive Stages
- **Strategy:** Native-Only (`ZyrquenModel` Random Initialization, Zero Pretrained External Weights, Zero External AI APIs)

---

## 1. Strategic Mission

ZYRQUEN V11 มุ่งยกระดับ **Native General Intelligence (NGI)** จากระดับ Baseline Feasibility ใน V10 ไปสู่ **ความสามารถในการให้เหตุผลเชิงโครงสร้าง การวางแผน การบูรณาการความรู้และหน่วยความจำ และการตรวจสอบตนเอง (Self-Verification)** ด้วยน้ำหนักโมเดลที่ฝึกขึ้นเองตั้งแต่เริ่มต้น (`random initialization`) ภายใต้การควบคุมของ Central Workflow Engine และ Tier-2 Governance

V11 **ไม่ใช่** โปรเจกต์ Chatbot ทั่วไป, **ไม่ใช้** LLM ภายนอกมาตอบแทนโมเดลหลัก, และ **ไม่อ้าง** ความสำเร็จของ AGI/NGI หากไม่มีผล Evaluation จริงครบทั้ง 4 Splits (`train`, `validation`, `unseen`, `ood`)

---

## 2. Entry Criteria (Prerequisites Before V11 Source Code Can Open)

ห้ามเริ่มพัฒนาโค้ด V11 หรือเปิดการฝึก จนกว่าเงื่อนไขต่อไปนี้จะครบ:

1. **V10 Final Closure Gate (`V10-A..D`) = `PASS`:**
   - Architecture & Integration Contracts 1–5 ผ่านครบและทดสอบจริง
   - ช่องโหว่ด้าน Governance ใน `apps/api/routers/workflows.py` (การตรวจ `verify_and_consume_by_id` ใน `/stage`, `/promote`, `/rollback`) และ False-PASS ใน Evaluation Gate ถูกปิดและมี Regression Test คุม
   - V10 Training Hook, Native Inference และ Evaluation Engine เชื่อมสมบูรณ์และมี Baseline Report จริง (เมื่อมี `torch`)
2. **Baseline Artifacts Preserved:** V7, V8, V9 และ V10 Artifacts/Checkpoints อยู่ในสถานะ Immutable ไม่ถูกแก้ไขหรือลบทับ
3. **Roadmap Integrity Intact:** `phases/phase11.py`..`phase20.py` และ `docs/PHASE_11_SPEC.md`..`PHASE_20_SPEC.md` คงเดิม ไม่สร้าง Phase 21
4. **Explicit Approval:** ผู้ดูแลโครงการอนุมัติเปลี่ยนสถานะชุดเอกสาร V11 จาก `BLUEPRINT ONLY` เป็น `APPROVED FOR IMPLEMENTATION`

---

## 3. High-Level Roadmap: 6 Stages / 10,000 Steps

| Stage | Step Range | Steps | Primary Focus | Required Exit Proof |
|---|---|---:|---|---|
| **Stage 1** | `1 – 1,000` | `1,000` | Format & Atomic Slot Alignment (`zyrquen.sft.v1`, `zyrquen.tokenizer.v2`, EOS termination) | Finite loss, `eos_hit_rate >= 0.90`, zero NaN/divergence |
| **Stage 2** | `1,001 – 3,000` | `2,000` | Abstract Reasoning & Relational Generalization (2–3 hop + distractor suppression) | Validation + Unseen accuracy improves over Stage 1 |
| **Stage 3** | `3,001 – 5,000` | `2,000` | Multi-Step Planning & Dependency DAG Ordering (`impossible` + unique topological plan) | Planning accuracy target met; Stage 2 retention intact |
| **Stage 4** | `5,001 – 7,000` | `2,000` | Knowledge Integration, Belief Revision & Grounded Memory (`[source=...]` + `conflict`) | Override vs Conflict accuracy target met; tenant/PII checks pass |
| **Stage 5** | `7,001 – 8,500` | `1,500` | Self-Verification (`true`/`false`/`unknown`, `valid`/`invalid_*`, `fact` vs `assumption`) | Verification gate pass; TF-FG exposure gap strictly bounded |
| **Stage 6** | `8,501 – 10,000` | `1,500` | Joint Consolidation, OOD Transfer (4–6+ hops) & Anti-Regression Polish | Full 4-split Eval PASS; Zero Regression vs V10 & prior stages |

---

## 4. Non-Negotiable Constraints

1. **Zero Duplication:** ใช้ `apps/core/native/train.py`, `apps/core/native/registry.py`, `apps/core/native/evaluation/engine.py`, `apps/core/workflow/` ที่มีอยู่เป็นแกนเดียว
2. **CPU-First Budget Discipline:** เริ่มต้นด้วย `V11-Tier0` (`<= 5,000,000` parameters, `max_seq_len=256`, `batch_size <= 4`, `CPU threads <= 2`, RAM soft `3.0 GB` / hard `3.5 GB`) จนกว่าจะมี PyTorch Benchmark พิสูจน์การขยาย
3. **Zero Auto-Training / Zero Auto-Promotion:** ทุกการรัน Training และ Model Promotion ต้องผ่าน Tier-2 HMAC-SHA256 Single-Use Approval Token จาก Admin
4. **Honest Reporting:** คงสถานะ `PASS / FAIL / BLOCKED / NOT RUN` แยกเด็ดขาดเสมอ

---

## 5. Mandatory Truthfulness Sections

### ASSUMPTIONS
- ชุดข้อมูล V11 จะพัฒนาต่อยอดจาก `tools/gen_nagi_v10.py` และ `tools/audit_leakage_v10.py` โดยเพิ่ม Split/Depth/Memory/Verification Coverage ภายใต้ Canonical Schema ที่เข้ากันได้กับ `zyrquen.dataset-manifest.v1`
- Hardware พื้นฐานในการพัฒนาคือ CPU-only (`HONOR X6b 6GB` หรือ Workspace CPU 4 cores / 12GB RAM)

### OPEN DECISIONS
- **OD-MP-01:** อนุมัติวิธีการรัน 10,000 Steps — รันแบบ 20 Segments × 500 Steps (ใช้ Budget Lock เดิม 100%) หรืออนุมัติขยาย `MAX_CPU_TRAINING_STEPS` ต่อ Segment หลังวัด CPU speed แล้ว
- **OD-MP-02:** เกณฑ์ Exact-Match ขั้นต่ำราย Capability ของ V11 Stage 6 ควรตั้งเท่าใดหลังเห็น Baseline จริงของ V10 (ดู [V11_EVALUATION_PLAN.md](./V11_EVALUATION_PLAN.md))

### NOT VERIFIED
- V10 Final Gate ยังไม่ถูกปิดสมบูรณ์ใน Source Code (รอการดำเนินการ V10-A..D)
- ความเร็ว Training จริง (seconds/step) และอัตราการลดของ Loss บน `10,000` steps ยัง **NOT VERIFIED** เนื่องจากยังไม่มี `torch` ในสภาพแวดล้อมปัจจุบัน
