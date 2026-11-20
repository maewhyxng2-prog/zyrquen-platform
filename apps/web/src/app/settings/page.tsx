"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { Icon } from "@/components/Icon";
import { StatusBadge } from "@/components/StatusBadge";
import { conversationStorageKey, readSession } from "@/lib/api";
import type { Session } from "@/lib/types";

export default function SettingsPage() {
  const router = useRouter();
  const [cleared, setCleared] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [sessionReady, setSessionReady] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState("");

  useEffect(() => {
    const refreshSession = () => {
      readSession()
        .then((current) => {
          setSession(current);
          setSessionReady(true);
        })
        .catch(() => {
          setSession({
            authenticated: false,
            email: null,
            error: "ไม่สามารถตรวจสอบสถานะเซสชันปัจจุบันได้",
          });
          setSessionReady(true);
        });
    };
    refreshSession();
    window.addEventListener("zyrquen:session-change", refreshSession);
    return () => window.removeEventListener("zyrquen:session-change", refreshSession);
  }, []);

  useEffect(() => {
    if (sessionReady && !session?.authenticated) {
      router.replace("/login");
    }
  }, [sessionReady, session, router]);

  function clearConversationHistory() {
    const key = conversationStorageKey(session);
    if (!key) {
      return;
    }
    window.localStorage.removeItem(key);
    window.dispatchEvent(new Event("zyrquen:conversations-cleared"));
    setCleared(true);
  }

  async function signOut() {
    setSigningOut(true);
    setSignOutError("");
    try {
      const response = await fetch("/api/logout", { method: "POST" });
      const payload = (await response.json().catch(() => null)) as {
        detail?: unknown;
      } | null;
      setSession({ authenticated: false, email: null, verified: true });
      window.dispatchEvent(new Event("zyrquen:session-change"));

      if (!response.ok) {
        const message =
          typeof payload?.detail === "string"
            ? payload.detail
            : "ไม่สามารถเพิกถอนเซสชันกับ Backend ได้ กรุณาลองใหม่อีกครั้ง";
        throw new Error(message);
      }

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

  if (!sessionReady || !session?.authenticated) {
    return (
      <div className="page-stack">
        <PageHeader
          description="ตรวจสอบข้อมูลบัญชี จัดการการตั้งค่าที่เปิดให้ใช้งาน และดูรายละเอียดการเชื่อมต่อ API ฝั่งเซิร์ฟเวอร์"
          eyebrow="แพลตฟอร์ม / การตั้งค่า"
          icon="settings"
          title="การตั้งค่า"
        />
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
                  : "จำเป็นต้องเข้าสู่ระบบเพื่อเข้าถึงการตั้งค่าบัญชี"}
            </strong>
            <p>
              {!sessionReady
                ? "ระบบกำลังยืนยันตัวตนกับบริการ ZYRQUEN API เพื่อปกป้องข้อมูลบัญชีของคุณ"
                : session?.error ||
                  "กรุณาเข้าสู่ระบบด้วยบัญชีของคุณก่อนจัดการการตั้งค่าและประวัติการสนทนา"}
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
            <code>{session.email || "เข้าสู่ระบบแล้ว"}</code>
            <p>ตรวจสอบข้อมูลบัญชีของคุณ จัดการการตั้งค่าที่เปิดให้ใช้งาน และออกจากระบบเมื่อใช้งานเสร็จสิ้น</p>
          </div>
          <button className="button button-secondary" disabled={signingOut} onClick={() => void signOut()} type="button">
            <Icon name="logout" size={16} /> {signingOut ? "กำลังออกจากระบบ..." : "ออกจากระบบ"}
          </button>
          {signOutError && <p className="form-alert form-alert-error" role="alert"><Icon name="close" size={15} /> {signOutError}</p>}
        </Panel>
        <Panel>
          <div className="panel-heading"><div><div className="eyebrow">ข้อมูลเฉพาะบัญชีในเครื่อง</div><h2>ประวัติการสนทนา</h2></div><span className="metric-icon"><Icon name="history" /></span></div>
          <div className="settings-info">
            <span>ตำแหน่งจัดเก็บ</span><code>เบราว์เซอร์นี้ · แยกตามบัญชี ({session.email})</code>
            <p>ข้อความและคำตอบของบทสนทนาจะถูกแยกจัดเก็บตามบัญชีผู้ใช้ในเบราว์เซอร์นี้ และไม่ปะปนกับบัญชีอื่นบนอุปกรณ์เดียวกัน</p>
          </div>
          <button className="button button-danger" onClick={clearConversationHistory} type="button"><Icon name="close" size={16} /> ล้างประวัติการสนทนาของบัญชีนี้</button>
          {cleared && <p className="settings-confirmation" role="status"><Icon name="check-circle" size={15} /> ล้างประวัติการสนทนาของบัญชีนี้เรียบร้อยแล้ว</p>}
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
