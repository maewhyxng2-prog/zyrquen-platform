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
        : `Request failed with status ${response.status}.`;
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
        setNotice("Account created. Signing in…");
      }
      try {
        await postJson("auth/login", { email, password });
      } catch (reason) {
        if (mode === "register") {
          setNotice("Account created. Sign in with your new credentials.");
          return;
        }
        throw reason;
      }
      window.dispatchEvent(new Event("zyrquen:session-change"));
      router.replace("/workspace");
      router.refresh();
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Authentication failed.";
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
          <div><span className="eyebrow">ZYRQUEN Ω∞</span><strong>Independent intelligence</strong></div>
        </div>
        {signedIn ? (
          <div className="auth-signed-in">
            <StatusBadge tone="good" icon="check-circle">SESSION ACTIVE</StatusBadge>
            <h1 id="auth-title">You&apos;re signed in.</h1>
            <p>Your authenticated session is available for native inference.</p>
            <Link className="button button-primary full-button" href="/workspace">Go to AI workspace <Icon name="arrow-right" size={16} /></Link>
          </div>
        ) : (
          <>
            <div className="auth-heading">
              <StatusBadge tone="info" icon="lock">SECURE ACCESS</StatusBadge>
              <h1 id="auth-title">{mode === "login" ? "Welcome back" : "Create your account"}</h1>
              <p>{mode === "login" ? "Sign in to access your ZYRQUEN workspace." : "Create a user account for authenticated API access."}</p>
            </div>
            <div aria-label="Account action" className="auth-tabs" role="tablist">
              <button aria-selected={mode === "login"} className={mode === "login" ? "auth-tab auth-tab-active" : "auth-tab"} onClick={() => { setMode("login"); setError(""); setNotice(""); }} role="tab" type="button">Sign in</button>
              <button aria-selected={mode === "register"} className={mode === "register" ? "auth-tab auth-tab-active" : "auth-tab"} onClick={() => { setMode("register"); setError(""); setNotice(""); }} role="tab" type="button">Create account</button>
            </div>
            <form className="auth-form" onSubmit={(event) => void submit(event)}>
              <label className="field-label" htmlFor="email">Email address</label>
              <div className="input-wrap"><Icon name="user" size={17} /><input autoComplete="email" id="email" maxLength={320} minLength={5} onChange={(event) => setEmail(event.target.value)} placeholder="name@company.com" required type="email" value={email} /></div>
              <label className="field-label" htmlFor="password">Password <span>{mode === "register" ? "12–128 characters" : ""}</span></label>
              <div className="input-wrap"><Icon name="key" size={17} /><input autoComplete={mode === "register" ? "new-password" : "current-password"} id="password" maxLength={128} minLength={mode === "register" ? 12 : 1} onChange={(event) => setPassword(event.target.value)} placeholder="Enter your password" required type="password" value={password} /></div>
              {error && <div className="form-alert form-alert-error" role="alert"><Icon name="close" size={16} />{error}</div>}
              {notice && <div className="form-alert form-alert-success" role="status"><Icon name="check-circle" size={16} />{notice}</div>}
              <button className="button button-primary full-button auth-submit" disabled={submitting} type="submit">
                {submitting ? <><span className="spinner" /> Working...</> : <>{mode === "login" ? "Sign in to workspace" : "Create account"} <Icon name="arrow-right" size={16} /></>}
              </button>
            </form>
            <div className="auth-security-note"><Icon name="shield" size={15} /><span>Credentials are sent to the configured API over the server-side proxy. Access tokens are stored in an HTTP-only session cookie.</span></div>
            <Link className="auth-back-link" href="/">Return to platform overview</Link>
          </>
        )}
      </section>
      <div className="auth-footer"><span>ZYRQUEN Ω∞</span><span>Independent online AI platform</span></div>
    </div>
  );
}
