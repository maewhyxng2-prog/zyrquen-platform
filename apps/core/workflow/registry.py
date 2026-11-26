"""Versioned WorkflowRegistry for registering and resolving the 8 workflow groups."""

from __future__ import annotations

import threading
from typing import Callable

from apps.core.workflow.dag import validate_dag
from apps.core.workflow.models import (
    WORKFLOW_GROUPS,
    StepExecutionResult,
    WorkflowDefinition,
    WorkflowValidationError,
)


StepHandler = Callable[[dict, dict], StepExecutionResult]


class WorkflowRegistry:
    """Central registry holding versioned workflow definitions and step handlers."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._definitions: dict[tuple[str, str], WorkflowDefinition] = {}
        self._latest_versions: dict[str, str] = {}
        self._handlers: dict[str, StepHandler] = {}

    def register_handler(self, handler_key: str, fn: StepHandler) -> None:
        if not handler_key or not callable(fn):
            raise WorkflowValidationError(f"Invalid handler registration for {handler_key!r}")
        with self._lock:
            self._handlers[handler_key] = fn

    def get_handler(self, handler_key: str) -> StepHandler:
        with self._lock:
            fn = self._handlers.get(handler_key)
            if fn is None:
                raise WorkflowValidationError(f"No handler registered for {handler_key!r}")
            return fn

    def register_definition(self, definition: WorkflowDefinition) -> list[str]:
        if definition.group_name not in WORKFLOW_GROUPS:
            raise WorkflowValidationError(f"Unsupported workflow group: {definition.group_name!r}")
        order = validate_dag(definition.steps)
        with self._lock:
            key = (definition.workflow_key, definition.version)
            self._definitions[key] = definition
            if definition.is_active:
                self._latest_versions[definition.workflow_key] = definition.version
        return order

    def get(self, workflow_key: str, version: str | None = None) -> WorkflowDefinition:
        with self._lock:
            target_version = version or self._latest_versions.get(workflow_key)
            if not target_version:
                raise WorkflowValidationError(f"Unknown workflow_key: {workflow_key!r}")
            defn = self._definitions.get((workflow_key, target_version))
            if defn is None:
                raise WorkflowValidationError(
                    f"Unknown workflow definition: {workflow_key}@{target_version}"
                )
            return defn

    def list_definitions(self, group_name: str | None = None) -> list[WorkflowDefinition]:
        with self._lock:
            items = list(self._definitions.values())
        if group_name:
            items = [d for d in items if d.group_name == group_name]
        return sorted(items, key=lambda d: (d.group_name, d.workflow_key, d.version))

    def find_by_event(self, event_name: str) -> list[WorkflowDefinition]:
        with self._lock:
            return [
                defn
                for wf_key, ver in self._latest_versions.items()
                for defn in [self._definitions[(wf_key, ver)]]
                if defn.is_active and event_name in defn.event_triggers
            ]

    def list_scheduled(self) -> list[WorkflowDefinition]:
        with self._lock:
            return [
                self._definitions[(wf_key, ver)]
                for wf_key, ver in self._latest_versions.items()
                if self._definitions[(wf_key, ver)].is_active
                and self._definitions[(wf_key, ver)].schedule_interval_sec is not None
            ]
