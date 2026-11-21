import pytest
from phase13 import check_governance, ingest_record, validate_record

def test_ingestion_creates_record_with_provenance():
    r = ingest_record("manual", "mit", "Maew", "นี่คือข้อความตัวอย่างที่ยาวพอ")
    assert r["source"] == "manual"
    assert r["license"] == "mit"
    assert r["attribution"] == "Maew"
    assert r["id"]
    assert r["created_at"]

def test_ingestion_requires_provenance():
    with pytest.raises(ValueError):
        ingest_record("", "mit", "Maew", "text")
    with pytest.raises(ValueError):
        ingest_record("manual", "", "Maew", "text")
    with pytest.raises(ValueError):
        ingest_record("manual", "mit", "", "text")

def test_governance_allows_approved_license():
    r = ingest_record("manual", "cc-by-4.0", "Maew", "ข้อความที่ยาวพอสำหรับเทส")
    s = check_governance(r)
    assert s["status"] == "allowed"

def test_governance_blocks_unknown_license():
    r = ingest_record("manual", "unknown-license", "Maew", "ข้อความที่ยาวพอสำหรับเทส")
    s = check_governance(r)
    assert s["status"] == "blocked"
    assert "reason" in s and s["reason"]

def test_validation_detects_empty_and_too_short():
    assert validate_record({"text": ""})["issues"] == ["empty_text"]
    assert "too_short" in validate_record({"text": "สั้น"})["issues"]
    assert validate_record({"text": "ข้อความนี้ยาวพอสำหรับผ่าน"})["valid"] is True

def test_validation_detects_duplicate_and_pii():
    seen = {"ข้อความนี้ยาวพอสำหรับเทส"}
    assert "duplicate" in validate_record({"text": "ข้อความนี้ยาวพอสำหรับเทส"}, seen)["issues"]
    assert "possible_pii" in validate_record({"text": "ติดต่อ me@example.com ได้เลยครับผม"})["issues"]
