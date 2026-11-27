"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { DeveloperNav } from "@/components/DeveloperNav";
import { Icon } from "@/components/Icon";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { readSession } from "@/lib/api";
import { getMyQuota, getMyUsage } from "@/lib/user-api";
import {
  belongsToAccount,
  quotaPercent,
  quotaState,
} from "@/lib/user-state";
import type { QuotaSummary, Session, UsageSummary } from "@/lib/types";

function QuotaMetric({
  label,
  used,
  limit,
}: {
  label: string;
  used: number;
  limit: number | null;
}) {
  const percent = quotaPercent(used, limit);
  const clamped = percent === null ? 0 : Math.min(100, Math.max(0, percent));
  return (
    <div className="settings-quota-item">
      <div className="settings-quota-head">
        <span>{label}</span>
        {limit !== null && (
          <code className="tabular-nums">
            {used.toLocaleString("th-TH")} / {limit.toLocaleString("th-TH")}
          </code>
        )}
      </div>
      {limit === null ? (
        <p className="settings-quota-meta">
          Backend ไม่ได้กำหนดขีดจำกัดสำหรับรายการนี้
        </p>
      ) : (
        <>
          <div
            aria-label={`สัดส่วน ${label}`}
            aria-valuemax={100}
            aria-valuemin={0}
            aria-valuenow={clamped}
            className="progress-track"
            role="progressbar"
          >
            <div
              className={
                clamped >= 80
                  ? "progress-fill progress-fill-warn"
                  : "progress-fill"
              }
              style={{ width: `${clamped}%` }}
            />
          </div>
          <p className="settings-quota-meta tabular-nums">
            {percent}% · {quotaState(used, limit)}
          </p>
        </>
      )}
    </div>
  );
}

export default function DeveloperUsagePage() {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const sessionRef = useRef<Session | null>(null);
  const [sessionReady, setSessionReady] = useState(false);

  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [quota, setQuota] = useState<QuotaSummary | null>(null);
  const [usageLoading, setUsageLoading] = useState(true);
  const [usageOwnerId, setUsageOwnerId] = useState<string | null>(null);
  const [usageError, setUsageError] = useState("");
  const [quotaError, setQuotaError] = useState("");

  useEffect(() => {
    let active = true;
    const refreshSession = () => {
      readSession()
        .then((current) => {
          if (!active) return;
          if (sessionRef.current?.userId !== current.userId) {
            setUsage(null);
            setQuota(null);
            setUsageOwnerId(null);
            setUsageLoading(Boolean(current.authenticated && current.userId));
            setUsageError("");
            setQuotaError("");
          } else if (!current.authenticated) {
            setUsageLoading(false);
          }
          sessionRef.current = current;
          setSession(current);
          setSessionReady(true);
        })
        .catch(() => {
          if (!active) return;
          setUsageLoading(false);
          const unavailableSession: Session = {
            authenticated: false,
            email: null,
            userId: null,
            role: null,
            verified: false,
            emailVerified: false,
            error: "ไม่สามารถตรวจสอบสถานะเซสชันปัจจุบันได้",
          };
          sessionRef.current = unavailableSession;
          setSession(unavailableSession);
          setSessionReady(true);
        });
    };
    refreshSession();
    window.addEventListener("zyrquen:session-change", refreshSession);
    return () => {
      active = false;
      window.removeEventListener("zyrquen:session-change", refreshSession);
    };
  }, []);

  useEffect(() => {
    if (sessionReady && (!session?.authenticated || !session.userId)) {
      router.replace("/login");
    }
  }, [sessionReady, session?.authenticated, session?.userId, router]);

  useEffect(() => {
    if (!sessionReady || !session?.authenticated || !session.userId) {
      return;
    }
    const ownerId = session.userId;
    if (!ownerId) return;
    let active = true;
    const isCurrentOwner = () =>
      active && sessionRef.current?.userId === ownerId;

    void Promise.allSettled([getMyUsage(ownerId), getMyQuota(ownerId)])
      .then(([usageResult, quotaResult]) => {
        if (!isCurrentOwner()) return;
        if (usageResult.status === "fulfilled") {
          setUsage(usageResult.value);
          setUsageError("");
        } else {
          setUsage(null);
          setUsageError(
            usageResult.reason instanceof Error
              ? usageResult.reason.message
              : "ไม่สามารถโหลดข้อมูล Usage ได้",
          );
        }
        if (quotaResult.status === "fulfilled") {
          setQuota(quotaResult.value);
          setQuotaError("");
        } else {
          setQuota(null);
          setQuotaError(
            quotaResult.reason instanceof Error
              ? quotaResult.reason.message
              : "ไม่สามารถโหลดข้อมูลโควตาได้",
          );
        }
      })
      .finally(() => {
        if (!isCurrentOwner()) return;
        setUsageOwnerId(ownerId);
        setUsageLoading(false);
      });

    return () => {
      active = false;
    };
  }, [sessionReady, session?.authenticated, session?.userId]);

  if (!sessionReady || !session?.authenticated) {
    return (
      <div className="page-stack">
        <PageHeader
          description="ตรวจสอบปริมาณการใช้งาน Native Inference, โทเค็นสะสม และนโยบายโควตาประจำบัญชี"
          eyebrow="DEVELOPER & ADVANCED / USAGE & QUOTAS"
          icon="layers"
          title="Usage & Quotas"
        />
        <DeveloperNav />
        <Panel className="notice-panel">
          <span className="notice-icon">
            <Icon name="lock" size={18} />
          </span>
          <div>
            <strong>
              {!sessionReady
                ? "กำลังตรวจสอบเซสชันจาก Backend..."
                : session?.expired
                  ? "เซสชันหมดอายุแล้ว"
                  : "จำเป็นต้องเข้าสู่ระบบเพื่อดูข้อมูล Usage และ Quotas"}
            </strong>
            <p>
              {!sessionReady
                ? "ระบบกำลังยืนยันตัวตนเพื่อดึงข้อมูลโควตาเฉพาะบัญชีของคุณ"
                : session?.error ||
                  "กรุณาเข้าสู่ระบบด้วยบัญชีของคุณก่อนตรวจสอบ Usage และ Quotas"}
            </p>
            {sessionReady && (
              <Link className="button button-primary" href="/login">
                <Icon name="lock" size={16} />
                ไปยังหน้าเข้าสู่ระบบ
              </Link>
            )}
          </div>
        </Panel>
      </div>
    );
  }

  const usageIsLoading =
    usageLoading || !belongsToAccount(usageOwnerId, session.userId);

  return (
    <div className="page-stack">
      <PageHeader
        action={
          <Link className="button button-secondary" href="/developer/keys">
            <Icon name="key" size={16} />
            จัดการ API Keys
          </Link>
        }
        description="ข้อมูลการใช้งานจริงจาก /users/me/usage และนโยบายโควตาแบบ fail-closed จาก /users/me/quota"
        eyebrow="DEVELOPER & ADVANCED / USAGE & QUOTAS"
        icon="layers"
        title="Usage & Quotas"
      />

      <DeveloperNav />

      <div className="settings-grid">
        <Panel>
          <div className="panel-heading">
            <div>
              <div className="eyebrow">การใช้งานสะสม</div>
              <h2>สถิติการประมวลผล ({session.email || "บัญชีปัจจุบัน"})</h2>
            </div>
            <span className="metric-icon metric-icon-blue">
              <Icon name="server" />
            </span>
          </div>
          {usageIsLoading ? (
            <p className="settings-confirmation" role="status">
              กำลังโหลดข้อมูลจาก Backend...
            </p>
          ) : usageError ? (
            <p className="form-alert form-alert-error" role="alert">
              <Icon name="close" size={15} /> {usageError}
            </p>
          ) : usage ? (
            <div className="settings-info">
              <span>Inference สำเร็จ</span>
              <code className="tabular-nums">
                {usage.successfulRequests.toLocaleString("th-TH")} ครั้ง
              </code>
              <p className="tabular-nums">
                Input {usage.inputTokens.toLocaleString("th-TH")} · Output{" "}
                {usage.outputTokens.toLocaleString("th-TH")} · รวม{" "}
                {usage.totalTokens.toLocaleString("th-TH")} Tokens
              </p>
              {usage.updatedAt && (
                <p>
                  อัปเดตล่าสุดจาก Backend:{" "}
                  {new Date(usage.updatedAt).toLocaleString("th-TH")}
                </p>
              )}
            </div>
          ) : (
            <p className="settings-key-meta">ยังไม่มีข้อมูลการใช้งาน</p>
          )}
        </Panel>

        <Panel>
          <div className="panel-heading">
            <div>
              <div className="eyebrow">นโยบายโควตา (FAIL-CLOSED)</div>
              <h2>ขีดจำกัดการใช้งานปัจจุบัน</h2>
            </div>
            <span className="metric-icon metric-icon-cyan">
              <Icon name="shield" />
            </span>
          </div>
          {usageIsLoading ? (
            <p className="settings-confirmation" role="status">
              กำลังโหลดข้อมูลโควตาจาก Backend...
            </p>
          ) : quotaError ? (
            <p className="form-alert form-alert-error" role="alert">
              <Icon name="close" size={15} /> {quotaError}
            </p>
          ) : !quota?.configured ? (
            <div className="security-callout">
              <Icon name="lock" size={16} />
              <span>
                ยังไม่มี Policy โควตาที่ Backend ยืนยันได้ Native Inference จะถูกปฏิเสธแบบ fail-closed
              </span>
            </div>
          ) : !quota.active ? (
            <div className="security-callout">
              <Icon name="lock" size={16} />
              <span>
                Policy โควตาหมดอายุหรือยังไม่เริ่มใช้งาน Native Inference จึงถูกปฏิเสธ
              </span>
            </div>
          ) : (
            <div className="settings-quota-list">
              <QuotaMetric
                label="Requests ที่ใช้หรือกำลังประมวลผล"
                used={quota.requestsInUse}
                limit={quota.maxRequests}
              />
              <QuotaMetric
                label="Input Tokens ที่ใช้หรือจอง"
                used={quota.inputTokens}
                limit={quota.maxInputTokens}
              />
              <QuotaMetric
                label="Output Tokens ที่ใช้หรือจอง"
                used={quota.outputTokens}
                limit={quota.maxOutputTokens}
              />
              <QuotaMetric
                label="Total Tokens ที่ใช้หรือจอง"
                used={quota.totalTokens}
                limit={quota.maxTotalTokens}
              />
              {quota.windowStartedAt && quota.windowEndsAt && (
                <p className="settings-quota-meta">
                  ช่วงโควตา:{" "}
                  {new Date(quota.windowStartedAt).toLocaleString("th-TH")} –{" "}
                  {new Date(quota.windowEndsAt).toLocaleString("th-TH")}
                </p>
              )}
              {quota.runningRequests > 0 && (
                <p className="settings-quota-meta">
                  กำลังประมวลผลอยู่{" "}
                  {quota.runningRequests.toLocaleString("th-TH")} Request
                </p>
              )}
            </div>
          )}
        </Panel>

        <Panel className="settings-panel-wide">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">RECENT INFERENCE LOGS</div>
              <h2>ประวัติคำขอประมวลผลล่าสุด</h2>
            </div>
            <StatusBadge tone="neutral">
              {usage?.records ? `${usage.records.length} รายการ` : "0 รายการ"}
            </StatusBadge>
          </div>
          {!usage?.records || usage.records.length === 0 ? (
            <div className="unavailable-block">
              <strong>ยังไม่มีบันทึกคำขอประมวลผลของบัญชีนี้</strong>
              <p>เมื่อมีการเรียกใช้ Native Inference ผ่านพื้นที่ทำงาน AI หรือ API Key บันทึกจริงจะแสดงที่นี่</p>
            </div>
          ) : (
            <div className="workflow-table-wrap">
              <table className="workflow-table">
                <thead>
                  <tr>
                    <th>Request ID</th>
                    <th>สถานะ</th>
                    <th>Model</th>
                    <th>Input / Output / Total</th>
                    <th>เวลา</th>
                  </tr>
                </thead>
                <tbody className="tabular-nums">
                  {usage.records.slice(0, 20).map((rec) => (
                    <tr key={rec.requestId}>
                      <td>
                        <code>{rec.requestId.slice(0, 12)}…</code>
                      </td>
                      <td>
                        <StatusBadge
                          tone={rec.status === "completed" ? "good" : "neutral"}
                        >
                          {rec.status}
                        </StatusBadge>
                      </td>
                      <td>{rec.modelVersion || "native"}</td>
                      <td>
                        {rec.inputTokens} / {rec.outputTokens} /{" "}
                        <strong>{rec.totalTokens}</strong>
                      </td>
                      <td>{new Date(rec.createdAt).toLocaleString("th-TH")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
