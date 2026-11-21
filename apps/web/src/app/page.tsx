"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { Icon } from "@/components/Icon";
import { usePlatformHealth } from "@/hooks/usePlatformHealth";
import { readSession } from "@/lib/api";
import type { Session } from "@/lib/types";

function valueForHealth(ok: boolean | null, label: string, hasError = false) {
  if (ok === null) {
    return hasError
      ? { text: "ตรวจสอบไม่สำเร็จ", tone: "warn" as const }
      : { text: "ยังไม่มีข้อมูล", tone: "neutral" as const };
  }

  return ok
    ? { text: label, tone: "good" as const }
    : { text: "ทำงานไม่สมบูรณ์", tone: "warn" as const };
}

export default function DashboardPage() {
  const {
    apiHealth,
    nativeHealth,
    apiError,
    nativeError,
    loading,
    lastChecked,
    refresh,
  } = usePlatformHealth();
  const [session, setSession] = useState<Session | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);

  const syncSession = useCallback(() => {
    readSession()
      .then((current) => {
        setSession(current);
        setSessionError(null);
      })
      .catch((reason) => {
        setSession(null);
        setSessionError(
          reason instanceof Error
            ? reason.message
            : "ไม่สามารถตรวจสอบสถานะเซสชันปัจจุบันได้",
        );
      });
  }, []);

  useEffect(() => {
    syncSession();
    window.addEventListener("zyrquen:session-change", syncSession);
    return () => window.removeEventListener("zyrquen:session-change", syncSession);
  }, [syncSession]);

  const apiStatus = valueForHealth(
    apiHealth ? apiHealth.status === "healthy" : null,
    "พร้อมใช้งาน",
    Boolean(apiError),
  );

  const nativeStatus = valueForHealth(
    nativeHealth ? nativeHealth.inference_available : null,
    "พร้อมประมวลผล",
    Boolean(nativeError),
  );

  const apiDisplayStatus =
    loading && !apiHealth ? "กำลังตรวจสอบ" : apiStatus.text;

  const nativeDisplayStatus =
    loading && !nativeHealth ? "กำลังตรวจสอบ" : nativeStatus.text;

  const authBadge = sessionError
    ? { text: "ตรวจสอบไม่สำเร็จ", tone: "warn" as const, detail: sessionError }
    : !session
      ? {
          text: "กำลังตรวจสอบ",
          tone: "neutral" as const,
          detail: "กำลังตรวจสอบสถานะเซสชันปัจจุบันจาก /api/session",
        }
      : session.authenticated
        ? {
            text: "เข้าสู่ระบบแล้ว",
            tone: "good" as const,
            detail: `ยืนยันตัวตนจาก Backend แล้ว${session.email ? ` ในชื่อ ${session.email}` : ""}`,
          }
        : session.expired
          ? {
              text: "เซสชันหมดอายุ",
              tone: "warn" as const,
              detail: "เซสชันหมดอายุแล้ว กรุณาเข้าสู่ระบบใหม่อีกครั้ง",
            }
          : session.error
            ? {
                text: "ยืนยันเซสชันไม่สำเร็จ",
                tone: "warn" as const,
                detail: session.error,
              }
            : {
                text: "ยังไม่ได้เข้าสู่ระบบ",
                tone: "info" as const,
                detail:
                  "เข้าสู่ระบบหรือสมัครสมาชิกเพื่อใช้งานพื้นที่สนทนา (ต้องเชื่อมต่อ API)",
              };

  return (
    <div className="page-stack">
      <PageHeader
        action={
          <button
            className="button button-secondary"
            disabled={loading}
            onClick={() => {
              void refresh();
              syncSession();
            }}
            type="button"
          >
            <Icon name="activity" size={16} />
            {loading ? "กำลังตรวจสอบ..." : "รีเฟรชสถานะ"}
          </button>
        }
        description="แพลตฟอร์ม AI ที่พัฒนาขึ้นเพื่อให้คุณสามารถใช้งานระบบปัญญาประดิษฐ์ผ่านเครือข่ายออนไลน์ได้อย่างสะดวกและเป็นระบบ"
        eyebrow="แพลตฟอร์ม / ภาพรวม"
        icon="gauge"
        title="ยินดีต้อนรับสู่ ZYRQUEN Ω∞"
      />

      <section aria-label="สถานะการทำงาน" className="status-grid">
        <Panel className="metric-card">
          <div className="metric-topline">
            <span className="metric-icon"><Icon name="server" /></span>
            <span className="metric-label">บริการ API</span>
          </div>
          <div className="metric-value">{apiDisplayStatus}</div>
          <div className="metric-foot">
            <StatusBadge tone={apiStatus.tone}>
              {apiDisplayStatus}
            </StatusBadge>
            <span className="metric-caption">
              {apiError || apiHealth?.service || "GET /health"}
            </span>
          </div>
        </Panel>

        <Panel className="metric-card">
          <div className="metric-topline">
            <span className="metric-icon metric-icon-cyan"><Icon name="cpu" /></span>
            <span className="metric-label">รันไทม์ NATIVE AI</span>
          </div>
          <div className="metric-value">{nativeDisplayStatus}</div>
          <div className="metric-foot">
            <StatusBadge tone={nativeStatus.tone}>
              {nativeHealth?.runtime_status ||
                (loading && !nativeHealth
                  ? "กำลังตรวจสอบ"
                  : nativeError
                    ? "ตรวจสอบไม่สำเร็จ"
                    : "ยังไม่มีข้อมูล")}
            </StatusBadge>
            <span className="metric-caption">
              {nativeError ||
                (nativeHealth
                  ? nativeHealth.native_model_loaded
                    ? "โหลด Native Model แล้ว"
                    : "ยังไม่ได้โหลด Native Model"
                  : "ยังไม่มีข้อมูลสถานะโมเดล")}
            </span>
          </div>
        </Panel>

        <Panel className="metric-card">
          <div className="metric-topline">
            <span className="metric-icon metric-icon-blue"><Icon name="database" /></span>
            <span className="metric-label">ไปป์ไลน์ชุดข้อมูล</span>
          </div>
          <div className="metric-value metric-value-small">
            มีโมดูลหลักในระบบ
          </div>
          <div className="metric-foot">
            <StatusBadge tone="info">ยังไม่เปิดใช้ผ่าน API</StatusBadge>
            <span className="metric-caption">
              ไม่มี Endpoint ตรวจสอบสถานะชุดข้อมูล
            </span>
          </div>
        </Panel>

        <Panel className="metric-card">
          <div className="metric-topline">
            <span className="metric-icon metric-icon-violet"><Icon name="layers" /></span>
            <span className="metric-label">ไปป์ไลน์การฝึกโมเดล</span>
          </div>
          <div className="metric-value metric-value-small">
            มีโมดูลหลักในระบบ
          </div>
          <div className="metric-foot">
            <StatusBadge tone="info">ยังไม่เปิดใช้ผ่าน API</StatusBadge>
            <span className="metric-caption">
              ไม่มี Endpoint สั่งงานการฝึกโมเดล
            </span>
          </div>
        </Panel>
      </section>

      <section aria-label="การติดตามความคืบหน้า ZYRQUEN Ω∞">
        <Panel className="progress-monitoring-panel">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">
                การติดตามความคืบหน้า
                {(nativeHealth?.platform_version || nativeHealth?.model_version)
                  ? ` · ${nativeHealth.platform_version || nativeHealth.model_version}`
                  : ""}
              </div>
              <h2>ตัวชี้วัดความก้าวหน้า ZYRQUEN Ω∞</h2>
            </div>
            <StatusBadge
              tone={
                nativeError
                  ? "warn"
                  : nativeHealth?.progress_metrics?.evaluation_status === "evaluated"
                    ? "good"
                    : "neutral"
              }
            >
              {loading && !nativeHealth
                ? "กำลังตรวจสอบ"
                : nativeError
                  ? "ไม่สามารถเชื่อมต่อ Backend"
                  : nativeHealth?.progress_metrics?.evaluation_status === "evaluated"
                    ? "มีผลประเมินจาก Backend"
                    : "ยังไม่มีข้อมูลผลประเมินจาก Backend"}
            </StatusBadge>
          </div>

          {(() => {
            const pm = nativeHealth?.progress_metrics ?? null;
            const genScore = pm?.generalization_score ?? null;
            const relScore = pm?.relational_reasoning_success_rate ?? null;
            const hasAnyMetric = genScore !== null || relScore !== null;

            if (!hasAnyMetric) {
              return (
                <div className="unavailable-block">
                  <strong>
                    {loading && !nativeHealth
                      ? "กำลังตรวจสอบค่า Generalization Score และ Relational Reasoning Success Rate"
                      : nativeError
                        ? "ไม่สามารถดึงตัวชี้วัดจาก Backend ได้"
                        : "ยังไม่มีค่าชี้วัดความก้าวหน้าจาก Backend"}
                  </strong>
                  <p>
                    {nativeError ||
                      "Endpoint /v1/native-ai/health ยังไม่ได้ส่งค่า Generalization Score และ Relational Reasoning Success Rate ที่วัดผลจริงกลับมา ระบบจะไม่แสดงตัวเลขหรือกราฟจำลอง"}
                  </p>
                </div>
              );
            }

            return (
              <div className="progress-metrics-grid">
                <div className="progress-metric-block">
                  <div className="progress-metric-head">
                    <span className="metric-label">GENERALIZATION SCORE</span>
                  </div>
                  <div className="progress-metric-value tabular-nums">
                    {genScore !== null ? `${genScore.toFixed(1)}%` : "ไม่ระบุ"}
                  </div>
                  {genScore !== null && (
                    <div
                      aria-label="แถบความคืบหน้า Generalization Score"
                      className="progress-track"
                    >
                      <div
                        className="progress-fill"
                        style={{
                          width: `${Math.min(100, Math.max(0, genScore))}%`,
                        }}
                      />
                    </div>
                  )}
                  <p className="progress-metric-note">
                    {pm?.metrics_source
                      ? `แหล่งข้อมูลจาก Backend: ${pm.metrics_source}`
                      : "ค่าที่รายงานจาก Backend"}
                  </p>
                </div>

                <div className="progress-metric-block">
                  <div className="progress-metric-head">
                    <span className="metric-label">
                      RELATIONAL REASONING SUCCESS RATE
                    </span>
                  </div>
                  <div className="progress-metric-value tabular-nums">
                    {relScore !== null ? `${relScore.toFixed(1)}%` : "ไม่ระบุ"}
                  </div>
                  {relScore !== null && (
                    <div
                      aria-label="แถบความคืบหน้า Relational Reasoning Success Rate"
                      className="progress-track"
                    >
                      <div
                        className="progress-fill progress-fill-blue"
                        style={{
                          width: `${Math.min(100, Math.max(0, relScore))}%`,
                        }}
                      />
                    </div>
                  )}
                  <p className="progress-metric-note">
                    {pm?.metrics_source
                      ? `แหล่งข้อมูลจาก Backend: ${pm.metrics_source}`
                      : "ค่าที่รายงานจาก Backend"}
                  </p>
                </div>
              </div>
            );
          })()}

          <div className="panel-link-row">
            <Link className="text-link" href="/training">
              ตรวจสอบข้อมูลการฝึกอบรมและสถานะความสามารถ
              <Icon name="arrow-right" size={15} />
            </Link>
          </div>
        </Panel>
      </section>

      <section className="dashboard-grid">
        <Panel className="dashboard-primary">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">สถานะระบบ</div>
              <h2>ความพร้อมของบริการ</h2>
            </div>
            <span className="updated-label">
              <span className="status-dot" />
              {lastChecked
                ? `ตรวจสอบล่าสุด ${lastChecked.toLocaleTimeString("th-TH")}`
                : "รอการตรวจสอบสถานะ"}
            </span>
          </div>

          <div className="readiness-list">
            <div className="readiness-row">
              <span className="readiness-symbol">
                <Icon name="server" size={17} />
              </span>
              <div className="readiness-copy">
                <strong>บริการ API หลัก (FastAPI)</strong>
                <small>
                  {apiError ||
                    "ตรวจสอบสถานะการเชื่อมต่อ API ผ่าน /health"}
                </small>
              </div>
              <StatusBadge tone={apiStatus.tone}>
                {apiDisplayStatus}
              </StatusBadge>
            </div>

            <div className="readiness-row">
              <span className="readiness-symbol">
                <Icon name="cpu" size={17} />
              </span>
              <div className="readiness-copy">
                <strong>การประมวลผล Native Model</strong>
                <small>
                  {nativeHealth?.authority ||
                    nativeError ||
                    "ตรวจสอบความพร้อมของบริการผ่าน /v1/native-ai/health"}
                </small>
              </div>
              <StatusBadge tone={nativeStatus.tone}>
                {nativeDisplayStatus}
              </StatusBadge>
            </div>

            <div className="readiness-row">
              <span className="readiness-symbol">
                <Icon name="shield" size={17} />
              </span>
              <div className="readiness-copy">
                <strong>การยืนยันตัวตน</strong>
                <small>{authBadge.detail}</small>
              </div>
              <StatusBadge tone={authBadge.tone}>{authBadge.text}</StatusBadge>
            </div>
          </div>

          <div className="panel-link-row">
            <Link className="text-link" href="/system">
              ดูรายละเอียดสถานะระบบ
              <Icon name="arrow-right" size={15} />
            </Link>
          </div>
        </Panel>

        <Panel className="quick-panel">
          <div className="eyebrow">คำแนะนำระบบ</div>
          <h2>เริ่มต้นใช้งาน ZYRQUEN Ω∞</h2>
          <p>
            ZYRQUEN ประกอบด้วยพื้นที่สนทนา การจัดการบัญชี
            ประวัติการสนทนา การตั้งค่า และเครื่องมือจัดการ Native Model
          </p>
          <Link className="button button-primary full-button" href="/workspace">
            <Icon name="sparkles" size={16} />
            เปิดพื้นที่ทำงาน AI
            <Icon name="arrow-right" size={16} />
          </Link>
          <div className="quick-divider" />
          <Link className="quick-link" href="/training">
            <span className="quick-link-icon">
              <Icon name="layers" size={16} />
            </span>
            <span>
              <strong>เครื่องมือจัดการ Native Model</strong>
              <small>ตรวจสอบโมดูลเตรียมชุดข้อมูลและการฝึกอบรม</small>
            </span>
            <Icon name="chevron-right" size={16} />
          </Link>
        </Panel>
      </section>

      <section className="dashboard-grid dashboard-lower">
        <Panel>
          <div className="panel-heading">
            <div>
              <div className="eyebrow">คำแนะนำการใช้งาน</div>
              <h2>ขั้นตอนการใช้งานระบบ</h2>
            </div>
            <Icon name="help" size={18} className="subtle-icon" />
          </div>
          <div className="guidance-list">
            <div className="guidance-group">
              <strong>เริ่มต้นใช้งาน</strong>
              <ul>
                <li>เข้าสู่ระบบด้วยบัญชีของคุณ</li>
                <li>เปิดพื้นที่ทำงานเพื่อเริ่มต้นสนทนา</li>
                <li>พิมพ์ข้อความลงในช่องสนทนาแล้วส่งข้อความ</li>
                <li>ตรวจสอบคำตอบจากระบบในพื้นที่สนทนา</li>
              </ul>
            </div>
            <div className="guidance-group">
              <strong>การจัดการบทสนทนาและการตั้งค่าบัญชี</strong>
              <ul>
                <li>
                  สร้างบทสนทนาใหม่เมื่อเริ่มหัวข้อใหม่
                  และตรวจสอบประวัติการสนทนาที่บันทึกไว้
                </li>
                <li>
                  จัดการบทสนทนาตามความสามารถที่ระบบรองรับ
                  ตรวจสอบข้อมูลบัญชี และออกจากระบบเมื่อใช้งานเสร็จสิ้น
                </li>
              </ul>
            </div>
          </div>
        </Panel>

        <Panel>
          <div className="panel-heading">
            <div>
              <div className="eyebrow">สถานะระบบและโมดูลหลัก</div>
              <h2>รายงานความพร้อมตามจริง</h2>
            </div>
            <Icon name="layers" size={18} className="subtle-icon" />
          </div>
          <p className="panel-body-copy">
            ระบบตรวจสอบสถานะ API และ Native Model จาก Endpoint จริง
            หากตรวจสอบไม่สำเร็จจะแสดงข้อผิดพลาดแทนการรายงานว่าสำเร็จ
            ส่วนโมดูลเตรียมชุดข้อมูลและการฝึกโมเดล
            ยังไม่มี Endpoint สำหรับตรวจสอบหรือสั่งงานผ่านหน้าแพลตฟอร์ม
          </p>
          <Link className="text-link" href="/training">
            สำรวจพื้นที่ทำงานสำหรับการฝึกอบรม
            <Icon name="arrow-right" size={15} />
          </Link>
        </Panel>
      </section>
    </div>
  );
}
