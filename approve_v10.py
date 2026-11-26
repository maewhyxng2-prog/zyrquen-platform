from pathlib import Path
from apps.core.workflow import CentralWorkflowOrchestrator

WORKFLOW_RUN_ID = "57b249f4-1f69-4976-85e1-b436161a4a2b"
SECRET_KEY = "development-secret-key-at-least-32-chars-long"

def main():
    print(f"⏳ กำลังขออนุมัติ Workflow: {WORKFLOW_RUN_ID}")
    orch = CentralWorkflowOrchestrator(
        db_path=Path("./workflow.db"),
        work_dir=Path("./"),
        approval_secret=SECRET_KEY
    )

    # ใช้ list_approvals ตามที่ grep เจอ
    all_pending = orch.store.list_approvals(status="pending")
    pending = [a for a in all_pending if a.get("run_id") == WORKFLOW_RUN_ID]

    if not pending:
        print("⚠️ ไม่มี Approval ที่รออนุมัติ (อาจจะอนุมัติไปแล้ว หรือ ID ไม่ตรง)")
        return

    for app in pending:
        print(f"📝 กำลังอนุมัติ Approval ID: {app['id']}")
        orch.governance.decide_approval(
            app['id'],
            approve=True,
            approver_user_id="admin-1",
            approver_role="admin"
        )
        print("✅ อนุมัติสำเร็จ!")

if __name__ == "__main__":
    main()
