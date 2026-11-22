# ZYRQUEN Ω∞ — V12 Integration Contract

- **Document ID:** `V12-DOC-17`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Core Rule:** Zero Duplicate Engines — Register V12 as Workflows inside `CentralWorkflowOrchestrator` Only

---

## 1. Mandatory Reuse of Existing System Core

ห้ามสร้าง Scheduler ใหม่, Registry ใหม่, หรือ Evaluation Loop แยกต่างหาก V12 ต้องเชื่อมต่อผ่านสัญญาของระบบกลางที่มีอยู่แล้ว:

| Subsystem | Existing Module Anchor | V12 Integration Point | Contract Constraint |
|---|---|---|---|
| **Central Workflow Engine** | `apps/core/workflow/orchestrator.py`, `groups.py` | ลงทะเบียน V12 Stage Pipelines ผ่าน `CentralWorkflowOrchestrator` | ทุก Run ต้องเดินตาม Flow: Trigger -> ResourceGuard -> Tier-2 Gate -> Execute -> Eval Gate -> Audit |
| **Native Training Hook** | `apps/core/native/train.py`, `groups.py::handle_training_execute` | ส่ง Config + `parent_checkpoint` + `dataset_manifest` + `stage_id` | ห้าม Bypass `WorkflowResourceGuard` หรือ `MAX_STEPS` Policy |
| **Evaluation Engine** | `apps/core/native/evaluation/engine.py`, `groups.py::handle_evaluation_gate` | เรียก `EvaluationEngine.evaluate_native_model` บน 4 Splits (`train_diag`, `validation`, `unseen`, `ood`) | ห้าม Override `zero_regression` หรือ Fake Report Fields |
| **Model Registry** | `apps/core/native/registry.py::ModelRegistry` | บันทึก Lineage `v12.x`, `attach_evaluation_evidence`, `compare_versions`, `promote` | ห้ามแก้ไข/ลบ `FROZEN_BASELINE_NAMES` หรือ V7..V11 Versions |
| **Inference & Conversations API** | `apps/api/routers/inference.py`, `conversations.py` | ชี้ Active Promoted Checkpoint ของ V12 เฉพาะเมื่อ `V12 Release Gate = PASS` | ต้องคง Explicit Disclosure ของ Model Version & Status เสมอ |
| **Memory & Epistemic Verification** | Phase 16 & Phase 17 Modules (`phases/phase16.py`, `phase17.py`) | เชื่อมต่อแบบ Adapter Layer ใน Workflow/Inference Pipeline สำหรับ Stage 5–6 | **ห้ามแก้ไฟล์ `phases/phase11..20.py` หรือสร้าง Phase 21** |
| **App Build & Verification Harness** *(V12 SE Extension)* | Sandboxed Runner + `CentralWorkflowOrchestrator` + `EvaluationEngine` | เชื่อมต่อ Generation ของ `ZyrquenModel` เข้ากับ Compile, Unit/Integration/Hidden Tests และ Security Scans | Deterministic Execution เท่านั้น ห้ามใช้ External LLM ช่วยเขียน/แก้โค้ด และต้องผ่าน Tier-2 Isolation Rules |

---

## 2. End-to-End 8-Group Workflow Mapping for V12

ตามโครงสร้าง 8 กลุ่มหลักของ ZYRQUEN Workflow Engine:
1. **System Operations:** ตรวจสุขภาพ CPU/RAM/Disk ก่อนทุก Experiment ใน `EXP-001..100`
2. **Data Workflow:** สร้าง/ตรวจสอบ Hash & Leakage (`EL-01..06`, `TL-01`, `SL-01`, `DL-01`) ของ V12 Dataset Splits
3. **Native Training:** รัน Experiment ภายใต้ Tier-2 Token + บันทึก Immutable Checkpoint + Abort บน NaN/OOM
4. **Evaluation:** รัน Micro-Check (`500` steps) และ Full 4-Split Stage Exit Gate
5. **Knowledge & Memory:** อัปเดต/ทวนสอบ Grounded Memory Context และตรวจ Conflict ใน Stage 2 & 5
6. **Autonomous Improvement:** เสนอ Hypothesis/Experiment Next-Step จาก Error Profile จริง (*เสนอเท่านั้น — ห้าม Auto-Execute โดยไม่ผ่าน Tier-2*)
7. **Security & Governance:** บังคับ Tier-2 HMAC, Native-Only AST Check, และ Append-Only Audit Logs
8. **Project & Development:** รายงานความคืบหน้าสะสม (`global_step / 50,000`) และสถานะ Gate จริงโดยไม่แต่งตัวเลข

---

## 3. Mandatory Truthfulness Sections

### ASSUMPTIONS
- สัญญา V10-A..D และ V11 Integration Contract (`V11_INTEGRATION_CONTRACT.md`) จะถูก Verified ครบก่อนที่จะเปิด V12 Integration

### OPEN DECISIONS
- **OD-V12-INT-01:** การขยาย `DatasetManifest` ใน `dataset.py` เพื่อเก็บ Metadata `stage_id` และ `replay_mix_sha256` จะดำเนินการตอนเปิดเฟส V11/V12 หลัง V10 Closure ผ่านแล้วเท่านั้น

### NOT VERIFIED
- การทำงานประสานกันแบบ Full End-to-End ของ 8 Workflow Groups กับ Checkpoint ระดับ 50,000 Steps ของ V12 ยัง **NOT VERIFIED / NOT RUN**
