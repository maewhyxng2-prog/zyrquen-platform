from phases.phase14 import compare_benchmark, evaluate_case, regression_gate, reliability_score

def test_evaluate_pass_and_fail():
    assert evaluate_case({"name": "a", "ran": True, "passed": True, "evidence": "e1"})["status"] == "PASS"
    assert evaluate_case({"name": "b", "ran": True, "passed": False, "evidence": "e2"})["status"] == "FAIL"

def test_evaluate_not_run_never_pass():
    out = evaluate_case({"name": "c", "ran": False, "passed": True, "evidence": "e3"})
    assert out["status"] == "NOT RUN"
    assert out["status"] != "PASS"

def test_evaluate_blocked():
    out = evaluate_case({"name": "d", "ran": True, "blocked": True, "evidence": "e4", "reason": "need data"})
    assert out["status"] == "BLOCKED"
    assert out["reason"] == "need data"

def test_benchmark_regression_detected():
    out = compare_benchmark({"accuracy": 0.9}, {"accuracy": 0.8})
    assert out["regression"] is True
    assert out["diff"]["accuracy"]["delta"] == -0.1 or abs(out["diff"]["accuracy"]["delta"] + 0.1) < 1e-9

def test_benchmark_no_regression_and_gate_allows():
    out = compare_benchmark({"accuracy": 0.8}, {"accuracy": 0.9})
    assert out["regression"] is False
    gate = regression_gate({"accuracy": 0.8}, {"accuracy": 0.9})
    assert gate["allowed"] is True

def test_reliability_excludes_blocked_not_run_and_gate_blocks():
    results = [
        {"status": "PASS"}, {"status": "PASS"}, {"status": "FAIL"},
        {"status": "BLOCKED"}, {"status": "NOT RUN"},
    ]
    # PASS 2 / (PASS 2 + FAIL 1) = 0.666... NOT 2/5
    score = reliability_score(results)
    assert abs(score - 2 / 3) < 1e-9
    gate = regression_gate({"accuracy": 0.9}, {"accuracy": 0.5})
    assert gate["allowed"] is False
