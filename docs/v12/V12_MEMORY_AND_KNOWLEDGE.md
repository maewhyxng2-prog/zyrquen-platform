# ZYRQUEN Ω∞ — V12 Memory & Knowledge Integration Specification

- **Document ID:** `V12-DOC-12`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Integration Anchor:** `MemoryStore` (Phase 17) & `KnowledgeSystem`
- **Primary Training Windows:** Stage 2 (`Knowledge Acquisition`: steps `5,001–13,000`) & Stage 5 (`Memory & Knowledge Integration`: steps `33,001–41,000`)

---

## 1. Grounded Memory Architecture & Separation of Roles

ใน ZYRQUEN V12 ความรู้และหน่วยความจำต้อง **มีที่มา ตรวจสอบได้ แก้ไขตามหลักฐานได้ และแยกขอบเขตสิทธิ์ชัดเจน** โดยแบ่งหน้าที่ออกเป็น 2 ส่วนที่ไม่ก้าวก่ายกัน:

1. **System Memory Infrastructure (`MemoryStore` — Phase 17):**
   - จัดการ Persistence, Tenant Isolation (`tenant_id`), Scope (`session` vs `long_term`), PII Redaction ก่อนเขียนลง Disk, และ Deterministic Retrieval พร้อม Metadata (`source_id`, `timestamp`, `confidence`, `sha256`)
2. **Native Model Cognitive Processing (`ZyrquenModel` — Stage 2 & 5):**
   - เรียนรู้การอ่าน Structured Grounded Context (`[source=S1 | t=102] ...`) ที่ป้อนเข้ามาใน Prompt
   - ตัดสินใจเชิงตรรกะว่าจะ **Accept & Cite**, **Override by Newer Valid Authority**, **Flag `conflict`**, หรือ **Abstain (`unknown`)** เมื่อหน่วยความจำไม่มีคำตอบ

---

## 2. Knowledge Acquisition (Stage 2) vs. Memory Integration (Stage 5)

| Dimension | Stage 2 (`steps 5,001–13,000`) | Stage 5 (`steps 33,001–41,000`) |
|---|---|---|
| **Core Objective** | การรับรู้และดึงข้อเท็จจริงแบบมี Provenance (`[source=...]`), Attribute Schemas, และ Multi-Fact Synthesis ภายใต้ Noise | การเชื่อมโยงหน่วยความจำหลายรอบ, **Temporal Override**, **Irreconcilable Conflict Detection**, และ Tenant/PII Boundary Adherence |
| **Conflict Policy** | Single-Consistent KB + Noise Filtering | Multi-Source Conflicting KB: แยก **Timestamp/Authority Override** ออกจาก **True Conflict (`conflict`)** |
| **Hallucination Guard** | ห้ามตอบ Fact ที่ไม่ได้อยู่ใน Grounded Context ด้วยการเดา | ต้องตอบ `unknown` เมื่อ Memory Chunk ขาด Fact สำคัญ |

---

## 3. Belief Revision & Conflict Resolution Matrix

| Case | Context Condition | Mandatory Model Output |
|---|---|---|
| **Case A: Single Verified Fact** | มี Fact จาก `[source=S1]` และไม่มีข้อขัดแย้ง | คำตอบ + `[source=S1]` |
| **Case B: Temporal / Authority Override** | `[source=S1 | t=100]` ขัดกับ `[source=S2 | t=250 | status=supersedes]` | ตอบตามค่าล่าสุด `S2` พร้อมระบุ `[source=S2]` (Override) |
| **Case C: Irreconcilable Conflict** | `[source=S1 | t=100]` ขัดกับ `[source=S2 | t=100]` โดยไม่มีกฏ Supersede | **ห้ามเลือกเดาข้างใดข้างหนึ่ง:** ต้องรายงาน `conflict` พร้อมระบุทั้ง `[source=S1, S2]` |
| **Case D: Missing Evidence** | Context มี Fact อื่นๆ แต่ไม่มี Fact ที่ถาม | ต้องตอบ `unknown` (Zero Hallucination) |

---

## 4. Phase 17 Security & Isolation Invariants

- **Zero Cross-Tenant Leakage:** Memory Retrieval และ Prompt Context Construction ต้อง Filter ตาม `tenant_id` เสมอ (มี Integration Test ยืนยัน 0% Cross-Tenant Spill)
- **PII Redaction Gate:** ห้ามข้อมูล PII ดิบ (ตามกฎ Phase 17) หลุดเข้า Training Replay Buffer หรือ Long-Term Memory Unredacted
- **No Unaudited Self-Write:** `ZyrquenModel` ไม่มีสิทธิ์เขียนทับ Ground Truth Memory Store โดยตรงหากไม่ผ่าน Verification & Provenance Logger

---

## 5. Mandatory Truthfulness Sections

### ASSUMPTIONS
- โครงสร้าง `phases/phase17.py` (ซึ่งห้ามแก้ไขโดยไม่ได้รับอนุมัติ) มี Interfaces พื้นฐานของ `MemoryStore` และ Tenant/PII Guard ที่ V12 จะเชื่อมต่อผ่าน Integration Adapter ในชั้น Application/Workflow

### OPEN DECISIONS
- **OD-V12-MEM-01:** รูปแบบ Retrieval Ranking ใน Stage 5 (Pure BM25/Lexical Deterministic vs Native Embedding Similarity ที่ผ่าน Verification) โดยต้องไม่มี External Embedding API

### NOT VERIFIED
- อัตรา Accuracy ในการแยก **Override** vs **Irreconcilable Conflict** บนบริบทยาวหลาย Turns ของ `ZyrquenModel` ยัง **NOT VERIFIED / NOT RUN**
- E2E Integration ระหว่าง `MemoryStore` (Phase 17) กับ `ZyrquenModel` Checkpoint จริงยัง **NOT RUN**
