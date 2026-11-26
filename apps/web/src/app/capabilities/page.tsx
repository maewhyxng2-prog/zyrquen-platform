"use client";

import Link from "next/link";
import { Icon } from "@/components/Icon";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { usePlatformHealth } from "@/hooks/usePlatformHealth";

const nativeDomains = [
  {
    key: "reasoning",
    title: "Reasoning & Structured Analysis",
    modulePath: "apps/core/intelligence/reasoning.py",
    description:
      "วิเคราะห์ปัญหาเชิงโครงสร้าง ตรวจสอบตรรกะและความสอดคล้องของสมมติฐานภายในสถาปัตยกรรม Native Core โดยไม่พึ่งพาโมเดลภายนอก",
  },
  {
    key: "planning",
    title: "Planning & Verification Gates",
    modulePath: "apps/core/intelligence/planning.py",
    description:
      "จัดทำแผนดำเนินการ แยกขอบเขตงานที่มีความเสี่ยงสูงเข้าสู่ Approval Gate และตรวจสอบความถูกต้องทั้งแบบสถิตและรันไทม์",
  },
  {
    key: "knowledge",
    title: "Knowledge Integration & Context",
    modulePath: "apps/core/intelligence/knowledge.py",
    description:
      "เชื่อมโยงความรู้ที่ตรวจสอบแหล่งที่มาแล้วกับบริบทการสนทนา พร้อมตรวจจับความขัดแย้งก่อนจัดเก็บในหน่วยความจำระบบ",
  },
  {
    key: "evaluation",
    title: "Scientific Generalization & Zero-Regression",
    modulePath: "apps/core/intelligence/capability_evaluation.py",
    description:
      "ทดสอบกับชุดข้อมูล Unseen และ OOD แยกจากชุดฝึกอย่างเด็ดขาด และป้องกันการประกาศผ่านโดยไม่มีหลักฐานการประเมินจริง",
  },
];

export default function CapabilitiesPage() {
  const { nativeHealth, nativeError, loading, refresh } = usePlatformHealth();
  const capabilities = nativeHealth?.capabilities ?? [];
  const progress = nativeHealth?.progress_metrics ?? null;

  return (
    <div className="page-stack">
      <PageHeader
        action={
          <div className="page-header-actions-group">
            <button
              className="button button-secondary"
              disabled={loading}
              onClick={() => void refresh()}
              type="button"
            >
              <Icon name="activity" size={16} />
              {loading ? "กำลังตรวจสอบ..." : "อัปเดตผลประเมิน"}
            </button>
            <Link className="button button-primary" href="/workspace">
              <Icon name="sparkles" size={16} />
              ทดลองใช้ในพื้นที่ทำงาน AI
            </Link>
          </div>
        }
        description="สำรวจความสามารถหลักของสถาปัตยกรรม Native General Intelligence และตัวชี้วัดที่วัดผลจริงจากรันไทม์ ZYRQUEN Ω∞"
        eyebrow="NATIVE AI / ความสามารถของระบบ"
        icon="sparkles"
        title="ความสามารถ AI และผลประเมินตามจริง"
      />

      <section aria-label="สถานะความพร้อมโมเดลหลัก" className="capabilities-summary-grid">
        <Panel className="metric-card">
          <div className="metric-topline">
            <span className="metric-icon metric-icon-cyan">
              <Icon name="cpu" />
            </span>
            <span className="metric-label">NATIVE RUNTIME</span>
          </div>
          <div className="metric-value">
            {loading && !nativeHealth
              ? "กำลังตรวจสอบ"
              : nativeHealth?.inference_available
                ? "พร้อมประมวลผล"
                : "BLOCKED"}
          </div>
          <div className="metric-foot">
            <StatusBadge
              tone={
                nativeHealth?.inference_available
                  ? "good"
                  : nativeError || nativeHealth
                    ? "warn"
                    : "neutral"
              }
            >
              {nativeHealth?.runtime_status?.toUpperCase() ||
                (nativeError ? "BLOCKED" : "รอข้อมูล")}
            </StatusBadge>
            <span className="metric-caption">
              {nativeHealth?.native_model_loaded
                ? "โหลดน้ำหนักโมเดลแล้ว"
                : "ยังไม่ได้โหลดน้ำหนักโมเดล (BLOCKED)"}
            </span>
          </div>
        </Panel>

        <Panel className="metric-card">
          <div className="metric-topline">
            <span className="metric-icon metric-icon-blue">
              <Icon name="layers" />
            </span>
            <span className="metric-label">MODEL VERSION</span>
          </div>
          <div className="metric-value tabular-nums">
            {nativeHealth?.model_version || nativeHealth?.platform_version || "ยังไม่ระบุ"}
          </div>
          <div className="metric-foot">
            <StatusBadge tone={nativeHealth?.is_trained ? "good" : "warn"}>
              {nativeHealth?.is_trained ? "Trained Artifact" : "NOT_VERIFIED / Untrained"}
            </StatusBadge>
            <span className="metric-caption">
              {nativeHealth?.platform_stage || "Native Intelligence Core"}
            </span>
          </div>
        </Panel>

        <Panel className="metric-card">
          <div className="metric-topline">
            <span className="metric-icon metric-icon-violet">
              <Icon name="check-circle" />
            </span>
            <span className="metric-label">EVALUATION EVIDENCE</span>
          </div>
          <div className="metric-value tabular-nums">
            {progress?.evaluation_status === "evaluated"
              ? "VERIFIED (Measured)"
              : "NOT_VERIFIED"}
          </div>
          <div className="metric-foot">
            <StatusBadge
              tone={progress?.evaluation_status === "evaluated" ? "good" : "warn"}
            >
              {progress?.evaluation_status === "evaluated" ? "VERIFIED" : "BLOCKED / NOT RUN"}
            </StatusBadge>
            <span className="metric-caption">
              {progress?.metrics_source || "ไม่มีการสร้างคะแนนจำลอง"}
            </span>
          </div>
        </Panel>
      </section>

      <Panel>
        <div className="panel-heading">
          <div>
            <div className="eyebrow">
              MEASURED CAPABILITY SIGNALS · /v1/native-ai/health
            </div>
            <h2>คะแนนความสามารถแต่ละด้านจากระบบประเมินผล</h2>
          </div>
          <StatusBadge
            tone={
              capabilities.some((item) => item.status === "measured")
                ? "good"
                : "neutral"
            }
          >
            {capabilities.length > 0
              ? `${capabilities.length} ตัวชี้วัด`
              : "รอรายงานความสามารถ"}
          </StatusBadge>
        </div>

        {capabilities.length === 0 ? (
          <div className="unavailable-block">
            <strong>
              {loading && !nativeHealth
                ? "กำลังตรวจสอบรายการความสามารถจากรันไทม์..."
                : nativeError
                  ? "ไม่สามารถเชื่อมต่อข้อมูลความสามารถจาก Backend ได้"
                  : "รันไทม์ยังไม่ได้ส่งรายการคะแนนความสามารถกลับมา"}
            </strong>
            <p>
              {nativeError ||
                "ZYRQUEN รายงานเฉพาะคะแนนความสามารถที่ได้จากการรันชุดประเมินจริงเท่านั้น หากยังไม่มีผลประเมิน ระบบจะไม่สร้างคะแนนจำลองขึ้นแสดง"}
            </p>
          </div>
        ) : (
          <div className="capabilities-metric-grid">
            {capabilities.map((cap) => (
              <div className="capability-score-card" key={cap.key}>
                <div className="capability-score-head">
                  <strong>{cap.label}</strong>
                  <StatusBadge tone={cap.status === "measured" ? "good" : "neutral"}>
                    {cap.status === "measured" ? "วัดผลแล้ว" : "ยังไม่ประเมิน"}
                  </StatusBadge>
                </div>
                <div className="capability-score-value tabular-nums">
                  {cap.score !== null ? `${cap.score.toFixed(1)}%` : "—"}
                </div>
                <div className="capability-score-meta tabular-nums">
                  <span>รหัส: <code>{cap.key}</code></span>
                  {typeof cap.target === "number" && (
                    <span>เป้าหมาย {cap.target.toFixed(1)}%</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <section aria-label="สถาปัตยกรรมความสามารถหลัก" className="capability-grid">
        {nativeDomains.map((domain) => (
          <Panel className="capability-panel" key={domain.key}>
            <div className="capability-top">
              <span className="phase-label">NATIVE CORE MODULE</span>
              <StatusBadge tone="info">IMPLEMENTED · มีโค้ดหลักในระบบ</StatusBadge>
            </div>
            <h2>{domain.title}</h2>
            <p>{domain.description}</p>
            <div className="capability-source">
              <Icon name="terminal" size={14} />
              <code>{domain.modulePath}</code>
            </div>
          </Panel>
        ))}
      </section>

      <Panel className="notice-panel">
        <span className="notice-icon">
          <Icon name="shield" size={18} />
        </span>
        <div>
          <strong>หลักความโปร่งใสของความสามารถ Native AI</strong>
          <p>
            ความสามารถทุกด้านของ ZYRQUEN Ω∞ พัฒนาจากสถาปัตยกรรมโมเดลภายในโดยไม่แอบใช้ LLM ภายนอก
            สามารถดูสถานะการปิดงานสถาปัตยกรรมได้ที่{" "}
            <Link className="text-link" href="/system">
              หน้าสถานะระบบ
            </Link>{" "}
            หรือเปิด{" "}
            <Link className="text-link" href="/developer/console">
              Developer Console
            </Link>{" "}
            เพื่อตรวจสอบ Model Registry และผลเปรียบเทียบเวอร์ชัน
          </p>
        </div>
      </Panel>
    </div>
  );
}
