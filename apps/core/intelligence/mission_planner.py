"""Domain-Adaptive DAG Planner, Execution Contracts & Resumable Mission State Machine.

Provides:
- Typed MissionStepSpec with input/output contracts, preconditions, postconditions,
  tool_id, retry_policy, approval_policy, effect ('read_only' | 'side_effecting'),
  and idempotency_key.
- Kahn topological sort & cycle/dependency validation bridged with plan_contract.
- Persistent SQLite-backed MissionStateMachine ensuring side-effecting step
  idempotency on retries/restarts and strict post-execution verification.
"""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .plan_contract import validate_plan

MISSION_STATES = frozenset({
    "CREATED",
    "PLANNED",
    "EXECUTING",
    "WAITING_APPROVAL",
    "RECOVERING",
    "BLOCKED",
    "COMPLETED",
    "FAILED",
})

STEP_STATES = frozenset({
    "PENDING",
    "RUNNING",
    "WAITING_APPROVAL",
    "COMPLETED",
    "FAILED",
    "BLOCKED",
    "SKIPPED",
})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MissionPlanningError(ValueError):
    pass


@dataclass
class MissionStepSpec:
    task_id: str
    description: str
    dependencies: tuple[str, ...] = ()
    input_contract: dict[str, str] = field(default_factory=dict)
    output_contract: dict[str, str] = field(default_factory=dict)
    tool_id: str = "noop"
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    max_attempts: int = 2
    approval_policy: str = "tier1_auto"  # "tier1_auto" | "tier2_approval"
    effect: str = "read_only"  # "read_only" | "side_effecting"
    idempotency_key: str | None = None
    execution_status: str = "PENDING"
    evidence_refs: list[str] = field(default_factory=list)

    def to_plan_step(self) -> dict[str, Any]:
        criteria = (
            ", ".join(self.postconditions)
            if self.postconditions
            else f"Verify output contract for {self.task_id}"
        )
        return {
            "id": self.task_id,
            "description": self.description,
            "depends_on": list(self.dependencies),
            "success_criteria": criteria,
        }


def _check_contract_types(payload: Any, contract: dict[str, str], label: str) -> list[str]:
    if not contract:
        return []
    if not isinstance(payload, dict):
        return [f"{label} must be a dict"]
    problems: list[str] = []
    type_map = {
        "str": str,
        "int": int,
        "float": (int, float),
        "bool": bool,
        "dict": dict,
        "list": list,
    }
    for key, expected in contract.items():
        if key not in payload:
            problems.append(f"{label} missing required key {key!r}")
            continue
        expected_py = type_map.get(expected)
        if expected_py is not None:
            val = payload[key]
            if expected == "int" and isinstance(val, bool):
                problems.append(f"{label}.{key} expected int, got bool")
            elif not isinstance(val, expected_py):
                problems.append(f"{label}.{key} expected {expected}")
    return problems


class DomainAdaptiveDAGPlanner:
    """Validates and compiles typed MissionStepSpecs into an acyclic topological plan."""

    def build_dag(
        self,
        *,
        goal: str,
        context: dict[str, Any],
        steps: list[MissionStepSpec],
        completed_ids: set[str] | frozenset[str] | None = None,
    ) -> dict[str, Any]:
        if not steps:
            raise MissionPlanningError("Mission plan requires at least one step")
        resolved_completed = frozenset(completed_ids or ())
        by_id: dict[str, MissionStepSpec] = {}
        for step in steps:
            if not step.task_id.strip():
                raise MissionPlanningError("task_id must be non-empty")
            if step.task_id in by_id:
                raise MissionPlanningError(f"Duplicate task_id: {step.task_id}")
            if step.approval_policy not in {"tier1_auto", "tier2_approval"}:
                raise MissionPlanningError(f"Invalid approval_policy: {step.approval_policy}")
            if step.effect not in {"read_only", "side_effecting"}:
                raise MissionPlanningError(f"Invalid effect: {step.effect}")
            if step.max_attempts < 1:
                raise MissionPlanningError("max_attempts must be >= 1")
            if step.effect == "side_effecting" and not (step.idempotency_key or "").strip():
                raise MissionPlanningError(
                    f"side_effecting step {step.task_id!r} requires a non-empty idempotency_key"
                )
            by_id[step.task_id] = step

        in_degree: dict[str, int] = {k: 0 for k in by_id}
        dependents: dict[str, list[str]] = {k: [] for k in by_id}
        for step in steps:
            for dep in step.dependencies:
                if dep == step.task_id:
                    raise MissionPlanningError(f"Self-dependency on {step.task_id}")
                if dep not in by_id:
                    if dep in resolved_completed:
                        continue
                    raise MissionPlanningError(f"Unknown dependency {dep!r} on {step.task_id}")
                in_degree[step.task_id] += 1
                dependents[dep].append(step.task_id)

        queue: deque[str] = deque(sorted(k for k, d in in_degree.items() if d == 0))
        order: list[str] = []
        while queue:
            cur = queue.popleft()
            order.append(cur)
            for nxt in sorted(dependents[cur]):
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)

        if len(order) != len(by_id):
            raise MissionPlanningError("Cycle detected in mission DAG")

        plan_steps = []
        for s in steps:
            ps = s.to_plan_step()
            ps["depends_on"] = [d for d in ps["depends_on"] if d not in resolved_completed]
            plan_steps.append(ps)

        validate_plan({
            "goal": goal,
            "context": context,
            "steps": plan_steps,
            "generated_by": "rule_based",
        })
        return {
            "goal": goal,
            "step_order": order,
            "steps": [by_id[k] for k in order],
        }


class MissionStateMachine:
    """Resumable SQLite-persisted mission executor with idempotent side-effect protection."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._planner = DomainAdaptiveDAGPlanner()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS missions (
                    mission_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    state TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    error_message TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mission_steps (
                    mission_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    step_order INTEGER NOT NULL,
                    spec_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    approved INTEGER NOT NULL DEFAULT 0,
                    output_json TEXT,
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY (mission_id, task_id)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS executed_idempotency_keys (
                    idempotency_key TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    output_json TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                )
                """
            )

    def create_mission(
        self,
        *,
        mission_id: str,
        goal: str,
        context: dict[str, Any],
        steps: list[MissionStepSpec],
    ) -> dict[str, Any]:
        compiled = self._planner.build_dag(goal=goal, context=context, steps=steps)
        ordered_steps: list[MissionStepSpec] = compiled["steps"]
        now = _utc_now()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO missions (mission_id, goal, state, context_json, error_message, updated_at)
                VALUES (?, ?, 'PLANNED', ?, NULL, ?)
                """,
                (mission_id, goal, json.dumps(context), now),
            )
            for idx, step in enumerate(ordered_steps):
                spec_payload = {
                    "task_id": step.task_id,
                    "description": step.description,
                    "dependencies": list(step.dependencies),
                    "input_contract": step.input_contract,
                    "output_contract": step.output_contract,
                    "tool_id": step.tool_id,
                    "preconditions": list(step.preconditions),
                    "postconditions": list(step.postconditions),
                    "max_attempts": step.max_attempts,
                    "approval_policy": step.approval_policy,
                    "effect": step.effect,
                    "idempotency_key": step.idempotency_key,
                }
                self._conn.execute(
                    """
                    INSERT INTO mission_steps
                    (mission_id, task_id, step_order, spec_json, status, attempts, approved, output_json, evidence_refs_json)
                    VALUES (?, ?, ?, ?, 'PENDING', 0, 0, NULL, '[]')
                    """,
                    (mission_id, step.task_id, idx, json.dumps(spec_payload)),
                )
        return self.get_mission(mission_id)

    def approve_step(self, mission_id: str, task_id: str, *, approved: bool) -> dict[str, Any]:
        with self._conn:
            if approved:
                self._conn.execute(
                    "UPDATE mission_steps SET approved = 1, status = 'PENDING' WHERE mission_id = ? AND task_id = ?",
                    (mission_id, task_id),
                )
                self._conn.execute(
                    "UPDATE missions SET state = 'PLANNED', error_message = NULL, updated_at = ? WHERE mission_id = ?",
                    (_utc_now(), mission_id),
                )
            else:
                self._conn.execute(
                    "UPDATE mission_steps SET status = 'BLOCKED' WHERE mission_id = ? AND task_id = ?",
                    (mission_id, task_id),
                )
                self._conn.execute(
                    "UPDATE missions SET state = 'BLOCKED', error_message = ?, updated_at = ? WHERE mission_id = ?",
                    (f"Tier-2 approval rejected for {task_id}", _utc_now(), mission_id),
                )
        return self.get_mission(mission_id)

    def replan_mission(
        self,
        mission_id: str,
        replacement_steps: list[MissionStepSpec],
        *,
        goal: str | None = None,
    ) -> dict[str, Any]:
        mission = self.get_mission(mission_id)
        if mission["state"] not in {"FAILED", "RECOVERING", "BLOCKED", "PLANNED"}:
            raise MissionPlanningError(f"Cannot replan mission from state {mission['state']}")
        target_goal = goal or mission["goal"]
        completed_rows = self._conn.execute(
            "SELECT task_id FROM mission_steps WHERE mission_id = ? AND status = 'COMPLETED'",
            (mission_id,),
        ).fetchall()
        completed_ids = {r["task_id"] for r in completed_rows}
        compiled = self._planner.build_dag(
            goal=target_goal,
            context=mission["context"],
            steps=replacement_steps,
            completed_ids=completed_ids,
        )
        ordered_steps: list[MissionStepSpec] = compiled["steps"]
        with self._conn:
            self._conn.execute(
                "DELETE FROM mission_steps WHERE mission_id = ? AND status != 'COMPLETED'",
                (mission_id,),
            )
            for idx, step in enumerate(ordered_steps):
                if step.task_id in completed_ids:
                    continue
                spec_payload = {
                    "task_id": step.task_id,
                    "description": step.description,
                    "dependencies": list(step.dependencies),
                    "input_contract": step.input_contract,
                    "output_contract": step.output_contract,
                    "tool_id": step.tool_id,
                    "preconditions": list(step.preconditions),
                    "postconditions": list(step.postconditions),
                    "max_attempts": step.max_attempts,
                    "approval_policy": step.approval_policy,
                    "effect": step.effect,
                    "idempotency_key": step.idempotency_key,
                }
                self._conn.execute(
                    """
                    INSERT INTO mission_steps
                    (mission_id, task_id, step_order, spec_json, status, attempts, approved, output_json, evidence_refs_json)
                    VALUES (?, ?, ?, ?, 'PENDING', 0, 0, NULL, '[]')
                    """,
                    (mission_id, step.task_id, idx + 100, json.dumps(spec_payload)),
                )
            self._conn.execute(
                "UPDATE missions SET state = 'RECOVERING', error_message = NULL, updated_at = ? WHERE mission_id = ?",
                (_utc_now(), mission_id),
            )
        return self.get_mission(mission_id)

    def get_mission(self, mission_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM missions WHERE mission_id = ?", (mission_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown mission: {mission_id}")
        steps = self._conn.execute(
            "SELECT * FROM mission_steps WHERE mission_id = ? ORDER BY step_order ASC",
            (mission_id,),
        ).fetchall()
        return {
            "mission_id": row["mission_id"],
            "goal": row["goal"],
            "state": row["state"],
            "context": json.loads(row["context_json"]),
            "error_message": row["error_message"],
            "updated_at": row["updated_at"],
            "steps": [
                {
                    "task_id": s["task_id"],
                    "spec": json.loads(s["spec_json"]),
                    "status": s["status"],
                    "attempts": s["attempts"],
                    "approved": bool(s["approved"]),
                    "output": json.loads(s["output_json"]) if s["output_json"] else None,
                    "evidence_refs": json.loads(s["evidence_refs_json"]),
                }
                for s in steps
            ],
        }

    def run_mission(
        self,
        mission_id: str,
        executors: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]],
        *,
        precondition_checker: Callable[[str, dict[str, Any]], bool] | None = None,
        postcondition_checker: Callable[[str, dict[str, Any], dict[str, Any]], bool] | None = None,
        replan_on_failure: Callable[[dict[str, Any], str], list[MissionStepSpec] | None] | None = None,
    ) -> dict[str, Any]:
        with self._conn:
            self._conn.execute(
                "UPDATE missions SET state = 'EXECUTING', updated_at = ? WHERE mission_id = ?",
                (_utc_now(), mission_id),
            )

        replan_used = False
        while True:
            mission = self.get_mission(mission_id)
            steps = mission["steps"]
            context = dict(mission["context"])
            step_by_id = {s["task_id"]: s for s in steps}

            progressed = False
            for step in steps:
                if step["status"] in {"COMPLETED", "SKIPPED"}:
                    continue
                if step["status"] in {"BLOCKED", "FAILED"}:
                    return self.get_mission(mission_id)

                spec = step["spec"]
                deps = spec.get("dependencies", [])
                if any(step_by_id[d]["status"] != "COMPLETED" for d in deps if d in step_by_id):
                    continue

                if spec.get("approval_policy") == "tier2_approval" and not step["approved"]:
                    with self._conn:
                        self._conn.execute(
                            "UPDATE mission_steps SET status = 'WAITING_APPROVAL' WHERE mission_id = ? AND task_id = ?",
                            (mission_id, step["task_id"]),
                        )
                        self._conn.execute(
                            "UPDATE missions SET state = 'WAITING_APPROVAL', updated_at = ? WHERE mission_id = ?",
                            (_utc_now(), mission_id),
                        )
                    return self.get_mission(mission_id)

                # Idempotency guard for side-effecting steps across retries/restarts
                idem_key = spec.get("idempotency_key")
                if spec.get("effect") == "side_effecting" and idem_key:
                    existing = self._conn.execute(
                        "SELECT output_json, evidence_refs_json FROM executed_idempotency_keys WHERE idempotency_key = ?",
                        (idem_key,),
                    ).fetchone()
                    if existing is not None:
                        with self._conn:
                            self._conn.execute(
                                """
                                UPDATE mission_steps
                                SET status = 'COMPLETED', output_json = ?, evidence_refs_json = ?
                                WHERE mission_id = ? AND task_id = ?
                                """,
                                (
                                    existing["output_json"],
                                    existing["evidence_refs_json"],
                                    mission_id,
                                    step["task_id"],
                                ),
                            )
                        progressed = True
                        break

                # Precondition check
                for cond in spec.get("preconditions", []):
                    ok = precondition_checker(cond, context) if precondition_checker else bool(context.get(cond, True))
                    if not ok:
                        with self._conn:
                            self._conn.execute(
                                "UPDATE mission_steps SET status = 'BLOCKED' WHERE mission_id = ? AND task_id = ?",
                                (mission_id, step["task_id"]),
                            )
                            self._conn.execute(
                                "UPDATE missions SET state = 'BLOCKED', error_message = ?, updated_at = ? WHERE mission_id = ?",
                                (f"Precondition failed: {cond}", _utc_now(), mission_id),
                            )
                        return self.get_mission(mission_id)

                # Input contract check
                in_problems = _check_contract_types(
                    context, spec.get("input_contract", {}), f"{step['task_id']}.input"
                )
                if in_problems:
                    with self._conn:
                        self._conn.execute(
                            "UPDATE mission_steps SET status = 'BLOCKED' WHERE mission_id = ? AND task_id = ?",
                            (mission_id, step["task_id"]),
                        )
                        self._conn.execute(
                            "UPDATE missions SET state = 'BLOCKED', error_message = ?, updated_at = ? WHERE mission_id = ?",
                            ("; ".join(in_problems), _utc_now(), mission_id),
                        )
                    return self.get_mission(mission_id)

                tool_id = spec.get("tool_id", "")
                fn = executors.get(tool_id)
                if fn is None:
                    with self._conn:
                        self._conn.execute(
                            "UPDATE mission_steps SET status = 'BLOCKED' WHERE mission_id = ? AND task_id = ?",
                            (mission_id, step["task_id"]),
                        )
                        self._conn.execute(
                            "UPDATE missions SET state = 'BLOCKED', error_message = ?, updated_at = ? WHERE mission_id = ?",
                            (f"Executor unavailable for tool_id={tool_id!r}", _utc_now(), mission_id),
                        )
                    return self.get_mission(mission_id)

                max_attempts = int(spec.get("max_attempts", 1))
                last_error: str | None = None
                step_output: dict[str, Any] | None = None
                for attempt in range(1, max_attempts + 1):
                    with self._conn:
                        self._conn.execute(
                            "UPDATE mission_steps SET status = 'RUNNING', attempts = ? WHERE mission_id = ? AND task_id = ?",
                            (attempt, mission_id, step["task_id"]),
                        )
                    try:
                        candidate = fn(spec, context)
                        out_problems = _check_contract_types(
                            candidate,
                            spec.get("output_contract", {}),
                            f"{step['task_id']}.output",
                        )
                        if out_problems:
                            raise RuntimeError("; ".join(out_problems))
                        for post in spec.get("postconditions", []):
                            ok_post = (
                                postcondition_checker(post, candidate, context)
                                if postcondition_checker
                                else bool(candidate.get(post))
                            )
                            if not ok_post:
                                raise RuntimeError(f"Postcondition not verified: {post}")
                        step_output = candidate
                        last_error = None
                        break
                    except Exception as exc:
                        last_error = str(exc) or exc.__class__.__name__

                if step_output is not None:
                    ev_refs = list(step_output.get("evidence_refs", []))
                    if not ev_refs:
                        ev_refs = [f"step:{step['task_id']}:verified"]
                    out_json = json.dumps(step_output)
                    ev_json = json.dumps(ev_refs)
                    context.update({k: v for k, v in step_output.items() if k != "evidence_refs"})
                    with self._conn:
                        if spec.get("effect") == "side_effecting" and idem_key:
                            self._conn.execute(
                                """
                                INSERT OR IGNORE INTO executed_idempotency_keys
                                (idempotency_key, mission_id, task_id, output_json, evidence_refs_json, recorded_at)
                                VALUES (?, ?, ?, ?, ?, ?)
                                """,
                                (idem_key, mission_id, step["task_id"], out_json, ev_json, _utc_now()),
                            )
                        self._conn.execute(
                            """
                            UPDATE mission_steps
                            SET status = 'COMPLETED', output_json = ?, evidence_refs_json = ?
                            WHERE mission_id = ? AND task_id = ?
                            """,
                            (out_json, ev_json, mission_id, step["task_id"]),
                        )
                        self._conn.execute(
                            "UPDATE missions SET context_json = ?, updated_at = ? WHERE mission_id = ?",
                            (json.dumps(context), _utc_now(), mission_id),
                        )
                    progressed = True
                    break

                # Step exhausted attempts
                if replan_on_failure is not None and not replan_used:
                    replan_used = True
                    new_steps = replan_on_failure(mission, last_error or "step_failed")
                    if new_steps:
                        with self._conn:
                            self._conn.execute(
                                "UPDATE mission_steps SET status = 'SKIPPED' WHERE mission_id = ? AND task_id = ?",
                                (mission_id, step["task_id"]),
                            )
                            self._conn.execute(
                                "UPDATE missions SET state = 'RECOVERING', updated_at = ? WHERE mission_id = ?",
                                (_utc_now(), mission_id),
                            )
                        self.replan_mission(mission_id, new_steps)
                        with self._conn:
                            self._conn.execute(
                                "UPDATE missions SET state = 'EXECUTING', updated_at = ? WHERE mission_id = ?",
                                (_utc_now(), mission_id),
                            )
                        progressed = True
                        break

                with self._conn:
                    self._conn.execute(
                        "UPDATE mission_steps SET status = 'FAILED' WHERE mission_id = ? AND task_id = ?",
                        (mission_id, step["task_id"]),
                    )
                    self._conn.execute(
                        "UPDATE missions SET state = 'FAILED', error_message = ?, updated_at = ? WHERE mission_id = ?",
                        (last_error, _utc_now(), mission_id),
                    )
                return self.get_mission(mission_id)

            if not progressed:
                latest = self.get_mission(mission_id)
                if all(s["status"] in {"COMPLETED", "SKIPPED"} for s in latest["steps"]):
                    with self._conn:
                        self._conn.execute(
                            "UPDATE missions SET state = 'COMPLETED', updated_at = ? WHERE mission_id = ?",
                            (_utc_now(), mission_id),
                        )
                return self.get_mission(mission_id)
