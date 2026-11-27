"use client";

import {
  FormEvent,
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Icon, type IconName } from "@/components/Icon";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { usePlatformHealth } from "@/hooks/usePlatformHealth";
import { readSession } from "@/lib/api";
import { listConversations } from "@/lib/conversation-api";
import { filterAndGroupConversations } from "@/lib/conversation-groups";
import type { Conversation, Session } from "@/lib/types";

const quickStarters = [
  {
    title: "วิเคราะห์สถาปัตยกรรมและวางแผนระบบ",
    prompt: "ช่วยวิเคราะห์และวางแนวทางแก้ไขปัญหาทางเทคนิค",
    summary: "จัดลำดับปัญหา แยกสมมติฐาน และวางแผนดำเนินการเป็นขั้นตอน",
    icon: "layers" as IconName,
  },
  {
    title: "สำรวจความสามารถของ Native Model",
    prompt: "สรุปความสามารถของ Native Model ในระบบปัจจุบัน",
    summary: "ตรวจสอบขอบเขตการทำงานของโมเดลหลักและความพร้อมรันไทม์จริง",
    icon: "cpu" as IconName,
  },
  {
    title: "ทำความเข้าใจการฝึกและชุดข้อมูล",
    prompt: "อธิบายขั้นตอนการทำงานของไปป์ไลน์การฝึกโมเดล",
    summary: "ทบทวนกระบวนการเตรียมชุดข้อมูล 4-Split และการประเมินผล",
    icon: "book" as IconName,
  },
];

const coreCapabilities = [
  {
    key: "reasoning",
    title: "Reasoning & Analysis",
    detail: "วิเคราะห์ปัญหาเชิงโครงสร้าง ตรวจสอบตรรกะ และแยกสมมติฐานอย่างเป็นระบบ",
    prompt: "ช่วยวิเคราะห์ปัญหาทางตรรกะและโครงสร้างระบบแบบเป็นขั้นตอน",
    icon: "sparkles" as IconName,
  },
  {
    key: "planning",
    title: "Planning & Verification",
    detail: "วางแผนดำเนินการและตรวจสอบความถูกต้องด้วย Approval & Validation Gates",
    prompt: "ช่วยวางแผนการทำงานและเกณฑ์ตรวจสอบความถูกต้องสำหรับโปรเจกต์",
    icon: "check-circle" as IconName,
  },
  {
    key: "knowledge",
    title: "Knowledge & Context",
    detail: "เชื่อมโยงความรู้จากชุดข้อมูล 4-Split และตรวจจับความขัดแย้งก่อนตอบ",
    prompt: "อธิบายหลักการจัดโครงสร้างความรู้และการตรวจสอบข้อมูลของ ZYRQUEN",
    icon: "book" as IconName,
  },
  {
    key: "evaluation",
    title: "Scientific Evaluation",
    detail: "ประเมิน Generalization บนชุดข้อมูล Unseen และ OOD อย่างโปร่งใส",
    prompt: "อธิบายเกณฑ์วัดผล Generalization และ Zero-Regression ของ Native Model",
    icon: "gauge" as IconName,
  },
];

export default function HomePage() {
  const router = useRouter();
  const {
    apiHealth,
    nativeHealth,
    apiError,
    nativeError,
    loading: healthLoading,
    lastChecked,
    refresh,
  } = usePlatformHealth();

  const [session, setSession] = useState<Session | null>(null);
  const [sessionReady, setSessionReady] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationsLoading, setConversationsLoading] = useState(false);
  const [conversationsError, setConversationsError] = useState("");
  const [recentSearch, setRecentSearch] = useState("");
  const [homePrompt, setHomePrompt] = useState("");
  const [trackedUserId, setTrackedUserId] = useState<string | null>(null);
  const [resendingVerification, setResendingVerification] = useState(false);
  const [verificationNotice, setVerificationNotice] = useState("");
  const [verificationError, setVerificationError] = useState("");

  const targetUserId =
    sessionReady && session?.authenticated ? (session.userId ?? null) : null;

  if (targetUserId !== trackedUserId) {
    setTrackedUserId(targetUserId);
    setConversations([]);
    setConversationsError("");
    setRecentSearch("");
    setConversationsLoading(Boolean(targetUserId));
    setVerificationNotice("");
    setVerificationError("");
  }

  const groupedConversations = useMemo(
    () => filterAndGroupConversations(conversations, recentSearch),
    [conversations, recentSearch],
  );

  const syncSession = useCallback(() => {
    readSession()
      .then((current) => {
        setSession(current);
        setSessionReady(true);
      })
      .catch(() => {
        setSession(null);
        setSessionReady(true);
      });
  }, []);

  useEffect(() => {
    let active = true;
    const handleSync = () => {
      readSession()
        .then((current) => {
          if (!active) return;
          setSession(current);
          setSessionReady(true);
        })
        .catch(() => {
          if (!active) return;
          setSession(null);
          setSessionReady(true);
        });
    };
    handleSync();
    window.addEventListener("zyrquen:session-change", handleSync);
    return () => {
      active = false;
      window.removeEventListener("zyrquen:session-change", handleSync);
    };
  }, []);

  async function resendEmailVerification() {
    if (resendingVerification) return;
    setResendingVerification(true);
    setVerificationNotice("");
    setVerificationError("");
    try {
      const response = await fetch("/api/backend/auth/verification/resend", {
        method: "POST",
      });
      const payload = (await response.json().catch(() => null)) as {
        alreadyVerified?: boolean;
        emailSent?: boolean;
        detail?: string;
        verification?: { emailSent?: boolean; deliveryReason?: string | null };
      } | null;
      if (!response.ok) {
        setVerificationError(
          typeof payload?.detail === "string"
            ? payload.detail
            : "ไม่สามารถส่งลิงก์ยืนยันอีเมลได้ในขณะนี้",
        );
        return;
      }
      if (payload?.alreadyVerified) {
        setVerificationNotice("อีเมลของคุณได้รับการยืนยันแล้ว");
        syncSession();
        return;
      }
      const sent = Boolean(payload?.emailSent ?? payload?.verification?.emailSent);
      if (sent) {
        setVerificationNotice("ส่งลิงก์ยืนยันอีเมลแล้ว กรุณาตรวจสอบกล่องจดหมายของคุณ");
      } else {
        setVerificationNotice(
          typeof payload?.detail === "string"
            ? payload.detail
            : "ระบบยังไม่ได้ตั้งค่าผู้ให้บริการส่งอีเมล (RESEND_API_KEY / EMAIL_FROM)",
        );
      }
    } catch {
      setVerificationError("ไม่สามารถติดต่อบริการส่งลิงก์ยืนยันอีเมลได้");
    } finally {
      setResendingVerification(false);
    }
  }

  useEffect(() => {
    let active = true;
    if (!targetUserId) {
      return () => {
        active = false;
      };
    }

    listConversations(targetUserId)
      .then((items) => {
        if (!active) return;
        setConversations(items);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setConversations([]);
        setConversationsError(
          reason instanceof Error
            ? reason.message
            : "ไม่สามารถโหลดประวัติบทสนทนาล่าสุดได้",
        );
      })
      .finally(() => {
        if (active) setConversationsLoading(false);
      });

    return () => {
      active = false;
    };
  }, [targetUserId]);

  function launchWorkspace(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const trimmed = homePrompt.trim();
    if (trimmed) {
      router.push(`/workspace?prompt=${encodeURIComponent(trimmed)}`);
      return;
    }
    router.push("/workspace");
  }

  function onPromptKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      launchWorkspace();
    }
  }

  const runtimeReady = Boolean(nativeHealth?.inference_available);
  const serviceReady = apiHealth?.status === "healthy";
  const measuredCapabilities = (nativeHealth?.capabilities ?? []).filter(
    (item) => item.status === "measured",
  );
  const versionText =
    nativeHealth?.platform_version || nativeHealth?.model_version || null;

  const availabilityLabel =
    healthLoading && !nativeHealth
      ? "กำลังตรวจสอบระบบ"
      : runtimeReady && serviceReady
        ? "Native AI พร้อมใช้งาน"
        : nativeError || apiError
          ? "ตรวจสอบความพร้อมบางส่วนไม่สำเร็จ"
          : serviceReady
            ? "เชื่อมต่อแล้ว · รอความพร้อม Native Model"
            : "กำลังรอสถานะระบบ";

  const availabilityTone =
    healthLoading && !nativeHealth
      ? ("neutral" as const)
      : runtimeReady && serviceReady
        ? ("good" as const)
        : ("warn" as const);

  return (
    <div className="page-stack home-app-stack">
      {sessionReady && session?.authenticated && session.emailVerified === false && (
        <Panel
          aria-label="Verify Email status notice"
          className="notice-panel"
          role="status"
        >
          <span className="notice-icon">
            <Icon name="shield" size={18} />
          </span>
          <div style={{ flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
              <StatusBadge icon="activity" tone="warn">
                Verify Email
              </StatusBadge>
              <strong>บัญชีของคุณ ({session.email}) ยังไม่ได้ยืนยันอีเมล</strong>
            </div>
            <p>
              กรุณาตรวจสอบกล่องจดหมายและคลิกลิงก์ยืนยันอีเมลเพื่อยืนยันความเป็นเจ้าของบัญชี
              {verificationNotice ? ` · ${verificationNotice}` : ""}
            </p>
            {verificationError && (
              <p className="form-alert form-alert-error" role="alert">
                {verificationError}
              </p>
            )}
            <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", marginTop: "8px" }}>
              <button
                className="button button-secondary"
                disabled={resendingVerification}
                onClick={() => void resendEmailVerification()}
                type="button"
              >
                <Icon name="send" size={14} />
                <span>
                  {resendingVerification ? "กำลังส่ง..." : "ส่งลิงก์ยืนยันอีเมลอีกครั้ง"}
                </span>
              </button>
              <Link className="button button-secondary" href="/settings">
                <Icon name="settings" size={14} />
                <span>จัดการบัญชี</span>
              </Link>
            </div>
          </div>
        </Panel>
      )}
      <section aria-label="จุดเริ่มต้นใช้งาน ZYRQUEN Ω∞" className="home-launcher panel">
        <div className="home-launcher-top">
          <div className="home-identity">
            <span className="home-eyebrow">
              <Icon name="sparkles" size={14} />
              <span>ZYRQUEN Ω∞ · NATIVE AI APPLICATION</span>
            </span>
            <h1>ยินดีต้อนรับสู่ ZYRQUEN Ω∞</h1>
            <p className="home-lead">
              {session?.authenticated
                ? `สวัสดี ${session.email || "ผู้ใช้งาน"} — พร้อมเริ่มต้นสนทนา วิเคราะห์ และวางแผนงานร่วมกับ Native Model ของคุณ`
                : "ผู้ช่วยปัญญาประดิษฐ์สถาปัตยกรรม Native Core สำหรับการสนทนา การให้เหตุผล และการวางแผนเชิงโครงสร้าง"}
            </p>
          </div>

          <Link
            aria-label="ตรวจสอบสถานะความพร้อมระบบ"
            className="home-availability-pill"
            href="/system"
          >
            <StatusBadge icon="cpu" tone={availabilityTone}>
              {availabilityLabel}
            </StatusBadge>
            <span className="home-availability-meta tabular-nums">
              {versionText ? `${versionText} · ` : ""}
              {lastChecked
                ? `อัปเดต ${lastChecked.toLocaleTimeString("th-TH", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}`
                : "ดูรายละเอียดระบบ"}
            </span>
          </Link>
        </div>

        <form className="home-prompt-box" onSubmit={launchWorkspace}>
          <label className="sr-only" htmlFor="home-ai-prompt">
            พิมพ์คำถามหรือคำสั่งเพื่อเริ่มต้นสนทนาในพื้นที่ทำงาน AI
          </label>
          <textarea
            id="home-ai-prompt"
            maxLength={4096}
            onChange={(event) => setHomePrompt(event.target.value)}
            onKeyDown={onPromptKeyDown}
            placeholder="พิมพ์คำถาม วิเคราะห์โค้ด หรือวางแผนงานกับ ZYRQUEN Ω∞..."
            rows={2}
            value={homePrompt}
          />
          <div className="home-prompt-actions">
            <div className="home-prompt-secondary">
              <button
                className="home-refresh-link"
                disabled={healthLoading}
                onClick={() => {
                  void refresh();
                  syncSession();
                }}
                type="button"
              >
                <Icon name="activity" size={14} />
                <span>{healthLoading ? "กำลังตรวจ..." : "อัปเดตสถานะ"}</span>
              </button>
              {!session?.authenticated && sessionReady && (
                <Link className="text-link" href="/login">
                  เข้าสู่ระบบ
                  <Icon name="arrow-up-right" size={14} />
                </Link>
              )}
            </div>

            <div className="home-prompt-primary">
              <Link className="button button-secondary" href="/workspace">
                <Icon name="message" size={15} />
                <span>เปิดพื้นที่ทำงาน AI</span>
              </Link>
              <button className="button button-primary" type="submit">
                <Icon name="send" size={15} />
                <span>{homePrompt.trim() ? "ส่งไปยังพื้นที่ทำงาน" : "เริ่มสนทนา"}</span>
              </button>
            </div>
          </div>
        </form>

        <div className="home-starter-row" aria-label="คำสั่งแนะนำเริ่มต้น">
          {quickStarters.map((starter) => (
            <Link
              className="home-starter-card"
              href={`/workspace?prompt=${encodeURIComponent(starter.prompt)}`}
              key={starter.title}
            >
              <span className="home-starter-icon">
                <Icon name={starter.icon} size={16} />
              </span>
              <span className="home-starter-card-copy">
                <strong>{starter.title}</strong>
                <small>{starter.summary}</small>
              </span>
              <Icon name="arrow-up-right" size={16} />
            </Link>
          ))}
        </div>
      </section>

      <div className="home-two-col">
        <Panel className="home-section-panel">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">RECENT CONVERSATIONS</div>
              <h2>บทสนทนาล่าสุด</h2>
            </div>
            <Link className="text-link" href="/workspace">
              ทั้งหมด
              <Icon name="arrow-right" size={14} />
            </Link>
          </div>

          {!sessionReady || conversationsLoading ? (
            <div className="home-empty-box" role="status">
              <Icon name="history" size={18} />
              <span>กำลังโหลดบทสนทนาล่าสุด...</span>
            </div>
          ) : !session?.authenticated ? (
            <div className="home-empty-box">
              <Icon name="lock" size={18} />
              <div>
                <strong>เข้าสู่ระบบเพื่อซิงก์บทสนทนา</strong>
                <p>ประวัติการสนทนาจะถูกบันทึกแยกตามบัญชีเพื่อให้เปิดต่อได้ทันทีทุกอุปกรณ์</p>
              </div>
              <Link className="button button-secondary" href="/login">
                เข้าสู่ระบบ
              </Link>
            </div>
          ) : conversationsError ? (
            <div className="home-empty-box" role="alert">
              <Icon name="close" size={18} />
              <span>{conversationsError}</span>
            </div>
          ) : conversations.length === 0 ? (
            <div className="home-empty-box">
              <Icon name="message" size={18} />
              <div>
                <strong>ยังไม่มีประวัติการสนทนา</strong>
                <p>พิมพ์คำสั่งด้านบนหรือเปิดพื้นที่ทำงาน AI เพื่อเริ่มบทสนทนาแรกของคุณ</p>
              </div>
              <Link className="button button-primary" href="/workspace">
                เริ่มบทสนทนาใหม่
              </Link>
            </div>
          ) : (
            <div className="home-recent-container">
              <div className="home-recent-search">
                <label className="sr-only" htmlFor="home-conversation-search">
                  ค้นหาประวัติบทสนทนา
                </label>
                <Icon name="search" size={14} />
                <input
                  aria-label="ค้นหาประวัติบทสนทนา"
                  id="home-conversation-search"
                  onChange={(event) => setRecentSearch(event.target.value)}
                  placeholder={`ค้นหาจาก ${conversations.length} บทสนทนา...`}
                  type="search"
                  value={recentSearch}
                />
                {recentSearch && (
                  <button
                    aria-label="ล้างคำค้นหาบทสนทนา"
                    className="home-recent-search-clear"
                    onClick={() => setRecentSearch("")}
                    type="button"
                  >
                    <Icon name="close" size={13} />
                  </button>
                )}
              </div>

              {groupedConversations.length === 0 ? (
                <div className="home-empty-box">
                  <Icon name="search" size={18} />
                  <div>
                    <strong>ไม่พบบทสนทนาที่ตรงกับ &ldquo;{recentSearch.trim()}&rdquo;</strong>
                    <p>ลองใช้คำค้นอื่น หรือล้างตัวกรองเพื่อดูรายการทั้งหมดตามช่วงเวลา</p>
                  </div>
                  <button
                    className="button button-secondary"
                    onClick={() => setRecentSearch("")}
                    type="button"
                  >
                    ล้างคำค้นหา
                  </button>
                </div>
              ) : (
                <div className="home-recent-groups" aria-label="บทสนทนาแยกตามวันที่">
                  {groupedConversations.map((group) => (
                    <div className="home-recent-group" key={group.key}>
                      <div className="home-recent-group-label">
                        <span>{group.label}</span>
                        <span className="tabular-nums">{group.items.length}</span>
                      </div>
                      <div className="home-recent-list">
                        {group.items.map((conversation) => (
                          <Link
                            className="home-recent-item"
                            href={`/workspace?conversation=${encodeURIComponent(conversation.id)}`}
                            key={conversation.id}
                          >
                            <span className="home-recent-icon">
                              <Icon name="message" size={16} />
                            </span>
                            <span className="home-recent-copy">
                              <strong>{conversation.title}</strong>
                              <small className="tabular-nums">
                                {conversation.messageCount} ข้อความ ·{" "}
                                {new Date(conversation.updatedAt).toLocaleString("th-TH", {
                                  dateStyle: "short",
                                  timeStyle: "short",
                                })}
                              </small>
                            </span>
                            <Icon name="chevron-right" size={16} />
                          </Link>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </Panel>

        <Panel className="home-section-panel">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">AVAILABLE CAPABILITIES</div>
              <h2>ความสามารถที่พร้อมใช้งาน</h2>
            </div>
            <Link className="text-link" href="/capabilities">
              รายละเอียด
              <Icon name="arrow-right" size={14} />
            </Link>
          </div>

          <div className="home-capabilities-list">
            {coreCapabilities.map((cap) => {
              const matched = measuredCapabilities.find((item) =>
                item.key.toLowerCase().includes(cap.key),
              );
              return (
                <Link
                  className="home-capability-row"
                  href={`/workspace?prompt=${encodeURIComponent(cap.prompt)}`}
                  key={cap.key}
                >
                  <span className="home-capability-icon">
                    <Icon name={cap.icon} size={16} />
                  </span>
                  <span className="home-capability-copy">
                    <strong>{cap.title}</strong>
                    <small>{cap.detail}</small>
                  </span>
                  {matched && matched.score !== null ? (
                    <span className="home-capability-score tabular-nums">
                      {matched.score.toFixed(1)}%
                    </span>
                  ) : (
                    <Icon name="arrow-up-right" size={15} />
                  )}
                </Link>
              );
            })}
          </div>

          <div className="home-capability-footer">
            <span className="home-runtime-meta">
              {nativeHealth?.progress_metrics?.evaluation_status === "evaluated"
                ? `ผลประเมินล่าสุด: Generalization ${
                    nativeHealth.progress_metrics.generalization_score?.toFixed(1) ?? "—"
                  }%`
                : "ความสามารถทุกด้านทำงานบนสถาปัตยกรรม Native Core โดยไม่สร้างคะแนนจำลอง"}
            </span>
            <Link className="text-link" href="/knowledge">
              คลังความรู้และข้อมูล
              <Icon name="arrow-right" size={14} />
            </Link>
          </div>
        </Panel>
      </div>
    </div>
  );
}
