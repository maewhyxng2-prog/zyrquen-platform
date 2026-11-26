"""
Contracts, Manifests, Versioning, Dependency Checking, and Permission Models
for ZYRQUEN Capability Library & Tool Center.

Principle: Build Once -> Register Once -> Reuse Everywhere.
Pure Python 3.11 standard library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


class ToolContractError(ValueError):
    """Raised when capability registration or input/output fails contract checks."""


ALLOWED_PERMISSION_MODES = frozenset({"auto", "approval_required", "admin_only", "disabled"})
ALLOWED_RISK_TIERS = frozenset({"local_readonly", "sandbox_io", "external_readonly", "governance"})
ALLOWED_LIFECYCLE_STATUSES = frozenset({"READY", "IN_DEVELOPMENT", "DEPRECATED"})


@dataclass(frozen=True)
class CapabilitySpec:
    id: str
    toolkit_id: str
    name: str
    version: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    dependencies: tuple[str, ...] = ()
    permission_mode: str = "auto"
    risk_tier: str = "local_readonly"
    lifecycle_status: str = "READY"  # READY | IN_DEVELOPMENT | DEPRECATED
    bound_modules: tuple[str, ...] = ()
    documentation: str = ""
    example_input: dict[str, Any] = field(default_factory=dict)
    keywords: tuple[str, ...] = ()
    changelog: tuple[str, ...] = ("1.0.0: Initial verified registration",)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "toolkit_id": self.toolkit_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "dependencies": list(self.dependencies),
            "permission_mode": self.permission_mode,
            "risk_tier": self.risk_tier,
            "lifecycle_status": self.lifecycle_status,
            "bound_modules": list(self.bound_modules),
            "documentation": self.documentation,
            "example_input": self.example_input,
            "keywords": list(self.keywords),
            "changelog": list(self.changelog),
        }


@dataclass(frozen=True)
class ToolkitManifest:
    id: str
    name: str
    thai_name: str
    version: str
    description: str
    category: str
    dependencies: tuple[str, ...] = ()
    default_permission: str = "auto"
    lifecycle_status: str = "READY"
    bound_modules: tuple[str, ...] = ()
    documentation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "thai_name": self.thai_name,
            "version": self.version,
            "description": self.description,
            "category": self.category,
            "dependencies": list(self.dependencies),
            "default_permission": self.default_permission,
            "lifecycle_status": self.lifecycle_status,
            "bound_modules": list(self.bound_modules),
            "documentation": self.documentation,
        }


@dataclass
class CapabilityExecutionResult:
    ok: bool
    capability_id: str
    capability_version: str
    toolkit_id: str
    status: str  # COMPLETED | PENDING_APPROVAL | BLOCKED | FAILED | REJECTED
    output: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    error: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    external_models_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "capability_id": self.capability_id,
            "capability_version": self.capability_version,
            "toolkit_id": self.toolkit_id,
            "status": self.status,
            "output": self.output,
            "summary": self.summary,
            "error": self.error,
            "evidence": self.evidence,
            "external_models_used": False,
        }


def validate_capability_input(spec: CapabilitySpec, payload: Any) -> tuple[bool, str | None, dict[str, Any]]:
    """Validate input dictionary against the capability's declared input_schema."""
    if payload is None:
        normalized: dict[str, Any] = {}
    elif isinstance(payload, dict):
        normalized = dict(payload)
    else:
        return False, f"Input for '{spec.id}' must be a JSON object/dict.", {}

    schema = spec.input_schema or {}
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    for req_key in required:
        val = normalized.get(req_key)
        if val is None or (isinstance(val, str) and not val.strip()) or (isinstance(val, (list, dict)) and len(val) == 0):
            return False, f"Missing required input field '{req_key}' for capability '{spec.id}'.", normalized

    type_map = {
        "string": str,
        "boolean": bool,
        "integer": int,
        "number": (int, float),
        "array": list,
        "object": dict,
    }
    for key, val in normalized.items():
        if val is None or key not in properties:
            continue
        expected_type = properties[key].get("type")
        if expected_type in type_map:
            py_type = type_map[expected_type]
            if expected_type == "integer" and isinstance(val, bool):
                return False, f"Field '{key}' must be an integer.", normalized
            if expected_type == "number" and isinstance(val, bool):
                return False, f"Field '{key}' must be a number.", normalized
            if not isinstance(val, py_type):
                return False, f"Field '{key}' must be of type '{expected_type}'.", normalized
        enum_vals = properties[key].get("enum")
        if isinstance(enum_vals, list) and val not in enum_vals:
            return False, f"Field '{key}' must be one of {enum_vals}.", normalized

    return True, None, normalized


def validate_capability_output(spec: CapabilitySpec, output: Any) -> tuple[bool, str | None]:
    """Validate output dictionary against the capability's declared output_schema."""
    if not isinstance(output, dict):
        return False, f"Output of '{spec.id}' must be a dict."
    required = (spec.output_schema or {}).get("required", [])
    for key in required:
        if key not in output:
            return False, f"Output of '{spec.id}' missing declared contract key '{key}'."
    return True, None


def evaluate_capability_permission(
    spec: CapabilitySpec,
    user_role: str,
    *,
    approved_by: str | None = None,
    allow_in_development: bool = False,
) -> dict[str, Any]:
    """Determine whether a role can execute a capability directly or requires P5 Approval Gate."""
    role = "admin" if str(user_role).lower() == "admin" else "user"
    if spec.lifecycle_status == "DEPRECATED":
        return {
            "allowed": False,
            "requires_approval": False,
            "status": "BLOCKED",
            "reason": f"Capability '{spec.id}' v{spec.version} is deprecated.",
        }
    if spec.lifecycle_status == "IN_DEVELOPMENT" and not allow_in_development and role != "admin":
        return {
            "allowed": False,
            "requires_approval": False,
            "status": "BLOCKED",
            "reason": f"Capability '{spec.id}' is IN_DEVELOPMENT and not yet approved for general Studio use.",
        }

    mode = spec.permission_mode
    if mode == "disabled":
        return {
            "allowed": False,
            "requires_approval": False,
            "status": "BLOCKED",
            "reason": f"Capability '{spec.id}' is disabled by system policy.",
        }
    if mode == "admin_only" and role != "admin":
        return {
            "allowed": False,
            "requires_approval": False,
            "status": "BLOCKED",
            "reason": f"Capability '{spec.id}' requires admin role.",
        }
    if mode == "approval_required" and not approved_by:
        return {
            "allowed": True,
            "requires_approval": True,
            "status": "PENDING_APPROVAL",
            "reason": f"Capability '{spec.id}' requires P5 Approval Gate before execution.",
        }
    return {
        "allowed": True,
        "requires_approval": False,
        "status": "ALLOWED",
        "reason": "Permitted by capability policy.",
    }


class CapabilityHandle:
    """
    Bound capability object returned by `registry.resolve("<toolkit>.<capability>")`.
    Supports direct Python execution: `result = capability.execute(payload)`.
    """

    def __init__(
        self,
        *,
        spec: CapabilitySpec,
        manifest: ToolkitManifest,
        handler: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
        registry: Any,
    ) -> None:
        self.spec = spec
        self.manifest = manifest
        self._handler = handler
        self._registry = registry

    def execute(
        self,
        payload: dict[str, Any] | None = None,
        *,
        user_id: str = "system",
        user_role: str = "admin",
        conn: Any = None,
        data_dir: Any = None,
        approved_by: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        return self._registry.execute(
            self.spec.id,
            payload or {},
            user_id=user_id,
            user_role=user_role,
            conn=conn,
            data_dir=data_dir,
            approved_by=approved_by,
            project_id=project_id,
            conversation_id=conversation_id,
        )
