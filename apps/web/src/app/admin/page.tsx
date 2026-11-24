"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Icon } from "@/components/Icon";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
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

  const fetchAdminData = useCallback(async (isCancelled?: () => boolean) => {
    try {
      const session = await readSession();
      if (isCancelled?.()) return;
      if (!session.authenticated) {
        router.replace("/login");
        return;
      }
      const results = await Promise.allSettled([
        apiRequest<AdminOverview>("admin/overview"),
        apiRequest<AdminUser[]>("admin/users"),
        apiRequest<AuditEntry[]>("admin/audit-logs"),
      ]);
      if (isCancelled?.()) return;
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
      } else {
        setError("");
      }
      if (results[0].status === "fulfilled") setOverview(results[0].value);
      if (results[1].status === "fulfilled") setUsers(results[1].value);
      if (results[2].status === "fulfilled") setAuditLogs(results[2].value);
    } catch (reason) {
      if (isCancelled?.()) return;
      setError(
        reason instanceof Error
          ? reason.message
          : "ไม่สามารถยืนยันเซสชันได้",
      );
    } finally {
      if (!isCancelled?.()) setLoading(false);
    }
  }, [router]);

  const handleRefresh = useCallback(async () => {
    setLoading(true);
    setError("");
    await fetchAdminData();
  }, [fetchAdminData]);

  useEffect(() => {
    let active = true;
    void (async () => {
      await Promise.resolve();
      if (active) {
        await fetchAdminData(() => !active);
      }
    })();
    return () => {
      active = false;
    };
  }, [fetchAdminData]);

  return (
    <div className="page-stack">
      <PageHeader
        action={
          <button
            className="button button-secondary"
            disabled={loading}
            onClick={() => void handleRefresh()}
            type="button"
          >
            <Icon name="activity" size={16} />
            {loading ? "กำลังโหลด..." : "รีเฟรชข้อมูล"}
          </button>
        }
        description="ข้อมูลผู้ดูแลระบบจาก Backend พร้อมการตรวจสิทธิ์ฝั่งเซิร์ฟเวอร์"
        eyebrow="แพลตฟอร์ม / ผู้ดูแลระบบ"
        icon="shield"
        title="แดชบอร์ดผู้ดูแลระบบ"
      />

      {loading && !overview ? (
        <Panel className="notice-panel">
          <span className="notice-icon">
            <Icon name="shield" size={18} />
          </span>
          <div>
            <strong>กำลังตรวจสอบสิทธิ์และโหลดข้อมูลจาก Backend</strong>
            <p role="status">
              กำลังดึงข้อมูลภาพรวม บัญชีผู้ใช้ และ Audit Log จาก Endpoint ผู้ดูแลระบบ...
            </p>
          </div>
        </Panel>
      ) : error ? (
        <Panel className="notice-panel">
          <span className="notice-icon">
            <Icon name="lock" size={18} />
          </span>
          <div>
            <strong>ไม่สามารถเข้าถึงข้อมูลผู้ดูแลระบบได้</strong>
            <p className="form-alert form-alert-error" role="alert">
              <Icon name="close" size={15} />
              <span>{error}</span>
            </p>
            <div className="unavailable-actions">
              <Link className="button button-secondary" href="/settings">
                กลับไปยังการตั้งค่าบัญชี
              </Link>
            </div>
          </div>
        </Panel>
      ) : (
        <>
          {overview && (
            <section aria-label="ภาพรวมผู้ดูแลระบบ" className="admin-kpi-grid">
              <Panel className="metric-card">
                <div className="metric-topline">
                  <span className="metric-icon">
                    <Icon name="user" />
                  </span>
                  <span className="metric-label">บัญชีผู้ใช้ทั้งหมด</span>
                </div>
                <div className="metric-value tabular-nums">
                  {overview.users.toLocaleString("th-TH")}
                </div>
                <div className="metric-foot">
                  <StatusBadge tone="info">Backend Users</StatusBadge>
                  <span className="metric-caption">บัญชีในระบบ</span>
                </div>
              </Panel>

              <Panel className="metric-card">
                <div className="metric-topline">
                  <span className="metric-icon metric-icon-cyan">
                    <Icon name="zap" />
                  </span>
                  <span className="metric-label">INFERENCE สำเร็จ</span>
                </div>
                <div className="metric-value tabular-nums">
                  {overview.successful_inference_requests.toLocaleString("th-TH")}
                </div>
                <div className="metric-foot">
                  <StatusBadge tone="good">Requests</StatusBadge>
                  <span className="metric-caption">คำขอที่ประมวลผลสำเร็จ</span>
                </div>
              </Panel>

              <Panel className="metric-card">
                <div className="metric-topline">
                  <span className="metric-icon metric-icon-blue">
                    <Icon name="database" />
                  </span>
                  <span className="metric-label">TOTAL TOKENS</span>
                </div>
                <div className="metric-value tabular-nums">
                  {overview.total_tokens.toLocaleString("th-TH")}
                </div>
                <div className="metric-foot">
                  <StatusBadge tone="neutral">
                    In {overview.input_tokens.toLocaleString("th-TH")}
                  </StatusBadge>
                  <span className="metric-caption tabular-nums">
                    Out {overview.output_tokens.toLocaleString("th-TH")}
                  </span>
                </div>
              </Panel>

              <Panel className="metric-card">
                <div className="metric-topline">
                  <span className="metric-icon metric-icon-violet">
                    <Icon name="key" />
                  </span>
                  <span className="metric-label">API KEY ที่ใช้งานได้</span>
                </div>
                <div className="metric-value tabular-nums">
                  {overview.active_api_keys.toLocaleString("th-TH")}
                </div>
                <div className="metric-foot">
                  <StatusBadge tone="info">
                    Policy {overview.active_quota_policies}/{overview.configured_quota_policies}
                  </StatusBadge>
                  <span className="metric-caption">โควตาที่เปิดใช้งาน</span>
                </div>
              </Panel>
            </section>
          )}

          <div className="settings-grid">
            <Panel>
              <div className="panel-heading">
                <div>
                  <div className="eyebrow">รันไทม์โมเดล</div>
                  <h2>สถานะ Native Model</h2>
                </div>
                <span className="metric-icon metric-icon-cyan">
                  <Icon name="cpu" />
                </span>
              </div>
              {overview ? (
                <div className="readiness-list">
                  <div className="readiness-row">
                    <span className="readiness-symbol">
                      <Icon name="activity" size={16} />
                    </span>
                    <div className="readiness-copy">
                      <strong>Runtime Status</strong>
                      <small>สถานะการทำงานที่ Backend รายงาน</small>
                    </div>
                    <StatusBadge
                      tone={
                        overview.native_ai.runtime_status ? "info" : "neutral"
                      }
                    >
                      {overview.native_ai.runtime_status ?? "ไม่ระบุ"}
                    </StatusBadge>
                  </div>
                  <div className="readiness-row">
                    <span className="readiness-symbol">
                      <Icon name="layers" size={16} />
                    </span>
                    <div className="readiness-copy">
                      <strong>การโหลด Native Model</strong>
                      <small>สถานะหน่วยความจำของโมเดลหลัก</small>
                    </div>
                    <StatusBadge
                      tone={
                        overview.native_ai.native_model_loaded === undefined
                          ? "neutral"
                          : overview.native_ai.native_model_loaded
                            ? "good"
                            : "warn"
                      }
                    >
                      {overview.native_ai.native_model_loaded === undefined
                        ? "ไม่ระบุ"
                        : overview.native_ai.native_model_loaded
                          ? "โหลดแล้ว"
                          : "ยังไม่โหลด"}
                    </StatusBadge>
                  </div>
                  <div className="readiness-row">
                    <span className="readiness-symbol">
                      <Icon name="sparkles" size={16} />
                    </span>
                    <div className="readiness-copy">
                      <strong>Native Inference</strong>
                      <small>ความพร้อมรับคำขอสร้างข้อความ</small>
                    </div>
                    <StatusBadge
                      tone={
                        overview.native_ai.inference_available === undefined
                          ? "neutral"
                          : overview.native_ai.inference_available
                            ? "good"
                            : "warn"
                      }
                    >
                      {overview.native_ai.inference_available === undefined
                        ? "ไม่ระบุ"
                        : overview.native_ai.inference_available
                          ? "พร้อมใช้งาน"
                          : "ไม่พร้อมใช้งาน"}
                    </StatusBadge>
                  </div>
                </div>
              ) : (
                <div className="unavailable-block">
                  <strong>สถานะ Native Model ไม่พร้อมใช้งาน</strong>
                  <p>Backend ไม่สามารถยืนยันข้อมูลภาพรวมรันไทม์ได้</p>
                </div>
              )}
            </Panel>

            <Panel>
              <div className="panel-heading">
                <div>
                  <div className="eyebrow">โควตาและทรัพยากร</div>
                  <h2>รายละเอียด Token และ Policy</h2>
                </div>
                <span className="metric-icon metric-icon-blue">
                  <Icon name="server" />
                </span>
              </div>
              {overview ? (
                <div className="readiness-list">
                  <div className="readiness-row">
                    <span className="readiness-symbol">
                      <Icon name="arrow-up-right" size={16} />
                    </span>
                    <div className="readiness-copy">
                      <strong>Input Tokens สะสม</strong>
                      <small>ปริมาณโทเค็นขาเข้าทั้งหมด</small>
                    </div>
                    <StatusBadge tone="info">
                      {overview.input_tokens.toLocaleString("th-TH")}
                    </StatusBadge>
                  </div>
                  <div className="readiness-row">
                    <span className="readiness-symbol">
                      <Icon name="arrow-down-right" size={16} />
                    </span>
                    <div className="readiness-copy">
                      <strong>Output Tokens สะสม</strong>
                      <small>ปริมาณโทเค็นขาออกทั้งหมด</small>
                    </div>
                    <StatusBadge tone="info">
                      {overview.output_tokens.toLocaleString("th-TH")}
                    </StatusBadge>
                  </div>
                  <div className="readiness-row">
                    <span className="readiness-symbol">
                      <Icon name="shield" size={16} />
                    </span>
                    <div className="readiness-copy">
                      <strong>นโยบายโควตา (Quota Policies)</strong>
                      <small>กำหนดค่าแล้ว {overview.configured_quota_policies} นโยบาย</small>
                    </div>
                    <StatusBadge tone="good">
                      ใช้งาน {overview.active_quota_policies.toLocaleString("th-TH")}
                    </StatusBadge>
                  </div>
                </div>
              ) : (
                <div className="unavailable-block">
                  <strong>Backend ไม่สามารถยืนยันข้อมูลภาพรวมได้</strong>
                </div>
              )}
              <div className="panel-link-row">
                <Link className="text-link" href="/training">
                  เปิดคอนโซล Workflow และ Tier-2 Approvals
                  <Icon name="arrow-right" size={15} />
                </Link>
              </div>
            </Panel>

            <Panel className="settings-panel-wide">
              <div className="panel-heading">
                <div>
                  <div className="eyebrow">การจัดการผู้ใช้</div>
                  <h2>บัญชีผู้ใช้ในระบบ</h2>
                </div>
                <StatusBadge tone="neutral">
                  {users ? `${users.length} บัญชี` : "ไม่ระบุ"}
                </StatusBadge>
              </div>
              {users ? (
                users.length === 0 ? (
                  <div className="unavailable-block">
                    <strong>Backend ไม่พบผู้ใช้</strong>
                  </div>
                ) : (
                  <div className="admin-list">
                    {users.map((user) => (
                      <div className="admin-list-row" key={user.id}>
                        <div className="admin-list-main">
                          <strong>{user.email}</strong>
                          <span className="admin-list-meta tabular-nums">
                            ID: <code>{user.id}</code> · สร้างเมื่อ{" "}
                            {new Date(user.created_at).toLocaleString("th-TH")}
                          </span>
                        </div>
                        <div className="workflow-actions">
                          <StatusBadge tone="info">{user.role}</StatusBadge>
                          <StatusBadge tone={user.is_active ? "good" : "bad"}>
                            {user.is_active ? "ใช้งานอยู่" : "ปิดใช้งาน"}
                          </StatusBadge>
                        </div>
                      </div>
                    ))}
                  </div>
                )
              ) : (
                <div className="unavailable-block">
                  <strong>Backend ไม่สามารถยืนยันรายการผู้ใช้ได้</strong>
                </div>
              )}
            </Panel>

            <Panel className="settings-panel-wide">
              <div className="panel-heading">
                <div>
                  <div className="eyebrow">การตรวจสอบความปลอดภัย</div>
                  <h2>Audit Log</h2>
                </div>
                <StatusBadge tone="neutral">
                  {auditLogs ? `${auditLogs.length} เหตุการณ์` : "ไม่ระบุ"}
                </StatusBadge>
              </div>
              {auditLogs ? (
                auditLogs.length === 0 ? (
                  <div className="unavailable-block">
                    <strong>ยังไม่มีเหตุการณ์ที่บันทึกไว้</strong>
                  </div>
                ) : (
                  <div className="admin-list">
                    {auditLogs.map((entry) => (
                      <div className="admin-list-row" key={entry.id}>
                        <div className="admin-list-main">
                          <strong>{entry.action}</strong>
                          <span className="admin-list-meta tabular-nums">
                            ผู้ดำเนินการ {entry.actor_user_id ?? "บัญชีถูกลบ"} ·
                            ทรัพยากร {entry.resource_id ?? "ไม่ระบุ"} ·{" "}
                            {new Date(entry.created_at).toLocaleString("th-TH")}
                          </span>
                        </div>
                        <StatusBadge tone="neutral">AUDIT</StatusBadge>
                      </div>
                    ))}
                  </div>
                )
              ) : (
                <div className="unavailable-block">
                  <strong>Backend ไม่สามารถยืนยัน Audit Log ได้</strong>
                </div>
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
