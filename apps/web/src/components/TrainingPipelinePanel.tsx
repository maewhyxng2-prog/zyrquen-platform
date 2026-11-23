"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { apiRequest, readSession } from "@/lib/api";
import type {
  DatasetPipelineStatus,
  TrainingReadinessStatus,
  TrainingRunSummary,
  TrainingTelemetryPayload,
} from "@/lib/types";
import { Icon } from "./Icon";
import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";

function toneForRunStatus(status: string): "good" | "warn" | "bad" | "info" | "neutral" {
  switch (status) {
    case "completed":
    case "ready":
    case "verified":
      return "good";
    case "queued":
    case "running":
      return "info";
    case "not_configured":
    case "missing":
      return "warn";
    case "failed":
    case "invalid":
    case "leakage_failed":
      return "bad";
    default:
      return "neutral";
  }
}

export function TrainingPipelinePanel() {
  const [authChecked, setAuthChecked] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [datasetStatus, setDatasetStatus] = useState<DatasetPipelineStatus | null>(null);
  const [readiness, setReadiness] = useState<TrainingReadinessStatus | null>(null);
  const [runs, setRuns] = useState<TrainingRunSummary[]>([]);
  const [runsForbidden, setRunsForbidden] = useState(false);
  const [selectedTelemetry, setSelectedTelemetry] = useState<TrainingTelemetryPayload | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // Controlled form state adhering to V11 Tier-0 CPU caps + mandatory Tier-2 approval_id
  const [datasetVersion, setDatasetVersion] = useState("0.1.0");
  const [approvalId, setApprovalId] = useState("");
  const [maxSteps, setMaxSteps] = useState(100);
  const [batchSize, setBatchSize] = useState(2);
  const [blockSize, setBlockSize] = useState(128);
  const [submitting, setSubmitting] = useState(false);
  const [telemetryBusyId, setTelemetryBusyId] = useState<string | null>(null);

  const loadPipelineState = useCallback(async (isCancelled?: () => boolean) => {
    try {
      const session = await readSession();
      if (isCancelled?.()) return;
      setError("");
      setAuthChecked(true);
      if (!session.authenticated) {
        setAuthenticated(false);
        setLoading(false);
        return;
      }
      setAuthenticated(true);

      const [dsRes, readyRes, runsRes] = await Promise.allSettled([
        apiRequest<DatasetPipelineStatus>("v1/datasets/status"),
        apiRequest<TrainingReadinessStatus>("training/readiness"),
        apiRequest<{ items: TrainingRunSummary[] }>("training/runs?limit=15"),
      ]);
      if (isCancelled?.()) return;

      if (dsRes.status === "fulfilled") {
        setDatasetStatus(dsRes.value);
        const firstVer = dsRes.value.active_dataset?.version;
        if (firstVer) {
          setDatasetVersion((prev) => prev || firstVer);
        }
      } else {
        setError(
          dsRes.reason instanceof Error
            ? dsRes.reason.message
            : "ไม่สามารถตรวจสอบสถานะ Dataset API ได้",
        );
      }

      if (readyRes.status === "fulfilled") {
        setReadiness(readyRes.value);
      }

      if (runsRes.status === "fulfilled") {
        setRunsForbidden(false);
        setRuns(runsRes.value.items ?? []);
      } else {
        setRunsForbidden(true);
        setRuns([]);
      }
    } catch (err) {
      if (isCancelled?.()) return;
      setError(err instanceof Error ? err.message : "ไม่สามารถเชื่อมต่อ Dataset/Training API ได้");
    } finally {
      if (!isCancelled?.()) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await Promise.resolve();
      if (!cancelled) {
        await loadPipelineState(() => cancelled);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadPipelineState]);

  const handleSubmitTraining = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setNotice("");

    const trimmedVersion = datasetVersion.trim();
    const trimmedApproval = approvalId.trim();
    if (!trimmedVersion) {
      setError("กรุณาระบุเวอร์ชันชุดข้อมูล (dataset_version)");
      return;
    }
    if (!trimmedApproval) {
      setError("การสั่งฝึกโมเดลต้องระบุ Tier-2 Approval ID ที่ได้รับการลงนามอนุมัติแล้ว");
      return;
    }

    setSubmitting(true);
    try {
      const created = await apiRequest<TrainingRunSummary>("training/runs", {
        method: "POST",
        body: JSON.stringify({
          dataset_version: trimmedVersion,
          approval_id: trimmedApproval,
          training: {
            block_size: blockSize,
            batch_size: batchSize,
            max_steps: maxSteps,
          },
        }),
      });
      setNotice(`ส่งงานฝึกโมเดล ${created.id} สำเร็จ (สถานะ: ${created.status})`);
      setApprovalId("");
      await loadPipelineState();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "ไม่สามารถส่งคำขอเริ่มงานฝึกโมเดลได้",
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleInspectTelemetry = async (runId: string) => {
    setTelemetryBusyId(runId);
    setError("");
    try {
      const data = await apiRequest<TrainingTelemetryPayload>(
        `training/runs/${runId}/telemetry`,
      );
      setSelectedTelemetry(data);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "ไม่สามารถดึง Telemetry ของงานฝึกโมเดลนี้ได้",
      );
    } finally {
      setTelemetryBusyId(null);
    }
  };

  if (authChecked && !authenticated) {
    return (
      <section className="training-data-grid">
        <Panel className="training-data-card">
          <div className="data-card-heading">
            <span className="metric-icon"><Icon name="database" /></span>
            <span className="metric-label">สถานะชุดข้อมูล (Dataset API)</span>
          </div>
          <div className="unavailable-block">
            <strong>ต้องยืนยันตัวตนก่อนตรวจสอบสถานะชุดข้อมูล</strong>
            <p>
              เชื่อมต่อผ่าน <code>GET /v1/datasets/status</code> แบบ Read-only
              กรุณา <Link className="text-link" href="/login">เข้าสู่ระบบ</Link> เพื่อดูสถานะ Manifest และ Integrity
            </p>
          </div>
        </Panel>
        <Panel className="training-data-card">
          <div className="data-card-heading">
            <span className="metric-icon metric-icon-blue"><Icon name="activity" /></span>
            <span className="metric-label">การทำงานของการฝึกโมเดล</span>
          </div>
          <div className="unavailable-block">
            <strong>ต้องยืนยันตัวตนก่อนเข้าถึง Training API</strong>
            <p>
              เชื่อมต่อผ่าน <code>GET /training/readiness</code> และ <code>POST /training/runs</code>{" "}
              โดยบังคับสิทธิ์ Training Admin และ Tier-2 Approval Gate
            </p>
          </div>
        </Panel>
        <Panel className="training-data-card">
          <div className="data-card-heading">
            <span className="metric-icon metric-icon-violet"><Icon name="cpu" /></span>
            <span className="metric-label">ขอบเขตทรัพยากร</span>
          </div>
          <div className="unavailable-block">
            <strong>CPU Tier-0 Bounded Limits</strong>
            <p>จำกัดพารามิเตอร์ &le; 5M, batch_size &le; 4, block_size &le; 256 และห้ามใช้ Paid GPU โดยไม่ได้รับอนุมัติ</p>
          </div>
        </Panel>
      </section>
    );
  }

  const activeDataset = datasetStatus?.active_dataset;

  return (
    <div className="page-stack">
      <div className="eyebrow section-eyebrow">ไปป์ไลน์ชุดข้อมูลและการฝึกโมเดล (เชื่อมต่อ API จริง)</div>

      {error ? (
        <div className="form-alert form-alert-error" role="alert">
          <Icon name="bell" size={16} />
          <span>{error}</span>
        </div>
      ) : null}
      {notice ? (
        <div className="form-alert form-alert-success" role="status">
          <Icon name="check-circle" size={16} />
          <span>{notice}</span>
        </div>
      ) : null}

      <section className="training-data-grid">
        <Panel className="training-data-card">
          <div className="data-card-heading">
            <span className="metric-icon"><Icon name="database" /></span>
            <span className="metric-label">สถานะชุดข้อมูล (/v1/datasets/status)</span>
          </div>
          {loading && !datasetStatus ? (
            <div className="unavailable-block">
              <strong>กำลังตรวจสอบ Dataset API...</strong>
              <p>กำลังอ่านสถานะ Manifest และแฮช SHA-256 จาก Backend</p>
            </div>
          ) : datasetStatus?.configured && activeDataset ? (
            <div className="settings-key-list">
              <div className="settings-key-card">
                <div className="settings-key-head">
                  <strong>{activeDataset.version || "ชุดข้อมูลที่ตั้งค่าไว้"}</strong>
                  <StatusBadge tone={toneForRunStatus(activeDataset.status)}>
                    {activeDataset.status}
                  </StatusBadge>
                </div>
                <p className="settings-key-meta">
                  Format: <code>{activeDataset.format || "—"}</code> · Schema:{" "}
                  <code>{activeDataset.schema || "—"}</code>
                </p>
                {activeDataset.split_counts ? (
                  <p className="settings-key-meta">
                    Splits:{" "}
                    {Object.entries(activeDataset.split_counts)
                      .map(([sp, info]) => `${sp}=${info.documents ?? "?"}`)
                      .join(", ")}
                  </p>
                ) : null}
                {activeDataset.v11_leakage_check ? (
                  <p className="settings-key-meta">
                    V11 Leakage Check: <code>{activeDataset.v11_leakage_check.status}</code>
                  </p>
                ) : null}
              </div>
            </div>
          ) : (
            <div className="unavailable-block">
              <strong>ยังไม่ได้ตั้งค่าชุดข้อมูลบน Backend</strong>
              <p>{datasetStatus?.detail || "ระบบเชื่อมต่อ /v1/datasets/status แล้ว แต่ยังไม่ได้กำหนด ZYRQUEN_DATASET_DIR"}</p>
            </div>
          )}
        </Panel>

        <Panel className="training-data-card">
          <div className="data-card-heading">
            <span className="metric-icon metric-icon-blue"><Icon name="activity" /></span>
            <span className="metric-label">ความพร้อมการฝึกโมเดล (/training/readiness)</span>
          </div>
          {loading && !readiness ? (
            <div className="unavailable-block">
              <strong>กำลังตรวจสอบ Training Readiness...</strong>
              <p>กำลังตรวจสอบ Dataset, Tokenizer และสิทธิ์ Training Admin</p>
            </div>
          ) : readiness ? (
            <div className="settings-key-list">
              <div className="settings-key-card">
                <div className="settings-key-head">
                  <strong>{readiness.configured ? "พร้อมรับคำสั่ง (ต้องมี Tier-2)" : "ยังไม่พร้อมเริ่มฝึก"}</strong>
                  <StatusBadge tone={toneForRunStatus(readiness.status)}>
                    {readiness.status}
                  </StatusBadge>
                </div>
                <p className="settings-key-meta">
                  Dataset: {readiness.dataset_configured ? "พร้อม" : "ยังไม่ตั้งค่า"} · Tokenizer:{" "}
                  {readiness.tokenizer_configured ? "พร้อม" : "ยังไม่ตั้งค่า"}
                </p>
                <p className="settings-key-meta">
                  Admin Allowlist: {readiness.admin_allowlist_configured ? "ตั้งค่าแล้ว" : "ยังไม่ตั้งค่า"} ·{" "}
                  Tier-2 Approval: บังคับเสมอ
                </p>
              </div>
            </div>
          ) : (
            <div className="unavailable-block">
              <strong>ไม่สามารถโหลด Training Readiness</strong>
              <p>Endpoint /training/readiness ยังไม่ตอบกลับข้อมูล</p>
            </div>
          )}
        </Panel>

        <Panel className="training-data-card">
          <div className="data-card-heading">
            <span className="metric-icon metric-icon-violet"><Icon name="cpu" /></span>
            <span className="metric-label">ขอบเขตการฝึกบน CPU &amp; Telemetry</span>
          </div>
          <div className="settings-key-list">
            <div className="settings-key-card">
              <div className="settings-key-head">
                <strong>Guardrails &amp; Limits</strong>
                <StatusBadge tone="info">Tier-2 Enforced</StatusBadge>
              </div>
              <p className="settings-key-meta">
                Endpoint: <code>POST /training/runs</code>, <code>GET /training/runs</code>,{" "}
                <code>GET /training/runs/&#123;id&#125;/telemetry</code>
              </p>
              <p className="settings-key-meta">
                จำกัดพารามิเตอร์ &le; 5M, block_size &le; 256, batch_size &le; 4, Paid GPU ถูกบล็อกหากไม่ได้รับอนุมัติ
              </p>
            </div>
          </div>
        </Panel>
      </section>

      <div className="workflow-split-grid">
        <Panel className="workflow-panel">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">
                <Icon name="lock" size={14} />
                <span>CONTROLLED TRAINING DISPATCH</span>
              </div>
              <h2>สั่งงานฝึกโมเดล (ต้องใช้ Tier-2 Approval ID)</h2>
            </div>
            <StatusBadge tone={readiness?.configured ? "good" : "warn"}>
              {readiness?.configured ? "Artifacts Configured" : "Artifacts Not Configured"}
            </StatusBadge>
          </div>

          <form className="settings-form" onSubmit={(e) => void handleSubmitTraining(e)}>
            <div className="settings-field">
              <label htmlFor="train-dataset-version">เวอร์ชันชุดข้อมูล (dataset_version)</label>
              <input
                className="settings-input"
                id="train-dataset-version"
                onChange={(e) => setDatasetVersion(e.target.value)}
                placeholder="เช่น 0.1.0 หรือ nagi_v11"
                required
                type="text"
                value={datasetVersion}
              />
            </div>

            <div className="settings-field">
              <label htmlFor="train-approval-id">Tier-2 Approval ID (HMAC Signed)</label>
              <input
                className="settings-input"
                id="train-approval-id"
                onChange={(e) => setApprovalId(e.target.value)}
                placeholder="ระบุ Approval ID จาก Workflow Console ด้านบน"
                required
                type="text"
                value={approvalId}
              />
            </div>

            <div className="settings-field">
              <label htmlFor="train-max-steps">จำนวน Steps สูงสุด (max_steps &le; 500)</label>
              <input
                className="settings-input"
                id="train-max-steps"
                max={500}
                min={1}
                onChange={(e) => setMaxSteps(Number(e.target.value) || 100)}
                type="number"
                value={maxSteps}
              />
            </div>

            <div className="settings-field">
              <label htmlFor="train-batch-size">Batch Size (&le; 4)</label>
              <input
                className="settings-input"
                id="train-batch-size"
                max={4}
                min={1}
                onChange={(e) => setBatchSize(Number(e.target.value) || 1)}
                type="number"
                value={batchSize}
              />
            </div>

            <div className="settings-field">
              <label htmlFor="train-block-size">Block Size (&le; 256)</label>
              <input
                className="settings-input"
                id="train-block-size"
                max={256}
                min={16}
                onChange={(e) => setBlockSize(Number(e.target.value) || 128)}
                type="number"
                value={blockSize}
              />
            </div>

            <div className="workflow-actions">
              <button className="button button-primary" disabled={submitting} type="submit">
                {submitting ? "กำลังส่งคำสั่ง..." : "ส่งคำขอเริ่มฝึกโมเดล"}
              </button>
              <button
                className="button button-secondary"
                disabled={loading}
                onClick={() => void loadPipelineState()}
                type="button"
              >
                รีเฟรชสถานะจริง
              </button>
            </div>
          </form>
        </Panel>

        <Panel className="workflow-panel">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">
                <Icon name="activity" size={14} />
                <span>TRAINING RUN HISTORY &amp; TELEMETRY</span>
              </div>
              <h2>ประวัติงานฝึกโมเดล (/training/runs)</h2>
            </div>
            <StatusBadge tone="neutral">{runs.length} รายการ</StatusBadge>
          </div>

          {runsForbidden ? (
            <div className="unavailable-block">
              <strong>ต้องใช้สิทธิ์ Training Administrator</strong>
              <p>อีเมลผู้ใช้งานปัจจุบันต้องอยู่ใน ZYRQUEN_TRAINING_ADMIN_EMAILS เพื่อดูประวัติและสั่งฝึกโมเดล</p>
            </div>
          ) : runs.length === 0 ? (
            <div className="unavailable-block">
              <strong>ยังไม่มีประวัติการฝึกโมเดล</strong>
              <p>ระบบดึงข้อมูลจริงจาก GET /training/runs และจะไม่สร้างประวัติจำลอง</p>
            </div>
          ) : (
            <div className="workflow-run-list">
              {runs.map((run) => (
                <div className="workflow-run-row" key={run.id}>
                  <div className="workflow-run-main">
                    <strong>Dataset {run.dataset_version}</strong>
                    <small>
                      ID: <code>{run.id}</code>
                    </small>
                    {run.error_message ? (
                      <small className="workflow-err-note">{run.error_message}</small>
                    ) : null}
                  </div>
                  <div className="workflow-actions">
                    <StatusBadge tone={toneForRunStatus(run.status)}>{run.status}</StatusBadge>
                    <button
                      className="button button-secondary"
                      disabled={telemetryBusyId === run.id}
                      onClick={() => void handleInspectTelemetry(run.id)}
                      type="button"
                    >
                      {telemetryBusyId === run.id ? "กำลังโหลด..." : "ดู Telemetry"}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {selectedTelemetry ? (
            <div className="workflow-compare-result">
              <div className="workflow-def-head">
                <strong>Telemetry: {selectedTelemetry.run_id}</strong>
                <StatusBadge tone={toneForRunStatus(selectedTelemetry.status)}>
                  {selectedTelemetry.status}
                </StatusBadge>
              </div>
              <p className="settings-key-meta">
                Metrics logged: {selectedTelemetry.metrics.length} · Verified Checkpoints:{" "}
                {selectedTelemetry.checkpoints.length}
              </p>
            </div>
          ) : null}
        </Panel>
      </div>
    </div>
  );
}
