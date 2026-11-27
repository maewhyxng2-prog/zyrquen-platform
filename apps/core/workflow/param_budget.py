"""Trusted resolution of a workflow step's estimated parameter budget."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ESTIMATED_PARAMS_KEY = "estimated_params"


def resolve_estimated_params(
    step: Any,
    previous_outputs: Mapping[str, Any] | None = None,
) -> Any:
    """Return the budget from step config, else from a prior step output; None when undeclared.

    Never reads caller-supplied trigger payload: the guard validates and enforces any
    payload value it receives, exactly as before. The returned value is not coerced here,
    because WorkflowResourceGuard is the single place that validates it and fails closed.
    """
    declared = getattr(step, ESTIMATED_PARAMS_KEY, None)
    if declared is not None:
        return declared

    outputs = previous_outputs or {}
    depends_on = tuple(getattr(step, "depends_on", ()) or ())
    ordered_keys = list(depends_on) + [k for k in reversed(list(outputs)) if k not in depends_on]
    for step_key in ordered_keys:
        output = outputs.get(step_key)
        if isinstance(output, Mapping) and output.get(ESTIMATED_PARAMS_KEY) is not None:
            return output[ESTIMATED_PARAMS_KEY]
    return None
