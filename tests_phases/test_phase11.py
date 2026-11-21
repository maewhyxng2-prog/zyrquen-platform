from phases.phase11 import (
    ConversationContext,
    group_workspace_items,
    search_workspace,
    suggest_followups,
)

def test_followup_for_known_action():
    out = suggest_followups("task_done")
    assert len(out) == 3
    assert out[0]["action"] == "summarize"

def test_followup_for_unknown_action_uses_default():
    out = suggest_followups("something_new")
    assert len(out) == 3
    assert out[0]["action"] == "list_open_tasks"

def test_context_summary_keeps_current_task():
    ctx = ConversationContext(user_id="u1")
    ctx.set_current_task("ทำรายงาน")
    ctx.add_message("user", "ช่วยสรุปหน่อย")
    s = ctx.summary()
    assert s["current_task"] == "ทำรายงาน"
    assert s["message_count"] == 1
    assert s["last_message"]["text"] == "ช่วยสรุปหน่อย"

def test_context_does_not_leak_across_users():
    a = ConversationContext(user_id="u1")
    b = ConversationContext(user_id="u2")
    a.set_current_task("งานของ A")
    assert b.summary()["current_task"] is None

def test_group_workspace_items():
    items = [
        {"title": "A", "status": "open"},
        {"title": "B", "status": "done"},
        {"title": "C", "status": "archived"},
    ]
    g = group_workspace_items(items)
    assert len(g["open"]) == 1
    assert len(g["done"]) == 1
    assert len(g["other"]) == 1

def test_search_workspace():
    items = [{"title": "รายงานประจำสัปดาห์"}, {"title": "ซื้อของ"}]
    out = search_workspace(items, "รายงาน")
    assert len(out) == 1
    assert out[0]["title"] == "รายงานประจำสัปดาห์"
    assert search_workspace(items, "") == []
