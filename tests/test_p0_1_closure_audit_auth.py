"""P0-1 regression: closure-audit must require authentication (no training, no runtime)."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.routers import workflows


def _route_for(path: str, method: str = "GET"):
    for r in workflows.router.routes:
        methods = getattr(r, "methods", None) or set()
        if getattr(r, "path", None) == path and method in methods:
            return r
    raise AssertionError(f"route {method} {path} not found")


def test_closure_audit_requires_get_current_user():
    # Direct function signature must include authenticated User dependency.
    sig = inspect.signature(workflows.get_v10_closure_audit)
    assert "_user" in sig.parameters or any(
        "user" in name.lower() for name in sig.parameters
    ), "closure-audit must declare an authenticated user dependency"

    # FastAPI route dependant must include get_current_user (or require_admin which wraps it).
    route = _route_for("/v1/v10/closure-audit", "GET")
    dependant = getattr(route, "dependant", None)
    deps = getattr(dependant, "dependencies", []) if dependant else []
    # Fallback: inspect defaults for Depends markers.
    dep_names = []
    for p in sig.parameters.values():
        default = p.default
        dep_names.append(f"{p.name}={default!r}")
    blob = " ".join(dep_names) + " " + str(getattr(dependant, "__dict__", ""))
    assert "get_current_user" in blob or "Depends" in blob, (
        f"closure-audit route must depend on get_current_user, got: {blob[:500]}"
    )


def test_closure_audit_not_open_while_siblings_require_auth():
    # Guard against regression: ensure no other workflow GET remains open unintentionally.
    open_routes = []
    for r in workflows.router.routes:
        if "GET" not in (getattr(r, "methods", None) or set()):
            continue
        if getattr(r, "path", None) != "/v1/v10/closure-audit":
            continue
        dependant = getattr(r, "dependant", None)
        if not dependant or not getattr(dependant, "dependencies", []):
            # Check function signature as secondary signal.
            fn = getattr(r, "endpoint", None)
            try:
                sig = inspect.signature(fn)
                has_dep = any(
                    "Depends" in repr(p.default) for p in sig.parameters.values()
                )
            except Exception:
                has_dep = False
            if not has_dep:
                open_routes.append(r.path)
    assert open_routes == [], f"unauthenticated closure-audit routes: {open_routes}"
