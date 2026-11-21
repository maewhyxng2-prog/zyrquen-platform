"""Contracts for tool definitions, calls, and results; no tools are executed."""
import math
import re

TOOL_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
ALLOWED_TOOL_EFFECTS = frozenset({"read_only", "side_effecting"})
ALLOWED_TOOL_RESULT_STATUSES = frozenset({"succeeded", "failed", "denied"})
TOOL_DEFINITION_KEYS = frozenset(
    {"name", "description", "input_schema", "effect", "required_permission"})
TOOL_CALL_KEYS = frozenset({"call_id", "tool_name", "arguments"})
TOOL_RESULT_KEYS = frozenset({"call_id", "status", "output", "error"})
_SCHEMA_KEYS = frozenset(
    {"type", "properties", "required", "additionalProperties", "items"})
_SCHEMA_TYPES = frozenset(
    {"object", "array", "string", "integer", "number", "boolean", "null"})
_MAX_NESTING = 32


class ToolContractViolation(ValueError):
    pass


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _schema_problems(schema, path="input_schema", depth=0, ancestors=None):
    if not isinstance(schema, dict):
        return [f"{path} must be a dict"]
    if depth >= _MAX_NESTING:
        return [f"{path} exceeds maximum schema nesting"]
    ancestors = set() if ancestors is None else ancestors
    identity = id(schema)
    if identity in ancestors:
        return [f"{path} contains a schema cycle"]
    ancestors.add(identity)
    problems = []
    unknown = set(schema) - _SCHEMA_KEYS
    if unknown:
        problems.append(
            f"{path} has unsupported keys: {sorted(map(repr, unknown))}")
    schema_type = schema.get("type")
    if not isinstance(schema_type, str) or schema_type not in _SCHEMA_TYPES:
        problems.append(f"{path}.type is not supported")
    elif schema_type == "object":
        unexpected = set(schema) - {
            "type", "properties", "required", "additionalProperties"}
        if unexpected:
            problems.append(
                f"{path} has keys not supported for object: "
                f"{sorted(map(repr, unexpected))}")
        properties = schema.get("properties")
        required = schema.get("required")
        if not isinstance(properties, dict):
            problems.append(f"{path}.properties must be a dict")
        else:
            for name, child in properties.items():
                if not _text(name):
                    problems.append(f"{path}.properties keys must be non-empty text")
                problems.extend(
                    _schema_problems(
                        child, f"{path}.properties.{name}", depth + 1, ancestors))
        if (not isinstance(required, list)
                or any(not _text(name) for name in required)):
            problems.append(f"{path}.required must be a list of non-empty names")
        elif isinstance(properties, dict) and not set(required) <= set(properties):
            problems.append(f"{path}.required contains an unknown property")
        if schema.get("additionalProperties") is not False:
            problems.append(f"{path}.additionalProperties must be false")
    elif schema_type == "array":
        unexpected = set(schema) - {"type", "items"}
        if unexpected:
            problems.append(
                f"{path} has keys not supported for array: "
                f"{sorted(map(repr, unexpected))}")
        if "items" not in schema:
            problems.append(f"{path}.items is required")
        else:
            problems.extend(
                _schema_problems(schema["items"], f"{path}.items",
                                 depth + 1, ancestors))
    elif set(schema) != {"type"}:
        problems.append(f"{path} only supports the type keyword")
    ancestors.remove(identity)
    return problems


def _value_matches(value, schema, path, depth=0):
    if depth >= _MAX_NESTING:
        return [f"{path} exceeds maximum value nesting"]
    schema_type = schema["type"]
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": (isinstance(value, (int, float))
                   and not isinstance(value, bool)
                   and (not isinstance(value, float) or math.isfinite(value))),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }[schema_type]
    if not valid:
        return [f"{path} must be {schema_type}"]
    if schema_type == "object":
        properties = schema["properties"]
        problems = []
        missing = set(schema["required"]) - set(value)
        if missing:
            problems.append(f"{path} is missing required keys: {sorted(missing)}")
        extra = set(value) - set(properties)
        if extra:
            problems.append(
                f"{path} has unsupported keys: {sorted(map(repr, extra))}")
        for name in set(value) & set(properties):
            problems.extend(
                _value_matches(value[name], properties[name],
                               f"{path}.{name}", depth + 1))
        return problems
    if schema_type == "array":
        problems = []
        for index, item in enumerate(value):
            problems.extend(
                _value_matches(item, schema["items"],
                               f"{path}[{index}]", depth + 1))
        return problems
    return []


def analyze_tool_definition(definition):
    if not isinstance(definition, dict):
        return {"status": "invalid_definition", "problems": ["definition must be a dict"]}
    problems = []
    missing = TOOL_DEFINITION_KEYS - set(definition)
    extra = set(definition) - TOOL_DEFINITION_KEYS
    if missing:
        problems.append(f"missing definition keys: {sorted(missing)}")
    if extra:
        problems.append(f"unknown definition keys: {sorted(map(repr, extra))}")
    if "name" in definition and (
            not _text(definition["name"])
            or TOOL_NAME_PATTERN.fullmatch(definition["name"]) is None):
        problems.append("name must match [a-z][a-z0-9_]{0,63}")
    if "description" in definition and not _text(definition["description"]):
        problems.append("description must be non-empty text")
    if "effect" in definition and (
            not isinstance(definition["effect"], str)
            or definition["effect"] not in ALLOWED_TOOL_EFFECTS):
        problems.append(f"effect not allowed: {definition['effect']!r}")
    if "required_permission" in definition and not _text(
            definition["required_permission"]):
        problems.append("required_permission must be non-empty text")
    if "input_schema" in definition:
        schema = definition["input_schema"]
        if not isinstance(schema, dict) or schema.get("type") != "object":
            problems.append("input_schema must describe an object")
        problems.extend(_schema_problems(schema))
    return {
        "status": "valid_definition" if not problems else "invalid_definition",
        "problems": problems,
    }


def validate_tool_definition(definition):
    result = analyze_tool_definition(definition)
    if result["status"] != "valid_definition":
        raise ToolContractViolation("; ".join(result["problems"]))
    return definition


def analyze_tool_call(call, definition):
    definition_result = analyze_tool_definition(definition)
    if definition_result["status"] != "valid_definition":
        return {
            "status": "invalid_call",
            "problems": ["tool definition is invalid", *definition_result["problems"]],
        }
    if not isinstance(call, dict):
        return {"status": "invalid_call", "problems": ["call must be a dict"]}
    problems = []
    missing = TOOL_CALL_KEYS - set(call)
    extra = set(call) - TOOL_CALL_KEYS
    if missing:
        problems.append(f"missing call keys: {sorted(map(repr, missing))}")
    if extra:
        problems.append(f"unknown call keys: {sorted(map(repr, extra))}")
    if "call_id" in call and not _text(call["call_id"]):
        problems.append("call_id must be non-empty text")
    if "tool_name" in call:
        if not _text(call["tool_name"]):
            problems.append("tool_name must be non-empty text")
        elif call["tool_name"] != definition["name"]:
            problems.append("tool_name does not match definition")
    if "arguments" in call:
        problems.extend(_value_matches(
            call["arguments"], definition["input_schema"], "arguments"))
    return {
        "status": "valid_call" if not problems else "invalid_call",
        "problems": problems,
    }


def validate_tool_call(call, definition):
    result = analyze_tool_call(call, definition)
    if result["status"] != "valid_call":
        raise ToolContractViolation("; ".join(result["problems"]))
    return call


def _json_value_problems(value, path="output", depth=0):
    if depth >= _MAX_NESTING:
        return [f"{path} exceeds maximum value nesting"]
    if value is None or isinstance(value, (str, bool, int)):
        return []
    if isinstance(value, float):
        return [] if math.isfinite(value) else [f"{path} must be a finite number"]
    if isinstance(value, list):
        problems = []
        for index, item in enumerate(value):
            problems.extend(_json_value_problems(item, f"{path}[{index}]", depth + 1))
        return problems
    if isinstance(value, dict):
        problems = []
        for key, item in value.items():
            if not isinstance(key, str):
                problems.append(f"{path} keys must be text")
            else:
                problems.extend(
                    _json_value_problems(item, f"{path}.{key}", depth + 1))
        return problems
    return [f"{path} must contain JSON-compatible values"]


def analyze_tool_result(result):
    if not isinstance(result, dict):
        return {"status": "invalid_result", "problems": ["result must be a dict"]}
    problems = []
    missing = TOOL_RESULT_KEYS - set(result)
    extra = set(result) - TOOL_RESULT_KEYS
    if missing:
        problems.append(f"missing result keys: {sorted(map(repr, missing))}")
    if extra:
        problems.append(f"unknown result keys: {sorted(map(repr, extra))}")
    if "call_id" in result and not _text(result["call_id"]):
        problems.append("call_id must be non-empty text")
    status = result.get("status")
    if (not isinstance(status, str)
            or status not in ALLOWED_TOOL_RESULT_STATUSES):
        problems.append(f"status not allowed: {status!r}")
    if status == "succeeded":
        if result.get("error") is not None:
            problems.append("succeeded result must have error=None")
        if "output" in result:
            problems.extend(_json_value_problems(result["output"]))
    elif isinstance(status, str) and status in {"failed", "denied"}:
        if not _text(result.get("error")):
            problems.append(f"{status} result requires a non-empty error")
        if result.get("output") is not None:
            problems.append(f"{status} result must have output=None")
    return {
        "status": "valid_result" if not problems else "invalid_result",
        "problems": problems,
    }


def validate_tool_result(result):
    validation = analyze_tool_result(result)
    if validation["status"] != "valid_result":
        raise ToolContractViolation("; ".join(validation["problems"]))
    return result
