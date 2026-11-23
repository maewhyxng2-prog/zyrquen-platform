# ZYRQUEN Ω∞ — V11 Tokenizer & Vocabulary Specification

- **Document ID:** `V11-DOC-09`
- **Status:** `STAGE 1 CODE READINESS APPROVED (V10 CLOSED_FAIL BASELINE POLICY — TRAINING & PROMOTION LOCKED)`
- **Implementation Module:** `apps/core/native/tokenizer.py` (`ZyrquenTokenizer`, Pure Python Standard Library)
- **Canonical Schema:** `SCHEMA_V2 = "zyrquen.tokenizer.v2"`

---

## 1. Special & Atomic Slot Token Layout (Verified in `tokenizer.py`)

`ZyrquenTokenizer(schema="zyrquen.tokenizer.v2")` จอง IDs ด้านหน้าแบบตายตัวและรักษาความเป็น Atomic (ไม่แยก BPE และไม่นำเข้า BPE merges):

| Token ID Range | Count | Token Symbols | Purpose |
|---|---:|---|---|
| `0 – 3` | `4` | `<|pad|>`, `<|bos|>`, `<|eos|>`, `<|unk|>` | Control tokens (`pad_id=0`, `bos_id=1`, `eos_id=2`, `unk_id=3`) |
| `4 – 35` | `32` | `<slot_0>` .. `<slot_31>` | Atomic ephemeral entity slots (`SLOT_COUNT = 32`) |
| `36 – 291` | `256` | Raw UTF-8 Bytes (`byte_offset=36`, byte `b -> 36 + b`) | Lossless Unicode byte fallback (รองรับไทย/อังกฤษ/สัญลักษณ์โดยไม่มี `<unk>` collapse) |
| `292 – (V-1)` | `V - 292` | Learned BPE merges (เฉพาะ `pair count >= 2`) | Subword structural/operator compression |

- **Base Minimum Vocab:** `292` (`36 + 256`)
- **Recommended V11 Baseline Vocab Sizes:** `2048` (สำหรับ `V11-Tier0-Default` / `V11-Tier0-Deep6L`) หรือ `4096` (สำหรับ `V11-Tier0-Vocab4096` หลังวัดอัตราการบีบอัด sequence length)

---

## 2. Training & Slot-Safe Vocabulary Construction (`EL-05` Enforcement)

1. **Train-Only BPE Training:** ฝึกผ่าน `apps/core/native/sft.py::train_slot_safe_tokenizer(train_records, vocab_size, schema=SCHEMA_V2, use_slots=True, forbidden_entities=...)` เท่านั้น
2. **Pre-Substitution Before Merge Counting:** ก่อนนับ BPE pairs ทุกตัวอย่างใน `train` จะถูกแทน surface entity (`TR_E*`, etc.) ด้วย `<slot_k>` ผ่าน `bind_ephemeral_slots(..., permute_slots=False)` เพื่อให้ BPE เรียนรู้โครงสร้างประโยค ตัวดำเนินการ (`linked_to`, `>`, `after`, `update:`, `[source=...]`) โดย **ไม่จำชื่อ Entity**
3. **Zero Evaluation Entity Leakage:** บังคับรัน `tok.find_entity_leakage(val_entities | unseen_entities | ood_entities)` หลังฝึก Tokenizer — หากพบตัวใดหลุดเข้า BPE pieces ให้ Reject ทันที
4. **NFC Normalization:** `normalize(text) = unicodedata.normalize("NFC", text)` ทำให้อักขระไทยและ Unicode round-trip อย่างสมบูรณ์

---

## 3. Ephemeral Slot Binding & Restoration Rules

- **Regex Update Note for V11:** ปัจจุบัน `_V10_ENTITY_RE` ใน `apps/core/native/sft.py` จับ `(TR|VA|TE)_E...`, `(node|item|step)_(tr|va|te)_...`, `rec_(tr|va|te)_e...` — เมื่อเปิด V11 (หลัง V10 Gate ผ่าน) จะต้องขยาย pattern ให้รองรับ Entity Prefix ของ `unseen` (`UN_E*`, `*_un_*`) และ `ood` (`OO_E*`, `*_oo_*`) ในที่เดียว (`sft.py`) และซิงก์กับ Auditor
- **Slot Capacity Guard:** ตัวอย่างใดที่มี distinct entities เกิน `SLOT_COUNT = 32` จะถูก Reject ด้วย `ValueError` เพื่อกัน silent collision
- **Inference Alignment:** ทั้ง `NativeInferenceEngine`, `StreamingInferenceEngine`, และ `EvaluationEngine` ต้องใช้ `tokenizer.fingerprint()` เดียวกับที่ฝังใน checkpoint (`tokenizer_sha256`)

---

## 4. Integrity & Versioning Contract

- ไฟล์ `tokenizer.json` เก็บ `"schema"`, `"version"`, `"normalization": "NFC"`, `"special_tokens"`, `"vocab_size"`, `"merges"`, และ `"sha256"` (`tok.fingerprint()`)
- `ZyrquenTokenizer.load()` ปฏิเสธการโหลดทันทีหาก `special_tokens`, `vocab_size`, หรือ `sha256` ไม่ตรงกับเนื้อหา
- `VersionedCheckpointManager` และ `ModelRegistry` บังคับให้ทุก Checkpoint ผูก `tokenizer_sha256` แบบถาวร

---

## 5. Mandatory Truthfulness Sections

### ASSUMPTIONS
- `32` atomic slots (`<slot_0>..<slot_31>`) เพียงพอสำหรับกราฟเหตุผลและแผนงานในหน้าต่าง `max_seq_len = 256` ของ V11
- Structural vocabulary `<= 2048` โทเคนเพียงพอให้ทุกตัวอย่าง (รวม 4–6 hops OOD) มีความยาว BPE token `<= 256`

### OPEN DECISIONS
- **OD-TK-01:** เลือก `vocab_size = 2048` (ประหยัด ~524K params เพื่อให้มีงบไปเพิ่ม Layer เป็น 6L ใต้ 5M) หรือ `vocab_size = 4096`
- **OD-TK-02:** จะใช้ Tokenizer ใบเดียวที่ฝึกจาก V11 `train` split ร่วมกันทั้ง 6 Stages หรือ Freeze ตั้งแต่วันที่ Dataset V11 ล็อก (แนะนำให้ **Freeze จาก V11 `train` split ตั้งแต่ก่อนเริ่ม Stage 1** เพื่อไม่ให้ `tokenizer_sha256` เปลี่ยนระหว่าง Stage 1–6)

### NOT VERIFIED
- อัตราการบีบอัด (Tokens-per-Example Distribution) ของชุดข้อมูล V11 (6,240 ตัวอย่าง) ด้วย `vocab_size = 2048` vs `4096` ยัง **NOT VERIFIED**
- การทำงานร่วมกันของ `bind_ephemeral_slots` ใน API Streaming Chat path (`apps/core/streaming.py`) ยังไม่ได้ถูกทดสอบครบกับ V11 prompts
