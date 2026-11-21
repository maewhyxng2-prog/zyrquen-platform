from phases.phase20 import SystemMaturity

def test_end_to_end_all_pass():
    m = SystemMaturity()
    results = {s: "PASS" for s in ["architecture", "reasoning", "planning", "memory", "learning", "safety"]}
    out = m.run_end_to_end(results)
    assert out["status"] == "PASS"

def test_end_to_end_one_fail_fails_all():
    m = SystemMaturity()
    results = {s: "PASS" for s in ["architecture", "reasoning", "planning", "memory", "learning", "safety"]}
    results["reasoning"] = "FAIL"
    out = m.run_end_to_end(results)
    assert out["status"] == "FAIL"
    assert out["detail"]["reasoning"] == "FAIL"

def test_slo_pass_and_fail():
    m = SystemMaturity()
    assert m.evaluate_slo(120, 0.005, True)["status"] == "PASS"
    assert m.evaluate_slo(800, 0.005, True)["status"] == "FAIL"  # latency
    assert m.evaluate_slo(120, 0.05, True)["status"] == "FAIL"  # error rate
    assert m.evaluate_slo(120, 0.005, False)["status"] == "FAIL"  # not recovered

def test_operational_readiness_not_ready_when_missing():
    m = SystemMaturity()
    full = {"monitoring": True, "incident_response": True, "security": True, "controls": True}
    assert m.readiness_checklist(full)["status"] == "ready"
    missing = dict(full, security=False)
    out = m.readiness_checklist(missing)
    assert out["status"] == "NOT READY"
    assert out["missing"] == ["security"]

def test_maintenance_blocks_on_regression_fail():
    m = SystemMaturity()
    assert m.check_maintenance(True, "FAIL")["status"] == "BLOCKED"
    assert m.check_maintenance(False, "PASS")["status"] == "BLOCKED"
    assert m.check_maintenance(True, "PASS")["status"] == "ok"

def test_status_never_counts_not_run_as_pass():
    m = SystemMaturity()
    # Missing step = NOT RUN, not PASS
    out = m.run_end_to_end({"architecture": "PASS"})
    assert out["status"] == "NOT RUN"
    assert out["status"] != "PASS"
    # Regression NOT RUN = NOT RUN, not PASS
    assert m.check_maintenance(True, "NOT RUN")["status"] == "NOT RUN"
