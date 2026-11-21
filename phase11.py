"""Phase 11 — Workspace Intelligence — pure logic only.

No DB, no auth, no quota, no migration, no external AI, no training.
Uses only the context already inside the Workspace.
"""

FOLLOWUP_MAP = {
    "task_done": [
        {"title": "สรุปงานที่เพิ่งเสร็จ", "action": "summarize"},
        {"title": "สร้างงานถัดไป", "action": "create_next_task"},
        {"title": "ทบทวนงานที่เกี่ยวข้อง", "action": "review_related"},
    ],
    "file_opened": [
        {"title": "สรุปไฟล์ที่เปิดอยู่", "action": "summarize_file"},
        {"title": "ค้นหางานที่เกี่ยวกับไฟล์นี้", "action": "find_related_tasks"},
        {"title": "สร้างงานจากไฟล์นี้", "action": "create_task_from_file"},
    ],
    "message_sent": [
        {"title": "เสนอคำตอบถัดไป", "action": "suggest_reply"},
        {"title": "สร้างงานจากบทสนทนา", "action": "create_task_from_chat"},
        {"title": "บันทึกบริบทนี้", "action": "save_context"},
    ],
}

DEFAULT_SUGGESTIONS = [
    {"title": "ดูงานที่ค้างอยู่", "action": "list_open_tasks"},
    {"title": "ค้นหาใน Workspace", "action": "search_workspace"},
    {"title": "สรุปบริบทปัจจุบัน", "action": "summarize_context"},
]

def suggest_followups(last_action, context=None):
    """Follow-up Suggestions — return 3 suggestions, never auto-run."""
    suggestions = FOLLOWUP_MAP.get(last_action, DEFAULT_SUGGESTIONS)
    # Keep it to max 3, copy so caller cannot mutate the map
    return [dict(s) for s in suggestions[:3]]

class ConversationContext:
    """Conversation Context Awareness — per-user, per-session only."""

    def __init__(self, user_id):
        self.user_id = user_id
        self.messages = []
        self.current_task = None
        self.current_file = None

    def add_message(self, role, text):
        self.messages.append({"role": role, "text": text})
        return len(self.messages)

    def set_current_task(self, task):
        self.current_task = task

    def set_current_file(self, filename):
        self.current_file = filename

    def summary(self):
        return {
            "user_id": self.user_id,
            "current_task": self.current_task,
            "current_file": self.current_file,
            "message_count": len(self.messages),
            "last_message": self.messages[-1] if self.messages else None,
        }

def group_workspace_items(items):
    """Workspace Interaction — group by status, no schema change."""
    grouped = {"open": [], "done": [], "other": []}
    for item in items:
        status = item.get("status", "other")
        if status in ("open", "done"):
            grouped[status].append(item)
        else:
            grouped["other"].append(item)
    return grouped

def search_workspace(items, query):
    """Workspace Interaction — simple search inside Workspace only."""
    q = (query or "").strip().lower()
    if not q:
        return []
    out = []
    for item in items:
        title = str(item.get("title", "")).lower()
        if q in title:
            out.append(item)
    return out
