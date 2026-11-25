"""
Isolated Benchmark Fixtures for ZYRQUEN Native AI Core (P1-1).

Strict Leakage Policy:
- TRAINING_CORPUS_LINES and SEED_TRIPLES are exclusively for populating the
  isolated benchmark SQLite database.
- EVALUATION_FIXTURES are strictly disjoint from TRAINING_CORPUS_LINES so
  memorized training lines can never masquerade as generalization.
"""

import re

SEED_TRIPLES: list[tuple[str, str, str]] = [
    ("ZYRQUEN", "ใช้งาน", "Python Native Core"),
    ("Python Native Core", "พัฒนาโดย", "ทีมวิจัยอัลฟ่า"),
    ("ทีมวิจัยอัลฟ่า", "ตั้งอยู่ที่", "ศูนย์ปฏิบัติการโอเมก้า"),
    ("ศูนย์ปฏิบัติการโอเมก้า", "ใช้ฐานข้อมูล", "SQLite WAL"),
    ("SQLite WAL", "รองรับ", "Parameterized Queries"),
    ("โมดูล AST", "ตรวจสอบ", "นิพจน์คณิตศาสตร์"),
    ("A", "มากกว่า", "B"),
    ("คาร์บอน", "มีเลขอะตอม", "6"),
]

# Training corpus used strictly for N-Gram checkpoint training in isolated DB.
# Kept strictly disjoint from every evaluation prompt below.
TRAINING_CORPUS_LINES: list[str] = [
    "ระบบ zyrquen ประมวลผลคณิตศาสตร์ผ่าน ast อย่างปลอดภัย",
    "ระบบ zyrquen จัดเก็บความจำในกราฟความรู้ sqlite",
    "ระบบ zyrquen วางแผนงานแบบ dag จากสถานะฐานข้อมูลจริง",
    "ระบบ zyrquen ไม่ส่งข้อมูลไปยังโมเดลภายนอกโดยเด็ดขาด",
    "ระบบ zyrquen ตรวจสอบคำตอบก่อนบันทึกทุกครั้ง",
    "การฝึกโมเดลภายในต้องผ่านขั้นตอน approval gate ก่อนเสมอ",
    "ชุดข้อมูลที่ดีต้องไม่มี data leakage ระหว่าง train และ test",
    "การค้นคว้าเว็บต้องตรวจ allowlist และแยกหลักฐานภายนอกเสมอ",
    "กราฟความรู้รองรับการอนุมานความสัมพันธ์สองช่วงและหลายช่วง",
    "ทุกคำสั่งสำคัญต้องบันทึกใน audit log เพื่อตรวจสอบย้อนกลับ",
]

# Strictly held-out prompts used for Negative Abstention / OOV / Generalization probes.
HELD_OUT_NEGATIVE_PROMPTS: list[dict] = [
    {
        "id": "NEG-01",
        "prompt": "ทฤษฎีสัมพัทธภาพทั่วไปคืออะไร",
        "mode": "auto",
        "expected_status": "NOT_LEARNED",
        "description": "Unlearned Thai physics question (probing short-syllable false positive)",
    },
    {
        "id": "NEG-02",
        "prompt": "กลไกการสังเคราะห์แสงในคลอโรพลาสต์ทำงานอย่างไร",
        "mode": "auto",
        "expected_status": "NOT_LEARNED",
        "description": "Unlearned Thai biology question",
    },
    {
        "id": "NEG-03",
        "prompt": "หลุมดำมวลยิ่งยวดเกิดขึ้นได้อย่างไร",
        "mode": "auto",
        "expected_status": "NOT_LEARNED",
        "description": "Unlearned Thai astronomy question",
    },
    {
        "id": "NEG-04",
        "prompt": "อะไรคืออะไร",
        "mode": "auto",
        "expected_status": "NOT_LEARNED",
        "description": "Thai stopword-only query must abstain",
    },
    {
        "id": "NEG-05",
        "prompt": "Explain quantum entanglement",
        "mode": "auto",
        "expected_status": "NOT_LEARNED",
        "description": "Unlearned English physics prompt must abstain",
    },
    {
        "id": "NEG-06",
        "prompt": "Explain quantum computing architecture",
        "mode": "model",
        "expected_status": "NOT_LEARNED",
        "description": "OOV English prompt in N-Gram model mode must abstain",
    },
    {
        "id": "NEG-07",
        "prompt": "ทฤษฎีสัมพัทธภาพทั่วไปคืออะไร",
        "mode": "model",
        "expected_status": "NOT_LEARNED",
        "description": "Unlearned Thai prompt with partial stopword/syllable vocab overlap in model mode must abstain",
    },
    {
        "id": "NEG-08",
        "prompt": "ถ้า ฝนตก แล้ว ถนนลื่น หาก แดดออก จะเกิดอะไรขึ้น",
        "mode": "auto",
        "expected_status": "UNABLE_TO_INFER",
        "description": "Undetermined causal forward-chaining when observed fact does not match rule antecedent",
    },
    {
        "id": "NEG-09",
        "prompt": "ทุก นก เป็น สัตว์มีปีก และ ค้างคาว เป็น สัตว์มีปีก ดังนั้น ค้างคาว เป็น นก หรือไม่",
        "mode": "auto",
        "expected_status": "UNABLE_TO_INFER",
        "description": "Undetermined categorical syllogism (affirming the consequent fallacy must abstain)",
    },
]


# Strictly held-out unseen lines used exclusively to measure neural generalization & perplexity
# without training exposure (contains overlapping ZYRQUEN domain vocabulary in unseen sequences).
HELD_OUT_NEURAL_TEST_LINES: list[str] = [
    "ระบบ zyrquen ตรวจสอบความถูกต้องผ่านกราฟความรู้และบันทึกผล",
    "การวางแผนแบบ dag ต้องยืนยันหลักฐานก่อนอนุมัติงานทุกครั้ง",
    "ชุดข้อมูลที่ดีช่วยป้องกันปัญหาการจำคำตอบในโมเดลภายใน",
    "การตรวจสอบ allowlist ช่วยป้องกันการรั่วไหลสู่โมเดลภายนอก",
    "audit log บันทึกสถานะการทำงานของระบบอย่างต่อเนื่อง",
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def verify_fixture_isolation() -> dict:
    """
    Verify zero exact or substring contamination between TRAINING_CORPUS_LINES
    and HELD_OUT_NEGATIVE_PROMPTS + HELD_OUT_NEURAL_TEST_LINES.
    """
    train_norm = {_norm(line) for line in TRAINING_CORPUS_LINES}
    overlaps: list[dict] = []

    for item in HELD_OUT_NEGATIVE_PROMPTS:
        p_norm = _norm(item["prompt"])
        if p_norm in train_norm:
            overlaps.append({"id": item["id"], "prompt": item["prompt"], "type": "exact"})
            continue
        for tr in train_norm:
            if len(p_norm) >= 8 and (p_norm in tr or tr in p_norm):
                overlaps.append({"id": item["id"], "prompt": item["prompt"], "type": "substring", "matched_train": tr})

    for idx, line in enumerate(HELD_OUT_NEURAL_TEST_LINES):
        l_norm = _norm(line)
        if l_norm in train_norm:
            overlaps.append({"id": f"NEURAL-TEST-{idx+1}", "prompt": line, "type": "exact"})
            continue
        for tr in train_norm:
            if len(l_norm) >= 8 and (l_norm in tr or tr in l_norm):
                overlaps.append({"id": f"NEURAL-TEST-{idx+1}", "prompt": line, "type": "substring", "matched_train": tr})

    return {
        "isolated": len(overlaps) == 0,
        "training_records": len(TRAINING_CORPUS_LINES),
        "heldout_negative_cases": len(HELD_OUT_NEGATIVE_PROMPTS),
        "heldout_neural_test_lines": len(HELD_OUT_NEURAL_TEST_LINES),
        "overlaps": overlaps,
    }
