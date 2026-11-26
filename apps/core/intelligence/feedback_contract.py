"""Feedback contract (Phase 9.5.1). Validates feedback records only.

accepted_for_log means the record is well-formed and may be logged. It does
NOT mean the feedback was applied or that any model learned from it.
"""
from datetime import datetime

ALLOWED_TARGETS = frozenset({"reasoning", "planning"})
ALLOWED_RATINGS = frozenset({"correct", "incorrect", "partially_correct"})
ALLOWED_SOURCES = frozenset({"user", "evaluator", "automated_test"})
ALLOWED_FEEDBACK_STATUS = frozenset({"accepted_for_log", "rejected_invalid"})
REQUIRED_KEYS = frozenset(
    {"id", "target", "rating", "comment", "source", "created_at"})


def _text(v):
    return isinstance(v, str) and v.strip() != ""


def _member(v, allowed):
    return isinstance(v, str) and v in allowed


def parse_iso8601(value):
    """Return a timezone-aware datetime, or None if value is not valid."""
    if not isinstance(value, str) or value != value.strip() or "T" not in value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt


def _result(problems):
    return {
        "status": "rejected_invalid" if problems else "accepted_for_log",
        "problems": problems,
        "model_weights_changed": False,
    }


def analyze_feedback(record):
    if not isinstance(record, dict):
        return _result(["record must be a dict"])
    problems = []
    missing = REQUIRED_KEYS - set(record)
    if missing:
        problems.append("missing keys: %s" % sorted(missing))
    extra = set(record) - REQUIRED_KEYS
    if extra:
        problems.append("unknown keys: %s" % sorted(map(repr, extra)))
    if "id" in record and not _text(record["id"]):
        problems.append("id must be non-empty text")
    if "target" in record and not _member(record["target"], ALLOWED_TARGETS):
        problems.append("target not allowed: %r" % (record["target"],))
    if "rating" in record and not _member(record["rating"], ALLOWED_RATINGS):
        problems.append("rating not allowed: %r" % (record["rating"],))
    if "source" in record and not _member(record["source"], ALLOWED_SOURCES):
        problems.append("source not allowed: %r" % (record["source"],))
    if "created_at" in record and parse_iso8601(record["created_at"]) is None:
        problems.append("created_at must be ISO 8601 with timezone")
    if "comment" in record:
        if not isinstance(record["comment"], str):
            problems.append("comment must be text")
        elif record.get("rating") == "incorrect" and not _text(record["comment"]):
            problems.append("comment required when rating is incorrect")
    return _result(problems)
