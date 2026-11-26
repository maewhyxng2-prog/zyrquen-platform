import unittest

from apps.core.intelligence.tool_contract import (
    ALLOWED_TOOL_RESULT_STATUSES,
    ToolContractViolation,
    analyze_tool_call,
    analyze_tool_definition,
    analyze_tool_result,
    validate_tool_call,
    validate_tool_result,
)


def _definition(**overrides):
    definition = {
        "name": "read_status",
        "description": "Read a status value",
        "effect": "read_only",
        "required_permission": "status:read",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "options": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer"}},
                    "required": [],
                    "additionalProperties": False,
                },
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["key"],
            "additionalProperties": False,
        },
    }
    definition.update(overrides)
    return definition


def _call(**overrides):
    call = {
        "call_id": "call-1",
        "tool_name": "read_status",
        "arguments": {"key": "ready", "options": {"limit": 1}, "tags": ["api"]},
    }
    call.update(overrides)
    return call


class TestToolContract(unittest.TestCase):
    def test_valid_definition_and_nested_call(self):
        definition = _definition()
        self.assertEqual(analyze_tool_definition(definition)["status"],
                         "valid_definition")
        self.assertEqual(analyze_tool_call(_call(), definition)["status"],
                         "valid_call")

    def test_definition_rejects_bad_names_and_unrestricted_schemas(self):
        for definition in (
                _definition(name="Read-Status"),
                _definition(input_schema={
                    "type": "object", "properties": {}, "required": [],
                    "additionalProperties": True,
                })):
            with self.subTest(definition=definition):
                self.assertEqual(analyze_tool_definition(definition)["status"],
                                 "invalid_definition")

    def test_definition_rejects_schema_cycles(self):
        schema = {
            "type": "object", "properties": {}, "required": [],
            "additionalProperties": False,
        }
        schema["properties"]["nested"] = schema
        self.assertEqual(analyze_tool_definition(
            _definition(input_schema=schema))["status"], "invalid_definition")

    def test_call_requires_registered_definition_name_and_valid_arguments(self):
        definition = _definition()
        for call in (
                _call(tool_name="other"),
                _call(arguments={"unexpected": True}),
                _call(arguments={"key": True}),
                _call(arguments={"key": "ready", "options": {"limit": True}}),
                _call(arguments={"key": "ready", "tags": [1]}),
                _call(call_id="  ")):
            with self.subTest(call=call):
                self.assertEqual(analyze_tool_call(call, definition)["status"],
                                 "invalid_call")

    def test_validate_call_raises_for_invalid_input(self):
        with self.assertRaises(ToolContractViolation):
            validate_tool_call(_call(arguments={}), _definition())

    def test_valid_success_failure_and_denial_result_shapes(self):
        for result in (
                {"call_id": "c1", "status": "succeeded",
                 "output": {"ok": True}, "error": None},
                {"call_id": "c1", "status": "failed",
                 "output": None, "error": "failed"},
                {"call_id": "c1", "status": "denied",
                 "output": None, "error": "not approved"}):
            with self.subTest(result=result):
                self.assertEqual(analyze_tool_result(result)["status"],
                                 "valid_result")

    def test_result_status_is_closed_and_shapes_are_consistent(self):
        invalid = (
            {"call_id": "c1", "status": "executed",
             "output": None, "error": None},
            {"call_id": "c1", "status": "succeeded",
             "output": None, "error": "error"},
            {"call_id": "c1", "status": "failed",
             "output": "partial", "error": "error"},
            {"call_id": "c1", "status": "denied",
             "output": None, "error": ""},
        )
        for result in invalid:
            with self.subTest(result=result):
                self.assertEqual(analyze_tool_result(result)["status"],
                                 "invalid_result")
        self.assertEqual(ALLOWED_TOOL_RESULT_STATUSES,
                         {"succeeded", "failed", "denied"})

    def test_result_rejects_non_json_output_and_validator_raises(self):
        result = {"call_id": "c1", "status": "succeeded",
                  "output": object(), "error": None}
        self.assertEqual(analyze_tool_result(result)["status"], "invalid_result")
        with self.assertRaises(ToolContractViolation):
            validate_tool_result(result)


if __name__ == "__main__":
    unittest.main()
