import copy
import unittest

from apps.core.intelligence.feedback_log import FeedbackLog
from apps.core.intelligence.feedback_summary import (
    ALLOWED_EVIDENCE_LEVELS, MIN_SAMPLE_PER_GROUP, summarize)


def _rec(tag, i, target="reasoning", rating="correct", source="user"):
    return {
        "id": "%s-%s" % (tag, i), "target": target, "rating": rating,
        "comment": "x" if rating == "incorrect" else "",
        "source": source, "created_at": "2026-11-21T10:00:00Z",
    }


def _many(tag, n, **kw):
    return [_rec(tag, i, **kw) for i in range(n)]


def _all_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _all_keys(v)


def _groups(s):
    return ([s["overall"]] + list(s["by_target"].values())
            + list(s["by_source"].values()))


class TestFeedbackSummary(unittest.TestCase):
    def test_empty_is_no_data(self):
        s = summarize([])
        self.assertEqual(s["overall"]["total"], 0)
        for g in _groups(s):
            self.assertEqual(g["evidence_level"], "no_data")
            self.assertIsNone(g["proportions"])
            self.assertEqual(
                g["counts"],
                {"correct": 0, "incorrect": 0, "partially_correct": 0})
        self.assertEqual(s["skipped_invalid"], 0)
        self.assertEqual(s["skipped_duplicate"], 0)

    def test_counts_by_rating_target_source(self):
        recs = [
            _rec("a", 0, "reasoning", "correct", "user"),
            _rec("a", 1, "reasoning", "incorrect", "evaluator"),
            _rec("a", 2, "planning", "partially_correct", "automated_test"),
            _rec("a", 3, "planning", "correct", "user"),
        ]
        s = summarize(recs)
        self.assertEqual(s["overall"]["total"], 4)
        self.assertEqual(s["overall"]["counts"], {
            "correct": 2, "incorrect": 1, "partially_correct": 1})
        self.assertEqual(s["by_target"]["reasoning"]["counts"], {
            "correct": 1, "incorrect": 1, "partially_correct": 0})
        self.assertEqual(s["by_target"]["planning"]["counts"], {
            "correct": 1, "incorrect": 0, "partially_correct": 1})
        self.assertEqual(s["by_source"]["user"]["counts"], {
            "correct": 2, "incorrect": 0, "partially_correct": 0})
        self.assertEqual(s["by_source"]["evaluator"]["counts"], {
            "correct": 0, "incorrect": 1, "partially_correct": 0})
        self.assertEqual(s["by_source"]["automated_test"]["counts"], {
            "correct": 0, "incorrect": 0, "partially_correct": 1})

    def test_29_is_insufficient_and_has_no_proportions(self):
        self.assertEqual(MIN_SAMPLE_PER_GROUP, 30)
        s = summarize(_many("a", 29))
        g = s["by_target"]["reasoning"]
        self.assertEqual(g["total"], 29)
        self.assertEqual(g["evidence_level"], "insufficient_sample")
        self.assertIsNone(g["proportions"])
        self.assertEqual(g["counts"]["correct"], 29)

    def test_30_is_sufficient_with_proportions(self):
        recs = (_many("a", 20, rating="correct")
                + _many("b", 5, rating="incorrect")
                + _many("c", 5, rating="partially_correct"))
        g = summarize(recs)["by_target"]["reasoning"]
        self.assertEqual(g["total"], 30)
        self.assertEqual(g["evidence_level"], "sufficient_sample")
        self.assertAlmostEqual(g["proportions"]["correct"], 20 / 30)
        self.assertAlmostEqual(g["proportions"]["incorrect"], 5 / 30)
        self.assertAlmostEqual(g["proportions"]["partially_correct"], 5 / 30)
        self.assertAlmostEqual(sum(g["proportions"].values()), 1.0)

    def test_threshold_applies_per_target_group(self):
        recs = _many("r", 30, target="reasoning") + _many(
            "p", 5, target="planning")
        s = summarize(recs)
        self.assertEqual(
            s["by_target"]["reasoning"]["evidence_level"], "sufficient_sample")
        self.assertEqual(
            s["by_target"]["planning"]["evidence_level"], "insufficient_sample")
        self.assertIsNone(s["by_target"]["planning"]["proportions"])
        self.assertEqual(s["overall"]["total"], 35)
        self.assertEqual(
            s["overall"]["evidence_level"], "sufficient_sample")
        self.assertEqual(s["by_source"]["evaluator"]["evidence_level"], "no_data")

    def test_threshold_applies_per_source_group(self):
        recs = [_rec("m", i, source="user" if i % 2 == 0 else "evaluator")
                for i in range(30)]
        s = summarize(recs)
        self.assertEqual(
            s["by_target"]["reasoning"]["evidence_level"], "sufficient_sample")
        for src in ("user", "evaluator"):
            g = s["by_source"][src]
            self.assertEqual(g["total"], 15)
            self.assertEqual(g["evidence_level"], "insufficient_sample")
            self.assertIsNone(g["proportions"])

    def test_invalid_records_skipped_and_counted(self):
        recs = [_rec("a", 0), _rec("a", 1, rating="applied"), None]
        s = summarize(recs)
        self.assertEqual(s["overall"]["total"], 1)
        self.assertEqual(s["skipped_invalid"], 2)

    def test_duplicate_ids_counted_once(self):
        r = _rec("a", 0)
        s = summarize([r, copy.deepcopy(r)])
        self.assertEqual(s["overall"]["total"], 1)
        self.assertEqual(s["skipped_duplicate"], 1)
        self.assertEqual(s["skipped_invalid"], 0)

    def test_read_only_on_input_and_log(self):
        recs = _many("a", 3)
        before = copy.deepcopy(recs)
        summarize(recs)
        self.assertEqual(recs, before)
        log = FeedbackLog()
        for r in _many("l", 3):
            log.submit(r)
        snapshot = log.records()
        s = summarize(log.records())
        self.assertEqual(log.records(), snapshot)
        self.assertEqual(len(log), 3)
        self.assertEqual(s["overall"]["total"], 3)

    def test_rejects_non_sequence_input(self):
        for bad in (None, "x", 5, {}, {"a": 1}):
            with self.subTest(bad):
                with self.assertRaises(TypeError):
                    summarize(bad)

    def test_output_makes_no_accuracy_or_improvement_claims(self):
        s = summarize(_many("a", 30))
        keys = set(_all_keys(s))
        for word in ("accuracy", "improved", "improvement", "applied",
                     "learned"):
            self.assertNotIn(word, keys)
        self.assertIs(s["model_weights_changed"], False)
        self.assertIn("not statistical evidence", s["evidence_note"])
        for g in _groups(s):
            self.assertIn(g["evidence_level"], ALLOWED_EVIDENCE_LEVELS)

    def test_proportions_only_when_sufficient(self):
        recs = _many("r", 30, target="reasoning") + _many(
            "p", 7, target="planning", rating="incorrect", source="evaluator")
        for g in _groups(summarize(recs)):
            if g["evidence_level"] == "sufficient_sample":
                self.assertIsNotNone(g["proportions"])
            else:
                self.assertIsNone(g["proportions"])


if __name__ == "__main__":
    unittest.main()
