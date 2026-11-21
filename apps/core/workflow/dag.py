"""DAG topological validation, cycle detection, and dependency resolution."""

from __future__ import annotations

from collections import deque
from typing import Iterable

from apps.core.workflow.models import (
    APPROVAL_TIERS,
    LANES,
    WorkflowStepSpec,
    WorkflowValidationError,
)


def validate_dag(steps: Iterable[WorkflowStepSpec]) -> list[str]:
    """Validate workflow step DAG using Kahn topological sort and strict attribute checks.

    Returns the validated topological execution order of step keys.
    Raises WorkflowValidationError on duplicate keys, missing dependencies, invalid tiers/lanes,
    or cyclic graphs.
    """
    step_list = list(steps)
    if not step_list:
        raise WorkflowValidationError("Workflow definition must include at least one step")

    by_key: dict[str, WorkflowStepSpec] = {}
    for step in step_list:
        if not step.step_key or not step.step_key.replace("_", "").replace("-", "").isalnum():
            raise WorkflowValidationError(f"Invalid step_key: {step.step_key!r}")
        if step.step_key in by_key:
            raise WorkflowValidationError(f"Duplicate step_key in DAG: {step.step_key}")
        if step.lane not in LANES:
            raise WorkflowValidationError(f"Invalid lane {step.lane!r} on step {step.step_key}")
        if step.tier not in APPROVAL_TIERS:
            raise WorkflowValidationError(f"Invalid tier {step.tier!r} on step {step.step_key}")
        if step.max_attempts < 1:
            raise WorkflowValidationError(f"max_attempts must be >= 1 on step {step.step_key}")
        by_key[step.step_key] = step

    in_degree: dict[str, int] = {k: 0 for k in by_key}
    dependents: dict[str, list[str]] = {k: [] for k in by_key}

    for step in step_list:
        seen_deps: set[str] = set()
        for dep in step.depends_on:
            if dep == step.step_key:
                raise WorkflowValidationError(f"Self-dependency detected on step {step.step_key}")
            if dep not in by_key:
                raise WorkflowValidationError(
                    f"Step {step.step_key} depends on unknown step {dep!r}"
                )
            if dep in seen_deps:
                continue
            seen_deps.add(dep)
            in_degree[step.step_key] += 1
            dependents[dep].append(step.step_key)

        if step.condition_step is not None and step.condition_step not in by_key:
            raise WorkflowValidationError(
                f"Step {step.step_key} references unknown condition_step {step.condition_step!r}"
            )

    queue: deque[str] = deque(sorted(k for k, deg in in_degree.items() if deg == 0))
    order: list[str] = []

    while queue:
        current = queue.popleft()
        order.append(current)
        for nxt in sorted(dependents[current]):
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(by_key):
        cyclic = sorted(k for k, deg in in_degree.items() if deg > 0)
        raise WorkflowValidationError(f"Cycle detected in workflow DAG involving: {cyclic}")

    return order


def resolve_ready_steps(
    steps: Iterable[WorkflowStepSpec],
    step_records: dict[str, dict],
) -> tuple[list[WorkflowStepSpec], list[str]]:
    """Return (runnable_steps, steps_to_skip) based on completed dependencies & conditions."""
    runnable: list[WorkflowStepSpec] = []
    to_skip: list[str] = []

    for step in steps:
        rec = step_records.get(step.step_key)
        if not rec or rec["status"] not in ("PENDING", "WAITING_RESOURCE"):
            continue

        deps_ok = True
        deps_blocked = False
        for dep_key in step.depends_on:
            dep_rec = step_records.get(dep_key, {})
            dep_status = dep_rec.get("status", "PENDING")
            if dep_status in ("FAILED", "BLOCKED", "SKIPPED"):
                deps_blocked = True
                break
            if dep_status != "COMPLETED":
                deps_ok = False
                break

        if deps_blocked:
            to_skip.append(step.step_key)
            continue
        if not deps_ok:
            continue

        if step.condition_step and step.condition_verdict:
            cond_rec = step_records.get(step.condition_step, {})
            cond_verdict = (cond_rec.get("evidence") or {}).get("verdict")
            if cond_verdict != step.condition_verdict:
                to_skip.append(step.step_key)
                continue

        runnable.append(step)

    return runnable, to_skip
