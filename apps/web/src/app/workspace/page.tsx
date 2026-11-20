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
  "Summarize what the native runtime can do.",
  "Help me think through a technical problem.",
  "Explain the current training pipeline.",
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
  const [mobileHistory, setMobileHistory] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
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

  function createConversation(): Conversation {
    const conversation: Conversation = {
      id: crypto.randomUUID(),
      title: "New conversation",
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
      setError(nativeHealth ? "Native inference is unavailable. The runtime has not reported ready." : nativeError || "Native runtime health is unavailable.");
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
      const message = reason instanceof Error ? reason.message : "Inference request failed.";
      if (reason && typeof reason === "object" && "status" in reason && reason.status === 401) {
        setSession({ authenticated: false, email: null });
        setError("Your session is no longer valid. Sign in again to continue.");
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
        action={<StatusBadge icon="command" tone={nativeHealth?.inference_available ? "good" : "warn"}>{nativeHealth?.inference_available ? "NATIVE RUNTIME READY" : "RUNTIME UNAVAILABLE"}</StatusBadge>}
        description="A direct interface to the authenticated native inference endpoint."
        eyebrow="NATIVE AI / WORKSPACE"
        icon="sparkles"
        title="AI workspace"
      />
      <div className="chat-layout">
        <aside aria-label="Local conversation history" className={`conversation-sidebar${mobileHistory ? " conversation-sidebar-open" : ""}`}>
          <div className="conversation-sidebar-head">
            <div><span className="eyebrow">CONVERSATIONS</span><span className="local-only-label">This browser only</span></div>
            <button aria-label="New conversation" className="icon-button icon-button-accent" onClick={() => createConversation()} type="button"><Icon name="plus" size={18} /></button>
          </div>
          <button className="button button-secondary new-chat-button" onClick={() => createConversation()} type="button"><Icon name="plus" size={16} /> New conversation</button>
          <div className="conversation-list">
            {conversations.length === 0 ? (
              <div className="history-empty"><Icon name="history" size={18} /><span>No saved conversations yet</span></div>
            ) : conversations.map((conversation) => (
              <button
                aria-current={activeId === conversation.id ? "page" : undefined}
                className={`conversation-item${activeId === conversation.id ? " conversation-item-active" : ""}`}
                key={conversation.id}
                onClick={() => { setActiveId(conversation.id); setError(""); setMobileHistory(false); }}
                type="button"
              >
                <Icon name="message" size={16} />
                <span><strong>{conversation.title}</strong><small>{conversation.messages.length} messages</small></span>
              </button>
            ))}
          </div>
          <div className="conversation-sidebar-foot"><Icon name="lock" size={13} /> Conversation history stays in this browser.</div>
        </aside>

        <section aria-label="Conversation" className="conversation-main">
          <div className="conversation-toolbar">
            <button className="mobile-history-button" onClick={() => setMobileHistory((open) => !open)} type="button"><Icon name="history" size={16} /> History</button>
            <div className="conversation-title">
              <span className="assistant-avatar"><Icon name="sparkles" size={16} /></span>
              <span><strong>{activeConversation?.title || "New conversation"}</strong><small>ZYRQUEN native inference</small></span>
            </div>
            <div className="conversation-runtime">
              <span className={`runtime-dot${nativeHealth?.inference_available ? " runtime-dot-ready" : ""}`} />
              <span>{healthLoading ? "Checking" : nativeHealth?.inference_available ? "Ready" : "Unavailable"}</span>
            </div>
          </div>

          <div className="message-scroll" ref={scrollRef}>
            {!activeConversation?.messages.length ? (
              <div className="chat-empty-state">
                <div className="chat-empty-mark"><Icon name="sparkles" size={24} /></div>
                <StatusBadge tone={nativeHealth?.inference_available ? "good" : "warn"}>{nativeHealth?.inference_available ? "NATIVE MODEL READY" : "NATIVE MODEL UNAVAILABLE"}</StatusBadge>
                <h2>What would you like to explore?</h2>
                <p>Responses are generated by the existing native inference API. A ready model is required before prompts can be sent.</p>
                <div className="suggestion-list">
                  {examples.map((example) => <button key={example} onClick={() => setDraft(example)} type="button">{example}<Icon name="arrow-up-right" size={14} /></button>)}
                </div>
              </div>
            ) : (
              <div className="message-list">
                {activeConversation.messages.map((message) => (
                  <article className={`message-row message-${message.role}`} key={message.id}>
                    <span className={`message-avatar${message.role === "assistant" ? " message-avatar-assistant" : ""}`}>{message.role === "assistant" ? <Icon name="sparkles" size={16} /> : <Icon name="user" size={16} />}</span>
                    <div className="message-content">
                      <div className="message-meta"><strong>{message.role === "assistant" ? "ZYRQUEN" : "You"}</strong><time>{new Date(message.createdAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time></div>
                      <p>{message.content}</p>
                    </div>
                  </article>
                ))}
                {sending && <div className="message-row message-assistant"><span className="message-avatar message-avatar-assistant"><Icon name="sparkles" size={16} /></span><div className="message-content"><div className="message-meta"><strong>ZYRQUEN</strong><span>Generating</span></div><div aria-label="Generating response" className="typing-indicator"><i /><i /><i /></div></div></div>}
              </div>
            )}
          </div>

          {error && <div className="workspace-error" role="alert"><Icon name="close" size={16} /><span>{error}</span>{!session?.authenticated && <Link href="/login">Sign in</Link>}</div>}

          <div className="composer-wrap">
            {!session?.authenticated && <div className="composer-signin"><Icon name="lock" size={14} /> Sign in is required to send inference requests. <Link href="/login">Sign in</Link></div>}
            <form className="composer" onSubmit={(event) => void sendPrompt(event)}>
              <label className="sr-only" htmlFor="prompt">Message ZYRQUEN</label>
              <textarea
                disabled={sending}
                id="prompt"
                maxLength={4096}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={onComposerKeyDown}
                placeholder={nativeHealth?.inference_available ? "Message the native model..." : "Native inference is unavailable"}
                rows={2}
                value={draft}
              />
              <div className="composer-bottom">
                <details className="generation-options">
                  <summary><Icon name="settings" size={15} /> Generation settings</summary>
                  <div className="generation-popover">
                    <label htmlFor="max-tokens">Maximum new tokens <output>{maxTokens}</output></label>
                    <input id="max-tokens" max="1024" min="1" onChange={(event) => setMaxTokens(Number(event.target.value))} type="range" value={maxTokens} />
                    <label htmlFor="temperature">Temperature <output>{temperature.toFixed(1)}</output></label>
                    <input id="temperature" max="1" min="0" onChange={(event) => setTemperature(Number(event.target.value))} step="0.1" type="range" value={temperature} />
                  </div>
                </details>
                <span className="composer-hint">{draft.length}/4096 · Enter to send</span>
                <button aria-label="Send message" className="send-button" disabled={!draft.trim() || sending || !nativeHealth?.inference_available || !session?.authenticated} type="submit">
                  {sending ? <span className="spinner" /> : <Icon name="send" size={17} />}
                </button>
              </div>
            </form>
            <p className="composer-disclaimer">Model output may be incomplete. Conversations are stored locally in this browser and are not synced to the server.</p>
          </div>
        </section>
      </div>
    </div>
  );
}
