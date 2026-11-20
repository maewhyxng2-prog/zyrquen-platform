import time
from apps.core.evaluation import (
    evaluate_quality,
    run_single,
    run_stability,
)

def _gen(prompt):
    return "hello world test output"

def _slow_gen(prompt):
    time.sleep(0.01)
    return "hello slow world"

def test_01_quality():
    q = evaluate_quality(
        "hello world test",
        expected_keywords=["hello", "missing"],
    )
    assert q["is_valid"] is True
    assert q["word_count"] == 3
    assert q["keywords_found"] == 1
    assert q["keyword_coverage"] == 0.5
    q2 = evaluate_quality("   ")
    assert q2["is_valid"] is False
    assert q2["word_count"] == 0

def test_02_single_speed():
    r = run_single(_gen, "hi")
    assert r["success"] is True
    assert r["output"] == (
        "hello world test output"
    )
    assert r["token_count"] == 4
    assert r["latency_sec"] >= 0
    assert r["tokens_per_sec"] >= 0
    assert r["quality"]["is_valid"] is True

def test_03_stability_success():
    r = run_stability(
        _slow_gen, "hi", runs=3
    )
    assert r["runs"] == 3
    assert r["success_count"] == 3
    assert r["success_rate"] == 1.0
    assert r["avg_latency_sec"] >= 0.01
    assert r["min_latency_sec"] <= (
        r["max_latency_sec"]
    )
    assert len(r["results"]) == 3

def test_04_stability_with_failure():
    calls = {"n": 0}

    def flaky(prompt):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return "hello ok"

    r = run_stability(flaky, "hi", runs=3)
    assert r["success_count"] == 2
    assert r["success_rate"] == round(
        2 / 3, 4
    )
    assert len(r["results"]) == 3
