"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ClosureAudit } from "@/components/ClosureAudit";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { Icon, type IconName } from "@/components/Icon";
import { usePlatformHealth } from "@/hooks/usePlatformHealth";
import { readSession } from "@/lib/api";
import type { Session } from "@/lib/types";

function SystemRow({
  icon,
  title,
  detail,
  state,
  tone,
}: {
  icon: IconName;
  title: string;
  detail: string;
  state: string;
  tone: "good" | "warn" | "bad" | "neutral" | "info";
}) {
  return (
    <div className="system-row">
      <span className="system-row-icon"><Icon name={icon} size={18} /></span>
      <div className="system-row-copy"><strong>{title}</strong><small>{detail}</small></div>
      <StatusBadge tone={tone}>{state}</StatusBadge>
    </div>
  );
}

export default function SystemPage() {
  const {
    apiHealth,
    nativeHealth,
    workflowServices,
    apiError,
    nativeError,
    workflowServicesError,
    loading,
    lastChecked,
    refresh,
  } = usePlatformHealth();
  const [session, setSession] = useState<Session | null>(null);
  const [closureRefreshTick, setClosureRefreshTick] = useState(0);

  useEffect(() => {
    const syncSession = () => {
      readSession().then(setSession).catch(() => setSession(null));
    };
    syncSession();
    window.addEventListener("zyrquen:session-change", syncSession);
    return () => window.removeEventListener("zyrquen:session-change", syncSession);
  }, []);

  const apiState =
    loading && !apiHealth
      ? "กำลังตรวจสอบ"
      : apiHealth?.status === "healthy"
        ? "พร้อมใช้งาน"
        : apiHealth
          ? "ทำงานไม่สมบูรณ์"
          : apiError
            ? "ตรวจสอบไม่สำเร็จ"
            : "ยังไม่มีข้อมูล";

  const apiTone =
    apiHealth?.status === "healthy" ? "good" : apiHealth || apiError ? "warn" : "neutral";

  const nativeState =
    loading && !nativeHealth
      ? "กำลังตรวจสอบ"
      : nativeHealth?.inference_available
        ? "พร้อมใช้งาน"
        : nativeHealth?.runtime_status || (nativeError ? "ตรวจสอบไม่สำเร็จ" : "ยังไม่มีข้อมูล");

  const nativeTone =
    nativeHealth?.inference_available ? "good" : nativeHealth || nativeError ? "warn" : "neutral";

  const scheduler = workflowServices?.scheduler;
  const schedulerState =
    loading && !workflowServices
      ? "กำลังตรวจสอบ"
      : scheduler?.safely_disabled
        ? "ปิดการทำงานอย่างปลอดภัย (Diagnostics)"
        : scheduler?.running
          ? "กำลังทำงาน"
          : scheduler
            ? "พร้อมทำงาน (ยังไม่เริ่ม)"
            : workflowServicesError
              ? "ตรวจสอบไม่สำเร็จ"
              : "ยังไม่มีข้อมูล";
  const schedulerTone = scheduler?.safely_disabled
    ? "info"
    : scheduler?.running
      ? "good"
      : workflowServicesError
        ? "warn"
        : "neutral";

  const recovery = workflowServices?.recovery;
  const recoveryState =
    loading && !workflowServices
      ? "กำลังตรวจสอบ"
      : recovery?.safely_disabled
        ? "ปิดการทำงานอย่างปลอดภัย (Diagnostics)"
        : recovery?.enabled
          ? "เปิดใช้งาน (Startup Reconciliation)"
          : workflowServicesError
            ? "ตรวจสอบไม่สำเร็จ"
            : "ยังไม่มีข้อมูล";
  const recoveryTone = recovery?.safely_disabled
    ? "info"
    : recovery?.enabled
      ? "good"
      : workflowServicesError
        ? "warn"
        : "neutral";

  return (
    <div className="page-stack">
      <PageHeader
        action={
          <button
            className="button button-secondary"
            disabled={loading}
            onClick={() => {
              void refresh();
              setClosureRefreshTick((tick) => tick + 1);
            }}
            type="button"
          >
            <Icon name="activity" size={16} />
            {loading ? "กำลังตรวจสอบ..." : "ตรวจสอบบริการอีกครั้ง"}
          </button>
        }
        description="ตรวจสอบสถานะความพร้อมของ Native Model, บริการ API หลัก, Workflow Scheduler / Recovery และ V10→V11 Closure Audit จาก Endpoint จริง"
        eyebrow="แพลตฟอร์ม / สถานะระบบ"
        icon="activity"
        title="สถานะสุขภาพของระบบ"
      />
      <Panel>
        <div className="panel-heading">
          <div><div className="eyebrow">รายการบริการ</div><h2>สถานะบริการปัจจุบัน</h2></div>
          <span className="updated-label">{lastChecked ? `ตรวจสอบล่าสุด ${lastChecked.toLocaleTimeString("th-TH")}` : loading ? "กำลังตรวจสอบ..." : "ยังไม่ได้ตรวจสอบ"}</span>
        </div>
        <div className="system-list">
          <SystemRow
            detail={apiError || `GET /health${apiHealth?.service ? ` · ${apiHealth.service}` : ""}`}
            icon="server"
            state={apiState}
            title="บริการ API"
            tone={apiTone}
          />
          <SystemRow
            detail={nativeError || nativeHealth?.authority || "GET /v1/native-ai/health"}
            icon="cpu"
            state={nativeState}
            title="รันไทม์ Native Model"
            tone={nativeTone}
          />
          <SystemRow
            detail={
              workflowServicesError ||
              (scheduler
                ? `GET /v1/workflows/services/status · ${scheduler.env_flag}=${scheduler.env_enabled ? "1" : "0"}${
                    workflowServices?.diagnostics_safe_mode ? " · โหมดตรวจสอบปลอดภัย" : ""
                  }`
                : "GET /v1/workflows/services/status")
            }
            icon="command"
            state={schedulerState}
            title="ตัวตั้งเวลา Workflow (Scheduler)"
            tone={schedulerTone}
          />
          <SystemRow
            detail={
              workflowServicesError ||
              (recovery
                ? `GET /v1/workflows/services/status · ${recovery.env_flag}=${recovery.env_enabled ? "1" : "0"} · กู้คืนเมื่อเริ่มระบบ ${recovery.reconciled_runs_count} งาน`
                : "GET /v1/workflows/services/status")
            }
            icon="shield"
            state={recoveryState}
            title="ระบบกู้คืนงานค้าง (Recovery)"
            tone={recoveryTone}
          />
          <SystemRow
            detail={
              session?.authenticated
                ? `ยืนยันตัวตนจาก Backend แล้ว${session.email ? ` ในชื่อ ${session.email}` : ""}`
                : session?.expired
                  ? "เซสชันหมดอายุแล้ว กรุณาเข้าสู่ระบบใหม่อีกครั้ง"
                  : session?.error ||
                    "รองรับการสมัครสมาชิกและเข้าสู่ระบบด้วย JWT (ตรวจสอบผ่าน GET /auth/me)"
            }
            icon="shield"
            state={
              session?.authenticated
                ? "มีเซสชันใช้งานอยู่"
                : session?.expired
                  ? "เซสชันหมดอายุ"
                  : session?.error
                    ? "ยืนยันเซสชันไม่สำเร็จ"
                    : session
                      ? "ยังไม่ได้เข้าสู่ระบบ"
                      : "กำลังตรวจสอบ"
            }
            title="การยืนยันตัวตน"
            tone={
              session?.authenticated
                ? "good"
                : session?.expired || session?.error
                  ? "warn"
                  : session
                    ? "info"
                    : "neutral"
            }
          />
          <SystemRow
            detail="ยังไม่มี Endpoint สำหรับตรวจสอบสถานะฐานข้อมูล"
            icon="database"
            state="ไม่พร้อมใช้งาน"
            title="การเชื่อมต่อฐานข้อมูล"
            tone="neutral"
          />
          <SystemRow
            detail="ยังไม่มี Endpoint สำหรับตรวจสอบสถานะพื้นที่จัดเก็บโมเดลและชุดข้อมูล"
            icon="layers"
            state="ไม่พร้อมใช้งาน"
            title="พื้นที่จัดเก็บโมเดลและชุดข้อมูล"
            tone="neutral"
          />
          <SystemRow
            detail="ยังไม่มี Endpoint สำหรับตรวจวัดทรัพยากรโครงสร้างพื้นฐานและ GPU"
            icon="activity"
            state="ไม่พร้อมใช้งาน"
            title="ข้อมูลโครงสร้างพื้นฐาน"
            tone="neutral"
          />
        </div>
      </Panel>

      <section aria-label="การตรวจสอบการปิดงาน V10 สู่ V11">
        <ClosureAudit refreshTrigger={closureRefreshTick} />
      </section>

      <Panel className="notice-panel">
        <span className="notice-icon"><Icon name="help" size={18} /></span>
        <div>
          <strong>หลักการตรวจสอบสถานะระบบ</strong>
          <p>
            API รายงานเฉพาะสถานะสุขภาพบริการโดยรวม ความพร้อมของ Native Model และสถานะจริงของ Workflow Scheduler กับ Recovery (ผ่าน <code>GET /v1/workflows/services/status</code>) เพื่อให้ยืนยันได้ว่าโมดูลทำงานเบื้องหลังถูกปิดอย่างปลอดภัยระหว่างการตรวจสอบ ระบบจะไม่แสดงสถานะว่าสำเร็จหากยังไม่ได้ดำเนินการจริง สำหรับการจัดการ Endpoint และ API Keys สามารถเปิดได้ที่{" "}
            <Link className="text-link" href="/developer">
              ส่วนนักพัฒนา (Developer)
            </Link>
          </p>
        </div>
      </Panel>
    </div>
  );
}
