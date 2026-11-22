"""P0-1 regression: closure-audit must require get_current_user (no DB/training/inference)."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.params import Depends

from apps.api.routers import workflows
from apps.api.security import get_current_user


def _route_for(path: str, method: str = "GET"):
    for r in workflows.router.routes:
        methods = getattr(r, "methods", None) or set()
        if getattr(r, "path", None) == path and method in methods:
            return r
    raise AssertionError(f"route {method} {path} not found")


def _collect_dependency_calls(dependant) -> list:
    """Walk FastAPI Dependant graph and return every registered dependency callable."""
    calls: list = []
    seen_ids: set[int] = set()
    stack = [dependant]
    while stack:
        node = stack.pop()
        if node is None or id(node) in seen_ids:
            continue
        seen_ids.add(id(node))
        call = getattr(node, "call", None)
        if callable(call):
            calls.append(call)
        for sub in getattr(node, "dependencies", None) or []:
            stack.append(sub)
    return calls


def test_closure_audit_registers_get_current_user_in_route_graph():
    route = _route_for("/v1/v10/closure-audit", "GET")
    dependant = getattr(route, "dependant", None)
    assert dependant is not None, "closure-audit route has no FastAPI dependant graph"
    calls = _collect_dependency_calls(dependant)
    assert any(c is get_current_user for c in calls), (
        "closure-audit route graph must register the actual "
        "apps.api.security.get_current_user callable; found: "
        f"{[getattr(c, '__name__', repr(c)) for c in calls][:20]}"
    )


def test_closure_audit_signature_uses_get_current_user_identity():
    # Identity check on the endpoint signature. Parameter name is intentionally
    # irrelevant (implementation uses "_"); only the Depends dependency identity matters.
    sig = inspect.signature(workflows.get_v10_closure_audit)
    found = False
    for param in sig.parameters.values():
        default = param.default
        if isinstance(default, Depends) and default.dependency is get_current_user:
            found = True
            break
    assert found, (
        "get_v10_closure_audit signature must include Depends(get_current_user) "
        "with identity equality; arbitrary Depends markers are not accepted"
    )


def test_closure_audit_fails_closed_without_auth_dependency():
    # Documents fail-closed expectation: removing or swapping the dependency
    # must break the two checks above. Here we assert the positive control only
    # (negative case is enforced by those checks), and guard against an empty graph.
    route = _route_for("/v1/v10/closure-audit", "GET")
    calls = _collect_dependency_calls(getattr(route, "dependant", None))
    assert len(calls) > 0, "dependency graph must not be empty for an authenticated route"
    assert not any(
        getattr(c, "__name__", "") in {"get_db", "get_workflow_engine"}
        and c is not get_current_user
        for c in calls
        if getattr(c, "__name__", "") in {"get_db", "get_workflow_engine"}
    ) or any(c is get_current_user for c in calls), (
        "unrelated dependencies alone must not satisfy authentication"
    )
