import { WorkflowConsole } from "@/components/WorkflowConsole";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { Icon } from "@/components/Icon";

function CapabilityPanel({
  phase,
  title,
  description,
  source,
}: {
  phase: string;
  title: string;
  description: string;
  source: string;
}) {
  return (
    <Panel className="capability-panel">
      <div className="capability-top">
        <span className="phase-label">{phase}</span>
        <StatusBadge tone="info">มีโค้ดหลักในระบบ</StatusBadge>
      </div>
      <h2>{title}</h2>
      <p>{description}</p>
      <div className="capability-source"><Icon name="terminal" size={14} /><code>{source}</code></div>
    </Panel>
  );
}

export default function TrainingPage() {
  return (
    <div className="page-stack">
      <PageHeader
        description="แสดงโมดูลการเตรียมชุดข้อมูล การฝึกโมเดล (Phase 3.3–3.4) และตัวจัดการ Workflow กลาง + Model Registry โดยไม่สร้างข้อมูลจำลอง"
        eyebrow="NATIVE AI / WORKFLOW & MODEL MANAGEMENT"
        icon="layers"
        title="พื้นที่ทำงานสำหรับการฝึกอบรมและ Workflow กลาง"
      />

      <Panel className="training-banner">
        <div className="training-banner-icon"><Icon name="file-check" size={21} /></div>
        <div>
          <StatusBadge tone="good">มีโมดูลต้นฉบับและ Workflow Engine กลาง</StatusBadge>
          <h2>ไปป์ไลน์เตรียมชุดข้อมูล, การฝึกโมเดล และ Central Workflow Orchestrator</h2>
          <p>ควบคุมงาน 8 กลุ่มผ่าน Orchestrator กลางเพียงตัวเดียว พร้อม Resource Guard, Tier-2 Approval Gate, Audit Trail และ Model Registry Lifecycle</p>
        </div>
      </Panel>


      <WorkflowConsole />

      <section className="capability-grid" aria-label="ความสามารถที่พัฒนาไว้ในโค้ดหลัก">
        <CapabilityPanel
          description="นำเข้าไฟล์ JSONL และข้อความ ทำความสะอาดและปรับมาตรฐานเอกสาร ปิดบังข้อมูลส่วนบุคคล (PII) ตามรูปแบบ คัดกรองและตัดข้อมูลซ้ำ แบ่งชุดข้อมูลแบบกำหนดซ้ำได้ และสร้าง Manifest พร้อมตรวจสอบแฮช"
          phase="PHASE 3.3"
          source="apps/core/native/dataset.py"
          title="การเตรียมชุดข้อมูล"
        />
        <CapabilityPanel
          description="สร้างสตรีม Token สุ่มแบตช์แบบกำหนดซ้ำได้ กำหนดตารางอัตราการเรียนรู้แบบ Warmup/Cosine ประเมินผล ตรวจสอบการทำงาน และมีจุดเชื่อมต่อสำหรับบันทึก/กู้คืน Checkpoint"
          phase="PHASE 3.4"
          source="apps/core/native/train.py"
          title="ไปป์ไลน์การฝึกโมเดล"
        />
      </section>

      <div className="eyebrow section-eyebrow">การติดตามสถานะไปป์ไลน์</div>
      <section className="training-data-grid">
        <Panel className="training-data-card">
          <div className="data-card-heading"><span className="metric-icon"><Icon name="database" /></span><span className="metric-label">สถานะชุดข้อมูล</span></div>
          <div className="unavailable-block"><strong>ยังไม่เปิดใช้ผ่าน Web API</strong><p>ยังไม่มี Endpoint สำหรับแสดงรายการ ตรวจสอบความถูกต้อง อัปโหลด หรือดู Manifest ของชุดข้อมูล</p></div>
        </Panel>
        <Panel className="training-data-card">
          <div className="data-card-heading"><span className="metric-icon metric-icon-blue"><Icon name="activity" /></span><span className="metric-label">การทำงานของการฝึกโมเดล</span></div>
          <div className="unavailable-block"><strong>ไม่มีข้อมูลการรันจริง</strong><p>ยังไม่มี Endpoint สำหรับเริ่ม/หยุดงาน ตั้งค่า ดูบันทึกการทำงาน ค่าชี้วัด หรือประวัติการฝึกโมเดล</p></div>
        </Panel>
        <Panel className="training-data-card">
          <div className="data-card-heading"><span className="metric-icon metric-icon-violet"><Icon name="cpu" /></span><span className="metric-label">การใช้ทรัพยากร</span></div>
          <div className="unavailable-block"><strong>ไม่มีรายงานค่า</strong><p>ข้อมูลการใช้งาน GPU และทรัพยากรการประมวลผลยังไม่สามารถเข้าถึงได้ผ่าน API ปัจจุบัน</p></div>
        </Panel>
      </section>

      <section className="future-grid" aria-label="ขอบเขต API และ Runtime">
        <Panel className="future-card">
          <div className="future-title"><Icon name="layers" size={17} /><span>การจัดการ Checkpoint</span></div>
          <StatusBadge tone="neutral">จัดการผ่าน Registry · อัปโหลดไฟล์ยังปิด</StatusBadge>
          <p>ไฟล์ Checkpoint ที่ลงทะเบียนแล้วถูกตรวจ SHA-256 ผ่าน Model Registry โดยไม่อนุญาตให้แก้ไขหรือลบไฟล์เดิมจากหน้าเว็บโดยตรง</p>
        </Panel>
        <Panel className="future-card">
          <div className="future-title"><Icon name="history" size={17} /><span>การจัดการเวอร์ชันโมเดล</span></div>
          <StatusBadge tone="good">เชื่อมต่อ /v1/models/registry*</StatusBadge>
          <p>แสดง Lifecycle, Lineage, Compatibility, Comparison, Staging, Promote และ Rollback ผ่าน Workflow &amp; Registry Console ด้านบน</p>
        </Panel>
        <Panel className="future-card">
          <div className="future-title"><Icon name="check-circle" size={17} /><span>ระบบประเมินผลโมเดล</span></div>
          <StatusBadge tone="warn">ต้องใช้หลักฐานจริงจาก Evaluation</StatusBadge>
          <p>Evaluation Gate จะเปลี่ยนสถานะเป็น Verified หรือ Quarantined จาก Evaluation Report จริงเท่านั้น</p>
        </Panel>
      </section>
      <p className="footnote"><Icon name="help" size={14} /> การปิดบังข้อมูลส่วนบุคคล (PII) ในชุดข้อมูลทำงานแบบจับคู่รูปแบบข้อความ โมดูลหลักไม่ได้รับรองการปกป้องความเป็นส่วนตัวแบบสมบูรณ์</p>
    </div>
  );
}
