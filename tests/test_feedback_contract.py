import unittest

from apps.core.intelligence.feedback_contract import (
    ALLOWED_FEEDBACK_STATUS, REQUIRED_KEYS, analyze_feedback, parse_iso8601)


def _rec(**over):
    r = {"id": "fb-1", "target": "reasoning", "rating": "correct",
         "comment": "", "source": "user",
         "created_at": "2026-11-21T10:00:00+07:00"}
    r.update(over)
    return r


def _bad(rec):
    r = analyze_feedback(rec)
    return r, " | ".join(r["problems"])


class TestFeedbackContract(unittest.TestCase):
    def test_valid_record_accepted(self):
        r = analyze_feedback(_rec())
        self.assertEqual(r["status"], "accepted_for_log")
        self.assertEqual(r["problems"], [])

    def test_valid_timezones(self):
        for ts in ("2026-11-21T10:00:00Z", "2026-11-21T10:00:00+07:00",
                   "2026-11-21T10:00:00-05:00",
                   "2026-11-21T10:00:00.123+00:00"):
            with self.subTest(ts):
                self.assertEqual(
                    analyze_feedback(_rec(created_at=ts))["status"],
                    "accepted_for_log")
                self.assertIsNotNone(parse_iso8601(ts).utcoffset())

    def test_rejects_non_dict(self):
        for bad in (None, 5, [], "x"):
            with self.subTest(bad):
                self.assertEqual(
                    analyze_feedback(bad)["status"], "rejected_invalid")

    def test_rejects_missing_keys(self):
        for key in sorted(REQUIRED_KEYS):
            with self.subTest(key):
                r = _rec()
                del r[key]
                res, txt = _bad(r)
                self.assertEqual(res["status"], "rejected_invalid")
                self.assertIn("missing", txt)

    def test_rejects_unknown_keys(self):
        res, txt = _bad(_rec(applied=True))
        self.assertEqual(res["status"], "rejected_invalid")
        self.assertIn("unknown keys", txt)

    def test_rejects_bad_target(self):
        for bad in ("training", "", None, ["reasoning"]):
            with self.subTest(bad):
                self.assertEqual(
                    analyze_feedback(_rec(target=bad))["status"],
                    "rejected_invalid")

    def test_rejects_bad_rating(self):
        for bad in ("applied", "", None, 5, ["correct"]):
            with self.subTest(bad):
                self.assertEqual(
                    analyze_feedback(_rec(rating=bad))["status"],
                    "rejected_invalid")

    def test_rejects_bad_source(self):
        for bad in ("bot", "", None, 5):
            with self.subTest(bad):
                self.assertEqual(
                    analyze_feedback(_rec(source=bad))["status"],
                    "rejected_invalid")

    def test_rejects_bad_ids(self):
        for bad in ("", "  ", None, 5):
            with self.subTest(bad):
                self.assertEqual(
                    analyze_feedback(_rec(id=bad))["status"],
                    "rejected_invalid")

    def test_rejects_bad_timestamps(self):
        for bad in ("2026-11-21T10:00:00", "2026-11-21", "yesterday", "",
                    None, 5, " 2026-11-21T10:00:00Z",
                    "2026-13-40T10:00:00Z", "2026-11-21 10:00:00+07:00"):
            with self.subTest(bad):
                self.assertEqual(
                    analyze_feedback(_rec(created_at=bad))["status"],
                    "rejected_invalid")

    def test_incorrect_requires_comment(self):
        res, txt = _bad(_rec(rating="incorrect", comment="  "))
        self.assertEqual(res["status"], "rejected_invalid")
        self.assertIn("comment", txt)
        self.assertEqual(
            analyze_feedback(
                _rec(rating="incorrect", comment="wrong answer"))["status"],
            "accepted_for_log")

    def test_comment_must_be_text(self):
        for bad in (None, 5):
            with self.subTest(bad):
                self.assertEqual(
                    analyze_feedback(_rec(comment=bad))["status"],
                    "rejected_invalid")

    def test_status_closed_and_weights_unchanged(self):
        for rec in (_rec(), _rec(rating="x"), None):
            r = analyze_feedback(rec)
            self.assertIn(r["status"], ALLOWED_FEEDBACK_STATUS)
            self.assertIs(r["model_weights_changed"], False)


if __name__ == "__main__":
    unittest.main()
