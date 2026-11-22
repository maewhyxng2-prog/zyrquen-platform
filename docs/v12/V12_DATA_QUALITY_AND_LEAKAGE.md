# ZYRQUEN Ω∞ — V12 Data Quality & Anti-Leakage Specification

- **Document ID:** `V12-DOC-08`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Audit Scope:** All 6 Stages (`251,500` records across `train`, `validation`, `unseen`, `ood`)
- **Zero-Tolerance Rule:** Leakage Violation เพียง 1 ตัวอย่าง = `BLOCKED / FAILED` สำหรับทั้ง Stage Dataset

---

## 1. Exhaustive Unique-Answer & Deterministic Solver Rules

1. **Exact Solver Verification:** ทุก Prompt ใน V12 ต้องผ่านตัวแก้สมการ/กราฟแบบ Exhaustive Search (BFS/DFS/SAT/Topological Check) เพื่อยืนยันว่า:
   - คำตอบถูกต้องตามตรรกะ 100% (ไม่มีคำตอบกำกวม)
   - กรณี `multi_step_planning` หากระบุว่าต้องมี Unique Topological Plan ต้องตรวจว่าไม่มีทางเลือกคู่ขนานที่ขัดแย้งกับการให้คะแนน หรือใช้ Set-Membership / Validator Verifier ที่ตรวจความถูกต้องของลำดับทุกแบบ
2. **No Silent Answer Copying:** คำตอบ (`completion`) ต้องไม่ปรากฏเป็นสตริงตรงๆ ในบริบทโดยไม่มีการคำนวณ/อ้างอิงที่จำเป็น (ยกเว้นโจทย์ Grounded Memory Fact Extraction ที่ตั้งใจทดสอบ Provenance Citation และต้องผ่าน Conflict/Distractor Masking)
3. **Sequence Budget Check:** ทุกตัวอย่างต้องมีความยาว Token รวม `<BOS> + prompt + SFT_SEP + completion + <EOS>` ไม่เกิน `max_seq_len` (`256` หรือ `512` ตาม Tier Config) เพื่อให้ `<EOS>` ไม่ถูก Truncate ทิ้ง

---

## 2. Leakage Taxonomy & Automated Guards (`EL-01..06`, `TL-01`, `SL-01`, `DL-01`)

| Code | Leakage Type | Detection Rule | Enforcement |
|---|---|---|---|
| **EL-01** | Entity ID Overlap Across Splits | `entities(train) ∩ entities(validation ∪ unseen ∪ ood) == ∅` | Hard Fail |
| **EL-02** | Cross-Stage Entity Contamination | Entity Pool ของ Stage Evaluation (`unseen`/`ood`) ห้ามปนใน Replay Mix ของ Stage อื่น | Hard Fail |
| **EL-03** | Relation-Pair Memorization | กราฟความสัมพันธ์ `(u, rel, v)` ที่ปรากฏใน `validation`/`unseen`/`ood` ห้ามมีโครงสร้าง Subgraph สมมูลใน `train` | Hard Fail |
| **EL-04** | Prefix Tag Leakage | Prefix `TR_`/`VA_`/`UN_`/`OO_` ห้ามหลุดเข้า Prompt Text ดิบ (ต้อง Normalize ผ่าน `<slot_i>` เท่านั้น) | Hard Fail |
| **EL-05** | Tokenizer Subword Entity Leakage | Tokenizer ห้ามเรียนรู้ Merge ของ Entity Names ใน `validation`/`unseen`/`ood` และ Slot `<slot_0>..<slot_31>` ต้องเป็น Atomic Token เดี่ยว | Hard Fail |
| **EL-06** | Answer Distribution / Shortcut Bias | ตรวจ Label Entropy ในแต่ละ Split (เช่น `true`/`false`/`unknown` หรือ `impossible` vs valid) เพื่อกันการเดาเสียงข้างมาก | Hard Fail |
| **TL-01** | Template Overlap in `ood` | Surface Templates ของ `ood` ต้องไม่มี Structural Signature ซ้ำกับ Templates ใน `train` | Hard Fail |
| **SL-01** | Sequence Truncation Leakage | ห้าม Truncate คำตอบหรือ `<EOS>` ออก ทำให้โมเดลประเมินบนคำตอบขาดช่วง | Hard Fail |
| **DL-01** | Exact / Near-Duplicate Record | SHA-256 และ Normalized Canonical Hash ระหว่าง Split ต้องไม่ซ้ำกัน (`0` collisions) | Hard Fail |
| **CL-01** | Source/Test Answer Memorization | ห้ามนำ Reference Solutions หรือ Test Assertions ของ `validation`/`unseen`/`ood` App Benchmarks ปะปนใน Train | Hard Fail |
| **CL-02** | Hidden Evaluation Test Isolation | Hidden Integration/Security Test Suites ต้องอยู่นอก Training & Tokenizer Corpus 100% | Hard Fail |
| **CL-03** | AST Structural Clone Detection | ห้ามใช้ App Code ที่มี AST Subtree Similarity สูงเกินเกณฑ์ข้าม `train` กับ `ood` Tasks | Hard Fail |

---

## 3. Multi-Stage Dataset Manifest Signing

ทุก Stage Dataset Bundle ต้องสร้าง `dataset_manifest.json` ที่บันทึก:
- File SHA-256 ของ `train.jsonl`, `validation.jsonl`, `unseen.jsonl`, `ood.jsonl`
- Generator Version, Seed Map ต่อ Split, Total Counts, Token Length Histogram (`p50`, `p95`, `max`)
- Leakage Audit Report Hash (`EL-01..06`, `TL-01`, `SL-01`, `DL-01` = `PASS` ทั้งหมด)
- **Prerequisite Before Training:** `handle_training_execute` ต้องเทียบ SHA-256 Manifest ก่อนเริ่มทุก Experiment ของ V12

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- `tools/audit_leakage_v10.py` จะถูกใช้เป็นแม่แบบในการสร้าง V12 Multi-Split Leakage Auditor (หลัง V10 Closure และ V11 Approval) โดยคงการตรวจสอบทุก Code ข้างต้น

### OPEN DECISIONS
- **OD-V12-DQL-01:** เกณฑ์ Quantitative Near-Duplicate Similarity Threshold (เช่น Jaccard / MinHash `<= 0.85` สำหรับ `ood` vs `train` surface prompts)

### NOT VERIFIED
- การทำงานจริงของ V12 Leakage Auditor กับข้อมูล `251,500` ตัวอย่าง ยัง **NOT VERIFIED / NOT RUN**
- อัตรา False-Negative ของ Slot Binding Check ในการตรวจจับ Hidden Shortcuts ยัง **NOT VERIFIED**
