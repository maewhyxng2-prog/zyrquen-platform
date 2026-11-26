import threading
import pytest
from apps.core.multi_user import (
    MultiUserManager,
    UserLimitExceededError,
)

def test_01_isolation():
    m = MultiUserManager()
    m.add_message("user-a", "user", "hello A")
    m.add_message("user-b", "user", "hello B")
    ha = m.get_history("user-a")
    hb = m.get_history("user-b")
    assert len(ha) == 1
    assert len(hb) == 1
    assert ha[0]["content"] == "hello A"
    assert hb[0]["content"] == "hello B"
    ha.append({"role": "user", "content": "fake"})
    assert len(m.get_history("user-a")) == 1

def test_02_request_limit():
    m = MultiUserManager(
        max_requests_per_minute=2
    )
    m.record_request("user-a")
    m.record_request("user-a")
    with pytest.raises(UserLimitExceededError):
        m.record_request("user-a")
    m.record_request("user-b")
    u = m.get_usage("user-a")
    assert u["requests_last_minute"] == 2

def test_03_token_limit():
    m = MultiUserManager(
        max_tokens_per_minute=100
    )
    m.record_request("user-a", tokens=60)
    with pytest.raises(UserLimitExceededError):
        m.record_request("user-a", tokens=60)
    u = m.get_usage("user-a")
    assert u["tokens_last_minute"] == 60

def test_04_concurrent_and_clear():
    m = MultiUserManager(max_history=50)
    m.add_message("user-a", "user", "keep A")
    m.add_message("user-b", "user", "keep B")

    def worker(n):
        for i in range(20):
            m.add_message(
                "user-a", "user", f"m-{n}-{i}"
            )

    threads = [
        threading.Thread(target=worker, args=(n,))
        for n in range(10)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(m.get_history("user-a")) == 50
    m.clear_user("user-a")
    assert m.get_history("user-a") == []
    assert len(m.get_history("user-b")) == 1
    assert (
        m.get_history("user-b")[0]["content"]
        == "keep B"
    )
