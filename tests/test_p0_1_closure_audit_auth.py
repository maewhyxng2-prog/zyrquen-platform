"""P0-1 regression: closure-audit must require get_current_user (no DB/training/inference)."""

from __future__ import annotations

import ast
import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from fastapi.params import Depends
    from apps.api.routers import workflows
    from apps.api.security import get_current_user
    _HAS_FASTAPI = True
except ImportError:
    Depends = None  # type: ignore[assignment]
    workflows = None  # type: ignore[assignment]
    get_current_user = None  # type: ignore[assignment]
    _HAS_FASTAPI = False


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


class TestClosureAuditAuth(unittest.TestCase):
    def test_closure_audit_auth_contract_in_source(self):
        workflows_path = ROOT / "apps" / "api" / "routers" / "workflows.py"
        tree = ast.parse(workflows_path.read_text(encoding="utf-8"), filename=str(workflows_path))
        target_fn = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "get_v10_closure_audit":
                target_fn = node
                break
        self.assertIsNotNone(target_fn, "get_v10_closure_audit endpoint missing")
        assert target_fn is not None
        has_get_route = any(
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.func.attr == "get"
            and dec.args
            and isinstance(dec.args[0], ast.Constant)
            and dec.args[0].value == "/v1/v10/closure-audit"
            for dec in target_fn.decorator_list
        )
        self.assertTrue(has_get_route, "/v1/v10/closure-audit GET route decorator missing")
        has_depends_current_user = any(
            isinstance(default, ast.Call)
            and isinstance(default.func, ast.Name)
            and default.func.id == "Depends"
            and default.args
            and isinstance(default.args[0], ast.Name)
            and default.args[0].id == "get_current_user"
            for default in target_fn.args.defaults
        )
        self.assertTrue(
            has_depends_current_user,
            "get_v10_closure_audit must declare Depends(get_current_user)",
        )

    @unittest.skipUnless(_HAS_FASTAPI, "Requires FastAPI runtime dependencies (verified in API Tests workflow)")
    def test_closure_audit_registers_get_current_user_in_route_graph(self):
        route = _route_for("/v1/v10/closure-audit", "GET")
        dependant = getattr(route, "dependant", None)
        self.assertIsNotNone(dependant, "closure-audit route has no FastAPI dependant graph")
        calls = _collect_dependency_calls(dependant)
        self.assertTrue(
            any(c is get_current_user for c in calls),
            "closure-audit route graph must register the actual "
            "apps.api.security.get_current_user callable; found: "
            f"{[getattr(c, '__name__', repr(c)) for c in calls][:20]}",
        )

    @unittest.skipUnless(_HAS_FASTAPI, "Requires FastAPI runtime dependencies (verified in API Tests workflow)")
    def test_closure_audit_signature_uses_get_current_user_identity(self):
        sig = inspect.signature(workflows.get_v10_closure_audit)
        found = False
        for param in sig.parameters.values():
            default = param.default
            if isinstance(default, Depends) and default.dependency is get_current_user:
                found = True
                break
        self.assertTrue(
            found,
            "get_v10_closure_audit signature must include Depends(get_current_user) "
            "with identity equality; arbitrary Depends markers are not accepted",
        )

    @unittest.skipUnless(_HAS_FASTAPI, "Requires FastAPI runtime dependencies (verified in API Tests workflow)")
    def test_closure_audit_fails_closed_without_auth_dependency(self):
        route = _route_for("/v1/v10/closure-audit", "GET")
        calls = _collect_dependency_calls(getattr(route, "dependant", None))
        self.assertGreater(len(calls), 0, "dependency graph must not be empty for an authenticated route")
        self.assertTrue(
            not any(
                getattr(c, "__name__", "") in {"get_db", "get_workflow_engine"}
                and c is not get_current_user
                for c in calls
                if getattr(c, "__name__", "") in {"get_db", "get_workflow_engine"}
            )
            or any(c is get_current_user for c in calls),
            "unrelated dependencies alone must not satisfy authentication",
        )


if __name__ == "__main__":
    unittest.main()
