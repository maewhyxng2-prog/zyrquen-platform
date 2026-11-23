# ZYRQUEN Ω∞ — V11 Dataset Specification

- **Document ID:** `V11-DOC-07`
- **Status:** `STAGE 1 CODE READINESS APPROVED (V10 CLOSED_FAIL BASELINE POLICY — TRAINING & PROMOTION LOCKED)`
- **V10 Baseline & Scope Note:** V10 Static/Architecture/Governance/Hook audits (`V10-A`..`V10-D`) passed, and V10 closed as `FAIL`. Per Tier-2 Gate Transition Approval, V10 remains an immutable `CLOSED_FAIL` baseline while Stage 1 4-split dataset adapter/audit readiness (`dataset.py`, `sft.py`, `registry.py`, `groups.py`) is enabled. No training or promotion is authorized here.
- **Scope Clarification (V11 vs Existing `phases/phase11.py`):** Existing `phases/phase11.py` implements immutable Workspace Intelligence helpers (no training/DB). This specification governs **ZYRQUEN Native Model v11** (`data/nagi_v11/`, `dataset = "nagi_v11"`, `version = "11.0.0"`) for the 10,000-step NGI objective without modifying `phases/phase11.py`–`phase20.py`.
- **Manifest Schema:** `zyrquen.dataset-manifest.v1` (`apps/core/native/dataset.py`)
- **Dataset Origin Policy:** 100% Deterministic Rule-Based & Exhaustive-Solver Verified Generator (Pure Python stdlib); Zero External Unlicensed Corpora, Zero External AI APIs

---

## 1. Canonical 4-Split Isolation Architecture

เพื่อวัดผลแยกขาดระหว่าง **Optimization on Train**, **In-Distribution Validation**, **Entity/Template Generalization (`unseen`)**, และ **Structural/Depth/Relation Transfer (`ood`)**, ชุดข้อมูล V11 แยกเป็น 4 Splits โดยบังคับ Disjointness ทุกชั้น (ดู [V11_DATA_QUALITY_AND_LEAKAGE.md](./V11_DATA_QUALITY_AND_LEAKAGE.md)):

| Split Name | File | Entity Prefix Pool | Template Pool (`TL-01`) | Structural & Complexity Role | Counts toward Release Gate? |
|---|---|---|---|---|---|
| **`train`** | `train.jsonl` | `TR_E*`, `node_tr_*`, `item_tr_*`, `step_tr_*`, `rec_tr_e*` | `*_TR_*` only | Base training distribution across 6 capabilities (1–3 hops, base plan/memory graphs) | Diagnostic only (ห้ามใช้อ้าง PASS) |
| **`validation`** | `validation.jsonl` | `VA_E*`, `node_va_*`, `item_va_*`, `step_va_*`, `rec_va_e*` | `*_VA_*` only | In-distribution depth/structure with **0% entity/template overlap**; Stage exit gates & LR checks | **Yes (Stage & Final Gates)** |
| **`unseen`** | `unseen.jsonl` | `UN_E*`, `node_un_*`, `item_un_*`, `step_un_*`, `rec_un_e*` | `*_UN_*` only | Matched structural complexity to `train`/`validation`, แต่ Entity + Phrasing ไม่เคยปรากฏเลย | **Yes (Mandatory Stage Exit & Final Gate)** |
| **`ood`** | `ood.jsonl` | `OO_E*`, `node_oo_*`, `item_oo_*`, `step_oo_*`, `rec_oo_e*` | `*_OO_*` only | **Out-of-Distribution shift (`SL-01`):** higher hop depth (`4–6 hops`), unseen relations, larger distractor fan-out, novel graph patterns | **Yes (Mandatory Final & OOD Transfer Gate)** |

*Compatibility Bridge with Closed V10 Contracts (`ModelRegistry._verify_dataset`, `dataset.py`, `sft.py`):*
1. **Path & Provenance Security (ปิดแล้วใน V10-A):** ทั้ง generator และ dataset validator ต้องคงข้อกำหนดห้าม symlink บน `dataset_dir`, `manifest.json` และ `<split>.jsonl`, ตรวจ `is_relative_to` path containment, และระบุ `"sources"` (`path`, `license`, `sha256`) ใน `manifest.json` เพื่อผ่าน `TrainingOrchestrator.prepare()`
2. **4-Split Compatibility:** `ModelRegistry._verify_dataset` และ `dataset.py::SPLITS` ปัจจุบันตรวจ `("train", "validation", "test")` — เมื่อ V11 เปิดใช้งานจะขยายผ่าน Compatibility Adapter (`V11_INTEGRATION_CONTRACT.md` / `V11_V10_COMPATIBILITY.md`) ให้รองรับ `splits: ["train", "validation", "unseen", "ood"]` ร่วมกับ `test.jsonl` archive
3. **Ephemeral Slot Regex Alignment (`apps/core/native/sft.py`):** `_V10_ENTITY_RE` ปัจจุบันจับเฉพาะ prefix `TR`/`VA`/`TE` (`_tr_`/`_va_`/`_te_`) — ในเฟสเปิด V11 ต้องขยาย pattern ให้ครอบคลุม `UN`/`OO` (`_un_`/`_oo_`) ด้วย เพื่อให้ `bind_ephemeral_slots()` แทนค่า `<slot_0>..<slot_31>` ได้ตรงกันทั้ง `train`, `validation`, `unseen` และ `ood` (ไม่เช่นนั้น Entity ใน `unseen`/`ood` จะหลุดเป็น raw BPE tokens)

---

## 2. Dataset Volume & Capability Distribution (`6,240` Examples Baseline)

ขยายขนาดจาก V10 (`600` ตัวอย่าง: `480 / 60 / 60`) เพื่อรองรับ **10,000-Step Objective** (`batch_size = 4` → `40,000` sample draws ตลอด 6 Stages) โดยลดความเสี่ยงการท่องจำซ้ำซาก:

| Capability | `train` | `validation` | `unseen` | `ood` | Total | Target Token Budget (`max_seq_len = 256`) |
|---|---:|---:|---:|---:|---:|---|
| **`abstract_reasoning`** | `800` | `80` | `80` | `80` | `1,040` | `<= 250` structural / `<= 256` BPE+BOS/EOS |
| **`relational_generalization`** | `800` | `80` | `80` | `80` | `1,040` | `<= 250` structural / `<= 256` BPE+BOS/EOS |
| **`ood_transfer`** | `800` | `80` | `80` | `80` | `1,040` | `<= 250` structural / `<= 256` BPE+BOS/EOS |
| **`multi_step_planning`** | `800` | `80` | `80` | `80` | `1,040` | `<= 250` structural / `<= 256` BPE+BOS/EOS |
| **`self_verification`** | `800` | `80` | `80` | `80` | `1,040` | `<= 250` structural / `<= 256` BPE+BOS/EOS |
| **`knowledge_integration`** | `800` | `80` | `80` | `80` | `1,040` | `<= 250` structural / `<= 256` BPE+BOS/EOS |
| **Total** | **`4,800`** | **`480`** | **`480`** | **`480`** | **`6,240`** | **100% under `256` window** |

---

## 3. Detailed Specification: `abstract_reasoning` Dataset

### 3.1 Formal Task Definition
`abstract_reasoning` ทดสอบความสามารถในการสร้าง **Transitive Partial/Strict Order Graph** ภายในบริบท แล้วอนุมานความสัมพันธ์ระหว่างคู่ Entity เป้าหมาย โดยไม่หลงกล Distractor Edges, การสลับลำดับประโยค (Shuffled Premises), หรือความสัมพันธ์ที่กลับทิศ (Inverse Query)

### 3.2 Split-by-Split Progression Matrix (`abstract_reasoning`)

| Parameter | `train` (`n=800`) | `validation` (`n=80`) | `unseen` (`n=80`) | `ood` (`n=80`) |
|---|---|---|---|---|
| **Graph Nodes** | `3 – 5` nodes | `4 – 5` nodes | `4 – 5` nodes | `6 – 9` nodes |
| **Reasoning Chain Hops** | `1 – 3` hops | `2 – 3` hops | `2 – 3` hops | **`4 – 6` hops** |
| **Distractor Edges** | `1 – 2` disconnected/side edges | `2` side branches | `2 – 3` side branches | **`3 – 4` multi-branch distractors** |
| **Edge Order in Prompt** | Shuffled deterministically | Shuffled deterministically | Shuffled deterministically | Adversarially shuffled (reverse chain order biased) |
| **Relation Operators** | `greater_than` (`>`); optional `equal_to` (`=`, gated by `OD-CS-01`) | Same operators, unseen `VA_*` entities & `AR_VA_*` phrasings | Same operators, unseen `UN_*` entities & `AR_UN_*` phrasings | Longer mixed transitive chains + inverse direction queries (`B ? A` when chain gives `A -> ... -> B`) |
| **Target Label Mix** | ~40% `>`, ~40% `<`, ~20% `unknown` (หรือ ~30/30/20/20 ถ้าเปิด `=`) | Balanced across labels | Balanced across labels | Balanced across labels (`unknown` tested on disconnected multi-component graphs & parallel incomparable branches) |

### 3.3 Sub-Type Mix & Anti-Shortcut Controls (`abstract_reasoning`)
เพื่อไม่ให้โมเดลใช้ Statistical Shortcuts ใน `abstract_reasoning` (เช่น เดา `>` เมื่อ chain เรียงจากซ้ายไปขวา หรือเดา `unknown` จากจำนวน edge น้อย):
1. **Forward vs Inverse Query Parity (`50% / 50%`):** ครึ่งหนึ่งถาม `left ? right` ตามทิศ chain จริง และอีกครึ่งถามกลับทิศ `right ? left` เพื่อให้ label `>` และ `<` สมดุลแม้โครงสร้างกราฟเหมือนกัน
2. **Hard Negative `unknown` Graphs:** ตัวอย่างคำตอบ `unknown` ต้องมี edge count และ node count ใกล้เคียงตัวอย่าง `>`/`<` โดยมีทั้งกรณี disconnected components (เช่น 2 โซ่แยกกัน) และกรณี incomparable branches จาก root เดียวกัน (diamond/fork: `A > B`, `A > C`, query `B ? C` -> `unknown`)
3. **Adversarial Edge Ordering in `ood`:** ประโยคข้อเท็จจริงใน `ood` ถูกสับลำดับแบบ reverse-topological หรือ interleaved กับ distractor branches เพื่อป้องกัน positional shortcut

### 3.4 Exhaustive Solver & Unique-Answer Guarantee
ต่อยอดจาก `tools/gen_nagi_v10.py::solve_order_dag`:
1. **Acyclicity Check (3-Color DFS):** ปฏิเสธกราฟที่มี Cycle ทันที (กรณี Cycle ถูกแยกไปทดสอบใน `knowledge_integration` หรือ `multi_step_planning` เพื่อไม่ให้ label ปนเปกัน)
2. **Transitive Reachability Closure:** คำนวณ `reachable(left, right)` และ `reachable(right, left)` (รวม equivalence class closure หากเปิด `=`)
3. **Uniqueness Invariant:** คำตอบต้องเป็น singleton ใน `{">", "<", "=", "unknown"}` เท่านั้น ตัวอย่างที่ `left == right` หรือเกิด contradiction ระหว่างสร้างจะถูก Discard ทันที
4. **Anti-Shortcut Balancing:** สัดส่วนคำตอบ `>`, `<`, `unknown` ถูกบังคับให้สมดุล เพื่อป้องกัน Majority-Class Guessing

### 3.5 Concrete JSONL Record Example (`abstract_reasoning` — `ood` Split)

```json
{
  "schema_version": "2.0",
  "dataset_version": "11.0.0",
  "example_id": "v11-oo-ar-0001",
  "split": "ood",
  "stage_tags": [6],
  "capability": "abstract_reasoning",
  "task_type": "transitive_order_inference",
  "reasoning_operator": "acyclic_dominance_closure",
  "template_id": "AR_OO_03",
  "difficulty_level": "hops_5_distractors_3_inverse",
  "instruction": "Infer the dominance symbol linking the queried pair from the acyclic ordering graph.",
  "input": "FACTS: OO_E0104 > OO_E0105; OO_E0107 > OO_E0108; OO_E0102 > OO_E0103; OO_E0101 > OO_E0102; OO_E0103 > OO_E0104; OO_E0105 > OO_E0106 | QUERY: compare OO_E0106 ? OO_E0101",
  "target": "<",
  "facts": [
    {"source": "OO_E0104", "relation": "greater_than", "target": "OO_E0105"},
    {"source": "OO_E0107", "relation": "greater_than", "target": "OO_E0108"},
    {"source": "OO_E0102", "relation": "greater_than", "target": "OO_E0103"},
    {"source": "OO_E0101", "relation": "greater_than", "target": "OO_E0102"},
    {"source": "OO_E0103", "relation": "greater_than", "target": "OO_E0104"},
    {"source": "OO_E0105", "relation": "greater_than", "target": "OO_E0106"}
  ],
  "query": {"left": "OO_E0106", "right": "OO_E0101", "expected_hops": 5, "inverse": true},
  "answer": "<",
  "unique_answer_verified": true,
  "provenance": "deterministic_rule_solver_v11",
  "license": "internal-native-research",
  "metadata": {"hop_count": 5, "distractor_count": 1, "abstract_pattern": "AR::6_edges_5hop_inv"}
}
```

*หลังทำ Ephemeral Slot Binding (`sft.py`):* Entity `OO_E0101..OO_E0108` จะถูกแทนด้วย `<slot_0>..<slot_7>` แบบ Equivariant (สุ่มสลับตอน Train, คงที่ตอน Eval) ทำให้โมเดลไม่เคยเห็น prefix `OO_` ในระดับ Token

---

## 4. Detailed Specification: `ood_transfer` Dataset

### 4.1 Formal Task Definition
`ood_transfer` ออกแบบมาเพื่อพิสูจน์ว่าโมเดลไม่ได้จำ "ชื่อความสัมพันธ์ (Relation Lexicon)" หรือ "จำนวน Hop ตายตัว" แต่สามารถทำ **Compositional Graph Traversal** ข้ามความสัมพันธ์ใหม่ โครงสร้างกราฟใหม่ และความลึกของ Path ที่ยาวกว่าช่วงฝึก (`SL-01` Structural Disjointness)

### 4.2 Split-by-Split Progression Matrix (`ood_transfer`)

| Parameter | `train` (`n=800`) | `validation` (`n=80`) | `unseen` (`n=80`) | `ood` (`n=80`) |
|---|---|---|---|---|
| **Hop Depth `H`** | **`2` หรือ `3` hops** (`400` at 2-hop, `400` at 3-hop) | **`3` hops** | **`3` hops** | **`4`, `5`, `6` hops** (เช่น `30` at 4-hop, `30` at 5-hop, `20` at 6-hop) |
| **Relation Lexicon** | `connects_to`, `feeds_into` | `routes_to` *(or `bridges_to` alias, disjoint from train)* | `relates_to` (disjoint from train & val) | `transfers_to`, `channels_to` (disjoint from all prior splits) |
| **Distractor Edges** | `2 – 3` dead-end / alternate-relation edges | `3` distractor edges | `3 – 4` distractor edges | **`4 – 6` distractor edges** (including near-miss walks of length `H-1` or `H+1`) |
| **Abstract Structure (`SL-01`)** | Train structural templates (`2–3` hops) | Unseen entity + `routes_to` | Unseen phrasing + `relates_to` | **Strict `SL-01` = 0 overlap:** unseen depth `4–6` + unseen fan-out topologies |
| **Target Type** | Exact terminal entity (mapped to `<slot_k>` during model pass) | Exact terminal entity | Exact terminal entity | Exact terminal entity |

### 4.3 Multi-Factor OOD Transfer Axes & Near-Miss Distractor Design
`ood_transfer` ทดสอบการถ่ายโอนความรู้ข้าม 4 แกนพร้อมกันใน split `ood`:
1. **Hop Depth Extrapolation (`H = 2..3` -> `4..6`):** ฝึกที่ `2` และ `3` hops (400/400 ตัวอย่างใน `train`) และประเมิน In-dist ที่ `3` hops (`validation`/`unseen`) ก่อนบังคับ extrapolate ไปยัง `4` (`n=30`), `5` (`n=30`), และ `6` (`n=20`) hops ใน `ood`
2. **Disjoint Relation Lexicon:** ชื่อความสัมพันธ์ไม่ซ้ำกันเลยระหว่าง splits (`connects_to`/`feeds_into` vs `routes_to` vs `relates_to` vs `transfers_to`/`channels_to`) เพื่อพิสูจน์ว่าโมเดลจับโครงสร้างกราฟ ไม่ใช่ท่องจำคำกริยา
3. **Near-Miss Distractor Branches:** ใน `ood` มี distractor branch จาก node ต้นทางเดียวกันที่มีความยาว `H - 1` (dead end) และ chain ความยาว `H + 1` เพื่อดักโมเดลที่ไม่นับจำนวน `H` จริงหรือเดา leaf node สุดท้าย
4. **Reverse-Ordered Fact Presentation:** Edge ภายใน chain หลักถูกสับลำดับไม่เรียงจากต้นทางไปปลายทาง เพื่อทดสอบ Multi-hop state tracking แท้จริง

### 4.4 Exhaustive Solver & Anti-Shortcut Rules (`solve_exact_hop_path`)
ต่อยอดจาก `tools/gen_nagi_v10.py::solve_exact_hop_path`:
1. **Unique Reachable Endpoint at Depth `H`:** `len(endpoints_at_depth_H) == 1` และตรงกับ `answer`
2. **Unique Walk Count:** `walk_counts[answer] == 1` (ห้ามมีเส้นทาง 2 เส้นที่มีความยาว `H` ไปยังปลายทางเดียวกัน)
3. **Zero Shortcut Leakage:** `answer not in shortcut_targets` (ปลายทางต้อง **ไม่** สามารถเข้าถึงได้ใน `< H` hops เพื่อบังคับให้โมเดลเดินครบทุก `H` ก้าว)
4. **Distractor Isolation:** Distractor edges (รวมถึง edge ที่ใช้ relation อื่นของ split นั้นเป็นตัวหลอก) ต้องไม่สร้างทางลัดหรือปลายทางคู่แข่งที่ depth `H`
5. **Entity & Sequence Budget Verification:** จำนวน distinct entities ต่อตัวอย่างต้อง `<= 32` (`SLOT_COUNT = 32`) และความยาว structural/BPE ต้อง `<= 250 / 256` โทเคนแม้ที่ `6` hops + `5` distractors

### 4.5 Concrete JSONL Record Example (`ood_transfer` — `ood` Split, 5-Hop)

```json
{
  "schema_version": "2.0",
  "dataset_version": "11.0.0",
  "example_id": "v11-oo-ot-0042",
  "split": "ood",
  "stage_tags": [6],
  "capability": "ood_transfer",
  "task_type": "variable_depth_path_composition",
  "reasoning_operator": "exact_hop_reachability",
  "template_id": "OT_OO_5HOP_02",
  "difficulty_level": "hops_5_distractors_4",
  "instruction": "Follow exactly five transfers_to transitions from the origin node and output the unique endpoint.",
  "input": "EDGES: node_oo_0422 transfers_to node_oo_0423; node_oo_0420 transfers_to node_oo_0426; node_oo_0423 transfers_to node_oo_0424; node_oo_0426 transfers_to node_oo_0427; node_oo_0421 transfers_to node_oo_0422; node_oo_0424 transfers_to node_oo_0425; node_oo_0420 transfers_to node_oo_0421; node_oo_0428 transfers_to node_oo_0429 | QUERY: start node_oo_0420 | hops 5 | relation transfers_to",
  "target": "node_oo_0425",
  "facts": [
    {"source": "node_oo_0422", "relation": "transfers_to", "target": "node_oo_0423"},
    {"source": "node_oo_0420", "relation": "transfers_to", "target": "node_oo_0426"},
    {"source": "node_oo_0423", "relation": "transfers_to", "target": "node_oo_0424"},
    {"source": "node_oo_0426", "relation": "transfers_to", "target": "node_oo_0427"},
    {"source": "node_oo_0421", "relation": "transfers_to", "target": "node_oo_0422"},
    {"source": "node_oo_0424", "relation": "transfers_to", "target": "node_oo_0425"},
    {"source": "node_oo_0420", "relation": "transfers_to", "target": "node_oo_0421"},
    {"source": "node_oo_0428", "relation": "transfers_to", "target": "node_oo_0429"}
  ],
  "query": {"source": "node_oo_0420", "hops": 5, "relation": "transfers_to"},
  "answer": "node_oo_0425",
  "unique_answer_verified": true,
  "provenance": "deterministic_rule_solver_v11",
  "license": "internal-native-research",
  "metadata": {"hop_count": 5, "distractor_count": 3, "abstract_pattern": "OT::5hop_8edges_deadend2"}
}
```

---

## 5. Summary of Companion Capabilities (`relational_generalization`, `multi_step_planning`, `self_verification`, `knowledge_integration`)

เพื่อให้ชุดข้อมูล `6,240` ตัวอย่างครอบคลุมทั้ง 6 Stages อย่างสอดคล้อง:
1. **`relational_generalization` (`800/80/80/80`):** Directed graph 3-hop (`train`/`validation`/`unseen`) และ 4-hop (`ood`) บน relation หลัก (`linked_to` ใน in-dist, `bound_to` ใน `ood`) พร้อม shuffled premises + shortcut-free distractor branches (ตรวจด้วย `solve_exact_hop_path`)
2. **`multi_step_planning` (`800/80/80/80`):** Dependency DAG (`requires`), irrelevant parallel tasks pruning, ~20% cycle/missing-prereq traps -> `"impossible"`, และแผน 3–4 ขั้น (`train`/`val`/`unseen`) ขยายเป็น 5–6 ขั้นใน `ood` (ตรวจด้วย `solve_unique_plan` Kahn `len(ready) == 1`)
3. **`self_verification` (`800/80/80/80`):** แบ่ง 2 sub-tasks: `claim_check` (`true`/`false`/`unknown`) และ `plan_check` (`valid`/`invalid_order`/`invalid_missing`/`invalid_cycle`) พร้อม tagging `[fact]`/`[assumption]`/`[unverified]` (ตรวจด้วย `solve_verification`)
4. **`knowledge_integration` (`800/80/80/80`):** Multi-source ledger (`[tier=...][source=...][verified=...]`) ทดสอบ `base` + `update` override, selective retention, `retract` -> `"unknown"`, conflict detection -> `"conflict"`, และปฏิเสธการยืนยันจาก `[verified=false]` (ดูรายละเอียดที่ [V11_MEMORY_AND_KNOWLEDGE.md](./V11_MEMORY_AND_KNOWLEDGE.md))

---

## 6. Stage Curriculum Mapping (`stage_tags` Filtering)

ทุก Record ใน `train.jsonl` มีฟิลด์ `"stage_tags"` เพื่อใช้จัด Sample Pool ต่อ Stage ใน [V11_TRAINING_PLAN.md](./V11_TRAINING_PLAN.md) โดยไม่ต้องสร้างไฟล์ Dataset แยกซ้ำซ้อน:
- **Stage 1 (`1–1,000`):** ตัวอย่างความยากง่าย (`1–2` hops / simple comparison) จาก `abstract_reasoning` + `relational_generalization`
- **Stage 2 (`1,001–3,000`):** `abstract_reasoning` + `relational_generalization` (เต็มรูปแบบ `2–3` hops + distractors) + `15%` Stage 1 retention
- **Stage 3 (`3,001–5,000`):** `50%` `multi_step_planning` + `50%` Stage 1–2 replay
- **Stage 4 (`5,001–7,000`):** `50%` `knowledge_integration` + `50%` Stage 1–3 replay
- **Stage 5 (`7,001–9,000`):** `45%` `self_verification` + `55%` Stage 2–4 replay
- **Stage 6 (`9,001–10,000`):** Full balanced mixture ของทุก Capability (`~16.7%` ต่อด้าน) รวม `ood_transfer` train compositions

---

## 7. Manifest Schema Contract (`manifest.json`)

```json
{
  "schema": "zyrquen.dataset-manifest.v1",
  "dataset": "nagi_v11",
  "version": "11.0.0",
  "generator": "tools/gen_nagi_v11.py",
  "generator_version": "1.0.0",
  "seed": 42,
  "content_sha256": "<sha256 of concatenated canonical split hashes>",
  "splits": {
    "train": {"path": "train.jsonl", "example_count": 4800, "sha256": "<64-hex>"},
    "validation": {"path": "validation.jsonl", "example_count": 480, "sha256": "<64-hex>"},
    "unseen": {"path": "unseen.jsonl", "example_count": 480, "sha256": "<64-hex>"},
    "ood": {"path": "ood.jsonl", "example_count": 480, "sha256": "<64-hex>"}
  },
  "sources": {
    "nagi_v11_synthetic": {
      "path": "tools/gen_nagi_v11.py",
      "license": "internal-native-research",
      "sha256": "<64-hex>"
    }
  },
  "split_isolation": {
    "entity_disjoint": true,
    "template_disjoint": true,
    "ood_structural_disjoint": true,
    "unique_answer_solver_verified": true
  }
}
```

---

## 8. Mandatory Truthfulness Sections

### ASSUMPTIONS
- Pure-Python exhaustive solvers (`solve_order_dag`, `solve_exact_hop_path`, `solve_unique_plan`, `solve_verification`, `solve_knowledge_integration`) สามารถตรวจสอบครบทั้ง `6,240` ตัวอย่างได้ในเวลาไม่กี่วินาทีบน CPU
- ความยาวของตัวอย่าง 6-hop `ood_transfer` และ 6-edge `ood` `abstract_reasoning` สามารถบีบให้อยู่ใน `<= 250` structural tokens และ `<= 256` BPE tokens หลัง `train_slot_safe_tokenizer` ได้

### OPEN DECISIONS
- **OD-DS-01:** ขนาด `6,240` ตัวอย่าง (`800` per capability in train) เพียงพอสำหรับ `10,000` steps หรือควรขยายเป็น `1,200` / `1,600` per capability หาก Stage 2/3 แสดงอาการ Overfit บน `train` vs `unseen`
- **OD-DS-02:** รูปแบบการ Map `4` splits (`train`, `validation`, `unseen`, `ood`) เข้ากับ `ModelRegistry._verify_dataset` (`("train", "validation", "test")`) — เลือกระหว่างสร้าง `test.jsonl` เป็น verified deterministic union ของ `unseen + ood` หรือปรับ `_verify_dataset` ให้อ่าน `splits` list จาก `manifest.json`
- **OD-CS-01:** จะเปิด operator `"="` (equivalence) ใน `abstract_reasoning` ตั้งแต่รอบ V11 แรก หรือคง `{">", "<", "unknown"}` เพื่อเปรียบเทียบตรงกับ V10 ก่อน

### NOT VERIFIED
- ยังไม่มีไฟล์ Dataset V11 จริงใน Repository (`data/nagi_v11/` ยังไม่ถูกสร้าง และ `tools/gen_nagi_v11.py` ยังไม่ถูกเขียนตามข้อห้ามก่อน V10 Gate)
- การกระจายตัวของ BPE token length (`max(len(full_ids) - 1)`) บนตัวอย่าง 6-hop `ood_transfer` ด้วย `vocab_size = 2048` และ `4096` ยัง **NOT VERIFIED**
- อัตรา generation rejection ของกราฟ `6` hops + `5` distractors ภายใต้เงื่อนไข unique-walk + no-shortcut ยัง **NOT VERIFIED**
