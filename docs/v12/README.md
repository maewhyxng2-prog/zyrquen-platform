# ZYRQUEN Ω∞ — V12 Complete Documentation Package (Index)

- **Document Set Version:** `v12.0-blueprint.1`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Prerequisite Chain:** `V10 Runtime Closure PASS -> V11 10,000-Step Final Gate PASS -> V12 Stage Gate Execution`
- **Rule:** `50,000` Cumulative Training Steps เป็น **เป้าหมายสะสมล่วงหน้าเพื่อเตรียมความพร้อม** ไม่ใช่คำสั่งให้เริ่มฝึกทันที ห้ามเขียน Source Code ของ V12, ห้ามเริ่ม Training/Inference, ห้ามแก้ `v7`/`v8`/`v9`/`v10` หรือ Checkpoints เดิม, ห้ามแก้ `phases/phase11..20` หรือสร้าง Phase 21 และห้าม Commit/Push/Merge/Deploy จนกว่า V10 และ V11 จะผ่าน Final Gate ครบตามลำดับ

---

## 1. Purpose of This Package

ชุดเอกสาร `docs/v12/` จัดทำขึ้นล่วงหน้าเป็น **Single Source of Truth ด้านสถาปัตยกรรม, สเปกโมเดล, ข้อมูล, แผนฝึกสะสม 50,000 Steps, การประเมิน, ความปลอดภัย, และ Gate ปล่อยรุ่น** สำหรับ **ZYRQUEN V12** เพื่อให้หลังการปิด V10 (Runtime Closure) และ V11 (10,000 Steps) แล้ว ทีมวิศวกรรมสามารถเข้าสู่ V12 ได้อย่างมีวินัย ตรวจสอบย้อนกลับได้ทุก Step และปราศจากโมเดลภายนอกหรือผลลัพธ์ปลอม

---

## 2. Canonical Single-Source Constants (Locked Across All 23 Docs)

| Dimension | Locked V12 Blueprint Specification | Code / Repo Anchor |
|---|---|---|
| **Strategy** | Native-Only, Random Initialization (`ZyrquenModel`), Zero Pretrained External Weights, Zero External AI APIs, Zero Distillation | `apps/core/native/model.py` |
| **Model Type** | `zyrquen-decoder` (Pre-RMSNorm + RoPE + Causal SDPA + SwiGLU FFN) | `apps/core/native/config.py` |
| **CPU Entry Tier** | `V12-Tier0` (สืบทอดเพดาน `<= 5,000,000` params ของ `V11-Tier0`: Default `3,737,856`, Vocab-4096 `4,262,144`, Deep-6L `4,754,688`), `max_seq_len=256..512`, `batch_size<=4`, `CPU threads<=2` | `MAX_V10_PARAMETERS`, `autonomous_training_loop.py` |
| **Higher Scaling Tiers** | `V12-Tier1` (`~12.19M`), `V12-Tier2` (`~27.80M`) — **LOCKED / NOT APPROVED** จนกว่า V11 Runtime Benchmark + Resource Headroom + Tier-2 Approval จะผ่าน | `V12_RESOURCE_AND_SCALING.md` |
| **Tokenizer Contract** | Byte-level BPE (`ZyrquenTokenizer`), `SCHEMA_V2 = "zyrquen.tokenizer.v2"`, 4 control tokens + 32 atomic `<slot_0>..<slot_31>` tokens, train-only BPE merges, EL-05 enforced | `apps/core/native/tokenizer.py` |
| **SFT Format Contract** | `SFT_FORMAT_VERSION = "zyrquen.sft.v1"`, `SFT_SEP = "\n### Response:\n"`, `IGNORE_INDEX = -100` (สืบทอด `UN`/`OO` slot binding หลัง V11 เปิดใช้งานแล้ว) | `apps/core/native/sft.py` |
| **Training Horizon** | **`50,000` Cumulative Global Optimizer Steps** แบ่ง **6 Stages** (`5K + 8K + 10K + 10K + 8K + 9K`), อย่างน้อย **`>= 100` Disjoint Experiments** ภายใต้ `MAX_STEPS = 500`/experiment เว้นแต่ขออนุมัติขยายเพดานพร้อม Benchmark | `V12_TRAINING_PLAN.md`, `autonomous_training_loop.py` |
| **Core Capabilities (6)** | `abstract_reasoning`, `relational_generalization`, `ood_transfer`, `multi_step_planning`, `self_verification`, `knowledge_integration` (พร้อม Domain-Scale Coverage & Belief Revision) | `V12_CAPABILITY_SPECIFICATION.md` |
| **Evaluation Splits (4)** | `train`, `validation`, `unseen`, `ood` + Anti-Regression vs V10 & V11 Baselines | `V12_EVALUATION_PLAN.md`, `V12_V11_COMPATIBILITY.md` |
| **Governance** | Central Workflow Engine + `WorkflowResourceGuard` + Tier-2 HMAC-SHA256 Single-Use Approval + Zero Auto-Train / Zero Auto-Promote | `apps/core/workflow/` |

---

## 3. Canonical 6-Stage / 50,000 Cumulative Step Map

| Stage | Name | Stage Steps | Cumulative Exit Step | Min Experiments (`<= 500`/exp) |
|---|---|---:|---:|---:|
| **Stage 1** | Native Representation | `5,000` | `5,000` | `10` (`EXP-001..010`) |
| **Stage 2** | Knowledge Acquisition | `8,000` | `13,000` | `16` (`EXP-011..026`) |
| **Stage 3** | Abstract & Relational Reasoning | `10,000` | `23,000` | `20` (`EXP-027..046`) |
| **Stage 4** | Multi-step Planning & OOD Transfer | `10,000` | `33,000` | `20` (`EXP-047..066`) |
| **Stage 5** | Memory & Knowledge Integration | `8,000` | `41,000` | `16` (`EXP-067..082`) |
| **Stage 6** | Self-Verification & Capability Integration | `9,000` | `50,000` | `18` (`EXP-083..100`) |
| **Total** | **ZYRQUEN V12 Cumulative Target** | **`50,000`** | **`50,000`** | **`100`** |

---

## 4. Complete Document Directory (23 Files)

### A. Strategic & Architecture
1. `README.md` (`V12-DOC-00`) — สารบัญ ค่าคงที่กลาง และสถานะของชุดเอกสาร V12
2. [V12_MASTER_PLAN.md](./V12_MASTER_PLAN.md) (`V12-DOC-01`) — เป้าหมาย เงื่อนไข Gate จาก V10/V11 และแผน 6 Stages 50,000 Steps
3. [V12_ARCHITECTURE.md](./V12_ARCHITECTURE.md) (`V12-DOC-02`) — สถาปัตยกรรม Native Model ระดับ 50K, Reasoning/Memory/Verification Pipeline และกฎห้ามโมเดลภายนอก
4. [V12_MODEL_SPECIFICATION.md](./V12_MODEL_SPECIFICATION.md) (`V12-DOC-03`) — Parameters, Layers, Dimensions, Memory Footprint และ Configuration Matrix
5. [V12_CAPABILITY_SPECIFICATION.md](./V12_CAPABILITY_SPECIFICATION.md) (`V12-DOC-04`) — นิยาม I/O Schema และเกณฑ์เชิงปริมาณของความสามารถหลักทั้ง 6 ด้าน

### B. Training & Data
6. [V12_TRAINING_PLAN.md](./V12_TRAINING_PLAN.md) (`V12-DOC-05`) — แผนการฝึก 50,000 Steps แบ่ง 6 Stages, Global vs Experiment Accounting, LR และ Stop Rules
7. [V12_TRAINING_OBJECTIVE.md](./V12_TRAINING_OBJECTIVE.md) (`V12-DOC-06`) — Masked SFT Loss (`-100`), Calibration/EOS Diagnostics, Gradient Clipping และ Exposure Bias Controls
8. [V12_DATASET_SPECIFICATION.md](./V12_DATASET_SPECIFICATION.md) (`V12-DOC-07`) — โครงสร้าง Dataset 4 Splits (`train`, `validation`, `unseen`, `ood`), OOD Transfer Suites และ Manifest Provenance
9. [V12_DATA_QUALITY_AND_LEAKAGE.md](./V12_DATA_QUALITY_AND_LEAKAGE.md) (`V12-DOC-08`) — Data Integrity, Exhaustive Unique-Answer Solvers, EL-01..06, TL-01, SL-01, DL-01
10. [V12_TOKENIZER_SPECIFICATION.md](./V12_TOKENIZER_SPECIFICATION.md) (`V12-DOC-09`) — Byte-level BPE (`zyrquen.tokenizer.v2`), Atomic Slots (`<slot_0>..<slot_31>`), SHA-256 Pinning

### C. Evaluation & Intelligence
11. [V12_EVALUATION_PLAN.md](./V12_EVALUATION_PLAN.md) (`V12-DOC-10`) — แผนประเมินทุก Stage ครบ 4 Splits พร้อม Anti-False-PASS & Baseline Delta Comparisons
12. [V12_REASONING_BENCHMARK.md](./V12_REASONING_BENCHMARK.md) (`V12-DOC-11`) — ชุดทดสอบ Abstract Reasoning, Relational Generalization, Multi-step Planning และ OOD Transfer (6–10+ hops)
13. [V12_MEMORY_AND_KNOWLEDGE.md](./V12_MEMORY_AND_KNOWLEDGE.md) (`V12-DOC-12`) — การเชื่อมต่อ `MemoryStore` (Phase 17) & `KnowledgeSystem`, Tenant Isolation, Belief Revision
14. [V12_SELF_VERIFICATION.md](./V12_SELF_VERIFICATION.md) (`V12-DOC-13`) — Self-Verification Protocol, Fact/Assumption/Unverified Separation (Phase 16) และ Abstention Discipline

### D. Infrastructure & Governance
15. [V12_RESOURCE_AND_SCALING.md](./V12_RESOURCE_AND_SCALING.md) (`V12-DOC-14`) — Hardware Baselines, CPU/RAM/Disk Guardrails, Wall-Clock Budgeting สำหรับ 50,000 Steps
16. [V12_CHECKPOINT_AND_RECOVERY.md](./V12_CHECKPOINT_AND_RECOVERY.md) (`V12-DOC-15`) — Immutable Versioned Checkpoints (`EXP-001..100`), `weights_only=True`, Resume และ Recovery
17. [V12_SECURITY_AND_GOVERNANCE.md](./V12_SECURITY_AND_GOVERNANCE.md) (`V12-DOC-16`) — Native-Only Guard, Tier-2 HMAC-SHA256 Approval, Paid Compute Guard และ Audit Trail

### E. Control & Transition
18. [V12_INTEGRATION_CONTRACT.md](./V12_INTEGRATION_CONTRACT.md) (`V12-DOC-17`) — สัญญาการเชื่อมต่อเข้ากับ Central Workflow Engine, ModelRegistry, EvaluationEngine และ API
19. [V12_TEST_STRATEGY.md](./V12_TEST_STRATEGY.md) (`V12-DOC-18`) — แผน Unit, Integration, Regression, Anti-Leakage และ PyTorch Runtime Tests
20. [V12_RELEASE_GATE.md](./V12_RELEASE_GATE.md) (`V12-DOC-19`) — เกณฑ์บังคับราย Stage และ Final Release Gate ก่อนประกาศ V12 COMPLETE
21. [V12_RISK_REGISTER.md](./V12_RISK_REGISTER.md) (`V12-DOC-20`) — ทะเบียนความเสี่ยงระดับ 50,000 Steps (Catastrophic Forgetting, Loss Collapse, Resource Exhaustion)
22. [V12_V11_COMPATIBILITY.md](./V12_V11_COMPATIBILITY.md) (`V12-DOC-21`) — การรักษา V10/V11 เป็น Immutable Baselines และความเข้ากันได้ของ Schema & Registry
23. [V12_CHANGELOG.md](./V12_CHANGELOG.md) (`V12-DOC-22`) — บันทึกประวัติการปรับปรุงชุดเอกสาร V12

---

## 5. Mandatory Truthfulness Sections

### ASSUMPTIONS
- V10 Runtime Closure และ V11 10,000-Step Final Release Gate จะผ่านสมบูรณ์แบบตรวจสอบย้อนกลับได้ก่อนที่ V12 จะเปิดรับการฝึกจริงแม้แต่ 1 Step
- โครงสร้าง `CentralWorkflowOrchestrator`, `ModelRegistry`, `EvaluationEngine`, และ `ZyrquenModel` ใน V12 ยังคงยึด Native-Only Strategy 100%

### OPEN DECISIONS
- **OD-V12-00:** รูปแบบการรัน 50,000 Steps — คง `MAX_STEPS = 500`/experiment (`100` experiments) หรือปรับเพดานต่อ experiment หลังมี CPU/RAM benchmark จาก V11 จริง
- **OD-V12-01:** อนุมัติขยายจาก `V12-Tier0` (`<= 5M`) ไปยัง `V12-Tier1` (`12.19M`) หรือไม่ หลังได้ผล Capacity Saturation Check จาก V11

### NOT VERIFIED
- **V10 & V11 Baselines:** ปัจจุบัน V10 ยังไม่มี PyTorch Runtime Checkpoint และ V11 ยังถูกล็อกอยู่ ผล Benchmark ของทั้ง V10 และ V11 จึงเป็น `NOT RUN / NOT VERIFIED`
- **50,000-Step CPU Wall-Clock Time & Thermal Endurance:** ระยะเวลาการรันสะสม `100` experiments บน CPU-only container ยัง **NOT VERIFIED**
- **V12 Scaling Tiers (`Tier1`/`Tier2`):** Peak RSS และความเสถียรของ Loss บนขนาด >5M parameters ยัง **NOT VERIFIED**
