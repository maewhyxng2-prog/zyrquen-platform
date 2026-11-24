"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Icon } from "@/components/Icon";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { usePlatformHealth } from "@/hooks/usePlatformHealth";
import { readSession } from "@/lib/api";
import type { Session } from "@/lib/types";

const quickStarters = [
  {
    title: "วิเคราะห์สถาปัตยกรรมและวางแผนระบบ",
    prompt: "ช่วยวิเคราะห์และวางแนวทางแก้ไขปัญหาทางเทคนิค",
    summary: "จัดลำดับปัญหา แยกสมมติฐาน และวางแผนดำเนินการเป็นขั้นตอน",
  },
  {
    title: "สำรวจความสามารถของ Native Model",
    prompt: "สรุปความสามารถของ Native Model ในระบบปัจจุบัน",
    summary: "ตรวจสอบขอบเขตการทำงานของโมเดลหลักและความพร้อมรันไทม์จริง",
  },
  {
    title: "ทำความเข้าใจการฝึกและชุดข้อมูล",
    prompt: "อธิบายขั้นตอนการทำงานของไปป์ไลน์การฝึกโมเดล",
    summary: "ทบทวนกระบวนการเตรียมชุดข้อมูล 4-Split และการประเมินผล",
  },
];

type ProgressDatum = {
  metric: string;
  score: number;
  target: number | null;
  fill: string;
};

function subscribeClientMount() {
  return () => {};
}

function ProgressTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: ProgressDatum }>;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const item = payload[0]?.payload;
  if (!item) return null;

  return (
    <div className="radar-tooltip">
      <strong>{item.metric}</strong>
      <div className="radar-tooltip-row">
        <span>คะแนนปัจจุบัน</span>
        <strong>{item.score.toFixed(1)}%</strong>
      </div>
      {item.target !== null && (
        <div className="radar-tooltip-row">
          <span>เป้าหมาย</span>
          <span>{item.target.toFixed(1)}%</span>
        </div>
      )}
    </div>
  );
}

export default function HomePage() {
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
  const chartMounted = useSyncExternalStore(
    subscribeClientMount,
    () => true,
    () => false,
  );

  const syncSession = useCallback(() => {
    readSession()
      .then((current) => setSession(current))
      .catch(() => setSession(null));
  }, []);

  useEffect(() => {
    syncSession();
    window.addEventListener("zyrquen:session-change", syncSession);
    return () => window.removeEventListener("zyrquen:session-change", syncSession);
  }, [syncSession]);

  const runtimeReady = Boolean(nativeHealth?.inference_available);
  const serviceReady = apiHealth?.status === "healthy";

  const runtimeLabel =
    loading && !nativeHealth
      ? "กำลังตรวจสอบรันไทม์"
      : runtimeReady
        ? "Native Model พร้อมประมวลผล"
        : nativeError
          ? "ตรวจสอบรันไทม์ไม่สำเร็จ"
          : "รอความพร้อม Native Model";

  const runtimeTone =
    loading && !nativeHealth
      ? ("neutral" as const)
      : runtimeReady
        ? ("good" as const)
        : ("warn" as const);

  return (
    <div className="page-stack">
      <section aria-label="จุดเริ่มต้นใช้งาน ZYRQUEN Ω∞" className="home-hero panel">
        <div className="home-hero-grid">
          <div className="home-hero-copy">
            <div className="eyebrow">
              <Icon name="sparkles" size={14} />
              <span>NATIVE GENERAL INTELLIGENCE PLATFORM</span>
            </div>
            <h1>ยินดีต้อนรับสู่ ZYRQUEN Ω∞</h1>
            <p className="home-hero-lead">
              แพลตฟอร์มปัญญาประดิษฐ์ที่พัฒนาสถาปัตยกรรม Native Model ขึ้นเอง เพื่อการสนทนา
              การให้เหตุผล การวางแผน และการตรวจสอบผลลัพธ์อย่างโปร่งใส
            </p>
            <div className="home-hero-actions">
              <Link className="button button-primary home-hero-cta" href="/workspace">
                <Icon name="sparkles" size={16} />
                เปิดพื้นที่ทำงาน AI
                <Icon name="arrow-right" size={16} />
              </Link>
              <Link className="button button-secondary" href="/capabilities">
                <Icon name="layers" size={16} />
                สำรวจความสามารถ AI
              </Link>
              {!session?.authenticated && (
                <Link className="text-link" href="/login">
                  เข้าสู่ระบบบัญชีของคุณ
                  <Icon name="arrow-up-right" size={15} />
                </Link>
              )}
            </div>
            <div className="home-runtime-strip">
              <StatusBadge icon="cpu" tone={runtimeTone}>
                {runtimeLabel}
              </StatusBadge>
              <span className="home-runtime-meta">
                {session?.authenticated
                  ? `เข้าสู่ระบบแล้ว · ${session.email || "บัญชีที่ยืนยันตัวตนแล้ว"}`
                  : "พร้อมสำรวจพื้นที่ทำงาน AI และภาพรวมความสามารถของระบบ"}
              </span>
              {lastChecked && (
                <span className="home-runtime-meta tabular-nums">
                  · อัปเดต {lastChecked.toLocaleTimeString("th-TH")}
                </span>
              )}
            </div>
          </div>

          <div className="home-starter-column">
            <div className="home-starter-head">
              <span className="metric-label">เริ่มต้นสนทนาทันที</span>
              <button
                className="home-refresh-link"
                disabled={loading}
                onClick={() => {
                  void refresh();
                  syncSession();
                }}
                type="button"
              >
                <Icon name="activity" size={14} />
                {loading ? "กำลังตรวจ..." : "รีเฟรชสถานะ"}
              </button>
            </div>
            <div className="home-starter-list">
              {quickStarters.map((starter) => (
                <Link
                  className="home-starter-card"
                  href={`/workspace?prompt=${encodeURIComponent(starter.prompt)}`}
                  key={starter.title}
                >
                  <div className="home-starter-card-copy">
                    <strong>{starter.title}</strong>
                    <small>{starter.summary}</small>
                  </div>
                  <Icon name="arrow-up-right" size={16} />
                </Link>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section aria-label="โครงสร้างหลักของแพลตฟอร์ม" className="home-pillars-grid">
        <Panel className="home-pillar-card">
          <div className="metric-topline">
            <span className="metric-icon metric-icon-cyan">
              <Icon name="message" />
            </span>
            <StatusBadge tone={runtimeTone}>{runtimeReady ? "พร้อมสนทนา" : "รอโมเดล"}</StatusBadge>
          </div>
          <h2>พื้นที่ทำงาน AI</h2>
          <p>
            พื้นที่สนทนาหลักสำหรับส่งคำสั่ง รับคำตอบแบบสตรีมมิงจาก Native Model
            ปรับพารามิเตอร์ และจัดการประวัติการสนทนาที่บันทึกแยกตามบัญชีผู้ใช้
          </p>
          <div className="panel-link-row">
            <Link className="text-link" href="/workspace">
              ไปยังพื้นที่ทำงาน AI
              <Icon name="arrow-right" size={15} />
            </Link>
          </div>
        </Panel>

        <Panel className="home-pillar-card">
          <div className="metric-topline">
            <span className="metric-icon metric-icon-blue">
              <Icon name="sparkles" />
            </span>
            <StatusBadge
              tone={
                nativeHealth?.progress_metrics?.evaluation_status === "evaluated"
                  ? "good"
                  : "neutral"
              }
            >
              {nativeHealth?.progress_metrics?.evaluation_status === "evaluated"
                ? "มีผลประเมิน"
                : "ตรวจวัดตามจริง"}
            </StatusBadge>
          </div>
          <h2>ความสามารถของระบบ</h2>
          <p>
            ติดตามความสามารถด้านการให้เหตุผล การวางแผน การตรวจสอบความถูกต้อง
            และผลประเมิน Generalization ที่วัดจากรันไทม์จริงโดยไม่สร้างตัวเลขจำลอง
          </p>
          <div className="panel-link-row">
            <Link className="text-link" href="/capabilities">
              ดูความสามารถระบบ
              <Icon name="arrow-right" size={15} />
            </Link>
          </div>
        </Panel>

        <Panel className="home-pillar-card">
          <div className="metric-topline">
            <span className="metric-icon metric-icon-violet">
              <Icon name="book" />
            </span>
            <StatusBadge tone="info">Data Provenance</StatusBadge>
          </div>
          <h2>คลังความรู้และข้อมูล</h2>
          <p>
            จัดการแหล่งที่มาของชุดข้อมูล ตรวจสอบความครบถ้วนแบบ 4-Split (Train / Validation
            / Unseen / OOD) และการป้องกัน Data Leakage ด้วย SHA-256
          </p>
          <div className="panel-link-row">
            <Link className="text-link" href="/knowledge">
              สำรวจคลังความรู้และข้อมูล
              <Icon name="arrow-right" size={15} />
            </Link>
          </div>
        </Panel>
      </section>

      <section aria-label="การติดตามความคืบหน้า ZYRQUEN Ω∞">
        <Panel className="progress-monitoring-panel">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">
                การติดตามความก้าวหน้า
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
                  ? "ไม่สามารถเชื่อมต่อรันไทม์"
                  : nativeHealth?.progress_metrics?.evaluation_status === "evaluated"
                    ? "มีผลประเมินจริง"
                    : "รอข้อมูลผลประเมินจริง"}
            </StatusBadge>
          </div>

          {(() => {
            const pm = nativeHealth?.progress_metrics ?? null;
            const genScore = pm?.generalization_score ?? null;
            const genTarget =
              typeof pm?.generalization_target === "number"
                ? pm.generalization_target
                : null;
            const relScore = pm?.relational_reasoning_success_rate ?? null;
            const relTarget =
              typeof pm?.relational_reasoning_target === "number"
                ? pm.relational_reasoning_target
                : null;
            const hasAnyMetric = genScore !== null || relScore !== null;

            if (!hasAnyMetric) {
              return (
                <div className="unavailable-block">
                  <strong>
                    {loading && !nativeHealth
                      ? "กำลังตรวจสอบค่า Generalization Score และ Relational Reasoning Success Rate"
                      : nativeError
                        ? "ไม่สามารถดึงตัวชี้วัดจากรันไทม์ได้"
                        : "ยังไม่มีค่าชี้วัดความก้าวหน้าที่ผ่านการประเมินจริง"}
                  </strong>
                  <p>
                    {nativeError ||
                      "ระบบจะแสดงตัวเลขและกราฟความก้าวหน้าเฉพาะเมื่อ Native Model ผ่านการวัดผล Generalization Score และ Relational Reasoning Success Rate จริงเท่านั้น โดยจะไม่แสดงข้อมูลจำลอง"}
                  </p>
                </div>
              );
            }

            const chartData: ProgressDatum[] = [
              ...(genScore !== null
                ? [
                    {
                      metric: "Generalization Score",
                      score: Math.min(100, Math.max(0, genScore)),
                      target: genTarget,
                      fill: "#22d3ee",
                    },
                  ]
                : []),
              ...(relScore !== null
                ? [
                    {
                      metric: "Relational Reasoning",
                      score: Math.min(100, Math.max(0, relScore)),
                      target: relTarget,
                      fill: "#3b82f6",
                    },
                  ]
                : []),
            ];

            const sharedTarget =
              genTarget !== null && relTarget !== null && genTarget === relTarget
                ? genTarget
                : genTarget ?? relTarget;

            return (
              <>
                <div className="progress-metrics-grid">
                  <div className="progress-metric-block">
                    <div className="progress-metric-head">
                      <span className="metric-label">GENERALIZATION SCORE</span>
                      {genTarget !== null && (
                        <span className="progress-target tabular-nums">
                          เป้าหมาย {genTarget.toFixed(1)}%
                        </span>
                      )}
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
                        {genTarget !== null && (
                          <span
                            className="progress-target-marker"
                            style={{
                              left: `${Math.min(100, Math.max(0, genTarget))}%`,
                            }}
                            title={`เป้าหมาย ${genTarget.toFixed(1)}%`}
                          />
                        )}
                      </div>
                    )}
                    <p className="progress-metric-note">
                      {pm?.metrics_source
                        ? `แหล่งข้อมูลผลประเมิน: ${pm.metrics_source}`
                        : "ค่าที่รายงานจากระบบประเมินผล"}
                    </p>
                  </div>

                  <div className="progress-metric-block">
                    <div className="progress-metric-head">
                      <span className="metric-label">
                        RELATIONAL REASONING SUCCESS RATE
                      </span>
                      {relTarget !== null && (
                        <span className="progress-target tabular-nums">
                          เป้าหมาย {relTarget.toFixed(1)}%
                        </span>
                      )}
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
                        {relTarget !== null && (
                          <span
                            className="progress-target-marker"
                            style={{
                              left: `${Math.min(100, Math.max(0, relTarget))}%`,
                            }}
                            title={`เป้าหมาย ${relTarget.toFixed(1)}%`}
                          />
                        )}
                      </div>
                    )}
                    <p className="progress-metric-note">
                      {pm?.metrics_source
                        ? `แหล่งข้อมูลผลประเมิน: ${pm.metrics_source}`
                        : "ค่าที่รายงานจากระบบประเมินผล"}
                    </p>
                  </div>
                </div>

                <div className="progress-chart-box">
                  <div className="progress-chart-head">
                    <span className="metric-label">
                      PROGRESS COMPARISON · NATIVE EVALUATION
                    </span>
                    {sharedTarget !== null && (
                      <span className="progress-target tabular-nums">
                        เส้นอ้างอิงเป้าหมาย {sharedTarget.toFixed(1)}%
                      </span>
                    )}
                  </div>
                  <div
                    className="progress-chart-stage"
                    role="img"
                    aria-label="กราฟเปรียบเทียบค่าตัวชี้วัดความก้าวหน้าจากระบบประเมินผล"
                  >
                    {chartMounted ? (
                      <ResponsiveContainer width="100%" height={176}>
                        <BarChart
                          data={chartData}
                          layout="vertical"
                          margin={{ top: 8, right: 20, left: 8, bottom: 4 }}
                        >
                          <CartesianGrid
                            stroke="#1e2943"
                            strokeDasharray="3 3"
                            horizontal={false}
                          />
                          <XAxis
                            type="number"
                            domain={[0, 100]}
                            stroke="#64748b"
                            tick={{ fill: "#94a3b8", fontSize: 11 }}
                            tickFormatter={(val: number) => `${val}%`}
                            tickLine={false}
                            axisLine={{ stroke: "#1e2943" }}
                          />
                          <YAxis
                            type="category"
                            dataKey="metric"
                            width={150}
                            stroke="#64748b"
                            tick={{ fill: "#eef2fa", fontSize: 12 }}
                            tickLine={false}
                            axisLine={false}
                          />
                          <Tooltip
                            cursor={{ fill: "rgba(59, 130, 246, 0.08)" }}
                            content={<ProgressTooltip />}
                          />
                          {sharedTarget !== null && (
                            <ReferenceLine
                              x={sharedTarget}
                              stroke="#8b5cf6"
                              strokeDasharray="4 4"
                              strokeWidth={2}
                            />
                          )}
                          <Bar
                            dataKey="score"
                            radius={[0, 6, 6, 0]}
                            maxBarSize={28}
                          >
                            {chartData.map((entry) => (
                              <Cell key={entry.metric} fill={entry.fill} />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="settings-usage-skeleton" />
                    )}
                  </div>
                </div>
              </>
            );
          })()}

          <div className="panel-link-row home-panel-links">
            <Link className="text-link" href="/capabilities">
              ตรวจสอบความสามารถและโมเดล
              <Icon name="arrow-right" size={15} />
            </Link>
            <Link className="text-link" href="/system">
              ตรวจสอบสถานะระบบและ Closure Audit
              <Icon name="arrow-right" size={15} />
            </Link>
          </div>
        </Panel>
      </section>

      <section aria-label="สรุปความพร้อมรันไทม์และบัญชี" className="home-status-footer">
        <div className="home-status-item">
          <Icon name="cpu" size={16} />
          <span>
            รันไทม์ Native Model:{" "}
            <strong>{runtimeReady ? "พร้อมประมวลผล" : nativeHealth?.runtime_status || "รอความพร้อม"}</strong>
          </span>
        </div>
        <div className="home-status-item">
          <Icon name="server" size={16} />
          <span>
            บริการหลัก:{" "}
            <strong>{serviceReady ? "ออนไลน์" : apiError ? "ตรวจสอบไม่สำเร็จ" : "กำลังตรวจสอบ"}</strong>
          </span>
        </div>
        <div className="home-status-item">
          <Icon name="shield" size={16} />
          <span>
            บัญชี:{" "}
            <strong>{session?.authenticated ? session.email || "เข้าสู่ระบบแล้ว" : "โหมดผู้เยี่ยมชม"}</strong>
          </span>
        </div>
      </section>
    </div>
  );
}
