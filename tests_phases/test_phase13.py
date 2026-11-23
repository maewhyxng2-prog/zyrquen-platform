import unittest
from phases.phase13 import check_governance, ingest_record, validate_record


class TestPhase13(unittest.TestCase):
    def test_ingestion_creates_record_with_provenance(self):
        r = ingest_record("manual", "mit", "Maew", "นี่คือข้อความตัวอย่างที่ยาวพอ")
        self.assertEqual(r["source"], "manual")
        self.assertEqual(r["license"], "mit")
        self.assertEqual(r["attribution"], "Maew")
        self.assertTrue(r["id"])
        self.assertTrue(r["created_at"])

    def test_ingestion_requires_provenance(self):
        with self.assertRaises(ValueError):
            ingest_record("", "mit", "Maew", "text")
        with self.assertRaises(ValueError):
            ingest_record("manual", "", "Maew", "text")
        with self.assertRaises(ValueError):
            ingest_record("manual", "mit", "", "text")

    def test_governance_allows_approved_license(self):
        r = ingest_record("manual", "cc-by-4.0", "Maew", "ข้อความที่ยาวพอสำหรับเทส")
        s = check_governance(r)
        self.assertEqual(s["status"], "allowed")

    def test_governance_blocks_unknown_license(self):
        r = ingest_record("manual", "unknown-license", "Maew", "ข้อความที่ยาวพอสำหรับเทส")
        s = check_governance(r)
        self.assertEqual(s["status"], "blocked")
        self.assertTrue("reason" in s and s["reason"])

    def test_validation_detects_empty_and_too_short(self):
        self.assertEqual(validate_record({"text": ""})["issues"], ["empty_text"])
        self.assertIn("too_short", validate_record({"text": "สั้น"})["issues"])
        self.assertIs(validate_record({"text": "ข้อความนี้ยาวพอสำหรับผ่าน"})["valid"], True)

    def test_validation_detects_duplicate_and_pii(self):
        seen = {"ข้อความนี้ยาวพอสำหรับเทส"}
        self.assertIn("duplicate", validate_record({"text": "ข้อความนี้ยาวพอสำหรับเทส"}, seen)["issues"])
        self.assertIn("possible_pii", validate_record({"text": "ติดต่อ me@example.com ได้เลยครับผม"})["issues"])


if __name__ == "__main__":
    unittest.main()
