"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Icon } from "@/components/Icon";
import { StatusBadge } from "@/components/StatusBadge";
import { readSession } from "@/lib/api";

type Mode = "login" | "register";

async function postJson(path: string, values: Record<string, string>) {
  const response = await fetch(`/api/backend/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(values),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      data && typeof data.detail === "string"
        ? data.detail
        : `คำขอไม่สำเร็จ (รหัสสถานะ ${response.status}) กรุณาลองใหม่อีกครั้ง`;
    throw new Error(detail);
  }
  return data;
}

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [signedIn, setSignedIn] = useState(false);

  useEffect(() => {
    readSession().then((session) => setSignedIn(session.authenticated)).catch(() => setSignedIn(false));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    setSubmitting(true);
    try {
      if (mode === "register") {
        await postJson("auth/register", { email, password });
        setMode("login");
        setNotice("สร้างบัญชีเรียบร้อยแล้ว กำลังเข้าสู่ระบบ…");
      }
      try {
        await postJson("auth/login", { email, password });
      } catch (reason) {
        if (mode === "register") {
          setNotice("สร้างบัญชีเรียบร้อยแล้ว กรุณาเข้าสู่ระบบด้วยอีเมลและรหัสผ่านที่ตั้งไว้");
          return;
        }
        throw reason;
      }
      window.dispatchEvent(new Event("zyrquen:session-change"));
      router.replace("/workspace");
      router.refresh();
    } catch (reason) {
      const message =
        reason instanceof Error
          ? reason.message
          : "การยืนยันตัวตนไม่สำเร็จ กรุณาตรวจสอบข้อมูลแล้วลองใหม่อีกครั้ง";
      setError(message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-orbit auth-orbit-one" />
      <div className="auth-orbit auth-orbit-two" />
      <section aria-labelledby="auth-title" className="auth-card">
        <div className="auth-card-brand">
          <span className="brand-mark brand-mark-large">Ω</span>
          <div><span className="eyebrow">ZYRQUEN Ω∞</span><strong>แพลตฟอร์ม AI ออนไลน์</strong></div>
        </div>
        {signedIn ? (
          <div className="auth-signed-in">
            <StatusBadge tone="good" icon="check-circle">เซสชันพร้อมใช้งาน</StatusBadge>
            <h1 id="auth-title">คุณเข้าสู่ระบบแล้ว</h1>
            <p>บัญชีของคุณพร้อมสำหรับเปิดพื้นที่ทำงานและสนทนากับ Native Model</p>
            <Link className="button button-primary full-button" href="/workspace">ไปยังพื้นที่ทำงาน AI <Icon name="arrow-right" size={16} /></Link>
          </div>
        ) : (
          <>
            <div className="auth-heading">
              <StatusBadge tone="info" icon="lock">การเข้าถึงที่ปลอดภัย</StatusBadge>
              <h1 id="auth-title">{mode === "login" ? "ยินดีต้อนรับสู่ ZYRQUEN Ω∞" : "สร้างบัญชีผู้ใช้ใหม่"}</h1>
              <p>{mode === "login" ? "เข้าสู่ระบบด้วยบัญชีของคุณเพื่อเปิดพื้นที่ทำงานและเริ่มต้นสนทนา" : "สมัครสมาชิกเพื่อเข้าถึงการใช้งานพื้นที่สนทนาและ API ของระบบ"}</p>
            </div>
            <div aria-label="ตัวเลือกการจัดการบัญชี" className="auth-tabs" role="tablist">
              <button aria-selected={mode === "login"} className={mode === "login" ? "auth-tab auth-tab-active" : "auth-tab"} onClick={() => { setMode("login"); setError(""); setNotice(""); }} role="tab" type="button">เข้าสู่ระบบ</button>
              <button aria-selected={mode === "register"} className={mode === "register" ? "auth-tab auth-tab-active" : "auth-tab"} onClick={() => { setMode("register"); setError(""); setNotice(""); }} role="tab" type="button">สมัครสมาชิก</button>
            </div>
            <form className="auth-form" onSubmit={(event) => void submit(event)}>
              <label className="field-label" htmlFor="email">ที่อยู่อีเมล</label>
              <div className="input-wrap"><Icon name="user" size={17} /><input autoComplete="email" id="email" maxLength={320} minLength={5} onChange={(event) => setEmail(event.target.value)} placeholder="name@company.com" required type="email" value={email} /></div>
              <label className="field-label" htmlFor="password">รหัสผ่าน <span>{mode === "register" ? "12–128 ตัวอักษร" : ""}</span></label>
              <div className="input-wrap"><Icon name="key" size={17} /><input autoComplete={mode === "register" ? "new-password" : "current-password"} id="password" maxLength={128} minLength={mode === "register" ? 12 : 1} onChange={(event) => setPassword(event.target.value)} placeholder="กรอกรหัสผ่านของคุณ" required type="password" value={password} /></div>
              {error && <div className="form-alert form-alert-error" role="alert"><Icon name="close" size={16} />{error}</div>}
              {notice && <div className="form-alert form-alert-success" role="status"><Icon name="check-circle" size={16} />{notice}</div>}
              <button className="button button-primary full-button auth-submit" disabled={submitting} type="submit">
                {submitting ? <><span className="spinner" /> กำลังดำเนินการ...</> : <>{mode === "login" ? "เข้าสู่ระบบไปยังพื้นที่ทำงาน" : "สร้างบัญชีผู้ใช้"} <Icon name="arrow-right" size={16} /></>}
              </button>
            </form>
            <div className="auth-security-note"><Icon name="shield" size={15} /><span>ข้อมูลการเข้าสู่ระบบจะถูกส่งผ่านพร็อกซีฝั่งเซิร์ฟเวอร์ไปยัง API ที่กำหนดไว้ และจัดเก็บ Token ในคุกกี้แบบ HTTP-only</span></div>
            <Link className="auth-back-link" href="/">กลับสู่หน้าภาพรวมแพลตฟอร์ม</Link>
          </>
        )}
      </section>
      <div className="auth-footer"><span>ZYRQUEN Ω∞</span><span>แพลตฟอร์ม AI ออนไลน์</span></div>
    </div>
  );
}
