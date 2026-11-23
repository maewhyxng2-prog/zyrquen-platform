"use client";

import { useCallback, useEffect, useState } from "react";
import { apiRequest, readSession } from "@/lib/api";
import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";
import { Icon } from "./Icon";

type DatasetStatus = {
  configured: boolean; available: boolean; valid: boolean; status: string;
  schema: string | null; version: string | null; content_sha256: string | null;
  splits: Record<string, { documents: number | null; sha256: string | null }>;
  detail: string;
};
type TrainingRun = {
  id: string; status: "queued" | "running" | "completed" | "failed";
  dataset_version: string; created_at: string;
};

function badgeTone(value: string): "good" | "warn" | "bad" | "info" | "neutral" {
  if (value === "ready" || value === "completed") return "good";
  if (value === "running" || value === "queued") return "info";
  if (value === "failed" || value === "unavailable_or_invalid") return "bad";
  if (value === "not_configured") return "warn";
  return "neutral";
}

export function PipelineStatus() {
  const [authenticated, setAuthenticated] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [dataset, setDataset] = useState<DatasetStatus | null>(null);
  const [runs, setRuns] = useState<TrainingRun[]>([]);
  const [trainingAccess, setTrainingAccess] = useState("loading");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const session = await readSession();
      setAuthChecked(true); setAuthenticated(session.authenticated);
      if (!session.authenticated) {
        setDataset(null); setRuns([]); setTrainingAccess("restricted"); return;
      }
      const [datasetResult, trainingResult] = await Promise.allSettled([
        apiRequest<DatasetStatus>("v1/datasets/status"),
        apiRequest<{ items: TrainingRun[]; total: number }>("training/runs?limit=10"),
      ]);
      if (datasetResult.status === "fulfilled") setDataset(datasetResult.value);
      else setError(datasetResult.reason instanceof Error ? datasetResult.reason.message : "อ่านสถานะชุดข้อมูลไม่สำเร็จ");
      if (trainingResult.status === "fulfilled") {
        setRuns(trainingResult.value.items ?? []); setTrainingAccess("available");
      } else setTrainingAccess("restricted");
    } catch (err) {
      setError(err instanceof Error ? err.message : "เชื่อมต่อ Pipeline API ไม่สำเร็จ");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  if (authChecked && !authenticated) {
    return <section className="training-data-grid"><Panel className="training-data-card">
      <StatusBadge tone="neutral">ต้องลงชื่อเข้าใช้</StatusBadge>
      <p>เข้าสู่ระบบเพื่ออ่านสถานะชุดข้อมูลและประวัติ Training จาก Backend</p>
    </Panel></section>;
  }

  return <>
    <div className="panel-heading">
      <div><div className="eyebrow section-eyebrow">การติดตามสถานะจาก Backend จริง</div><h2>สถานะ Pipeline</h2></div>
      <button className="button button-secondary" type="button" onClick={() => void refresh()} disabled={loading}>
        <Icon name="refresh-cw" size={14} /> {loading ? "กำลังตรวจสอบ" : "รีเฟรช"}
      </button>
    </div>
    {error ? <p role="alert" className="error-text">{error}</p> : null}
    <section className="training-data-grid" aria-label="สถานะชุดข้อมูลและ Training">
      <Panel className="training-data-card">
        <div className="data-card-heading"><span className="metric-icon"><Icon name="database" /></span><span className="metric-label">สถานะชุดข้อมูล</span></div>
        <StatusBadge tone={badgeTone(dataset?.status ?? "unknown")}>{dataset?.status ?? (loading ? "กำลังโหลด" : "ไม่ทราบสถานะ")}</StatusBadge>
        <p>{dataset?.detail ?? "ยังไม่ได้รับข้อมูลจาก Dataset API"}</p>
        {dataset?.valid ? <>
          <p>Version: <strong>{dataset.version}</strong></p>
          <p>Schema: <code>{dataset.schema}</code></p>
          <p>SHA-256: <code>{dataset.content_sha256}</code></p>
          <ul>{Object.entries(dataset.splits).map(([name, item]) => <li key={name}>{name}: {item.documents ?? "—"} documents</li>)}</ul>
        </> : null}
      </Panel>
      <Panel className="training-data-card">
        <div className="data-card-heading"><span className="metric-icon metric-icon-blue"><Icon name="activity" /></span><span className="metric-label">ประวัติการฝึกโมเดล</span></div>
        <StatusBadge tone={trainingAccess === "available" ? "good" : trainingAccess === "restricted" ? "warn" : "neutral"}>
          {trainingAccess === "available" ? "อ่านประวัติได้" : trainingAccess === "restricted" ? "ต้องมีสิทธิ์ Training Admin" : "กำลังโหลด"}
        </StatusBadge>
        {trainingAccess === "available" ? (runs.length
          ? <ul>{runs.map(run => <li key={run.id}><strong>{run.status}</strong> · {run.dataset_version} · <code>{run.id.slice(0, 8)}</code></li>)}</ul>
          : <p>ยังไม่มี Training Run ที่บันทึกไว้</p>)
          : <p>รายการ Run จำกัดตามสิทธิ์ Training Admin และแสดงเฉพาะงานของผู้ใช้ที่ได้รับอนุญาต</p>}
        <p className="footnote">แผงนี้ไม่สั่งเริ่ม Training การเริ่มงานยังต้องผ่าน Admin และ Tier-2 Approval</p>
      </Panel>
      <Panel className="training-data-card">
        <div className="data-card-heading"><span className="metric-icon metric-icon-violet"><Icon name="shield-check" /></span><span className="metric-label">ขอบเขตความปลอดภัย</span></div>
        <StatusBadge tone="good">Read-only status</StatusBadge>
        <p>แผงนี้อ่านสถานะเท่านั้น ไม่อัปโหลดข้อมูล ไม่เริ่ม Training ไม่หยุดงาน และไม่เปลี่ยน Model Registry หรือ Gate</p>
      </Panel>
    </section>
  </>;
}
