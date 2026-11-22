# ZYRQUEN Ω∞ — V11 Data Quality & Leakage Prevention Specification

- **Document ID:** `V11-DOC-08`
- **Status:** `BLUEPRINT ONLY — LOCKED UNTIL V10 FINAL GATE PASS`
- **Auditor Inheritance:** ต่อยอดและยกระดับจาก `tools/audit_leakage_v10.py` (Read-Only Pure Stdlib Auditor)
- **Zero-Tolerance Policy:** หาก Gate ใด Gate หนึ่งล้มเหลว Auditor ต้องคืน Exit Code `1` และ `handle_data_verify_and_audit` ต้องยก `LeakageGateFailedError` (FAIL/BLOCKED ทันที ห้ามฝึกเด็ดขาด)

---

## 1. Mandatory Quality & Integrity Gates

| Gate ID | Scope | Exact Verification Rule | Failure Action |
|---|---|---|---|
| **INTEGRITY_MANIFEST** | `manifest.json` + all split `.jsonl` | ตรวจ `schema == "zyrquen.dataset-manifest.v1"`, ห้าม symlink/path traversal, ตรวจ SHA-256 รายไฟล์และ `content_sha256` รวม, ตรวจ `sources.*.license` และ `sources.*.sha256` | `BLOCKED` / Exit `1` |
| **SCHEMA_VALIDATION** | Every JSONL row | ตรวจ Required fields ครบทุก key, `record["split"] == split_name`, `record["target"] == record["answer"]`, `record["unique_answer_verified"] is True`, non-empty `provenance` & `license` | `FAIL` / Exit `1` |
| **UNIQUE_ANSWER** | Every reasoning example | รัน Independent Exhaustive Solver อิสระตาม `capability`: เช่น BFS/DP นับ reachable set == 1 (relational/ood), DAG closure check (abstract_reasoning), Kahn `len(ready) == 1` ทุกขั้น (planning), deterministic belief ledger (knowledge), claim/plan validator (self_verification) | `FAIL` / Exit `1` |
| **DL-01** | Duplicates & Empty Targets | Zero duplicate `example_id`; Zero duplicate exact `input` และ normalized `input` (whitespace/casefold) ทั้งภายในและข้าม split; Zero empty `target` | `FAIL` / Exit `1` |
| **SEQ_BUDGET** | Token length safety | โครงสร้างคำสั่ง + คำตอบ <= `250` structural tokens และหลัง tokenize ด้วย `ZyrquenTokenizer` + `encode_sft_pair` ต้อง `len(full_ids) - 1 <= max_seq_len (256)` 100% ของทุกตัวอย่าง | `FAIL` / Exit `1` |
| **PII_HYGIENE** | Memory & knowledge text | ตรวจด้วย pattern scanner (`dataset.py::redact_pii` patterns) + Phase 17 `EMAIL_RE`; ห้ามมีข้อมูลส่วนบุคคลจริงในตัวอย่างสังเคราะห์ | `FAIL` / Exit `1` |

---

## 2. Anti-Leakage Matrix (EL-01..EL-06, TL-01, SL-01) Across 4 Splits

| Leakage Layer | Cross-Split Boundaries Tested | Exact Invariant |
|---|---|---|
| **EL-01..EL-04 (Entity Pool Disjointness)** | `train` vs `validation` vs `unseen` vs `ood` | Intersection ของ Entity Pool ระหว่างคู่ split ใดๆ ต้องเท่ากับ `0` (`TR_*`, `VA_*`, `UN_*`, `OO_*` แยก prefix เด็ดขาด) |
| **EL-05 (Static Vocab Leak Guard)** | `tokenizer.json` vs `validation`/`unseen`/`ood` entities | `ZyrquenTokenizer.find_entity_leakage(eval_entities) == []` — ห้าม Entity จาก Eval Split ปรากฏใน BPE merges |
| **EL-06 (Eval Unseen Coverage)** | Every record in `validation`, `unseen`, `ood` | `100%` ของตัวอย่างประเมินต้องใช้ Entity ที่ไม่เคยปรากฏใน `train` และแต่ละ eval split มี distinct unseen entities `>= 40` |
| **TL-01 (Template & Phrasing Disjointness)** | `template_id` & `raw_phrasing_signature` | Zero overlap ของ `template_id` และ canonical phrasing signature ระหว่าง `train`, `validation`, `unseen`, `ood` |
| **SL-01 (Structural Pattern Disjointness)** | `recompute_abstract_pattern("ood_transfer" / all)` | สำหรับ `ood` split: Abstract graph/hop/pattern signature หลังแทน entity ด้วย `<E0>, <E1>, ...` ต้อง **ไม่ซ้ำ** กับ `train`, `validation`, หรือ `unseen` |

---

## 3. Data Tampering & Provenance Guardrails

1. Dataset generator ต้อง **ห้ามเขียนทับ** output directory ที่มีอยู่แล้วโดยพลการ (คงพฤติกรรม `gen_nagi_v10.py` fail if exists)
2. Auditor ต้องทำงานแบบ **Strictly Read-Only** ห้ามแก้ `manifest.json` หรือ split `.jsonl`
3. ทุกแหล่งข้อมูล (แม้เป็น synthetic generator) ต้องระบุ `license` และ `sha256` ของ generator script / spec เพื่อตรวจสอบย้อนกลับได้ใน `ModelRegistry` และ `TrainingOrchestrator.prepare()`

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- รูปแบบ Regex สำหรับ Entity Extraction (`ENTITY_PATTERNS`) ใน V11 จะเพิ่ม prefix สำหรับ `unseen` (`UN_E*`, `*_un_*`) และ `ood` (`OO_E*`, `*_oo_*`) ให้ตรงกับ `_V10_ENTITY_RE` / V11 slot regex ใน `sft.py`
- Unique-answer solver สำหรับ 4–6 hops OOD สามารถรันตรวจสอบภายในเวลาไม่เกินไม่กี่วินาทีต่อ 6,240 ตัวอย่าง

### OPEN DECISIONS
- **OD-DQ-01:** ใน `SL-01` จะบังคับ zero structural pattern overlap เฉพาะ `ood_transfer` + `ood` split หรือบังคับครอบคลุมทุก capability ใน `ood` split ด้วย
- **OD-DQ-02:** เกณฑ์ Tolerance ของ `SEQ_BUDGET` เมื่อใช้ BPE tokenizer ที่ฝึกใหม่ (ต้องตรวจสอบทั้ง structural token count `<= 250` และ actual BPE token count `<= 256`)

### NOT VERIFIED
- ยังไม่มี V11 Dataset Audit Run จริงให้ตรวจสอบ
- Edge cases ของ entity regex ที่อาจจับผิดพลาดบนคำศัพท์ภาษาอังกฤษ/สัญลักษณ์ใหม่ใน Stage 4 Grounded Memory ยัง **NOT VERIFIED**
