"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { Icon } from "@/components/Icon";
import { StatusBadge } from "@/components/StatusBadge";
import { readSession } from "@/lib/api";
import type { Session } from "@/lib/types";

const CONVERSATIONS_KEY = "zyrquen.local-conversations.v1";

export default function SettingsPage() {
  const router = useRouter();
  const [cleared, setCleared] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [signingOut, setSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState("");

  useEffect(() => {
    readSession().then(setSession).catch(() => setSession(null));
    const refreshSession = () => {
      readSession().then(setSession).catch(() => setSession(null));
    };
    window.addEventListener("zyrquen:session-change", refreshSession);
    return () => window.removeEventListener("zyrquen:session-change", refreshSession);
  }, []);

  function clearConversationHistory() {
    window.localStorage.removeItem(CONVERSATIONS_KEY);
    window.dispatchEvent(new Event("zyrquen:conversations-cleared"));
    setCleared(true);
  }

  async function signOut() {
    setSigningOut(true);
    setSignOutError("");
    try {
      const response = await fetch("/api/logout", { method: "POST" });
      if (!response.ok) throw new Error("ไม่สามารถออกจากระบบได้ กรุณาลองใหม่อีกครั้ง");
      setSession({ authenticated: false, email: null });
      window.dispatchEvent(new Event("zyrquen:session-change"));
      router.push("/login");
      router.refresh();
    } catch (reason) {
      setSignOutError(
        reason instanceof Error
          ? reason.message
          : "ไม่สามารถออกจากระบบได้ กรุณาลองใหม่อีกครั้ง",
      );
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <div className="page-stack">
      <PageHeader
        description="ตรวจสอบข้อมูลบัญชี จัดการการตั้งค่าที่เปิดให้ใช้งาน และดูรายละเอียดการเชื่อมต่อ API ฝั่งเซิร์ฟเวอร์"
        eyebrow="แพลตฟอร์ม / การตั้งค่า"
        icon="settings"
        title="การตั้งค่า"
      />
      <div className="settings-grid">
        <Panel>
          <div className="panel-heading"><div><div className="eyebrow">การตั้งค่าบัญชี</div><h2>ข้อมูลบัญชีและเซสชัน</h2></div><span className="metric-icon"><Icon name="user" /></span></div>
          <div className="settings-info">
            <span>สถานะบัญชี</span>
            <code>{session?.authenticated ? session.email || "เข้าสู่ระบบแล้ว" : "ยังไม่ได้เข้าสู่ระบบ"}</code>
            <p>ตรวจสอบข้อมูลบัญชีของคุณ จัดการการตั้งค่าที่เปิดให้ใช้งาน และออกจากระบบเมื่อใช้งานเสร็จสิ้น</p>
          </div>
          {session?.authenticated ? (
            <button className="button button-secondary" disabled={signingOut} onClick={() => void signOut()} type="button">
              <Icon name="logout" size={16} /> {signingOut ? "กำลังออกจากระบบ..." : "ออกจากระบบ"}
            </button>
          ) : (
            <Link className="button button-primary" href="/login">
              <Icon name="lock" size={16} /> เข้าสู่ระบบด้วยบัญชีของคุณ
            </Link>
          )}
          {signOutError && <p className="form-alert form-alert-error" role="alert"><Icon name="close" size={15} /> {signOutError}</p>}
        </Panel>
        <Panel>
          <div className="panel-heading"><div><div className="eyebrow">ข้อมูลในเครื่อง</div><h2>ประวัติการสนทนา</h2></div><span className="metric-icon"><Icon name="history" /></span></div>
          <div className="settings-info">
            <span>ตำแหน่งจัดเก็บ</span><code>เบราว์เซอร์นี้ · localStorage</code>
            <p>ข้อความและคำตอบของบทสนทนาจะถูกบันทึกไว้ในเบราว์เซอร์บนอุปกรณ์นี้เท่านั้น และยังไม่ได้จัดเก็บบนเซิร์ฟเวอร์ประวัติบัญชี</p>
          </div>
          <button className="button button-danger" onClick={clearConversationHistory} type="button"><Icon name="close" size={16} /> ล้างประวัติการสนทนาในเบราว์เซอร์</button>
          {cleared && <p className="settings-confirmation" role="status"><Icon name="check-circle" size={15} /> ล้างประวัติการสนทนาในเบราว์เซอร์เรียบร้อยแล้ว</p>}
        </Panel>
        <Panel>
          <div className="panel-heading"><div><div className="eyebrow">การเชื่อมต่อ API</div><h2>Endpoint ฝั่งเซิร์ฟเวอร์</h2></div><span className="metric-icon metric-icon-blue"><Icon name="server" /></span></div>
          <div className="settings-info">
            <span>ตัวแปรกำหนดค่า</span><code>ZYRQUEN_API_BASE_URL</code>
            <p>กำหนดค่าบนเซิร์ฟเวอร์ Next.js (เช่น <code>http://localhost:8000</code>) คำขอจากเบราว์เซอร์จะส่งผ่านพร็อกซีแบบ same-origin โดยส่งต่อเฉพาะเส้นทางตรวจสอบสถานะ การยืนยันตัวตน และการประมวลผลที่มีอยู่จริง</p>
          </div>
          <div className="security-callout"><Icon name="lock" size={16} /><span>URL ปลายทางเป็นค่ากำหนดฝั่งเซิร์ฟเวอร์ จึงไม่เปิดให้แก้ไขจากฝั่งเบราว์เซอร์</span></div>
        </Panel>
        <Panel>
          <div className="panel-heading"><div><div className="eyebrow">คำแนะนำการใช้งาน</div><h2>การจัดการบัญชีและการตั้งค่า</h2></div><StatusBadge tone="info">เปิดให้ใช้งาน</StatusBadge></div>
          <div className="guidance-list">
            <div className="guidance-group">
              <strong>การตั้งค่าบัญชี</strong>
              <ul>
                <li>ตรวจสอบข้อมูลบัญชีของคุณ</li>
                <li>จัดการการตั้งค่าที่เปิดให้ใช้งาน</li>
                <li>ออกจากระบบเมื่อใช้งานเสร็จสิ้น</li>
              </ul>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
