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
import type { Session } from "@/lib/types";

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

  useEffect(() => {
    const refreshSession = () => {
      readSession()
        .then((current) => {
          sessionRef.current = current;
          setSession(current);
          setSessionReady(true);
        })
        .catch(() => {
          const unavailableSession = {
            authenticated: false,
            email: null,
            error: "ไม่สามารถตรวจสอบสถานะเซสชันปัจจุบันได้",
          };
          sessionRef.current = unavailableSession;
          setSession(unavailableSession);
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

    return () => {
      active = false;
    };
  }, [sessionReady, session?.authenticated, session?.userId]);

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
      const signedOutSession = {
        authenticated: false,
        email: null,
        verified: true,
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

  if (!sessionReady || !session?.authenticated) {
    return (
      <div className="page-stack">
        <PageHeader
          description="จัดการข้อมูลบัญชีผู้ใช้ การตั้งค่าพื้นที่ทำงาน และประวัติการสนทนาส่วนตัว"
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
                ? "ระบบกำลังยืนยันตัวตนกับบริการ ZYRQUEN เพื่อปกป้องข้อมูลบัญชีของคุณ"
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

  return (
    <div className="page-stack">
      <PageHeader
        description="จัดการข้อมูลบัญชีผู้ใช้ การเข้าถึงเซสชัน และประวัติการสนทนาในพื้นที่ทำงาน AI"
        eyebrow="แพลตฟอร์ม / การตั้งค่า"
        icon="settings"
        title="การตั้งค่า"
      />
      <div className="settings-grid">
        <Panel>
          <div className="panel-heading">
            <div>
              <div className="eyebrow">การตั้งค่าบัญชี</div>
              <h2>ข้อมูลบัญชีและเซสชัน</h2>
            </div>
            <span className="metric-icon">
              <Icon name="user" />
            </span>
          </div>
          <div className="settings-info">
            <span>สถานะบัญชี</span>
            <code>{session.email || "เข้าสู่ระบบแล้ว"}</code>
            <p>อัปเดตอีเมลประจำบัญชี ตรวจสอบสถานะเซสชัน และออกจากระบบเมื่อใช้งานเสร็จสิ้น</p>
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
              <div className="eyebrow">ข้อมูลเฉพาะบัญชี</div>
              <h2>ประวัติการสนทนาในพื้นที่ทำงาน AI</h2>
            </div>
            <span className="metric-icon">
              <Icon name="history" />
            </span>
          </div>
          <div className="settings-info">
            <span>ตำแหน่งจัดเก็บ</span>
            <code>Backend · แยกตามบัญชี ({session.email})</code>
            <p>
              บทสนทนาและข้อความทั้งหมดถูกจัดเก็บบนเซิร์ฟเวอร์โดยผูกกับบัญชีของคุณเท่านั้น
              ไม่ปะปนกับผู้ใช้อื่น
            </p>
          </div>
          <button
            className="button button-danger"
            disabled={clearing}
            onClick={() => void clearConversationHistory()}
            type="button"
          >
            <Icon name="close" size={16} />{" "}
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
              <div className="eyebrow">นักพัฒนาและเครื่องมือขั้นสูง</div>
              <h2>API Management, API Keys, Developer Console และ Usage &amp; Quotas</h2>
            </div>
            <span className="metric-icon metric-icon-cyan">
              <Icon name="code" />
            </span>
          </div>
          <p className="panel-body-copy">
            ฟังก์ชันการจัดการ API Keys, การตรวจสอบปริมาณการใช้งานและโควตา (Usage &amp; Quotas),
            คอนโซลควบคุม Workflow / Model Registry รวมถึงแดชบอร์ดผู้ดูแลระบบ
            ถูกจัดหมวดหมู่แยกไว้ในส่วนนักพัฒนาเพื่อให้หน้าตั้งค่าบัญชีสะอาดและใช้งานง่ายขึ้น
          </p>
          <div className="developer-handoff-grid">
            <Link className="developer-handoff-card" href="/developer">
              <div>
                <strong>API Management</strong>
                <small>Endpoint ฝั่งเซิร์ฟเวอร์และสัญญาการเชื่อมต่อ</small>
              </div>
              <Icon name="arrow-up-right" size={16} />
            </Link>
            <Link className="developer-handoff-card" href="/developer/keys">
              <div>
                <strong>API Keys</strong>
                <small>สร้าง หมุนเวียน และจัดการคีย์เชื่อมต่อ</small>
              </div>
              <Icon name="arrow-up-right" size={16} />
            </Link>
            <Link className="developer-handoff-card" href="/developer/usage">
              <div>
                <strong>Usage &amp; Quotas</strong>
                <small>ติดตามโทเค็นและขีดจำกัดการใช้งาน</small>
              </div>
              <Icon name="arrow-up-right" size={16} />
            </Link>
            <Link className="developer-handoff-card" href="/developer/console">
              <div>
                <strong>Developer Console</strong>
                <small>Workflow Engine และ Training Pipeline</small>
              </div>
              <Icon name="arrow-up-right" size={16} />
            </Link>
          </div>
        </Panel>

        <Panel>
          <div className="panel-heading">
            <div>
              <div className="eyebrow">ผู้ดูแลระบบ</div>
              <h2>แดชบอร์ดผู้ดูแลแพลตฟอร์ม</h2>
            </div>
            <span className="metric-icon metric-icon-violet">
              <Icon name="shield" />
            </span>
          </div>
          <p className="panel-body-copy">
            ข้อมูลภาพรวมผู้ดูแล บัญชีผู้ใช้ และ Audit Log เปิดให้เข้าถึงเฉพาะบัญชีที่มีสิทธิ์ผู้ดูแลจาก Backend
          </p>
          <Link className="button button-secondary" href="/admin">
            เปิดแดชบอร์ดผู้ดูแลระบบ
          </Link>
        </Panel>

        <Panel>
          <div className="panel-heading">
            <div>
              <div className="eyebrow">คำแนะนำการใช้งาน</div>
              <h2>ความเป็นส่วนตัวและความปลอดภัย</h2>
            </div>
            <StatusBadge tone="info">เปิดให้ใช้งาน</StatusBadge>
          </div>
          <div className="guidance-list">
            <div className="guidance-group">
              <strong>การปกป้องบัญชี</strong>
              <ul>
                <li>โทเค็นการเข้าสู่ระบบถูกจัดเก็บในคุกกี้ฝั่งเซิร์ฟเวอร์แบบ HTTP-only</li>
                <li>สามารถอัปเดตอีเมลหรือล้างประวัติการสนทนาเฉพาะบัญชีได้ตลอดเวลา</li>
                <li>ควรออกจากระบบทุกครั้งหลังใช้งานบนอุปกรณ์สาธารณะ</li>
              </ul>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
