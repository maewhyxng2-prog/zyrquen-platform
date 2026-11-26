# Phase 3 — ZYRQUEN Native AI Architecture

เป้าหมาย: Independently Developed AI Model

## 1. Model Architecture
- Transformer-based Neural Architecture, Token Embedding, Positional Encoding
- Multi-Head Self-Attention, Feed-Forward Network, Normalization, Residual Connections
- Output Projection, Autoregressive Text Generation
- เริ่มด้วย Decoder-only Transformer ฝึกจาก Random Initialization (ไม่โหลดน้ำหนัก Qwen หรือโมเดลอื่น)

## 2. Native Tokenizer
- รองรับภาษาไทยและอังกฤษ
- Text Normalization, Unicode Handling, Subword Tokenization, Vocabulary Training
- Special Tokens, Encode / Decode, Tokenizer Versioning
- สร้าง Vocabulary จาก Dataset จริง

## 3. Training Pipeline
Initialize Weights → Load Dataset → Tokenize → Batches → Forward Pass → Loss → Backpropagation → Optimizer Update → Save Checkpoint → Evaluate
(ใช้ PyTorch ได้ โดย Architecture และ Weights เป็นของ ZYRQUEN)

## 4. Dataset Preparation
- Import, Cleaning, Unicode Normalization, Duplicate Detection, Quality Filtering
- Language Classification, Train / Validation / Test Split, Versioning, Data Provenance
- ตรวจสิทธิ์การใช้ข้อมูลและป้องกันข้อมูลส่วนบุคคลรั่วไหล

## 5. Checkpoint & Model Versioning
- Checkpoints, Training Step Tracking, Optimizer State
- Configuration / Tokenizer / Dataset Version
- Model Registry, Rollback, Artifact Integrity Verification

## 6. Evaluation Engine
| ตัวชี้วัด | วัตถุประสงค์ |
|---|---|
| Training Loss | ติดตามการเรียนรู้ |
| Validation Loss | ตรวจสอบการ Generalize |
| Perplexity | ประเมิน Language Modeling |
| Token Accuracy | วัดการทำนาย Token |
| Thai Benchmark | ประเมินภาษาไทย |
| English Benchmark | ประเมินภาษาอังกฤษ |
| Safety Evaluation | ตรวจสอบความเสี่ยง |
| Regression Test | ป้องกันความสามารถถดถอย |

## ลำดับการลงมือสร้างจริง
| ลำดับ | โมดูล | ผลลัพธ์ที่ต้องได้ |
|---|---|---|
| 3.1 | Model Architecture | โมเดลจาก Random Initialization |
| 3.2 | Native Tokenizer | Vocabulary และ Encode/Decode |
| 3.3 | Dataset Preparation | ชุดข้อมูลที่ผ่านการตรวจสอบ |
| 3.4 | Training Pipeline | ฝึกและปรับ Weights ได้จริง |
| 3.5 | Checkpoint Registry | บันทึกและกู้คืนการฝึก |
| 3.6 | Evaluation Engine | รายงานผลทดสอบโมเดล |

ข้อกำหนด: โมเดลเริ่มต้นอาจมีขนาดเล็กเพื่อทดสอบกระบวนการ ไม่อ้างความฉลาดระดับโมเดลใหญ่จนกว่ามีผลฝึกและ Benchmark รองรับ การฝึกจริงต้องใช้ GPU Cloud

เริ่มที่ 3.1 — ตรวจ `apps/core/engine.py` ก่อนเพื่อไม่ให้ซ้ำซ้อนกับ Engine เดิม
