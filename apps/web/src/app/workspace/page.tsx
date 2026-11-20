"use client";

import {
  FormEvent,
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Icon } from "@/components/Icon";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { usePlatformHealth } from "@/hooks/usePlatformHealth";
import {
  apiStreamRequest,
  ApiError,
  conversationStorageKey,
  readSession,
} from "@/lib/api";
import {
  buildNativeInferencePrompt,
  consumeNativeInferenceStream,
} from "@/lib/native-chat";
import type { Conversation, ConversationMessage, Session } from "@/lib/types";

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

type RequestPhase = "verifying" | "connecting" | "generating" | null;

export default function WorkspacePage() {
  const router = useRouter();
  const { nativeHealth, nativeError, loading: healthLoading } = usePlatformHealth();
  const [session, setSession] = useState<Session | null>(null);
  const [sessionReady, setSessionReady] = useState(false);
  const sessionRef = useRef<Session | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loadedStorageKey, setLoadedStorageKey] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [maxTokens, setMaxTokens] = useState(256);
  const [temperature, setTemperature] = useState(0.7);
  const [requestPhase, setRequestPhase] = useState<RequestPhase>(null);
  const [streamingOutput, setStreamingOutput] = useState<{
    conversationId: string;
    content: string;
  } | null>(null);
  const [error, setError] = useState("");
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [mobileHistory, setMobileHistory] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const copyTimerRef = useRef<number | null>(null);
  const inferenceAbortControllerRef = useRef<AbortController | null>(null);
  const sending = requestPhase !== null;
  const storageKey = useMemo(() => conversationStorageKey(session), [session]);
  const storageReadyForCurrentUser =
    storageKey !== null && loadedStorageKey === storageKey;
  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeId) ?? null,
    [conversations, activeId],
  );
  const filteredConversations = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return conversations;
    return conversations.filter((conversation) =>
      conversation.title.toLowerCase().includes(query),
    );
  }, [conversations, searchQuery]);

  const applySession = useCallback((nextSession: Session) => {
    const previousUserId = sessionRef.current?.userId ?? null;
    const nextUserId = nextSession.authenticated ? nextSession.userId ?? null : null;
    sessionRef.current = nextSession;
    if (previousUserId && previousUserId !== nextUserId) {
      inferenceAbortControllerRef.current?.abort();
    }
    setSession(nextSession);
  }, []);

  useEffect(() => {
    const syncSession = () => {
      readSession()
        .then((current) => {
          applySession(current);
          setSessionReady(true);
        })
        .catch(() => {
          applySession({
            authenticated: false,
            email: null,
            error: "ไม่สามารถตรวจสอบสถานะเซสชันปัจจุบันได้",
          });
          setSessionReady(true);
        });
    };
    syncSession();
    window.addEventListener("zyrquen:session-change", syncSession);
    return () => {
      inferenceAbortControllerRef.current?.abort();
      if (copyTimerRef.current !== null) {
        window.clearTimeout(copyTimerRef.current);
      }
      window.removeEventListener("zyrquen:session-change", syncSession);
    };
  }, [applySession]);

  useEffect(() => {
    if (sessionReady && !session?.authenticated) {
      router.replace("/login");
    }
  }, [sessionReady, session, router]);

  useEffect(() => {
    const loadTimer = window.setTimeout(() => {
      if (!storageKey) {
        setConversations([]);
        setActiveId(null);
        setDraft("");
        setError("");
        setStreamingOutput(null);
        setLoadedStorageKey(null);
        return;
      }

      try {
        const raw = window.localStorage.getItem(storageKey);
        if (raw) {
          const parsed: unknown = JSON.parse(raw);
          if (Array.isArray(parsed)) {
            const valid = parsed.filter(isConversation);
            setConversations(valid);
            setActiveId(valid[0]?.id ?? null);
          } else {
            setConversations([]);
            setActiveId(null);
          }
        } else {
          setConversations([]);
          setActiveId(null);
        }
      } catch {
        window.localStorage.removeItem(storageKey);
        setConversations([]);
        setActiveId(null);
      }
      setDraft("");
      setError("");
      setStreamingOutput(null);
      setLoadedStorageKey(storageKey);
    }, 0);

    const clearHistory = () => {
      setConversations([]);
      setActiveId(null);
    };

    window.addEventListener("zyrquen:conversations-cleared", clearHistory);
    return () => {
      window.clearTimeout(loadTimer);
      window.removeEventListener("zyrquen:conversations-cleared", clearHistory);
    };
  }, [storageKey]);

  useEffect(() => {
    if (!mobileHistory) return;
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        setMobileHistory(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [mobileHistory]);

  useEffect(() => {
    if (storageReadyForCurrentUser && storageKey) {
      window.localStorage.setItem(storageKey, JSON.stringify(conversations));
    }
  }, [conversations, storageKey, storageReadyForCurrentUser]);

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
    setSearchQuery("");
    setError("");
    setMobileHistory(false);
    return conversation;
  }

  function selectConversation(id: string) {
    setActiveId(id);
    setError("");
    setMobileHistory(false);
  }

  function updateConversation(id: string, update: (current: Conversation) => Conversation) {
    setConversations((current) =>
      current.map((conversation) =>
        conversation.id === id ? update(conversation) : conversation,
      ),
    );
  }

  function deleteConversation(id: string) {
    const remaining = conversations.filter((conversation) => conversation.id !== id);
    setConversations(remaining);
    if (storageReadyForCurrentUser && storageKey) {
      if (remaining.length === 0) {
        window.localStorage.removeItem(storageKey);
      } else {
        window.localStorage.setItem(storageKey, JSON.stringify(remaining));
      }
    }
    if (activeId === id) {
      setActiveId(remaining[0]?.id ?? null);
    }
    if (editingId === id) {
      setEditingId(null);
      setEditingTitle("");
    }
    setError("");
  }

  function startEditingTitle(conversation: Conversation) {
    setEditingId(conversation.id);
    setEditingTitle(conversation.title);
  }

  function commitRename(id: string) {
    if (editingId !== id) return;
    const trimmed = editingTitle.trim();
    if (trimmed) {
      updateConversation(id, (current) => ({
        ...current,
        title: trimmed,
        updatedAt: new Date().toISOString(),
      }));
    }
    setEditingId(null);
    setEditingTitle("");
  }

  function cancelRename() {
    setEditingId(null);
    setEditingTitle("");
  }

  function onRenameKeyDown(event: KeyboardEvent<HTMLInputElement>, id: string) {
    if (event.key === "Enter") {
      event.preventDefault();
      commitRename(id);
    } else if (event.key === "Escape") {
      event.preventDefault();
      cancelRename();
    }
  }

  async function sendPrompt(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const prompt = draft.trim();
    if (!prompt || inferenceAbortControllerRef.current) return;
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

    const controller = new AbortController();
    inferenceAbortControllerRef.current = controller;
    setRequestPhase("verifying");
    setError("");
    let conversation: Conversation | null = null;
    let responseText = "";
    const expectedUserId = session.userId?.trim();

    try {
      if (!expectedUserId) {
        throw new ApiError("ไม่พบรหัสบัญชีที่ยืนยันตัวตนแล้ว", 401);
      }

      const verifiedSession = await readSession(controller.signal);
      if (
        !verifiedSession.authenticated ||
        verifiedSession.userId !== expectedUserId
      ) {
        applySession(verifiedSession);
        throw new ApiError(
          "เซสชันเปลี่ยนหรือหมดอายุ กรุณาตรวจสอบบัญชีก่อนส่งข้อความ",
          401,
        );
      }

      const requestConversation = activeConversation ?? createConversation();
      conversation = requestConversation;
      const inferencePrompt = buildNativeInferencePrompt(
        requestConversation.messages,
        prompt,
      );
      const userMessage: ConversationMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content: prompt,
        createdAt: new Date().toISOString(),
      };
      updateConversation(requestConversation.id, (current) => ({
        ...current,
        title: current.messages.length === 0 ? prompt.slice(0, 48) : current.title,
        updatedAt: userMessage.createdAt,
        messages: [...current.messages, userMessage],
      }));
      setDraft("");
      setRequestPhase("connecting");

      const response = await apiStreamRequest("v1/native-ai/infer/stream", {
        method: "POST",
        headers: {
          "X-Zyrquen-Expected-User-ID": expectedUserId,
        },
        body: JSON.stringify({
          prompt: inferencePrompt,
          max_tokens: maxTokens,
          temperature,
        }),
        signal: controller.signal,
      });
      if (sessionRef.current?.userId !== expectedUserId) {
        throw new DOMException("Session changed", "AbortError");
      }
      setRequestPhase("generating");
      if (!response.body) {
        throw new ApiError("Native inference stream is unavailable", 502);
      }
      setStreamingOutput({ conversationId: requestConversation.id, content: "" });
      responseText = await consumeNativeInferenceStream(
        response.body,
        (content) => {
          responseText = content;
          setStreamingOutput({
            conversationId: requestConversation.id,
            content,
          });
        },
      );
      if (!responseText.trim()) {
        throw new ApiError("Native Model returned an empty response", 502);
      }
      if (sessionRef.current?.userId !== expectedUserId) {
        throw new DOMException("Session changed", "AbortError");
      }
      const assistantMessage: ConversationMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: responseText,
        createdAt: new Date().toISOString(),
      };
      updateConversation(requestConversation.id, (current) => ({
        ...current,
        updatedAt: assistantMessage.createdAt,
        messages: [...current.messages, assistantMessage],
      }));
    } catch (reason) {
      const sessionStillMatches =
        expectedUserId !== undefined &&
        sessionRef.current?.userId === expectedUserId;
      if (conversation && responseText.trim() && sessionStillMatches) {
        const partialMessage: ConversationMessage = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: responseText,
          createdAt: new Date().toISOString(),
          incomplete: true,
        };
        updateConversation(conversation.id, (current) => ({
          ...current,
          updatedAt: partialMessage.createdAt,
          messages: [...current.messages, partialMessage],
        }));
      }

      if (
        reason instanceof ApiError &&
        (reason.status === 401 || reason.status === 403)
      ) {
        applySession({
          authenticated: false,
          email: null,
          verified: true,
        });
        setError(
          "เซสชันของคุณหมดอายุหรือไม่ถูกต้อง กรุณาเข้าสู่ระบบใหม่อีกครั้งเพื่อใช้งานต่อ",
        );
      } else if (controller.signal.aborted) {
        setError(
          responseText.trim()
            ? "ยกเลิกคำขอแล้ว คำตอบที่แสดงเป็นข้อความที่ Native Model ส่งมาก่อนยกเลิก"
            : "ยกเลิกคำขอ Native Inference แล้ว",
        );
      } else if (reason instanceof ApiError && reason.status === 409) {
        setError(reason.message);
      } else {
        const message =
          reason instanceof Error
            ? reason.message
            : "ส่งคำขอประมวลผลไม่สำเร็จ กรุณาตรวจสอบสถานะการเชื่อมต่อ API แล้วลองใหม่อีกครั้ง";
        setError(message);
      }
    } finally {
      setStreamingOutput(null);
      if (inferenceAbortControllerRef.current === controller) {
        inferenceAbortControllerRef.current = null;
      }
      setRequestPhase(null);
    }
  }

  function cancelInference() {
    inferenceAbortControllerRef.current?.abort();
  }

  function onComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendPrompt();
    }
  }

  const runtimeBadgeLabel =
    healthLoading && !nativeHealth
      ? "กำลังตรวจสอบรันไทม์..."
      : nativeHealth?.inference_available
        ? "Native Model พร้อมใช้งาน"
        : nativeError
          ? "รันไทม์ตรวจสอบไม่สำเร็จ"
          : "รันไทม์ไม่พร้อมใช้งาน";
  const requestStatusLabel =
    requestPhase === "verifying"
      ? "กำลังตรวจสอบเซสชัน"
      : requestPhase === "connecting"
        ? "กำลังเชื่อมต่อ Native Inference API"
        : "กำลังรับข้อความจาก Native Model";

  if (sessionReady && session?.authenticated && !storageReadyForCurrentUser) {
    return (
      <div className="page-stack">
        <PageHeader
          description="กำลังโหลดประวัติที่แยกตามบัญชีผู้ใช้"
          eyebrow="NATIVE AI / พื้นที่ทำงาน"
          icon="lock"
          title="กำลังตรวจสอบพื้นที่ส่วนตัว"
        />
        <div className="panel notice-panel" role="status">
          กำลังโหลดข้อมูลของบัญชีที่ยืนยันตัวตนแล้ว...
        </div>
      </div>
    );
  }

  if (!sessionReady || !session?.authenticated) {
    return (
      <div className="page-stack">
        <PageHeader
          description="พื้นที่สนทนาสำหรับพิมพ์ข้อความและรับคำตอบจาก Native Model ผ่าน API ที่ผ่านการยืนยันตัวตน"
          eyebrow="NATIVE AI / พื้นที่ทำงาน"
          icon="sparkles"
          title="พื้นที่ทำงาน AI"
        />
        <div className="panel notice-panel">
          <span className="notice-icon">
            <Icon name="lock" size={18} />
          </span>
          <div>
            <strong>
              {!sessionReady
                ? "กำลังตรวจสอบเซสชันจาก Backend..."
                : session?.expired
                  ? "เซสชันหมดอายุแล้ว"
                  : "จำเป็นต้องเข้าสู่ระบบก่อนใช้งานพื้นที่ทำงาน AI"}
            </strong>
            <p>
              {!sessionReady
                ? "ระบบกำลังยืนยันตัวตนกับบริการ ZYRQUEN API เพื่อปกป้องเส้นทางที่มีการจำกัดสิทธิ์"
                : session?.error ||
                  "หน้านี้เป็นพื้นที่ทำงานสำหรับผู้ใช้ที่ผ่านการยืนยันตัวตนแล้วเท่านั้น กรุณาเข้าสู่ระบบเพื่อดำเนินการต่อ"}
            </p>
            {sessionReady && (
              <Link className="button button-primary" href="/login">
                <Icon name="lock" size={16} />
                ไปยังหน้าเข้าสู่ระบบ
              </Link>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="page-stack workspace-page">
      <PageHeader
        action={<StatusBadge icon="command" tone={nativeHealth?.inference_available ? "good" : healthLoading && !nativeHealth ? "neutral" : "warn"}>{runtimeBadgeLabel}</StatusBadge>}
        description="พื้นที่สนทนาสำหรับพิมพ์ข้อความและรับคำตอบจาก Native Model ผ่าน API ที่ผ่านการยืนยันตัวตน"
        eyebrow="NATIVE AI / พื้นที่ทำงาน"
        icon="sparkles"
        title="พื้นที่ทำงาน AI"
      />
      <div className="chat-layout">
        {mobileHistory && (
          <button
            aria-label="ปิดรายการประวัติการสนทนา"
            className="conversation-mobile-scrim"
            onClick={() => setMobileHistory(false)}
            type="button"
          />
        )}
        <aside aria-label="ประวัติการสนทนาในเครื่อง" className={`conversation-sidebar${mobileHistory ? " conversation-sidebar-open" : ""}`} id="workspace-history-sidebar">
          <div className="conversation-sidebar-head">
            <div><span className="eyebrow">บทสนทนา</span><span className="local-only-label">บันทึกเฉพาะในเบราว์เซอร์นี้</span></div>
            <div className="conversation-sidebar-actions">
              <button aria-label="สร้างบทสนทนาใหม่" className="icon-button icon-button-accent" onClick={() => createConversation()} type="button"><Icon name="plus" size={18} /></button>
              <button aria-label="ปิดรายการบทสนทนา" className="icon-button mobile-history-close" onClick={() => setMobileHistory(false)} type="button"><Icon name="close" size={16} /></button>
            </div>
          </div>
          <button className="button button-secondary new-chat-button" onClick={() => createConversation()} type="button"><Icon name="plus" size={16} /> สร้างบทสนทนาใหม่</button>
          <div className="conversation-search">
            <label className="sr-only" htmlFor="conversation-search">ค้นหาบทสนทนาตามชื่อ</label>
            <Icon name="search" size={14} />
            <input
              aria-label="ค้นหาบทสนทนาตามชื่อ"
              id="conversation-search"
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="ค้นหาบทสนทนา..."
              type="search"
              value={searchQuery}
            />
            {searchQuery && (
              <button
                aria-label="ล้างคำค้นหา"
                className="conversation-search-clear"
                onClick={() => setSearchQuery("")}
                type="button"
              >
                <Icon name="close" size={13} />
              </button>
            )}
          </div>
          <div className="conversation-list">
            {conversations.length === 0 ? (
              <div className="history-empty"><Icon name="history" size={18} /><span>ยังไม่มีประวัติการสนทนาที่บันทึกไว้</span></div>
            ) : filteredConversations.length === 0 ? (
              <div className="history-empty"><Icon name="search" size={18} /><span>ไม่พบบทสนทนาที่ตรงกับคำค้นหา</span></div>
            ) : filteredConversations.map((conversation) => {
              const isActive = activeId === conversation.id;
              const isEditing = editingId === conversation.id;
              return (
                <div
                  className={`conversation-item${isActive ? " conversation-item-active" : ""}`}
                  key={conversation.id}
                >
                  <button
                    aria-current={isActive ? "page" : undefined}
                    aria-label={`เลือกบทสนทนา ${conversation.title}`}
                    className="conversation-item-trigger"
                    onClick={() => selectConversation(conversation.id)}
                    type="button"
                  >
                    <Icon name="message" size={16} />
                  </button>
                  <div className="conversation-item-body">
                    {isEditing ? (
                      <input
                        aria-label="แก้ไขชื่อบทสนทนา"
                        autoFocus
                        className="conversation-title-input"
                        maxLength={80}
                        onBlur={() => commitRename(conversation.id)}
                        onChange={(event) => setEditingTitle(event.target.value)}
                        onKeyDown={(event) => onRenameKeyDown(event, conversation.id)}
                        type="text"
                        value={editingTitle}
                      />
                    ) : (
                      <button
                        className="conversation-title-button"
                        onClick={() => {
                          setActiveId(conversation.id);
                          setError("");
                          startEditingTitle(conversation);
                        }}
                        title="คลิกเพื่อเปลี่ยนชื่อบทสนทนา"
                        type="button"
                      >
                        {conversation.title}
                      </button>
                    )}
                    <button
                      className="conversation-count-button"
                      onClick={() => selectConversation(conversation.id)}
                      type="button"
                    >
                      {conversation.messages.length} ข้อความ
                    </button>
                  </div>
                  <button
                    aria-label={`ลบบทสนทนา ${conversation.title}`}
                    className="conversation-delete-button"
                    onClick={() => deleteConversation(conversation.id)}
                    title="ลบบทสนทนา"
                    type="button"
                  >
                    <Icon name="close" size={14} />
                  </button>
                </div>
              );
            })}
          </div>
          <div className="conversation-sidebar-foot"><Icon name="lock" size={13} /> ประวัติการสนทนาจะถูกเก็บไว้ในเบราว์เซอร์นี้เท่านั้น</div>
        </aside>

        <section aria-label="บทสนทนา" className="conversation-main">
          <div className="conversation-toolbar">
            <button
              aria-controls="workspace-history-sidebar"
              aria-expanded={mobileHistory}
              className="mobile-history-button"
              onClick={() => setMobileHistory((open) => !open)}
              type="button"
            >
              <Icon name="history" size={16} /> ประวัติ
            </button>
            <div className="conversation-title">
              <span className="assistant-avatar"><Icon name="sparkles" size={16} /></span>
              <span><strong>{activeConversation?.title || "บทสนทนาใหม่"}</strong><small>การประมวลผล Native Model ของ ZYRQUEN Ω∞</small></span>
            </div>
            <div className="conversation-runtime">
              <span className={`runtime-dot${nativeHealth?.inference_available ? " runtime-dot-ready" : ""}`} />
              <span>{healthLoading && !nativeHealth ? "กำลังตรวจสอบ" : nativeHealth?.inference_available ? "พร้อมใช้งาน" : nativeError ? "ตรวจสอบไม่สำเร็จ" : "ไม่พร้อมใช้งาน"}</span>
            </div>
          </div>

          <div className="message-scroll" ref={scrollRef}>
            {!activeConversation?.messages.length ? (
              <div className="chat-empty-state">
                <div className="chat-empty-mark"><Icon name="sparkles" size={24} /></div>
                <StatusBadge tone={nativeHealth?.inference_available ? "good" : healthLoading && !nativeHealth ? "neutral" : "warn"}>{runtimeBadgeLabel}</StatusBadge>
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
                          {message.incomplete && (
                            <span className="typing-status-label">หยุดก่อนจบ</span>
                          )}
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
                {streamingOutput?.conversationId === activeConversation.id &&
                  streamingOutput.content && (
                    <article className="message-row message-assistant">
                      <span className="message-avatar message-avatar-assistant">
                        <Icon name="sparkles" size={16} />
                      </span>
                      <div className="message-content">
                        <div className="message-meta">
                          <strong>ZYRQUEN Ω∞</strong>
                          <span className="typing-status-label">กำลังรับคำตอบ</span>
                        </div>
                        <p>{streamingOutput.content}</p>
                      </div>
                    </article>
                  )}
                <div
                  aria-hidden={!sending}
                  aria-live="polite"
                  className={`message-generating${sending ? " message-generating-active" : ""}`}
                >
                  <div className="message-generating-inner">
                    <div className="message-row message-assistant">
                      <span className="message-avatar message-avatar-assistant"><Icon name="sparkles" size={16} /></span>
                      <div className="message-content">
                        <div className="message-meta">
                          <strong>ZYRQUEN Ω∞</strong>
                          <span className="typing-status-label">{requestStatusLabel}</span>
                        </div>
                        <div aria-label={requestStatusLabel} className="typing-indicator"><i /><i /><i /></div>
                      </div>
                    </div>
                  </div>
                </div>
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
                <span className="composer-hint">
                  {sending ? requestStatusLabel : `${draft.length}/4096 · กด Enter เพื่อส่งข้อความ`}
                </span>
                {sending ? (
                  <button
                    aria-label="ยกเลิกคำขอ Native Inference"
                    className="send-button send-button-cancel"
                    onClick={cancelInference}
                    type="button"
                  >
                    <Icon name="close" size={17} />
                  </button>
                ) : (
                  <button
                    aria-label="ส่งข้อความ"
                    className="send-button"
                    disabled={!draft.trim() || !nativeHealth?.inference_available || !session?.authenticated}
                    type="submit"
                  >
                    <Icon name="send" size={17} />
                  </button>
                )}
              </div>
            </form>
            <p className="composer-disclaimer">คำตอบจากโมเดลอาจยังไม่สมบูรณ์ ประวัติการสนทนาถูกบันทึกไว้เฉพาะในเบราว์เซอร์นี้ และไม่ได้ซิงค์ขึ้นเซิร์ฟเวอร์</p>
          </div>
        </section>
      </div>
    </div>
  );
}
