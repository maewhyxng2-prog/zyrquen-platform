# ZYRQUEN Ω∞ — V11 Memory & Knowledge Integration Specification

- **Document ID:** `V11-DOC-12`
- **Status:** `STAGE 1 CODE READINESS APPROVED (V10 CLOSED_FAIL BASELINE POLICY — TRAINING & PROMOTION LOCKED)`
- **Existing Subsystem Anchors:**
  - `phases/phase17.py` (`MemoryStore`: `short`, `long`, `task` tiers; Grounded Retrieval; `owner_id + workspace_id` multi-tenant isolation; PII block)
  - `apps/core/intelligence/knowledge.py` (`KnowledgeSystem`: entity & directed relation graph)
  - `apps/core/workflow/handlers/groups.py::handle_knowledge_validate` (`knowledge.memory_ingestion` workflow)

---

## 1. Integration Principles (Zero Duplication of Phase 17 & KnowledgeSystem)

1. **Non-Parametric Memory + Parametric Reasoning Separation:** V11 ไม่พยายาม "ท่องจำข้อเท็จจริงของโลก" ทั้งหมดลงใน Weights ขนาด 3.74M–4.75M แต่ฝึกให้ `ZyrquenModel` **ใช้เหตุผลและปรับแก้ความเชื่อ (Belief Revision) บน Grounded Evidence ที่ดึงมาจาก `MemoryStore` และ `KnowledgeSystem`**
2. **Preserve Phase 17 Invariants Unchanged:** ห้ามแก้ไขพฤติกรรมหรือทำลายสัญญาของ `phases/phase17.py`:
   - Valid tiers strictly `{"short", "long", "task"}`
   - Multi-tenant check `owner_id` & `workspace_id` mandatory
   - Grounded Retrieval returns ONLY records with non-empty `source` and preserves `verified: bool`
   - PII blocking before storage

---

## 2. Knowledge & Memory Representation in V11 SFT Prompts (Stage 4+)

ใน Stage 4 (`knowledge_integration`) และ Runtime Retrieval Injection บริบทความรู้จะถูกจัดรูปแบบเชิงโครงสร้างเข้าสู่ Prompt ก่อน Slot Binding:

```text
MEMORY_CONTEXT:
- [tier=long][source=ledger_v1][verified=true] base: TR_E01 -> TR_E02
- [tier=task][source=ops_patch_2][verified=true] update: TR_E01 -> TR_E03
- [tier=short][source=unverified_note][verified=false] claim: TR_E04 -> TR_E05
QUERY: resolve TR_E01 ?
```

### Required Reasoning Semantics Over Memory Context
1. **Override Rule (`base` + `update`):** เมื่อมี `update:` จากแหล่งที่ `verified=true` ให้แทนที่ค่า `base:` ของ Entity เดิม
2. **Selective Retention:** Entity อื่นใน `base:` ที่ไม่ได้ถูก `update:` ต้องคงค่าเดิม
3. **Belief Retraction (`retract:`):** หากมี `retract:` บน relation ให้ถือว่าสถานะปัจจุบันคือ `"unknown"` (เว้นแต่มี `update:` ใหม่กว่าที่ verified)
4. **Conflict Detection (`"conflict"`):** หากพบข้อมูล `verified=true` สองชุดที่ขัดแย้งกันเอง (เช่น `fact: A -> B` และ `fact: A -> C` หรือ cycle `A > B, B > C, C > A`) โดยไม่มี `update:` ชัดเจน ต้องตอบ `"conflict"`
5. **Unverified Evidence Restraint (Phase 16/17 Alignment):** ข้อความที่ติด `[verified=false]` ห้ามถูกโมเดลนำมาอ้างเป็นข้อเท็จจริงยืนยัน (`unverified` fallback -> `"unknown"` เว้นแต่มีหลักฐาน verified รองรับ)

---

## 3. Tenant Boundary & Workflow Hook Safety

- การนำเข้าความรู้เข้าสู่ Pipeline ต้องผ่าน `knowledge.memory_ingestion` (`handle_knowledge_validate` ใน `apps/core/workflow/handlers/groups.py`) ซึ่งตรวจ `tenant_id` / `owner_id` / `workspace_id` และสแกน PII (`_EMAIL_RE`, `_PHONE_RE`) และเก็บ SHA-256 provenance digest
- **ห้าม** ป้อนความจำของผู้ใช้ A (`owner_a`) เข้าบริบท Prompt ของผู้ใช้ B (`owner_b`) ในทุกกรณี

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- รูปแบบ Metadata Tag `[tier=...][source=...][verified=...]` สามารถถูกบีบอัดเป็นคำศัพท์ BPE คงที่ได้ง่ายภายใน `vocab_size = 2048/4096`
- `phases/phase17.py` คงอยู่เดิมในฐานะ Contract Layer โดย Runtime Adapter ใน `apps/core/` จะเป็นผู้เรียกใช้แทนการแก้ไขไฟล์ใน `phases/`

### OPEN DECISIONS
- **OD-MK-01:** ใน Production API (`apps/api/routers/conversations.py` / `inference.py`), จะจัดเก็บ Persistent `MemoryStore` state ใน SQLite/PostgreSQL table (ผ่าน migration ใหม่ที่อนุมัติแยก) หรือเริ่มต้นด้วย session-scoped store
- **OD-MK-02:** รูปแบบ Timestamp/Priority resolution เมื่อมี `update:` หลายลำดับใน Stage 4 (`seq=1, seq=2` vs literal order in prompt)

### NOT VERIFIED
- ความสามารถของ `ZyrquenModel` ในการแยกแยะ `[verified=true]` vs `[verified=false]` เมื่อมี Distractor facts ยาวถึง `200+` tokens ยัง **NOT VERIFIED**
- Integration bridge จริงระหว่าง `phases/phase17.py::MemoryStore` กับ `apps/core/inference.py` ยังไม่ได้ถูกสร้างหรือทดสอบใน codebase
