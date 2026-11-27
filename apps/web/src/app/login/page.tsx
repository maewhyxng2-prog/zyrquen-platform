"use client";

import Image from "next/image";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Icon } from "@/components/Icon";
import { StatusBadge } from "@/components/StatusBadge";
import { readSession } from "@/lib/api";
import type { AuthProvidersResponse, Session } from "@/lib/types";

type Mode = "login" | "register";

function formatAuthError(status: number, rawDetail: string): string {
  const detail = rawDetail.trim();
  if (detail === "Email already registered") {
    return "อีเมลนี้ถูกลงทะเบียนไว้แล้ว กรุณาเข้าสู่ระบบหรือใช้อีเมลอื่น";
  }
  if (detail === "Invalid email or password") {
    return "อีเมลหรือรหัสผ่านไม่ถูกต้อง กรุณาตรวจสอบข้อมูลแล้วลองใหม่อีกครั้ง";
  }
  if (detail === "Account disabled") {
    return "บัญชีนี้ถูกระงับการใช้งาน กรุณาติดต่อผู้ดูแลระบบ";
  }
  if (status === 401 && detail.includes("Missing Authorization header")) {
    return "ปลายทางพอร์ตที่เชื่อมต่ออยู่ไม่ใช่บริการยืนยันตัวตนของ ZYRQUEN (รหัสสถานะ 401) กรุณาตรวจสอบค่า ZYRQUEN_API_BASE_URL";
  }
  if (detail) {
    return detail;
  }
  return `คำขอไม่สำเร็จ (รหัสสถานะ ${status}) กรุณาลองใหม่อีกครั้ง`;
}

async function postJson<T extends Record<string, unknown>>(
  path: string,
  values: Record<string, string>,
): Promise<T> {
  const response = await fetch(`/api/backend/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(values),
  });
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const payload =
      data && typeof data === "object" ? (data as Record<string, unknown>) : null;
    const rawDetail =
      payload && typeof payload.detail === "string"
        ? payload.detail
        : payload && typeof payload.error === "string"
          ? payload.error
          : "";
    throw new Error(formatAuthError(response.status, rawDetail));
  }
  if (!data || typeof data !== "object") {
    throw new Error("บริการยืนยันตัวตนส่งข้อมูลตอบกลับไม่ถูกต้อง กรุณาลองใหม่อีกครั้ง");
  }
  return data as T;
}

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [session, setSession] = useState<Session | null>(null);
  const [sessionReady, setSessionReady] = useState(false);
  const [oauthLoading, setOauthLoading] = useState<"github" | "google" | null>(null);
  const [providers, setProviders] = useState<AuthProvidersResponse["providers"] | null>(null);

  const signedIn = Boolean(session?.authenticated && session.userId);

  useEffect(() => {
    let active = true;
    const syncSession = () => {
      readSession()
        .then((current) => {
          if (!active) return;
          setSession(current);
          setSessionReady(true);
          if (!current.authenticated && current.expired) {
            setError("เซสชันเดิมของคุณหมดอายุแล้ว กรุณาเข้าสู่ระบบใหม่อีกครั้ง");
          } else if (!current.authenticated && current.error) {
            setError(current.error);
          }
        })
        .catch(() => {
          if (!active) return;
          setSession({
            authenticated: false,
            email: null,
            userId: null,
            role: null,
            verified: false,
            emailVerified: false,
          });
          setSessionReady(true);
        });
    };

    syncSession();
    window.addEventListener("zyrquen:session-change", syncSession);
    return () => {
      active = false;
      window.removeEventListener("zyrquen:session-change", syncSession);
    };
  }, []);

  useEffect(() => {
    let active = true;
    fetch("/api/backend/auth/providers", { cache: "no-store" })
      .then((resp) => (resp.ok ? resp.json() : null))
      .then((data: AuthProvidersResponse | null) => {
        if (!active || !data?.providers) return;
        setProviders(data.providers);
      })
      .catch(() => {
        // leave provider availability as unknown
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const verifyToken = params.get("verify_token")?.trim();
    const oauthError = params.get("oauth_error")?.trim();

    if (oauthError) {
      setError(oauthError);
      params.delete("oauth_error");
      const nextSearch = params.toString();
      window.history.replaceState(
        {},
        "",
        `${window.location.pathname}${nextSearch ? `?${nextSearch}` : ""}`,
      );
    }

    if (!verifyToken) return;
    let active = true;

    fetch("/api/backend/auth/verify-email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: verifyToken }),
    })
      .then(async (resp) => {
        const data = (await resp.json().catch(() => null)) as {
          ok?: boolean;
          detail?: string;
          error?: string;
        } | null;
        if (!active) return;
        if (!resp.ok) {
          setError(
            data?.detail ||
              data?.error ||
              "ลิงก์ยืนยันอีเมลไม่ถูกต้องหรือหมดอายุแล้ว",
          );
          return;
        }
        setNotice("ยืนยันอีเมลเรียบร้อยแล้ว บัญชีของคุณได้รับการยืนยันแล้ว");
        window.dispatchEvent(new Event("zyrquen:session-change"));
      })
      .catch(() => {
        if (!active) return;
        setError("ไม่สามารถตรวจสอบโทเคนยืนยันอีเมลได้");
      })
      .finally(() => {
        params.delete("verify_token");
        const nextSearch = params.toString();
        window.history.replaceState(
          {},
          "",
          `${window.location.pathname}${nextSearch ? `?${nextSearch}` : ""}`,
        );
      });

    return () => {
      active = false;
    };
  }, []);

  function switchMode(nextMode: Mode) {
    if (submitting || nextMode === mode) {
      return;
    }
    setMode(nextMode);
    setPassword("");
    setError("");
    setNotice("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) {
      return;
    }

    const normalizedEmail = email.trim().toLowerCase();
    if (
      normalizedEmail.length < 5 ||
      normalizedEmail.length > 320 ||
      !normalizedEmail.includes("@")
    ) {
      setError("กรุณากรอกที่อยู่อีเมลให้ถูกต้อง");
      return;
    }

    if (mode === "register" && (password.length < 12 || password.length > 128)) {
      setError("รหัสผ่านสำหรับการสมัครสมาชิกต้องมีความยาว 12–128 ตัวอักษร");
      return;
    }

    if (mode === "login" && (password.length < 1 || password.length > 128)) {
      setError("กรุณากรอกรหัสผ่านของคุณ");
      return;
    }

    setError("");
    setNotice("");
    setSubmitting(true);
    const activeMode = mode;

    try {
      let verificationNotice = "";
      if (activeMode === "register") {
        const regResult = await postJson<{
          verification?: { emailSent?: boolean; deliveryReason?: string | null };
        }>("auth/register", { email: normalizedEmail, password });
        setMode("login");
        verificationNotice = regResult.verification?.emailSent
          ? "สร้างบัญชีเรียบร้อยแล้ว และส่งลิงก์ยืนยันอีเมลไปยังกล่องจดหมายของคุณแล้ว กำลังเข้าสู่ระบบ…"
          : "สร้างบัญชีเรียบร้อยแล้ว (คุณสามารถยืนยันอีเมลได้จากแดชบอร์ดหรือหน้าการตั้งค่า) กำลังเข้าสู่ระบบ…";
        setNotice(verificationNotice);
      }

      try {
        await postJson("auth/login", { email: normalizedEmail, password });
      } catch (reason) {
        if (activeMode === "register") {
          setPassword("");
          setNotice(
            verificationNotice ||
              "สร้างบัญชีเรียบร้อยแล้ว กรุณาเข้าสู่ระบบด้วยอีเมลและรหัสผ่านที่ตั้งไว้",
          );
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

  async function startOAuth(provider: "github" | "google") {
    if (submitting || oauthLoading) return;
    setError("");
    setNotice("");
    setOauthLoading(provider);
    try {
      const originParam =
        typeof window !== "undefined"
          ? `?origin=${encodeURIComponent(window.location.origin)}`
          : "";
      const response = await fetch(
        `/api/backend/auth/oauth/${provider}/url${originParam}`,
        {
          method: "GET",
          cache: "no-store",
        },
      );
      const payload = (await response.json().catch(() => null)) as {
        url?: unknown;
        detail?: unknown;
      } | null;
      if (!response.ok || typeof payload?.url !== "string" || !payload.url) {
        const message =
          typeof payload?.detail === "string" && payload.detail.trim()
            ? payload.detail
            : `ยังไม่ได้ตั้งค่าการเข้าสู่ระบบผ่าน ${provider === "github" ? "GitHub" : "Google"} OAuth 2.0 ใน Backend นี้`;
        setError(message);
        return;
      }
      window.location.assign(payload.url);
    } catch {
      setError(`ไม่สามารถเชื่อมต่อบริการ ${provider === "github" ? "GitHub" : "Google"} OAuth 2.0 ได้`);
    } finally {
      setOauthLoading(null);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-orbit auth-orbit-one" />
      <div className="auth-orbit auth-orbit-two" />
      <section aria-labelledby="auth-title" className="auth-card">
        <div className="auth-card-brand">
          <Image
            alt=""
            className="brand-mark brand-mark-large"
            height={44}
            src="/zyrquen-icon.svg"
            unoptimized
            width={44}
          />
          <div><span className="eyebrow">ZYRQUEN Ω∞</span><strong>แพลตฟอร์ม AI ระหว่างพัฒนา</strong></div>
        </div>
        {sessionReady && signedIn ? (
          <div className="auth-signed-in">
            <StatusBadge tone="good" icon="check-circle">
              เซสชันพร้อมใช้งาน ({session?.role === "admin" ? "admin" : session?.role || "user"})
            </StatusBadge>
            <h1 id="auth-title">คุณเข้าสู่ระบบแล้ว</h1>
            <p>
              บัญชี {session?.email || ""} พร้อมสำหรับเปิดพื้นที่ทำงานและสนทนากับ Native Model
            </p>
            {session?.emailVerified === false && (
              <div className="form-alert" role="status">
                <Icon name="shield" size={16} />
                <span>Verify Email: อีเมลของบัญชียังไม่ได้รับการยืนยัน</span>
              </div>
            )}
            <Link className="button button-primary full-button" href="/workspace">ไปยังพื้นที่ทำงาน AI <Icon name="arrow-right" size={16} /></Link>
          </div>
        ) : (
          <>
            <div className="auth-heading">
              <StatusBadge tone="info" icon="lock">การเข้าถึงที่ปลอดภัย</StatusBadge>
              <h1 id="auth-title">{mode === "login" ? "ยินดีต้อนรับสู่ ZYRQUEN Ω∞" : "สร้างบัญชีผู้ใช้ใหม่"}</h1>
              <p>{mode === "login" ? "เข้าสู่ระบบด้วยบัญชีของคุณเพื่อเปิดพื้นที่ทำงาน AI และเริ่มต้นสนทนา" : "สมัครสมาชิกเพื่อใช้งานพื้นที่ทำงาน AI บันทึกประวัติการสนทนา และเข้าถึงความสามารถของระบบ"}</p>
            </div>
            <div aria-label="ตัวเลือกการจัดการบัญชี" className="auth-tabs" role="tablist">
              <button
                aria-controls="auth-tabpanel"
                aria-selected={mode === "login"}
                className={mode === "login" ? "auth-tab auth-tab-active" : "auth-tab"}
                disabled={submitting}
                id="auth-tab-login"
                onClick={() => switchMode("login")}
                role="tab"
                type="button"
              >
                เข้าสู่ระบบ
              </button>
              <button
                aria-controls="auth-tabpanel"
                aria-selected={mode === "register"}
                className={mode === "register" ? "auth-tab auth-tab-active" : "auth-tab"}
                disabled={submitting}
                id="auth-tab-register"
                onClick={() => switchMode("register")}
                role="tab"
                type="button"
              >
                สมัครสมาชิก
              </button>
            </div>
            <form
              aria-labelledby={mode === "login" ? "auth-tab-login" : "auth-tab-register"}
              className="auth-form"
              id="auth-tabpanel"
              onSubmit={(event) => void submit(event)}
              role="tabpanel"
            >
              <label className="field-label" htmlFor="email">ที่อยู่อีเมล</label>
              <div className="input-wrap">
                <Icon name="user" size={17} />
                <input
                  autoComplete="email"
                  id="email"
                  maxLength={320}
                  minLength={5}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="name@company.com"
                  required
                  type="email"
                  value={email}
                />
              </div>
              <label className="field-label" htmlFor="password">
                รหัสผ่าน <span>{mode === "register" ? "12–128 ตัวอักษร" : ""}</span>
              </label>
              <div className="input-wrap">
                <Icon name="key" size={17} />
                <input
                  autoComplete={mode === "register" ? "new-password" : "current-password"}
                  id="password"
                  maxLength={128}
                  minLength={mode === "register" ? 12 : 1}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder={mode === "register" ? "ตั้งรหัสผ่านใหม่ (12–128 ตัวอักษร)" : "กรอกรหัสผ่านของคุณ"}
                  required
                  type="password"
                  value={password}
                />
              </div>
              {error && <div className="form-alert form-alert-error" role="alert"><Icon name="close" size={16} />{error}</div>}
              {notice && <div className="form-alert form-alert-success" role="status"><Icon name="check-circle" size={16} />{notice}</div>}
              <button className="button button-primary full-button auth-submit" disabled={submitting} type="submit">
                {submitting ? <><span className="spinner" /> กำลังดำเนินการ...</> : <>{mode === "login" ? "เข้าสู่ระบบไปยังพื้นที่ทำงาน" : "สร้างบัญชีผู้ใช้"} <Icon name="arrow-right" size={16} /></>}
              </button>
            </form>
            <div style={{ display: "grid", gap: "10px", marginTop: "14px" }}>
              <button
                className="button button-secondary full-button"
                disabled={submitting || oauthLoading !== null}
                onClick={() => void startOAuth("github")}
                type="button"
              >
                <Icon name="code" size={16} />
                {oauthLoading === "github" ? "กำลังเชื่อมต่อ GitHub..." : "Login with GitHub"}
                {providers && !providers.github.configured ? " (ยังไม่ตั้งค่า)" : ""}
              </button>
              <button
                className="button button-secondary full-button"
                disabled={submitting || oauthLoading !== null}
                onClick={() => void startOAuth("google")}
                type="button"
              >
                <Icon name="user" size={16} />
                {oauthLoading === "google" ? "กำลังเชื่อมต่อ Google..." : "Login with Google"}
                {providers && !providers.google.configured ? " (ยังไม่ตั้งค่า)" : ""}
              </button>
            </div>
            <div className="auth-security-note"><Icon name="shield" size={15} /><span>ข้อมูลการเข้าสู่ระบบจะถูกส่งผ่านพร็อกซีฝั่งเซิร์ฟเวอร์ไปยัง API ที่กำหนดไว้ และจัดเก็บ Token ในคุกกี้แบบ HTTP-only</span></div>
            <Link className="auth-back-link" href="/">กลับสู่หน้าภาพรวมแพลตฟอร์ม</Link>
          </>
        )}
      </section>
      <div className="auth-footer"><span>ZYRQUEN Ω∞</span><span>แพลตฟอร์ม AI ออนไลน์</span></div>
    </div>
  );
}
