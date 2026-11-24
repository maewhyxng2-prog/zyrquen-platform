"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Icon } from "@/components/Icon";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { apiRequest, readSession } from "@/lib/api";
import type {
  DatasetPipelineStatus,
  Session,
  TrainingReadinessStatus,
} from "@/lib/types";

type WorkflowDefinitionItem = {
  workflow_key: string;
  version: string;
  group_name: string;
  title: string;
  description: string;
  default_tier: string;
};

export default function KnowledgePage() {
  const [session, setSession] = useState<Session | null>(null);
  const [sessionReady, setSessionReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [datasetStatus, setDatasetStatus] = useState<DatasetPipelineStatus | null>(null);
  const [readiness, setReadiness] = useState<TrainingReadinessStatus | null>(null);
  const [knowledgeWorkflows, setKnowledgeWorkflows] = useState<WorkflowDefinitionItem[]>([]);
  const [error, setError] = useState("");

  const loadKnowledgeState = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const current = await readSession();
      setSession(current);
      setSessionReady(true);
      if (!current.authenticated) {
        setDatasetStatus(null);
        setReadiness(null);
        setKnowledgeWorkflows([]);
        setLoading(false);
        return;
      }

      const [dsRes, readyRes, wfRes] = await Promise.allSettled([
        apiRequest<DatasetPipelineStatus>("v1/datasets/status"),
        apiRequest<TrainingReadinessStatus>("training/readiness"),
        apiRequest<{ items: WorkflowDefinitionItem[] }>("v1/workflows/definitions"),
      ]);

      if (dsRes.status === "fulfilled") {
        setDatasetStatus(dsRes.value);
      } else {
        setError(
          dsRes.reason instanceof Error
            ? dsRes.reason.message
            : "ไม่สามารถตรวจสอบสถานะ Dataset ได้",
        );
      }

      if (readyRes.status === "fulfilled") {
        setReadiness(readyRes.value);
      }

      if (wfRes.status === "fulfilled") {
        const relevant = (wfRes.value.items ?? []).filter((item) =>
          ["data", "knowledge", "knowledge_memory"].includes(
            item.group_name.toLowerCase(),
          ) || item.workflow_key.includes("data") || item.workflow_key.includes("knowledge"),
        );
        setKnowledgeWorkflows(relevant);
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "ไม่สามารถเชื่อมต่อข้อมูลชุดข้อมูลและความรู้ได้",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadKnowledgeState();
    }, 0);
    const onSessionChange = () => {
      void loadKnowledgeState();
    };
    window.addEventListener("zyrquen:session-change", onSessionChange);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("zyrquen:session-change", onSessionChange);
    };
  }, [loadKnowledgeState]);

  const activeDataset = datasetStatus?.active_dataset ?? null;

  return (
    <div className="page-stack">
      <PageHeader
        action={
          <div className="page-header-actions-group">
            <button
              className="button button-secondary"
              disabled={loading}
              onClick={() => void loadKnowledgeState()}
              type="button"
            >
              <Icon name="activity" size={16} />
              {loading ? "กำลังตรวจสอบ..." : "ตรวจสอบชุดข้อมูล"}
            </button>
            <Link className="button button-primary" href="/developer/console">
              <Icon name="terminal" size={16} />
              เปิด Developer Console
            </Link>
          </div>
        }
        description="จัดการและตรวจสอบแหล่งข้อมูล ความสมบูรณ์ของ Manifest (SHA-256) การแบ่ง 4-Split และการเชื่อมโยงความรู้ในระบบ"
        eyebrow="NATIVE AI / คลังความรู้และข้อมูล"
        icon="book"
        title="คลังความรู้และข้อมูล (Knowledge & Data)"
      />

      {error && (
        <div className="form-alert form-alert-error" role="alert">
          <Icon name="close" size={16} />
          <span>{error}</span>
        </div>
      )}

      {!sessionReady || !session?.authenticated ? (
        <Panel className="notice-panel">
          <span className="notice-icon">
            <Icon name="lock" size={18} />
          </span>
          <div>
            <strong>เข้าสู่ระบบเพื่อดูรายละเอียด Manifest ชุดข้อมูลจริงของระบบ</strong>
            <p>
              การตรวจสอบไฟล์ชุดข้อมูล (<code>GET /v1/datasets/status</code>)
              ความพร้อมก่อนฝึก (<code>GET /training/readiness</code>) และรายการ Data/Knowledge Workflow
              เปิดให้เข้าถึงเฉพาะผู้ใช้ที่ยืนยันตัวตนแล้วเพื่อรักษาความปลอดภัยของข้อมูลวิจัย
            </p>
            {sessionReady && (
              <Link className="button button-primary" href="/login">
                <Icon name="lock" size={16} />
                เข้าสู่ระบบเพื่อดูข้อมูลชุดข้อมูล
              </Link>
            )}
          </div>
        </Panel>
      ) : (
        <>
          <section aria-label="สรุปความพร้อมของชุดข้อมูลและหน่วยความรู้" className="capabilities-summary-grid">
            <Panel className="metric-card">
              <div className="metric-topline">
                <span className="metric-icon">
                  <Icon name="database" />
                </span>
                <span className="metric-label">DATASET MANIFEST</span>
              </div>
              <div className="metric-value">
                {datasetStatus?.status === "ready"
                  ? "ยืนยัน Manifest แล้ว"
                  : datasetStatus?.status === "invalid"
                    ? "ไม่ผ่านเกณฑ์"
                    : "ยังไม่กำหนดค่า"}
              </div>
              <div className="metric-foot">
                <StatusBadge
                  tone={
                    datasetStatus?.status === "ready"
                      ? "good"
                      : datasetStatus?.status === "invalid"
                        ? "bad"
                        : "neutral"
                  }
                >
                  {activeDataset?.version || datasetStatus?.status || "N/A"}
                </StatusBadge>
                <span className="metric-caption">
                  {activeDataset?.total_documents !== undefined
                    ? `${activeDataset.total_documents.toLocaleString("th-TH")} เอกสาร`
                    : datasetStatus?.detail || "ตรวจสอบจาก /v1/datasets/status"}
                </span>
              </div>
            </Panel>

            <Panel className="metric-card">
              <div className="metric-topline">
                <span className="metric-icon metric-icon-cyan">
                  <Icon name="layers" />
                </span>
                <span className="metric-label">4-SPLIT COMPLIANCE</span>
              </div>
              <div className="metric-value">
                {activeDataset?.four_split_compliant
                  ? "ครบทั้ง 4 ส่วน"
                  : activeDataset
                    ? "ยังไม่ครบ 4 ส่วน"
                    : "รอข้อมูล"}
              </div>
              <div className="metric-foot">
                <StatusBadge
                  tone={
                    activeDataset?.four_split_compliant
                      ? "good"
                      : activeDataset
                        ? "warn"
                        : "neutral"
                  }
                >
                  Train · Val · Unseen · OOD
                </StatusBadge>
                <span className="metric-caption">
                  {activeDataset?.missing_four_splits?.length
                    ? `ขาด: ${activeDataset.missing_four_splits.join(", ")}`
                    : "แยกชุดประเมินจากชุดฝึกอย่างอิสระ"}
                </span>
              </div>
            </Panel>

            <Panel className="metric-card">
              <div className="metric-topline">
                <span className="metric-icon metric-icon-violet">
                  <Icon name="shield" />
                </span>
                <span className="metric-label">LEAKAGE &amp; INTEGRITY</span>
              </div>
              <div className="metric-value">
                {activeDataset?.v11_leakage_check?.passed
                  ? "ปลอด Data Leakage"
                  : activeDataset?.v11_leakage_check?.status || "รอตรวจสอบ"}
              </div>
              <div className="metric-foot">
                <StatusBadge
                  tone={
                    activeDataset?.v11_leakage_check?.passed
                      ? "good"
                      : activeDataset
                        ? "warn"
                        : "neutral"
                  }
                >
                  {activeDataset?.v11_leakage_check?.status || "UNCHECKED"}
                </StatusBadge>
                <span className="metric-caption">
                  Tokenizer: {readiness?.tokenizer_configured ? "พร้อมใช้งาน" : "ยังไม่ตั้งค่า"}
                </span>
              </div>
            </Panel>
          </section>

          <Panel>
            <div className="panel-heading">
              <div>
                <div className="eyebrow">DATASET SPLIT &amp; PROVENANCE BREAKDOWN</div>
                <h2>รายละเอียดชุดข้อมูลที่ใช้งานอยู่</h2>
              </div>
              {activeDataset?.content_sha256 && (
                <StatusBadge tone="info">SHA-256 Verified</StatusBadge>
              )}
            </div>

            {!datasetStatus?.configured || !activeDataset ? (
              <div className="unavailable-block">
                <strong>ยังไม่ได้กำหนดชุดข้อมูลบนเซิร์ฟเวอร์ Backend</strong>
                <p>
                  {datasetStatus?.detail ||
                    "ยังไม่ได้กำหนดตัวแปร ZYRQUEN_DATASET_DIR เพื่อชี้ไปยัง Dataset Manifest จริง"}
                </p>
              </div>
            ) : (
              <>
                <div className="knowledge-meta-row tabular-nums">
                  <span>
                    เวอร์ชัน: <code>{activeDataset.version || "—"}</code>
                  </span>
                  <span>
                    Schema: <code>{activeDataset.schema || "—"}</code>
                  </span>
                  <span>
                    Format: <code>{activeDataset.format || "—"}</code>
                  </span>
                  {typeof activeDataset.licensed_sources_count === "number" && (
                    <span>
                      Licensed Sources:{" "}
                      <strong>{activeDataset.licensed_sources_count}</strong>
                    </span>
                  )}
                </div>

                {activeDataset.split_distribution && (
                  <div className="workflow-table-wrap">
                    <table className="workflow-table">
                      <thead>
                        <tr>
                          <th>Split</th>
                          <th>สถานะ</th>
                          <th>จำนวนเอกสาร</th>
                          <th>สัดส่วน</th>
                          <th>SHA-256</th>
                        </tr>
                      </thead>
                      <tbody className="tabular-nums">
                        {Object.entries(activeDataset.split_distribution).map(
                          ([splitName, dist]) => (
                            <tr key={splitName}>
                              <td>
                                <strong>{splitName}</strong>
                              </td>
                              <td>
                                <StatusBadge tone={dist.present ? "good" : "bad"}>
                                  {dist.present ? "พร้อมใช้" : "ขาดหาย"}
                                </StatusBadge>
                              </td>
                              <td>{dist.documents.toLocaleString("th-TH")}</td>
                              <td>{(dist.ratio * 100).toFixed(1)}%</td>
                              <td>
                                <code>
                                  {activeDataset.split_counts?.[splitName]?.sha256
                                    ? `${activeDataset.split_counts[splitName].sha256?.slice(0, 12)}…`
                                    : "—"}
                                </code>
                              </td>
                            </tr>
                          ),
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </Panel>

          {knowledgeWorkflows.length > 0 && (
            <Panel>
              <div className="panel-heading">
                <div>
                  <div className="eyebrow">DATA &amp; KNOWLEDGE WORKFLOWS</div>
                  <h2>เวิร์กโฟลว์จัดการข้อมูลและความรู้ใน Orchestrator กลาง</h2>
                </div>
                <Link className="text-link" href="/developer/console">
                  จัดการรันใน Developer Console
                  <Icon name="arrow-right" size={15} />
                </Link>
              </div>
              <div className="workflow-def-grid">
                {knowledgeWorkflows.map((wf) => (
                  <div className="workflow-def-card" key={`${wf.workflow_key}@${wf.version}`}>
                    <div className="workflow-def-head">
                      <span className="phase-label">{wf.group_name}</span>
                      <StatusBadge
                        tone={wf.default_tier === "tier2_approval" ? "warn" : "info"}
                      >
                        {wf.default_tier === "tier2_approval" ? "Tier-2 Gated" : "Tier-1 Auto"}
                      </StatusBadge>
                    </div>
                    <strong>{wf.title}</strong>
                    <p>{wf.description}</p>
                    <div className="workflow-def-foot">
                      <code>{wf.workflow_key}</code>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          )}
        </>
      )}

      <section aria-label="สถาปัตยกรรมการจัดการความรู้และข้อมูล" className="capability-grid">
        <Panel className="capability-panel">
          <div className="capability-top">
            <span className="phase-label">DATA PROVENANCE</span>
            <StatusBadge tone="info">มีโค้ดหลักในระบบ</StatusBadge>
          </div>
          <h2>การเตรียมชุดข้อมูลและการตรวจแฮช</h2>
          <p>
            คัดกรองและตัดข้อมูลซ้ำ ปิดบังข้อมูลส่วนบุคคลตามรูปแบบ แบ่ง 4-Split แบบกำหนดซ้ำได้
            (Train / Validation / Unseen / OOD) และตรวจสอบความสอดคล้องด้วย SHA-256
          </p>
          <div className="capability-source">
            <Icon name="terminal" size={14} />
            <code>apps/core/native/dataset.py</code>
          </div>
        </Panel>

        <Panel className="capability-panel">
          <div className="capability-top">
            <span className="phase-label">KNOWLEDGE &amp; MEMORY</span>
            <StatusBadge tone="info">มีโค้ดหลักในระบบ</StatusBadge>
          </div>
          <h2>การจัดโครงสร้างและเชื่อมโยงความรู้</h2>
          <p>
            รับความรู้ใหม่ ตรวจสอบความสัมพันธ์และตรวจจับความขัดแย้งกับความรู้เดิม
            เพื่อสร้างความถูกต้องก่อนนำไปใช้ในการให้เหตุผลและการประเมินผล
          </p>
          <div className="capability-source">
            <Icon name="terminal" size={14} />
            <code>apps/core/intelligence/knowledge.py</code>
          </div>
        </Panel>
      </section>

      <p className="footnote">
        <Icon name="help" size={14} /> การปิดบังข้อมูลส่วนบุคคล (PII) ในชุดข้อมูลทำงานแบบจับคู่รูปแบบข้อความ โมดูลหลักไม่ได้รับรองการปกป้องความเป็นส่วนตัวแบบสมบูรณ์
      </p>
    </div>
  );
}
