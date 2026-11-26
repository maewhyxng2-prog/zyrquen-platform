# ZYRQUEN Ω∞ — V12 Dataset Specification

- **Document ID:** `V12-DOC-07`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Manifest Contract:** `zyrquen.dataset-manifest.v1` + V12 Provenance Extensions
- **Splits Contract:** Strictly 4 Disjoint Splits (`train`, `validation`, `unseen`, `ood`)

---

## 1. Dataset Design Philosophy for 50,000 Steps

การฝึก `50,000` Steps บนชุดข้อมูลเล็กหรือซ้ำซากจะทำให้โมเดล **จำตัวอย่าง (Memorization)** แทนการ **สรุปกฎ (Generalization)** ดังนั้น Dataset V12 ต้องมีขนาด ความหลากหลายทางโครงสร้าง (Structural Diversity) และกฎแยก Split ที่รัดกุมกว่า V11 อย่างมีนัยสำคัญ โดยข้อมูลทุกตัวอย่างต้องถูกสร้างจาก **Deterministic Formal Generators & Exact Solvers** ใน Repo เท่านั้น (ห้ามใช้ LLM ภายนอกสังเคราะห์คำตอบ)

---

## 2. Canonical 4-Split Architecture & Strict Boundaries

| Split | File Name | Purpose | Entity Pool | Template / Structure Constraint | Depth Constraint |
|---|---|---|---|---|---|
| **`train`** | `train.jsonl` | ใช้ปรับ Weights และฝึก Tokenizer BPE merges เท่านั้น | `TR_*` (`<slot_0>..`) | Canonical Training Templates | Base Depth (เช่น 1–4 hops) |
| **`validation`** | `validation.jsonl` | Early Stopping, Hyperparameter Selection & Per-Exp Mini-Eval | `VA_*` (Disjoint จาก Train) | Same Distribution with Train (แต่คนละ Fact Graphs) | Same Depth (1–4 hops) |
| **`unseen`** | `unseen.jsonl` | ทดสอบ **Entity & Combination Generalization** | `UN_*` (Disjoint จาก Train/Val) | New Entity Combinations & Paraphrased Templates | Base + Mid Depth (2–5 hops) |
| **`ood`** | `ood.jsonl` | ทดสอบ **Structural / Depth / Domain Shift OOD Transfer** | `OO_*` (Disjoint 100%) | Unseen Phrasing, Negated/Inverted Framing, Multi-Rule | **OOD Depth (6–10+ hops)** & Novel DAG Topologies |

---

## 3. Target Dataset Scale Across the 6 Training Stages (Blueprint Sizing)

| Stage / Track | `train` Target (Examples) | `validation` (Examples) | `unseen` (Examples) | `ood` (Examples) | Primary Sub-Types |
|---|---:|---:|---:|---:|---|
| **Stage 1: Native Representation** | `20,000` | `2,000` | `2,000` | `1,000` | Atomic Slot Binding, SFT Separator & EOS Termination, Basic 1–2 Hop Logic |
| **Stage 2: Knowledge Acquisition** | `35,000` | `3,000` | `3,000` | `1,500` | Provenance Facts (`[source=...]`), Attribute/Hierarchy Schemas, Noise-Filtered Recall |
| **Stage 3: Abstract & Relational** | `45,000` | `4,000` | `4,000` | `2,000` | Syllogism, Transitivity, Symmetry/Inverse, Conditional Rules + >=3 Distractors |
| **Stage 4: Planning & OOD Transfer** | `40,000` | `4,000` | `4,000` | `4,000` | Dependency DAG Planning, Precondition Chains, `impossible` Plans, 6–10 Hop Extrapolation |
| **Stage 5: Memory & Knowledge Int.** | `30,000` | `3,000` | `3,000` | `2,000` | Multi-turn Grounded Memory Context, Temporal Override vs Irreconcilable `conflict`, PII/Tenant Boundary |
| **Stage 6: Self-Verification & Joint** | `30,000` | `3,000` | `3,000` | `3,000` | `true`/`false`/`unknown`, `valid`/`invalid_*`, `fact`/`assumption`/`unverified`, All-Stage Audit |
| **V12 Combined Corpus (Unique)** | **`200,000`** | **`19,000`** | **`19,000`** | **`13,500`** | **Total Unique Pool: `251,500` Verified Examples** |

> **หมายเหตุสำคัญ:** ตัวเลข `251,500` ตัวอย่างถูกออกแบบให้เพียงพอที่จะป้องกันไม่ให้โมเดลวนเห็นตัวอย่างซ้ำมากเกินไป (Over-Epoching) ในช่วง `50,000` Steps (และสามารถ Generate แบบ Parametric Deterministically ภายใต้ Seed ที่แยกตาม Split ได้โดยไม่ใช้ Disk เกิน `DISK_RESERVE_GB`)

### 3b. Native Software Engineering Dataset Track (Cross-Stage Corpus Specification)

ข้อมูลสำหรับฝึกและประเมิน `CAP-SE-01..10` ต้องอยู่ในรูปแบบ **Executable Spec-to-App Bundles** ครอบคลุม 8 App Domains (Task Manager, Finance, E-Commerce, Education, Business/CRM, Dev Tools, IoT/Automation, Social/Messaging) โดยทุกตัวอย่างต้องประกอบด้วย:
1. **`requirement_spec` & `constraints`:** โจทย์ความต้องการ + Boundary Rules (เช่น Auth, DB Constraints, Budget/Error Handling)
2. **`reference_artifacts` (Verified By Execution, Not External LLMs):** Schema, API Spec, UI/Code Modules ที่รันผ่าน Deterministic Test Harness ใน Sandbox แล้ว 100%
3. **`executable_tests` (`unit`, `integration`, `security`):** ชุดทดสอบที่รันยืนยันผลจริงได้ — **ห้ามนำ Code Snippets ที่ไม่ผ่าน Compile/Test หรือ Scrape มาแบบไม่มี Execution Ground Truth เข้า Training Pool**
4. **Strict Split Isolation (`train` / `validation` / `unseen` / `ood`):** แยก App Templates, Domain Entities, Schema Layouts และ Debug Error Signatures ข้าม Split ชัดเจน (เช่น Train บน Task/Finance/Store/Edu และทดสอบ `ood` Transfer บน Business/IoT/Novel Schemas)
5. **Sizing Status (`TBD`):** จำนวนตัวอย่างของ Software Engineering Track จะกำหนดและผนวกรวมเข้าสมดุล Corpus **หลัง** สร้างและรัน Leakage + Sandbox Verification ของ Generator V12 ผ่านแล้วเท่านั้น (ไม่เดาตัวเลขลอยๆ)

---

## 4. Required Record Schema & Provenance

ทุกบรรทัดในไฟล์ `.jsonl` ต้องมีโครงสร้างสมบูรณ์ตามสัญญา:
```json
{
  "id": "v12_s3_unseen_000412",
  "split": "unseen",
  "stage": 3,
  "capability": "abstract_reasoning",
  "sub_type": "conditional_distractor_4hop",
  "prompt": "...",
  "completion": "...",
  "slot_binding": {"<slot_0>": "UN_E0194", "<slot_1>": "UN_E0411"},
  "provenance": {
    "generator": "v12_deterministic_solver",
    "generator_version": "1.0.0",
    "seed": 120300412,
    "sources": ["synthetic_formal_kb_s3"]
  },
  "record_sha256": "..."
}
```

---

## 5. Mandatory Truthfulness Sections

### ASSUMPTIONS
- `sft.py` และ `dataset.py` จะได้รับการอัปเดต **หลัง** V10 Runtime Closure และ V11 Approval เท่านั้น (ไม่แก้โค้ดในขั้น Blueprint นี้) เพื่อรองรับ Split `unseen`/`ood` และ Slot Regex `TR`/`VA`/`TE`/`UN`/`OO`
- พื้นที่ Disk สำหรับเก็บ JSONL + Tokenized Binary Cache ของ `~250K` ตัวอย่างประเมินเบื้องต้นว่าอยู่ในระดับ `~150–400 MB` (ต้องคำนวณและตรวจด้วย `WorkflowResourceGuard` จริงเมื่อสร้าง Dataset)

### OPEN DECISIONS
- **OD-V12-DAT-01:** สัดส่วน Epoch Target ของ `200,000` Train Examples กับ Batch Size x Steps ที่จะเลือกใช้จริงหลังได้ Benchmark Throughput ของ V11
- **OD-V12-DAT-02:** รูปแบบ Storage ของ Tokenized Dataset (Pre-tokenized `uint16` memory-mapped shard vs JSONL streaming) เพื่อประหยัด RAM บน CPU container

### NOT VERIFIED
- อัตราการใช้ Disk และ RAM จริงสำหรับ Dataset Pool ขนาด `251,500` ตัวอย่างยัง **NOT VERIFIED**
- Generator และ Exact Solver ของ V12 ยัง **ไม่ได้เขียนเป็น Source Code** (อยู่ในสถานะ Specification Only)
