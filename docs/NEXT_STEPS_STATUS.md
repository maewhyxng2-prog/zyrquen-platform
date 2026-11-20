# สถานะงาน 7 ข้อ (ตรวจจริง ณ ตอนแพ็ค)

| # | งาน | สถานะ | หลักฐาน / ข้อจำกัด |
|---|---|---|---|
| 1 | download_model.py | ตรวจโค้ดแล้ว ไม่แก้ | ไม่ได้รัน (ต้องใช้เน็ต + huggingface_hub). หมายเหตุ: ดึง Qwen เพื่อทดสอบ runtime เท่านั้น ไม่ใช่โมเดลของ ZYRQUEN |
| 2 | .gitignore | เพิ่มกฎที่ขาด | เพิ่ม *.db, cache, checkpoints/, !.env.example (เดิม `.env.*` ซ่อน .env.example) |
| 3 | apps/api/Dockerfile | แก้ PYTHONPATH + ZYRQUEN_MODEL_PATH | ยังไม่ได้ docker build (ไม่มี Docker) |
| 4 | api-tests.yml | เพิ่ม PYTHONPATH | ตรวจ import resolution: ก่อนแก้ `apps.core` หาไม่เจอ, หลังแก้เจอ. ยังไม่ได้รัน pytest/Actions จริง |
| 5 | Cloud Deployment | ยังไม่ทำ | ต้องมีบัญชี/สิทธิ์ผู้ให้บริการคลาวด์ |
| 6 | PostgreSQL + Volume | เตรียม docker-compose.yml + .env.example | ยังไม่ได้รัน; ยังไม่มี migration/สร้างตาราง (alembic อยู่ใน requirements แต่ไม่มีโค้ด) |
| 7 | Native Model Architecture | เขียน apps/core/native (config, model, tests) | ยังไม่ได้รัน เพราะไม่มี torch ในสภาพแวดล้อม; compile ผ่านเท่านั้น |

ข้อสังเกต: `model_loader.py` ใช้ torch + transformers แต่ไม่อยู่ใน requirements.txt จึงจะ degraded เสมอจนกว่าจะเพิ่ม

## Phase 3 progress
| ขั้น | สถานะ | หลักฐาน |
|---|---|---|
| 3.1 Model Architecture | เขียนแล้ว ยังไม่ได้รันเทสต์ | ไม่มี torch ในสภาพแวดล้อมที่แพ็ค |
| 3.2 Native Tokenizer | เสร็จ + ทดสอบแล้ว | `apps/core/native/tokenizer.py` (byte-level BPE, stdlib ล้วน) 14 เทสต์ผ่านด้วย runner ชั่วคราว (ไม่มี pytest ในที่แพ็ค); เพิ่ม step ใน CI แล้วแต่ยังไม่เคยรันบน Actions |
| 3.3–3.6 | ยังไม่ได้เริ่ม | |

หมายเหตุ 3.2: โค้ดฝึก vocabulary จาก corpus ที่ส่งเข้าไปเท่านั้น ยังไม่ได้ฝึกกับ Dataset จริง (ยังไม่มี Dataset) จึงยังไม่มีไฟล์ tokenizer.json จริง
