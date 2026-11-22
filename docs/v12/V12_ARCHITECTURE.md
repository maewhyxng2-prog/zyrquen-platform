# ZYRQUEN Ω∞ — V12 Native Model Architecture

- **Document ID:** `V12-DOC-02`
- **Status:** `BLUEPRINT ONLY — PREPARATION TARGET — LOCKED UNTIL V10 & V11 FINAL GATES PASS`
- **Model Family:** `zyrquen-decoder` (`ZyrquenModel`)
- **Strategy:** 100% Native-Only Architecture — Zero External Models, Zero External APIs, Zero Hidden Adapters

---

## 1. Architectural Core & Continuity

ZYRQUEN V12 สืบทอดแกนสถาปัตยกรรม Causal Decoder-Only Transformer ที่พัฒนาขึ้นเองใน `apps/core/native/model.py` (`ZyrquenModel`) และขยายบทบาทของ **Externalized Cognitive Scaffolding** (Memory Store, Knowledge System, Self-Verification Gate, Central Workflow Engine) ให้ทำงานสอดประสานกันตลอดการฝึกสะสม `50,000` Steps โดยไม่ฝังโค้ดหรือน้ำหนักจากโมเดลภายนอกใดๆ

### End-to-End Inference & Training Architecture

```text
+-------------------------------------------------------------------------+
|               Central Workflow Engine (Governance & Audit)              |
|  Trigger -> Orchestrator -> Tier-2 Gate -> ResourceGuard -> AuditTrail  |
+------------------------------------+------------------------------------+
                                     |
         +---------------------------v---------------------------+
         |            Request / Task Framing & Guard             |
         |  - Tenant Scope & PII Redaction (Phase 17)            |
         |  - Optional Grounded Context Retrieval (MemoryStore)  |
         |  - Deterministic Slot Binding (<slot_0>..<slot_31>)   |
         +---------------------------+---------------------------+
                                     |
                                     v
         +-------------------------------------------------------+
         |       Native Tokenizer (zyrquen.tokenizer.v2)         |
         |  Byte-level BPE (train-only merges) + Atomic Slots    |
         +---------------------------+---------------------------+
                                     |
                                     v
         +-------------------------------------------------------+
         |         ZyrquenModel (zyrquen-decoder Core)           |
         |  Token Emb (weight-tied) -> N x [                     |
         |    Pre-RMSNorm -> Causal SDPA (+ RoPE) -> Residual    |
         |    Pre-RMSNorm -> SwiGLU FFN           -> Residual    |
         |  ] -> Final RMSNorm -> Linear Head -> EOS Termination |
         +---------------------------+---------------------------+
                                     |
                                     v
         +-------------------------------------------------------+
         |      Post-Inference Self-Verification & Safety        |
         |  - Phase 16 Evidence Check (fact/assumption/unverified)|
         |  - Slot Deserializing & Format Contract Check         |
         |  - Abstention / Conflict Reporting when Unsupported   |
         +-------------------------------------------------------+
```

---

## 2. Core Native Components (Zero External Dependencies)

| Layer / Component | Internal Mechanism | Purpose in 50K Plan | Repo Anchor |
|---|---|---|---|
| **Embedding & Weight Tying** | Shared `vocab_size x d_model` embedding/output projection | ลดพารามิเตอร์ซ้ำซ้อนและช่วย Generalization บน CPU | `apps/core/native/model.py` |
| **Rotary Positional Embeddings (RoPE)** | Relative rotational phase encoding ใน Query/Key | รองรับ OOD Sequence Length & Multi-Hop Extrapolation | `apps/core/native/model.py` |
| **Pre-RMSNorm Residual Blocks** | `RMSNorm(x)` ก่อน Attention และ FFN ทุกชั้น | เสถียรภาพของ Gradient ตลอด 50,000 Steps | `apps/core/native/model.py` |
| **Causal SDPA** | Masked Scaled Dot-Product Attention แบบ Causal 100% | รักษา Autoregressive Causality และ No Future Leakage | `apps/core/native/model.py` |
| **SwiGLU Feed-Forward** | Gated Linear Unit (`SiLU(xW1) * xW3 -> W2`) | เพิ่มความจุเชิงเหตุผลต่อ Parameter บน CPU | `apps/core/native/model.py` |
| **Atomic Entity Slots** | `<slot_0>..<slot_31>` แบบ Single-Token ไม่แตกคำ | ป้องกัน Subword Entity Leakage (EL-05) | `apps/core/native/tokenizer.py`, `sft.py` |

---

## 3. Why Native Reasoning Remains Distinct From External Scaffolding

เพื่อป้องกันการหลอกตัวเองว่าโมเดลฉลาดขึ้นจาก Rule ภายนอก:
1. **Stage 1–4 (`steps 1–33,000`)** วัดความสามารถของ `ZyrquenModel` **ล้วนๆ (Standalone Native Weights)** บน Prompt ที่กำหนดโดยไม่มี Solver ภายนอกช่วยตอบ
2. **Stage 5–6 (`steps 33,001–50,000`)** เชื่อมต่อ `MemoryStore` (สำหรับ Retrieve ข้อมูลตาม Tenant/Provenance) และ `Self-Verification Rules` (Phase 16) **แต่** คะแนน Reasoning/Belief-Revision ต้องวัดความสามารถของโมเดลในการประมวลผล `[source=...]` และแยก `fact`/`assumption`/`conflict` ด้วยตนเอง พร้อมรายงาน `standalone_model_score` แยกจาก `system_end_to_end_score` เสมอ

---

## 4. Strict Anti-External-Model Prohibitions

1. ห้าม Import หรือเรียกใช้ `openai`, `anthropic`, `google-generativeai`, `transformers.AutoModelForCausalLM.from_pretrained(...)`, `llama_cpp`, `ollama`, `vllm` หรือ Hub weights ใดๆ
2. ห้ามใช้ Teacher Distillation จากโมเดลภายนอกมาสร้าง Target Labels ใน Dataset V12 (Target Labels ต้องมาจาก Deterministic Exact Solvers ที่ตรวจสอบได้ 100% เท่านั้น)
3. ห้ามซ่อน Heuristic Lookup Table หรือ Scripted Answers ไว้หลัง `InferenceRouter` เพื่อสร้างภาพลวงตาว่า `ZyrquenModel` ตอบถูก

---

## 5. Mandatory Truthfulness Sections

### ASSUMPTIONS
- สถาปัตยกรรม `zyrquen-decoder` เพียงพอสำหรับฝึกทดสอบ Feasibility และ Reasoning ถึง `50,000` Steps ในระดับ `V12-Tier0` (`<= 5M`) และอาจปรับ Scaling Tier เฉพาะเมื่อมีผล Capacity Saturation ที่พิสูจน์แล้วจาก V11
- การปรับสถาปัตยกรรมใดๆ (เช่น Context Window Extension เกิน `256 -> 512` ใน Stage 4) ต้องผ่าน Governance Review ก่อนเขียนโค้ด

### OPEN DECISIONS
- **OD-V12-ARCH-01:** การขยาย `max_seq_len` จาก `256` เป็น `512` สำหรับ Long-Horizon Multi-step Planning & Memory Context (`Stage 4–6`) จะเปิดใช้เฉพาะเมื่อ `V12-Tier0` RAM Benchmark ยืนยัน RSS `< 3.0 GB`

### NOT VERIFIED
- ความจุเชิงเหตุผลสูงสุดของ `ZyrquenModel` ขนาด `3.74M – 4.75M` parameters เมื่อฝึกถึง `50,000` Steps บนข้อมูล OOD 6–10 hops ยัง **NOT VERIFIED**
- ผลกระทบของการเปลี่ยน Context Length ต่อ CPU Attention Throughput บนสถาปัตยกรรม `zyrquen-decoder` ยัง **NOT VERIFIED**
