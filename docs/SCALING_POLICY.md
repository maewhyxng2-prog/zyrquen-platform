# ZYRQUEN Ω∞ — SCALING POLICY

**Status:** APPROVED POLICY — 21/11/2569
**Principle:** 5M is the starting point, not the final limit.

> 5M เป็นเพียงจุดเริ่มต้น ไม่ใช่จุดสิ้นสุด
> และไม่ควรจำกัด ZYRQUEN ไว้ที่ขนาดโมเดลใดโมเดลหนึ่งตลอดโครงการ

## 1. Progressive Model Scaling Architecture

ตัวเลขนี้เป็นเป้าหมายการทดลอง ไม่ใช่การรับรองว่า Hardware ปัจจุบันรองรับได้ทั้งหมด

| ระดับ | Parameters | เป้าหมาย |
|---|---|---|
| v5 | 0.5M | แก้ Token และ Generation |
| v6 | 1M | Representation |
| v7 | 2M | Reasoning |
| v8 | 5M | Knowledge Integration |
| v9 | 10M | Multi-step Planning |
| v10 | 25M | Adaptive Learning |
| v11+ | 50M → 100M → 500M → 1B+ | ขยายสู่ NGI |

### 1B+

Long-term experimental target, not a fixed maximum.
ขยายต่อได้ตามความสามารถ ทรัพยากร และผลการประเมินจริง

## 2. กติกาสถาปัตยกรรม — วางตั้งแต่ตอนนี้

1. **ไม่ Hardcode เพดาน 5M** ในระบบระยะยาว
2. รองรับ **CPU และ GPU Backend**
3. รองรับ **Mixed Precision** เมื่อ Hardware รองรับ
4. รองรับ **Checkpoint และ Resume Training**
5. รองรับ **Model Scaling โดยไม่ทำลาย Weights รุ่นเดิม**
6. มี **Memory และ Compute Budget** ตรวจสอบก่อนฝึกทุกครั้ง
7. **ประเมินความสามารถก่อนอนุมัติการขยาย** ทุกระดับ

## 3. แยกให้ชัด 2 ชั้น

### ชั้นที่ 1 — Hardware ปัจจุบัน
- Device: 【entity-HONOR¦canonical_name=HONOR】 X6b
- Backend: CPU only (ปัจจุบัน)
- Cap ปัจจุบัน: 5M params, max sequence 256, max batch 4
- หลักฐานปัจจุบัน: v7 500 Steps PASS
    - Val Exact 0.16, First-Token 0.16
    - Verification 0.56, Teacher-Forced 0.56, Gap 0.40
    - Overfit 4/4 PASS
    - Commit: `a25361d` — code only, no weights

### ชั้นที่ 2 — Architecture ระยะยาว
- ต้องขยายได้เรื่อยๆ ตามผลประเมิน
- ไม่ผูกกับ Hardware ใด Hardware หนึ่ง
- ไม่ผูกกับขนาดโมเดลใดโมเดลหนึ่ง

## 4. Scaling Gate — ก่อนขยายทุกครั้งต้องผ่าน

- [ ] Eval ของระดับปัจจุบันผ่าน First-Token / Exact ตามเกณฑ์ที่ตั้งไว้
- [ ] Checkpoint ปัจจุบันบันทึกครบ + Resume ได้
- [ ] Memory / Compute Budget ตรวจสอบแล้วว่าพอ
- [ ] ได้รับอนุมัติแยกต่างหากก่อนฝึก / ก่อนขยาย
- [ ] Weights รุ่นเดิมไม่ถูกเขียนทับ

## 5. ข้อห้ามที่ยังใช้เหมือนเดิม

- ห้าม Commit / Push Weights / Checkpoints (`*.pt` / `checkpoints/`)
- ห้าม Train / Deploy / Auto-promote โดยไม่มีอนุมัติแยก
- ห้ามเปิด Phase 21 — Phase 20 คือ Phase สุดท้ายของ Roadmap 11–20
- ห้ามอ้างว่า 5M / 1B+ คือขนาดที่ Hardware ปัจจุบันรองรับทั้งหมด

## 6. สรุป

- **5M = จุดที่เริ่มได้จริงวันนี้**
- **1B+ = เป้าหมายทดลองระยะยาว**
- **NGI = เป้าหมายสุดท้าย ไม่ใช่ขนาดโมเดล**

ZYRQUEN Ω∞ — Built for the Edge. Intelligence, Native.
