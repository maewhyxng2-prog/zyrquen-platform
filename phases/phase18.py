"""Phase 18 — Adaptive Learning & Improvement — pure logic only.

No real training, no online weight mutation, no auto-promote,
no dataset download, no external AI.
"""
import itertools

class AdaptiveLearning:
    """Controlled Learning + Feedback/Replay + Zero Online Weight Mutation."""

    def __init__(self, mode="online"):
        if mode not in ("online", "offline", "offline-approved"):
            mode = "online"
        self.mode = mode
        self._feedbacks = {}
        self._counter = itertools.count(1)
        self._replay_counter = itertools.count(1)

    def submit_feedback(self, feedback):
        fb = feedback or {}
        text = str(fb.get("text", "")).strip()
        source = str(fb.get("source", "")).strip()
        evidence = str(fb.get("evidence", "")).strip()
        fid = f"fb-{next(self._counter)}"
        if not text or not source or not evidence:
            self._feedbacks[fid] = {"status": "rejected", "reason": "missing text/source/evidence", "feedback": fb}
            return {"status": "rejected", "feedback_id": fid, "reason": "missing text/source/evidence"}
        self._feedbacks[fid] = {"status": "pending", "feedback": fb}
        return {"status": "pending", "feedback_id": fid}

    def approve_feedback(self, feedback_id):
        entry = self._feedbacks.get(feedback_id)
        if not entry:
            return {"status": "blocked", "reason": "feedback not found"}
        if entry["status"] != "pending":
            return {"status": "blocked", "reason": f"cannot approve {entry['status']} feedback"}
        entry["status"] = "approved"
        return {"status": "approved", "feedback_id": feedback_id}

    def replay(self, feedback_id):
        entry = self._feedbacks.get(feedback_id)
        if not entry:
            return {"status": "blocked", "reason": "feedback not found", "runs": []}
        if entry["status"] != "approved":
            return {"status": "blocked", "reason": "feedback not approved", "runs": []}
        run_id = f"run-{next(self._replay_counter)}"
        trace_id = f"trace-{feedback_id}-{run_id}"
        # Simulated evaluation / regression gate — Phase 14 link point.
        # No real training happens here.
        return {
            "status": "ok",
            "feedback_id": feedback_id,
            "runs": [{
                "run_id": run_id,
                "result": "replayed",
                "trace_id": trace_id,
                "regression_gate": "passed",
            }],
        }

    def try_mutate_weights(self, approved=False, evaluation_passed=False):
        if self.mode == "online":
            return {"status": "blocked", "reason": "zero online weight mutation", "mutated": False}
        if self.mode != "offline-approved":
            return {"status": "blocked", "reason": "training only in offline-approved mode", "mutated": False}
        if not approved or not evaluation_passed:
            return {"status": "blocked", "reason": "requires approval + evaluation passed", "mutated": False}
        # Even when allowed, this phase never mutates weights itself.
        # Promotion must be a separate human-approved step — no auto-promote.
        return {"status": "allowed_for_offline_review", "reason": "requires human promote step", "mutated": False}
