# ZYRQUEN Ω∞ — V12 Security & Governance Specification

- **Document ID:** `V12-DOC-16`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Governance Anchor:** `apps/core/workflow/governance.py`, `apps/core/workflow/audit.py`, Phase 19
- **Mandate:** Zero Unapproved Paid Compute, Zero Auto-Promotion, Zero External Model Smuggling, Strict Audit Trail

---

## 1. Two-Tier Action Classification Across the 50K Lifecycle

เพื่อไม่ให้ระบบอัตโนมัติ (Workflow Engine) กลายเป็นระบบรันไร้การควบคุม:

| Tier | Permitted Actions | Approval Requirement | Audit Enforcement |
|---|---|---|---|
| **Tier-1 (Autonomous Safe)** | Health Checks, Disk/RAM/CPU Monitoring, Data Schema & Leakage Audit, Read-Only `EvaluationEngine` Scoring, Micro-Report Generation | Pre-authorized by Workflow Policy | Append-only `WorkflowAuditLogger` |
| **Tier-2 (Gated High-Risk)** | Starting Any Training Experiment (`EXP-001..100`), Stage Transition (`1->2..5->6`), Scaling Tier Escalation (`>5M`), Model Registry `promote`/`rollback`, Modifying Thresholds | **Single-Use HMAC-SHA256 Token** Bound to Exact Action Payload + Actor + Expiry | Immutable Audit Entry + Token Replay Rejection |
| **Tier-3 (Strictly Prohibited Without Out-of-Band Signoff)** | Paid Cloud GPU Provisioning, Deleting Historical Checkpoints (`v7..v11`), Altering `phases/phase11..20`, Creating `Phase 21`, `git push`/`merge`/`deploy` | **Hard Blocked in Workflow Engine** | Security Alert + Immediate Abort |

---

## 2. Anti-External-Model & Supply-Chain Integrity Controls

1. **Static AST & Import Gate:** รันตรวจ Scan Imports ทุกครั้งใน CI/Workflow เพื่อยืนยันว่าไม่มีการนำเข้า `openai`, `anthropic`, `google.generativeai`, `transformers` Pretrained Loaders, หรือ External Weight Download Hooks (`urllib`/`requests` ดึงไฟล์ `.bin`/`.safetensors`/`.gguf` จากอินเทอร์เน็ต)
2. **Dataset Provenance Audit:** ปฏิเสธ Dataset Manifest ใดๆ ที่ `generator` ไม่ใช่ Deterministic Verified Generator ของ ZYRQUEN หรือมีหลักฐานว่าใช้ External LLM สร้างเฉลย
3. **Path Traversal & Symlink Guard:** ทุก Checkpoint Path, Dataset Path, และ Registry Artifact Path ต้องผ่าน `realpath` containment check ภายใน Approved Workspace Artifact Root และห้าม Follow Symlink ออกนอก Sandbox
4. **Zero Hardcoded Secrets:** Token Signing Keys, DB Credentials, และ Auth Secrets ต้องอ่านจาก Environment (`process.env` / `os.environ`) เท่านั้น ห้ามลง Repo หรือ Logs

---

## 3. Multi-User & API Security Boundaries

- **Admin-Only Governance Endpoints:** Endpoints สำหรับออก Tier-2 Token, เริ่ม Training Run, และ Promote Registry Version ต้องผ่าน Auth + RBAC (`admin` role) + Rate Limiting (`apps/api/routers/workflows.py`, `training.py`, `admin.py`)
- **Inference Tenant Isolation:** การเรียก Inference ที่เชื่อม `MemoryStore` ใน Stage 5–6 ต้องส่ง `tenant_id` จาก Verified Auth Context ห้ามรับจาก Body แบบไม่ตรวจสิทธิ์

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- `WorkflowGovernance` HMAC-SHA256 Single-Use Token Mechanism ที่ปิดปรับปรุงใน V10-B พร้อมใช้งานเป็นแกนหลักให้ V12 ใช้ต่อโดยไม่สร้าง Auth/Governance ใหม่ซ้ำซ้อน

### OPEN DECISIONS
- **OD-V12-SEC-01:** นโยบาย Batch Approval vs Per-Experiment Token สำหรับ `100` Sequential Experiments (เช่น ออก Tier-2 Token ทีละ 1 Run เพื่อความปลอดภัยสูงสุด หรือ Bounded Stage Envelope Token ที่ยังบังคับ Evaluation Check ระหว่าง Run)

### NOT VERIFIED
- Penetration Test และ Symlink/Path Traversal Stress Test เฉพาะ Artifacts V12 ยัง **NOT VERIFIED / NOT RUN**
- Workflow Enforcement ต่อการรันจริงระดับ 100 Sequential Experiments ยัง **NOT RUN**
