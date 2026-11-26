# ZYRQUEN — Phase 11–20 Master Engineering Roadmap

* **สถานะทั้งหมด:** **`PROPOSED / NOT APPROVED / PLANNING ONLY`**
* **เป้าหมายเชิงกลยุทธ์:** พัฒนาระบบ **ZYRQUEN Native Intelligence / Native Model** ของตนเองอย่างเป็นลำดับขั้น บนรากฐานที่มีหลักฐานจริง ตรวจสอบย้อนกลับได้ และคุ้มค่าทรัพยากร (ไม่ใช่ Chatbot Wrapper หรือการเปลี่ยนชื่อโมเดลภายนอก)
* **Repository:** `maewhyxng2-prog/zyrquen-platform` (`main`)
* **วันที่จัดทำ:** 2026-11-21
* **ข้อบังคับด้านขอบเขต:**
  * เอกสารนี้เป็นการวางแผนเชิงวิศวกรรมเท่านั้น (**ไม่มีการแก้ไข Source Code, Database Schema, API Contract, หรือ Dependencies**)
  * **ห้ามเปิดใช้งาน Phase 11–20**, **ห้ามสร้าง Phase 21**, **ห้ามเริ่ม Training**, **ห้ามดาวน์โหลด Dataset หรือ Model Weights**, และ **ห้าม Provision GPU หรือ Cloud Resources** จนกว่า Gate ก่อนหน้าจะปิด (`CLOSED`) และเจ้าของโครงการอนุมัติเป็นรายเฟส

---

## 0. Verified Historical Baseline (Phase 1–10 Evidence Summary)

เพื่อคงความซื่อสัตย์ทางวิศวกรรมและไม่เขียนประวัติย้อนหลังให้ดูเหมือนผ่านแล้ว สถานะจริงของ Phase 1–10 ณ วันที่จัดทำเอกสารมีดังนี้:

| ขอบเขตเดิม | สถานะตามหลักฐานจริง | หลักฐานที่ตรวจสอบได้ / ช่องว่างที่ยังเปิดอยู่ |
| :--- | :--- | :--- |
| **Phase 1–3 (Core Architecture, Tokenizer, Dataset, Evaluation Package)** | Implemented in Source / Partial Unit Verification | มี `apps/core/native/` (`config.py`, `model.py`, `tokenizer.py`, `dataset.py`, `train.py`, `checkpoint.py`, `registry.py`, `evaluation/`) และ `apps/core/runtime.py`; **ยังไม่มี trained weights ของ ZYRQUEN**, `test_model.py` / `test_train_torch.py` / `test_evaluation.py` (ส่วน `torch`) ยัง `BLOCKED` ในสภาพแวดล้อมที่ไม่มี PyTorch |
| **Phase 4–8 (Training Infra, API, Auth, Multi-user, Web Platform, Production Ops Prep)** | Implemented in Source / Partial Verification | มี `apps/api/` (9 routers, Alembic `20261120_01`–`07`, `database_safety.py`, `training_jobs.py`), `apps/core/training_infrastructure/`, `apps/web/` (Next.js standalone + same-origin proxy), และ Runbooks (`docs/operations/`); **ยังไม่ได้ Deploy Production**, ยังไม่มี Managed PG / Cloud Volume / Cloud GPU Adapter, และ `apps/core/evaluation/engine.py` เดิมยังมีเมธอด mock placeholder |
| **Phase 9.1–9.10 (`apps/core/intelligence/`)** | **Completed as Software Contracts Only** | ผ่านชุดทดสอบ `tests/` (`144` tests; `128/128` pure-unittest ผ่านใน AI Studio Sandbox); เป็นชั้นสัญญาและ policy validation ในหน่วยความจำ (`model_inference=False`, `execution_performed=False`) **ไม่ใช่ Native Model reasoning/planning/tool-use จริง** (อ้างอิง `docs/PHASE_9_STATUS.md`) |
| **Phase 10.8 / 10.9.9 (Final Integration Verification)** | **`NOT CLOSED`** (`BLOCKED`) | จัดเตรียมชุด Handoff Python 11 ไฟล์ใน `handoff/phase-10.9.9/` แล้ว แต่ **ยังไม่ได้รับการ Sync/Commit เข้า `main`** และ CI Run ล่าสุดที่เห็นผล (`44883421473`) ยังมี failure ใน `test` (2/88) และ `postgres-integration` (3/3); Docker build จาก Repo Root และ Playwright E2E ยังไม่ผ่านการยืนยันบน SHA หลังแก้ |

> **Hard Gate Prerequisite:** ทุก Phase ในเอกสารนี้ (Phase 11–20) จะไม่สามารถเปลี่ยนสถานะจาก `PROPOSED / NOT APPROVED` เป็น `APPROVED` ได้ จนกว่า **Phase 10.9.9 จะปิด (`CLOSED`) ด้วยหลักฐาน CI ครบ 4 jobs (`web`, `docker`, `test`, `postgres-integration`) บน `main` SHA เดียวกัน**

---

## 1. Phase-by-Phase Engineering Roadmap (Phase 11–20)

---

### Phase 11 — Workspace Intelligence
* **สถานะ:** `PROPOSED / NOT APPROVED / PLANNING ONLY`
* **ขอบเขตหลัก:** Follow-up Suggestions, Conversation Context Awareness, Workspace Interaction Improvements

1. **Objective และ Scope**
   * ยกระดับประสบการณ์โต้ตอบใน `WorkspacePage` โดยเพิ่มคำถามแนะนำต่อยอดจากข้อความ Assistant ล่าสุด (3–4 ข้อ), จัดการบริบทของบทสนทนาที่ส่งเข้า Inference อย่างมีโครงสร้าง และปรับปรุง UX/Accessibility ของการสนทนาทั้งบน Desktop และ Mobile โดยยังคงยึด Native AI Runtime ภายใน ZYRQUEN
2. **Technical Architecture**
   * **Frontend State Layer:** แยก Follow-up Suggestion State (`idle | loading | empty | error | ready`) ออกจาก Streaming Message State; Refactor `sendPrompt` ให้รับ `overridePrompt?: string` พร้อม Request Cancellation (`AbortController`) เมื่อผู้ใช้สลับหรือลบ Conversation
   * **Context Window Assembly:** รวบรวมประวัติข้อความจาก `ConversationMessage` ตามลำดับ `seq` ภายใต้ Token Budget ที่วัดด้วย `runtime.loader.tokenizer` (`max_seq_len` guard)
   * **Native Suggestion Channel:** ออกแบบให้ทำงานผ่าน Native Inference / Context-aware Endpoint ภายในระบบแบบ Fail-soft (ถ้าโมเดลยังไม่พร้อมหรือ error ต้องไม่รบกวนการสนทนาหลัก)
3. **Dependencies และ Prerequisites**
   * Phase 10.9.9 `CLOSED` (CI `web`, `docker`, `test`, `postgres-integration` ผ่านครบ)
   * ผ่านการอนุมัติ Scope Phase 11 (อ้างอิงรายละเอียด Requirement ใน `docs/engineering/ZYRQUEN_PHASE_READINESS.md` หัวข้อ 2.2)
4. **ไฟล์และโมดูลที่คาดว่าจะเกี่ยวข้อง**
   * *Existing:* `apps/web/src/app/workspace/page.tsx`, `apps/web/src/lib/native-chat.ts`, `apps/web/src/lib/conversation-api.ts`, `apps/web/src/lib/backend-routes.ts`, `apps/api/routers/inference.py`, `apps/api/routers/conversations.py`, `apps/core/streaming.py`
   * *Future Proposed (ยังไม่สร้าง):* helper/hook สำหรับ Follow-up state และ Context window budgeting ใน `apps/web/src/lib/` และ `apps/core/conversation.py`
5. **Security และ Governance Requirements**
   * ส่งผ่าน Same-origin Next.js BFF Allowlist (`apps/web/src/lib/backend-routes.ts`) พร้อมตรวจ Ownership (`_owned_conversation`) และ `X-Zyrquen-Expected-User-ID`
   * ห้ามเรียก External AI Provider API ภายนอก (`0` external wrappers)
   * บังคับ Quota Accounting และ Request Fingerprint สำหรับทุกคำขอ Inference ที่เกิดขึ้นจริง
6. **Testing Strategy**
   * **Unit Tests (Vitest & Pytest):** ทดสอบการเลือกข้อความ Assistant ล่าสุด, Guard State (`incomplete`, `streaming`, `sending`, `!inference_available`), Deduplication/จำกัด 3–4 ข้อ และ Context Truncation ให้อยู่ใน `max_seq_len`
   * **UI Tests:** ทดสอบ `Loading / Empty / Error / Success`, Auto-send, การล้างคำถามแนะนำทันทีเมื่อส่งข้อความใหม่, และ Layout บน Desktop + Mobile Viewport
   * **E2E Check:** ปรับ/รัน `apps/web/e2e/platform.spec.ts` ให้ตรงกับ UI ภาษาไทย
7. **Acceptance Criteria**
   * แสดงคำถามแนะนำ 3–4 ข้อเฉพาะใต้ข้อความ Assistant ล่าสุดที่สมบูรณ์ (`!incomplete`, `!streaming`)
   * คลิกคำถามแนะนำแล้ว Auto-send ได้ทันทีและล้างชุดเดิมออกทันควัน; Error ของ Suggestion Fail-soft ไม่ทำให้แชทหลักล่ม
   * มี Unit Tests และ UI Tests ผ่านครบ 100% บน CI โดยไม่เพิ่ม External AI dependency
8. **Exit Gate Checklist**
   * [ ] Phase 10.9.9 `CLOSED`
   * [ ] Unit + UI + E2E tests ผ่านบน CI
   * [ ] Security & Proxy allowlist review ผ่าน (ไม่มี direct browser-to-API bypass)
   * [ ] ยืนยันการเคารพ `_semaphore` / concurrency budget บน Backend
9. **Failure and Rollback Strategy**
   * ใช้ Feature Flag ฝั่ง Client/Config เพื่อปิด Follow-up Suggestions และ Context Enrichment ทันทีโดยไม่กระทบ Streaming Chat หรือ Conversation Persistence เดิม; Revert commit ของ Phase 11 ได้โดยไม่มี Migration เปลี่ยน Schema
10. **Resource and Cost Estimate**
    * **Local/CI:** CPU-only (Node 22 Vitest + FastAPI SQLite `unit_test`); ค่าใช้จ่ายเพิ่ม = **$0**
    * **Cloud/Runtime:** ใช้ Token Budget เพิ่มเล็กน้อยเฉพาะเมื่อ Follow-up Suggestion ถูกเปิดใช้กับ Native Model จริงในอนาคต (ต้องควบคุมด้วย Rate Limit / Token Cap)
11. **Risks and Mitigations**
    * *ความเสี่ยง:* Latency/Queue Contention จาก `_semaphore = Semaphore(1)` ใน Native Engine -> *การลดความเสี่ยง:* Non-blocking / cancellable request และ Fallback เป็น Lightweight Context Extraction เมื่อ Inference Queue ไม่ว่าง
    * *ความเสี่ยง:* Race condition เมื่อสลับแชทกลางคัน -> *การลดความเสี่ยง:* ผูก Suggestion state กับ `conversationId` + `messageId` และ AbortController
12. **Dependencies กับ Phase ก่อนหน้าและถัดไป**
    * *พึ่งพาก่อนหน้า:* Phase 10.9.9
    * *ปูทางสู่ถัดไป:* ป้อนสัญญาณ Context และ Interaction Flow สู่ Phase 12 (Native Intelligence Foundation) และ Phase 18 (Adaptive Feedback Loop)

---

### Phase 12 — Native Intelligence Foundation
* **สถานะ:** `PROPOSED / NOT APPROVED / PLANNING ONLY`
* **ขอบเขตหลัก:** Native Intelligence Architecture, Core Intelligence Interfaces, Capability Management

1. **Objective และ Scope**
   * เชื่อมช่องว่างระหว่างชั้นสัญญา Phase 9 (`apps/core/intelligence/`) กับ Native Runtime (`apps/core/runtime.py`, `apps/core/native/`) เพื่อให้ระบบมีความสามารถในการจัดการ Capability Registry, Provenance ของผลลัพธ์ (`model_inference` vs `rule_based_scaffold`), และการควบคุมสิทธิ์ระดับ Capability อย่างเป็นทางการ
2. **Technical Architecture**
   * **Unified Intelligence Facade:** ยกระดับ `IntelligenceRuntime` (`apps/core/intelligence/integration.py`) ให้แยกระดับความสามารถจริง (`capability_tier`: `contract_only` | `hybrid_verified` | `native_model_backed`) พร้อมหลักฐาน Model Version จาก `ModelRegistry`
   * **Core Interfaces:** มาตรฐาน Input/OutputEnvelope ที่บังคับ Cryptographic Run/Model Provenance แทนค่า string หลวมๆ ใน `native_model_evidence` (ปิดช่องโหว่ที่พบใน Phase 9)
   * **Capability Management:** Registry กลางสำหรับเปิด/ปิด Capability ต่อ Environment และ Role โดย Fail-closed เป็น default (`disabled` จนกว่าจะผ่าน Evaluation Gate)
3. **Dependencies และ Prerequisites**
   * Phase 10.9.9 `CLOSED` และ Phase 11 (หรือ Interface Contract ที่ตกลงร่วมกัน) เสร็จสิ้น
   * ยืนยันสัญญา `ModelRegistry` และ `NativeRuntime` ใน `apps/core/`
4. **ไฟล์และโมดูลที่คาดว่าจะเกี่ยวข้อง**
   * *Existing:* `apps/core/intelligence/__init__.py`, `apps/core/intelligence/integration.py`, `apps/core/intelligence/contract.py`, `apps/core/intelligence/capability_evaluation.py`, `apps/core/runtime.py`, `apps/core/native/registry.py`, `apps/api/main.py`
   * *Future Proposed:* Capability Manifest & Verified Provenance Interface ใน `apps/core/intelligence/`
5. **Security และ Governance Requirements**
   * ปิดช่องโหว่ `caller_reported` / self-attested evidence: ระบบต้องตรวจสอบ `model_version` และ `execution_digest` จาก Runtime จริงเท่านั้น
   * Capability ใหม่ทุกตัวเริ่มต้นเป็น `disabled` (Default-Deny)
6. **Testing Strategy**
   * ขยาย Contract Suite (`tests/test_intelligence_integration.py`, `tests/test_capability_evaluation.py`) เพื่อทดสอบการปฏิเสธ Fake Evidence, Provenance Mismatch, และ Capability Flag Isolation
7. **Acceptance Criteria**
   * `IntelligenceRuntime` สามารถรายงาน Capability Matrix ที่แยกแยะ `contract_only` ออกจาก `native_model_backed` ได้อย่างถูกต้อง
   * ไม่มีเส้นทางใดอนุญาตให้ `model_inference=True` โดยปราศจาก Runtime Verification Token/Provenance
8. **Exit Gate Checklist**
   * [ ] Phase 9 regression suite (`144` tests+) และ Provenance tests ผ่าน 100%
   * [ ] Security audit ยืนยัน Fail-closed default สำหรับทุก Capability
   * [ ] เอกสาร Architecture Synced ระหว่าง `apps/core/intelligence/` และ `apps/core/runtime.py`
9. **Failure and Rollback Strategy**
   * หาก Interface ใหม่ขัดข้อง ให้ Fail-closed กลับสู่ `contract_only` mode (`model_inference=False`) และปิด Capability Flag ทั้งหมดโดยไม่กระทบ `/v1/native-ai/infer` เดิม
10. **Resource and Cost Estimate**
    * **Local/CI:** CPU-only (Python unittest/pytest); ค่าใช้จ่ายเพิ่ม = **$0**
    * **Cloud:** ยังไม่ใช้ GPU หรือ Cloud Storage เพิ่มเติม
11. **Risks and Mitigations**
    * *ความเสี่ยง:* ความสับสนระหว่าง Rule-based Scaffold กับ Model Capability จริง -> *การลดความเสี่ยง:* บังคับ Type/Schema แยก `engine_type` และตรวจสอบ Provenance ระดับ Runtime
12. **Dependencies กับ Phase ก่อนหน้าและถัดไป**
    * *พึ่งพาก่อนหน้า:* Phase 9 (ฐานสัญญา), Phase 10.9.9, Phase 11
    * *ปูทางสู่ถัดไป:* เป็นแกน Interface ให้ Phase 14 (Evaluation), Phase 16 (Reasoning & Planning), และ Phase 19 (Safety Governance)

---

### Phase 13 — Knowledge & Data Pipeline
* **สถานะ:** `PROPOSED / NOT APPROVED / PLANNING ONLY`
* **ขอบเขตหลัก:** Data Ingestion Architecture, Dataset Governance, Data Validation and Quality

1. **Objective และ Scope**
   * สร้างสถาปัตยกรรมท่อเตรียมข้อมูลอย่างเป็นระบบตั้งแต่แหล่งข้อมูลต้นทางจนถึง Dataset Artifact ที่ตรวจสอบ Provenance และ License ได้ 100% (`zyrquen.dataset-manifest.v1`) เพื่อเตรียมความพร้อมสำหรับการฝึกและประเมิน Native Model ของ ZYRQUEN เอง
2. **Technical Architecture**
   * **Ingestion Pipeline:** Staging -> PII/Secret Scrubbing -> License/Source Attribution Check -> Deduplication (Exact & Near-duplicate) -> Deterministic Split (`train` / `val` / `test`) -> `zyrquen.dataset-manifest.v1` + SHA-256 Sealing
   * **Dataset Governance:** Catalog เก็บ Source Metadata, License Allowlist, Consent/Usage Restriction, และ Lineage Hash
   * **Quality Scoring Engine:** ตรวจ Language Distribution, Token Length Distribution (สอดคล้อง `ZyrquenTokenizer`), Corruption/Encoding Check, และ Train/Eval Contamination Detection
3. **Dependencies และ Prerequisites**
   * Phase 10.9.9 `CLOSED` และ Phase 12 Interface Baseline
   * การอนุมัติ Dataset License Policy จากเจ้าของโครงการ (ห้ามดาวน์โหลด Dataset ใดๆ ก่อนได้รับอนุมัติ)
4. **ไฟล์และโมดูลที่คาดว่าจะเกี่ยวข้อง**
   * *Existing:* `apps/core/native/dataset.py`, `apps/core/native/test_dataset.py`, `apps/core/native/tokenizer.py`, `apps/core/native/test_tokenizer.py`
   * *Future Proposed:* Data Ingestion / PII Filter / Contamination Check / Manifest Validator modules ภายใต้ `apps/core/native/` หรือ `apps/core/data/`
5. **Security และ Governance Requirements**
   * ห้ามนำข้อมูลที่มี Secrets, PII ที่ไม่ผ่าน Scrub, หรือ License ต้องห้ามเข้า Training Corpus
   * Dataset ทุกชุดต้องมี Deterministic SHA-256 Manifest และ Contamination Guard แยกชุด Evaluation/Benchmark ออกจาก Train split โดยเด็ดขาด
6. **Testing Strategy**
   * ใช้ Synthetic Micro-fixtures ในเครื่อง (ไม่ดาวน์โหลด Dataset จริงในขั้นพัฒนา Pipeline) เพื่อทดสอบ Manifest Integrity, Tamper Detection, Contamination Blocking, และ Deterministic Re-split
7. **Acceptance Criteria**
   * Pipeline ปฏิเสธ Dataset ที่ขาด License Metadata, มี Contamination กับ Test/Benchmark set, หรือ SHA-256 ไม่ตรง Manifest แบบ Fail-closed
   * ผลลัพธ์จาก Input เดียวกันและ Seed เดียวกันให้ Byte-identical Manifest และ Split เสมอ
8. **Exit Gate Checklist**
   * [ ] Synthetic pipeline tests ผ่าน 100%
   * [ ] Data License & PII Compliance Checklist ได้รับการลงนามอนุมัติจาก Owner
   * [ ] ยืนยันการแยก Storage ของ `train` และ `eval` splits อย่างชัดเจน
9. **Failure and Rollback Strategy**
   * กักกัน (Quarantine) Dataset Version ที่ตรวจพบความผิดพลาด; ห้ามลบ Lineage เก่าแบบทำลายหลักฐาน แต่ปรับสถานะเป็น `revoked` เพื่อกันไม่ให้ Training หรือ Evaluation นำไปใช้ต่อ
10. **Resource and Cost Estimate**
    * **Local/CI:** CPU + Local disk ด้วย Synthetic sample ขนาดเล็ก; **$0**
    * **Cloud/Future Real Ingestion (เมื่อได้รับอนุมัติแยก):** Object Storage + Batch CPU Worker (~$10–$50/เดือน ขึ้นกับขนาด Corpus) — *ห้ามใช้จ่ายก่อนอนุมัติ*
11. **Risks and Mitigations**
    * *ความเสี่ยง:* Data Poisoning / Train-Test Leakage -> *การลดความเสี่ยง:* Strict SHA-256 sealing, MinHash/n-gram overlap gate, และ Read-only Golden Eval isolation
    * *ความเสี่ยง:* ความละเมิด License หรือข้อมูลส่วนบุคคล -> *การลดความเสี่ยง:* Mandatory License Allowlist + Automated PII/Secret scanner ก่อนสร้าง Manifest
12. **Dependencies กับ Phase ก่อนหน้าและถัดไป**
    * *พึ่งพาก่อนหน้า:* Phase 10.9.9, Phase 12 (Governance contracts) — *สามารถออกแบบ Pipeline ขนานกับ Phase 11–12 ได้ในระดับซอฟต์แวร์*
    * *ปูทางสู่ถัดไป:* ป้อน Verified Dataset Manifest สู่ Phase 14 (Evaluation) และ Phase 15 (Native Model Training)

---

### Phase 14 — Evaluation & Capability Measurement
* **สถานะ:** `PROPOSED / NOT APPROVED / PLANNING ONLY`
* **ขอบเขตหลัก:** Evaluation Framework, Benchmark and Regression Testing, Reliability Measurement

1. **Objective และ Scope**
   * สร้างระบบประเมินผลที่ทำซ้ำได้จริง (Reproducible, Zero-Mock) เพื่อวัดทั้งคุณภาพระดับภาษา (Loss, Perplexity) และความสามารถเชิงฟังก์ชันของ ZYRQUEN โดยเชื่อมต่อ `apps/core/native/evaluation/engine.py`, `apps/api/evaluation_service.py`, และ `apps/core/intelligence/capability_evaluation.py` เข้าด้วยกันพร้อม RBAC และ Database Persistence ที่สมบูรณ์
2. **Technical Architecture**
   * **Unified Evaluation Engine:** เชื่อม `EvaluationEngine` กับ `NativeModelLoader` จริงเพื่อคำนวณ Metrics จาก Checkpoint + Sealed Dataset; ถอด/Deprecate Legacy Mock ใน `apps/core/evaluation/engine.py` (`15.5`, `0.85`)
   * **Persistence Sync:** สร้าง Alembic Migration (`20261120_08+`) ให้ `EvaluationMetric` (`apps/api/evaluation_models.py`) ตรงกับฐานข้อมูลจริงและใช้ `DateTime(timezone=True)`
   * **Regression & Reliability Suite:** วัด Deterministic Score, Latency (p50/p95), Memory Footprint, Calibration/Refusal Rate และเทียบ Delta กับ Baseline Model Version ก่อนหน้า
3. **Dependencies และ Prerequisites**
   * Phase 10.9.9 `CLOSED`, Phase 12 (Provenance Interface), Phase 13 (Sealed Evaluation Dataset Specification)
4. **ไฟล์และโมดูลที่คาดว่าจะเกี่ยวข้อง**
   * *Existing:* `apps/core/native/evaluation/engine.py`, `apps/core/native/evaluation/metrics.py`, `apps/core/native/test_evaluation.py`, `apps/core/evaluation/engine.py`, `apps/api/routers/evaluation.py`, `apps/api/evaluation_service.py`, `apps/api/evaluation_models.py`, `apps/api/evaluation_schemas.py`, `apps/api/test_evaluation.py`
   * *Future Proposed:* Alembic migration ใหม่สำหรับ `evaluation_metrics` และ Benchmark Runner ภายใต้ `apps/core/native/evaluation/`
5. **Security และ Governance Requirements**
   * ยกระดับสิทธิ์ `POST /v1/evaluation/runs` จาก `get_current_user` เป็น `Admin/Evaluator RBAC` + Quota/Budget Guard
   * ห้ามใช้ Hardcoded/Mock scores ทุกกรณี; หากขาด Artifact/Checksum/Dataset ให้คืน `503` / `422` แบบ Fail-closed
   * ห้าม Promote โมเดลโดยไม่ผ่าน Evaluation Gate
6. **Testing Strategy**
   * ทดสอบ Reproducibility (Same checkpoint + Same dataset + Fixed seed -> Exact same metrics)
   * ทดสอบ RBAC isolation (ผู้ใช้ทั่วไปสั่ง run ไม่ได้), Tampered dataset/checkpoint rejection (`422`), และ Legacy mock removal audit
7. **Acceptance Criteria**
   * `POST /v1/evaluation/runs` และ `EvaluationService` บันทึก `EvaluationRun` + `EvaluationMetric` ลง PostgreSQL จริงได้ครบถ้วน
   * ตรวจไม่พบ Mock/Hardcoded metrics ในเส้นทาง Evaluation หลัก และ Evaluation Gate บล็อกโมเดลที่คะแนนต่ำกว่าเกณฑ์
8. **Exit Gate Checklist**
   * [ ] Alembic migration cycle (upgrade/downgrade) ผ่านบน Test PostgreSQL
   * [ ] RBAC & Quota tests สำหรับ Evaluation API ผ่าน 100%
   * [ ] Legacy mock engine ถูกถอดหรือแยกออกจากการใช้งานจริงโดยสิ้นเชิง
9. **Failure and Rollback Strategy**
   * หาก Evaluation Pipeline ผิดพลาด ให้ Lock การ Promote ใน `ModelRegistry` (`active` pointer คงที่) และ Downgrade Migration เฉพาะของ Evaluation Metrics บน Test/Staging ก่อน Rollout
10. **Resource and Cost Estimate**
    * **Local/CI:** CPU tiny model fixture + SQLite/PG test container; **$0**
    * **Cloud/Runtime:** Evaluation Batch Job ใช้ Compute ตามขนาดโมเดล (~$5–$30 ต่อรอบ Sandbox evaluation เมื่ออนุมัติรันจริง)
11. **Risks and Mitigations**
    * *ความเสี่ยง:* Goodhart's Law / Benchmark overfitting -> *การลดความเสี่ยง:* แยก Held-out Regression Set ที่หมุนเวียนและไม่เปิดเข้า Training Corpus
    * *ความเสี่ยง:* Migration drift ระหว่าง ORM กับ DB -> *การลดความเสี่ยง:* บังคับ Model-vs-Schema inspection test ใน `postgres-integration`
12. **Dependencies กับ Phase ก่อนหน้าและถัดไป**
    * *พึ่งพาก่อนหน้า:* Phase 12, Phase 13
    * *ปูทางสู่ถัดไป:* เป็น Quality Gate บังคับให้ Phase 15 (Native Model Readiness), Phase 16, 17, 18, 19 และ Phase 20

---

### Phase 15 — Native Model Readiness
* **สถานะ:** `PROPOSED / NOT APPROVED / PLANNING ONLY`
* **ขอบเขตหลัก:** Model Architecture Readiness, Training-to-Inference Design, Model Versioning and Lifecycle

1. **Objective และ Scope**
   * ทำให้สถาปัตยกรรม `ZyrquenModel` และวงจร Training-to-Inference พร้อมใช้งานจริงอย่างมีประสิทธิภาพ ปลอดภัย และตรวจสอบย้อนกลับได้ครบวงจรตั้งแต่ `reserve()` -> Training -> Checkpoint Recovery -> Evaluation Gate -> Explicit `promote()` -> Multi-worker Serving พร้อม KV-Cache
2. **Technical Architecture**
   * **Model & Inference Optimization:** เพิ่ม KV-Cache support ใน `ZyrquenModel` (`apps/core/native/model.py`), แยก Inference Worker Pool ออกจาก Single-concurrency `_semaphore = Semaphore(1)` และ `native_generation_lock`, และรองรับ Batch/Queue Timeout Policy
   * **Distributed & Durable Training Orchestration:** ย้าย Job Dispatcher จาก Single-process `ThreadPoolExecutor(max_workers=1)` (`apps/api/training_jobs.py`) ไปสู่ Durable Worker Queue; เชื่อม `DistConfig` (`apps/core/training_infrastructure/distributed/trainer.py`) เข้ากับ `apps/core/native/train.py`; เก็บกวาดไฟล์ซ้ำ (`apps/core/training/apps/core/training/cost_limits.py`)
   * **Version Lifecycle & Registry Lock:** ยกระดับ `ModelRegistry` จาก `fcntl.flock` เป็น Shared DB/Coordinator Lock สำหรับ Multi-node; ยืนยัน Atomic Version Reservation (`reserve_next_native_version`), Lineage Integrity, Zero Auto-Promotion, และ One-command Rollback
3. **Dependencies และ Prerequisites**
   * Phase 10.9.9 `CLOSED`, Phase 13 (Verified Dataset Pipeline), Phase 14 (Evaluation Gate)
   * การอนุมัติงบประมาณ Hardware/GPU และ Max Budget Cap แยกต่างหากก่อนการรัน Sandbox Training จริง
4. **ไฟล์และโมดูลที่คาดว่าจะเกี่ยวข้อง**
   * *Existing:* `apps/core/native/config.py`, `apps/core/native/model.py`, `apps/core/native/train.py`, `apps/core/native/checkpoint.py`, `apps/core/native/registry.py`, `apps/core/model_loader.py`, `apps/core/inference.py`, `apps/core/streaming.py`, `apps/core/training/orchestrator.py`, `apps/core/training_infrastructure/**`, `apps/api/training_jobs.py`, `apps/api/routers/training.py`
   * *Future Proposed:* Durable Training Worker adapter, KV-Cache engine module, Shared Registry Lock coordinator
5. **Security และ Governance Requirements**
   * **No Auto-Promotion:** Training เสร็จสิ้นห้ามเปลี่ยน `active` pointer อัตโนมัติ ต้องผ่าน Phase 14 Evaluation Gate และ Explicit Admin Promote เท่านั้น
   * **Artifact Safety:** บังคับ `weights_only=True`, `strict=True`, `cfg.vocab_size == tokenizer.vocab_size`, และ SHA-256 verification ทุกจุด
   * **Cost Guardrail:** บังคับ `ZYRQUEN_TRAINING_MAX_BUDGET_USD` และ `MAX_RUNTIME_SECONDS` แบบ Hard-stop ก่อน Spawn Job
6. **Testing Strategy**
   * **Round-trip Verification (Tiny Synthetic CPU Model ก่อน):** Reserve -> Train -> Interrupt & Resume Checkpoint -> Verify Registry -> Evaluate -> Explicit Promote -> Serve Streaming -> Rollback to N-1
   * **Concurrency & Scale Tests:** Multi-worker Reservation Contention test, Concurrent Streaming Throughput & Memory Leak test
7. **Acceptance Criteria**
   * Training-to-Inference Round-trip ทำงานครบวงจรโดยไม่มี Version Collision, ไม่มี Auto-Promotion, และ Resume จาก Checkpoint ได้โดยไม่เสีย Lineage
   * KV-Cache ลด Latency ต่อ Token ได้อย่างวัดผลได้ภายใต้ Benchmark ที่กำหนด และ `/readyz` คืน `503` ทันทีหาก Active Artifact เสียหาย
8. **Exit Gate Checklist**
   * [ ] Tiny Synthetic Round-trip & Rollback Drill ผ่าน 100%
   * [ ] Multi-worker Registry Lock Test ผ่านโดยไม่มี Version Collision
   * [ ] Container Packaging (`apps/api/Dockerfile` / Inference image) รองรับ `torch` Runtime อย่างชัดเจนและไม่บวมเกินจำเป็น
   * [ ] Owner Approval ก่อนรัน GPU Training จริงทุกครั้ง
9. **Failure and Rollback Strategy**
   * **Serving Failure:** สลับ `active` pointer ใน `ModelRegistry` กลับไปยัง Version `N-1` ที่ผ่าน `verify()` แล้วทันที
   * **Training Failure:** Hard-stop Worker ผ่าน `CostController`, บันทึก Last Valid Checkpoint, และปฏิเสธการ Commit เวอร์ชันที่ไม่สมบูรณ์
10. **Resource and Cost Estimate**
    * **Local/CI:** Tiny Synthetic CPU Tests (`MAX_CPU_MODEL_PARAMETERS <= 5M`); **$0**
    * **Cloud/GPU Sandbox (เฉพาะเมื่อได้รับอนุมัติแยก):** 1x Mid-tier GPU Spot/On-demand แบบจำกัดเวลา (~$15–$100 ต่อการทดลอง Pre-flight ที่ตั้ง Hard Budget Cap ไว้ชัดเจน) + Artifact Volume (~$10–$30/เดือน)
11. **Risks and Mitigations**
    * *ความเสี่ยง:* ค่า GPU บานปลายจาก Loop ค้างหรือ Divergence -> *การลดความเสี่ยง:* Hard-stop ใน `CostController` + Early-stopping + Budget Alert ที่ 50%/80%/100%
    * *ความเสี่ยง:* Registry File Lock ไม่ทำงานข้าม Node -> *การลดความเสี่ยง:* ย้าย Lock Coordinator สู่ PostgreSQL Advisory Lock / DB Unique Constraint
12. **Dependencies กับ Phase ก่อนหน้าและถัดไป**
    * *พึ่งพาก่อนหน้า:* Phase 13, Phase 14
    * *ปูทางสู่ถัดไป:* มอบ Native Model Weights & Serving Runtime จริงให้ Phase 16 (Reasoning & Planning), Phase 17 (Memory), และ Phase 18 (Adaptive Learning)

---

### Phase 16 — Native Reasoning & Planning
* **สถานะ:** `PROPOSED / NOT APPROVED / PLANNING ONLY`
* **ขอบเขตหลัก:** Reasoning Architecture, Planning and Task Decomposition, Verification and Consistency

1. **Objective และ Scope**
   * เปลี่ยน `ReasoningEngine` และ `PlanningEngine` จาก Rule-based Lookup / Structural Plan Validator ใน Phase 9.3–9.4 ไปสู่ **Native Model-backed Reasoning & Planning** ที่โมเดลของ ZYRQUEN สร้างแผนและให้เหตุผลได้จริง พร้อมกลไกตรวจความสอดคล้อง (Self-consistency / Contract Verification) ที่เชื่อถือได้
2. **Technical Architecture**
   * **Reasoning Loop:** Structured Scratchpad / Deliberate Inference Step บน `ZyrquenModel` (ควบคุม Token/Step Budget) ผสานกับ `apps/core/intelligence/contract.py`
   * **Task Decomposition Engine:** เปลี่ยนจาก `PlanningEngine.build_plan()` ที่รับขั้นจากผู้เรียก ให้โมเดลสร้าง DAG ขั้นตอนได้เอง แล้วส่งผ่าน `validate_plan()` (`plan_contract.py`) เพื่อตรวจ Cyclic Dependency, Missing Step, และ Success Criteria ก่อนอนุญาตให้ใช้แผน
   * **Verification Layer:** Cross-check ระหว่าง Output ที่โมเดลสร้างกับ Constraints/Facts ที่ส่งเข้า พร้อม Evidence Tagging ที่ตรวจสอบได้จริง
3. **Dependencies และ Prerequisites**
   * Phase 12 (Provenance & Capability Management), Phase 14 (Reasoning/Planning Benchmarks), Phase 15 (Native Model Runtime ที่ผ่านการฝึกฐานแล้ว)
4. **ไฟล์และโมดูลที่คาดว่าจะเกี่ยวข้อง**
   * *Existing:* `apps/core/intelligence/reasoning.py`, `apps/core/intelligence/contract.py`, `apps/core/intelligence/planning.py`, `apps/core/intelligence/plan_contract.py`, `tests/test_reasoning_contract.py`, `tests/test_reasoning_enforcement.py`, `tests/test_planning_contract.py`, `tests/test_planning_enforcement.py`
   * *Future Proposed:* Native Reasoning Adapter, DAG Plan Generator + Verifier, Multi-step Budget Controller
5. **Security และ Governance Requirements**
   * บังคับ Hard Cap จำนวน Reasoning Steps / Recursion Depth / Token Budget เพื่อป้องกัน Infinite Loop และ DoS
   * ห้ามแผนที่โมเดลสร้างขึ้นสั่ง Execute Side-effects โดยตรง — ต้องผ่าน Boundary ของ Phase 19 (Safety Governance) เท่านั้น
6. **Testing Strategy**
   * Benchmark เปรียบเทียบ Rule-based Baseline vs Native Model Reasoning บนชุดทดสอบ Task Decomposition, Logic Consistency, และ Cycle/Hallucinated-dependency Rejection
   * Adversarial Tests: Prompt ที่พยายามบังคับให้เกิด Infinite Plan หรือ Fake Provenance
7. **Acceptance Criteria**
   * `PlanningEngine` สามารถสร้างและ Validate แผนแบบ DAG จาก Task Goal ได้โดยผ่าน `validate_plan()` และบรรลุเกณฑ์ความถูกต้องตาม Benchmark ของ Phase 14
   * ผลลัพธ์ทุกชิ้นระบุระดับการตรวจสอบและ Provenance ของ Model Version ที่สร้างจริง
8. **Exit Gate Checklist**
   * [ ] Native Reasoning & Planning Evaluation Suite ผ่านเกณฑ์ที่กำหนด
   * [ ] Step/Time/Token Budget Hard-cap tests ผ่าน 100%
   * [ ] Contract & Provenance audit ไม่พบ Fake `model_inference=True`
9. **Failure and Rollback Strategy**
   * หาก Native Reasoning ต่ำกว่าเกณฑ์หรือเกิน Budget ให้ Fallback กลับสู่ Deterministic Validation Mode (`rule_based_scaffold` / `plan_validator`) และปิด Capability Flag ของ Phase 16 ทันที
10. **Resource and Cost Estimate**
    * **Local/CI:** Contract/Budget Unit Tests = **$0**
    * **Cloud/Runtime:** Inference Token Multiplier (Multi-step reasoning ใช้ Compute มากกว่า 1-turn chat 2x–5x; ต้องจำกัดด้วย Step Cap และ Quota ต่อ User)
11. **Risks and Mitigations**
    * *ความเสี่ยง:* Hallucinated Steps หรือ Unbounded Reasoning Cost -> *การลดความเสี่ยง:* Strict Schema Validation (`plan_contract.py`) + Hard Step Limit + Per-request Token Cap
12. **Dependencies กับ Phase ก่อนหน้าและถัดไป**
    * *พึ่งพาก่อนหน้า:* Phase 12, Phase 14, Phase 15
    * *ปูทางสู่ถัดไป:* ใช้ความสามารถ Memory/Knowledge ใน Phase 17 และควบคุมการเลือกใช้ Tool ใน Phase 19

---

### Phase 17 — Memory & Knowledge Integration
* **สถานะ:** `PROPOSED / NOT APPROVED / PLANNING ONLY`
* **ขอบเขตหลัก:** Memory Architecture, Knowledge Retrieval and Integration, Memory Integrity and Governance

1. **Objective และ Scope**
   * ยกระดับจาก In-memory `KnowledgeSystem` (Phase 9.2) และ Single-session Conversation Messages ไปสู่ระบบ **Persistent Memory & Grounded Knowledge Retrieval** ที่ปลอดภัย แยกสิทธิ์ตามผู้ใช้/องค์กรอย่างเคร่งครัด และตรวจสอบความน่าเชื่อถือของความจำก่อนป้อนให้ Native Model
2. **Technical Architecture**
   * **Tiered Memory Architecture:** แยกชัดเจนระหว่าง *Working Memory* (Active Conversation Context), *Episodic User Memory* (Scoped per `user_id`), และ *Verified Knowledge Store* (Curated Domain Knowledge)
   * **Hybrid Retrieval & Grounding:** ดึงข้อมูลพร้อม Source Citation, Timestamp และ Relevance Filter ก่อนประกอบ Context เข้า `ZyrquenModel` (เลือก Index ที่ไม่พึ่ง External SaaS Vector DB เพื่อคงอิสระ)
   * **Memory Integrity & Governance:** TTL / Retention Policy, Right-to-Delete (สอดคล้อง Conversation Delete), Conflict Resolution, และ Poisoning Guard
3. **Dependencies และ Prerequisites**
   * Phase 13 (Data Quality & PII Hygiene), Phase 15 (Native Model Context Serving), Phase 16 (Reasoning Integration)
4. **ไฟล์และโมดูลที่คาดว่าจะเกี่ยวข้อง**
   * *Existing:* `apps/core/intelligence/knowledge.py`, `apps/core/context.py`, `apps/core/conversation.py`, `apps/api/models.py`, `apps/api/routers/conversations.py`, `apps/api/test_conversations.py`, `apps/api/test_pg_integration.py`
   * *Future Proposed:* Persistent Knowledge/Memory Store Schema + Alembic Migration, Scoped Retrieval Service, Memory Governance & Deletion Worker
5. **Security และ Governance Requirements**
   * **Zero Cross-Tenant Leakage:** ทุก Query ของ Memory/Knowledge ต้องบังคับ Filter ตาม `user_id` / `tenant_scope` ระดับ Database Policy และทดสอบด้วย Multi-user Isolation Tests
   * **Memory Poisoning Defense:** แยก Unverified User Input ออกจาก Verified System Knowledge; ห้าม Auto-write ข้อมูลจาก Model Output ลง Global Knowledge โดยไม่ผ่าน Verification
6. **Testing Strategy**
   * Multi-user Isolation Tests (User B ต้องไม่มีทางดึง Memory ของ User A ได้แม้ผ่าน Indirect Prompt Injection)
   * Deletion Integrity Tests (ลบแล้วต้องไม่โผล่ใน Index/Retrieval อีก), Citation Grounding Tests, และ Migration Rollback Tests
7. **Acceptance Criteria**
   * ผลลัพธ์การตอบคำถามที่มี Grounded Knowledge แสดง Source Reference ที่ตรวจสอบได้ และลดอัตรา Hallucination เทียบ Baseline Phase 15–16
   * ผ่าน Cross-user Isolation และ Deletion Compliance Test 100%
8. **Exit Gate Checklist**
   * [ ] PostgreSQL Migration & Multi-tenant Isolation tests ผ่านบน CI (`postgres-integration`)
   * [ ] Data Retention & User Deletion cascade tests ผ่าน 100%
   * [ ] Indirect Prompt Injection / Memory Poisoning audit ผ่าน
9. **Failure and Rollback Strategy**
   * ปิด Persistent Memory Retrieval Flag เพื่อกลับสู่ Stateless/Conversation-only Context ชั่วคราว; Freeze Memory Write Pipeline หากพบ Contamination หรือ Cross-tenant anomaly
10. **Resource and Cost Estimate**
    * **Local/CI:** PostgreSQL Test Container + Embedded/Local Index Fixtures; **$0**
    * **Cloud/Runtime:** Storage + Memory Indexing Compute (~$10–$40/เดือน สำหรับ PostgreSQL + Index Storage)
11. **Risks and Mitigations**
    * *ความเสี่ยง:* ข้อมูลผู้ใช้รั่วไหลข้ามบัญชี (Cross-tenant leakage) -> *การลดความเสี่ยง:* Mandatory `owner_id` scoping ใน Data Layer + Adversarial Multi-user Integration Tests
    * *ความเสี่ยง:* Memory Bloat / Stale Facts -> *การลดความเสี่ยง:* TTL, Summarization Quota, และ Provenance Timestamp Weighting
12. **Dependencies กับ Phase ก่อนหน้าและถัดไป**
    * *พึ่งพาก่อนหน้า:* Phase 13, Phase 15, Phase 16
    * *ปูทางสู่ถัดไป:* ป้อน Historical Signals และ Grounded Context สู่ Phase 18 (Adaptive Learning) และ Phase 20 (System Maturity)

---

### Phase 18 — Adaptive Learning & Improvement
* **สถานะ:** `PROPOSED / NOT APPROVED / PLANNING ONLY`
* **ขอบเขตหลัก:** Learning Strategy, Feedback and Evaluation Loops, Controlled Improvement Mechanisms

1. **Objective และ Scope**
   * เปลี่ยน `FeedbackLog` ที่เคยเก็บชั่วคราวในหน่วยความจำ (Phase 9.5) ไปสู่ระบบ **Controlled Continuous Improvement Pipeline** ที่รวบรวม Feedback จริงจาก Workspace/Evaluator อย่างปลอดภัย แปลงเป็น Verified Curated Training/Eval Samples และปรับปรุงโมเดลผ่าน **Offline Controlled Retraining + Evaluation Gate** (ไม่ใช่ออนไลน์ Self-modification แบบไร้การควบคุม)
2. **Technical Architecture**
   * **Persistent Feedback Store:** บันทึก `FeedbackRecord` พร้อม Privacy Scrubbing และ Statistical Gate (เช่น กลุ่มที่มีตัวอย่าง < 30 ยังคงห้ามตีความสัดส่วน ตามกติกา `summarize()` ใน Phase 9.5)
   * **Offline Curation & Replay Loop:** คัดกรอง Feedback -> Human/Evaluator Verification -> สร้าง Delta Dataset (`zyrquen.dataset-manifest.v1`) รวม Regression Mix เพื่อกัน Catastrophic Forgetting -> Offline Training Job (Phase 15) -> Evaluation Gate (Phase 14)
   * **Controlled Improvement Mechanisms:** ใช้ Shadow Evaluation / Canary Comparison บน Offline Benchmark ก่อนขอ Human Approval เพื่อ Promote เวอร์ชันใหม่
3. **Dependencies และ Prerequisites**
   * Phase 11 (Workspace Feedback Signals), Phase 13 (Dataset Curation & PII Scrubbing), Phase 14 (Regression & Evaluation Gate), Phase 15 (Registry & Version Rollback)
4. **ไฟล์และโมดูลที่คาดว่าจะเกี่ยวข้อง**
   * *Existing:* `apps/core/intelligence/feedback_contract.py`, `apps/core/intelligence/feedback_log.py`, `apps/core/intelligence/feedback_summary.py`, `tests/test_feedback_contract.py`, `tests/test_feedback_log.py`, `tests/test_feedback_summary.py`, `apps/core/native/registry.py`, `apps/api/routers/training.py`
   * *Future Proposed:* Persistent Feedback Repository + Migration, Offline Feedback-to-Dataset Curator, Catastrophic Forgetting Regression Harness
5. **Security และ Governance Requirements**
   * **ห้าม Online Weight Mutation:** โมเดลที่กำลังให้บริการ (`/v1/native-ai/*`) ต้อง Immutable ระหว่าง Inference เสมอ
   * **Feedback Poisoning Protection:** ป้องกัน Sybil/Spam Feedback ด้วย Auth + Rate Limit + Human/Evaluator Review Gate ก่อนนำ Feedback เข้าสู่ Training Manifest
   * **ห้าม Auto-Promotion:** ทุก Iteration ของการปรับปรุงต้องผ่าน Evaluation Gate และ Manual Promote
6. **Testing Strategy**
   * Feedback Ingestion Security Tests (Reject invalid/untrusted bulk injection), Statistical Threshold Tests (`n < 30`), และ Regression Retention Tests (ความสามารถเดิมต้องไม่ตกลงหลัง Fine-tune/Retrain)
7. **Acceptance Criteria**
   * Feedback ไหลจาก Workspace/API สู่ Persistent Store, ผ่านการกลั่นกรองและสร้าง Dataset Manifest, ผ่าน Offline Training และ Evaluation Gate โดยไม่เกิด Catastrophic Forgetting
8. **Exit Gate Checklist**
   * [ ] Persistent Feedback Schema & Quarantine tests ผ่าน
   * [ ] Catastrophic Forgetting Regression Suite ผ่านเกณฑ์ (>= Baseline ทุกหมวดหลัก)
   * [ ] Zero Online Weight Mutation & Zero Auto-Promotion audit ผ่าน
9. **Failure and Rollback Strategy**
   * ปฏิเสธ Model Candidate ที่คะแนน Regression ตก; หากพบพฤติกรรมถดถอยหลัง Promote ให้ Rollback `ModelRegistry` `active` pointer ทันทีและ Quarantine Feedback Batch ต้นเหตุ
10. **Resource and Cost Estimate**
    * **Local/CI:** Curation & Statistical Policy Tests = **$0**
    * **Cloud/GPU (เฉพาะเมื่ออนุมัติรอบ Retrain):** Scheduled Offline Adaptation Run (~$20–$100 ต่อรอบ ตาม Budget Cap ใน `CostController`)
11. **Risks and Mitigations**
    * *ความเสี่ยง:* Model Collapse / Catastrophic Forgetting / Poisoned User Feedback -> *การลดความเสี่ยง:* Replay Mix กับ Core Verified Dataset + Mandatory Evaluator Sign-off + Held-out Regression Gate
12. **Dependencies กับ Phase ก่อนหน้าและถัดไป**
    * *พึ่งพาก่อนหน้า:* Phase 11, Phase 13, Phase 14, Phase 15, Phase 17
    * *ปูทางสู่ถัดไป:* ปรับปรุงคุณภาพ Decision/Reasoning ก่อนเข้าสู่ Phase 19 (Autonomous Capability & Safety) และ Phase 20

---

### Phase 19 — Autonomous Capability & Safety Governance
* **สถานะ:** `PROPOSED / NOT APPROVED / PLANNING ONLY`
* **ขอบเขตหลัก:** Tool and Capability Boundaries, Permission and Safety Architecture, Human Approval and Auditability

1. **Objective และ Scope**
   * เปิดใช้งานความสามารถเชิงปฏิบัติการแบบมีขอบเขต (Tool Use, Sandboxed Code Analysis/Generation, Bounded Application Scaffolding) บนพื้นฐานของ Phase 9.6–9.8 โดยแก้ไขช่องว่างเรื่อง **Trusted Identity/Approval**, **Sandboxed Execution Isolation**, และ **Immutable Auditability** ก่อนอนุญาต Side-effects ใดๆ
2. **Technical Architecture**
   * **Trusted Identity & Cryptographic Approval:** แทนที่ Self-asserted `approval_granted=True` (ข้อจำกัดใน Phase 9.6) ด้วย Server-signed Approval Token ที่ผูกกับ `user_id`, `role`, `action_hash`, `expiry` และ UI Confirmation Flow สำหรับ High-risk Actions (Human-in-the-Loop)
   * **Capability & Sandbox Boundaries:** รัน Execution Adapter ภายใน Isolated Sandbox (Read-only default, No network egress unless allowlisted, Symlink/Realpath enforcement แทน lexical-only check ใน `WorkspaceBoundaryPolicy`, Resource/Timeout limits)
   * **Auditability:** บันทึกคำขอ Tool, Input/Output Digest, Approval Actor และ Policy Decision ลง `AuditLog` แบบ Append-only
3. **Dependencies และ Prerequisites**
   * Phase 12 (Capability Management), Phase 16 (Reasoning & Planning ที่สร้างคำขอ Tool อย่างมีเหตุผล), Phase 14 (Safety/Adversarial Evaluation Gate)
4. **ไฟล์และโมดูลที่คาดว่าจะเกี่ยวข้อง**
   * *Existing:* `apps/core/intelligence/tool_contract.py`, `apps/core/intelligence/tool_policy.py`, `apps/core/intelligence/tool_registry.py`, `apps/core/intelligence/code_contract.py`, `apps/core/intelligence/code_policy.py`, `apps/core/intelligence/application_contract.py`, `apps/core/intelligence/file_manifest_contract.py`, `apps/core/intelligence/workspace_policy.py`, `apps/core/intelligence/build_validation.py`, `apps/api/api_access_models.py` (`AuditLog`)
   * *Future Proposed:* Server-side Approval Token Service, Isolated Execution Sandbox Adapter, Real-filesystem Symlink-safe Boundary Enforcer
5. **Security และ Governance Requirements**
   * **Least Privilege & Default Deny:** Side-effecting tools ทุกตัวปิดเป็นค่าเริ่มต้น; ห้าม Code Execution, Package Install, หรือ Network Outbound นอก Sandbox Allowlist
   * **Human-in-the-Loop Mandatory:** การกระทำที่เปลี่ยนแปลงข้อมูล, สร้าง/เขียนไฟล์, หรือเรียกทรัพยากรภายนอก ต้องได้รับ Human Approval ที่ตรวจสอบลายเซ็นได้ทุกครั้ง
   * **Prompt Injection Defense:** แยก Data Plane ออกจาก Control Plane; Output จาก External/Memory data ห้าม Bypass PermissionGate
6. **Testing Strategy**
   * Red-team / Adversarial Sandbox Escape Tests (Symlink traversal, Forged approval token, Privilege escalation, SSRF, Resource exhaustion)
   * Policy Matrix Tests สำหรับ Read-only vs Side-effecting Tools และ Complete Audit Trail Verification
7. **Acceptance Criteria**
   * ไม่สามารถ Execute tool หรือเขียนไฟล์ได้หากขาด Verified Server-side User/Admin Approval และ Sandbox Policy
   * ทุก Tool Invocation มี Audit Trail ครบถ้วนและปฏิเสธ Traversal/Escape Attempts ได้ 100%
8. **Exit Gate Checklist**
   * [ ] Red-team Sandbox Escape & Forged Approval Tests ผ่าน 100%
   * [ ] AuditLog persistence & tamper-check tests ผ่านบน PostgreSQL
   * [ ] Security Architecture Review อนุมัติ Policy Boundaries ทุกหมวด
9. **Failure and Rollback Strategy**
   * Global Kill Switch: ตั้ง Policy Flag กลับสู่ `ExecutionSafetyPolicy` (`execution_performed=False` สำหรับทุก Tool) ทันทีเมื่อพบ Policy Bypass หรือ Anomaly เพื่อลด Surface กลับไปเป็น Read-only / Text-only
10. **Resource and Cost Estimate**
    * **Local/CI:** Policy & Mocked Sandbox Isolation Tests = **$0**
    * **Cloud/Runtime:** Ephemeral Sandbox Container / MicroVM Pool (คิดค่าใช้จ่ายตาม Execution Time เมื่อเปิดใช้งานจริง ~ $15–$60/เดือน + Hard Timeout)
11. **Risks and Mitigations**
    * *ความเสี่ยง:* Remote Code Execution / Data Exfiltration ผ่าน Tool Use -> *การลดความเสี่ยง:* Isolated Ephemeral Sandbox + Network Egress Block + Mandatory Human Approval Token + Symlink-aware Realpath Guard
12. **Dependencies กับ Phase ก่อนหน้าและถัดไป**
    * *พึ่งพาก่อนหน้า:* Phase 12, Phase 14, Phase 16
    * *ปูทางสู่ถัดไป:* ป้อนระบบความสามารถที่มี Safety Gate ครบเข้าสู่ Phase 20 (System Maturity)

---

### Phase 20 — Native Intelligence System Maturity
* **สถานะ:** `PROPOSED / NOT APPROVED / PLANNING ONLY`
* **ขอบเขตหลัก:** End-to-End System Integration, Capability and Reliability Assessment, Operational Readiness, Long-Term Maintenance Strategy

1. **Objective และ Scope**
   * บูรณาการทุกองค์ประกอบจาก Phase 11–19 เข้าเป็นแพลตฟอร์ม ZYRQUEN Native Intelligence ที่สมบูรณ์แบบ End-to-End พร้อมผ่านการรับรองเชิงปฏิบัติการ (Production Operational Readiness), Disaster Recovery Drill, Load/Reliability Assessment, และกลยุทธ์บำรุงรักษาระยะยาว
2. **Technical Architecture**
   * **End-to-End Platform Cohesion:** Workspace Intelligence (Phase 11) <-> Native Runtime & Model Lifecycle (Phase 12, 15) <-> Grounded Memory (Phase 17) <-> Reasoning & Planning (Phase 16) <-> Governed Tool/Sandbox Capabilities (Phase 19) <-> Continuous Evaluation & Safe Adaptation (Phase 14, 18)
   * **Observability & SRE Stack:** Prometheus/OpenTelemetry Metrics (Latency, Token Throughput, Queue Depth, Error Budget), Structured Tracing ผ่าน `X-Correlation-ID`, Alerting, และ Automated Backup/Restore Verification (`scripts/verify_backup_integrity.py`)
   * **TLS & Security Hardening:** ทบทวน `Secure` Cookie Policy (`apps/web/src/lib/cookies.ts`) กับ TLS Reverse Proxy, Dependency/Container Vulnerability Scanning ใน CI, และ Zero-downtime Blue/Green หรือ Canary Model Rollout
3. **Dependencies และ Prerequisites**
   * Phase 11–19 ทุก Phase ที่เกี่ยวข้องผ่าน Exit Gate และได้รับอนุมัติครบถ้วน
   * ผ่านการทดสอบบน Staging Environment ที่จำลอง Topology เหมือน Production (Managed PostgreSQL + Persistent Volumes + TLS)
4. **ไฟล์และโมดูลที่คาดว่าจะเกี่ยวข้อง**
   * *Existing:* `apps/api/main.py`, `apps/api/operations.py`, `apps/web/src/lib/cookies.ts`, `.github/workflows/api-tests.yml`, `docker-compose.yml`, `scripts/verify_backup_integrity.py`, `docs/CLOUD_DEPLOYMENT.md`, `docs/operations/**` (9 runbooks), `apps/api/main.py.save` (cleanup)
   * *Future Proposed:* OpenTelemetry/Prometheus exporters, Production Staging Terraform/IaC specs (เมื่ออนุมัติ), Automated Chaos/Load Test Suite
5. **Security และ Governance Requirements**
   * ผ่าน Security Operations Checklist (`docs/operations/SECURITY_OPERATIONS_CHECKLIST.md`) ครบ 100%
   * ผ่าน Backup-and-Restore Integrity Drill บน Disposable Staging DB + Artifact Volume
   * คงหลักการ Fail-closed readiness (`/readyz`), Least-privilege non-root containers (`UID 10001` / `1001`), และ Human-approved Model Promotion
6. **Testing Strategy**
   * Full End-to-End System Suite (Auth -> Workspace -> Streaming Native Inference -> Follow-ups -> Grounded Memory -> Governed Planning/Tool -> Audit -> Backup/Restore Drill)
   * Load, Soak, Chaos/Failover Tests (DB connection drop, Worker restart recovery, Model rollback under load)
7. **Acceptance Criteria**
   * ผ่าน SLO/Reliability Targets ที่กำหนด (เช่น Availability, p95 Latency, Error Rate, Zero Critical Security Findings) บน Staging Soak Test
   * ผ่าน Disaster Recovery / Rollback Drill ภายใน RTO/RPO ที่กำหนด
8. **Exit Gate Checklist**
   * [ ] Phase 11–19 Gate Closure ครบถ้วน
   * [ ] CI/CD Pipeline (`test`, `web`, `postgres-integration`, `docker`, security scan, E2E) เขียวทั้งหมด 0 critical skips
   * [ ] Backup & Restore Drill (`verify_backup_integrity.py`) + Model Rollback Drill ผ่านมีหลักฐานบันทึก
   * [ ] Sign-off จากเจ้าของโครงการเพื่อพิจารณาเปิด Production Deployment
9. **Failure and Rollback Strategy**
   * **Model Degradation:** Rollback `ModelRegistry` ไปยัง Active Artifact ก่อนหน้า
   * **Release/Infra Failure:** Rollback Container Tag + Restore Database จาก Verified Point-in-time Snapshot ตาม `docs/operations/BACKUP_RECOVERY_RUNBOOK.md` และ `INCIDENT_RESPONSE_RUNBOOK.md`
10. **Resource and Cost Estimate**
    * **Staging / Production Baseline (เฉพาะเมื่อได้รับอนุมัติ Production Deployment):**
      * Managed PostgreSQL + Automated Backups (~$30–$120/เดือน)
      * Persistent Artifact/Registry Volume (~$10–$50/เดือน)
      * Web + API Compute Containers (~$40–$150/เดือน)
      * Inference GPU/Compute Node (ขึ้นกับ Traffic Tier ที่เจ้าของโครงการอนุมัติ)
    * **Long-Term Maintenance:** Monthly Security Patch, Quarterly DR Drill, Continuous Cost Telemetry Monitoring
11. **Risks and Mitigations**
    * *ความเสี่ยง:* Technical Debt สะสม / Drift ระหว่าง Local, CI และ Cloud -> *การลดความเสี่ยง:* IaC Declarative Config + Zero-skip CI Gates + Monthly Drift Audit
    * *ความเสี่ยง:* Uncontrolled Inference/Cloud Bill -> *การลดความเสี่ยง:* Per-user Token Quotas + Autoscaling Ceiling + Billing Hard-alert Caps
12. **Dependencies กับ Phase ก่อนหน้าและถัดไป**
    * *พึ่งพาก่อนหน้า:* Phase 11–19 ทั้งหมด (และ Phase 10.9.9 เป็นรากฐานเริ่มต้น)
    * *ถัดไป:* สิ้นสุด Roadmap ขอบเขต Phase 20 (ไม่มี Phase 21 ตามข้อกำหนด; เข้าสู่วงจร Production Operations & Maintenance)

---

## 2. Master Dependency Map (Phase 10.9.9 & Phase 11–20)

```
[Phase 10.9.9: NOT CLOSED]  <-- HARD BLOCKER: ต้องผ่าน CI 4 jobs บน main ก่อนเริ่ม Phase 11+
        │
        ├──────────────────────────────┬──────────────────────────────┐
        ▼                              ▼                              ▼
[Phase 11: Workspace Intel]   [Phase 12: Native Intel Found.]  [Phase 13: Knowledge & Data Pipeline]
 (PROPOSED / NOT APPROVED)     (PROPOSED / NOT APPROVED)       (PROPOSED / NOT APPROVED)
        │                              │                              │
        │                              └──────────────┬───────────────┘
        │                                             ▼
        │                              [Phase 14: Evaluation & Capability Measurement]
        │                                             │
        │                                             ▼
        │                              [Phase 15: Native Model Readiness]
        │                                 (KV-Cache, Durable Jobs, Training-to-Inference)
        │                                             │
        │                              ┌──────────────┴───────────────┐
        │                              ▼                              │
        │               [Phase 16: Native Reasoning & Planning]       │
        │                              │                              │
        │                              ▼                              │
        │               [Phase 17: Memory & Knowledge Integration]    │
        │                              │                              │
        ├──────────────────────────────┴──────────────┬───────────────┘
        ▼                                             ▼
[Phase 18: Adaptive Learning & Improvement]   [Phase 19: Autonomous Capability & Safety Governance]
        │                                             │
        └──────────────────────┬──────────────────────┘
                               ▼
              [Phase 20: Native Intelligence System Maturity]
```

### สรุปลำดับการพึ่งพาและเส้นทางวิกฤต
* **Critical Path:**
  `Phase 10.9.9 (Closure)` -> `Phase 12 (Native Interfaces)` / `Phase 13 (Data Pipeline)` -> `Phase 14 (Evaluation Gate)` -> `Phase 15 (Native Model Readiness)` -> `Phase 16 (Reasoning & Planning)` -> `Phase 17 (Memory & Knowledge)` -> `Phase 18 / 19` -> `Phase 20 (System Maturity)`
* **Blocking Dependencies:**
  * **Phase 10.9.9 (`NOT CLOSED`)** บล็อกการอนุมัติ Implementation ของทุก Phase (11–20)
  * **Phase 13 + Phase 14** บล็อกการ Training และ Promote โมเดลใน Phase 15
  * **Phase 15** บล็อกการเปลี่ยนผ่านของ Phase 16, 17, 18 จาก Software Contracts ไปสู่ Native Model จริง
  * **Phase 19** บล็อกการเปิดใช้งาน Side-effecting Tools / Execution ใดๆ บน Production
* **Parallelizable Work (เฉพาะระดับงานออกแบบ / ซอฟต์แวร์ หลัง Phase 10.9.9 ปิดแล้ว):**
  * **Phase 11 (Workspace UX)**, **Phase 12 (Capability/Provenance Contracts)** และ **Phase 13 (Data Validation Pipeline ด้วย Synthetic fixtures)** สามารถพัฒนาคู่ขนานกันได้โดยไม่ชนกัน
  * **Phase 18 (Offline Curation & Feedback Persistence)** และ **Phase 19 (Sandbox & Approval Token Architecture)** สามารถเตรียมโครงสร้างส่วนฐานควบคู่กันหลัง Phase 16 มีเสถียรภาพ
* **Gate Requirements กลาง (ทุก Phase):**
  1. มี Evidence ของ Phase ก่อนหน้าครบถ้วน (ห้ามอนุมัติข้าม Gate)
  2. Test Suite (Unit + Integration + Security) ผ่านบน CI SHA ปัจจุบัน
  3. Zero External AI Wrapper / Zero Auto-Promotion / Fail-closed Guarantees
  4. Owner Written Approval ก่อนเปิด Phase ถัดไปหรือใช้จ่ายงบประมาณ
* **External Dependencies:**
  * GitHub Actions & Container Registry (CI/CD verification)
  * PostgreSQL 16 (ทั้ง Test marker DB และ Managed DB ในอนาคต)
  * PyTorch runtime (สำหรับ Native Model Training/Inference จริงนอกเหนือจาก Pure-Python API tests)
  * Approved Dataset Licenses & Hardware/GPU Provider (เฉพาะเมื่อได้รับอนุมัติแยกใน Phase 13 / 15 / 20)

---

## 3. Resource and Cost Governance

> **นโยบายหลัก:** Minimal Cost First — ใช้ Local CPU และ Synthetic Micro-fixtures ในการพัฒนาและทดสอบจนกว่า Pipeline และ Quality Gates จะเสถียร 100% ก่อนพิจารณาใช้ทรัพยากร Cloud/GPU ใดๆ

| สภาพแวดล้อม | บทบาทและขอบเขตการใช้งาน | แนวทางควบคุมต้นทุน (Minimal Cost) | ข้อจำกัด / การอนุมัติ |
| :--- | :--- | :--- | :--- |
| **Local Development** | พัฒนาซอฟต์แวร์, UI Tests, Pure-Python Contract Tests, Tiny Synthetic CPU Smoke Tests (`<= 5M` params ตาม `TrainingOrchestrator`) | ใช้ทรัพยากรเครื่องท้องถิ่น / Docker Compose; **$0 Cloud Cost** | ห้ามดาวน์โหลด Dataset ขนาดใหญ่หรือ Weights จริงโดยไม่ได้รับอนุมัติ |
| **CI (GitHub Actions)** | Static checks, Vitest, Next.js Build, API Unit/PG Integration, Docker Build | แยก Job API/Web จากงานหนัก; ใช้ CPU `torch` wheel เฉพาะ job ที่จำเป็นและ Cache dependencies | ห้ามรัน Training จริงหรือโหลด Weights ใหญ่ใน CI |
| **Cloud Resources (Staging / Production / GPU)** | Managed PostgreSQL, Persistent Artifact Volumes, GPU Training Sandbox, Staging/Prod Containers | เลือก On-demand/Spot แบบปิดเมื่อไม่ใช้, ตั้ง `ZYRQUEN_TRAINING_MAX_BUDGET_USD`, `MAX_RUNTIME_SECONDS`, และ Billing Hard-alerts | **ห้าม Provision GPU/Cloud, ห้ามเริ่ม Training, ห้ามสร้างค่าใช้จ่ายใดๆ จนกว่า Owner จะอนุมัติแยกเป็นลายลักษณ์อักษร** |

### ประมาณการค่าใช้จ่ายที่เป็นไปได้ในอนาคต (เมื่อได้รับอนุมัติใช้งานจริงเท่านั้น)
* **Phase 11–12 & Phase 13–14 (Dev/CI + Synthetic Fixtures):** **$0 / เดือน**
* **Phase 15 Pre-flight / Sandbox Training (เมื่ออนุมัติ):** ช่วงทดลองควบคุมงบประมาณ **~$15–$100 ต่อรอบ** (GPU ชั่วคราว + Budget Hard Cap)
* **Phase 17 / 20 Managed Staging Infrastructure (เมื่ออนุมัติ):** **~$80–$320 / เดือน** (Managed PG + Volume + Web/API + Sandbox Compute — ไม่รวม Dedicated GPU Cluster ที่ขึ้นกับ Traffic Tier)

---

## 4. Consolidated Risk Register (Phase 11–20)

| Risk ID | Phase | ความเสี่ยง | ระดับ | มาตรการลดความเสี่ยง (Mitigation) |
| :--- | :---: | :--- | :---: | :--- |
| **R-01** | All | อ้างว่า Native Model มีความสามารถทั้งที่โค้ดยังเป็น Rule-based Contract (False Capability Claim) | Critical | บังคับ `Provenance` จาก Runtime จริง, แยกสถานะชัดเจนในเอกสาร, ห้าม Mock scores |
| **R-02** | 10.9.9 -> All | เริ่ม Phase 11+ ทั้งที่ `main` CI และ PG Integration ยังไม่ผ่าน | Critical | ตั้ง Phase 10.9.9 `CLOSED` เป็น Hard Prerequisite |
| **R-03** | 13, 17, 18 | Data Poisoning, PII/Secret Leakage หรือ Train-Eval Contamination | High | PII/Secret scanner, License allowlist, SHA-256 sealing, Overlap/Contamination block |
| **R-04** | 15, 18 | ค่าใช้จ่าย GPU บานปลาย หรือโมเดลพังหลัง Auto-promotion | Critical | `CostController` Hard-stop, Zero Auto-Promotion, Evaluation Gate + One-step Rollback |
| **R-05** | 11, 15 | Concurrency Bottleneck (`_semaphore = Semaphore(1)`) ทำให้ Streaming/Follow-up ค้าง | High | ย้าย Inference Worker Pool, Timeout/Queue policy, Cancellable follow-up requests |
| **R-06** | 17 | Cross-tenant Memory Leakage ระหว่างผู้ใช้ | Critical | บังคับ `user_id` scoping ระดับ DB Query + Adversarial Multi-user Integration Tests |
| **R-07** | 16, 19 | Prompt Injection นำไปสู่ Unbounded Planning Loop หรือ Tool Execution โดยพลการ | Critical | Step/Token Hard Cap, Server-signed Human Approval Token, Isolated Ephemeral Sandbox, Default-deny `ExecutionSafetyPolicy` |
| **R-08** | 14, 20 | Schema/Migration Drift หรือ Backup ไม่สามารถกู้คืนได้จริง | High | Test `upgrade/downgrade` บน PG CI ทุกครั้ง + Quarterly `verify_backup_integrity.py` Drill |

---

## 5. Governance Summary & Next Action Gate

* **สถานะปัจจุบันของ Roadmap:** `MASTER ROADMAP PREPARED` — **ทุก Phase (11–20) อยู่ในสถานะ `PROPOSED / NOT APPROVED / PLANNING ONLY`**
* **สิ่งที่ไม่ได้ทำในรอบนี้ (Strict Compliance):**
  * ไม่ได้แก้ไข Source Code ใดๆ (`apps/web/`, `apps/api/`, `apps/core/`)
  * ไม่ได้แก้ไข Database Schema หรือ API Contract
  * ไม่ได้เริ่ม Training, ดาวน์โหลด Dataset/Weights, หรือ Provision GPU/Cloud
  * ไม่ได้ Commit / Push / GitHub Sync
* **ขั้นตอนถัดไป:** รอคำสั่งจาก **OWNER** เพื่อนำชุดส่งมอบ Phase 10.9.9 (`handoff/phase-10.9.9/`) ไปตรวจสอบและปิด Gate Phase 10.9.9 ใน GitHub Codespaces / GitHub Actions ให้สำเร็จก่อนพิจารณาอนุมัติ Phase 11 เป็นลำดับแรก
