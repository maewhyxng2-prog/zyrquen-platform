import time
import pytest
from apps.core.resource import (
    ResourceManager,
    ResourceLimitExceededError,
)

def test_01_snapshot_is_real():
    m = ResourceManager()
    snap = m.snapshot()
    assert snap["ram_mb"] > 0
    assert snap["vram_mb"] >= 0
    assert isinstance(
        snap["vram_available"], bool
    )
    assert snap["timestamp"] > 0

def test_02_token_limit():
    m = ResourceManager(
        max_tokens_per_request=10
    )
    m.check_request(tokens=10)
    with pytest.raises(
        ResourceLimitExceededError
    ):
        m.check_request(tokens=11)

def test_03_time_limit():
    m = ResourceManager(
        max_seconds_per_request=1
    )
    m.check_request(
        tokens=1, started_at=time.time()
    )
    with pytest.raises(
        ResourceLimitExceededError
    ):
        m.check_request(
            tokens=1,
            started_at=time.time() - 100,
        )

def test_04_ram_limit_and_pass():
    m = ResourceManager(
        max_ram_mb=0.001,
        max_tokens_per_request=100,
    )
    with pytest.raises(
        ResourceLimitExceededError
    ):
        m.check_request(tokens=1)
    ok = ResourceManager(
        max_ram_mb=100000,
        max_tokens_per_request=100,
    )
    snap = ok.check_request(tokens=1)
    assert snap["ram_mb"] > 0
