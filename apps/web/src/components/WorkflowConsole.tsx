"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest, readSession } from "@/lib/api";
import { Icon } from "./Icon";
import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";

type WorkflowDefinitionItem = {
  workflow_key: string;
  version: string;
  group_name: string;
  title: string;
  description: string;
  default_tier: string;
  schedule_interval_sec: number | null;
  event_triggers: string[];
};

type WorkflowStepItem = {
  step_key: string;
  status: string;
  lane: string;
  evidence?: { verdict?: string; summary?: string } | null;
  error_code?: string | null;
};

type WorkflowRunItem = {
  id: string;
  workflow_key: string;
  workflow_version: string;
  trigger_type: string;
  status: string;
  error_message?: string | null;
  created_at: string;
  steps: WorkflowStepItem[];
};

type WorkflowApprovalItem = {
  id: string;
  run_id: string;
  step_key: string;
  action_type: string;
  scope: string;
  status: string;
  reason: string;
  expires_at: string;
};

type ModelVersionItem = {
  version: string;
  parent?: string | null;
  lifecycle_status?: string;
  created_at: string;
  evaluation_evidence?: {
    passed?: boolean;
    zero_regression?: boolean;
  } | null;
};

type ModelRegistryPayload = {
  configured: boolean;
  detail?: string;
  active_version: string | null;
  versions: ModelVersionItem[];
};

function statusToneFor(status: string): "good" | "warn" | "bad" | "info" | "neutral" {
  switch (status) {
    case "COMPLETED":
    case "PASS":
    case "production":
    case "verified":
    case "approved":
      return "good";
    case "WAITING_APPROVAL":
    case "WAITING_RESOURCE":
    case "NOT RUN":
    case "pending":
    case "staging":
      return "warn";
    case "FAILED":
    case "BLOCKED":
    case "quarantined":
    case "rejected":
      return "bad";
    case "RUNNING":
    case "VERIFYING":
    case "registered":
      return "info";
    default:
      return "neutral";
  }
}

export function WorkflowConsole() {
  const [authChecked, setAuthChecked] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [definitions, setDefinitions] = useState<WorkflowDefinitionItem[]>([]);
  const [runs, setRuns] = useState<WorkflowRunItem[]>([]);
  const [approvals, setApprovals] = useState<WorkflowApprovalItem[]>([]);
  const [registry, setRegistry] = useState<ModelRegistryPayload | null>(null);
  const [schedulerActive, setSchedulerActive] = useState(false);

  const fetchAndApply = useCallback(async (isCancelled?: () => boolean) => {
    setError("");
    try {
      const session = await readSession();
      if (isCancelled?.()) return;
      setAuthChecked(true);
      if (!session.authenticated) {
        setAuthenticated(false);
        setLoading(false);
        return;
      }
      setAuthenticated(true);

      const res = await Promise.allSettled([
        apiRequest<{ items: WorkflowDefinitionItem[]; scheduler_active: boolean }>(
          "v1/workflows/definitions",
        ),
        apiRequest<{ items: WorkflowRunItem[] }>("v1/workflows/runs?limit=20"),
        apiRequest<ModelRegistryPayload>("v1/models/registry"),
        apiRequest<{ items: WorkflowApprovalItem[] }>("v1/workflows/approvals?limit=25"),
      ]);
      if (isCancelled?.()) return;

      if (res[0].status === "fulfilled") {
        setDefinitions(res[0].value.items ?? []);
        setSchedulerActive(Boolean(res[0].value.scheduler_active));
      } else {
        setError(res[0].reason instanceof Error ? res[0].reason.message : "ไม่สามารถโหลด Workflow Engine ได้");
      }
      if (res[1].status === "fulfilled") {
        setRuns(res[1].value.items ?? []);
      }
      if (res[2].status === "fulfilled") {
        setRegistry(res[2].value);
      }
      if (res[3].status === "fulfilled") {
        setIsAdmin(true);
        setApprovals(res[3].value.items ?? []);
      } else {
        setIsAdmin(false);
        setApprovals([]);
      }
    } catch (err) {
      if (isCancelled?.()) return;
      setError(err instanceof Error ? err.message : "ไม่สามารถเชื่อมต่อ Central Workflow API ได้");
    } finally {
      if (!isCancelled?.()) {
        setLoading(false);
      }
    }
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    await fetchAndApply();
  }, [fetchAndApply]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await Promise.resolve();
      if (!cancelled) {
        await fetchAndApply(() => cancelled);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchAndApply]);

  async function triggerWorkflow(workflowKey: string) {
    setBusyKey(workflowKey);
    setError("");
    try {
      await apiRequest<WorkflowRunItem>("v1/workflows/runs", {
        method: "POST",
        body: JSON.stringify({ workflow_key: workflowKey, payload: {} }),
      });
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "สั่งรัน Workflow ไม่สำเร็จ");
    } finally {
      setBusyKey(null);
    }
  }

  async function decideApproval(approvalId: string, approve: boolean) {
    setBusyKey(approvalId);
    setError("");
    try {
      await apiRequest(`v1/workflows/approvals/${approvalId}/decision`, {
        method: "POST",
        body: JSON.stringify({
          approve,
          reason: approve ? "Approved via Training Console" : "Rejected via Training Console",
        }),
      });
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "บันทึกการตัดสินใจ Approval ไม่สำเร็จ");
    } finally {
      setBusyKey(null);
    }
  }

  if (authChecked && !authenticated) {
    return (
      <Panel className="workflow-panel">
        <div className="panel-heading">
          <div>
            <div className="eyebrow">
              <Icon name="command" size={14} />
              <span>CENTRAL WORKFLOW ENGINE & MODEL REGISTRY</span>
            </div>
            <h2>ระบบจัดการ Workflow กลางและเวอร์ชันโมเดล</h2>
          </div>
          <StatusBadge tone="neutral">ต้องลงชื่อเข้าใช้</StatusBadge>
        </div>
        <div className="unavailable-block">
          <strong>กรุณาเข้าสู่ระบบเพื่อเรียกดูสถานะ Workflow และ Model Registry จาก Backend</strong>
          <p>หน้านี้ไม่สร้างข้อมูลหรือสถานะจำลอง เมื่อลงชื่อเข้าใช้แล้วจะแสดงเฉพาะข้อมูลจริงจาก <code>/v1/workflows/*</code> และ <code>/v1/models/registry</code></p>
          <div style={{ marginTop: 12 }}>
            <Link className="button button-primary" href="/login">
              เข้าสู่ระบบ
            </Link>
          </div>
        </div>
      </Panel>
    );
  }

  const pendingApprovals = approvals.filter((a) => a.status === "pending");

  return (
    <div className="workflow-stack">
      <Panel className="workflow-panel">
        <div className="panel-heading">
          <div>
            <div className="eyebrow">
              <Icon name="command" size={14} />
              <span>CENTRAL NATIVE WORKFLOW ENGINE · 8 GROUPS</span>
            </div>
            <h2>ตัวจัดการ Workflow กลาง (Single Central Orchestrator)</h2>
          </div>
          <div className="workflow-actions">
            <StatusBadge tone={schedulerActive ? "good" : "neutral"}>
              {schedulerActive ? "Scheduler Active" : "Scheduler Manual / Idle"}
            </StatusBadge>
            <button
              className="button button-secondary"
              disabled={loading}
              onClick={() => void loadData()}
              type="button"
            >
              รีเฟรช
            </button>
          </div>
        </div>

        {error ? (
          <p className="form-alert form-alert-error" role="alert">
            {error}
          </p>
        ) : null}

        {loading && definitions.length === 0 ? (
          <div className="unavailable-block">
            <strong>กำลังโหลดรายการ Workflow จาก Backend...</strong>
          </div>
        ) : definitions.length === 0 ? (
          <div className="unavailable-block">
            <strong>ยังไม่ได้เชื่อมต่อ Backend API สำหรับ Workflow</strong>
            <p>ตรวจสอบการรัน FastAPI Backend และตัวแปร <code>ZYRQUEN_API_BASE_URL</code></p>
          </div>
        ) : (
          <div className="workflow-def-grid">
            {definitions.map((def) => (
              <div className="workflow-def-card" key={`${def.workflow_key}@${def.version}`}>
                <div className="workflow-def-head">
                  <span className="phase-label">{def.group_name}</span>
                  <StatusBadge tone={def.default_tier === "tier2_approval" ? "warn" : "info"}>
                    {def.default_tier === "tier2_approval" ? "Tier-2 Gated" : "Tier-1 Auto"}
                  </StatusBadge>
                </div>
                <strong>{def.title}</strong>
                <p>{def.description}</p>
                <div className="workflow-def-foot">
                  <code>{def.workflow_key}</code>
                  <button
                    className="button button-secondary"
                    disabled={busyKey === def.workflow_key}
                    onClick={() => void triggerWorkflow(def.workflow_key)}
                    type="button"
                  >
                    {busyKey === def.workflow_key ? "กำลังส่ง..." : "สั่งตรวจสอบ"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <div className="workflow-split-grid">
        <Panel className="workflow-panel">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">
                <Icon name="activity" size={14} />
                <span>EXECUTION HISTORY</span>
              </div>
              <h2>ประวัติการทำงาน Workflow ล่าสุด</h2>
            </div>
            <StatusBadge tone="neutral">{runs.length} รายการ</StatusBadge>
          </div>
          {runs.length === 0 ? (
            <div className="unavailable-block">
              <strong>ยังไม่มีประวัติการรัน Workflow</strong>
              <p>กดปุ่ม &quot;สั่งตรวจสอบ&quot; เพื่อสร้าง Run จริงพร้อม Audit Trail และ Verification Evidence</p>
            </div>
          ) : (
            <div className="workflow-run-list">
              {runs.slice(0, 8).map((run) => (
                <div className="workflow-run-row" key={run.id}>
                  <div className="workflow-run-main">
                    <strong>{run.workflow_key}</strong>
                    <small>
                      {run.trigger_type} · {run.steps.map((s) => `${s.step_key}:${s.evidence?.verdict ?? s.status}`).join(" → ")}
                    </small>
                    {run.error_message ? <small className="workflow-err-note">{run.error_message}</small> : null}
                  </div>
                  <StatusBadge tone={statusToneFor(run.status)}>{run.status}</StatusBadge>
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel className="workflow-panel">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">
                <Icon name="shield" size={14} />
                <span>MODEL REGISTRY & LIFECYCLE GATE</span>
              </div>
              <h2>คลังเวอร์ชันโมเดล (Native Registry)</h2>
            </div>
            <StatusBadge tone={registry?.configured ? "good" : "neutral"}>
              {registry?.active_version || (registry?.configured ? "ยังไม่ Active" : "ยังไม่ตั้งค่า Registry")}
            </StatusBadge>
          </div>
          {!registry?.configured ? (
            <div className="unavailable-block">
              <strong>{registry?.detail || "ยังไม่ได้กำหนด ZYRQUEN_MODEL_REGISTRY_ROOT บน Backend"}</strong>
              <p>ระบบจะไม่แสดงเวอร์ชันหรือผลประเมินจำลองจนกว่าจะเชื่อมต่อโฟลเดอร์ ModelRegistry จริง</p>
            </div>
          ) : registry.versions.length === 0 ? (
            <div className="unavailable-block">
              <strong>ยังไม่มีเวอร์ชันโมเดลที่ลงทะเบียนไว้</strong>
              <p>เวอร์ชันใหม่จะปรากฏที่นี่หลังผ่าน Data Gate, Training และ Registration</p>
            </div>
          ) : (
            <div className="workflow-run-list">
              {registry.versions.map((ver) => (
                <div className="workflow-run-row" key={ver.version}>
                  <div className="workflow-run-main">
                    <strong>{ver.version}</strong>
                    <small>
                      Parent: {ver.parent || "baseline"} · Eval:{" "}
                      {ver.evaluation_evidence ? (ver.evaluation_evidence.passed ? "PASS" : "FAIL") : "NOT RUN"}
                    </small>
                  </div>
                  <StatusBadge tone={statusToneFor(ver.lifecycle_status || "registered")}>
                    {ver.lifecycle_status || "registered"}
                  </StatusBadge>
                </div>
              ))}
            </div>
          )}

          {isAdmin ? (
            <div className="workflow-approval-box">
              <div className="eyebrow" style={{ marginBottom: 8 }}>
                <Icon name="lock" size={13} />
                <span>TIER-2 HUMAN APPROVAL QUEUE ({pendingApprovals.length})</span>
              </div>
              {pendingApprovals.length === 0 ? (
                <p className="workflow-muted">ไม่มีคำขอ Tier-2 ที่รออนุมัติในขณะนี้</p>
              ) : (
                <div className="workflow-run-list">
                  {pendingApprovals.map((app) => (
                    <div className="workflow-run-row" key={app.id}>
                      <div className="workflow-run-main">
                        <strong>{app.action_type}</strong>
                        <small>{app.scope}</small>
                      </div>
                      <div className="workflow-actions">
                        <button
                          className="button button-primary"
                          disabled={busyKey === app.id}
                          onClick={() => void decideApproval(app.id, true)}
                          type="button"
                        >
                          อนุมัติ
                        </button>
                        <button
                          className="button button-danger"
                          disabled={busyKey === app.id}
                          onClick={() => void decideApproval(app.id, false)}
                          type="button"
                        >
                          ปฏิเสธ
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : null}
        </Panel>
      </div>
    </div>
  );
}
