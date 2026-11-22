# ZYRQUEN Ω∞ — V11 Architecture Specification

- **Document ID:** `V11-DOC-02`
- **Status:** `BLUEPRINT ONLY — LOCKED UNTIL V10 FINAL GATE PASS`
- **Model Family:** `zyrquen-decoder` (`apps/core/native/model.py`)
- **Initialization:** Random Initialization (`normal_(0, 0.02)` + residual scaled `0.02 / sqrt(2 * n_layers)`)

---

## 1. Architectural Principles

1. **Native-Only Intelligence Core:** ระบบประมวลผลภาษาและการให้เหตุผลทั้งหมดของ V11 รันผ่าน `ZyrquenModel` (`apps/core/native/model.py`) และ `NativeRuntime` (`apps/core/runtime.py`) เท่านั้น ห้ามเรียก external LLM APIs หรือโหลด pretrained weights จากภายนอก
2. **Single Canonical Neural Backbone:** คงสถาปัตยกรรม Decoder-Only Transformer (`ZyrquenModel`) เพื่อลดความซ้ำซ้อนของ Checkpoint Loader (`NativeModelLoader`), Inference Engine (`NativeInferenceEngine`), และ Streaming Engine (`StreamingInferenceEngine`)
3. **Ephemeral Slot Equivariance Layer:** แก้ปัญหา OOV / Entity Surface Memorization ด้วย `bind_ephemeral_slots` และ `restore_ephemeral_slots` (`apps/core/native/sft.py`) ผสานกับ `zyrquen.tokenizer.v2` (`<slot_0>..<slot_31>`) ทำให้โมเดลประมวลผล Entity ใหม่ที่ไม่เคยเห็นใน Test/OOD ได้แบบ Equivariant โดยไม่ทำลาย Static Vocabulary
4. **Structured Cognitive System Integration:** โมเดล Neural Core ไม่ทำงานแบบลอยตัว แต่เชื่อมต่อกับ Subsystem ที่สร้างไว้ใน Phase 16–19:
   - **Memory & Grounding:** `phases/phase17.py` (`MemoryStore`) + `apps/core/intelligence/knowledge.py`
   - **Reasoning & Plan Verification:** `phases/phase16.py` (`ReasoningPipeline`, `validate_dag`, `verify_step`, `ExecutionSafetyPolicy`)
   - **Governance & Workflow:** `apps/core/workflow/` (`CentralWorkflowOrchestrator`, `WorkflowGovernance`, `WorkflowResourceGuard`)

---

## 2. System Data Flow (End-to-End Architecture)

```text
[User / Evaluation Prompt]
        │
        ▼
[1. Grounded Memory & Knowledge Retrieval (Tenant-Isolated, Source-Required)]
   - Check owner_id + workspace_id (Phase 17)
   - Inject verified facts with provenance tags; never inject PII or unverified as fact
        │
        ▼
[2. Ephemeral Slot Binding (apps/core/native/sft.py)]
   - Map surface entity tokens -> <slot_0>..<slot_31> deterministically per request
   - Format prompt with SFT_FORMAT_VERSION ("zyrquen.sft.v1") & SFT_SEP ("\n### Response:\n")
        │
        ▼
[3. Native Tokenizer (ZyrquenTokenizer schema=zyrquen.tokenizer.v2)]
   - NFC normalize -> preserve control/slot IDs -> byte-level BPE merges
   - Enforce input_tokens <= max_seq_len
        │
        ▼
[4. ZyrquenModel Forward / Autoregressive Generation (CPU-safe)]
   - Embedding (tied with LM head) -> N × [Pre-RMSNorm + RoPE Causal SDPA + Pre-RMSNorm + SwiGLU FFN]
   - Final RMSNorm -> Linear LM Head -> stop at <|eos|> or max_new_tokens
        │
        ▼
[5. Slot Restoration & Self-Verification Guard (Phase 16 / Phase 19)]
   - Restore <slot_k> -> original surface entities
   - Classify reasoning assertions (fact | assumption | unverified)
   - Validate DAG plan / dependency syntax / tool allowlist (default-deny)
```

---

## 3. Core Model Building Blocks (Verified in `apps/core/native/model.py`)

| Component | Implementation Detail | Purpose in V11 |
|---|---|---|
| **Token Embedding** | `nn.Embedding(vocab_size, d_model)` tied to `lm_head` (`tie_embeddings=True`) | ประหยัดพารามิเตอร์บน Budget `<= 5M` และผูกความหมาย input/output ของ `<slot_k>` |
| **Position Encoding** | Rotary Position Embedding (`_rope_cache`, `theta=10000.0`, non-persistent buffers) | รองรับการเรียนรู้ตำแหน่งสัมพัทธ์และเตรียมขยาย context สำหรับ OOD chain (ต้องตรวจสอบเรื่อง extrapolated `max_seq_len`) |
| **Normalization** | `RMSNorm(dim, eps=1e-5)` แบบ Pre-Norm ทั้งก่อน Attention และก่อน FFN | เสถียรภาพของ Gradient เมื่อฝึกยาวถึง `10,000` Steps |
| **Attention** | `CausalSelfAttention` ใช้ `F.scaled_dot_product_attention(..., is_causal=True)` แบบ No-Bias QKV/Proj | ประมวลผลความสัมพันธ์หลายขั้นภายใน Context |
| **Feed-Forward** | `FeedForward` แบบ SwiGLU (`silu(gate(x)) * up(x)` -> `down`), No-Bias | เพิ่มความจุเชิงตรรกะและ non-linear composition ต่อพารามิเตอร์ |

---

## 4. Architecture Non-Modification Boundaries for V11 First Wave

- **ไม่เปลี่ยน** ชื่อ Class `ZyrquenModel` หรือ Key Format ของ `state_dict` ที่ `NativeModelLoader` และ `EvaluationEngine.evaluate_native_model` คาดหวัง
- **ไม่เพิ่ม** External Model Adapter, Remote Embedding API หรือ Hybrid External Fallback
- **การขยายเชิงโครงสร้างในอนาคต** (เช่น เพิ่ม `n_layers`, `d_model`, `max_seq_len`, หรือเพิ่ม RoPE scaling / auxiliary loss head) ต้องผ่านการพิสูจน์ใน `V11_MODEL_SPECIFICATION.md` และ Tier-2 `architecture.modify` approval ก่อนเสมอ

---

## 5. Mandatory Truthfulness Sections

### ASSUMPTIONS
- `NativeInferenceEngine` และ `StreamingInferenceEngine` จะถูกอัปเดต (ในเฟส V10-A/V11 integration ที่ได้รับอนุมัติ) ให้รองรับ ephemeral slot bind/restore แบบ opt-in/metadata-driven ตรงกับ `EvaluationEngine.evaluate_native_model`
- โครงสร้าง `ZyrquenModel` มีความสามารถเพียงพอสำหรับการเรียนรู้ symbolic composition ที่ความยาว context `<= 256` เมื่อฝึกต่อเนื่อง `10,000` Steps

### OPEN DECISIONS
- **OD-AR-01:** ใน Stage 6 (OOD Length Transfer) จะคง `rope_theta = 10000.0` และ `max_seq_len = 256` ตาม `V11-Tier0` หรือเปิด `max_seq_len = 512` ใน `V11-Tier1` (ต้องใช้ RoPE interpolation/NTK หรือ pre-allocate `max_seq_len=512` ตั้งแต่ Stage 1)
- **OD-AR-02:** จะคง `tie_embeddings = True` ตลอด V11 หรือเปิดทางเลือก untied เมื่อขึ้น Tier-1/Tier-2

### NOT VERIFIED
- ความสามารถในการ generalize ข้าม hop depth 4–6+ ของ Pre-Norm RoPE 4-layer Transformer หลังฝึก 10,000 Steps บนข้อมูล V11 ยัง **NOT VERIFIED** (ต้องทดสอบจริงหลังเปิด Runtime)
- ผลกระทบของ `dropout = 0.0` เทียบกับ `dropout = 0.05/0.1` ต่อการกัน Overfitting ที่ `10,000` Steps บนชุดข้อมูลสังเคราะห์ขนาดเล็ก/กลาง ยัง **NOT VERIFIED**
