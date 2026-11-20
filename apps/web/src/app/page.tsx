"use client";

import Link from "next/link";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { Icon } from "@/components/Icon";
import { usePlatformHealth } from "@/hooks/usePlatformHealth";

function valueForHealth(ok: boolean | null, label: string) {
  if (ok === null) return { text: "ไม่พร้อมใช้งาน", tone: "neutral" as const };
  return ok
    ? { text: label, tone: "good" as const }
    : { text: "ทำงานไม่สมบูรณ์", tone: "warn" as const };
}

export default function DashboardPage() {
  const { apiHealth, nativeHealth, apiError, nativeError, loading, lastChecked, refresh } =
    usePlatformHealth();
  const apiStatus = valueForHealth(apiHealth?.status === "healthy", "พร้อมใช้งาน");
  const nativeStatus = valueForHealth(
    nativeHealth ? nativeHealth.inference_available : null,
    "พร้อมประมวลผล",
  );

  return (
    <div className="page-stack">
      <PageHeader
        action={
          <button className="button button-secondary" onClick={() => void refresh()} type="button">
            <Icon name="activity" size={16} /> รีเฟรชสถานะ
          </button>
        }
        description="แพลตฟอร์ม AI ที่พัฒนาขึ้นเพื่อให้คุณสามารถใช้งานระบบปัญญาประดิษฐ์ผ่านเครือข่ายออนไลน์ได้อย่างสะดวกและเป็นระบบ"
        eyebrow="แพลตฟอร์ม / ภาพรวม"
        icon="gauge"
        title="ยินดีต้อนรับสู่ ZYRQUEN Ω∞"
      />

      <section aria-label="สถานะการทำงาน" className="status-grid">
        <Panel className="metric-card">
          <div className="metric-topline"><span className="metric-icon"><Icon name="server" /></span><span className="metric-label">บริการ API</span></div>
          <div className="metric-value">{loading && !apiHealth ? "กำลังตรวจสอบ" : apiStatus.text}</div>
          <div className="metric-foot">
            <StatusBadge tone={apiStatus.tone}>{apiStatus.text}</StatusBadge>
            <span className="metric-caption">{apiError || apiHealth?.service || "GET /health"}</span>
          </div>
        </Panel>
        <Panel className="metric-card">
          <div className="metric-topline"><span className="metric-icon metric-icon-cyan"><Icon name="cpu" /></span><span className="metric-label">รันไทม์ NATIVE AI</span></div>
          <div className="metric-value">{loading && !nativeHealth ? "กำลังตรวจสอบ" : nativeStatus.text}</div>
          <div className="metric-foot">
            <StatusBadge tone={nativeStatus.tone}>{nativeHealth?.runtime_status || (nativeError ? "ไม่พร้อมใช้งาน" : "กำลังตรวจสอบ")}</StatusBadge>
            <span className="metric-caption">{nativeHealth ? (nativeHealth.native_model_loaded ? "โหลด Native Model แล้ว" : "ยังไม่ได้โหลด Native Model") : "ไม่สามารถตรวจสอบสถานะโมเดลได้"}</span>
          </div>
        </Panel>
        <Panel className="metric-card">
          <div className="metric-topline"><span className="metric-icon metric-icon-blue"><Icon name="database" /></span><span className="metric-label">ไปป์ไลน์ชุดข้อมูล</span></div>
          <div className="metric-value metric-value-small">มีโมดูลหลักในระบบ</div>
          <div className="metric-foot">
            <StatusBadge tone="info">ยังไม่เปิดใช้ผ่าน API</StatusBadge>
            <span className="metric-caption">ไม่มี Endpoint ตรวจสอบสถานะชุดข้อมูล</span>
          </div>
        </Panel>
        <Panel className="metric-card">
          <div className="metric-topline"><span className="metric-icon metric-icon-violet"><Icon name="layers" /></span><span className="metric-label">ไปป์ไลน์การฝึกโมเดล</span></div>
          <div className="metric-value metric-value-small">มีโมดูลหลักในระบบ</div>
          <div className="metric-foot">
            <StatusBadge tone="info">ยังไม่เปิดใช้ผ่าน API</StatusBadge>
            <span className="metric-caption">ไม่มี Endpoint สั่งงานการฝึกโมเดล</span>
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
              <span className="status-dot" /> {lastChecked ? `ตรวจสอบล่าสุด ${lastChecked.toLocaleTimeString("th-TH")}` : "รอการตรวจสอบสถานะ"}
            </span>
          </div>
          <div className="readiness-list">
            <div className="readiness-row">
              <span className="readiness-symbol"><Icon name="server" size={17} /></span>
              <div className="readiness-copy"><strong>บริการ API หลัก (FastAPI)</strong><small>{apiError || "ตรวจสอบสถานะการเชื่อมต่อ API ผ่าน /health"}</small></div>
              <StatusBadge tone={apiStatus.tone}>{apiHealth ? apiStatus.text : "ไม่พร้อมใช้งาน"}</StatusBadge>
            </div>
            <div className="readiness-row">
              <span className="readiness-symbol"><Icon name="cpu" size={17} /></span>
              <div className="readiness-copy"><strong>การประมวลผล Native Model</strong><small>{nativeHealth?.authority || nativeError || "ตรวจสอบความพร้อมของบริการผ่าน /v1/native-ai/health"}</small></div>
              <StatusBadge tone={nativeStatus.tone}>{nativeHealth?.inference_available ? "พร้อมใช้งาน" : nativeHealth ? "ไม่พร้อมใช้งาน" : "ไม่ทราบสถานะ"}</StatusBadge>
            </div>
            <div className="readiness-row">
              <span className="readiness-symbol"><Icon name="shield" size={17} /></span>
              <div className="readiness-copy"><strong>การยืนยันตัวตน</strong><small>เส้นทางเข้าสู่ระบบและสมัครสมาชิกด้วย JWT พร้อมให้บริการ</small></div>
              <StatusBadge tone="info">เปิดให้บริการ</StatusBadge>
            </div>
          </div>
          <div className="panel-link-row">
            <Link className="text-link" href="/system">ดูรายละเอียดสถานะระบบ <Icon name="arrow-right" size={15} /></Link>
          </div>
        </Panel>

        <Panel className="quick-panel">
          <div className="eyebrow">คำแนะนำระบบ</div>
          <h2>เริ่มต้นใช้งาน ZYRQUEN Ω∞</h2>
          <p>ZYRQUEN ประกอบด้วยพื้นที่สนทนา การจัดการบัญชี ประวัติการสนทนา การตั้งค่า และเครื่องมือจัดการ Native Model</p>
          <Link className="button button-primary full-button" href="/workspace">
            <Icon name="sparkles" size={16} /> เปิดพื้นที่ทำงาน AI <Icon name="arrow-right" size={16} />
          </Link>
          <div className="quick-divider" />
          <Link className="quick-link" href="/training"><span className="quick-link-icon"><Icon name="layers" size={16} /></span><span><strong>เครื่องมือจัดการ Native Model</strong><small>ตรวจสอบโมดูลเตรียมชุดข้อมูลและการฝึกอบรม</small></span><Icon name="chevron-right" size={16} /></Link>
        </Panel>
      </section>

      <section className="dashboard-grid dashboard-lower">
        <Panel>
          <div className="panel-heading">
            <div><div className="eyebrow">คำแนะนำการใช้งาน</div><h2>ขั้นตอนการใช้งานระบบ</h2></div>
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
                <li>สร้างบทสนทนาใหม่เมื่อเริ่มหัวข้อใหม่ และตรวจสอบประวัติการสนทนาที่บันทึกไว้</li>
                <li>จัดการบทสนทนาตามความสามารถที่ระบบรองรับ ตรวจสอบข้อมูลบัญชี และออกจากระบบเมื่อใช้งานเสร็จสิ้น</li>
              </ul>
            </div>
          </div>
        </Panel>
        <Panel>
          <div className="panel-heading">
            <div><div className="eyebrow">สถานะระบบและโมดูลหลัก</div><h2>รายงานความพร้อมตามจริง</h2></div>
            <Icon name="layers" size={18} className="subtle-icon" />
          </div>
          <p className="panel-body-copy">ระบบจะตรวจสอบสถานะการเชื่อมต่อ API และความพร้อมของบริการตามจริง หากบริการไม่พร้อมใช้งานจะแสดงข้อความแจ้งเตือนที่เข้าใจง่าย และจะไม่แสดงสถานะว่าสำเร็จหากระบบยังไม่ได้ดำเนินการจริง สำหรับโมดูลเตรียมชุดข้อมูลและการฝึกโมเดลมีอยู่ในโค้ดหลักแต่ยังไม่เปิดใช้งานผ่าน API</p>
          <Link className="text-link" href="/training">สำรวจพื้นที่ทำงานสำหรับการฝึกอบรม <Icon name="arrow-right" size={15} /></Link>
        </Panel>
      </section>
    </div>
  );
}
