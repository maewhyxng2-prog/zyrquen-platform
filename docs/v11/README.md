# ZYRQUEN Ω∞ — V11 Complete Documentation Package (Index)

- **Document Set Version:** `v11.0-stage1-readiness.1`
- **Status:** `STAGE 1 CODE READINESS APPROVED — TRAINING & PROMOTION STILL TIER-2 LOCKED`
- **Pre-condition Gate:** **V10 Runtime Closure Policy Updated (`CLOSED_FAIL` Immutable Baseline Permitted):** รอบฝึก/ประเมินจริง V10 (`ZYRQUEN-Native-10.0.0`) ปิดเป็น `FAIL` — อนุมัติเปลี่ยนผ่านสู่ **V11 Stage 1 Code Alignment** บนหลักการไม่แก้ผล V10 และไม่ปลอม PASS (การบันทึก `CLOSED_FAIL` อย่างเป็นทางการยังรอตรวจ SHA-256 ต้นทางของรายงาน V10)
- **Rule:** ห้ามแก้ `v7`/`v8`/`v9`/`v10`, ห้ามปรับเกณฑ์เพื่อให้ V10 ผ่าน, ห้ามใช้ External Weights/AI APIs, ห้ามแก้ Roadmap Phase 11–20 หรือสร้าง Phase 21, และห้ามเริ่ม Training/Promotion/Merge โดยไม่มี Tier-2 Approval แยก

---

## 1. Purpose of This Package

ชุดเอกสาร `docs/v11/` นี้จัดทำขึ้นล่วงหน้าเป็น **Single Source of Truth เชิงสถาปัตยกรรม สัญญาระบบ ข้อมูล การฝึก การประเมิน ความปลอดภัย และการเชื่อมต่อระบบ** สำหรับ ZYRQUEN V11 (เป้าหมาย Native General Intelligence 10,000-Step Controlled Training) เพื่อให้เมื่อ V10 ปิดสมบูรณ์แล้ว สามารถเข้าสู่การทบทวน Gate และพัฒนา V11 ได้ทันทีโดยไม่มีความขัดแย้งข้ามเอกสาร

---

## 2. Canonical Single-Source Constants (Locked Across All 22 Docs)

| Dimension | Locked V11 Blueprint Specification | Code / Repo Anchor |
|---|---|---|
| **Strategy** | Native-Only, Random Initialization (`ZyrquenModel`), Zero External Weights / External AI APIs | `apps/core/native/model.py` |
| **Model Type** | `zyrquen-decoder` (Pre-RMSNorm + RoPE + Causal SDPA + SwiGLU FFN) | `apps/core/native/config.py` |
| **Active CPU Baseline Tier** | `V11-Tier0` (`<= 5,000,000` params: Default `3,737,856`, Vocab-4096 `4,262,144`, Deep-6L `4,754,688`), `max_seq_len=256`, `batch_size<=4`, `CPU threads<=2` | `MAX_V10_PARAMETERS`, `MAX_CPU_MODEL_PARAMETERS`, `autonomous_training_loop.py` |
| **Higher Scaling Tiers** | `V11-Tier1` (`12,194,688`), `V11-Tier2` (`27,795,968`) — **LOCKED / NOT APPROVED** จนกว่าจะมี PyTorch RSS/Throughput Benchmark จริง | `docs/SCALING_POLICY.md` |
| **Tokenizer Contract** | Byte-level BPE (`ZyrquenTokenizer`), `SCHEMA_V2 = "zyrquen.tokenizer.v2"`, 4 control tokens + 32 atomic `<slot_0>..<slot_31>` tokens, train-only BPE merges, EL-05 enforced | `apps/core/native/tokenizer.py`, `apps/core/native/sft.py` |
| **SFT Format Contract** | `SFT_FORMAT_VERSION = "zyrquen.sft.v1"`, `SFT_SEP = "\n### Response:\n"`, `IGNORE_INDEX = -100` | `apps/core/native/sft.py` |
| **Training Horizon** | `10,000` total optimizer steps แบ่ง **6 Stages** (รันแบบ segmented checkpoint-resume หรือปรับ cap ผ่าน Tier-2 approval) | `V11_TRAINING_PLAN.md` |
| **Core Capabilities (6)** | `abstract_reasoning`, `relational_generalization`, `ood_transfer`, `multi_step_planning`, `self_verification`, `knowledge_integration` | `tools/gen_nagi_v10.py`, `audit_leakage_v10.py` |
| **Evaluation Splits (4)** | `train`, `validation`, `unseen`, `ood` (รักษาความเข้ากันได้กับ manifest `train`/`validation`/`test` เดิมผ่าน compatibility adapter) | `V11_EVALUATION_PLAN.md`, `V11_V10_COMPATIBILITY.md` |
| **Governance** | Central Workflow Engine + Dual-Lane Queue + `WorkflowResourceGuard` + Tier-2 Single-Use HMAC-SHA256 Approval + Zero Auto-Promote | `apps/core/workflow/` |

---

## 3. Complete Document Directory (22 Control & Spec Docs + README)

### A. Strategic & Architecture (1–4)
1. [V11_MASTER_PLAN.md](./V11_MASTER_PLAN.md) — เป้าหมาย ขอบเขต เงื่อนไขเปิดเฟสจาก V10 และแผนงาน 6 Stages 10,000 Steps
2. [V11_ARCHITECTURE.md](./V11_ARCHITECTURE.md) — สถาปัตยกรรม Native Model, Reasoning/Memory/Verification Pipeline และข้อห้ามด้าน External AI
3. [V11_MODEL_SPECIFICATION.md](./V11_MODEL_SPECIFICATION.md) — พารามิเตอร์ Layers Dimensions สูตรคำนวณ Memory Footprint และ Configuration Matrix
4. [V11_CAPABILITY_SPECIFICATION.md](./V11_CAPABILITY_SPECIFICATION.md) — นิยาม I/O Schema และเกณฑ์ความสามารถทั้ง 6 ด้าน + Self-Verification & Memory Integration

### B. Training & Data (5–9)
5. [V11_TRAINING_PLAN.md](./V11_TRAINING_PLAN.md) — แผนการฝึก 10,000 Steps แบ่ง 6 Stages พร้อม Learning Rate, Curriculum Mix, Exit Criteria และ Stop Conditions
6. [V11_TRAINING_OBJECTIVE.md](./V11_TRAINING_OBJECTIVE.md) — Masked SFT Cross-Entropy Loss (`-100`), Auxiliary Calibration/EOS Margin Analysis, Gradient Clipping และ Exposure Bias Controls
7. [V11_DATASET_SPECIFICATION.md](./V11_DATASET_SPECIFICATION.md) — โครงสร้าง Dataset, Canonical Splits (`train`, `validation`, `unseen`, `ood`), Provenance และ Manifest Schema
8. [V11_DATA_QUALITY_AND_LEAKAGE.md](./V11_DATA_QUALITY_AND_LEAKAGE.md) — Data Integrity, Unique-Answer Exhaustive Solvers, EL-01..06, TL-01, SL-01, DL-01 และ Sequence Budget
9. [V11_TOKENIZER_SPECIFICATION.md](./V11_TOKENIZER_SPECIFICATION.md) — Byte-level BPE (`zyrquen.tokenizer.v2`), Atomic Slots (`<slot_0>..<slot_31>`), Normalization และ SHA-256 Pinning

### C. Evaluation & Intelligence (10–13)
10. [V11_EVALUATION_PLAN.md](./V11_EVALUATION_PLAN.md) — แผนประเมินแยก 4 Splits (`train`, `validation`, `unseen`, `ood`), Per-Stage Gates และห้าม False-PASS
11. [V11_REASONING_BENCHMARK.md](./V11_REASONING_BENCHMARK.md) — ชุดทดสอบ Abstract Reasoning, Relational Generalization, OOD Depth/Structure Transfer และ Multi-Step Planning
12. [V11_MEMORY_AND_KNOWLEDGE.md](./V11_MEMORY_AND_KNOWLEDGE.md) — การเชื่อมต่อ `MemoryStore` (Phase 17) / `KnowledgeSystem`, Tenant Isolation และ Belief Revision
13. [V11_SELF_VERIFICATION.md](./V11_SELF_VERIFICATION.md) — Self-Verification Protocol, Fact/Assumption/Unverified Separation (Phase 16) และ Plan Validation

### D. Infrastructure & Governance (14–16)
14. [V11_RESOURCE_AND_SCALING.md](./V11_RESOURCE_AND_SCALING.md) — Hardware Baselines (HONOR X6b & Host CPU), CPU/RAM/Disk Guardrails, Segmented Scaling Rules
15. [V11_CHECKPOINT_AND_RECOVERY.md](./V11_CHECKPOINT_AND_RECOVERY.md) — Immutable Versioned Checkpoints, `weights_only=True`, Atomic Manifests, Resume & Corruption Recovery
16. [V11_SECURITY_AND_GOVERNANCE.md](./V11_SECURITY_AND_GOVERNANCE.md) — Native-Only Enforcement, Tier-2 HMAC-SHA256 Approval, API Governance, Symlink/Path Safety

### E. Control & Transition Documents (17–22)
17. [V11_INTEGRATION_CONTRACT.md](./V11_INTEGRATION_CONTRACT.md) — สัญญาการเชื่อมต่อ V11 เข้ากับ Workflow Engine, ModelRegistry, EvaluationEngine และ API โดยไม่สร้างซ้ำ
18. [V11_TEST_STRATEGY.md](./V11_TEST_STRATEGY.md) — แผน Unit, Integration, Regression, Anti-False-PASS และ PyTorch Runtime Tests
19. [V11_RELEASE_GATE.md](./V11_RELEASE_GATE.md) — รายการตรวจสอบและเกณฑ์บังคับก่อนประกาศ V11 COMPLETE
20. [V11_RISK_REGISTER.md](./V11_RISK_REGISTER.md) — ทะเบียนความเสี่ยงทางเทคนิค ทรัพยากร ข้อมูล และความปลอดภัย พร้อม Stop Triggers
21. [V11_V10_COMPATIBILITY.md](./V11_V10_COMPATIBILITY.md) — การใช้ V10 เป็น Baseline แบบ Immutable และ Schema/Registry Backward Compatibility
22. [V11_CHANGELOG.md](./V11_CHANGELOG.md) — บันทึกการเปลี่ยนแปลงของชุดเอกสาร V11

---

## 4. Mandatory Truthfulness Sections (Package Level)

### ASSUMPTIONS
- V10 จะผ่าน Closure Gate (`V10-A` ถึง `V10-D`) และได้รับอนุมัติปิดก่อนที่จะเริ่มแก้ไข Source Code ใดๆ ของ V11
- สภาพแวดล้อมที่ใช้รัน Training/Evaluation จริงในอนาคตจะติดตั้ง PyTorch (`torch`) แบบ CPU หรือ Compute ที่ได้รับอนุมัติแยกต่างหาก

### OPEN DECISIONS
- **OD-00:** เลือกระดับ Parameter Tier สำหรับรอบ V11 แรก (`V11-Tier0` `3.74M` / `4.75M` เทียบกับ `V11-Tier1` `12.19M` หลังมี Benchmark)
- **OD-01:** เลือกรูปแบบการรัน 10,000 Steps ระหว่าง segmented checkpoint-resume (`<= 500` หรือ `<= 1000` steps ต่อ run) กับการปรับเพดาน `MAX_STEPS` หลังอนุมัติงบประมาณ/เวลา
- **OD-02:** การขยาย `SPLITS` ใน `dataset.py` / `registry.py` เพื่อรองรับ `unseen.jsonl` และ `ood.jsonl` ควบคู่กับ `test.jsonl`

### NOT VERIFIED
- **PyTorch Runtime Execution:** Container ปัจจุบันไม่มี `torch` ติดตั้งอยู่ จึงยัง **NOT VERIFIED** ด้าน Training throughput (tokens/sec), Real Peak RSS, Convergence บน 10,000 Steps และ Real Inference Accuracy
- **V10 Baseline Numbers:** ยังไม่มี Checkpoint ที่ผ่านการฝึกของ V10 ใน workspace นี้ ตัวเลข Benchmark ของ V10 จึงยังเป็น `NOT RUN`
- **HONOR X6b Thermal/RAM Endurance:** การรัน 10,000 Steps บนอุปกรณ์พกพายังไม่มีผลวัดจริง
