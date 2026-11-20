"use client";

import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Icon } from "@/components/Icon";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { usePlatformHealth } from "@/hooks/usePlatformHealth";
import { apiRequest, readSession } from "@/lib/api";
import type { Conversation, ConversationMessage, InferenceResponse, Session } from "@/lib/types";

const STORAGE_KEY = "zyrquen.local-conversations.v1";
const examples = [
  "สรุปความสามารถของ Native Model ในระบบปัจจุบัน",
  "ช่วยวิเคราะห์และวางแนวทางแก้ไขปัญหาทางเทคนิค",
  "อธิบายขั้นตอนการทำงานของไปป์ไลน์การฝึกโมเดล",
];

function isConversation(value: unknown): value is Conversation {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<Conversation>;
  return typeof item.id === "string" && typeof item.title === "string" && Array.isArray(item.messages);
}

export default function WorkspacePage() {
  const router = useRouter();
  const { nativeHealth, nativeError, loading: healthLoading } = usePlatformHealth();
  const [session, setSession] = useState<Session | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [storageReady, setStorageReady] = useState(false);
  const [draft, setDraft] = useState("");
  const [maxTokens, setMaxTokens] = useState(256);
  const [temperature, setTemperature] = useState(0.7);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [mobileHistory, setMobileHistory] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const copyTimerRef = useRef<number | null>(null);
  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeId) ?? null,
    [conversations, activeId],
  );

  useEffect(() => {
    readSession().then(setSession).catch(() => setSession(null));
    const loadTimer = window.setTimeout(() => {
      try {
        const raw = window.localStorage.getItem(STORAGE_KEY);
        if (raw) {
          const parsed: unknown = JSON.parse(raw);
          if (Array.isArray(parsed)) {
            const valid = parsed.filter(isConversation);
            setConversations(valid);
            setActiveId(valid[0]?.id ?? null);
          }
        }
      } catch {
        window.localStorage.removeItem(STORAGE_KEY);
      }
      setStorageReady(true);
    }, 0);
    const clearHistory = () => {
      setConversations([]);
      setActiveId(null);
    };
    window.addEventListener("zyrquen:conversations-cleared", clearHistory);
    return () => {
      window.clearTimeout(loadTimer);
      if (copyTimerRef.current !== null) {
        window.clearTimeout(copyTimerRef.current);
      }
      window.removeEventListener("zyrquen:conversations-cleared", clearHistory);
    };
  }, []);

  useEffect(() => {
    if (storageReady) {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
    }
  }, [conversations, storageReady]);

  useEffect(() => {
    const scroller = scrollRef.current;
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  }, [activeConversation?.messages, sending]);

  async function copyMessageContent(message: ConversationMessage) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(message.content);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = message.content;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        document.body.removeChild(textarea);
      }
      setCopiedMessageId(message.id);
      if (copyTimerRef.current !== null) {
        window.clearTimeout(copyTimerRef.current);
      }
      copyTimerRef.current = window.setTimeout(() => {
        setCopiedMessageId((current) => (current === message.id ? null : current));
      }, 2000);
    } catch {
      setError("ไม่สามารถคัดลอกข้อความลงคลิปบอร์ดได้");
    }
  }

  function createConversation(): Conversation {
    const conversation: Conversation = {
      id: crypto.randomUUID(),
      title: "บทสนทนาใหม่",
      updatedAt: new Date().toISOString(),
      messages: [],
    };
    setConversations((current) => [conversation, ...current]);
    setActiveId(conversation.id);
    setError("");
    setMobileHistory(false);
    return conversation;
  }

  function updateConversation(id: string, update: (current: Conversation) => Conversation) {
    setConversations((current) =>
      current.map((conversation) =>
        conversation.id === id ? update(conversation) : conversation,
      ),
    );
  }

  async function sendPrompt(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const prompt = draft.trim();
    if (!prompt || sending) return;
    if (!session?.authenticated) {
      router.push("/login");
      return;
    }
    if (!nativeHealth?.inference_available) {
      setError(
        nativeHealth
          ? "ไม่สามารถส่งข้อความได้ เนื่องจากรันไทม์ Native Model ยังไม่พร้อมใช้งาน"
          : nativeError || "ไม่สามารถตรวจสอบความพร้อมของ Native Model ได้ในขณะนี้",
      );
      return;
    }

    const conversation = activeConversation ?? createConversation();
    const userMessage: ConversationMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: prompt,
      createdAt: new Date().toISOString(),
    };
    updateConversation(conversation.id, (current) => ({
      ...current,
      title: current.messages.length === 0 ? prompt.slice(0, 48) : current.title,
      updatedAt: userMessage.createdAt,
      messages: [...current.messages, userMessage],
    }));
    setDraft("");
    setSending(true);
    setError("");

    try {
      const response = await apiRequest<InferenceResponse>("v1/native-ai/infer", {
        method: "POST",
        body: JSON.stringify({ prompt, max_tokens: maxTokens, temperature }),
      });
      const assistantMessage: ConversationMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: response.result,
        createdAt: new Date().toISOString(),
      };
      updateConversation(conversation.id, (current) => ({
        ...current,
        updatedAt: assistantMessage.createdAt,
        messages: [...current.messages, assistantMessage],
      }));
    } catch (reason) {
      const message =
        reason instanceof Error
          ? reason.message
          : "ส่งคำขอประมวลผลไม่สำเร็จ กรุณาตรวจสอบสถานะการเชื่อมต่อ API แล้วลองใหม่อีกครั้ง";
      if (reason && typeof reason === "object" && "status" in reason && reason.status === 401) {
        setSession({ authenticated: false, email: null });
        setError("เซสชันของคุณหมดอายุหรือไม่ถูกต้อง กรุณาเข้าสู่ระบบใหม่อีกครั้งเพื่อใช้งานต่อ");
      } else {
        setError(message);
      }
    } finally {
      setSending(false);
    }
  }

  function onComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendPrompt();
    }
  }

  return (
    <div className="page-stack workspace-page">
      <PageHeader
        action={<StatusBadge icon="command" tone={nativeHealth?.inference_available ? "good" : "warn"}>{nativeHealth?.inference_available ? "Native Model พร้อมใช้งาน" : "รันไทม์ไม่พร้อมใช้งาน"}</StatusBadge>}
        description="พื้นที่สนทนาสำหรับพิมพ์ข้อความและรับคำตอบจาก Native Model ผ่าน API ที่ผ่านการยืนยันตัวตน"
        eyebrow="NATIVE AI / พื้นที่ทำงาน"
        icon="sparkles"
        title="พื้นที่ทำงาน AI"
      />
      <div className="chat-layout">
        <aside aria-label="ประวัติการสนทนาในเครื่อง" className={`conversation-sidebar${mobileHistory ? " conversation-sidebar-open" : ""}`}>
          <div className="conversation-sidebar-head">
            <div><span className="eyebrow">บทสนทนา</span><span className="local-only-label">บันทึกเฉพาะในเบราว์เซอร์นี้</span></div>
            <button aria-label="สร้างบทสนทนาใหม่" className="icon-button icon-button-accent" onClick={() => createConversation()} type="button"><Icon name="plus" size={18} /></button>
          </div>
          <button className="button button-secondary new-chat-button" onClick={() => createConversation()} type="button"><Icon name="plus" size={16} /> สร้างบทสนทนาใหม่</button>
          <div className="conversation-list">
            {conversations.length === 0 ? (
              <div className="history-empty"><Icon name="history" size={18} /><span>ยังไม่มีประวัติการสนทนาที่บันทึกไว้</span></div>
            ) : conversations.map((conversation) => (
              <button
                aria-current={activeId === conversation.id ? "page" : undefined}
                className={`conversation-item${activeId === conversation.id ? " conversation-item-active" : ""}`}
                key={conversation.id}
                onClick={() => { setActiveId(conversation.id); setError(""); setMobileHistory(false); }}
                type="button"
              >
                <Icon name="message" size={16} />
                <span><strong>{conversation.title}</strong><small>{conversation.messages.length} ข้อความ</small></span>
              </button>
            ))}
          </div>
          <div className="conversation-sidebar-foot"><Icon name="lock" size={13} /> ประวัติการสนทนาจะถูกเก็บไว้ในเบราว์เซอร์นี้เท่านั้น</div>
        </aside>

        <section aria-label="บทสนทนา" className="conversation-main">
          <div className="conversation-toolbar">
            <button className="mobile-history-button" onClick={() => setMobileHistory((open) => !open)} type="button"><Icon name="history" size={16} /> ประวัติ</button>
            <div className="conversation-title">
              <span className="assistant-avatar"><Icon name="sparkles" size={16} /></span>
              <span><strong>{activeConversation?.title || "บทสนทนาใหม่"}</strong><small>การประมวลผล Native Model ของ ZYRQUEN Ω∞</small></span>
            </div>
            <div className="conversation-runtime">
              <span className={`runtime-dot${nativeHealth?.inference_available ? " runtime-dot-ready" : ""}`} />
              <span>{healthLoading ? "กำลังตรวจสอบ" : nativeHealth?.inference_available ? "พร้อมใช้งาน" : "ไม่พร้อมใช้งาน"}</span>
            </div>
          </div>

          <div className="message-scroll" ref={scrollRef}>
            {!activeConversation?.messages.length ? (
              <div className="chat-empty-state">
                <div className="chat-empty-mark"><Icon name="sparkles" size={24} /></div>
                <StatusBadge tone={nativeHealth?.inference_available ? "good" : "warn"}>{nativeHealth?.inference_available ? "Native Model พร้อมใช้งาน" : "Native Model ไม่พร้อมใช้งาน"}</StatusBadge>
                <h2>เริ่มต้นสนทนากับ ZYRQUEN Ω∞</h2>
                <p>พิมพ์ข้อความลงในช่องสนทนาแล้วส่งข้อความ เพื่อตรวจสอบคำตอบจากระบบในพื้นที่สนทนา (ต้องเข้าสู่ระบบและ Native Model ต้องพร้อมใช้งาน)</p>
                <div className="suggestion-list">
                  {examples.map((example) => <button key={example} onClick={() => setDraft(example)} type="button">{example}<Icon name="arrow-up-right" size={14} /></button>)}
                </div>
              </div>
            ) : (
              <div className="message-list">
                {activeConversation.messages.map((message) => {
                  const isCopied = copiedMessageId === message.id;
                  return (
                    <article className={`message-row message-${message.role}`} key={message.id}>
                      <span className={`message-avatar${message.role === "assistant" ? " message-avatar-assistant" : ""}`}>{message.role === "assistant" ? <Icon name="sparkles" size={16} /> : <Icon name="user" size={16} />}</span>
                      <div className="message-content">
                        <div className="message-meta">
                          <strong>{message.role === "assistant" ? "ZYRQUEN Ω∞" : "คุณ"}</strong>
                          <time>{new Date(message.createdAt).toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" })}</time>
                          {message.role === "assistant" && (
                            <button
                              aria-label={isCopied ? "คัดลอกลงคลิปบอร์ดแล้ว" : "คัดลอกข้อความตอบกลับลงคลิปบอร์ด"}
                              className={`message-copy-button${isCopied ? " message-copy-button-copied" : ""}`}
                              onClick={() => void copyMessageContent(message)}
                              title={isCopied ? "คัดลอกแล้ว" : "คัดลอกข้อความ"}
                              type="button"
                            >
                              <Icon name={isCopied ? "check" : "copy"} size={12} />
                              <span>{isCopied ? "คัดลอกแล้ว" : "คัดลอก"}</span>
                            </button>
                          )}
                        </div>
                        <p>{message.content}</p>
                      </div>
                    </article>
                  );
                })}
                {sending && <div className="message-row message-assistant"><span className="message-avatar message-avatar-assistant"><Icon name="sparkles" size={16} /></span><div className="message-content"><div className="message-meta"><strong>ZYRQUEN Ω∞</strong><span>กำลังสร้างคำตอบ</span></div><div aria-label="กำลังสร้างคำตอบ" className="typing-indicator"><i /><i /><i /></div></div></div>}
              </div>
            )}
          </div>

          {error && <div className="workspace-error" role="alert"><Icon name="close" size={16} /><span>{error}</span>{!session?.authenticated && <Link href="/login">เข้าสู่ระบบ</Link>}</div>}

          <div className="composer-wrap">
            {!session?.authenticated && <div className="composer-signin"><Icon name="lock" size={14} /> จำเป็นต้องเข้าสู่ระบบก่อนจึงจะส่งคำขอประมวลผลได้ <Link href="/login">เข้าสู่ระบบ</Link></div>}
            <form className="composer" onSubmit={(event) => void sendPrompt(event)}>
              <label className="sr-only" htmlFor="prompt">พิมพ์ข้อความถึง ZYRQUEN Ω∞</label>
              <textarea
                disabled={sending}
                id="prompt"
                maxLength={4096}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={onComposerKeyDown}
                placeholder={nativeHealth?.inference_available ? "พิมพ์ข้อความถึง Native Model..." : "รันไทม์ Native Model ยังไม่พร้อมใช้งาน"}
                rows={2}
                value={draft}
              />
              <div className="composer-bottom">
                <details className="generation-options">
                  <summary><Icon name="settings" size={15} /> ตั้งค่าการสร้างข้อความ</summary>
                  <div className="generation-popover">
                    <label htmlFor="max-tokens">จำนวน Token สูงสุด <output>{maxTokens}</output></label>
                    <input id="max-tokens" max="1024" min="1" onChange={(event) => setMaxTokens(Number(event.target.value))} type="range" value={maxTokens} />
                    <label htmlFor="temperature">ค่า Temperature <output>{temperature.toFixed(1)}</output></label>
                    <input id="temperature" max="1" min="0" onChange={(event) => setTemperature(Number(event.target.value))} step="0.1" type="range" value={temperature} />
                  </div>
                </details>
                <span className="composer-hint">{draft.length}/4096 · กด Enter เพื่อส่งข้อความ</span>
                <button aria-label="ส่งข้อความ" className="send-button" disabled={!draft.trim() || sending || !nativeHealth?.inference_available || !session?.authenticated} type="submit">
                  {sending ? <span className="spinner" /> : <Icon name="send" size={17} />}
                </button>
              </div>
            </form>
            <p className="composer-disclaimer">คำตอบจากโมเดลอาจยังไม่สมบูรณ์ ประวัติการสนทนาถูกบันทึกไว้เฉพาะในเบราว์เซอร์นี้ และไม่ได้ซิงค์ขึ้นเซิร์ฟเวอร์</p>
          </div>
        </section>
      </div>
    </div>
  );
}
