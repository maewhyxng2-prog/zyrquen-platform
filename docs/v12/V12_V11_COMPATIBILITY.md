# ZYRQUEN Ω∞ — V12 / V11 / V10 Compatibility & Lineage Policy

- **Document ID:** `V12-DOC-21`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Core Law:** Zero Modification to V7, V8, V9, V10, and V11 Artifacts; Additive Schema Evolution Only

---

## 1. Immutable Lineage Boundaries

| Version | Artifact Isolation Rule | Role During V12 |
|---|---|---|
| **V7, V8, V9** | **Strictly Frozen Forever** (`FROZEN_BASELINE_NAMES` / Historical Archives) | ห้ามแตะ ห้ามโหลดมาเขียนทับ ห้ามย้ายไฟล์ |
| **V10** | **Immutable Reference Baseline** (หลังผ่าน Runtime Closure Gate) | ใช้เป็น Reference Floor สำหรับ Anti-Regression Comparison ของทั้ง V11 และ V12 |
| **V11 (10K)** | **Immutable Prior Milestone Baseline** (หลังผ่าน V11 Final Gate) | ใช้เป็น Direct Baseline สำหรับเปรียบเทียบ V12 (`V12 vs V11`) และเป็นจุด Warm-Start ที่อาจเลือกใช้ตาม **OD-V12-02** |
| **V12 (50K)** | **Isolated Directory & Registry Lineage (`v12.*`)** | เก็บ Artifacts/Manifests/Logs ใน `artifacts/checkpoints/v12/` และ Lineage แยก |

---

## 2. Schema & API Backward Compatibility

1. **SFT Format (`zyrquen.sft.v1`):** คงรูปแบบ Prompt Framing และ `SFT_SEP = "\n### Response:\n"`, `IGNORE_INDEX = -100` เดิม 100%
2. **Tokenizer Schema (`zyrquen.tokenizer.v2`):** คง Control Tokens `0..3` และ `32` Atomic Slots `<slot_0>..<slot_31>`; หาก V12 ใช้ Warm-Start จาก V11 Final Weights **ต้องใช้ `tokenizer.json` ไฟล์เดียวกับ V11 (SHA-256 ตรงกัน)** ห้ามเปลี่ยน Vocab/Merges
3. **Dataset Manifest (`zyrquen.dataset-manifest.v1`):**
   - คงความเข้ากันได้กับ Consumer ที่อ่าน `train`, `validation`, `test` โดย Map Compatibility Adapter (`unseen` + `ood` -> Consolidated `test` view เฉพาะ Legacy Reporting พร้อมระบุ Breakdown 4 Splits เสมอ)
   - Additive Metadata Fields (`stage`, `sub_type`, `provenance`) ใช้ Optional Keys โดยไม่ทำลาย Legacy Parsers
4. **Model Registry (`apps/core/native/registry.py`):** V12 Records ต้องรองรับ `compare_versions(v12_id, v11_id)` และ `compare_versions(v12_id, v10_id)` ได้โดยตรง

---

## 3. Roadmap Phase 11–20 Immutability

- **ห้าม** แก้ไขหรือทำลาย Roadmap Phase 11–20 (`phases/phase11.py`..`phase20.py`)
- **ห้าม** สร้าง `Phase 21`
- Capability Enhancements ของ V12 ด้าน Epistemic Verification และ Memory/Tenant Isolation เป็นการ **Integrate เข้ากับ Phase 16 & 17 ที่มีอยู่** เพื่อส่งมอบความสามารถระดับ V12 ภายใน Roadmap ที่อนุมัติไว้แล้ว

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- V11 จะปิดงานด้วย `zyrquen.tokenizer.v2` และ `zyrquen.sft.v1` ที่รวม Slot Binding Regex (`TR`/`VA`/`TE`/`UN`/`OO`) เรียบร้อยแล้ว ทำให้ V12 สืบทอดสัญญาได้ทันทีโดยไม่ Break Backward Compatibility

### OPEN DECISIONS
- **OD-V12-CMP-01 (เชื่อมโยง OD-V12-02):** เลือก Warm-Start จาก `V11_10K_FINAL` (ต้อง Lock `vocab_size` และ `ModelConfig` เท่ากับ V11) หรือ Fresh Random Init `V12` Lineage (`v12.0-fresh`) เพื่อพิสูจน์ 50K Curve ตั้งแต่ Step 0

### NOT VERIFIED
- ความเข้ากันได้แบบ Runtime Load (`torch.load` / `ModelRegistry.compare_versions`) ระหว่าง Checkpoint จริงของ V10, V11 และ V12 ยัง **NOT VERIFIED / NOT RUN**
