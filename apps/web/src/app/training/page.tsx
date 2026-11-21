import { CapabilityRadarChart } from "@/components/CapabilityRadarChart";
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
        <StatusBadge tone="info">มีโค้ดหลักในระบบ · ยังไม่เปิดผ่าน API</StatusBadge>
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
        description="แสดงโมดูลการเตรียมชุดข้อมูลและการฝึกโมเดล (Phase 3.3–3.4) ที่มีอยู่ใน Repository พร้อมแผนภาพความสามารถของรุ่นปัจจุบันจาก Backend โดยไม่สร้างข้อมูลจำลองการรันที่ไม่มีอยู่จริง"
        eyebrow="NATIVE AI / เครื่องมือจัดการ NATIVE MODEL"
        icon="layers"
        title="พื้นที่ทำงานสำหรับการฝึกอบรม"
      />

      <Panel className="training-banner">
        <div className="training-banner-icon"><Icon name="file-check" size={21} /></div>
        <div>
          <StatusBadge tone="good">มีโมดูลต้นฉบับในระบบ</StatusBadge>
          <h2>ไปป์ไลน์เตรียมชุดข้อมูลและการฝึกโมเดล</h2>
          <p>โค้ดหลักพร้อมใช้งานในรูปแบบโมดูล Python แต่แอปพลิเคชัน API ปัจจุบันยังไม่ได้เปิดเส้นทางสำหรับจัดการชุดข้อมูล สั่งฝึกโมเดล ดูค่าชี้วัด หรือดูประวัติงานผ่านหน้าเว็บ</p>
        </div>
      </Panel>

      <CapabilityRadarChart />

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

      <section className="future-grid" aria-label="ส่วนงานในแผนพัฒนา">
        <Panel className="future-card">
          <div className="future-title"><Icon name="layers" size={17} /><span>การจัดการ Checkpoint</span></div>
          <StatusBadge tone="neutral">อยู่ในแผนพัฒนา · ยังไม่เชื่อมต่อ API</StatusBadge>
          <p>ยังไม่มี Endpoint สำหรับจัดการ Checkpoint ให้หน้าเว็บเรียกใช้งานได้</p>
        </Panel>
        <Panel className="future-card">
          <div className="future-title"><Icon name="history" size={17} /><span>การจัดการเวอร์ชันโมเดล</span></div>
          <StatusBadge tone="neutral">อยู่ในแผนพัฒนา · ยังไม่เชื่อมต่อ API</StatusBadge>
          <p>ยังไม่สามารถแสดงรายการหรือตรวจสอบประวัติเวอร์ชันโมเดลผ่านเส้นทาง API ปัจจุบันได้</p>
        </Panel>
        <Panel className="future-card">
          <div className="future-title"><Icon name="check-circle" size={17} /><span>ระบบประเมินผลโมเดล</span></div>
          <StatusBadge tone="neutral">อยู่ในแผนพัฒนา · ยังไม่เชื่อมต่อ API</StatusBadge>
          <p>ยังไม่มีการเปิดเผยคะแนนประเมินและรายงานผลการตรวจสอบผ่าน API</p>
        </Panel>
      </section>
      <p className="footnote"><Icon name="help" size={14} /> การปิดบังข้อมูลส่วนบุคคล (PII) ในชุดข้อมูลทำงานแบบจับคู่รูปแบบข้อความ โมดูลหลักไม่ได้รับรองการปกป้องความเป็นส่วนตัวแบบสมบูรณ์</p>
    </div>
  );
}
