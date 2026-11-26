"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { DeveloperNav } from "@/components/DeveloperNav";
import { Icon } from "@/components/Icon";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { usePlatformHealth } from "@/hooks/usePlatformHealth";
import { readSession } from "@/lib/api";
import type { Session } from "@/lib/types";

const endpointDirectory = [
  {
    method: "POST",
    path: "/v1/native-ai/infer/stream",
    purpose: "สตรีมคำตอบจาก Native Model ด้วยการยืนยันตัวตนและบันทึกบริบท",
    access: "Session / API Key",
  },
  {
    method: "GET",
    path: "/v1/native-ai/health",
    purpose: "ตรวจสอบสถานะรันไทม์ ความพร้อมโมเดล และตัวชี้วัดความก้าวหน้า",
    access: "Public Health",
  },
  {
    method: "GET",
    path: "/v1/datasets/status",
    purpose: "ตรวจสอบ Manifest 4-Split, SHA-256 และผลตรวจ Data Leakage",
    access: "Authenticated",
  },
  {
    method: "GET / POST",
    path: "/v1/workflows/*",
    purpose: "จัดการ Central Workflow Orchestrator, Model Registry และ Tier-2 Approvals",
    access: "Authenticated / Admin",
  },
  {
    method: "GET / POST / DELETE",
    path: "/users/me/api-keys*",
    purpose: "สร้าง หมุนเวียน ตั้งเวลา Auto-rotate และเพิกถอน API Key",
    access: "Authenticated User",
  },
  {
    method: "GET",
    path: "/users/me/usage · /quota",
    purpose: "ดึงรายงาน Inference Requests, โทเค็นสะสม และ Quota Policy ปัจจุบัน",
    access: "Authenticated User",
  },
];

export default function DeveloperApiManagementPage() {
  const { apiHealth, nativeHealth, apiError, nativeError, loading, refresh } =
    usePlatformHealth();
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    readSession().then(setSession).catch(() => setSession(null));
  }, []);

  const apiHealthy = apiHealth?.status === "healthy";
  const nativeReady = Boolean(nativeHealth?.inference_available);
  const isAdmin = Boolean(session?.authenticated && session?.role === "admin");

  return (
    <div className="page-stack">
      <PageHeader
        action={
          <button
            className="button button-secondary"
            disabled={loading}
            onClick={() => void refresh()}
            type="button"
          >
            <Icon name="activity" size={16} />
            {loading ? "กำลังตรวจสอบ..." : "ตรวจสอบการเชื่อมต่อ API"}
          </button>
        }
        description="ศูนย์กลางการจัดการ API พร็อกซีฝั่งเซิร์ฟเวอร์ รายการ Endpoint ที่รองรับ และทางลัดเข้าสู่เครื่องมือสำหรับนักพัฒนา"
        eyebrow="DEVELOPER & ADVANCED / API MANAGEMENT"
        icon="code"
        title="API Management"
      />

      <DeveloperNav />

      <section aria-label="สถานะการเชื่อมต่อ API" className="capabilities-summary-grid">
        <Panel className="metric-card">
          <div className="metric-topline">
            <span className="metric-icon">
              <Icon name="server" />
            </span>
            <span className="metric-label">BACKEND PROXY</span>
          </div>
          <div className="metric-value">
            {loading && !apiHealth
              ? "กำลังตรวจสอบ"
              : apiHealthy
                ? "พร้อมใช้งาน"
                : apiError
                  ? "เชื่อมต่อไม่สำเร็จ"
                  : "รอการตอบกลับ"}
          </div>
          <div className="metric-foot">
            <StatusBadge tone={apiHealthy ? "good" : apiError ? "warn" : "neutral"}>
              {apiHealth?.service || "GET /health"}
            </StatusBadge>
            <span className="metric-caption">
              {apiError || "พร็อกซีผ่าน /api/backend/*"}
            </span>
          </div>
        </Panel>

        <Panel className="metric-card">
          <div className="metric-topline">
            <span className="metric-icon metric-icon-cyan">
              <Icon name="cpu" />
            </span>
            <span className="metric-label">NATIVE INFERENCE API</span>
          </div>
          <div className="metric-value">
            {loading && !nativeHealth
              ? "กำลังตรวจสอบ"
              : nativeReady
                ? "พร้อมรับคำขอ"
                : nativeHealth?.runtime_status || "ไม่พร้อมใช้งาน"}
          </div>
          <div className="metric-foot">
            <StatusBadge tone={nativeReady ? "good" : nativeError ? "warn" : "neutral"}>
              POST /v1/native-ai/infer/stream
            </StatusBadge>
            <span className="metric-caption">
              {nativeError || nativeHealth?.authority || "Native Core Authority"}
            </span>
          </div>
        </Panel>

        <Panel className="metric-card">
          <div className="metric-topline">
            <span className="metric-icon metric-icon-violet">
              <Icon name="lock" />
            </span>
            <span className="metric-label">SERVER ENDPOINT CONFIG</span>
          </div>
          <div className="metric-value metric-value-small">
            <code>ZYRQUEN_API_BASE_URL</code>
          </div>
          <div className="metric-foot">
            <StatusBadge tone="info">Allowlisted Routes</StatusBadge>
            <span className="metric-caption">
              กำหนดค่าฝั่งเซิร์ฟเวอร์ ป้องกัน SSRF
            </span>
          </div>
        </Panel>
      </section>

      <div className="developer-handoff-grid">
        <Link className="developer-handoff-card panel" href="/developer/keys">
          <div>
            <strong>API Keys</strong>
            <small>สร้าง API Key ตั้งเวลา Auto-rotate หมุนเวียน และดู Usage 7 วัน</small>
          </div>
          <Icon name="arrow-up-right" size={16} />
        </Link>
        <Link className="developer-handoff-card panel" href="/developer/console">
          <div>
            <strong>Developer Console</strong>
            <small>ควบคุม Workflow Orchestrator, Model Registry และไปป์ไลน์การฝึก</small>
          </div>
          <Icon name="arrow-up-right" size={16} />
        </Link>
        <Link className="developer-handoff-card panel" href="/developer/usage">
          <div>
            <strong>Usage &amp; Quotas</strong>
            <small>ตรวจสอบจำนวน Inference, Tokens และ Quota Policies ของบัญชี</small>
          </div>
          <Icon name="arrow-up-right" size={16} />
        </Link>
        {isAdmin && (
          <Link className="developer-handoff-card panel" href="/admin">
            <div>
              <strong>Admin Dashboard</strong>
              <small>จัดการผู้ใช้ทั้งหมด นโยบายโควตา และตรวจสอบ Audit Logs</small>
            </div>
            <Icon name="arrow-up-right" size={16} />
          </Link>
        )}
      </div>

      <Panel>
        <div className="panel-heading">
          <div>
            <div className="eyebrow">ALLOWLISTED BACKEND ENDPOINTS</div>
            <h2>สัญญา Endpoint ที่เปิดใช้งานจริงผ่านพร็อกซีฝั่งเซิร์ฟเวอร์</h2>
          </div>
          <StatusBadge tone="good">{endpointDirectory.length} กลุ่ม Endpoint</StatusBadge>
        </div>

        <div className="workflow-table-wrap">
          <table className="workflow-table">
            <thead>
              <tr>
                <th>Method</th>
                <th>Endpoint</th>
                <th>หน้าที่และขอบเขต</th>
                <th>สิทธิ์การเข้าถึง</th>
              </tr>
            </thead>
            <tbody>
              {endpointDirectory.map((ep) => (
                <tr key={ep.path}>
                  <td>
                    <code>{ep.method}</code>
                  </td>
                  <td>
                    <code>{ep.path}</code>
                  </td>
                  <td>{ep.purpose}</td>
                  <td>
                    <StatusBadge tone="neutral">{ep.access}</StatusBadge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
