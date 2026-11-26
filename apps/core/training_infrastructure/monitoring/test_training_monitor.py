# Phase 4.4 - ของจริงเท่านั้น ห้ามจำลอง
# ไม่มี clock ปลอม ไม่มีเวลา ปลอม ใช้ time.monotonic จริง + ไฟล์จริงบนดิสก์
from apps.core.training_infrastructure.monitoring.training_monitor import TrainingMonitor

def test_real_empty_history_and_summary(tmp_path):
    m = TrainingMonitor(tmp_path / "log.jsonl")
    assert m.history() == []
    assert m.summary() == {"records": 0}

def test_real_log_then_history(tmp_path):
    p = tmp_path / "log.jsonl"
    m = TrainingMonitor(p)
    m.log(1, 2.5, 0.001)
    m.log(2, 2.0, 0.001)
    assert p.exists()
    h = m.history()
    assert len(h) == 2
    assert h[0]["step"] == 1
    assert h[0]["loss"] == 2.5
    assert h[1]["step"] == 2
    assert h[1]["loss"] == 2.0

def test_real_summary_best_and_last(tmp_path):
    m = TrainingMonitor(tmp_path / "log.jsonl")
    m.log(1, 3.0, 0.001)
    m.log(2, 1.5, 0.001)
    m.log(3, 2.0, 0.001)
    s = m.summary()
    assert s["records"] == 3
    assert s["last_step"] == 3
    assert s["last_loss"] == 2.0
    assert s["best_loss"] == 1.5

def test_real_history_tolerates_corrupt_line(tmp_path):
    p = tmp_path / "log.jsonl"
    m = TrainingMonitor(p)
    m.log(1, 2.5, 0.001)
    # แปะบรรทัดพังจริงลงไฟล์ แล้ว history ต้องยังอ่านบรรทัดดีได้
    with p.open("a", encoding="utf-8") as f:
        f.write("{broken json\n")
    m.log(2, 2.0, 0.001)
    h = m.history()
    assert len(h) == 2
    assert h[-1]["step"] == 2
