"""
Tool Dependency Manager for ZYRQUEN Tool Center.
------------------------------------------------
Validates capability dependency graphs, enforces SemVer compatibility constraints,
detects dependency cycles & conflicts before execution, and computes topological
execution waves for safe sequential or controlled parallel orchestration.
Pure Python 3.11 standard library.
"""

from __future__ import annotations

import collections
import importlib
import re
from typing import Any

_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")
_CONSTRAINT_RE = re.compile(r"^([A-Za-z0-9_.\-]+?)\s*(>=|<=|==|!=|>|<|\^)?\s*(v?\d+\.\d+\.\d+)?$")


def parse_semver(version: str) -> tuple[int, int, int] | None:
    m = _SEMVER_RE.match(str(version or "").strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def parse_dependency_token(raw: str) -> tuple[str, str | None, str | None]:
    """
    Parse dependency specification such as:
      - 'development.code_analysis'
      - 'development.code_analysis>=1.0.0'
      - 'python_core.tools_engine'
    Returns (target_id, operator, required_version).
    """
    clean = str(raw or "").strip()
    m = _CONSTRAINT_RE.match(clean)
    if not m:
        return clean, None, None
    return m.group(1).strip(), m.group(2), m.group(3)


def satisfies_semver(actual: str, op: str | None, required: str | None) -> bool:
    if not op or not required:
        return True
    v_act = parse_semver(actual)
    v_req = parse_semver(required)
    if v_act is None or v_req is None:
        return actual == required if op == "==" else False
    if op == "==":
        return v_act == v_req
    if op == "!=":
        return v_act != v_req
    if op == ">=":
        return v_act >= v_req
    if op == "<=":
        return v_act <= v_req
    if op == ">":
        return v_act > v_req
    if op == "<":
        return v_act < v_req
    if op == "^":
        return v_act[0] == v_req[0] and v_act >= v_req
    return False


class ToolDependencyManager:
    """Validates dependencies, detects version conflicts, and builds parallel execution waves."""

    def check_capability(self, registry: Any, capability_id: str) -> dict[str, Any]:
        spec = registry.get_spec(capability_id)
        if spec is None:
            return {
                "ok": False,
                "capability_id": capability_id,
                "missing": [capability_id],
                "conflicts": [],
                "checked": [],
            }

        missing: list[str] = []
        conflicts: list[dict[str, Any]] = []
        checked: list[dict[str, Any]] = []
        visited: set[str] = set()

        def _visit(cid: str, trail: list[str]) -> None:
            if cid in trail:
                conflicts.append({
                    "type": "dependency_cycle",
                    "cycle": trail + [cid],
                })
                return
            if cid in visited:
                return
            visited.add(cid)
            cur_spec = registry.get_spec(cid)
            if cur_spec is None:
                missing.append(cid)
                return

            for raw_dep in cur_spec.dependencies:
                dep_target, op, req_ver = parse_dependency_token(raw_dep)
                dep_spec = registry.get_spec(dep_target)
                if dep_spec is not None:
                    status_ok = dep_spec.lifecycle_status == "READY"
                    ver_ok = satisfies_semver(dep_spec.version, op, req_ver)
                    available = status_ok and ver_ok
                    entry: dict[str, Any] = {
                        "dependency": dep_target,
                        "constraint": f"{op or ''}{req_ver or ''}" or "any",
                        "resolved_version": dep_spec.version,
                        "lifecycle_status": dep_spec.lifecycle_status,
                        "kind": "capability",
                        "available": available,
                    }
                    checked.append(entry)
                    if not status_ok:
                        missing.append(dep_target)
                    if not ver_ok:
                        conflicts.append({
                            "type": "version_conflict",
                            "capability": cid,
                            "dependency": dep_target,
                            "required": f"{op}{req_ver}",
                            "actual": dep_spec.version,
                        })
                    _visit(dep_target, trail + [cid])
                else:
                    try:
                        importlib.import_module(dep_target)
                        checked.append({
                            "dependency": dep_target,
                            "kind": "python_module",
                            "available": True,
                        })
                    except Exception as exc:
                        checked.append({
                            "dependency": dep_target,
                            "kind": "python_module",
                            "available": False,
                            "error": str(exc),
                        })
                        missing.append(dep_target)

        _visit(capability_id, [])
        return {
            "ok": len(missing) == 0 and len(conflicts) == 0,
            "capability_id": capability_id,
            "capability_version": spec.version,
            "missing": sorted(set(missing)),
            "conflicts": conflicts,
            "checked": checked,
        }

    def check_environment(self, registry: Any) -> dict[str, Any]:
        """Audit all registered capabilities for missing dependencies or version conflicts."""
        reports: list[dict[str, Any]] = []
        conflicts_total = 0
        missing_total = 0
        for cid in registry.list_capability_ids():
            rep = self.check_capability(registry, cid)
            reports.append(rep)
            conflicts_total += len(rep["conflicts"])
            missing_total += len(rep["missing"])
        return {
            "ok": conflicts_total == 0 and missing_total == 0,
            "capabilities_checked": len(reports),
            "conflicts_count": conflicts_total,
            "missing_count": missing_total,
            "details": [r for r in reports if not r["ok"]],
        }

    def plan_execution_waves(
        self,
        steps: list[dict[str, Any]],
        registry: Any | None = None,
    ) -> dict[str, Any]:
        """
        Validate a multi-step DAG and group dependency-free steps into topological waves
        for controlled parallel execution. Detects duplicate IDs, missing deps, cycles,
        and capability version conflicts before anything executes.
        """
        if not steps:
            return {"ok": False, "error": "Execution plan contains zero steps.", "waves": [], "conflicts": []}

        step_ids: list[str] = []
        step_map: dict[str, dict[str, Any]] = {}
        for idx, s in enumerate(steps):
            sid = str(s.get("step_id") or f"step_{idx + 1}").strip()
            if sid in step_map:
                return {"ok": False, "error": f"Duplicate step_id '{sid}' in execution plan.", "waves": [], "conflicts": []}
            norm = {**s, "step_id": sid, "depends_on": list(s.get("depends_on") or [])}
            step_ids.append(sid)
            step_map[sid] = norm

        conflicts: list[dict[str, Any]] = []
        indegree: dict[str, int] = {sid: 0 for sid in step_ids}
        dependents: dict[str, list[str]] = collections.defaultdict(list)
        cap_versions_seen: dict[str, set[str]] = collections.defaultdict(set)

        for sid in step_ids:
            step = step_map[sid]
            cid = str(step.get("capability_id") or "")
            req_ver = step.get("version_constraint")
            if registry is not None and cid:
                dep_rep = self.check_capability(registry, cid)
                if not dep_rep["ok"]:
                    conflicts.append({
                        "step_id": sid,
                        "capability_id": cid,
                        "missing": dep_rep["missing"],
                        "conflicts": dep_rep["conflicts"],
                    })
                spec = registry.get_spec(cid)
                if spec is not None:
                    cap_versions_seen[cid].add(spec.version)
                    if req_ver:
                        _, op, ver = parse_dependency_token(f"{cid}{req_ver}" if not str(req_ver)[0].isalnum() else f"{cid}=={req_ver}")
                        if not satisfies_semver(spec.version, op, ver):
                            conflicts.append({
                                "step_id": sid,
                                "capability_id": cid,
                                "type": "requested_version_mismatch",
                                "required": str(req_ver),
                                "actual": spec.version,
                            })

            for dep in step["depends_on"]:
                if dep == sid or dep not in step_map:
                    return {
                        "ok": False,
                        "error": f"Step '{sid}' references invalid dependency '{dep}'.",
                        "waves": [],
                        "conflicts": conflicts,
                    }
                indegree[sid] += 1
                dependents[dep].append(sid)

        if conflicts:
            return {
                "ok": False,
                "error": f"Dependency or version conflict detected on {len(conflicts)} step(s).",
                "waves": [],
                "conflicts": conflicts,
            }

        waves: list[list[dict[str, Any]]] = []
        ready = sorted([sid for sid, deg in indegree.items() if deg == 0])
        processed = 0

        while ready:
            wave_nodes = [step_map[sid] for sid in ready]
            waves.append(wave_nodes)
            processed += len(wave_nodes)
            next_ready: list[str] = []
            for sid in ready:
                for nxt in dependents.get(sid, []):
                    indegree[nxt] -= 1
                    if indegree[nxt] == 0:
                        next_ready.append(nxt)
            ready = sorted(next_ready)

        if processed != len(step_ids):
            return {
                "ok": False,
                "error": "Cycle detected in execution plan dependency graph.",
                "waves": [],
                "conflicts": [{"type": "cycle"}],
            }

        return {
            "ok": True,
            "wave_count": len(waves),
            "step_count": len(step_ids),
            "waves": waves,
            "conflicts": [],
        }
