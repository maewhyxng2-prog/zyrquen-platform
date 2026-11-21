import unittest

from apps.core.intelligence.tool_policy import ExecutionPolicy, PermissionGate
from apps.core.intelligence.tool_registry import DuplicateToolError, ToolRegistry


def _definition(name="read_status", effect="read_only"):
    return {
        "name": name,
        "description": "Status lookup",
        "effect": effect,
        "required_permission": "status:read" if effect == "read_only"
        else "status:write",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
            "additionalProperties": False,
        },
    }


def _call(name="read_status", **overrides):
    call = {"call_id": "call-1", "tool_name": name,
            "arguments": {"key": "ready"}}
    call.update(overrides)
    return call


class TestToolRegistryAndPolicy(unittest.TestCase):
    def test_registry_stores_isolated_definitions_and_lists_sorted_names(self):
        registry = ToolRegistry()
        definition = _definition("z_tool")
        registry.register(definition)
        registry.register(_definition("a_tool"))
        definition["description"] = "mutated"
        returned = registry.get("z_tool")
        returned["description"] = "also mutated"
        self.assertEqual([item["name"] for item in registry.list_tools()],
                         ["a_tool", "z_tool"])
        self.assertEqual(registry.get("z_tool")["description"], "Status lookup")

    def test_registry_rejects_duplicates_and_invalid_definitions(self):
        registry = ToolRegistry()
        registry.register(_definition())
        with self.assertRaises(DuplicateToolError):
            registry.register(_definition())
        with self.assertRaises(ValueError):
            registry.register(_definition(name="Invalid Name"))

    def test_registry_missing_name_is_explicit(self):
        with self.assertRaises(KeyError):
            ToolRegistry().get("missing")

    def test_read_only_authorization_requires_permission_and_never_executes(self):
        registry = ToolRegistry()
        registry.register(_definition())
        gate = PermissionGate(registry)
        denied = gate.authorize(_call(), set())
        self.assertEqual(denied["status"], "denied")
        self.assertEqual(denied["reasons"], ["missing_required_permission"])
        allowed = gate.authorize(_call(), {"status:read"})
        self.assertEqual(allowed["status"], "authorized")
        self.assertIs(allowed["execution_performed"], False)

    def test_side_effecting_tool_requires_policy_permission_and_approval(self):
        registry = ToolRegistry()
        registry.register(_definition("write_status", "side_effecting"))
        call = _call("write_status")
        gate = PermissionGate(registry, ExecutionPolicy(allow_side_effecting=True))
        self.assertEqual(gate.authorize(call, {"status:write"})["reasons"],
                         ["explicit_approval_required"])
        self.assertEqual(
            gate.authorize(call, set(), approval_granted=True)["reasons"],
            ["missing_required_permission"])
        approved = gate.authorize(
            call, {"status:write"}, approval_granted=True)
        self.assertEqual(approved["status"], "authorized")
        self.assertIs(approved["execution_performed"], False)

    def test_side_effecting_is_denied_by_default_even_with_approval(self):
        registry = ToolRegistry()
        registry.register(_definition("write_status", "side_effecting"))
        result = PermissionGate(registry).authorize(
            _call("write_status"), {"status:write"}, approval_granted=True)
        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["reasons"], ["side_effecting_tools_disabled"])

    def test_gate_rejects_invalid_calls_and_unknown_tools(self):
        registry = ToolRegistry()
        registry.register(_definition())
        gate = PermissionGate(registry)
        with self.assertRaises(TypeError):
            gate.authorize(_call(), {"status:read": "invalid"})
        with self.assertRaises(ValueError):
            gate.authorize(_call(arguments={"extra": 1}), {"status:read"})
        with self.assertRaises(KeyError):
            gate.authorize(_call("missing"), set())

    def test_policy_flags_must_be_boolean(self):
        with self.assertRaises(TypeError):
            ExecutionPolicy(allow_read_only=1)
        with self.assertRaises(TypeError):
            ExecutionPolicy(allow_side_effecting="yes")


if __name__ == "__main__":
    unittest.main()
