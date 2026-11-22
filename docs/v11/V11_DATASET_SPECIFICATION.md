# ZYRQUEN Ω∞ — V11 Dataset Specification

- **Document ID:** `V11-DOC-07`
- **Status:** `BLUEPRINT ONLY — LOCKED UNTIL V10 FINAL GATE PASS`
- **Manifest Schema:** `zyrquen.dataset-manifest.v1` (`apps/core/native/dataset.py`)
- **Dataset Origin Policy:** 100% Deterministic Rule-Based / Exhaustive-Solver Verified Synthetic Generator (Pure Python stdlib); Zero External Unlicensed Corpora, Zero External LLM Synthetic Generation

---

## 1. Canonical 4-Split Evaluation Partition Architecture

เพื่อให้สอดคล้องกับทั้งข้อกำหนดการประเมิน 4 Splits (`train`, `validation`, `unseen`, `ood`) และโครงสร้าง Registry/Dataset เดิมของ V10:

| Split Name | File | Purpose | Entity Pool | Template Pool | Structural / Depth Rule |
|---|---|---|---|---|---|
| `train` | `train.jsonl` | Training + Train-loss monitoring เท่านั้น | `TR_E*`, `node_tr_*`, `item_tr_*`, `step_tr_*`, `rec_tr_e*` | Train templates only | Base training depths (e.g., 1–3 hops, base plan size 3–4 nodes) |
| `validation` | `validation.jsonl` | Hyperparameter tuning & Per-stage stopping gate | `VA_E*`, `node_va_*`, `item_va_*`, `step_va_*`, `rec_va_e*` | Validation templates only | In-distribution structural complexity with unseen entities |
| `unseen` | `unseen.jsonl` | Generalization test across completely unseen entities & phrasings | `UN_E*`, `node_un_*`, `item_un_*`, `step_un_*`, `rec_un_e*` | Unseen templates only | Same hop/depth complexity as train, 0 entity & 0 phrasing overlap |
| `ood` | `ood.jsonl` | Out-of-Distribution structural, depth & relation transfer | `OO_E*`, `node_oo_*`, `item_oo_*`, `step_oo_*`, `rec_oo_e*` | OOD templates only | Unseen relation verbs + higher hop depth (4–6 hops) + unseen abstract patterns (`SL-01`) |

*หมายเหตุ Compatibility:* สำหรับระบบเดิม (`ModelRegistry._verify_dataset` และ `dataset.py`) ที่ตรวจสอบคีย์ `("train", "validation", "test")` ใน `manifest["files"]`, ดูรายละเอียดแผนการเชื่อมใน [V11_INTEGRATION_CONTRACT.md](./V11_INTEGRATION_CONTRACT.md) และ [V11_V10_COMPATIBILITY.md](./V11_V10_COMPATIBILITY.md) (อาจสร้าง `test.jsonl` เป็น verified deterministic union ของ `unseen + ood` หรืออัปเดต `evaluation_splits` ใน V11 contract หลังผ่าน Gate)

---

## 2. Target Dataset Scale & Capability Mix (Baseline Blueprint)

ขยายจาก V10 (`600` ตัวอย่าง: `480 / 60 / 60`) เพื่อรองรับการฝึก `10,000` Steps (`batch_size=4` -> `40,000` example draws รวม replay/epochs) โดยไม่ Overfit ทันที:

| Capability | `train` | `validation` | `unseen` | `ood` | Total |
|---|---:|---:|---:|---:|---:|
| `abstract_reasoning` | `800` | `80` | `80` | `80` | `1,040` |
| `relational_generalization` | `800` | `80` | `80` | `80` | `1,040` |
| `ood_transfer` | `800` | `80` | `80` | `80` | `1,040` |
| `multi_step_planning` | `800` | `80` | `80` | `80` | `1,040` |
| `self_verification` | `800` | `80` | `80` | `80` | `1,040` |
| `knowledge_integration` | `800` | `80` | `80` | `80` | `1,040` |
| **Total** | **`4,800`** | **`480`** | **`480`** | **`480`** | **`6,240`** |

*หมายเหตุ:* จำนวน `4,800` train examples ที่ `batch_size=4` เท่ากับ `1,200` unique batches/epoch (เพียงพอให้รัน `10,000` steps ที่ `~8.3` epochs รวม curriculum replay แทนการวนซ้ำ ~83 epochs บนชุด 480 ตัวอย่าง)

---

## 3. Canonical JSONL Record Schema (`schema_version = "2.0"`)

```json
{
  "schema_version": "2.0",
  "dataset_version": "11.0.0",
  "example_id": "v11-tr-000001",
  "split": "train",
  "stage_tags": [1, 2, 6],
  "capability": "relational_generalization",
  "task_type": "directed_path_composition",
  "reasoning_operator": "exact_hop_reachability",
  "template_id": "RG_TR_01",
  "difficulty_level": "depth_3_distractor_2",
  "instruction": "...",
  "input": "...",
  "target": "TR_E014",
  "facts": [{"source": "TR_E001", "relation": "linked_to", "target": "TR_E005"}],
  "query": {"start": "TR_E001", "hops": 3},
  "answer": "TR_E014",
  "unique_answer_verified": true,
  "provenance": "deterministic_rule_solver_v11",
  "license": "internal-native-research",
  "metadata": {
    "hop_count": 3,
    "distractor_count": 2,
    "memory_grounded": false,
    "epistemic_labels": ["fact"]
  }
}
```

---

## 4. Mandatory Truthfulness Sections

### ASSUMPTIONS
- เครื่องสร้างข้อมูลแบบ Deterministic ใน Pure Python สามารถสร้าง `6,240` ตัวอย่างที่ผ่าน Unique-Answer Solver Verification ทั้งหมดภายในเวลาไม่กี่วินาทีบน CPU
- ความยาว `input + SFT_SEP + target` ของทุกตัวอย่างในทั้ง 4 Splits ยังคงพอดีภายใน `250` structural tokens (`<= 256` total tokens หลัง BPE + BOS/EOS)

### OPEN DECISIONS
- **OD-DS-01:** ขนาด `6,240` ตัวอย่าง (`800` per capability in train) เพียงพอสำหรับ `10,000` steps หรือควรเพิ่มเป็น `9,600` / `12,000` train examples
- **OD-DS-02:** รูปแบบการเก็บ Split `unseen` และ `ood` ใน `manifest.json` (เก็บเป็น 4 ไฟล์หลัก + symlink-free `test.jsonl` compatibility view หรือปรับ `SPLITS` tuple)

### NOT VERIFIED
- ยังไม่มีไฟล์ Dataset V11 ที่ถูกสร้างขึ้นจริงใน repo (`data/nagi_v11/` ยังไม่ถูกสร้าง)
- อัตราความสำเร็จของการ Generate ตัวอย่างที่ unique-answer ในระดับ 5–6 hops ภายใต้ข้อจำกัด `<= 250` structural tokens ยัง **NOT VERIFIED**
