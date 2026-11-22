# ZYRQUEN Ω∞ — V11 Integration Contract (Zero Duplication with V10)

- **Document ID:** `V11-DOC-17`
- **Status:** `BLUEPRINT ONLY — LOCKED UNTIL V10 FINAL GATE PASS`
- **Core Rule:** ห้ามสร้าง Trainer, Registry, Workflow Engine, Resource Guard, Checkpoint Manager, หรือ Evaluation Engine ชุดใหม่ซ้ำ — ให้ Reuse และ Extend ระบบเดิมผ่าน Contract ชัดเจนเท่านั้น

---

## 1. Existing Component Reuse & Extension Map

| Domain | Canonical Module to Reuse | How V11 Connects | Allowed Targeted Extension (After V10 Gate Only) |
|---|---|---|---|
| **Model & Config** | `apps/core/native/config.py`, `model.py` (`ZyrquenConfig`, `ZyrquenModel`) | คง `zyrquen-decoder` และ `V11-Tier0` (`<= 5M`) | หาก Scaling Gate ผ่านจึงเพิ่ม Tier-1/Tier-2 config constants (ไม่แก้ default `ZyrquenConfig()`) |
| **Tokenizer & SFT** | `apps/core/native/tokenizer.py`, `sft.py` (`SCHEMA_V2`, `zyrquen.sft.v1`) | ใช้ BPE `v2` + atomic slots + `-100` masking | ขยาย entity regex ใน `sft.py` ให้จับ `UN_E*`/`OO_E*` เป็น single source of truth |
| **Trainer** | `apps/core/native/train.py` (`train_sft`, `TrainConfig`) | รัน SFT training, cosine LR, `CheckpointManager`, NaN guard | รองรับ optional `stage_id` / global step continuity metadata (non-breaking) |
| **Dataset & Manifest** | `apps/core/native/dataset.py` (`zyrquen.dataset-manifest.v1`) | ตรวจ schema, SHA-256, `content_sha256`, provenance | รองรับ 4-split declarations (`train`, `validation`, `unseen`, `ood`) พร้อม compatibility กับ `("train", "validation", "test")` |
| **Checkpoint & Versioning** | `checkpoint_recovery.py`, `native/checkpoint.py`, `native/registry.py` | Atomic SHA-256 checkpoints, immutable snapshots `ZYRQUEN-Native-X.Y.Z` | คง `registry.json` schema v1 เดิม, เพิ่ม optional V11 stage/split evidence keys |
| **Evaluation Engine** | `apps/core/native/evaluation/engine.py` (`EvaluationEngine`) | ตรวจ checkpoint + dataset + รัน `evaluate_native_model` จริง | รองรับ `splits=("validation", "unseen", "ood")` และ `report_schema="zyrquen.v11.evaluation_report.v1"` |
| **Workflow Engine** | `apps/core/workflow/` (`CentralWorkflowOrchestrator`, `groups.py`) | Trigger `data.ingestion_and_leakage_gate`, `training.native_controlled_run`, `evaluation.model_verification` | เพิ่ม dispatch สำหรับ `audit_leakage_v11` และ `zyrquen.v11.evaluation_report.v1` ใน `groups.py` |
| **Inference & Runtime** | `apps/core/model_loader.py`, `inference.py`, `streaming.py`, `runtime.py` | โหลด Active Registry version และบริการ Native Inference | ซิงก์ `bind_ephemeral_slots`/`restore_ephemeral_slots` ตาม artifact metadata `use_slots` |
| **Intelligence & Phases 16–20** | `phases/phase16.py`..`phase20.py`, `apps/core/intelligence/` | ใช้เป็น Verification, Memory Isolation & Maturity Checks | **ห้ามแก้ไขไฟล์ใน `phases/`**; เชื่อมผ่าน Runtime Adapters ใน `apps/core/` |

---

## 2. Interface Contracts Between V11 Tools & Core

1. **Tool Layer (`tools/*_v11.py` เมื่อเปิดเฟส):** ทำหน้าที่เพียง Thin CLI Controllers (เหมือน `gen_nagi_v10.py`, `audit_leakage_v10.py`, `train_nagi_v10.py`, `eval_nagi_v10.py`) โดยเรียกใช้ Core Engines (`CentralWorkflowOrchestrator`, `EvaluationEngine`, `ModelRegistry`) ห้ามเขียน Trainer/Approval/Registry ใหม่ใน `tools/`
2. **Dataset Dispatch Contract (`handle_data_verify_and_audit`):**
   - `val_unseen.jsonl` + `test_ood.jsonl` -> `audit_leakage_v9`
   - `manifest["dataset"] == "nagi_v10"` -> `audit_leakage_v10`
   - `manifest["dataset"] == "nagi_v11"` -> `audit_leakage_v11`
3. **Evaluation Gate Dispatch Contract (`handle_evaluation_gate`):**
   - ตรวจ `report["report_schema"]` แยกชัดเจน (`v9` vs `v10` vs `v11`), ห้ามตกหล่นเป็น default PASS
   - `v11` gate บังคับตรวจครบ 4 splits (อย่างน้อย `validation`, `unseen`, `ood` ใน evaluation + `train` diagnostic), ครบ 6 capabilities, non-empty `regression_comparison`, และ `inference_executed = True`

---

## 3. Mandatory Truthfulness Sections

### ASSUMPTIONS
- V10-C จะปิด Gap เล็กๆ ของ V10 (เช่น `train_nagi_v10.py` ส่ง `tokenizer_path` เข้า `wf_payload`) ก่อนเปิด V11 ทำให้ Pattern การเชื่อม `tools/` -> `groups.py` -> `native/` มีเสถียรภาพแล้ว
- การเพิ่ม V11 Branch ใน `groups.py` และ `EvaluationEngine` สามารถทำแบบ Additive โดยไม่กระทบ Test ของ V9/V10

### OPEN DECISIONS
- **OD-IC-01:** สำหรับ API `NativeInferenceEngine`, การเปิด `use_slots` ควรควบคุมผ่าน `checkpoint` / `registry` metadata (`use_slots: bool`) หรือ `InferenceContext` flag เพื่อไม่ให้กระทบ Raw Text Generation ปกติ
- **OD-IC-02:** รูปแบบการ Map `4` splits (`train`, `validation`, `unseen`, `ood`) เข้ากับ `ModelRegistry._verify_dataset` (`SPLITS = ("train", "validation", "test")`) — เลือกอัปเดต `_verify_dataset` ให้อ่าน `manifest["splits"]` หรือคง `test.jsonl` ไว้เป็น Verified Alias Archive ของ `unseen + ood`

### NOT VERIFIED
- ไม่มีโค้ด V11 ใดถูกเขียนหรือรัน Integration Test จริงในรอบนี้ (Blueprint Only ตามคำสั่ง)
- ผลกระทบต่อ Frontend UI (`apps/web/src/components/WorkflowConsole.tsx`) เมื่อแสดงผลรายงาน 4 Splits ของ V11 ยัง **NOT VERIFIED**
