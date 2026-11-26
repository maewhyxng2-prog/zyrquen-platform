# ZYRQUEN Ω∞ — V12 Tokenizer & Slot Specification

- **Document ID:** `V12-DOC-09`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Schema Version:** `SCHEMA_V2 = "zyrquen.tokenizer.v2"` (`apps/core/native/tokenizer.py`)
- **Tokenizer Type:** Native Byte-Level BPE (Train-Only Merges + Atomic Entity Slots)

---

## 1. Tokenizer Contract & Immutability Across 50,000 Steps

ตาม `apps/core/native/tokenizer.py`:
1. **Control Tokens (Fixed IDs `0..3`):**
   - `<pad>` (`0`), `<bos>` (`1`), `<eos>` (`2`), `<unk>` (`3`)
2. **Atomic Entity Slot Tokens (32 Slots):**
   - `<slot_0>` .. `<slot_31>` (`SLOT_COUNT = 32`)
   - **Rule:** Pre-tokenizer ต้องจับคู่ Slot Token เป็น 1 Atomic Unit เสมอ ห้ามถูก BPE Split เป็น `<`, `slot`, `_`, `0`, `>` เด็ดขาด เพื่อรักษา Involution/Permutation Invariance ของ Entity Binding (ป้องกัน **EL-05**)
3. **Train-Only BPE Merge Learning:**
   - BPE merges (`vocab_size = 2048` สำหรับ `V12-Tier0-Base` หรือ `4096` สำหรับ `V12-Tier0-Vocab`/`Tier1`) **ต้องเรียนรู้จาก `train.jsonl` ของ V12 (และคำศัพท์พื้นฐานของ Domain) เท่านั้น**
   - **ห้าม** ให้ `validation.jsonl`, `unseen.jsonl`, `ood.jsonl` เข้าสู่กระบวนการ `train_bpe(...)` โดยเด็ดขาด
4. **Tokenizer SHA-256 Pinning:**
   - เมื่อฝึก Tokenizer เสร็จก่อนเริ่ม Stage 1 (`Step 1`) ต้อง Pin ไฟล์ `tokenizer.json` ด้วย SHA-256 และ **ห้ามเปลี่ยน Tokenizer Vocab/Merges ตลอด `EXP-001..EXP-100`** ใน Lineage เดียวกัน

---

## 2. Normalization & SFT Separation

- **Whitespace & Unicode Hygiene:** ใช้ NFC Normalization และรักษา Whitespace Framing ของ `SFT_SEP = "\n### Response:\n"` แบบ Deterministic
- **Roundtrip Invariant:** `decode(encode(text)) == text` สำหรับ Printable UTF-8 และ Canonical Slot Strings
- **Slot Regex Continuity:** สืบทอด Slot Binding Policy จาก V11 (`TR_`, `VA_`, `TE_`, `UN_`, `OO_` prefix matching -> deterministic randomized permutation `<slot_0>..<slot_31>` ต่อตัวอย่าง) เพื่อไม่ให้ Entity Order รั่วข้อมูล Split หรือความถี่ตัวเลข Entity ID

---

## 3. Handling `SLOT_COUNT = 32` Capacity in Deep Multi-Hop (6–10+ Hops)

- สำหรับโจทย์ Stage 4 OOD Depth `6–10+ hops` และ Stage 5 Multi-Turn Memory Context:
  - จำนวน Distinct Entities ต่อ 1 Prompt+Answer Context ต้องไม่เกิน `32` Entities (เพื่อให้เพียงพอกับ `<slot_0>..<slot_31>` ภายใต้ `SCHEMA_V2`)
  - หาก Stage 4/5 ในอนาคตต้องการ Entity Count > 32 ต่อตัวอย่าง ต้องเปิด Decision Request ขยาย `SLOT_COUNT` **ก่อน** เริ่มสร้าง Lineage (ห้ามเปลี่ยน `SLOT_COUNT` กลางทางหลังเริ่มฝึก Stage 1 แล้ว)

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- Vocabulary Size `2048` หรือ `4096` เพียงพอสำหรับ Symbolic Reasoning, Planning DAG Tokens, Provenance Tags (`[source=...]`), และ Verification Labels โดยไม่ทำให้ Token-per-Example เกิน `max_seq_len=256..512`

### OPEN DECISIONS
- **OD-V12-TOK-01:** ตัดสินใจเลือก `vocab_size = 2048` (คงที่เทียบเท่า V10/V11-Base, `3.74M` params) หรือ `4096` (`4.26M` params) ตามผล Token Length Distribution บน Dataset V11/V12

### NOT VERIFIED
- ความยาว Sequence สูงสุด (Token Count) ของตัวอย่าง Stage 4 (10-hop Planning) และ Stage 5 (Memory + Conflict) เมื่อ Tokenize ด้วย `vocab_size=2048` vs `4096` ยัง **NOT VERIFIED**
