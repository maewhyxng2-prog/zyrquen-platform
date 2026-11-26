"""Append-only in-memory feedback log (Phase 9.5.2).

Stores validated records only. Nothing here changes model weights or system
behaviour; a stored record is only a record.
"""
import copy
import threading

from .feedback_contract import analyze_feedback


class FeedbackLog:
    def __init__(self):
        self._records = []
        self._ids = set()
        self._lock = threading.Lock()

    def __len__(self):
        with self._lock:
            return len(self._records)

    def records(self):
        with self._lock:
            return copy.deepcopy(self._records)

    @staticmethod
    def _result(status, problems, stored):
        return {
            "status": status,
            "problems": problems,
            "stored": stored,
            "model_weights_changed": False,
        }

    def submit(self, record):
        try:
            snapshot = copy.deepcopy(record)
        except Exception:
            return self._result(
                "rejected_invalid", ["record could not be copied"], False)
        analysis = analyze_feedback(snapshot)
        if analysis["status"] != "accepted_for_log":
            return self._result(
                "rejected_invalid", list(analysis["problems"]), False)
        with self._lock:
            if snapshot["id"] in self._ids:
                return self._result(
                    "rejected_invalid",
                    ["duplicate id: %r" % snapshot["id"]], False)
            self._ids.add(snapshot["id"])
            self._records.append(snapshot)
        return self._result("accepted_for_log", [], True)
