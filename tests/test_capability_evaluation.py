import copy

import pytest

from apps.core.intelligence.capability_evaluation import (
    CapabilityEvaluationViolation,
    DuplicateTestCaseError,
    TestCaseRegistry,
    evaluate_capability,
    validate_evaluation_result,
)


def _registry():
    registry = TestCaseRegistry()
    registry.register({
        "case_id": "lookup-positive",
        "capability": "knowledge_lookup",
        "description": "Returns a related entity",
        "required": True,
    })
    registry.register({
        "case_id": "lookup-empty",
        "capability": "knowledge_lookup",
        "description": "Reports when no entity is related",
        "required": True,
    })
    registry.register({
        "case_id": "lookup-latency",
        "capability": "knowledge_lookup",
        "description": "Optional timing evidence",
        "required": False,
    })
    return registry


def _evidence(case_id, outcome="passed", reference="tests/test_lookup.py"):
    return {"case_id": case_id, "outcome": outcome, "reference": reference}


def test_registry_returns_isolated_sorted_case_metadata():
    registry = _registry()
    listed = registry.list_cases("knowledge_lookup")
    listed[0]["description"] = "changed"
    assert [case["case_id"] for case in registry.list_cases()] == [
        "lookup-empty", "lookup-latency", "lookup-positive"
    ]
    assert registry.get("lookup-empty")["description"] == (
        "Reports when no entity is related")


def test_registry_rejects_duplicate_or_malformed_cases():
    registry = _registry()
    with pytest.raises(DuplicateTestCaseError):
        registry.register({
            "case_id": "lookup-positive",
            "capability": "knowledge_lookup",
            "description": "Duplicate",
            "required": True,
        })
    invalid = {
        "case_id": "bad id",
        "capability": "knowledge_lookup",
        "description": "Invalid id",
        "required": True,
    }
    with pytest.raises(CapabilityEvaluationViolation):
        registry.register(invalid)


def test_only_all_required_cases_with_reported_evidence_are_supported():
    registry = _registry()
    partial = evaluate_capability(
        "knowledge_lookup", [_evidence("lookup-positive")], registry)
    assert partial["status"] == "partially_supported"
    assert partial["case_results"][1]["outcome"] == "not_run"

    supported = evaluate_capability("knowledge_lookup", [
        _evidence("lookup-positive"),
        _evidence("lookup-empty"),
    ], registry)
    assert supported["status"] == "supported_by_reported_evidence"
    assert supported["evidence_origin"] == "caller_reported"
    assert supported["model_inference"] is False


@pytest.mark.parametrize(
    ("evidence", "status"),
    [
        ([], "not_evaluated"),
        ([_evidence("lookup-positive", "blocked", "policy report")], "blocked"),
        ([_evidence("lookup-positive", "failed", "test failure")], "not_supported"),
        ([_evidence("lookup-positive", "not_run", None)], "not_evaluated"),
    ],
)
def test_failure_blocking_and_missing_evidence_are_not_overstated(evidence, status):
    result = evaluate_capability("knowledge_lookup", evidence, _registry())
    assert result["status"] == status


def test_evaluator_rejects_unregistered_duplicate_and_unreferenced_evidence():
    registry = _registry()
    with pytest.raises(CapabilityEvaluationViolation, match="unregistered"):
        evaluate_capability(
            "knowledge_lookup", [_evidence("other-case")], registry)
    with pytest.raises(CapabilityEvaluationViolation, match="duplicate"):
        evaluate_capability("knowledge_lookup", [
            _evidence("lookup-positive"),
            _evidence("lookup-positive"),
        ], registry)
    with pytest.raises(CapabilityEvaluationViolation, match="requires"):
        evaluate_capability("knowledge_lookup", [
            _evidence("lookup-positive", "passed", ""),
        ], registry)


def test_result_contract_recomputes_status_and_rejects_inflated_claims():
    registry = _registry()
    result = evaluate_capability(
        "knowledge_lookup", [_evidence("lookup-positive")], registry)
    inflated = copy.deepcopy(result)
    inflated["status"] = "supported_by_reported_evidence"
    with pytest.raises(CapabilityEvaluationViolation, match="status must match"):
        validate_evaluation_result(inflated, registry)

    false_model_claim = copy.deepcopy(result)
    false_model_claim["model_inference"] = True
    with pytest.raises(CapabilityEvaluationViolation, match="model inference"):
        validate_evaluation_result(false_model_claim, registry)


def test_result_contract_requires_closed_shape_and_reported_evidence_origin():
    registry = _registry()
    result = evaluate_capability(
        "knowledge_lookup",
        [_evidence("lookup-positive"), _evidence("lookup-empty")],
        registry,
    )
    extra_key = copy.deepcopy(result)
    extra_key["accuracy"] = 1.0
    with pytest.raises(CapabilityEvaluationViolation, match="exactly"):
        validate_evaluation_result(extra_key, registry)
    unreported = copy.deepcopy(result)
    unreported["evidence_origin"] = "verified"
    with pytest.raises(CapabilityEvaluationViolation, match="caller_reported"):
        validate_evaluation_result(unreported, registry)
