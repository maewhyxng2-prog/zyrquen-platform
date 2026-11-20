"""Input/output contract for ReasoningEngine results (Phase 9.3)."""

ALLOWED_STATUS = frozenset({"lookup_only", "no_knowledge_found"})
REQUIRED_KEYS = frozenset({
    "context", "question", "related_knowledge_found",
    "reasoning_path", "status", "engine_type", "model_inference",
})


class ContractViolation(ValueError):
    pass


def _valid_evidence(evidence):
    return (
        isinstance(evidence, dict)
        and isinstance(evidence.get("model_id"), str)
        and evidence["model_id"].strip() != ""
        and isinstance(evidence.get("response"), str)
        and evidence["response"].strip() != ""
    )


def validate_result(result, native_model_evidence=None):
    if not isinstance(result, dict):
        raise ContractViolation("result must be a dict")
    missing = REQUIRED_KEYS - set(result)
    if missing:
        raise ContractViolation("missing keys: %s" % sorted(missing))
    status = result["status"]
    if status not in ALLOWED_STATUS:
        raise ContractViolation("status not allowed: %r" % (status,))
    flag = result["model_inference"]
    if not isinstance(flag, bool):
        raise ContractViolation("model_inference must be bool")
    if flag and not _valid_evidence(native_model_evidence):
        raise ContractViolation("model_inference=True requires native model evidence")
    found = result["related_knowledge_found"]
    if (status == "lookup_only") != bool(found):
        raise ContractViolation("status inconsistent with related_knowledge_found")
    return result
