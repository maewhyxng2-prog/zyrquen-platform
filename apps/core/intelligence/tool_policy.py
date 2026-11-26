"""Permission and side-effect policy decisions; this module never executes tools."""
from dataclasses import dataclass

from .tool_contract import ToolContractViolation, validate_tool_call


@dataclass(frozen=True)
class ExecutionPolicy:
    allow_read_only: bool = True
    allow_side_effecting: bool = False

    def __post_init__(self):
        if not isinstance(self.allow_read_only, bool):
            raise TypeError("allow_read_only must be bool")
        if not isinstance(self.allow_side_effecting, bool):
            raise TypeError("allow_side_effecting must be bool")


class PermissionGate:
    def __init__(self, registry, policy=None):
        self._registry = registry
        self._policy = policy if policy is not None else ExecutionPolicy()
        if not isinstance(self._policy, ExecutionPolicy):
            raise TypeError("policy must be an ExecutionPolicy")

    def authorize(self, call, granted_permissions, approval_granted=False):
        if (not isinstance(call, dict)
                or not isinstance(call.get("tool_name"), str)
                or not call["tool_name"].strip()):
            raise ToolContractViolation("call must include a text tool_name")
        definition = self._registry.get(call["tool_name"])
        validate_tool_call(call, definition)
        if not isinstance(granted_permissions, (set, frozenset, list, tuple)):
            raise TypeError("granted_permissions must be a collection of permission names")
        if any(not isinstance(item, str) or not item.strip()
               for item in granted_permissions):
            raise ValueError("granted_permissions must contain non-empty text")
        if not isinstance(approval_granted, bool):
            raise TypeError("approval_granted must be bool")

        reasons = []
        if definition["required_permission"] not in granted_permissions:
            reasons.append("missing_required_permission")
        if definition["effect"] == "read_only" and not self._policy.allow_read_only:
            reasons.append("read_only_tools_disabled")
        if definition["effect"] == "side_effecting":
            if not self._policy.allow_side_effecting:
                reasons.append("side_effecting_tools_disabled")
            elif not approval_granted:
                reasons.append("explicit_approval_required")
        return {
            "status": "denied" if reasons else "authorized",
            "tool_name": definition["name"],
            "reasons": reasons,
            "execution_performed": False,
        }
