from phases.phase17 import MemoryStore

def test_tiered_memory_store_recall():
    m = MemoryStore()
    assert m.store("short", "task1", "ทำรายงานประจำสัปดาห์", "u1", "w1", source="manual", verified=True)["status"] == "ok"
    out = m.recall("short", "task1", "u1", "w1")
    assert out["status"] == "ok"
    assert out["result"] == "ทำรายงานประจำสัปดาห์"
    assert out["verified"] is True

def test_tiered_memory_invalid_tier_blocked():
    m = MemoryStore()
    out = m.store("magic", "k1", "v1", "u1", "w1", source="manual")
    assert out["status"] == "blocked"
    assert m.recall("magic", "k1", "u1", "w1")["status"] == "blocked"

def test_grounded_retrieval_requires_source():
    m = MemoryStore()
    m.store("long", "doc1", "ความรู้เรื่อง ZYRQUEN", "u1", "w1", source="docs", verified=True)
    # No source -> stored but not retrieved (store allows empty source, retrieve filters)
    m.store("long", "doc2", "ความรู้เรื่อง ZYRQUEN ลับ", "u1", "w1", source="", verified=False)
    out = m.retrieve("ZYRQUEN", "u1", "w1")
    assert len(out) == 1
    assert out[0]["source"] == "docs"

def test_grounded_retrieval_separates_verified():
    m = MemoryStore()
    m.store("long", "a", "ข้อมูลที่ตรวจสอบแล้ว", "u1", "w1", source="docs", verified=True)
    m.store("long", "b", "ข้อมูลที่ยังไม่ยืนยัน", "u1", "w1", source="chat", verified=False)
    out = m.retrieve("ข้อมูล", "u1", "w1")
    by_verified = {o["key"]: o["verified"] for o in out}
    assert by_verified["a"] is True
    assert by_verified["b"] is False

def test_multitenant_blocks_cross_user():
    m = MemoryStore()
    m.store("short", "secret", "ข้อมูลของ A", "u1", "w1", source="manual")
    out = m.recall("short", "secret", "u2", "w1")
    assert out["status"] == "blocked"
    assert out["result"] is None
    assert m.retrieve("ข้อมูล", "u2", "w1") == []

def test_multitenant_blocks_cross_workspace():
    m = MemoryStore()
    m.store("task", "t1", "งานของ workspace 1", "u1", "w1", source="manual")
    out = m.recall("task", "t1", "u1", "w2")
    assert out["status"] == "blocked"
    assert m.retrieve("งาน", "u1", "w2") == []
