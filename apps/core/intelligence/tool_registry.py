"""In-memory registry of tool metadata; registered tools are never invoked."""
import copy
import threading

from .tool_contract import validate_tool_definition


class DuplicateToolError(ValueError):
    pass


class ToolRegistry:
    def __init__(self):
        self._definitions = {}
        self._lock = threading.RLock()

    def register(self, definition):
        snapshot = copy.deepcopy(definition)
        validate_tool_definition(snapshot)
        with self._lock:
            name = snapshot["name"]
            if name in self._definitions:
                raise DuplicateToolError(f"tool already registered: {name}")
            self._definitions[name] = snapshot
            return copy.deepcopy(snapshot)

    def get(self, name):
        with self._lock:
            try:
                definition = self._definitions[name]
            except KeyError:
                raise KeyError(f"tool is not registered: {name}") from None
            return copy.deepcopy(definition)

    def list_tools(self):
        with self._lock:
            return [
                copy.deepcopy(self._definitions[name])
                for name in sorted(self._definitions)
            ]
