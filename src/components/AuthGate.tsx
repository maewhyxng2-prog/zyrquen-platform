import React, { useEffect, useRef, useState } from 'react';
import {
  ArrowRight,
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  Mail,
  Moon,
  ShieldCheck,
  Sun,
  UserPlus,
} from 'lucide-react';
import { apiRequest, ApiError } from '../lib/api';
import { useZyrquenTheme } from '../lib/theme';
import type { AuthProvidersResponse, AuthStatus, User } from '../types';
import { SpacetimeFabric } from './SpacetimeFabric';
import { TemporalIntelligenceCore } from './TemporalIntelligenceCore';

interface AuthGateProps {
  authStatus: AuthStatus;
  initialVerifyToken?: string | null;
  initialResetToken?: string | null;
  onClearActionTokens?: () => void;
  onAuthenticated: (token: string, user: User) => void;
}

type AuthMode = 'claim' | 'login' | 'register' | 'forgot' | 'reset';

function GoogleGlyph() {
  return (
    <svg className="h-4 w-4 shrink-0" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="#EA4335"
        d="M12 10.2v3.9h5.4c-.24 1.25-.96 2.31-2.04 3.02l3.3 2.56c1.92-1.77 3.04-4.38 3.04-7.48 0-.72-.06-1.42-.19-2.09H12z"
      />
      <path
        fill="#34A853"
        d="M12 22c2.75 0 5.06-.91 6.74-2.46l-3.3-2.56c-.91.61-2.08.97-3.44.97-2.64 0-4.88-1.78-5.68-4.18H2.91v2.63A10 10 0 0 0 12 22z"
      />
      <path
        fill="#4A90E2"
        d="M6.32 13.77A5.99 5.99 0 0 1 6 12c0-.61.11-1.21.32-1.77V7.6H2.91A10 10 0 0 0 2 12c0 1.61.39 3.14 1.08 4.4l3.24-2.63z"
      />
      <path
        fill="#FBBC05"
        d="M12 6.05c1.5 0 2.84.52 3.9 1.53l2.92-2.92C17.05 3.02 14.75 2 12 2a10 10 0 0 0-9.09 5.6l3.41 2.63C7.12 7.83 9.36 6.05 12 6.05z"
      />
    </svg>
  );
}

function GitHubGlyph() {
  return (
    <svg className="h-4 w-4 shrink-0 fill-current" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0 1 12 6.844a9.59 9.59 0 0 1 2.504.337c1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0 0 22 12.017C22 6.484 17.522 2 12 2z" />
    </svg>
  );
}

export function AuthGate({
  authStatus,
  initialVerifyToken = null,
  initialResetToken = null,
  onClearActionTokens,
  onAuthenticated,
}: AuthGateProps) {
  const { theme, toggleTheme } = useZyrquenTheme();
  const [mode, setMode] = useState<AuthMode>(
    initialResetToken ? 'reset' : authStatus.initialized ? 'login' : 'claim'
  );
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [passcode, setPasscode] = useState('');
  const [resetToken, setResetToken] = useState(initialResetToken || '');
  const [loading, setLoading] = useState(false);
  const [oauthPending, setOauthPending] = useState<'google' | 'github' | null>(null);
  const [providersInfo, setProvidersInfo] = useState<AuthProvidersResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const oauthPopupRef = useRef<Window | null>(null);
  const onAuthenticatedRef = useRef(onAuthenticated);

  useEffect(() => {
    onAuthenticatedRef.current = onAuthenticated;
  }, [onAuthenticated]);

  useEffect(() => {
    let active = true;
    apiRequest<AuthProvidersResponse>('/api/auth/providers')
      .then((res) => {
        if (active) setProvidersInfo(res);
      })
      .catch(() => {
        // Optional metadata endpoint; keep UI usable if unavailable
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!initialVerifyToken) return;
    let active = true;
    apiRequest<{ ok: boolean; user?: User; error?: string }>('/api/auth/verify-email', {
      method: 'POST',
      body: { token: initialVerifyToken },
    })
      .then((res) => {
        if (!active) return;
        if (res.ok) {
          setNotice('ยืนยันอีเมลสำเร็จแล้ว สามารถเข้าสู่ระบบเพื่อใช้งานได้ทันที');
          onClearActionTokens?.();
        }
      })
      .catch((err) => {
        if (!active) return;
        setError(err instanceof ApiError ? err.message : 'ลิงก์ยืนยันอีเมลไม่ถูกต้องหรือหมดอายุแล้ว');
      });
    return () => {
      active = false;
    };
  }, [initialVerifyToken, onClearActionTokens]);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin) return;
      const data = event.data as
        | {
            type?: string;
            ok?: boolean;
            intent?: string;
            provider?: string;
            token?: string;
            user?: User;
            error?: string;
          }
        | undefined;
      if (!data) return;
      if (data.type === 'OAUTH_AUTH_SUCCESS' && data.token && data.user) {
        setOauthPending(null);
        onAuthenticatedRef.current(data.token, data.user);
        return;
      }
      if (data.type === 'OAUTH_AUTH_ERROR') {
        setOauthPending(null);
        setError(data.error || 'การเข้าสู่ระบบผ่านผู้ให้บริการภายนอกไม่สำเร็จ');
        return;
      }
      if (data.type !== 'ZYRQUEN_OAUTH_RESULT') return;
      setOauthPending(null);
      if (data.ok && data.token && data.user) {
        onAuthenticatedRef.current(data.token, data.user);
      } else {
        setError(data.error || 'การเข้าสู่ระบบผ่านผู้ให้บริการภายนอกไม่สำเร็จ');
      }
    }
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  function switchMode(nextMode: AuthMode) {
    setMode(nextMode);
    setError(null);
    setNotice(null);
  }

  async function handleOAuthStart(provider: 'google' | 'github') {
    setError(null);
    setNotice(null);
    setOauthPending(provider);
    try {
      const origin = window.location.origin;
      const res = await apiRequest<{ ok: boolean; url: string; provider: string }>(
        `/api/auth/oauth/${provider}/url?intent=login&origin=${encodeURIComponent(origin)}`
      );
      const popup = window.open(
        res.url,
        'zyrquen-oauth',
        'width=560,height=680,menubar=no,toolbar=no,status=no'
      );
      if (!popup) {
        setOauthPending(null);
        setError('เบราว์เซอร์บล็อกหน้าต่างป๊อปอัป กรุณาอนุญาตป๊อปอัปเพื่อดำเนินการเข้าสู่ระบบ');
        return;
      }
      oauthPopupRef.current = popup;
    } catch (err) {
      setOauthPending(null);
      setError(
        err instanceof ApiError
          ? err.message
          : `ไม่สามารถเริ่มการเชื่อมต่อ ${provider === 'github' ? 'GitHub' : 'Google'} OAuth 2.0 ได้`
      );
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);

    if (mode === 'forgot') {
      setLoading(true);
      try {
        const res = await apiRequest<{
          ok: boolean;
          message: string;
          emailProviderConfigured?: boolean;
          deliveryReason?: string | null;
        }>('/api/auth/forgot-password', {
          method: 'POST',
          body: { email },
        });
        const suffix =
          res.emailProviderConfigured === false
            ? ' (หมายเหตุ: เซิร์ฟเวอร์ยังไม่ได้ตั้งค่าผู้ให้บริการส่งอีเมล RESEND_API_KEY)'
            : '';
        setNotice(`${res.message}${suffix}`);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'ส่งคำขอรีเซ็ตรหัสผ่านไม่สำเร็จ');
      } finally {
        setLoading(false);
      }
      return;
    }

    if (mode === 'claim' || mode === 'register' || mode === 'reset') {
      if (password.length < 12 || password.length > 128) {
        setError('รหัสผ่านต้องมีความยาว 12–128 ตัวอักษร');
        return;
      }
    }

    if (mode === 'claim' && !authStatus.envPasscodeConfigured) {
      setError('เซิร์ฟเวอร์ยังไม่ได้ตั้งค่า ZYRQUEN_ADMIN_PASSCODE จึงไม่สามารถตั้งค่าผู้ดูแลได้');
      return;
    }

    if (mode === 'reset') {
      if (password.length < 12 || password.length > 128) {
        setError('รหัสผ่านใหม่ต้องมีความยาว 12–128 ตัวอักษร');
        return;
      }
      if (password !== confirmPassword) {
        setError('รหัสผ่านใหม่และยืนยันรหัสผ่านไม่ตรงกัน');
        return;
      }
      setLoading(true);
      try {
        await apiRequest<{ ok: boolean }>('/api/auth/reset-password', {
          method: 'POST',
          body: { token: resetToken, password },
        });
        setPassword('');
        setConfirmPassword('');
        onClearActionTokens?.();
        setMode('login');
        setNotice('เปลี่ยนรหัสผ่านสำเร็จแล้ว กรุณาเข้าสู่ระบบด้วยรหัสผ่านใหม่');
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'รีเซ็ตรหัสผ่านไม่สำเร็จ');
      } finally {
        setLoading(false);
      }
      return;
    }

    if (mode === 'register') {
      if (displayName.trim().length < 2) {
        setError('ชื่อที่แสดงต้องมีอย่างน้อย 2 ตัวอักษร');
        return;
      }
      if (password !== confirmPassword) {
        setError('รหัสผ่านและยืนยันรหัสผ่านไม่ตรงกัน');
        return;
      }
    }

    setLoading(true);
    try {
      if (mode === 'claim') {
        const res = await apiRequest<{ token: string; user: User }>('/api/auth/claim-admin', {
          method: 'POST',
          body: { email, displayName, password, passcode },
        });
        onAuthenticated(res.token, res.user);
      } else if (mode === 'register') {
        const res = await apiRequest<{
          token: string;
          user: User;
          verification?: { required: boolean; emailSent: boolean; deliveryReason: string | null };
        }>('/api/auth/register', {
          method: 'POST',
          body: { email, displayName, password, confirmPassword },
        });
        onAuthenticated(res.token, res.user);
      } else {
        const res = await apiRequest<{ token: string; user: User }>('/api/auth/login', {
          method: 'POST',
          body: { email, password },
        });
        onAuthenticated(res.token, res.user);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ยืนยันตัวตนไม่สำเร็จ');
    } finally {
      setLoading(false);
    }
  }

  const isCompactHero = mode === 'register' || mode === 'forgot' || mode === 'reset';
  const showOAuthSection = mode === 'login' || mode === 'register';
  const googleConfigured = providersInfo?.providers?.google?.configured;
  const githubConfigured = providersInfo?.providers?.github?.configured;

  return (
    <div className="relative flex min-h-[100dvh] flex-col justify-center overflow-hidden bg-[var(--color-bg)] px-4 py-8 text-[var(--color-text)] sm:px-6">
      <SpacetimeFabric
        density={isCompactHero ? 'minimal' : 'balanced'}
        className="absolute inset-0"
      />

      <div className="relative z-10 mx-auto w-full max-w-md">
        <div className="mb-4 flex items-center justify-end">
          <button
            type="button"
            onClick={toggleTheme}
            aria-label={theme === 'dark' ? 'เปลี่ยนเป็นโหมดสว่าง (Light Mode)' : 'เปลี่ยนเป็นโหมดมืด (Dark Mode)'}
            className="inline-flex min-h-[36px] items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]/90 px-3 text-xs font-medium text-[var(--color-text-secondary)] backdrop-blur-sm transition-colors hover:bg-[var(--color-surface-hover)] hover:text-[var(--color-text)]"
          >
            {theme === 'dark' ? (
              <Sun className="h-3.5 w-3.5 text-[var(--color-accent)]" />
            ) : (
              <Moon className="h-3.5 w-3.5 text-[var(--color-primary)]" />
            )}
            <span>{theme === 'dark' ? 'โหมดสว่าง' : 'โหมดมืด'}</span>
          </button>
        </div>

        <div className="mb-6 flex flex-col items-center text-center">
          <TemporalIntelligenceCore
            variant={isCompactHero ? 'compact' : 'prominent'}
            size={isCompactHero ? 92 : 148}
            active={loading || oauthPending !== null}
          />
          <p className="mt-2 font-mono text-[11px] font-semibold tracking-[0.22em] text-[var(--color-accent)] uppercase">
            AUTONOMOUS FOUNDATIONAL INTELLIGENCE
          </p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight text-[var(--color-text)]">
            ZYRQUEN
          </h1>
          <p className="mt-1 text-sm font-medium text-[var(--color-text-secondary)]">
            ปัญญาประดิษฐ์พื้นฐานแบบอัตโนมัติ — ปัญญาที่พัฒนาได้
          </p>
          {!isCompactHero && (
            <p className="mt-2 max-w-sm text-xs leading-relaxed text-[var(--color-text-muted)]">
              การคิดอย่างต่อเนื่อง · การเรียนรู้ · วิวัฒนาการความรู้ · การให้เหตุผล · การพัฒนาตนเอง
            </p>
          )}
        </div>

        <div className="zyrq-glow rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)]/95 p-6 backdrop-blur-md sm:p-7">
          <div className="mb-5 h-[2px] w-full rounded-full zyrq-brand-gradient-line opacity-80" aria-hidden="true" />

          {mode !== 'forgot' && mode !== 'reset' && (
            authStatus.initialized ? (
              <div className="mb-6 grid grid-cols-2 gap-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-1">
                <button
                  type="button"
                  onClick={() => switchMode('login')}
                  className={`min-h-[44px] rounded-lg px-3 text-sm font-medium transition-colors whitespace-nowrap ${
                    mode === 'login'
                      ? 'bg-[var(--color-primary)] text-white'
                      : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
                  }`}
                >
                  เข้าสู่ระบบ
                </button>
                <button
                  type="button"
                  onClick={() => switchMode('register')}
                  className={`min-h-[44px] rounded-lg px-3 text-sm font-medium transition-colors whitespace-nowrap ${
                    mode === 'register'
                      ? 'bg-[var(--color-primary)] text-white'
                      : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
                  }`}
                >
                  สมัครสมาชิก
                </button>
              </div>
            ) : (
              <div
                className={`mb-6 grid gap-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-1 ${
                  authStatus.userCount > 0 ? 'grid-cols-3' : 'grid-cols-2'
                }`}
              >
                <button
                  type="button"
                  onClick={() => switchMode('claim')}
                  className={`min-h-[44px] rounded-lg px-2.5 text-xs sm:text-sm font-medium transition-colors whitespace-nowrap ${
                    mode === 'claim'
                      ? 'bg-[var(--color-primary)] text-white'
                      : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
                  }`}
                >
                  ตั้งค่าผู้ดูแล
                </button>
                <button
                  type="button"
                  onClick={() => switchMode('register')}
                  className={`min-h-[44px] rounded-lg px-2.5 text-xs sm:text-sm font-medium transition-colors whitespace-nowrap ${
                    mode === 'register'
                      ? 'bg-[var(--color-primary)] text-white'
                      : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
                  }`}
                >
                  สมัครสมาชิก
                </button>
                {authStatus.userCount > 0 && (
                  <button
                    type="button"
                    onClick={() => switchMode('login')}
                    className={`min-h-[44px] rounded-lg px-2.5 text-xs sm:text-sm font-medium transition-colors whitespace-nowrap ${
                      mode === 'login'
                        ? 'bg-[var(--color-primary)] text-white'
                        : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text)]'
                    }`}
                  >
                    เข้าสู่ระบบ
                  </button>
                )}
              </div>
            )
          )}

          {mode === 'claim' && !authStatus.initialized && (
            <div className="mb-5 flex items-center gap-2.5 text-sm font-medium text-[var(--color-accent)]">
              <ShieldCheck className="h-4 w-4 shrink-0" />
              <span>ตั้งค่าผู้ดูแลระบบเริ่มต้น</span>
            </div>
          )}

          {mode === 'register' && (
            <div className="mb-4 space-y-1">
              <div className="flex items-center gap-2 text-sm font-medium text-[var(--color-accent)]">
                <UserPlus className="h-4 w-4 shrink-0" />
                <span>สมัครสมาชิกใหม่ (บัญชีผู้ใช้งานทั่วไป)</span>
              </div>
              <p className="text-xs text-[var(--color-text-secondary)]">สร้างบัญชีเพื่อเริ่มใช้งาน</p>
            </div>
          )}

          {mode === 'forgot' && (
            <div className="mb-5 space-y-1">
              <div className="flex items-center gap-2 text-sm font-medium text-[var(--color-accent)]">
                <Mail className="h-4 w-4 shrink-0" />
                <span>กู้คืนรหัสผ่าน</span>
              </div>
              <p className="text-xs text-[var(--color-text-secondary)]">
                กรอกอีเมลที่ลงทะเบียนไว้เพื่อรับลิงก์ตั้งรหัสผ่านใหม่
              </p>
            </div>
          )}

          {mode === 'reset' && (
            <div className="mb-5 space-y-1">
              <div className="flex items-center gap-2 text-sm font-medium text-[var(--color-accent)]">
                <KeyRound className="h-4 w-4 shrink-0" />
                <span>ตั้งรหัสผ่านใหม่</span>
              </div>
              <p className="text-xs text-[var(--color-text-secondary)]">
                กรอกรหัสผ่านใหม่ที่ต้องการใช้งานกับบัญชีของคุณ
              </p>
            </div>
          )}

          {showOAuthSection && (
            <div className="mb-5 space-y-3">
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                <button
                  type="button"
                  disabled={loading || oauthPending !== null}
                  onClick={() => void handleOAuthStart('google')}
                  aria-label={mode === 'register' ? 'สมัครด้วย Google (Login with Google)' : 'Login with Google'}
                  className="flex min-h-[44px] items-center justify-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-semibold text-[var(--color-text)] transition-colors hover:border-[var(--color-accent)] hover:bg-[var(--color-surface-hover)] disabled:opacity-60"
                >
                  <GoogleGlyph />
                  <span>
                    {oauthPending === 'google'
                      ? 'กำลังเชื่อมต่อ...'
                      : mode === 'register'
                        ? 'สมัครด้วย Google'
                        : 'Login with Google'}
                  </span>
                </button>
                <button
                  type="button"
                  disabled={loading || oauthPending !== null}
                  onClick={() => void handleOAuthStart('github')}
                  aria-label={mode === 'register' ? 'สมัครด้วย GitHub (Login with GitHub)' : 'Login with GitHub'}
                  className="flex min-h-[44px] items-center justify-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-semibold text-[var(--color-text)] transition-colors hover:border-[var(--color-accent)] hover:bg-[var(--color-surface-hover)] disabled:opacity-60"
                >
                  <GitHubGlyph />
                  <span>
                    {oauthPending === 'github'
                      ? 'กำลังเชื่อมต่อ...'
                      : mode === 'register'
                        ? 'สมัครด้วย GitHub'
                        : 'Login with GitHub'}
                  </span>
                </button>
              </div>
              {providersInfo && (!googleConfigured || !githubConfigured) && (
                <p className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">
                  สถานะ OAuth 2.0: Google {googleConfigured ? 'พร้อมใช้งาน' : 'ยังไม่ตั้งค่า Client ID/Secret'} · GitHub{' '}
                  {githubConfigured ? 'พร้อมใช้งาน' : 'ยังไม่ตั้งค่า Client ID/Secret'}
                </p>
              )}
              <div className="relative flex items-center py-1">
                <div className="flex-grow border-t border-[var(--color-border)]" />
                <span className="mx-3 shrink-0 text-[11px] font-medium text-[var(--color-text-muted)]">
                  หรือใช้อีเมล
                </span>
                <div className="flex-grow border-t border-[var(--color-border)]" />
              </div>
            </div>
          )}

          {notice && (
            <div
              role="status"
              className="mb-4 flex items-start gap-2 rounded-xl border border-[var(--color-success)]/40 bg-[var(--color-surface)] px-3.5 py-2.5 text-xs text-[var(--color-success)]"
            >
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{notice}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {(mode === 'claim' || mode === 'register') && (
              <div>
                <label
                  htmlFor="zyrq-display-name"
                  className="mb-1.5 block text-xs font-medium text-[var(--color-text-secondary)]"
                >
                  ชื่อที่แสดง
                </label>
                <input
                  id="zyrq-display-name"
                  type="text"
                  required
                  minLength={2}
                  maxLength={80}
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder={mode === 'claim' ? 'หัวหน้าทีมวิจัย' : 'ชื่อของคุณ'}
                  className="h-12 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                />
              </div>
            )}

            {mode !== 'reset' && (
              <div>
                <label
                  htmlFor="zyrq-email"
                  className="mb-1.5 block text-xs font-medium text-[var(--color-text-secondary)]"
                >
                  อีเมล
                </label>
                <input
                  id="zyrq-email"
                  type="email"
                  required
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  className="h-12 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                />
              </div>
            )}

            {mode !== 'forgot' && (
              <div>
                <div className="mb-1.5 flex items-center justify-between gap-2">
                  <label
                    htmlFor="zyrq-password"
                    className="block text-xs font-medium text-[var(--color-text-secondary)]"
                  >
                    {mode === 'reset' ? 'รหัสผ่านใหม่' : 'รหัสผ่าน'}
                  </label>
                  {mode === 'login' && (
                    <button
                      type="button"
                      onClick={() => switchMode('forgot')}
                      className="text-xs font-medium text-[var(--color-accent)] hover:underline"
                    >
                      ลืมรหัสผ่าน?
                    </button>
                  )}
                </div>
                <div className="relative">
                  <input
                    id="zyrq-password"
                    type={showPassword ? 'text' : 'password'}
                    required
                    minLength={mode === 'login' ? 1 : 12}
                    maxLength={mode === 'login' ? 256 : 128}
                    autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder={mode === 'login' ? 'กรอกรหัสผ่าน' : '12–128 ตัวอักษร'}
                    className="h-12 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] pl-3.5 pr-11 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                  />
                  <button
                    type="button"
                    aria-label={showPassword ? 'ซ่อนรหัสผ่าน' : 'แสดงรหัสผ่าน'}
                    onClick={() => setShowPassword((prev) => !prev)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>
            )}

            {(mode === 'register' || mode === 'reset') && (
              <div>
                <label
                  htmlFor="zyrq-confirm-password"
                  className="mb-1.5 block text-xs font-medium text-[var(--color-text-secondary)]"
                >
                  ยืนยันรหัสผ่าน
                </label>
                <input
                  id="zyrq-confirm-password"
                  type={showPassword ? 'text' : 'password'}
                  required
                  minLength={12}
                  maxLength={128}
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="กรอกรหัสผ่านซ้ำอีกครั้ง"
                  className="h-12 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                />
              </div>
            )}

            {mode === 'reset' && !initialResetToken && (
              <div>
                <label
                  htmlFor="zyrq-reset-token"
                  className="mb-1.5 block text-xs font-medium text-[var(--color-text-secondary)]"
                >
                  โทเคนรีเซ็ตรหัสผ่าน
                </label>
                <input
                  id="zyrq-reset-token"
                  type="text"
                  required
                  value={resetToken}
                  onChange={(e) => setResetToken(e.target.value)}
                  placeholder="วางโทเคนจากอีเมลรีเซ็ตรหัสผ่าน"
                  className="h-12 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 font-mono text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                />
              </div>
            )}

            {mode === 'claim' && authStatus.envPasscodeConfigured && (
              <div>
                <label
                  htmlFor="zyrq-passcode"
                  className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-[var(--color-text-secondary)]"
                >
                  <KeyRound className="h-3.5 w-3.5 text-[var(--color-accent)]" />
                  <span>รหัสยืนยันการตั้งค่าเซิร์ฟเวอร์</span>
                </label>
                <input
                  id="zyrq-passcode"
                  type="password"
                  required
                  value={passcode}
                  onChange={(e) => setPasscode(e.target.value)}
                  placeholder="กรอก ZYRQUEN_ADMIN_PASSCODE ที่ตั้งไว้"
                  className="h-12 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                />
              </div>
            )}

            {error && (
              <div
                role="alert"
                className="rounded-xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-3.5 py-2.5 text-sm text-[var(--color-danger)]"
              >
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading || oauthPending !== null}
              className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-[var(--color-primary)] px-5 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-primary-hover)] disabled:opacity-60"
            >
              <span>
                {loading
                  ? 'กำลังตรวจสอบ...'
                  : mode === 'claim'
                    ? 'ตั้งค่าผู้ดูแลและเข้าใช้งาน'
                    : mode === 'register'
                      ? 'สมัครสมาชิกด้วยอีเมล'
                      : mode === 'forgot'
                        ? 'ส่งคำขอรีเซ็ตรหัสผ่าน'
                        : mode === 'reset'
                          ? 'บันทึกรหัสผ่านใหม่'
                          : 'เข้าสู่ระบบ'}
              </span>
              <ArrowRight className="h-4 w-4" />
            </button>

            {(mode === 'forgot' || mode === 'reset') && (
              <button
                type="button"
                onClick={() => switchMode('login')}
                className="w-full py-1 text-center text-xs font-medium text-[var(--color-text-secondary)] hover:text-[var(--color-text)]"
              >
                กลับไปหน้าเข้าสู่ระบบ
              </button>
            )}
          </form>
        </div>
      </div>
    </div>
  );
}
