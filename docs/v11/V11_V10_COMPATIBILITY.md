# ZYRQUEN Ω∞ — V11 & V10 Compatibility & Baseline Preservation

- **Document ID:** `V11-DOC-21`
- **Status:** `STAGE 1 CODE READINESS APPROVED (V10 CLOSED_FAIL IMMUTABLE BASELINE)`
- **Immutable Baselines:** `v7`, `v8`, `v9`, and closed `v10` (`CLOSED_FAIL` immutable reference)

---

## 1. Baseline Protection Rules (Zero Destructive Mutation)

1. **Zero Modification to Prior Tracks:**
   - ห้ามแก้ไขหรือลบไฟล์/ชุดข้อมูล/รายงาน/Checkpoints ของ `v7`, `v8`, `v9` และ `v10` (`tools/*v7*`, `*v8*`, `*v9*`, `*v10*`, `data/nagi_v10`, `checkpoints/nagi_v10`, `eval/nagi_v10`)
   - คงรายการ `FROZEN_BASELINE_NAMES = {"v7", "v8", "v9", "ZYRQUEN-v7", "ZYRQUEN-v8", "ZYRQUEN-v9"}` ใน `apps/core/native/registry.py` และปฏิบัติต่อ V10 Checkpoints/Reports (`CLOSED_FAIL`) ด้วยสถานะ Immutable ห้ามแก้/ห้าม Promote
2. **Separate Namespace for V11 Artifacts:**
   - Dataset: `data/nagi_v11/` (`dataset = "nagi_v11"`, `version = "11.0.0"`)
   - Checkpoints: `checkpoints/nagi_v11/`
   - Reports: `eval/nagi_v11/` (`zyrquen.v11.evaluation_report.v1`)
   - Registry Versions: จัดสรรผ่าน `ModelRegistry.reserve_next_native_version(major=11, ...)` (`ZYRQUEN-Native-11.MINOR.PATCH`) โดย **ไม่แก้ไข** weights หรือ record ของ V10 (หากระบุ `parent` ต้องตรวจว่า V10 artifact นั้นอยู่ใน registry จริงและไม่ถูกแก้ทับ)

---

## 2. Training Origin Policy: Random Init vs V10 Weight Continuation

ตามข้อบังคับหลัก:
- **Default V11 Training Origin:** **Random Initialization (`ZyrquenModel(cfg)`) ตั้งแต่ Step `0 -> 10,000`** โดยใช้ V10 (`CLOSED_FAIL`) เป็น **Immutable Evaluation Comparison Baseline** เพื่อพิสูจน์การเรียนรู้จากศูนย์บน Curriculum 6 Stages โดยห้ามอ้าง regression pass หากยังไม่มีรายงาน V10 ที่ตรวจ SHA-256 ครบถ้วน
- **V10 Checkpoints Role:** ทำหน้าที่เป็น **Immutable Reference Baseline** สำหรับเปรียบเทียบความก้าวหน้าในแต่ละ Capability (`abstract_reasoning` .. `knowledge_integration`) โดยไม่นำไปใช้ initialize หรือ promote แทน V11

---

## 3. Schema & API Backward Compatibility Matrix

| Interface | V10 Behavior | V11 Extension | Backward Compatibility Guarantee |
|---|---|---|---|
| `ZyrquenConfig` | `vocab_size=2048, max_seq_len=256, n_layers=4, n_heads=4, d_model=256, d_ff=704` | คง defaults เดิมทั้งหมด | `ZyrquenConfig.from_dict()` โหลด V10 checkpoints ได้ 100% |
| `ZyrquenTokenizer` | `zyrquen.tokenizer.v2` (`<slot_0>..<slot_31>`) | ใช้ `SCHEMA_V2` เดียวกัน | Tokenizer V10 และ V11 ใช้ loader/verify ตัวเดียวกัน |
| `sft.py` | `SFT_FORMAT_VERSION = "zyrquen.sft.v1"`, `SFT_SEP` | ขยาย `_ENTITY_RE` เป็น superset ของ V10 (`TR`/`VA`/`TE` + `UN`/`OO`) | อินพุต V10 ทุกตัวจับ slot ได้เหมือนเดิม 100% |
| `dataset.py` (`zyrquen.dataset-manifest.v1`) | Required `train`, `validation`, `test` | รองรับ `train`, `validation`, `unseen`, `ood` + `test` compatibility | Dataset V10 ยังโหลดและตรวจ SHA-256 ผ่าน `ModelRegistry` และ `EvaluationEngine` ได้เหมือนเดิม |
| `handle_evaluation_gate` | ตรวจ `v9` และ `v10` schemas | เพิ่ม branch สำหรับ `zyrquen.v11.evaluation_report.v1` | รายงาน V9 และ V10 ยังถูก Gate ตรวจตามกฎเดิมทุกข้อ |
| `ModelRegistry` | `registry.json` (`zyrquen.model-registry.v1`) | ใช้ Schema v1 เดิม; เพิ่ม optional metadata keys ใน `metrics`/`capabilities` | Registry records ของ V10 อ่าน/verify/compare ได้โดยไม่ต้อง migrate โครงสร้าง |

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- V10 จะผลิตอย่างน้อย 1 Baseline Evaluation Report และ Verified Model Snapshot ใน `ModelRegistry` ก่อนเริ่ม Gate 3 ของ V11
- การขยาย Regex ใน `apps/core/native/sft.py` เป็น strict superset (ไม่เปลี่ยนผลการ match ของ entity format เดิมใน V10)

### OPEN DECISIONS
- **OD-VC-01:** สำหรับ `manifest.json` ของ V11, จะสร้าง `test.jsonl` (เป็น verified deterministic combination ของ `unseen` + `ood`) ควบคู่กับ `unseen.jsonl` และ `ood.jsonl` เพื่อให้ V10 `ModelRegistry._verify_dataset` อ่านได้ทันทีโดยไม่ต้องแก้ logic เก่า หรืออัปเดต `_verify_dataset` ให้อ่าน `splits` list จาก manifest
- **OD-VC-02:** เมื่อ V10 ปิดแล้ว จะเพิ่ม `"v10"`, `"ZYRQUEN-v10"` (หรือเวอร์ชัน V10 ที่ปิดแล้ว) เข้าชุด Immutable/Frozen policy ใน Registry API ด้วยหรือไม่

### NOT VERIFIED
- ยังไม่มี V10 Trained Checkpoint และ Evaluation Metrics จริงใน workspace นี้ (เพราะ `torch` ยังไม่ติดตั้ง) สำหรับใช้เป็นจุดอ้างอิงเปรียบเทียบกับ V11
