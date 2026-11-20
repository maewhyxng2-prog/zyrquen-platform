"use client";

import { useEffect, useState } from "react";
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
  const { apiHealth, nativeHealth, apiError, nativeError, loading, lastChecked, refresh } =
    usePlatformHealth();
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    readSession().then(setSession).catch(() => setSession(null));
  }, []);

  return (
    <div className="page-stack">
      <PageHeader
        action={<button className="button button-secondary" onClick={() => void refresh()} type="button"><Icon name="activity" size={16} /> ตรวจสอบบริการอีกครั้ง</button>}
        description="ตรวจสอบสถานะการเชื่อมต่อ API และความพร้อมของบริการจาก Endpoint ที่มีอยู่จริง หากบริการไม่พร้อมใช้งานระบบจะแจ้งเตือนตามจริงโดยไม่แสดงสถานะเท็จ"
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
            state={apiHealth?.status === "healthy" ? "พร้อมใช้งาน" : apiHealth ? "ทำงานไม่สมบูรณ์" : "ไม่พร้อมใช้งาน"}
            title="บริการ API"
            tone={apiHealth?.status === "healthy" ? "good" : apiHealth ? "warn" : "neutral"}
          />
          <SystemRow
            detail={nativeError || nativeHealth?.authority || "GET /v1/native-ai/health"}
            icon="cpu"
            state={nativeHealth?.inference_available ? "พร้อมใช้งาน" : nativeHealth?.runtime_status || "ไม่พร้อมใช้งาน"}
            title="รันไทม์ Native Model"
            tone={nativeHealth?.inference_available ? "good" : nativeHealth ? "warn" : "neutral"}
          />
          <SystemRow
            detail={session?.authenticated ? `เข้าสู่ระบบแล้ว${session.email ? ` ในชื่อ ${session.email}` : ""}` : "รองรับการสมัครสมาชิกและเข้าสู่ระบบด้วย JWT"}
            icon="shield"
            state={session?.authenticated ? "มีเซสชันใช้งานอยู่" : session ? "ยังไม่ได้เข้าสู่ระบบ" : "ไม่ทราบสถานะ"}
            title="การยืนยันตัวตน"
            tone={session?.authenticated ? "good" : session ? "info" : "neutral"}
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
      <Panel className="notice-panel">
        <span className="notice-icon"><Icon name="help" size={18} /></span>
        <div>
          <strong>หลักการตรวจสอบสถานะระบบ</strong>
          <p>API รายงานเฉพาะสถานะสุขภาพบริการโดยรวมและความพร้อมของ Native Model ส่วนฐานข้อมูล พื้นที่จัดเก็บ การใช้ GPU และบันทึกเหตุการณ์ยังไม่ได้เปิดใช้งานผ่านเส้นทาง API ปัจจุบัน ระบบจะไม่แสดงสถานะว่าสำเร็จหากยังไม่ได้ดำเนินการจริง และหากบริการไม่พร้อมใช้งานให้ตรวจสอบการตั้งค่าตัวแปร API ฝั่งเซิร์ฟเวอร์แล้วกดตรวจสอบอีกครั้ง</p>
        </div>
      </Panel>
    </div>
  );
}
