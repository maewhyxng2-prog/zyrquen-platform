"""Planning contract (Phase 9.4). Structural checks only, not model reasoning."""

ALLOWED_GENERATED_BY = frozenset({"manual", "rule_based", "model_generated"})
ALLOWED_PLAN_STATUS = frozenset({"valid_structure", "invalid_structure"})
REQUIRED_PLAN_KEYS = frozenset({"goal", "context", "steps", "generated_by"})
REQUIRED_STEP_KEYS = frozenset(
    {"id", "description", "depends_on", "success_criteria"})


class PlanViolation(ValueError):
    pass


def _text(v):
    return isinstance(v, str) and v.strip() != ""


def _evidence_ok(e):
    return (isinstance(e, dict) and _text(e.get("model_id"))
            and _text(e.get("response")))


def _result(problems, order):
    bad = bool(problems)
    return {
        "status": "invalid_structure" if bad else "valid_structure",
        "problems": problems,
        "step_order": [] if bad else order,
    }


def analyze_plan(plan, native_model_evidence=None):
    if not isinstance(plan, dict):
        return _result(["plan must be a dict"], [])
    problems = []
    missing = REQUIRED_PLAN_KEYS - set(plan)
    if missing:
        problems.append("missing plan keys: %s" % sorted(missing))
    if "goal" in plan and not _text(plan["goal"]):
        problems.append("goal must be non-empty text")
    if "context" in plan and not isinstance(plan["context"], dict):
        problems.append("context must be a dict")
    gen = plan.get("generated_by")
    if "generated_by" in plan:
        if gen not in ALLOWED_GENERATED_BY:
            problems.append("generated_by not allowed: %r" % (gen,))
        elif gen == "model_generated" and not _evidence_ok(
                native_model_evidence):
            problems.append("model_generated requires native model evidence")

    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        problems.append("steps must be a non-empty list")
        return _result(problems, [])

    graph = {}
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            problems.append("step %d must be a dict" % i)
            continue
        miss = REQUIRED_STEP_KEYS - set(s)
        if miss:
            problems.append("step %d missing keys: %s" % (i, sorted(miss)))
        if "description" in s and not _text(s["description"]):
            problems.append("step %d description empty" % i)
        if "success_criteria" in s and not _text(s["success_criteria"]):
            problems.append("step %d success_criteria empty" % i)
        if "depends_on" in s and not isinstance(s["depends_on"], list):
            problems.append("step %d depends_on must be a list" % i)
        sid = s.get("id")
        if "id" in s and not _text(sid):
            problems.append("step %d id must be non-empty text" % i)
        elif _text(sid):
            if sid in graph:
                problems.append("duplicate step id: %r" % sid)
            else:
                graph[sid] = set()

    for s in steps:
        if not isinstance(s, dict) or not _text(s.get("id")):
            continue
        sid = s["id"]
        deps = s.get("depends_on")
        if not isinstance(deps, list):
            continue
        for d in deps:
            if not _text(d):
                problems.append("step %r has invalid dependency" % sid)
            elif d == sid:
                problems.append("step %r depends on itself" % sid)
            elif d not in graph:
                problems.append("step %r depends on unknown %r" % (sid, d))
            else:
                graph[sid].add(d)

    order = []
    remaining = {k: set(v) for k, v in graph.items()}
    while remaining:
        ready = sorted(k for k, v in remaining.items() if not v)
        if not ready:
            problems.append(
                "dependency cycle among: %s" % sorted(remaining))
            break
        for k in ready:
            order.append(k)
            del remaining[k]
        for v in remaining.values():
            v.difference_update(ready)
    return _result(problems, order)


def validate_plan(plan, native_model_evidence=None):
    r = analyze_plan(plan, native_model_evidence)
    if r["status"] != "valid_structure":
        raise PlanViolation("; ".join(r["problems"]))
    return r
