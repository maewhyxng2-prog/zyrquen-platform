"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { Icon } from "@/components/Icon";
import { StatusBadge } from "@/components/StatusBadge";
import { readSession } from "@/lib/api";
import {
  deleteConversation,
  listConversations,
} from "@/lib/conversation-api";
import { getMyProfile, updateMyProfile } from "@/lib/user-api";
import { belongsToAccount } from "@/lib/user-state";
import type {
  AuthProvidersResponse,
  OAuthIdentity,
  Session,
} from "@/lib/types";

export default function SettingsPage() {
  const router = useRouter();
  const [cleared, setCleared] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [clearError, setClearError] = useState("");
  const [session, setSession] = useState<Session | null>(null);
  const sessionRef = useRef<Session | null>(null);
  const [sessionReady, setSessionReady] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState("");
  const [profileEmail, setProfileEmail] = useState("");
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileOwnerId, setProfileOwnerId] = useState<string | null>(null);
  const [profileSavingUserId, setProfileSavingUserId] = useState<string | null>(null);
  const profileSavingRef = useRef<string | null>(null);
  const [profileError, setProfileError] = useState("");
  const [profileSuccess, setProfileSuccess] = useState("");
  const [identities, setIdentities] = useState<OAuthIdentity[]>([]);
  const [providers, setProviders] = useState<AuthProvidersResponse["providers"] | null>(null);
  const [oauthNotice, setOauthNotice] = useState("");
  const [oauthError, setOauthError] = useState("");
  const [oauthBusy, setOauthBusy] = useState<string | null>(null);
  const [resendingVerify, setResendingVerify] = useState(false);
  const [verifyNotice, setVerifyNotice] = useState("");

  useEffect(() => {
    let active = true;
    const refreshSession = () => {
      readSession()
        .then((current) => {
          if (!active) return;
          sessionRef.current = current;
          setSession(current);
          setSessionReady(true);
        })
        .catch(() => {
          if (!active) return;
          const unavailableSession: Session = {
            authenticated: false,
            email: null,
            userId: null,
            role: null,
            verified: false,
            emailVerified: false,
            error: "ไม่สามารถตรวจสอบสถานะเซสชันปัจจุบันได้",
          };
          sessionRef.current = unavailableSession;
          setSession(unavailableSession);
          setSessionReady(true);
        });
    };
    refreshSession();
    window.addEventListener("zyrquen:session-change", refreshSession);
    return () => {
      active = false;
      window.removeEventListener("zyrquen:session-change", refreshSession);
    };
  }, []);

  useEffect(() => {
    if (sessionReady && !session?.authenticated) {
      router.replace("/login");
    }
  }, [sessionReady, session, router]);

  useEffect(() => {
    if (!sessionReady || !session?.authenticated) {
      return;
    }
    const ownerId = session.userId;
    if (!ownerId) return;
    let active = true;
    const isCurrentOwner = () =>
      active && sessionRef.current?.userId === ownerId;

    void getMyProfile(ownerId)
      .then((nextProfile) => {
        if (!isCurrentOwner()) return;
        setProfileEmail(nextProfile.email);
        setProfileError("");
        setProfileSuccess("");
      })
      .catch((reason: unknown) => {
        if (!isCurrentOwner()) return;
        setProfileEmail("");
        setProfileSuccess("");
        setProfileError(
          reason instanceof Error
            ? reason.message
            : "ไม่สามารถโหลดข้อมูลโปรไฟล์ได้",
        );
      })
      .finally(() => {
        if (!isCurrentOwner()) return;
        setProfileOwnerId(ownerId);
        setProfileLoading(false);
      });

    void Promise.all([
      fetch("/api/backend/auth/providers", { cache: "no-store" }).then((r) =>
        r.ok ? r.json() : null,
      ),
      fetch("/api/backend/auth/identities", { cache: "no-store" }).then((r) =>
        r.ok ? r.json() : null,
      ),
    ])
      .then(
        ([provData, idData]: [
          AuthProvidersResponse | null,
          { identities?: OAuthIdentity[] } | null,
        ]) => {
          if (!isCurrentOwner()) return;
          if (provData?.providers) setProviders(provData.providers);
          if (Array.isArray(idData?.identities)) setIdentities(idData.identities);
        },
      )
      .catch(() => {
        // non-fatal
      });

    return () => {
      active = false;
    };
  }, [sessionReady, session?.authenticated, session?.userId]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const linked = params.get("oauth_linked")?.trim();
    const err = params.get("oauth_error")?.trim();
    if (!linked && !err) return;
    if (linked) {
      setOauthNotice(
        `เชื่อมต่อบัญชี ${linked === "github" ? "GitHub" : "Google"} เรียบร้อยแล้ว`,
      );
      params.delete("oauth_linked");
    }
    if (err) {
      setOauthError(err);
      params.delete("oauth_error");
    }
    const nextSearch = params.toString();
    window.history.replaceState(
      {},
      "",
      `${window.location.pathname}${nextSearch ? `?${nextSearch}` : ""}`,
    );
  }, []);

  async function clearConversationHistory() {
    setClearing(true);
    setClearError("");
    setCleared(false);
    try {
      const ownerId = session?.userId;
      if (!ownerId) throw new Error("ไม่พบรหัสบัญชีที่ยืนยันตัวตนแล้ว");
      const conversations = await listConversations(ownerId);
      const verifiedSession = await readSession();
      if (!verifiedSession.authenticated || verifiedSession.userId !== ownerId) {
        throw new Error("บัญชีผู้ใช้เปลี่ยนระหว่างล้างประวัติ");
      }
      for (const conversation of conversations) {
        const currentSession = await readSession();
        if (!currentSession.authenticated || currentSession.userId !== ownerId) {
          throw new Error("บัญชีผู้ใช้เปลี่ยนระหว่างล้างประวัติ");
        }
        await deleteConversation(conversation.id, ownerId);
      }
      const finalSession = await readSession();
      if (!finalSession.authenticated || finalSession.userId !== ownerId) {
        throw new Error("บัญชีผู้ใช้เปลี่ยนระหว่างล้างประวัติ");
      }
      window.dispatchEvent(new Event("zyrquen:conversations-cleared"));
      setCleared(true);
    } catch (reason) {
      setClearError(
        reason instanceof Error
          ? reason.message
          : "ล้างประวัติการสนทนาไม่สำเร็จ",
      );
    } finally {
      setClearing(false);
    }
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ownerId = session?.userId;
    if (!ownerId || sessionRef.current?.userId !== ownerId) {
      setProfileError("ไม่สามารถยืนยันบัญชีผู้ใช้ปัจจุบันได้");
      return;
    }
    if (profileSavingRef.current === ownerId) return;
    const email = profileEmail.trim().toLowerCase();
    if (!email || email.length > 320) {
      setProfileError("กรุณากรอกอีเมลที่ถูกต้อง");
      return;
    }
    profileSavingRef.current = ownerId;
    setProfileSavingUserId(ownerId);
    setProfileError("");
    setProfileSuccess("");
    try {
      const nextProfile = await updateMyProfile(email, ownerId);
      if (sessionRef.current?.userId !== ownerId) return;
      setProfileEmail(nextProfile.email);
      const nextSession = { ...sessionRef.current, email: nextProfile.email };
      sessionRef.current = nextSession;
      setSession(nextSession);
      window.dispatchEvent(new Event("zyrquen:session-change"));
      setProfileSuccess("บันทึกข้อมูลบัญชีเรียบร้อยแล้ว");
    } catch (reason) {
      if (sessionRef.current?.userId !== ownerId) return;
      setProfileError(
        reason instanceof Error ? reason.message : "ไม่สามารถบันทึกข้อมูลบัญชีได้",
      );
    } finally {
      if (profileSavingRef.current === ownerId) {
        profileSavingRef.current = null;
        setProfileSavingUserId(null);
      }
    }
  }

  async function signOut() {
    setSigningOut(true);
    setSignOutError("");
    try {
      const response = await fetch("/api/logout", { method: "POST" });
      const payload = (await response.json().catch(() => null)) as {
        detail?: unknown;
      } | null;
      const signedOutSession: Session = {
        authenticated: false,
        email: null,
        userId: null,
        role: null,
        verified: false,
        emailVerified: false,
      };
      sessionRef.current = signedOutSession;
      setSession(signedOutSession);
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

  async function linkOAuthAccount(provider: "github" | "google") {
    if (oauthBusy) return;
    setOauthBusy(provider);
    setOauthError("");
    setOauthNotice("");
    try {
      const origin =
        typeof window !== "undefined" ? window.location.origin : "";
      const resp = await fetch(
        `/api/backend/auth/oauth/${provider}/url?intent=link&origin=${encodeURIComponent(origin)}`,
        { cache: "no-store" },
      );
      const data = (await resp.json().catch(() => null)) as {
        url?: string;
        detail?: string;
      } | null;
      if (!resp.ok || !data?.url) {
        setOauthError(
          data?.detail ||
            `ไม่สามารถเริ่มเชื่อมต่อบัญชี ${provider === "github" ? "GitHub" : "Google"} ได้`,
        );
        return;
      }
      window.location.assign(data.url);
    } catch {
      setOauthError("ไม่สามารถเชื่อมต่อบริการ OAuth ได้");
    } finally {
      setOauthBusy(null);
    }
  }

  async function unlinkOAuthAccount(provider: "github" | "google") {
    if (oauthBusy) return;
    setOauthBusy(provider);
    setOauthError("");
    setOauthNotice("");
    try {
      const resp = await fetch(`/api/backend/auth/identities/${provider}`, {
        method: "DELETE",
      });
      const data = (await resp.json().catch(() => null)) as {
        detail?: string;
      } | null;
      if (!resp.ok) {
        setOauthError(data?.detail || "ไม่สามารถยกเลิกการเชื่อมต่อบัญชีได้");
        return;
      }
      setIdentities((prev) => prev.filter((item) => item.provider !== provider));
      setOauthNotice(
        `ยกเลิกการเชื่อมต่อบัญชี ${provider === "github" ? "GitHub" : "Google"} แล้ว`,
      );
    } catch {
      setOauthError("ไม่สามารถยกเลิกการเชื่อมต่อบัญชีได้");
    } finally {
      setOauthBusy(null);
    }
  }

  async function resendVerification() {
    if (resendingVerify) return;
    setResendingVerify(true);
    setVerifyNotice("");
    try {
      const resp = await fetch("/api/backend/auth/verification/resend", {
        method: "POST",
      });
      const data = (await resp.json().catch(() => null)) as {
        emailSent?: boolean;
        detail?: string;
      } | null;
      if (!resp.ok) {
        setVerifyNotice(data?.detail || "ไม่สามารถส่งลิงก์ยืนยันอีเมลได้");
        return;
      }
      setVerifyNotice(
        data?.emailSent
          ? "ส่งลิงก์ยืนยันอีเมลแล้ว กรุณาตรวจสอบกล่องจดหมายของคุณ"
          : data?.detail || "ระบบยังไม่ได้ตั้งค่าผู้ให้บริการส่งอีเมล",
      );
    } catch {
      setVerifyNotice("ไม่สามารถติดต่อบริการส่งอีเมลยืนยันได้");
    } finally {
      setResendingVerify(false);
    }
  }

  if (!sessionReady || !session?.authenticated) {
    return (
      <div className="page-stack">
        <PageHeader
          description="จัดการข้อมูลบัญชีผู้ใช้ การตั้งค่าพื้นที่ทำงาน และประวัติการสนทนาส่วนตัว"
          eyebrow="ACCOUNT / การตั้งค่า"
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
                ? "กำลังตรวจสอบเซสชัน..."
                : session?.expired
                  ? "เซสชันหมดอายุแล้ว"
                  : "จำเป็นต้องเข้าสู่ระบบเพื่อเข้าถึงการตั้งค่าบัญชี"}
            </strong>
            <p>
              {!sessionReady
                ? "ระบบกำลังยืนยันตัวตนเพื่อปกป้องข้อมูลบัญชีของคุณ"
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

  const profileIsLoading =
    profileLoading || !belongsToAccount(profileOwnerId, session.userId);
  const profileSaving = profileSavingUserId === session.userId;
  const isAdmin = session.role === "admin";

  return (
    <div className="page-stack">
      <PageHeader
        description="จัดการข้อมูลบัญชีผู้ใช้ การเข้าถึงเซสชัน และความเป็นส่วนตัวของประวัติการสนทนา"
        eyebrow="ACCOUNT / การตั้งค่า"
        icon="settings"
        title="การตั้งค่า"
      />
      <div className="settings-grid">
        <Panel>
          <div className="panel-heading">
            <div>
              <div className="eyebrow">บัญชีผู้ใช้</div>
              <h2>โปรไฟล์และเซสชัน</h2>
            </div>
            <StatusBadge tone={isAdmin ? "info" : "good"}>
              {isAdmin ? "ผู้ดูแลระบบ" : "ผู้ใช้งาน"}
            </StatusBadge>
          </div>
          <div className="settings-info">
            <span>บัญชีที่ใช้งานอยู่</span>
            <code>{session.email || "เข้าสู่ระบบแล้ว"}</code>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap", marginTop: "6px" }}>
              <StatusBadge tone={session.emailVerified ? "good" : "warn"}>
                {session.emailVerified ? "ยืนยันอีเมลแล้ว" : "Verify Email · ยังไม่ยืนยันอีเมล"}
              </StatusBadge>
              {!session.emailVerified && (
                <button
                  className="button button-secondary"
                  disabled={resendingVerify}
                  onClick={() => void resendVerification()}
                  type="button"
                >
                  {resendingVerify ? "กำลังส่ง..." : "ส่งลิงก์ยืนยันอีเมล"}
                </button>
              )}
            </div>
            {verifyNotice && (
              <p className="settings-confirmation" role="status">
                {verifyNotice}
              </p>
            )}
            <p>อัปเดตอีเมลประจำบัญชี หรือออกจากระบบบนอุปกรณ์ปัจจุบัน</p>
          </div>
          {!session.userId ? (
            <p className="form-alert form-alert-error" role="alert">
              ข้อมูลเซสชันไม่มีรหัสบัญชีที่ยืนยันแล้ว
            </p>
          ) : profileIsLoading ? (
            <p className="settings-confirmation" role="status">
              กำลังโหลดข้อมูลโปรไฟล์...
            </p>
          ) : (
            <form className="settings-form" onSubmit={saveProfile}>
              <div className="settings-field">
                <label htmlFor="profile-email">อีเมลบัญชี</label>
                <input
                  className="settings-input"
                  id="profile-email"
                  type="email"
                  value={profileEmail}
                  maxLength={320}
                  disabled={profileSaving}
                  onChange={(event) => setProfileEmail(event.target.value)}
                  required
                />
              </div>
              <button
                className="button button-primary"
                disabled={profileSaving || !profileEmail.trim()}
                type="submit"
              >
                {profileSaving ? "กำลังบันทึก..." : "บันทึกอีเมล"}
              </button>
            </form>
          )}
          {belongsToAccount(profileOwnerId, session.userId) && profileSuccess && (
            <p className="settings-confirmation" role="status">
              <Icon name="check-circle" size={15} /> {profileSuccess}
            </p>
          )}
          {belongsToAccount(profileOwnerId, session.userId) && profileError && (
            <p className="form-alert form-alert-error" role="alert">
              <Icon name="close" size={15} /> {profileError}
            </p>
          )}
          <button
            className="button button-secondary"
            disabled={signingOut}
            onClick={() => void signOut()}
            type="button"
          >
            <Icon name="logout" size={16} />{" "}
            {signingOut ? "กำลังออกจากระบบ..." : "ออกจากระบบ"}
          </button>
          {signOutError && (
            <p className="form-alert form-alert-error" role="alert">
              <Icon name="close" size={15} /> {signOutError}
            </p>
          )}
        </Panel>

        <Panel>
          <div className="panel-heading">
            <div>
              <div className="eyebrow">ความเป็นส่วนตัวและข้อมูล</div>
              <h2>ประวัติการสนทนาในพื้นที่ทำงาน AI</h2>
            </div>
            <span className="metric-icon">
              <Icon name="history" />
            </span>
          </div>
          <div className="settings-info">
            <span>ขอบเขตการจัดเก็บ</span>
            <code>แยกเฉพาะบัญชี ({session.email})</code>
            <p>
              บทสนทนาและข้อความทั้งหมดถูกจัดเก็บแยกตามบัญชีผู้ใช้บนเซิร์ฟเวอร์
              และโทเค็นยืนยันตัวตนถูกเก็บในคุกกี้ฝั่งเซิร์ฟเวอร์แบบ HTTP-only
            </p>
          </div>
          <button
            className="button button-danger"
            disabled={clearing}
            onClick={() => void clearConversationHistory()}
            type="button"
          >
            <Icon name="trash" size={16} />{" "}
            {clearing ? "กำลังล้างประวัติ..." : "ล้างประวัติการสนทนาของบัญชีนี้"}
          </button>
          {cleared && (
            <p className="settings-confirmation" role="status">
              <Icon name="check-circle" size={15} /> ล้างประวัติการสนทนาของบัญชีนี้เรียบร้อยแล้ว
            </p>
          )}
          {clearError && (
            <p className="form-alert form-alert-error" role="alert">
              <Icon name="close" size={15} /> {clearError}
            </p>
          )}
        </Panel>

        <Panel className="settings-panel-wide">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">OAUTH 2.0 ACCOUNT LINKING</div>
              <h2>บัญชีที่เชื่อมต่อ (GitHub &amp; Google)</h2>
            </div>
            <StatusBadge tone="info">{identities.length} เชื่อมต่อ</StatusBadge>
          </div>
          <div className="admin-list">
            {(["github", "google"] as const).map((provider) => {
              const linked = identities.find((item) => item.provider === provider);
              const configured = providers ? providers[provider].configured : false;
              const label = provider === "github" ? "GitHub" : "Google";
              return (
                <div className="admin-list-row" key={provider}>
                  <div className="admin-list-main">
                    <strong>{label} OAuth 2.0</strong>
                    <span className="admin-list-meta">
                      {linked
                        ? `เชื่อมต่อแล้ว (${linked.provider_email || linked.display_name || linked.provider_user_id})`
                        : configured
                          ? "พร้อมเชื่อมต่อกับบัญชี ZYRQUEN"
                          : "ยังไม่ได้ตั้งค่า OAuth Credentials ใน Backend"}
                    </span>
                  </div>
                  <div className="workflow-actions">
                    {linked ? (
                      <button
                        className="button button-secondary"
                        disabled={oauthBusy !== null}
                        onClick={() => void unlinkOAuthAccount(provider)}
                        type="button"
                      >
                        {oauthBusy === provider ? "กำลังดำเนินการ..." : "ยกเลิกการเชื่อมต่อ"}
                      </button>
                    ) : (
                      <button
                        className="button button-secondary"
                        disabled={oauthBusy !== null}
                        onClick={() => void linkOAuthAccount(provider)}
                        type="button"
                      >
                        {oauthBusy === provider ? "กำลังเชื่อมต่อ..." : `เชื่อมต่อ ${label}`}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          {oauthNotice && (
            <p className="settings-confirmation" role="status">
              <Icon name="check-circle" size={15} /> {oauthNotice}
            </p>
          )}
          {oauthError && (
            <p className="form-alert form-alert-error" role="alert">
              <Icon name="close" size={15} /> {oauthError}
            </p>
          )}
        </Panel>

        <Panel className="settings-panel-wide">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">เครื่องมือเพิ่มเติม</div>
              <h2>สถานะระบบและตั้งค่าสำหรับนักพัฒนา</h2>
            </div>
            <span className="metric-icon metric-icon-cyan">
              <Icon name="sliders" />
            </span>
          </div>
          <div className="settings-link-list">
            <Link className="settings-link-row" href="/system">
              <span className="settings-link-icon">
                <Icon name="activity" size={17} />
              </span>
              <span className="settings-link-copy">
                <strong>สถานะระบบ (System Availability)</strong>
                <small>ตรวจสอบความพร้อมของ Native Model และ Closure Audit</small>
              </span>
              <Icon name="chevron-right" size={16} />
            </Link>

            <Link className="settings-link-row" href="/developer">
              <span className="settings-link-icon">
                <Icon name="code" size={17} />
              </span>
              <span className="settings-link-copy">
                <strong>ตั้งค่าสำหรับนักพัฒนา (Developer Settings)</strong>
                <small>จัดการ API Keys, Usage &amp; Quotas, Workflow และ Model Registry</small>
              </span>
              <Icon name="chevron-right" size={16} />
            </Link>

            {isAdmin && (
              <Link className="settings-link-row" href="/admin">
                <span className="settings-link-icon settings-link-icon-violet">
                  <Icon name="shield" size={17} />
                </span>
                <span className="settings-link-copy">
                  <strong>แดชบอร์ดผู้ดูแลระบบ (Admin)</strong>
                  <small>จัดการผู้ใช้ทั้งหมด โควตา และตรวจสอบ Audit Log</small>
                </span>
                <Icon name="chevron-right" size={16} />
              </Link>
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}
