# ZYRQUEN Ω∞ — V11 Security & Governance Specification

- **Document ID:** `V11-DOC-16`
- **Status:** `BLUEPRINT ONLY — LOCKED UNTIL V10 FINAL GATE PASS`
- **Governance Modules:**
  - `apps/core/workflow/governance.py` (`WorkflowGovernance`, `TIER2_GATED_ACTIONS`)
  - `apps/core/workflow/audit.py` (`WorkflowAuditLogger`, secret/token redaction)
  - `apps/api/routers/workflows.py` (REST Approval & Model Registry Lifecycle API)
  - `phases/phase19.py` (Tool Allowlist & Server-Signed Sandbox Policy)

---

## 1. Native-Only Security Policy (Zero External Intelligence Backdoors)

1. **Zero Pretrained External Weights:** ห้ามโหลด Weights จาก HuggingFace, OpenAI, Anthropic, Gemini หรือแหล่งภายนอกอื่นใดเข้าโมเดล ZYRQUEN V11
2. **Zero External AI API Inference:** ห้ามส่งข้อมูล Prompt/Reasoning ของผู้ใช้หรือ Evaluation ไปให้ API ภายนอกช่วยตอบและอ้างว่าเป็นความสามารถของ ZYRQUEN
3. **Truthful Evidence & Contract:** `apps/core/intelligence/contract.py::validate_result` ปฏิเสธการรายงาน `model_inference=True` ที่ไม่มี Native Model Evidence จริง

---

## 2. Two-Tier Permission & Single-Use HMAC-SHA256 Approval Policy

อ้างอิง `apps/core/workflow/governance.py`:
- **Tier-1 Auto (`tier1_auto`):** งานอ่านและตรวจสอบความปลอดภัยเท่านั้น (`system_ops.health_check`, `data.ingestion_and_leakage_gate`, `evaluation.model_verification`, `security.integrity_audit`, `knowledge.memory_ingestion`, `improvement.offline_proposal`) — ห้ามกลายพันธุ์ Weights หรือ Promote
- **Tier-2 Mandatory Human Approval (`tier2_approval`):**

| Action Key | Governance Rule |
|---|---|
| `training.execute` | ต้องมี Admin-approved HMAC-SHA256 token ตรงกับ `approval_id\|run_id\|step_key\|action_type\|scope\|expires_at` และถูก Consume แบบ single-use ก่อนรัน `handle_training_execute` |
| `compute.paid_gpu` | **FORBIDDEN** ใน V11 Tier-0; ปลดล็อกได้เฉพาะเมื่อมี Tier-2 token แยกและเปิด `has_paid_gpu_approval` |
| `model.stage` *(Required V10-B Closure)* | **Prerequisite ก่อนเปิด V11:** ต้องตรวจและ Consume Token จริงผ่าน `verify_and_consume_by_id` ใน `apps/api/routers/workflows.py` |
| `model.promote` | ต้องผ่าน `EvaluationEngine` + `enforce_evaluation_gate=True` + Consume HMAC Token จริงผ่าน API และ Workflow Engine |
| `model.rollback` | ต้องผ่าน `ModelRegistry.verify(target)` + Consume HMAC Token จริง |
| `architecture.modify`, `data.delete`, `git.push`, `deploy.production` | Tier-2 Gate + ห้าม Autonomous Execution โดย Agent |

> **Critical Security Prerequisite (V10-B Blocker):** ปัจจุบันใน `apps/api/routers/workflows.py` (lines 253–334), endpoint `/v1/models/registry/{version}/stage`, `/promote`, และ `/rollback` ตรวจเพียง `if not body.approval_id` โดยยังไม่เรียก `engine.governance.verify_and_consume_by_id(...)` และยังไม่เขียน `engine.audit.record(...)` — **ข้อบกพร่องนี้ต้องถูกปิดใน V10-B ก่อนอนุญาตให้เปิด V11**

---

## 3. Filesystem, Symlink, Deserialization & PII Controls

1. **No Symlinks:** Dataset, Manifest, Tokenizer, Checkpoints และ Evaluation Reports ที่เป็น Symlink ต้องถูกปฏิเสธ (`is_symlink()` -> `BLOCKED` / `RegistryError`)
2. **Path Traversal Containment:** ทุก File Resolution ต้อง `resolve().is_relative_to(allowed_root.resolve())`
3. **Safe Checkpoint Loading:** บังคับ `weights_only=True` (`_safe_torch_load`) พร้อมตรวจ SHA-256 ก่อนโหลดเสมอ
4. **Secret Redaction in Audit Logs:** `WorkflowAuditLogger` + `redact_dict` ล้าง secret/token ออกจาก Audit Log เสมอ และห้ามส่ง `signature_hmac` ออกทาง `GET /v1/workflows/approvals`
5. **Production Approval Secret Enforcement:** การใช้งานจริงนอก Test ต้องตั้ง `ZYRQUEN_APPROVAL_SECRET` ใน Environment (ไม่พึ่งพา ephemeral fallback)

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- ช่องโหว่ใน `apps/api/routers/workflows.py` (`stage`, `promote`, `rollback`) จะถูกแก้ไขและทดสอบด้วย Integration Test ใน V10-B ก่อนเริ่ม V11
- ระบบ Auth (`get_current_user` / `require_admin`) และ Rate Limiting ใน `apps/api/` จะคงไว้โดยไม่มีการแก้ไข Schema โดยไม่ได้รับอนุมัติ

### OPEN DECISIONS
- **OD-SG-01:** สำหรับการฝึก 10,000 Steps แบบ Segmented (20 segments × 500 steps), Admin ต้องลงนาม Tier-2 Token ราย Stage (`6` tokens, scope ผูก `stage_1..stage_6`) หรือราย Segment (`20` tokens) — ต้องบาลานซ์ความปลอดภัยกับความสามารถในการรันจริงโดยไม่ลดระดับ Single-Use HMAC Protection
- **OD-SG-02:** กำหนด TTL ที่เหมาะสมของ `ensure_pending_approval(..., ttl_minutes=120)` หากการอนุมัติ Stage ใหญ่ต้องรอนานกว่า 2 ชั่วโมง

### NOT VERIFIED
- Penetration/bypass test ของ API `/stage`, `/promote`, `/rollback` หลังแก้ V10-B ยัง **NOT VERIFIED** (ยังไม่ได้แก้ source code ในรอบ Blueprint นี้)
- พฤติกรรมของ `ZYRQUEN_APPROVAL_SECRET` rotation กับ active pending approvals ใน `WorkflowStore` ยัง **NOT VERIFIED**
