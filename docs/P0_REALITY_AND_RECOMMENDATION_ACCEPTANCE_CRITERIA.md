# ZYRQUEN Ω∞ — P0 Acceptance Criteria: Reality Over Appearance

**Quality Principle:** **REALITY OVER APPEARANCE** — *Real Intelligence · Real Tools · Real Recommendations · Real Evidence · Real Performance*

หลักการสูงสุด: ความสามารถจริงเหนือภาพลักษณ์ ไม่สร้างความสามารถเพื่อให้ดูเก่ง ไม่แนะนำสิ่งที่ใช้ไม่ได้ และไม่รายงานความสำเร็จที่ไม่มีหลักฐาน

---

## 1. กฎบังคับ 6 ข้อ (Real Capability, Real Recommendations)

1. **Real Products** — แนะนำเฉพาะผลิตภัณฑ์ บริการ หรือเครื่องมือที่ตรวจสอบตัวตนและแหล่งที่มาได้จริง ห้ามสร้างรายการเพื่อเติมจำนวน
2. **Real Functionality** — ปุ่ม เมนู และเครื่องมือต้องทำงานได้จริง ไม่ใช่หน้าตาจำลองหรือ Mock UI
3. **Real Availability** — ตรวจสอบสถานะความพร้อมให้บริการก่อนแนะนำเป็นตัวเลือกที่ใช้งานได้ (ห้ามแนะนำเครื่องมือที่หยุดให้บริการหรือถูกปิดใช้งานเป็นตัวเลือกพร้อมใช้)
4. **Real Evidence** — ทุกข้อเสนอแนะที่อาศัยข้อมูลภายนอกต้องแนบหลักฐานตรวจสอบย้อนกลับได้ครบถ้วน:
   - `source_id`
   - `source_url` (เมื่อมีแหล่งอ้างอิงเว็บ/ภายนอก)
   - `retrieved_at` (ISO-8601 UTC timestamp)
   - `evidence_content`
   - `verification_status` ∈ `{VERIFIED, UNVERIFIED, NOT_FOUND, UNAVAILABLE, STALE, BLOCKED}`
   - `freshness` (เมื่อความทันสมัยมีผลต่อคำแนะนำ)
5. **Honest Limitations** — หากตรวจสอบไม่ได้ ไม่มีหลักฐาน หรือ Runtime ยังขาด dependency ต้องแจ้งข้อจำกัดตรง ๆ ห้ามแต่งข้อมูลทดแทน
6. **Real Evaluation** — ความสามารถของ Native AI Core ต้องพิสูจน์ด้วย Benchmark และผลทดสอบที่รันจริง ห้ามใช้ Mock Metrics เป็นคะแนนความสามารถ

---

## 2. ตารางพฤติกรรมมาตรฐาน (Mandatory Behavior Matrix)

| สถานการณ์ | สถานะมาตรฐาน | พฤติกรรมที่ ZYRQUEN ต้องทำ |
|---|---|---|
| เครื่องมือใช้งานได้จริงและผ่านการตรวจหลักฐาน | `VERIFIED` | แนะนำได้พร้อมแหล่งที่มาและหลักฐานอ้างอิง |
| พบเครื่องมือแต่ยังไม่ได้ตรวจสอบ | `UNVERIFIED` | แสดงสถานะว่ายังไม่ยืนยัน ห้ามอ้างว่าผ่านการตรวจแล้ว |
| เครื่องมือหยุดให้บริการ / ปิดใช้งาน | `UNAVAILABLE` | ไม่แนะนำเป็นตัวเลือกที่ใช้งานได้จริง |
| ไม่พบเครื่องมือหรือหลักฐานที่เหมาะสม | `NOT_FOUND` | แจ้งว่าไม่พบตัวเลือกที่ยืนยันได้ (Abstention) |
| ข้อมูลล้าสมัยเกินเกณฑ์ | `STALE` | ไม่นำมาอ้างเป็นข้อมูลปัจจุบัน ต้องระบุความล้าสมัยหรือปฏิเสธ |
| ความสามารถยังพัฒนาไม่เสร็จ / ขาด Runtime | `BLOCKED` | ไม่แสดงว่าใช้งานได้แล้ว และระบุตัวบล็อกชัดเจน |

---

## 3. เกณฑ์ตรวจรับเชิงระบบใน P0 (Systematic P0 Verification Gates)

1. **Recommendation Verification** — คัดกรองคำแนะนำเฉพาะรายการที่ `verification_status == "VERIFIED"` และมีหลักฐานครบ ปฏิเสธรายการที่ `UNVERIFIED`, `STALE`, `UNAVAILABLE`, หรือ `NOT_FOUND`
2. **Tool Availability Verification** — ตรวจสอบสถานะจาก `ToolRegistry` และ `ExecutionPolicy` จริง ปฏิเสธเครื่องมือที่ไม่ลงทะเบียน ถูกปิดใช้งาน หรือยังไม่มี Execution Adapter
3. **Source Authenticity** — ตรวจสอบความถูกต้องของแหล่งที่มา (`source_id`, `retrieved_at`, `evidence_content`) ปฏิเสธ placeholder/fabricated domains และตรวจ SHA-256 provenance ของโมเดล/ชุดข้อมูล/tokenizer
4. **Broken Link Detection** — ปฏิเสธ URL ที่ผิดรูปแบบ ขาด scheme/host, scheme ไม่ปลอดภัย หรือ path/anchor อ้างอิงใน repository ที่ลิงก์ขาด
5. **Unsupported Capability Detection** — ตรวจสอบ Runtime, `EvaluationEngine`, `ReasoningEngine`, `PlanningEngine`, และ `ToolPolicy` เพื่อยืนยันว่าความสามารถที่ยังไม่เชื่อมหรือยังขาด dependency (`torch`, `pydantic`, trained weights) จะรายงานสถานะ `NOT_IMPLEMENTED` / `BLOCKED` / `not_configured` อย่างซื่อสัตย์
6. **False Success Prevention** — ยืนยันว่า Fail-Closed Gates (`capability_evaluation`, `ModelRegistry.attach_evaluation_evidence`, `NativeRuntime`, `EvaluationEngine`) ปฏิเสธ `PASS`/`verified`/`supported` เมื่อหลักฐานไม่ครบ `inference_executed=False` และยืนยันว่าไม่มี Legacy Mock (`15.5` / `0.85`) ใน `apps/core/evaluation/` รวมถึงไม่มีคะแนนประเมินจำลองใน UI preview

---

## 4. เกณฑ์ปิดงาน ZERO-MOCK IN REAL CAPABILITY EVALUATION

| รายการ | เป้าหมาย | สถานะตรวจรับใน P0 |
|---|---|---|
| Mock ใน Production Inference | `0` | ปฏิเสธเมื่อไม่พร้อม (`HTTP 503`) ไม่มี fallback mock |
| Mock ใน Real Capability Benchmark | `0` | ถอด `apps/core/evaluation/engine.py` และ `golden_dataset.json` แล้ว |
| Mock ที่ปะปนกับ Native Results | `0` | `EvaluationEngine` ใน `apps/core/native/evaluation/` บังคับ artifact + SHA-256 จริง |
| Mock ใน UI Preview (`capabilities` / `progress_metrics`) | `0` | แสดง `NOT RUN` / `ยังไม่ประเมินผล` เมื่อไม่มีการรัน PyTorch จริง |
| Mock ใน Isolated Unit Tests | อนุญาตเมื่อระบุชัด | จำกัดเฉพาะ fixture ภายใน `tests/` เท่านั้น |
| ผลทดสอบที่ไม่มีหลักฐาน | ไม่นับ `PASS` | บังคับสถานะ `BLOCKED` / `NOT RUN` |

---

## 5. การทดสอบมาตรฐาน (Executable Verification)

* Pure-Python Gate Runner: `python3 -m tests.benchmark.p0_reality_gate`
* Unit Test Suite: `python3 -m unittest tests/test_p0_reality_acceptance.py`
* เชื่อมต่อร่วมกับ P1-1 Capability Baseline (`tests/test_p1_1_capability_benchmark.py`)
