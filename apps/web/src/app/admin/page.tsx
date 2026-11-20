"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { apiRequest, readSession } from "@/lib/api";

type AdminOverview = {
  users: number;
  successful_inference_requests: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  active_api_keys: number;
  configured_quota_policies: number;
  active_quota_policies: number;
  native_ai: {
    runtime_status?: string;
    native_model_loaded?: boolean;
    inference_available?: boolean;
  };
};

type AdminUser = {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
};

type AuditEntry = {
  id: string;
  actor_user_id: string | null;
  action: string;
  resource_id: string | null;
  created_at: string;
};

export default function AdminPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const session = await readSession();
        if (!session.authenticated) {
          router.replace("/login");
          return;
        }
        const results = await Promise.allSettled([
          apiRequest<AdminOverview>("admin/overview"),
          apiRequest<AdminUser[]>("admin/users"),
          apiRequest<AuditEntry[]>("admin/audit-logs"),
        ]);
        if (!active) return;
        const failures = results.filter(
          (result): result is PromiseRejectedResult =>
            result.status === "rejected",
        );
        if (failures.length > 0) {
          const first = failures[0].reason;
          setError(
            first instanceof Error
              ? first.message
              : "ไม่สามารถโหลดข้อมูลผู้ดูแลระบบได้",
          );
        }
        if (results[0].status === "fulfilled") setOverview(results[0].value);
        if (results[1].status === "fulfilled") setUsers(results[1].value);
        if (results[2].status === "fulfilled") setAuditLogs(results[2].value);
      } catch (reason) {
        if (!active) return;
        setError(
          reason instanceof Error
            ? reason.message
            : "ไม่สามารถยืนยันเซสชันได้",
        );
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [router]);

  return (
    <div className="page-stack">
      <PageHeader
        description="ข้อมูลผู้ดูแลระบบจาก Backend พร้อมการตรวจสิทธิ์ฝั่งเซิร์ฟเวอร์"
        eyebrow="แพลตฟอร์ม / ผู้ดูแลระบบ"
        icon="settings"
        title="แดชบอร์ดผู้ดูแลระบบ"
      />
      {loading ? (
        <Panel><p role="status">กำลังตรวจสอบสิทธิ์และโหลดข้อมูลจาก Backend...</p></Panel>
      ) : error ? (
        <Panel>
          <p className="form-alert form-alert-error" role="alert">{error}</p>
        </Panel>
      ) : (
        <div className="settings-grid">
          <Panel>
            <h2>ภาพรวมแพลตฟอร์ม</h2>
            {overview ? (
              <div className="settings-info">
                <p>ผู้ใช้: {overview.users.toLocaleString("th-TH")}</p>
                <p>Inference สำเร็จ: {overview.successful_inference_requests.toLocaleString("th-TH")} Requests</p>
                <p>Input Tokens: {overview.input_tokens.toLocaleString("th-TH")}</p>
                <p>Output Tokens: {overview.output_tokens.toLocaleString("th-TH")}</p>
                <p>Total Tokens: {overview.total_tokens.toLocaleString("th-TH")}</p>
                <p>API Key ที่ใช้งานได้: {overview.active_api_keys.toLocaleString("th-TH")}</p>
                <p>Policy โควตาที่กำหนด: {overview.configured_quota_policies.toLocaleString("th-TH")}</p>
                <p>Policy โควตาที่ใช้งานอยู่: {overview.active_quota_policies.toLocaleString("th-TH")}</p>
              </div>
            ) : <p>Backend ไม่สามารถยืนยันข้อมูลภาพรวมได้</p>}
          </Panel>
          <Panel>
            <h2>สถานะ Native Model</h2>
            {overview ? (
              <div className="settings-info">
                <p>Runtime: {overview.native_ai.runtime_status ?? "Backend ไม่ได้รายงานสถานะ"}</p>
                <p>โหลด Model: {overview.native_ai.native_model_loaded === undefined ? "Backend ไม่ได้รายงาน" : overview.native_ai.native_model_loaded ? "ใช่" : "ไม่ใช่"}</p>
                <p>Inference: {overview.native_ai.inference_available === undefined ? "Backend ไม่ได้รายงาน" : overview.native_ai.inference_available ? "พร้อมใช้งาน" : "ไม่พร้อมใช้งาน"}</p>
              </div>
            ) : <p>สถานะ Native Model ไม่พร้อมใช้งาน</p>}
          </Panel>
          <Panel>
            <h2>บัญชีผู้ใช้</h2>
            {users ? users.length === 0 ? <p>Backend ไม่พบผู้ใช้</p> : (
              <div className="guidance-list">
                {users.map((user) => (
                  <div className="settings-info" key={user.id}>
                    <strong>{user.email}</strong>
                    <p>บทบาท {user.role} · {user.is_active ? "ใช้งานอยู่" : "ปิดใช้งาน"}</p>
                    <p>สร้างเมื่อ {new Date(user.created_at).toLocaleString("th-TH")}</p>
                  </div>
                ))}
              </div>
            ) : <p>Backend ไม่สามารถยืนยันรายการผู้ใช้ได้</p>}
          </Panel>
          <Panel>
            <h2>Audit Log</h2>
            {auditLogs ? auditLogs.length === 0 ? <p>ยังไม่มีเหตุการณ์ที่บันทึกไว้</p> : (
              <div className="guidance-list">
                {auditLogs.map((entry) => (
                  <div className="settings-info" key={entry.id}>
                    <strong>{entry.action}</strong>
                    <p>ผู้ดำเนินการ {entry.actor_user_id ?? "บัญชีถูกลบ"} · ทรัพยากร {entry.resource_id ?? "ไม่ระบุ"}</p>
                    <p>{new Date(entry.created_at).toLocaleString("th-TH")}</p>
                  </div>
                ))}
              </div>
            ) : <p>Backend ไม่สามารถยืนยัน Audit Log ได้</p>}
          </Panel>
        </div>
      )}
    </div>
  );
}
