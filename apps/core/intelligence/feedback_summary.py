"""Read-only feedback summary (Phase 9.5.3).

Counts feedback records by rating, per target and per source. It changes
nothing: no records, no behaviour, no model weights.

sufficient_sample only means a group reached MIN_SAMPLE_PER_GROUP records.
It is NOT statistical evidence that the system is accurate or improving.
"""
from .feedback_contract import (
    ALLOWED_RATINGS, ALLOWED_SOURCES, ALLOWED_TARGETS, analyze_feedback)

MIN_SAMPLE_PER_GROUP = 30
ALLOWED_EVIDENCE_LEVELS = frozenset(
    {"no_data", "insufficient_sample", "sufficient_sample"})
EVIDENCE_NOTE = (
    "sufficient_sample only means the sample count reached the minimum; it "
    "is not statistical evidence that the system is accurate or improving.")

_RATINGS = tuple(sorted(ALLOWED_RATINGS))


def _empty():
    return {r: 0 for r in _RATINGS}


def _evidence_level(n):
    if n == 0:
        return "no_data"
    if n < MIN_SAMPLE_PER_GROUP:
        return "insufficient_sample"
    return "sufficient_sample"


def _group(counts):
    n = sum(counts.values())
    level = _evidence_level(n)
    proportions = None
    if level == "sufficient_sample":
        proportions = {r: counts[r] / n for r in _RATINGS}
    return {
        "total": n,
        "evidence_level": level,
        "counts": dict(counts),
        "proportions": proportions,
    }


def summarize(records):
    if not isinstance(records, (list, tuple)):
        raise TypeError("records must be a list or tuple")
    overall = _empty()
    by_target = {t: _empty() for t in sorted(ALLOWED_TARGETS)}
    by_source = {s: _empty() for s in sorted(ALLOWED_SOURCES)}
    seen = set()
    invalid = 0
    duplicate = 0
    for rec in records:
        if analyze_feedback(rec)["status"] != "accepted_for_log":
            invalid += 1
            continue
        if rec["id"] in seen:
            duplicate += 1
            continue
        seen.add(rec["id"])
        rating = rec["rating"]
        overall[rating] += 1
        by_target[rec["target"]][rating] += 1
        by_source[rec["source"]][rating] += 1
    return {
        "overall": _group(overall),
        "by_target": {k: _group(v) for k, v in by_target.items()},
        "by_source": {k: _group(v) for k, v in by_source.items()},
        "skipped_invalid": invalid,
        "skipped_duplicate": duplicate,
        "min_sample_per_group": MIN_SAMPLE_PER_GROUP,
        "evidence_note": EVIDENCE_NOTE,
        "model_weights_changed": False,
    }
