import pytest

from apps.core.training.cost_limits import DEFAULT_MAX_RUNTIME_SECONDS, cost_controller_from_env


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_default_is_one_hour_fail_closed():
    clk = Clock()
    c = cost_controller_from_env({}, clk)
    c.start()
    clk.t = DEFAULT_MAX_RUNTIME_SECONDS - 1
    assert not c.should_stop()
    clk.t = DEFAULT_MAX_RUNTIME_SECONDS
    assert c.exceeded() == "max_runtime_seconds"


def test_budget_with_rate():
    clk = Clock()
    c = cost_controller_from_env({"ZYRQUEN_TRAINING_HOURLY_RATE_USD": "4",
                                  "ZYRQUEN_TRAINING_MAX_BUDGET_USD": "2"}, clk)
    c.start()
    clk.t = 1800
    assert c.exceeded() == "max_budget_usd"


def test_budget_without_rate_is_rejected():
    with pytest.raises(ValueError):
        cost_controller_from_env({"ZYRQUEN_TRAINING_MAX_BUDGET_USD": "5"})


def test_bad_and_nonpositive_values_rejected():
    with pytest.raises(ValueError):
        cost_controller_from_env({"ZYRQUEN_TRAINING_MAX_RUNTIME_SECONDS": "abc"})
    with pytest.raises(ValueError):
        cost_controller_from_env({"ZYRQUEN_TRAINING_MAX_RUNTIME_SECONDS": "0"})


def test_gpu_hours_with_gpu_count():
    clk = Clock()
    c = cost_controller_from_env({"ZYRQUEN_TRAINING_MAX_GPU_HOURS": "2",
                                  "ZYRQUEN_TRAINING_GPU_COUNT": "4"}, clk)
    c.start()
    clk.t = 1800  # 0.5h * 4 gpus = 2 gpu-hours
    assert c.exceeded() == "max_gpu_hours"
