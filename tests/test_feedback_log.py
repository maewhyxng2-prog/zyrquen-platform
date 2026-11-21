import threading
import unittest

from apps.core.intelligence.feedback_contract import ALLOWED_FEEDBACK_STATUS
from apps.core.intelligence.feedback_log import FeedbackLog


def _rec(**over):
    r = {"id": "fb-1", "target": "planning", "rating": "correct",
         "comment": "", "source": "evaluator",
         "created_at": "2026-11-21T10:00:00Z"}
    r.update(over)
    return r


class TestFeedbackLog(unittest.TestCase):
    def test_accepted_is_stored(self):
        log = FeedbackLog()
        r = log.submit(_rec())
        self.assertEqual(r["status"], "accepted_for_log")
        self.assertIs(r["stored"], True)
        self.assertEqual(len(log), 1)
        self.assertEqual(log.records()[0]["id"], "fb-1")

    def test_rejected_not_stored(self):
        log = FeedbackLog()
        for bad in (_rec(rating="applied"), None, _rec(created_at="x")):
            r = log.submit(bad)
            self.assertEqual(r["status"], "rejected_invalid")
            self.assertIs(r["stored"], False)
        self.assertEqual(len(log), 0)

    def test_duplicate_id_rejected_and_not_stored(self):
        log = FeedbackLog()
        log.submit(_rec())
        r = log.submit(_rec(rating="incorrect", comment="again"))
        self.assertEqual(r["status"], "rejected_invalid")
        self.assertIn("duplicate", " ".join(r["problems"]))
        self.assertEqual(len(log), 1)
        self.assertEqual(log.records()[0]["rating"], "correct")

    def test_rejected_record_does_not_consume_id(self):
        log = FeedbackLog()
        self.assertEqual(
            log.submit(_rec(rating="bad"))["status"], "rejected_invalid")
        self.assertEqual(log.submit(_rec())["status"], "accepted_for_log")
        self.assertEqual(len(log), 1)

    def test_concurrent_same_id_only_one_accepted(self):
        log = FeedbackLog()
        results = []

        def worker():
            results.append(log.submit(_rec()))

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        accepted = [r for r in results if r["status"] == "accepted_for_log"]
        self.assertEqual(len(results), 20)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(log), 1)

    def test_append_only_surface(self):
        log = FeedbackLog()
        for name in ("delete", "remove", "update", "pop", "clear",
                     "__setitem__", "__delitem__"):
            self.assertFalse(hasattr(log, name), name)

    def test_records_returns_copies(self):
        log = FeedbackLog()
        log.submit(_rec())
        recs = log.records()
        recs[0]["rating"] = "incorrect"
        recs.append({"x": 1})
        self.assertEqual(log.records()[0]["rating"], "correct")
        self.assertEqual(len(log), 1)

    def test_input_mutation_after_submit_does_not_change_log(self):
        log = FeedbackLog()
        rec = _rec()
        log.submit(rec)
        rec["rating"] = "incorrect"
        self.assertEqual(log.records()[0]["rating"], "correct")

    def test_accepted_does_not_mean_applied(self):
        r = FeedbackLog().submit(_rec())
        self.assertEqual(
            set(r), {"status", "problems", "stored", "model_weights_changed"})
        self.assertIs(r["model_weights_changed"], False)
        self.assertNotIn("applied", r)

    def test_order_preserved_and_statuses_closed(self):
        log = FeedbackLog()
        for i in ("a", "b", "c"):
            r = log.submit(_rec(id=i))
            self.assertIn(r["status"], ALLOWED_FEEDBACK_STATUS)
        self.assertEqual([x["id"] for x in log.records()], ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
