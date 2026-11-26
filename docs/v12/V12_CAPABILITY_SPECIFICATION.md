# ZYRQUEN Ω∞ — V12 Capability Specification

- **Document ID:** `V12-DOC-04`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Core Capabilities:** 6 Verifiable Native Intelligence Domains + Cross-Stage **Native Software Engineering (`CAP-SE-01..10`)**
- **Verification Principle:** ทุกความสามารถต้องมี Deterministic Ground Truth, Formal Verification Rule หรือ Executable Sandbox Verification (`Compile / Unit / Integration / Hidden / Security`) — ห้ามใช้ Subjective Scoring หรือ LLM-as-a-Judge

---

## 1. Six Core Capability Domains & Stage Mapping

| ID | Capability | Primary Training Stages | Quantitative Scope in V12 (50K) | Primary Code / Eval Key |
|---|---|---|---|---|
| **CAP-01** | `abstract_reasoning` | Stage 1, 3, 6 | Deduction & Induction เชิงสัญลักษณ์ 2–5 hops, Negation, Conditional Rules, Distractor Filtering | `cap_abstract_reasoning_accuracy` |
| **CAP-02** | `relational_generalization` | Stage 1, 3, 6 | Multi-hop Family/Graph/Ordering Relations (Transitive, Symmetric, Inverse) บน Unseen Entities | `cap_relational_generalization_accuracy` |
| **CAP-03** | `ood_transfer` | Stage 4, 6 | Depth Extrapolation (6–10+ hops เมื่อ Train <= 4 hops), New Templates & Novel Relation Compositions | `cap_ood_transfer_accuracy` |
| **CAP-04** | `multi_step_planning` | Stage 4, 6 | Dependency DAG Action Ordering, Precondition Verification, Explicit `impossible` / Cycle Detection | `cap_multi_step_planning_accuracy` |
| **CAP-05** | `knowledge_integration` | Stage 2, 5, 6 | Grounded Acquisition จาก Provenance `[source=...]`, Conflict Detection & Latest-Valid Belief Revision | `cap_knowledge_integration_accuracy` |
| **CAP-06** | `self_verification` | Stage 5, 6 | Claim Audit (`true`/`false`/`unknown`), `fact`/`assumption`/`unverified` Separation (Phase 16), Plan Check | `cap_self_verification_accuracy` |

---

## 2. Canonical I/O Contract (Across All 6 Capabilities)

- **Prompt Framing:** ใช้ `SFT_FORMAT_VERSION = "zyrquen.sft.v1"` และตัวคั่น `SFT_SEP = "\n### Response:\n"` เสมอ
- **Entity Representation:** ใช้ Atomic Slots `<slot_0>..<slot_31>` แทนชื่อ Entity ดิบ เพื่อขจัด Tokenizer Subword Leakage (EL-05)
- **Strict Output Discipline:**
  - ไม่มีข้อความฟุ่มเฟือย, ไม่มี Preamble ของแชทบอท
  - ปิดท้ายคำตอบด้วย `<eos>` เสมอ (`eos_hit_rate` ต้องวัดทุก Evaluation)
  - ห้ามเดาคำตอบเมื่อหลักฐานไม่พอ: ต้องคืน `unknown` หรือ `conflict` หรือ `impossible` ตาม Canonical Label

---

## 3. Capability-Specific Acceptance Criteria (Blueprint Targets)

| Capability | Stage Exit Focus | Zero-Shortcut Validation Rule |
|---|---|---|
| **CAP-01 Abstract Reasoning** | Stage 3 (`Step 23,000`) | เปลี่ยน Variable Binding (`<slot_i>`) ต้องยังตอบถูก; สลับตำแหน่ง Premise + ใส่ Distractor >= 3 ข้อ ต้องไม่ตกหลุม Keyword Match |
| **CAP-02 Relational Generalization** | Stage 3 (`Step 23,000`) | ใช้ Entity Set ที่ไม่เคยอยู่ด้วยกันใน Train (`unseen`) และห้ามจำคู่ `(entity_a, entity_b)` |
| **CAP-03 OOD Transfer** | Stage 4 (`Step 33,000`) | ต้องทดสอบกับ Graph/Reasoning Depth ที่ลึกกว่า Distribution ใน Train (`>= 6 hops`) และ Phrasing ใหม่ที่ไม่เคยฝึก |
| **CAP-04 Multi-step Planning** | Stage 4 (`Step 33,000`) | ตรวจ Topological Validity + Precondition Satisfaction ผ่าน Exact Simulator และตรวจจับกรณี `impossible` ที่ทำไม่ได้จริง |
| **CAP-05 Knowledge Integration** | Stage 5 (`Step 41,000`) | แยกให้ออกระหว่าง **Update/Override** (Timestamp/Authority ชัดเจน) กับ **Irreconcilable Conflict** (`conflict`) และอ้างอิง `[source=...]` ถูกต้อง |
| **CAP-06 Self-Verification** | Stage 6 (`Step 50,000`) | False Claim Acceptance Rate ต้องลดลงเทียบกับ Stage 1–4 และต้องไม่เปลี่ยนคำตอบถูกเป็นผิด (Calibration Retention) |

---

## 3b. Cross-Stage Native Software Engineering & Autonomous Application Development (`CAP-SE-01..10`)

เพื่อรองรับ Dual Mission ของ ZYRQUEN Ω∞ ทั้งด้าน **Native General Intelligence (NGI)** และ **Native Software Engineering & Autonomous Application Development** ชุดความสามารถ `CAP-SE-01..10` ถูกบูรณาการเป็น **Cross-Stage Capability** ภายในโครงสร้าง **6 Stages เดิม (`50,000` Cumulative Steps)** โดยไม่สร้าง Stage 7 และไม่ขยายงบ Steps

### 8 Target Application Domains

| Domain ID | Application Domain | Representative Functional Scope |
|---|---|---|
| **APP-DOM-01** | **Task Management** | Tasks, Calendar Scheduling, To-do Lists, Kanban/Project Management |
| **APP-DOM-02** | **Finance & Accounting** | Expense Tracker, Budgeting, Invoices, Deterministic Ledger & Summaries |
| **APP-DOM-03** | **E-Commerce & Storefront** | Product Catalog, Cart State, Checkout Rules, Order Lifecycle |
| **APP-DOM-04** | **Education & Learning** | Courses, Quizzes, Progress Tracking, Adaptive Study Planner |
| **APP-DOM-05** | **Business & Operations** | CRM, Inventory Control, Reporting, Analytics Dashboards |
| **APP-DOM-06** | **Developer & Engineering Tools** | Code Inspector, API Contract Tester, Schema Viewer, Debug Console |
| **APP-DOM-07** | **Automation & IoT Control** | Rule Triggers, State Machines, Safe Device/Workflow Controllers |
| **APP-DOM-08** | **Social & Messaging Systems** | Feeds, Threaded Discussions, Permission-Bounded Messaging |

### 10 Verifiable Software Engineering Capabilities (`CAP-SE-01..10`)

| ID | Capability | Primary Training Stages | Quantitative Scope in V12 (Cross-Stage within 50K) | Deterministic Executable Verification Key |
|---|---|---|---|---|
| **CAP-SE-01** | `requirement_engineering` | Stage 2, 4, 6 | แปลง Natural Language Brief -> Structured Spec, Acceptance Criteria & Edge Cases | `se_spec_completeness_rate` |
| **CAP-SE-02** | `system_architecture` | Stage 3, 4, 6 | ออกแบบ Module Boundaries, Data Flow & Dependency Graph ที่ไม่ขัดแย้งกัน | `se_architecture_consistency_rate` |
| **CAP-SE-03** | `ui_ux_engineering` | Stage 1, 3, 6 | โครงสร้าง State, Navigation, Accessible Form/Layout Contracts (ต้องผูก State จริง) | `se_ui_contract_pass_rate` |
| **CAP-SE-04** | `native_code_generation` | Stage 1, 3, 4, 6 | Multi-file TypeScript/Python/SQL Code Generation ที่ Build และ Type-check ผ่านจริง | `se_compile_pass_rate` |
| **CAP-SE-05** | `database_engineering` | Stage 2, 3, 6 | Relational Schema, Constraints, Migrations & Parameterized Queries | `se_schema_integrity_rate` |
| **CAP-SE-06** | `api_engineering` | Stage 3, 4, 6 | Typed Endpoints, Validation Schemas, Status Codes & Error Handling | `se_integration_test_pass_rate` |
| **CAP-SE-07** | `software_testing` | Stage 4, 5, 6 | สร้างและรัน Unit / Integration / E2E Assertions ที่จับ Bug จริงได้ | `se_unit_and_hidden_pass_rate` |
| **CAP-SE-08** | `debugging_and_repair` | Stage 4, 5, 6 | Fault Localization จาก Compiler/Test Trace และสร้าง Patch โดยไม่เกิด Regression | `se_repair_pass_rate` |
| **CAP-SE-09** | `security_engineering` | Stage 5, 6 | RBAC/Auth Enforcement, Input Sanitization, Zero SQLi/XSS/Path Traversal/Secrets | `se_security_audit_pass_rate` |
| **CAP-SE-10** | `delivery_verification` | Stage 5, 6 | Reproducible Build Manifest, Env Template & Rollback Readiness (Gated Deployment) | `se_build_packaging_pass_rate` |

- **Mandatory Executable Ground-Truth Rule:** การสร้างเพียง UI Mockup หรือโค้ดที่อ่านดูสวยแต่ไม่ผ่าน Build/Test **ถือว่า `FAILED` ทันที** — ทุก Application Task ต้องถูกตรวจผ่าน Sandbox จริงครบ 5 ด่าน: **Compile -> Unit -> Integration -> Hidden Tests -> Security Checks**

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- เกณฑ์ Exact-Match และ Executable Pass Rate ขั้นต่ำเชิงตัวเลข (ทั้ง `CAP-01..CAP-06` และ `CAP-SE-01..10`) จะถูกล็อกเป็นตัวเลขทางการหลังได้รับ **V10 Runtime Baseline** และ **V11 10K Final Baseline** แล้ว เพื่อไม่ให้ตั้งตัวเลขลอยๆ โดยขาดฐานอ้างอิง

### OPEN DECISIONS
- **OD-V12-CAP-01:** การกำหนด Threshold เชิงตัวเลขของแต่ละ Capability (`min_unseen_accuracy`, `min_ood_accuracy`, `min_se_hidden_pass_rate`) หลังเห็น V11 Stage 6 Actual Metrics
- **OD-V12-CAP-02:** รูปแบบ Exact Partial-Credit Metric สำหรับ `multi_step_planning` (ควบคู่กับ Strict Exact Sequence Match) เมื่อแผนถูกต้องได้หลาย Topological Orders

### NOT VERIFIED
- ความสามารถจริงของ `ZyrquenModel` ในทุก `CAP-01..CAP-06` และ `CAP-SE-01..10` บน `50,000` Steps ยัง **NOT VERIFIED / NOT RUN**
- อัตราความสำเร็จบน OOD Depth `6–10+ hops` และ End-to-End Multi-File App Build สำหรับโมเดลขนาด `<= 5M` ยัง **NOT VERIFIED**

