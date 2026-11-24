# ZYRQUEN Ω∞ — v9 Experiment Plan (Audit, Dataset v9, Architecture & Protocol)

- **รุ่น:** `v9 — Generalization` *(experiment completed; retained as baseline)*
- **สถานะเอกสาร:** `HISTORICAL EXPERIMENT PLAN — CLOSED_FAIL`
- **ผลปิดการทดลอง:** ดู [`docs/V9_EXPERIMENT_CLOSURE_REPORT.md`](V9_EXPERIMENT_CLOSURE_REPORT.md); runtime training/evaluation completed on Colab, but capability acceptance failed.
- **ข้อกำหนดการอ่านเอกสาร:** เนื้อหาด้านล่างเป็นแผนและสมมติฐานก่อนทดลอง ไม่ใช่สถานะปัจจุบันหรือผลที่พิสูจน์แล้ว.
- **เส้นทางพัฒนาเชิงความสามารถ (Capability-Driven Progression):**
  - `v7 Baseline Foundation` (ผ่านการทดลอง) → `v8 Attention + Pointer-Copy` (ปิดการทดลองแล้ว) → **`v9 Generalization` (`CLOSED_FAIL`; report retained as baseline)** → `v10 Relational & Multi-step Reasoning` → `v11 Knowledge Integration` → `v12 Adaptive Learning` → `v13 Planning & Decomposition` → `v14 Verification & Self-Correction` → `v15 Autonomous Capability` → `v16+ Integrated Native Intelligence` → **ZYRQUEN Ω∞ — NGI** *(ไม่จำกัดว่าต้องจบที่ v20 และคง Roadmap `Phase 11–20` เดิมโดยไม่สร้าง `Phase 21`)*
- **อ้างอิงหลัก:** `docs/V9_BLUEPRINT.md`, `docs/V8_SUMMARY.md`, `docs/V8_EXPERIMENT_CLOSURE_REPORT.md`, `docs/NATIVE_TRAINING_500_SPEC.md`, `docs/SCALING_POLICY.md`, `docs/HONOR_X6B_MOBILE_PLAN.md`
- **เป้าหมายสูงสุด:** พัฒนา **Native General Intelligence (NGI)** ด้วยสถาปัตยกรรมที่รวมความสามารถเข้าด้วยกันอย่างต่อเนื่อง (**ไม่สร้างโมเดลแยกส่วน และไม่ใช่ Chatbot-only**) โดยในรอบ `v9` มุ่งพิสูจน์ **Generalization Gate** ก่อนขยายสู่ `v10+`
- **การแยกส่วนและข้อห้าม:** ไม่แก้ไข/เขียนทับไฟล์ `v7` หรือ `v8` เดิม, ไม่ลบ/ย้าย Checkpoint หรือ Report เดิม, ไม่ Push น้ำหนักขึ้น GitHub, ไม่เพิ่มค่าใช้จ่าย Cloud/GPU และ **ยังไม่เริ่ม Training จริงจนกว่าเจ้าของโครงการจะอนุมัติแผนนี้**

---

## 1. Repository Audit (ผลการตรวจสอบ Repository และสภาพแวดล้อมจริง)

### 1.1 สถานะไฟล์โค้ดและเอกสารที่ตรวจสอบจริง
| หมวด | ไฟล์ที่ตรวจสอบ | สภาพปัจจุบันและข้อสังเกตเชิงเทคนิค |
|---|---|---|
| **เอกสาร `v8`/`v9`** | `docs/V9_BLUEPRINT.md`, `docs/V8_SUMMARY.md`, `docs/V8_EXPERIMENT_CLOSURE_REPORT.md`, `tools/v8_summary.md` | ครบถ้วนและสอดคล้องกัน; `v8` ยังอยู่สถานะ `FROZEN` และ `PARTIAL / BLOCKED IN WORKSPACE` (รอแนบ `report.json` จริงจาก Codespaces) |
| **สายงาน `v7` Baseline** | `tools/train_nagi_500_v7.py`, `tools/eval_nagi_500_v5.py` | `TinyNGI` (Embedding 128 + 2-layer LSTM 128 + Linear Head, ~`273,955` params ตามบันทึกโครงการ); ใช้ `batch=4`, `seq=256`, sequential batch, `Adam(lr=0.001)`, train-only vocab |
| **สายงาน `v8` Baseline** | `tools/train_nagi_500_v8.py`, `tools/eval_nagi_500_v8.py` | `Seq2Seq` (BiGRU Encoder 128→256 + Bahdanau Attention + PointerDecoder GRU 128 + `p_gen`, ~`523,708` params); แยกรายงาน TF vs Free-Gen และมี `dynamic local vocab` ในการประเมิน |
| **Dataset `v3` & Audit** | `tools/gen_nagi_500_v3.py`, `tools/audit_leakage_v3.py`, `tools/gen_ngi_500.py` | `gen_nagi_500_v3.py` ใช้ Entity `E00–E19` ซ้ำทุก Split และแชร์ Template; `audit_leakage_v3.py` ยืนยันว่า `v3` **FAIL** strict entity-disjoint และ strict template-disjoint (ส่วน `gen_ngi_500.py` มีโครงตรวจ Leakage 3 ชั้น แต่รูปแบบโจทย์ยังสั้นและตื้น) |
| **Native Core (`apps/core/native/`)** | `config.py`, `model.py`, `tokenizer.py`, `dataset.py`, `train.py`, `evaluation/engine.py` | มีโครงสร้าง Transformer (`ZyrquenModel` + RoPE + SwiGLU + RMSNorm), Byte-level BPE Tokenizer, Dataset Manifest SHA-256, CostController (`apps/core/training/cost_limits.py`) แยกอยู่เป็นโมดูลหลัก แต่ยังไม่มี Pointer-Copy / Dynamic Entity Slot Binding |
| **ความปลอดภัยของ Repo** | `.gitignore` | มีกฎป้องกัน `/data/`, `checkpoints/`, `*.pt`, `*.safetensors`, `*.ckpt`, `runs/`, `artifacts/` ไม่ให้ขึ้น Git แล้ว |

### 1.2 การตรวจสภาพแวดล้อมและทรัพยากรจริง (Hardware & Runtime Audit)
- **ทรัพยากรคอนเทนเนอร์ปัจจุบัน (ตรวจจริง):**
  - CPU: `4` cores, RAM: `12 GiB` (`~10 GiB` available), Swap: `0 B`, **ไม่มี CUDA GPU**
  - Python: `3.11.2`, **`torch` / `numpy` / `transformers` / `accelerate`: `NOT_INSTALLED`** ในคอนเทนเนอร์ปัจจุบัน
  - ไม่มีโฟลเดอร์ `data/`, `checkpoints/`, `eval/` ใน Snapshot นี้ (artifact รันไทม์เดิมอยู่ใน Codespaces)
- **กรอบทรัพยากรและเพดานการทดลองของโครงการ (`HONOR_X6B_MOBILE_PLAN.md` & `SCALING_POLICY.md`):**
  - ชั้น Hardware ปัจจุบัน (CPU-only / Edge-compatible): **`MAX_CPU_MODEL_PARAMETERS = 5,000,000`**, **`MAX_CPU_SEQUENCE_LENGTH = 256`**, **`MAX_CPU_BATCH_SIZE = 4`**, **`MAX_CPU_TRAINING_STEPS = 1,000`**
  - หมายเหตุเรื่อง `SCALING_POLICY.md`: ตารางระยะยาววาง `v9` ที่ระดับ `10M` แต่กฎชั้น Hardware ปัจจุบันห้ามรันโมเดลเกิน `5M` บน CPU และห้ามเปิดใช้ GPU/Cloud ที่มีค่าใช้จ่ายโดยไม่อนุมัติ — ดังนั้น **โมเดล `v9` Candidate รอบนี้ต้องออกแบบให้อยู่ในช่วง `~1.0M–1.4M` พารามิเตอร์ (ต่ำกว่าเพดาน `5M` อย่างชัดเจน)** เพื่อให้ฝึกและประเมินได้จริงบน CPU 4 cores / Codespaces
  - **ข้อกำหนดก่อนรันจริง:** การฝึกและการประเมินผล `v9` ต้องรันในสภาพแวดล้อมที่มี PyTorch CPU (เช่น Codespaces หรือหลังอนุมัติติดตั้ง `torch` CPU)

### 1.3 คอขวดเชิงลึกของ `v7`/`v8` ที่ต้องแก้ใน `v9` (Root-Cause Findings จากโค้ดจริง)
1. **Unseen Entity Bottleneck (`eval_nagi_500_v8.py` บรรทัด 233 & 278):**
   - แม้ `eval_nagi_500_v8.py` จะสร้าง `local_stoi` เพื่อ **Copy** คำตอบ OOV ได้ในขั้นตอน Output Distribution แต่ตอนส่งเข้า **Encoder** โค้ดใช้ `model_src_ids = [stoi.get(t, unk_id)]` ทำให้ Entity ใหม่ 2 ตัวขึ้นไปในโจทย์เดียวกัน (เช่น `TE_E01 > TE_E02, TE_E02 > TE_E03`) ถูกแปลงเป็น `<unk>` ทั้งคู่! โมเดลจึง **แยกความต่างของ Unseen Entities ระหว่างให้เหตุผลไม่ได้เชิงคณิตศาสตร์**
2. **Entity & Template Leakage ใน `nagi_500_v3` (`L1`, `L7`):**
   - `E00–E19` ซ้ำทั้ง Train/Val/Test ทำให้ `unseen_entity_count == 0` และ `unseen_entity_copy_acc` กลายเป็น `N/A`
3. **Adaptive Learning ตื้น (`L2`):**
   - `v3` มีแค่ `learn: A -> B | predict A ?` ไม่สามารถทดสอบการปรับทับความรู้เก่า (`override`), การรักษาความรู้ที่ไม่ได้แก้ (`retention`), หรือการเพิกถอน (`retraction`)
4. **Shallow Copy Bias & ขาด Gate Discipline (`L3`):**
   - Pointer Gate (`p_gen`) มีแนวโน้มพึ่งพา `copy_dist` มากเกินไปในงานที่ต้องสังเคราะห์คำตอบ (`true/false/conflict/>`)
5. **ขาด Arm B Ablation (`L4`):**
   - `v8` เพิ่ม Attention + Pointer-Copy พร้อมกัน ทำให้แยกผลกระทบระหว่าง Attention กับ Copy Mechanism ไม่ได้
6. **ข้อจำกัดความลึกและ Shortcut ของงาน (`L6`):**
   - `relational_reasoning` คงที่ 2 hops เรียงซ้ายไปขวา; `planning_decomposition` เป็นเพียง index `first/middle/last`; `verification` มีเพียง 6 คู่คำ; ยังไม่มี `knowledge_integration` (conflict/cycle detection) และ `generalization` slice แยกเฉพาะ
7. **Sequential Batch Order Bias (`train_nagi_500_v7.py` / `v8.py`):**
   - การวน batch แบบเรียงลำดับตาม `train.jsonl` โดยไม่ shuffle แบบควบคุม seed อาจทำให้ gradient ช่วงท้ายกระจุกตัวอยู่ที่ capability เดียวหากข้อมูลเรียงตามกลุ่ม

---

## 2. Dataset `v9` Design (`data/nagi_v9/` — แยกขาดจาก `v3` และ `v8`)

### 2.1 โครงสร้าง Split และขนาดชุดข้อมูล
ออกแบบชุดข้อมูลใหม่ทั้งหมดใน `data/nagi_v9/` โดยแยกชุดทดสอบมาตรฐานออกจากชุด Out-of-Distribution (OOD) อย่างชัดเจน:

| Split | จำนวนทั้งหมด | ต่อ Capability (`8` กลุ่ม) | ลักษณะ Entity Pool | ลักษณะ Template & Structure |
|---|---:|---:|---|---|
| **`train.jsonl`** | **960** | 120 | `TR_*` เท่านั้น (`>= 240` entities) | Train Templates (`*_TR_*`), 1–3 hops, baseline updates |
| **`val_unseen.jsonl`** | **120** | 15 | **`VA_*` 100% ใหม่** (`>= 40` entities) | โครงสร้างระดับ Train + Distractors (ตรวจ generalization ข้าม Entity) |
| **`val_ood.jsonl`** | **120** | 15 | **`VA_*` 100% ใหม่** (ใช้ร่วม/ไม่ทับ Train/Test) | **Unseen Templates (`*_VA_OOD_*`) + Unseen Abstract Patterns + 4 hops** |
| **`test_unseen.jsonl`** | **120** | 15 | **`TE_*` 100% ใหม่** (`>= 45` entities) | โครงสร้างระดับ Train + Distractors (Read-only Final Eval) |
| **`test_ood.jsonl`** | **120** | 15 | **`TE_*` 100% ใหม่** (ห้ามซ้ำ Train/Val) | **Unseen Templates (`*_TE_OOD_*`) + Unseen Abstract Patterns + 4–5 hops** |
| **รวม** | **1,440** | **180** | **Disjoint 3 Pools (`0` Overlap)** | **ตรวจ Leakage 4 ชั้น + Fail-Closed Gate** |

### 2.2 การออกแบบ Entity Pool เพื่อป้องกัน Entity Leakage และกำจัด `N/A`
1. **3 Entity Pools แยกขาด (`EL-01..EL-04 = 0`):**
   - **Train Pool (`>= 240` entities):** `TR_E000..TR_E179`, `node_tr_00..29`, `item_tr_00..29`
   - **Val Pool (`>= 60` distinct entities):** `VA_E000..VA_E039`, `node_va_00..09`, `item_va_00..09`
   - **Test Pool (`>= 60` distinct entities):** `TE_E000..TE_E039`, `node_te_00..09`, `item_te_00..09`
   - ครอบคลุม **>= 3 รูปแบบตัวระบุ** ต่อ Split เพื่อทดสอบ Entity Tokenizer & Regex Coverage (`EL-08`)
2. **การรับประกันไม่มี `N/A` ใน `unseen_entity_copy_acc`:**
   - ในทุก Eval Split (`val_unseen`, `val_ood`, `test_unseen`, `test_ood`) อย่างน้อย 5 Capability มีคำตอบเป็น Entity Token (`>= 45` ตัวอย่างที่มี Entity เป็น Target ต่อ Split) และใช้ Distinct Unseen Entities **อย่างน้อย `30` ตัวขึ้นไปต่อ Split** (ตั้งเป้ายืนยันใน Script Audit ที่ `>= 40` Entities เพื่อมี Margin สูงกว่าเกณฑ์ขั้นต่ำ `EL-07 >= 30`)
   - กฎ Vocab Policy (`EL-05`): สร้าง Static Vocab จาก `train.jsonl` **เท่านั้น** — ห้ามมี Entity จาก `VA_*` หรือ `TE_*` อยู่ใน Vocab

### 2.3 Specification ของ Capability Tests ทั้ง 8 กลุ่ม

| # | Capability | สิ่งที่ทดสอบ (NGI Focus) | รูปแบบตัวอย่าง (Train vs OOD / Hard) | Target Types & Label Balance |
|---|---|---|---|---|
| **1** | **`native_representation`** | การจับคู่ตำแหน่ง โครงสร้างลำดับ และช่วงข้อมูลแม้มี Distractor | `seq: A,B,C,D \| idx 2 ?` -> `C`; `set: [A,B] minus [B] \| rem ?` -> `A` | Entity tokens (สมดุลตำแหน่งหน้า/กลาง/หลัง/รายการ) |
| **2** | **`knowledge_acquisition`** | การเก็บและดึงข้อเท็จจริงหลายคู่ในบริบทที่มี Distractor 3–5 รายการ | `facts: A->B; C->D; E->F \| lookup C ?` -> `D`; `A has B \| what has B ?` | Entity tokens (สลับลำดับคู่ข้อเท็จจริงในบริบท) |
| **3** | **`relational_reasoning`** | Multi-hop graph traversal + **Shuffled premise ordering** + inverse + unreachable | `B > C, A > B, D > E \| A ? C` -> `>` ; `C ? A` -> `<` ; `A ? D` -> `unknown` (Train 2–3 hops; **OOD 4–5 hops**) | สมดุล `>`, `<`, `=`, `unknown` (~25% เท่ากัน) |
| **4** | **`planning_decomposition`** | Dependency-driven topological planning + subgoal pruning + **cycle/missing-prereq** | `goal: C \| deps: C after B, B after A, D after C \| plan ?` -> `A -> B -> C` ; วนลูป `A after B, B after A` -> `impossible` | Ordered entity plan หรือ `impossible` |
| **5** | **`verification`** | ตรวจความจริงของ Claim หลายขั้น และตรวจความถูกต้องของ Proposed Plan | `claim: A > C \| facts: B > C, A > B \| verdict ?` -> `true` / `false` / `unknown`; `check_plan: B->A \| deps: B after A` -> `invalid:order_violation` | สมดุล `true`, `false`, `unknown`, `valid`, `invalid:*` |
| **6** | **`adaptive_learning`** | In-context override, selective retention, chained adaptation, และ retraction | **Override:** `base: A->B \| update: A->C \| query A ?` -> `C`; **Retention:** `... \| query D ?`; **Retract:** `retract: A->B \| query A ?` -> `unknown` | Entity tokens + `unknown` (กันจำ keyword `learn:`) |
| **7** | **`knowledge_integration`** | รวมข้อมูลต่างแหล่ง (`fact:`, `obs:`, `rule:`), จับข้อขัดแย้ง/Cycle, แยก `update:` ออกจาก `conflict` | `fact: A=B \| obs: A!=B \| integrate A,B ?` -> `conflict`; `A>B, B>C, C>A` -> `conflict`; `base+update` -> ค่าใหม่ | Entity tokens, `true`/`false`, `conflict` |
| **8** | **`generalization`** | Compositional Multi-Skill: รวม Unseen Entities + Unseen Phrasing + 4-hop + Update + Verify ในโจทย์เดียว | `obs: D->E; base: A->B; update: A->C; chain: C>F, F>G \| verify A > G ?` -> `true` / `conflict` / entity | ผสมผสาน Symbol และ Unseen Entity |

---

## 3. Architecture Proposal (`v9` Candidate Model & Fair Resource Sizing)

### 3.1 การแก้ปัญหา `<unk>` Collision ของ `v8` ด้วย Dynamic Entity Slot Binding
ปัญหาใหญ่ที่สุดของ `v8` เมื่อเจอ Unseen Entity มากกว่า 1 ตัวในโจทย์คือ Encoder แปลงทุก Unseen Entity เป็น ID `<unk>` เดียวกันหมด เพื่อแก้ปัญหานี้โดย **ไม่เอา Entity Test เข้า Static Vocab**:
- **Context-Local Ephemeral Slotizer (ทำงานเฉพาะภายใน 1 Prompt):**
  1. Tokenize ข้อความอินพุตด้วย `tokenize()`
  2. โทเคนที่อยู่ใน Static Train Structural Vocab (operator, keyword, punctuation, `<pad>`, `<bos>`, `<eos>`, `<unk>`) ใช้ Token ID ปกติ
  3. โทเคน Entity (หรือโทเคน OOV ที่เป็น Slot Candidate ตามกติกาตรวจ Entity/OOV) ภายใน Prompt เดียวกัน จะถูก map ตามลำดับการเจอ (หรือสุ่มลำดับ Slot ID ระหว่าง Train: **Slot Permutation Augmentation**) เข้าสู่ **Local Entity Slots** `<slot_0> .. <slot_31>` (`S = 32` reserved embeddings)
  4. หาก Entity เดิม (เช่น `TE_E042`) ปรากฏ 3 ครั้งใน Prompt เดียวกัน จะได้ Slot เดียวกันทั้ง 3 จุด (เช่น `<slot_2>`) จึงรักษา Graph Structure (`<slot_2> > <slot_5>, <slot_5> > <slot_1>`) ได้สมบูรณ์ **แม้ไม่เคยเห็น `TE_E042` ในชีวิตมาก่อน**!
  5. ตาราง `slot_to_surface` ถูกเก็บเฉพาะในระดับ Request/Prompt เพื่อ Map กลับเวลา Pointer-Copy เลือกตำแหน่งหรือเลือก Slot เป็นคำตอบ
  - **ความสอดคล้องกฎ Leakage (`EL-05`):** Static Vocab (`train-only`) ไม่เคยเห็นชื่อ `VA_*` หรือ `TE_*` แม้แต่ตัวเดียว และตอน Training โมเดลเห็นการสุ่มสลับ Slot ID (`<slot_k>`) จึงจำ ID `<slot_0>` ตายตัวไม่ได้

### 3.2 สถาปัตยกรรมที่เสนอ: **Arm D — `ZyrquenSlotReasoner` (Compact Seq2Seq Transformer + Dual-Gated Pointer-Generator)**
- **Encoder (Bidirectional Relational Message Passing):**
  - Token/Slot Embedding (`d_model = 160`) + Rotary/Relative Positional Encoding (อ้างอิงสไตล์ RoPE/RMSNorm ที่โครงการใช้อยู่ใน `apps/core/native/model.py`)
  - **`4` Bidirectional Transformer Encoder Layers** (`n_heads = 4`, `head_dim = 40`, `d_ff = 448` SwiGLU/GELU, `dropout = 0.1`): แต่ละ Layer ทำหน้าที่เป็น 1 รอบของ Relational Message Passing บนทุก Node พร้อมกัน จึงแก้ปัญหา Shuffled Premise Ordering และ 4–5 hops ได้ดีกว่า BiGRU 1-pass
- **Decoder (Causal Reasoning + Cross-Attention Copy):**
  - **`2` Transformer Decoder Layers** (`d_model = 160`, `n_heads = 4`, `d_ff = 448`): Causal Self-Attention + Multi-Head Cross-Attention ไปยัง Encoder Outputs
  - **Dual Distribution Head:**
    - `vocab_dist = softmax(W_vocab h_dec)` เฉพาะคำศัพท์เชิงตรรกะ/คำตอบโครงสร้างจาก Train Vocab
    - `copy_dist` = ผลรวม Cross-Attention Weights (จาก Layer สุดท้ายหรือ Mean-Head Attention Bridge) ฉายลงบน Token/Slot ตำแหน่ง Input
    - `p_gen = sigmoid(W_p [h_dec; context; emb])` ผสาน `p_gen * vocab_dist + (1 - p_gen) * copy_dist`
  - **Slot Permutation Equivariance + Scheduled Teacher-Forcing / Multi-task Loss:**
    - Loss หลัก: NLLLoss บน Joint Pointer Distribution (Ignore `<pad>`)
    - Auxiliary Gate Regularization (น้ำหนักเล็ก เช่น `λ = 0.05` บน Validation check): กระตุ้นให้ `p_gen` ไม่ collapse ลงไปที่ copy บนงานที่ Target เป็น Operator/Verdict (`>`, `<`, `true`, `conflict`, `impossible`)

### 3.3 งบประมาณขนาดโมเดลและทรัพยากร (Resource Fit Proof)

| พารามิเตอร์โครงสร้าง | `v7` Baseline (Arm A) | `v8` Baseline (Arm C) | `v9` Candidate Proposal (Arm D) | เพดานโครงการ (CPU Cap) |
|---|---|---|---|---|
| **Backbone** | 2-Layer LSTM | BiGRU + Bahdanau Attn + Pointer | 4L Enc / 2L Dec Slot-Transformer + Pointer | — |
| **Hidden / Model Dim** | `128` | `128` | `d_model = 160` (`4` heads, `d_ff = 448`) | — |
| **Train Vocab + Slots** | Token-level (~30) | Token-level (~30) | Structural/Train Vocab (~180–350) + `32` Local Slots | Train-only (`EL-05 = 0`) |
| **Approx. Parameters** | `~274K` (`273,955` ref) | `~524K` (`523,708` ref) | **`~1.15M – 1.35M`** (Fallback compact config `d=128`: `~0.75M`) | **`<= 5,000,000`** (`PASS`) |
| **Sequence / Batch** | `256` / `4` | `256` / `4` | **`256` / `4`** (รองรับ `grad_accum=2` ถ้าต้องการ effective batch 8 บน RAM เท่าเดิม) | `<= 256` / `<= 4` (`PASS`) |
| **Approx. Peak RAM (CPU)** | `< 250 MB` | `< 300 MB` | **`< 450 MB`** (ปลอดภัยบนเครื่อง RAM 6GB และ Container 12GB) | `< 6 GB` (HONOR X6b) (`PASS`) |

---

## 4. Experiment Plan (แผนการทดลอง 4-Arm, Principle Probes, Metrics & Gates)

### 4.1 ตารางเปรียบเทียบแบบควบคุม 4 แขน (4-Arm Apples-to-Apples Protocol)
ทุก Arm ใช้ชุดข้อมูล `data/nagi_v9/` ชุดเดียวกัน, `seed=42`, `batch=4` (stratified shuffled), `seq=256`, `train-only vocab` และใช้ Evaluator ตัวเดียวกัน (`eval_nagi_v9.py`):

| Arm | โมเดล | จุดประสงค์ทางวิทยาศาสตร์ |
|---|---|---|
| **Arm A** | `v7` Architecture (`TinyNGI` 2L-LSTM) | Baseline ลำดับพื้นฐานบน `v9` Benchmark |
| **Arm B** | `v8-Ablation` (`BiGRU + Bahdanau Attention`, **ไม่มี Pointer-Copy**) | **Ablation ที่ขาดไปใน v8** — แยกผล Attention ออกจาก Pointer-Copy |
| **Arm C** | `v8` Architecture (`BiGRU + Bahdanau Attention + Pointer-Copy`) | Baseline ที่มีความสามารถ Copy ของเดิมบน `v9` Benchmark |
| **Arm D** | **`v9` Candidate (`Slot-Equivariant Transformer Reasoner + Pointer`)** | พิสูจน์ว่าการแก้ `<unk>` collision + multi-layer relational attention ชนะทุก Baseline บน Unseen & OOD |

*(เพิ่มเติม: สำหรับ Arm D จะทดสอบ Variant ย่อย `Arm D-NoSlot` เทียบ `Arm D-Slot` ในรอบ Validation เพื่อวัดผลของ Slot Binding แยกต่างหากหากเวลาเอื้ออำนวย)*

### 4.2 การทดลองพิสูจน์ "เรียนรู้หลักการจริง vs จำรูปแบบ" (6 Principle Diagnostic Probes)
นอกเหนือจาก Exact Match ปกติ `eval_nagi_v9.py` จะรัน 6 Probe Read-only บน `val` / `test`:
1. **Probe 1 — Alpha-Renaming Invariance:** เปลี่ยนชื่อ Unseen Entity แบบสุ่ม 3 ชุดบนข้อสอบเดียวกัน → ส่วนต่าง Accuracy ต้อง **`< 2.0 pp`** (พิสูจน์ว่าไม่ยึดติดชื่อ Token)
2. **Probe 2 — Premise Permutation Invariance:** สลับลำดับบรรทัด/ประโยคของข้อเท็จจริงในโจทย์เดียวกัน (Canonical Order vs Shuffled Order) → Accuracy Drop ต้อง **`< 5.0 pp`**
3. **Probe 3 — Depth Extrapolation Gap (`2–3 hop` -> `4–5 hop`):** เทียบความแม่นยำระหว่างความลึกที่ฝึก (`2–3 hops`) กับ OOD (`4–5 hops`) → `4+ hop >= 0.65`
4. **Probe 4 — Distractor Sensitivity (`0` vs `3–5` distractor facts):** Accuracy Drop เมื่อเติมข้อเท็จจริงหลอกต้อง **`< 10.0 pp`**
5. **Probe 5 — Override vs Conflict Minimal Pairs:** วัดความแม่นยำคู่เทียบที่ต่างกันเพียงคีย์เวิร์ด `update:` กับ `fact:` ที่ขัดแย้งกัน → พิสูจน์ว่าไม่เดาคำตอบเดียว
6. **Probe 6 — Pointer Gate Discipline (`mean_p_gen` Split):** วัดว่า `mean_p_gen` แยกพฤติกรรม Copy (`<= 0.45`) ออกจาก Reasoning/Verdict (`>= 0.60`) ได้จริง

### 4.3 Metrics, Acceptance Criteria & Stop Conditions (อ้างอิงเกณฑ์ตัวเลขใน `docs/V9_BLUEPRINT.md` Section 10)
- **Data Gate (Zero-Tolerance Fail-Closed ก่อน Train):**
  - `EL-01..EL-03` (Pairwise Entity Overlap Train/Val/Test) `= 0` (`0.00%`)
  - `EL-04` (`entity_leakage_rate`) `= 0.00%`
  - `EL-05` (Static Vocab Entity Leakage) `= 0`
  - `EL-06` (`unseen_entity_ratio` ใน Eval Splits) `= 100.00%`
  - `EL-07` Distinct Unseen Entities `>= 30` ต่อ Eval Split และ `>= 5` formats (ในแผน v9 ตั้งเป้า `>= 40` Entities)
  - `EL-08` Uncovered Entity Formats `= 0`
  - `TL-01` (OOD Template Overlap) `= 0`, `SL-01` (OOD Abstract Pattern Overlap) `= 0`, `DL-01` (Duplicates & Empty Target) `= 0`
- **Model Acceptance Criteria (Free-Generation หลัก + TF Gap):**
  - `unseen_entity_copy_acc >= 0.85` (ห้ามเป็น `N/A`)
  - `unseen_entity_reasoning_acc >= 0.75` และชนะ Arm C (`v8`) `>= +0.05`
  - `test_ood` `free_gen_exact_match > max(Arm A, B, C)` อย่างน้อย `+0.05` และเหนือ Majority Baseline `>= +0.20`
  - `multi_hop_acc >= 0.80` (2–3 hops) และ `>= 0.65` (4+ hops)
  - `adaptive_override_acc >= 0.75`, `adaptive_retention_acc >= 0.85`
  - `conflict_detection_f1 >= 0.80`
  - `plan_validity_acc`, `impossible_plan_acc`, `verification_acc` แต่ละกลุ่ม `>= 0.75` และ **0 Regression** เทียบ `v8` บน Benchmark เดียวกัน
  - `exposure_bias_gap <= 0.10`, `eos_hit_rate >= 0.95`, `premature_eos_rate <= 0.02`, `repetition_rate <= 0.05`
  - `mean_p_gen <= 0.45` (Copy tasks) vs `>= 0.60` (Reasoning/Verdict tasks)
  - `params <= 5,000,000`, `seq <= 256`, `NaN/Inf == 0`
- **Stop / Abort Criteria (หยุดทันทีเมื่อเกิดเงื่อนไข):**
  1. `EL-01..DL-01` ข้อใดข้อหนึ่ง `> 0` หรือ `unseen_entity_copy_acc == N/A` / distinct entities `< 30`
  2. Validation Loss เกิด `NaN`/`Inf` หรือ Diverge ต่อเนื่อง (`no_improve >= 2` โดย Loss ไม่ลด)
  3. **No-Gain Complexity Bloat:** `v9` ใหญ่/ช้ากว่า `v8` แต่ Validation หรือ OOD Exact Match ไม่ชนะทั้ง Arm B และ Arm C อย่างน้อย `+0.05`
  4. **Shallow Copy / Majority Collapse:** `mean_p_gen < 0.15` บนงาน Reasoning/Verdict หรือตอบ Majority Label เดียว `> 80%`
  5. **Autoregressive Degeneration:** `repetition_rate > 0.10` หรือ `eos_hit_rate < 0.85`

### 4.4 แผนผังไฟล์ `v9` แยกขาดจาก `v7`/`v8` และขั้นตอนดำเนินการหลังได้รับอนุมัติ

| ลำดับขั้น | สิ่งที่จะสร้าง / ดำเนินการ (หลังอนุมัติ) | ตำแหน่งไฟล์ใหม่เฉพาะ `v9` | สิ่งที่ห้ามแตะต้อง |
|---|---|---|---|
| **Step 1** | สร้าง Dataset Generator + Leakage Gate 4 ชั้น (`EL-01..DL-01`) | `tools/gen_nagi_v9.py`, `tools/audit_leakage_v9.py`, `data/nagi_v9/*` | ห้ามแก้ `tools/gen_nagi_500_v3.py`, `audit_leakage_v3.py`, `data/nagi_500_v3/*` |
| **Step 2** | สร้าง Trainer (`Arm A/B/C/D` unified controlled runner) + Overfit 4/4 & CPU Cost Check (100 steps) | `tools/train_nagi_v9.py`, `checkpoints/nagi_v9/*` | ห้ามแก้ `train_nagi_500_v7.py`, `train_nagi_500_v8.py`, `checkpoints/nagi_500_*` |
| **Step 3** | รัน Training ควบคุม (500→1,000 steps ตามงบ CPU ที่อนุมัติ, ไม่ใช้ GPU/Cloud เสียเงิน) | `checkpoints/nagi_v9/arm_{a,b,c,d}/` *(ไม่ push git)* | ห้าม Commit/Push `*.pt` หรือ `checkpoints/` |
| **Step 4** | สร้าง Evaluator + 6 Principle Probes + ออกรายงานเทียบ 4 Arm | `tools/eval_nagi_v9.py`, `eval/nagi_v9/report.{json,md}` | ห้ามแก้ `eval_nagi_500_v5.py`, `eval_nagi_500_v8.py`, `eval/nagi_500_*`, `phases/phase11..20` |

---

**สถานะ:** ส่ง Repository Audit, Dataset Design, Architecture Proposal และ Experiment Plan รอบแรกเสร็จสมบูรณ์ — **หยุดรออนุมัติจากเจ้าของโครงการก่อนสร้าง Script หรือเริ่ม Training จริง**
