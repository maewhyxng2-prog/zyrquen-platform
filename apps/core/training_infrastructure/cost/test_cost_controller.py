# Phase 4.5 - ของจริงเท่านั้น ห้ามจำลอง
# ไม่มี clock ปลอม ใช้ time.monotonic จริง + time.sleep จริงให้เวลาผ่านจริง
import time
import pytest
from apps.core.training_infrastructure.cost.cost_controller import CostController, CostLimits, LimitExceeded

def test_real_limits_rejects_invalid():
    with pytest.raises(ValueError):
        CostLimits(gpu_count=0, hourly_rate_usd=1.0)
    with pytest.raises(ValueError):
        CostLimits(gpu_count=1, hourly_rate_usd=-1.0)
    with pytest.raises(ValueError):
        CostLimits(gpu_count=1, hourly_rate_usd=1.0, max_runtime_seconds=0)

def test_real_fresh_not_exceeded():
    c = CostController(CostLimits(gpu_count=1, hourly_rate_usd=1.0, max_runtime_seconds=3600))
    c.start()
    s = c.snapshot()
    assert s["elapsed_seconds"] >= 0
    assert s["gpu_hours"] >= 0
    assert s["cost_usd"] >= 0
    assert c.exceeded() is None
    assert c.should_stop() is False
    c.enforce()
    c.pause()

def test_real_elapsed_grows_with_real_time():
    c = CostController(CostLimits(gpu_count=1, hourly_rate_usd=1.0))
    c.start()
    time.sleep(0.05)
    s1 = c.snapshot()
    assert s1["elapsed_seconds"] >= 0.04
    c.pause()
    e1 = c.elapsed_seconds()
    time.sleep(0.05)
    e2 = c.elapsed_seconds()
    assert abs(e2 - e1) < 0.02

def test_real_exceeded_after_real_time():
    c = CostController(CostLimits(gpu_count=1, hourly_rate_usd=1.0, max_runtime_seconds=0.01))
    c.start()
    time.sleep(0.03)
    assert c.exceeded() == "max_runtime_seconds"
    assert c.should_stop() is True
    with pytest.raises(LimitExceeded):
        c.enforce()
    c.pause()
