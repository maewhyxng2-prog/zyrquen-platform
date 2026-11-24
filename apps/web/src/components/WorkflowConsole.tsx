"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiRequest, readSession } from "@/lib/api";
import type { WorkflowServicesStatus } from "@/lib/types";
import {
  computeRunProgress,
  formatDuration,
  formatLoss,
  isWorkflowRunActive,
  selectLatestCompletedKpi,
  type WorkflowRunItem,
} from "@/lib/workflow-metrics";
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

type CompatibilityResult = {
  version: string;
  compatible: boolean;
  checks: {
    artifacts_sha256: boolean;
    tokenizer_sha256: boolean;
    architecture_config: boolean;
  };
  reasons: string[];
};

type ModelVersionItem = {
  version: string;
  parent?: string | null;
  lifecycle_status?: string;
  created_at: string;
  frozen?: boolean;
  checkpoint?: { step?: number; sha256?: string } | null;
  dataset?: { version?: string; content_sha256?: string } | null;
  evaluation_evidence?: {
    passed?: boolean;
    zero_regression?: boolean;
    report_sha256?: string;
  } | null;
  compatibility?: CompatibilityResult | null;
};

type ModelRegistryPayload = {
  configured: boolean;
  detail?: string;
  active_version: string | null;
  registered_count?: number;
  baseline_policy?: Record<string, { status: string; note: string }>;
  versions: ModelVersionItem[];
};

type VersionComparisonPayload = {
  base_version: string;
  candidate_version: string;
  base_lifecycle: string;
  candidate_lifecycle: string;
  metric_deltas: Record<string, { base: number; candidate: number; delta: number }>;
  capability_deltas: Record<string, { base: number; candidate: number; delta: number }>;
  regressed_metrics: string[];
  regressed_capabilities: string[];
  zero_regression: boolean;
};

type LineagePayload = {
  record: ModelVersionItem;
  lineage: {
    version: string;
    depth: number;
    ancestors: Array<{
      version: string;
      parent?: string | null;
      lifecycle_status: string;
      dataset_version?: string | null;
      checkpoint_sha256?: string | null;
      eval_report_sha256?: string | null;
      eval_passed?: boolean | null;
    }>;
  };
  compatibility: CompatibilityResult;
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
    case "evaluated":
      return "warn";
    case "FAILED":
    case "BLOCKED":
    case "quarantined":
    case "blocked":
    case "failed":
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
  const [notice, setNotice] = useState("");
  const [definitions, setDefinitions] = useState<WorkflowDefinitionItem[]>([]);
  const [runs, setRuns] = useState<WorkflowRunItem[]>([]);
  const [approvals, setApprovals] = useState<WorkflowApprovalItem[]>([]);
  const [registry, setRegistry] = useState<ModelRegistryPayload | null>(null);
  const [schedulerActive, setSchedulerActive] = useState(false);
  const [serviceStatus, setServiceStatus] = useState<WorkflowServicesStatus | null>(null);

  const [baseVersion, setBaseVersion] = useState("");
  const [candidateVersion, setCandidateVersion] = useState("");
  const [comparison, setComparison] = useState<VersionComparisonPayload | null>(null);
  const [selectedLineage, setSelectedLineage] = useState<LineagePayload | null>(null);
  const [approvalTokenInput, setApprovalTokenInput] = useState("");

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
        apiRequest<WorkflowServicesStatus>("v1/workflows/services/status"),
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
        const regData = res[2].value;
        setRegistry(regData);
        if (regData.versions.length >= 2) {
          setBaseVersion((prev) => prev || regData.versions[0].version);
          setCandidateVersion((prev) => prev || regData.versions[regData.versions.length - 1].version);
        }
      }
      if (res[3].status === "fulfilled") {
        setIsAdmin(true);
        setApprovals(res[3].value.items ?? []);
      } else {
        setIsAdmin(false);
        setApprovals([]);
      }
      if (res[4].status === "fulfilled") {
        setServiceStatus(res[4].value);
        setSchedulerActive(Boolean(res[4].value.scheduler?.running));
      } else {
        setServiceStatus(null);
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

  const refreshSilently = useCallback(async () => {
    try {
      const res = await Promise.allSettled([
        apiRequest<{ items: WorkflowRunItem[] }>("v1/workflows/runs?limit=20"),
        apiRequest<{ items: WorkflowApprovalItem[] }>("v1/workflows/approvals?limit=25"),
      ]);
      if (res[0].status === "fulfilled") {
        setRuns(res[0].value.items ?? []);
      }
      if (res[1].status === "fulfilled") {
        setApprovals(res[1].value.items ?? []);
      }
    } catch {
      // Keep existing state on transient background poll failure
    }
  }, []);

  const hasActiveRuns = runs.some((r) => isWorkflowRunActive(r.status));

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

  useEffect(() => {
    if (!authenticated || !hasActiveRuns) return;
    const timer = window.setInterval(() => {
      void refreshSilently();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [authenticated, hasActiveRuns, refreshSilently]);

  async function triggerWorkflow(workflowKey: string) {
    setBusyKey(workflowKey);
    setError("");
    setNotice("");
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
    setNotice("");
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

  async function compareVersions() {
    if (!baseVersion || !candidateVersion) return;
    setBusyKey("compare");
    setError("");
    try {
      const qs = new URLSearchParams({ base: baseVersion, candidate: candidateVersion });
      const data = await apiRequest<VersionComparisonPayload>(`v1/models/registry/compare?${qs.toString()}`);
      setComparison(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "เปรียบเทียบเวอร์ชันไม่สำเร็จ");
    } finally {
      setBusyKey(null);
    }
  }

  async function inspectLineage(version: string) {
    setBusyKey(`lineage:${version}`);
    setError("");
    try {
      const data = await apiRequest<LineagePayload>(`v1/models/registry/${encodeURIComponent(version)}/lineage`);
      setSelectedLineage(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ไม่สามารถดึง Lineage ของเวอร์ชันนี้ได้");
    } finally {
      setBusyKey(null);
    }
  }

  async function runModelLifecycleAction(action: "stage" | "promote" | "rollback", version?: string) {
    const approvalId = approvalTokenInput.trim();
    if (!approvalId) {
      setError("กรุณาระบุ Approval ID (Tier-2) ก่อนดำเนินการเปลี่ยนสถานะหรือย้อนกลับเวอร์ชันโมเดล");
      return;
    }
    setBusyKey(`${action}:${version || "rollback"}`);
    setError("");
    setNotice("");
    try {
      if (action === "rollback") {
        await apiRequest("v1/models/registry/rollback", {
          method: "POST",
          body: JSON.stringify({ to_version: version || null, approval_id: approvalId }),
        });
        setNotice("ย้อนกลับเวอร์ชัน Production สำเร็จ");
      } else if (version) {
        await apiRequest(`v1/models/registry/${encodeURIComponent(version)}/${action}`, {
          method: "POST",
          body: JSON.stringify({ approval_id: approvalId }),
        });
        setNotice(action === "stage" ? `นำ ${version} เข้าสู่ Staging สำเร็จ` : `โปรโมต ${version} เป็น Production สำเร็จ`);
      }
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "ไม่สามารถเปลี่ยนสถานะเวอร์ชันโมเดลได้");
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
          <div className="unavailable-actions">
            <Link className="button button-primary" href="/login">
              เข้าสู่ระบบ
            </Link>
          </div>
        </div>
      </Panel>
    );
  }

  const pendingApprovals = approvals.filter((a) => a.status === "pending");
  const versions = registry?.versions ?? [];
  const activeRuns = runs.filter((r) => isWorkflowRunActive(r.status));
  const latestKpi = selectLatestCompletedKpi(runs);

  return (
    <div className="workflow-stack">
      <Panel className="workflow-panel" aria-label="สรุปผลลัพธ์งานล่าสุดที่เสร็จสิ้น">
        <div className="panel-heading">
          <div>
            <div className="eyebrow">
              <Icon name="activity" size={14} />
              <span>LATEST COMPLETED RUN · KPI SUMMARY</span>
            </div>
            <h2>สรุปผลลัพธ์งานล่าสุดที่เสร็จสิ้น</h2>
          </div>
          {latestKpi ? (
            <StatusBadge tone="good">
              {latestKpi.latestRun.workflow_key} · COMPLETED
            </StatusBadge>
          ) : (
            <StatusBadge tone="neutral">
              {loading ? "กำลังโหลดข้อมูล" : "ยังไม่มีงานที่เสร็จสิ้น"}
            </StatusBadge>
          )}
        </div>

        {loading && runs.length === 0 ? (
          <div className="unavailable-block">
            <strong>กำลังโหลดสรุปผลลัพธ์ล่าสุดจาก Backend...</strong>
          </div>
        ) : !latestKpi ? (
          <div className="unavailable-block">
            <strong>ยังไม่มีงาน Workflow หรือการฝึกอบรมที่เสร็จสิ้น</strong>
            <p>
              เมื่อมีงานสถานะ <code>COMPLETED</code> ระบบจะแสดง Epoch/Steps, เวลาที่ใช้ และค่า Loss ล่าสุดที่นี่โดยอัตโนมัติ
            </p>
          </div>
        ) : (
          <div className="workflow-summary-grid">
            <div className="workflow-summary-cell">
              <span className="metric-label">EPOCH / STEPS ที่ใช้</span>
              <strong className="workflow-summary-value tabular-nums">
                {latestKpi.latestMetrics.epochs !== null
                  ? `${latestKpi.latestMetrics.epochs} Epochs`
                  : latestKpi.latestMetrics.steps !== null
                    ? `${latestKpi.latestMetrics.steps} Steps`
                    : "—"}
              </strong>
              <span className="workflow-summary-note">
                {latestKpi.latestMetrics.epochs !== null
                  ? latestKpi.latestMetrics.steps !== null
                    ? `รวม ${latestKpi.latestMetrics.steps} steps`
                    : "รายงานจากงานล่าสุด"
                  : latestKpi.latestMetrics.steps !== null
                    ? "Epoch: — (Native trainer รายงานเป็น steps)"
                    : "ไม่มีรายงาน Epoch / Steps ในงานล่าสุด"}
              </span>
            </div>

            <div className="workflow-summary-cell">
              <span className="metric-label">เวลาที่ใช้ (DURATION)</span>
              <strong className="workflow-summary-value tabular-nums">
                {formatDuration(latestKpi.durationMs)}
              </strong>
              <span className="workflow-summary-note tabular-nums">
                {latestKpi.durationDeltaMs !== null
                  ? `เทียบกับรอบก่อน: ${latestKpi.durationDeltaMs <= 0 ? "-" : "+"}${formatDuration(Math.abs(latestKpi.durationDeltaMs))}`
                  : latestKpi.latestRun.finished_at
                    ? `เสร็จสิ้น ${new Date(latestKpi.latestRun.finished_at).toLocaleTimeString("th-TH")}`
                    : "ไม่มีข้อมูลเวลาเริ่ม/สิ้นสุด"}
              </span>
            </div>

            <div className="workflow-summary-cell">
              <span className="metric-label">ค่า LOSS ล่าสุด</span>
              <strong className="workflow-summary-value tabular-nums">
                {formatLoss(latestKpi.latestMetrics.latestLoss)}
              </strong>
              <span
                className={`workflow-summary-note tabular-nums${
                  latestKpi.lossDelta !== null
                    ? latestKpi.lossDelta <= 0
                      ? " workflow-delta-good"
                      : " workflow-delta-warn"
                    : ""
                }`}
              >
                {latestKpi.latestMetrics.latestLoss !== null
                  ? [
                      latestKpi.latestMetrics.latestLossKind === "val_loss"
                        ? "Val Loss"
                        : latestKpi.latestMetrics.latestLossKind === "train_loss"
                          ? "Train Loss"
                          : "Loss",
                      latestKpi.latestMetrics.perplexity !== null
                        ? `PPL ${latestKpi.latestMetrics.perplexity.toFixed(2)}`
                        : null,
                      latestKpi.lossDelta !== null
                        ? `${latestKpi.lossDelta <= 0 ? "" : "+"}${latestKpi.lossDelta.toFixed(4)} vs รอบก่อน`
                        : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")
                  : "งานล่าสุดไม่ได้รายงานค่า Loss"}
              </span>
            </div>

            <div className="workflow-summary-cell">
              <span className="metric-label">ขอบเขตและการเปรียบเทียบ</span>
              <strong className="workflow-summary-value tabular-nums">
                {latestKpi.completedSteps}/{latestKpi.totalSteps} Steps ผ่าน
              </strong>
              <span className="workflow-summary-note tabular-nums">
                {[
                  `v${latestKpi.latestRun.workflow_version}`,
                  latestKpi.latestMetrics.ramPeakGb !== null
                    ? `RAM Peak ${latestKpi.latestMetrics.ramPeakGb} GB`
                    : null,
                  latestKpi.previousRun
                    ? "มีรอบก่อนหน้าเทียบผล"
                    : "ยังไม่มีรอบก่อนหน้า",
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </div>
          </div>
        )}
      </Panel>

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
            <StatusBadge
              tone={
                serviceStatus?.scheduler.safely_disabled
                  ? "info"
                  : schedulerActive
                    ? "good"
                    : "neutral"
              }
            >
              {serviceStatus?.scheduler.safely_disabled
                ? "Scheduler Safely Disabled"
                : schedulerActive
                  ? "Scheduler Active"
                  : "Scheduler Manual / Idle"}
            </StatusBadge>
            {serviceStatus ? (
              <StatusBadge
                tone={
                  serviceStatus.recovery.safely_disabled
                    ? "info"
                    : serviceStatus.recovery.enabled
                      ? "good"
                      : "neutral"
                }
              >
                {serviceStatus.recovery.safely_disabled
                  ? "Recovery Safely Disabled"
                  : "Recovery Enabled"}
              </StatusBadge>
            ) : null}
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
        {notice ? (
          <p className="form-alert form-alert-success" role="status">
            {notice}
          </p>
        ) : null}

        <div className="workflow-progress-section" aria-label="แถบความคืบหน้างานที่กำลังประมวลผล">
          <div className="workflow-progress-section-head">
            <span className="metric-label">ความคืบหน้าของงานที่กำลังประมวลผล (ACTIVE PROGRESS)</span>
            <span className="workflow-progress-count tabular-nums">
              {activeRuns.length > 0
                ? `${activeRuns.length} งานกำลังดำเนินการ`
                : "0 งานที่กำลังประมวลผล"}
            </span>
          </div>

          {activeRuns.length === 0 ? (
            <div className="workflow-progress-card">
              <div className="workflow-progress-row-head">
                <span className="workflow-progress-title">ไม่มีงานที่กำลังประมวลผลในขณะนี้</span>
                <span className="workflow-progress-pct tabular-nums">0%</span>
              </div>
              <div
                aria-label="ความคืบหน้างาน Workflow (ไม่มีงานกำลังประมวลผล)"
                aria-valuemax={100}
                aria-valuemin={0}
                aria-valuenow={0}
                className="progress-track"
                role="progressbar"
              >
                <div className="progress-fill" style={{ width: "0%" }} />
              </div>
              <span className="workflow-progress-meta">
                ระบบพร้อมรับคำสั่ง Workflow หรือตรวจสอบสถานะจากแผงด้านล่าง
              </span>
            </div>
          ) : (
            <div className="workflow-progress-list">
              {activeRuns.map((run) => {
                const progress = computeRunProgress(run);
                const fillClass =
                  progress.tone === "warn"
                    ? "progress-fill progress-fill-warn"
                    : progress.tone === "neutral"
                      ? "progress-fill progress-fill-muted"
                      : "progress-fill";
                return (
                  <div className="workflow-progress-card" key={`active-${run.id}`}>
                    <div className="workflow-progress-row-head">
                      <div className="workflow-progress-identity">
                        <strong>{run.workflow_key}</strong>
                        <span className="workflow-progress-meta tabular-nums">
                          {progress.completedSteps}/{progress.totalSteps} steps
                          {progress.activeStepKey ? ` · ${progress.activeStepKey}` : ""}
                        </span>
                      </div>
                      <div className="workflow-progress-status">
                        <span className="workflow-progress-pct tabular-nums">{progress.percent}%</span>
                        <StatusBadge tone={statusToneFor(run.status)}>{run.status}</StatusBadge>
                      </div>
                    </div>
                    <div
                      aria-label={`ความคืบหน้า ${run.workflow_key}`}
                      aria-valuemax={100}
                      aria-valuemin={0}
                      aria-valuenow={progress.percent}
                      className="progress-track"
                      role="progressbar"
                    >
                      <div className={fillClass} style={{ width: `${progress.percent}%` }} />
                    </div>
                    {run.error_message ? (
                      <span className="workflow-progress-meta workflow-err-note">{run.error_message}</span>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </div>

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

      <Panel className="workflow-panel">
        <div className="panel-heading">
          <div>
            <div className="eyebrow">
              <Icon name="shield" size={14} />
              <span>NATIVE MODEL REGISTRY & LIFECYCLE MANAGEMENT</span>
            </div>
            <h2>การจัดการเวอร์ชันโมเดล (Model Registry & Evaluation Gate)</h2>
          </div>
          <div className="workflow-kpi-strip">
            <div className="workflow-kpi-item">
              <span>Registered Models</span>
              <strong className="tabular-nums">
                {registry?.configured ? (registry.registered_count ?? versions.length) : "—"}
              </strong>
            </div>
            <div className="workflow-kpi-item">
              <span>Production Version</span>
              <strong className="tabular-nums">{registry?.active_version || "—"}</strong>
            </div>
          </div>
        </div>

        <div className="workflow-policy-row">
          <span>
            <strong>v7</strong> · Baseline (คงไว้ตรวจสอบ)
          </span>
          <span aria-hidden="true">/</span>
          <span>
            <strong>v8</strong> · CLOSED / FROZEN (ห้ามแก้ไขหรือฝึกซ้ำ)
          </span>
          <span aria-hidden="true">/</span>
          <span>
            <strong>v9</strong> · Development (ทดลองแยกจาก Baseline)
          </span>
        </div>

        {!registry?.configured ? (
          <div className="unavailable-block">
            <strong>{registry?.detail || "ยังไม่ได้กำหนด ZYRQUEN_MODEL_REGISTRY_ROOT บน Backend"}</strong>
            <p>ระบบจะไม่แสดงเวอร์ชันหรือผลประเมินจำลอง จนกว่าจะเชื่อมต่อโฟลเดอร์ ModelRegistry จริง</p>
          </div>
        ) : versions.length === 0 ? (
          <div className="unavailable-block">
            <strong>ยังไม่มีเวอร์ชันโมเดลที่ลงทะเบียนไว้ใน Registry</strong>
            <p>เวอร์ชันใหม่จะปรากฏที่นี่หลังผ่าน Data Gate, Training และ Registration</p>
          </div>
        ) : (
          <>
            {isAdmin ? (
              <div className="workflow-admin-toolbar">
                <label className="workflow-inline-field">
                  <span>Tier-2 Approval ID</span>
                  <input
                    className="input"
                    onChange={(e) => setApprovalTokenInput(e.target.value)}
                    placeholder="ระบุ Approval ID ก่อน Stage / Promote / Rollback"
                    type="text"
                    value={approvalTokenInput}
                  />
                </label>
                <button
                  className="button button-secondary"
                  disabled={busyKey === "rollback:rollback"}
                  onClick={() => void runModelLifecycleAction("rollback")}
                  type="button"
                >
                  Rollback Production
                </button>
              </div>
            ) : null}

            <div className="workflow-table-wrap">
              <table className="workflow-table">
                <thead>
                  <tr>
                    <th>Version</th>
                    <th>Status</th>
                    <th>Parent</th>
                    <th>Evaluation</th>
                    <th>Compatibility</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {versions.map((ver) => {
                    const evalText = ver.evaluation_evidence
                      ? `${ver.evaluation_evidence.passed ? "PASS" : "FAIL"}${ver.evaluation_evidence.zero_regression ? "" : " (Regression)"}`
                      : "NOT RUN";
                    const compatOk = ver.compatibility ? ver.compatibility.compatible : null;
                    const lifecycle = ver.lifecycle_status || "registered";
                    return (
                      <tr key={ver.version}>
                        <td className="tabular-nums">
                          <strong>{ver.version}</strong>
                          <div className="workflow-table-sub">
                            {ver.dataset?.version || "—"} · step {ver.checkpoint?.step ?? "—"}
                          </div>
                        </td>
                        <td>
                          <StatusBadge tone={statusToneFor(lifecycle)}>{lifecycle}</StatusBadge>
                        </td>
                        <td className="tabular-nums">{ver.parent || "baseline"}</td>
                        <td>
                          <StatusBadge
                            tone={
                              ver.evaluation_evidence
                                ? ver.evaluation_evidence.passed
                                  ? "good"
                                  : "bad"
                                : "warn"
                            }
                          >
                            {evalText}
                          </StatusBadge>
                        </td>
                        <td>
                          {compatOk === null ? (
                            "NOT CHECKED"
                          ) : (
                            <StatusBadge tone={compatOk ? "good" : "bad"}>
                              {compatOk ? "Compatible" : "Mismatch"}
                            </StatusBadge>
                          )}
                        </td>
                        <td>
                          <div className="workflow-actions">
                            <button
                              className="button button-secondary"
                              disabled={busyKey === `lineage:${ver.version}`}
                              onClick={() => void inspectLineage(ver.version)}
                              type="button"
                            >
                              Lineage
                            </button>
                            {isAdmin && lifecycle === "verified" ? (
                              <button
                                className="button button-secondary"
                                disabled={busyKey === `stage:${ver.version}`}
                                onClick={() => void runModelLifecycleAction("stage", ver.version)}
                                type="button"
                              >
                                Stage
                              </button>
                            ) : null}
                            {isAdmin && (lifecycle === "verified" || lifecycle === "staging") ? (
                              <button
                                className="button button-primary"
                                disabled={busyKey === `promote:${ver.version}`}
                                onClick={() => void runModelLifecycleAction("promote", ver.version)}
                                type="button"
                              >
                                Promote
                              </button>
                            ) : null}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {versions.length >= 2 ? (
              <div className="workflow-compare-box">
                <div className="workflow-compare-controls">
                  <select
                    aria-label="Base Version"
                    className="input"
                    onChange={(e) => setBaseVersion(e.target.value)}
                    value={baseVersion}
                  >
                    {versions.map((v) => (
                      <option key={`base-${v.version}`} value={v.version}>
                        Base: {v.version}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label="Candidate Version"
                    className="input"
                    onChange={(e) => setCandidateVersion(e.target.value)}
                    value={candidateVersion}
                  >
                    {versions.map((v) => (
                      <option key={`cand-${v.version}`} value={v.version}>
                        Candidate: {v.version}
                      </option>
                    ))}
                  </select>
                  <button
                    className="button button-secondary"
                    disabled={busyKey === "compare"}
                    onClick={() => void compareVersions()}
                    type="button"
                  >
                    {busyKey === "compare" ? "กำลังเปรียบเทียบ..." : "เปรียบเทียบเวอร์ชัน"}
                  </button>
                </div>

                {comparison ? (
                  <div className="workflow-compare-result">
                    <div className="workflow-def-head">
                      <strong>
                        {comparison.base_version} vs {comparison.candidate_version}
                      </strong>
                      <StatusBadge tone={comparison.zero_regression ? "good" : "bad"}>
                        {comparison.zero_regression ? "Zero Regression" : "Regression Detected"}
                      </StatusBadge>
                    </div>
                    <div className="workflow-delta-grid tabular-nums">
                      {Object.entries({ ...comparison.metric_deltas, ...comparison.capability_deltas }).map(
                        ([name, d]) => (
                          <div className="workflow-delta-row" key={name}>
                            <span>{name}</span>
                            <span>
                              {d.base} → {d.candidate} ({d.delta >= 0 ? `+${d.delta}` : d.delta})
                            </span>
                          </div>
                        ),
                      )}
                      {Object.keys(comparison.metric_deltas).length === 0 &&
                      Object.keys(comparison.capability_deltas).length === 0 ? (
                        <p className="workflow-muted">ยังไม่มีตัวเลข Metrics/Capabilities ที่เปรียบเทียบกันได้ระหว่างสองเวอร์ชันนี้</p>
                      ) : null}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}

            {selectedLineage ? (
              <div className="workflow-compare-result">
                <div className="workflow-def-head">
                  <strong>Model Lineage: {selectedLineage.lineage.version}</strong>
                  <StatusBadge tone={selectedLineage.compatibility.compatible ? "good" : "bad"}>
                    {selectedLineage.compatibility.compatible ? "Compatibility PASS" : "Compatibility FAIL"}
                  </StatusBadge>
                </div>
                <div className="workflow-delta-grid tabular-nums">
                  {selectedLineage.lineage.ancestors.map((anc) => (
                    <div className="workflow-delta-row" key={anc.version}>
                      <span>
                        {anc.version} ({anc.lifecycle_status})
                      </span>
                      <span>
                        Dataset: {anc.dataset_version || "—"} · Eval:{" "}
                        {anc.eval_passed === null || anc.eval_passed === undefined
                          ? "NOT RUN"
                          : anc.eval_passed
                            ? "PASS"
                            : "FAIL"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </>
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
              {runs.slice(0, 8).map((run) => {
                const active = isWorkflowRunActive(run.status);
                const progress = active ? computeRunProgress(run) : null;
                return (
                  <div className="workflow-run-row" key={run.id}>
                    <div className="workflow-run-main">
                      <strong>{run.workflow_key}</strong>
                      <small>
                        {run.trigger_type} · {run.steps.map((s) => `${s.step_key}:${s.evidence?.verdict ?? s.status}`).join(" → ")}
                      </small>
                      {progress ? (
                        <div className="workflow-run-progress-inline">
                          <div
                            aria-label={`ความคืบหน้า ${run.workflow_key}`}
                            aria-valuemax={100}
                            aria-valuemin={0}
                            aria-valuenow={progress.percent}
                            className="progress-track"
                            role="progressbar"
                          >
                            <div
                              className={
                                progress.tone === "warn"
                                  ? "progress-fill progress-fill-warn"
                                  : progress.tone === "neutral"
                                    ? "progress-fill progress-fill-muted"
                                    : "progress-fill"
                              }
                              style={{ width: `${progress.percent}%` }}
                            />
                          </div>
                          <span className="tabular-nums">{progress.percent}%</span>
                        </div>
                      ) : null}
                      {run.error_message ? <small className="workflow-err-note">{run.error_message}</small> : null}
                    </div>
                    <StatusBadge tone={statusToneFor(run.status)}>{run.status}</StatusBadge>
                  </div>
                );
              })}
            </div>
          )}
        </Panel>

        <Panel className="workflow-panel">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">
                <Icon name="lock" size={14} />
                <span>TIER-2 HUMAN APPROVAL QUEUE</span>
              </div>
              <h2>คำขออนุมัติที่รอดำเนินการ</h2>
            </div>
            <StatusBadge tone={pendingApprovals.length > 0 ? "warn" : "neutral"}>
              {pendingApprovals.length} รออนุมัติ
            </StatusBadge>
          </div>
          {!isAdmin ? (
            <div className="unavailable-block">
              <strong>เฉพาะผู้ดูแลระบบ (Admin) เท่านั้นที่อนุมัติ Tier-2 Gate ได้</strong>
              <p>งานฝึกโมเดล ใช้ GPU แบบมีค่าใช้จ่าย หรือการเปลี่ยนเวอร์ชัน Production จะถูกหยุดรอจนกว่า Admin จะลงนามอนุมัติ</p>
            </div>
          ) : pendingApprovals.length === 0 ? (
            <div className="unavailable-block">
              <strong>ไม่มีคำขอ Tier-2 ที่รออนุมัติในขณะนี้</strong>
              <p>เมื่อสั่งรัน Workflow กลุ่ม Training หรือ Model Promotion ระบบจะสร้างคำขอพร้อมลายเซ็น HMAC ที่นี่</p>
            </div>
          ) : (
            <div className="workflow-run-list">
              {pendingApprovals.map((app) => (
                <div className="workflow-run-row" key={app.id}>
                  <div className="workflow-run-main">
                    <strong>{app.action_type}</strong>
                    <small>
                      {app.scope} · ID: <code>{app.id}</code>
                    </small>
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
        </Panel>
      </div>
    </div>
  );
}
