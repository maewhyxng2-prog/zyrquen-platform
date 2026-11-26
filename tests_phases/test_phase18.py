from phases.phase18 import AdaptiveLearning

def test_controlled_learning_valid_feedback_pending():
    m = AdaptiveLearning(mode="online")
    out = m.submit_feedback({"text": "คำตอบนี้ดี", "source": "user", "evidence": "chat-123"})
    assert out["status"] == "pending"
    assert m.approve_feedback(out["feedback_id"])["status"] == "approved"

def test_controlled_learning_invalid_feedback_rejected():
    m = AdaptiveLearning(mode="online")
    out = m.submit_feedback({"text": "ดี", "source": "", "evidence": ""})
    assert out["status"] == "rejected"
    # Rejected feedback cannot be approved
    assert m.approve_feedback(out["feedback_id"])["status"] == "blocked"

def test_replay_requires_approved_feedback():
    m = AdaptiveLearning(mode="online")
    out = m.submit_feedback({"text": "แก้คำตอบ", "source": "user", "evidence": "chat-1"})
    fid = out["feedback_id"]
    assert m.replay(fid)["status"] == "blocked"
    m.approve_feedback(fid)
    assert m.replay(fid)["status"] == "ok"

def test_replay_has_trace_and_regression_gate():
    m = AdaptiveLearning(mode="online")
    fid = m.submit_feedback({"text": "test", "source": "user", "evidence": "e1"})["feedback_id"]
    m.approve_feedback(fid)
    out = m.replay(fid)
    run = out["runs"][0]
    assert run["trace_id"].startswith("trace-")
    assert run["regression_gate"] == "passed"
    assert run["result"] == "replayed"

def test_zero_mutation_online_blocked():
    m = AdaptiveLearning(mode="online")
    out = m.try_mutate_weights(approved=True, evaluation_passed=True)
    assert out["status"] == "blocked"
    assert out["mutated"] is False

def test_zero_mutation_offline_requires_approval_and_evaluation():
    m = AdaptiveLearning(mode="offline-approved")
    assert m.try_mutate_weights(approved=False, evaluation_passed=True)["status"] == "blocked"
    assert m.try_mutate_weights(approved=True, evaluation_passed=False)["status"] == "blocked"
    out = m.try_mutate_weights(approved=True, evaluation_passed=True)
    assert out["status"] == "allowed_for_offline_review"
    assert out["mutated"] is False  # no auto-promote, no real mutation in this phase
