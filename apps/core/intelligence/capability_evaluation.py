"""Evidence contracts for capability evaluation; no test cases are executed."""
import re
import threading

CASE_ID_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
CAPABILITY_ID_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
CASE_OUTCOMES = frozenset({"passed", "failed", "blocked", "not_run"})
CAPABILITY_STATUSES = frozenset({
    "not_evaluated",
    "partially_supported",
    "not_supported",
    "blocked",
    "supported_by_reported_evidence",
})
_CASE_KEYS = frozenset({"case_id", "capability", "description", "required"})
_EVIDENCE_KEYS = frozenset({"case_id", "outcome", "reference"})
_RESULT_KEYS = frozenset({
    "capability",
    "status",
    "case_results",
    "evidence_origin",
    "model_inference",
})


class CapabilityEvaluationViolation(ValueError):
    pass


class DuplicateTestCaseError(ValueError):
    pass


class TestCaseRegistry:
    """Stores evaluation case metadata only; registered cases are never run."""

    __test__ = False

    def __init__(self):
        self._cases = {}
        self._lock = threading.RLock()

    def register(self, case):
        if not isinstance(case, dict) or set(case) != _CASE_KEYS:
            raise CapabilityEvaluationViolation(
                "case must contain exactly case_id, capability, description, required")
        case_id = case["case_id"]
        capability = case["capability"]
        if (not isinstance(case_id, str)
                or CASE_ID_PATTERN.fullmatch(case_id) is None):
            raise CapabilityEvaluationViolation("case_id must be a lowercase identifier")
        if (not isinstance(capability, str)
                or CAPABILITY_ID_PATTERN.fullmatch(capability) is None):
            raise CapabilityEvaluationViolation(
                "capability must be a lowercase identifier")
        if not isinstance(case["description"], str) or not case["description"].strip():
            raise CapabilityEvaluationViolation("description must be non-empty text")
        if not isinstance(case["required"], bool):
            raise CapabilityEvaluationViolation("required must be bool")
        snapshot = dict(case)
        with self._lock:
            if case_id in self._cases:
                raise DuplicateTestCaseError(f"test case already registered: {case_id}")
            self._cases[case_id] = snapshot
        return dict(snapshot)

    def get(self, case_id):
        with self._lock:
            try:
                return dict(self._cases[case_id])
            except KeyError:
                raise KeyError(f"test case is not registered: {case_id}") from None

    def list_cases(self, capability=None):
        with self._lock:
            cases = [
                dict(self._cases[case_id])
                for case_id in sorted(self._cases)
                if capability is None
                or self._cases[case_id]["capability"] == capability
            ]
        return cases


def _expected_status(case_results, required_case_ids):
    if not case_results or all(
            result["outcome"] == "not_run" for result in case_results):
        return "not_evaluated"
    outcomes = {result["case_id"]: result["outcome"] for result in case_results}
    if any(outcome == "blocked" for outcome in outcomes.values()):
        return "blocked"
    if any(outcome == "failed" for outcome in outcomes.values()):
        return "not_supported"
    if required_case_ids and all(
            outcomes.get(case_id) == "passed" for case_id in required_case_ids):
        return "supported_by_reported_evidence"
    if any(outcome == "passed" for outcome in outcomes.values()):
        return "partially_supported"
    return "not_evaluated"


def validate_evaluation_result(result, registry):
    if not isinstance(registry, TestCaseRegistry):
        raise TypeError("registry must be a TestCaseRegistry")
    if not isinstance(result, dict) or set(result) != _RESULT_KEYS:
        raise CapabilityEvaluationViolation(
            "result must contain exactly the evaluation result contract keys")
    capability = result["capability"]
    if (not isinstance(capability, str)
            or CAPABILITY_ID_PATTERN.fullmatch(capability) is None):
        raise CapabilityEvaluationViolation("capability must be a lowercase identifier")
    registered_cases = registry.list_cases(capability)
    if not registered_cases:
        raise CapabilityEvaluationViolation(
            f"no test cases are registered for capability: {capability}")
    expected_ids = [case["case_id"] for case in registered_cases]
    required_ids = {
        case["case_id"] for case in registered_cases if case["required"]
    }
    case_results = result["case_results"]
    if not isinstance(case_results, list) or len(case_results) != len(expected_ids):
        raise CapabilityEvaluationViolation(
            "case_results must contain every registered case exactly once")
    normalized = []
    for case_result, expected_id in zip(case_results, expected_ids):
        if not isinstance(case_result, dict) or set(case_result) != _EVIDENCE_KEYS:
            raise CapabilityEvaluationViolation(
                "each case result must contain exactly case_id, outcome, reference")
        if case_result["case_id"] != expected_id:
            raise CapabilityEvaluationViolation(
                "case_results must follow registered case order")
        outcome = case_result["outcome"]
        reference = case_result["reference"]
        if not isinstance(outcome, str) or outcome not in CASE_OUTCOMES:
            raise CapabilityEvaluationViolation(
                f"case outcome is not allowed: {outcome!r}")
        if outcome == "not_run":
            if reference is not None:
                raise CapabilityEvaluationViolation(
                    "not_run case reference must be None")
        elif not isinstance(reference, str) or not reference.strip():
            raise CapabilityEvaluationViolation(
                f"{outcome} case requires a non-empty evidence reference")
        normalized.append(case_result)
    if result["evidence_origin"] != "caller_reported":
        raise CapabilityEvaluationViolation(
            "evidence_origin must be caller_reported")
    if result["model_inference"] is not False:
        raise CapabilityEvaluationViolation(
            "capability evaluation must not claim model inference")
    expected = _expected_status(normalized, required_ids)
    if result["status"] != expected or result["status"] not in CAPABILITY_STATUSES:
        raise CapabilityEvaluationViolation(
            f"status must match the supplied evidence: {expected}")
    return result


def evaluate_capability(capability, evidence, registry):
    """Classify caller-reported test evidence without claiming to run tests."""
    if not isinstance(registry, TestCaseRegistry):
        raise TypeError("registry must be a TestCaseRegistry")
    if not isinstance(evidence, (list, tuple)):
        raise TypeError("evidence must be a list or tuple")
    registered_cases = registry.list_cases(capability)
    if not registered_cases:
        raise CapabilityEvaluationViolation(
            f"no test cases are registered for capability: {capability}")
    by_id = {}
    allowed_ids = {case["case_id"] for case in registered_cases}
    for item in evidence:
        if not isinstance(item, dict) or set(item) != _EVIDENCE_KEYS:
            raise CapabilityEvaluationViolation(
                "evidence entries must contain exactly case_id, outcome, reference")
        case_id = item["case_id"]
        if not isinstance(case_id, str):
            raise CapabilityEvaluationViolation("evidence case_id must be text")
        if case_id not in allowed_ids:
            raise CapabilityEvaluationViolation(
                f"evidence refers to an unregistered case: {case_id!r}")
        if case_id in by_id:
            raise CapabilityEvaluationViolation(
                f"duplicate evidence for test case: {case_id}")
        by_id[case_id] = dict(item)
    case_results = [
        by_id.get(case["case_id"], {
            "case_id": case["case_id"],
            "outcome": "not_run",
            "reference": None,
        })
        for case in registered_cases
    ]
    required_ids = {
        case["case_id"] for case in registered_cases if case["required"]
    }
    result = {
        "capability": capability,
        "status": _expected_status(case_results, required_ids),
        "case_results": case_results,
        "evidence_origin": "caller_reported",
        "model_inference": False,
    }
    return validate_evaluation_result(result, registry)
