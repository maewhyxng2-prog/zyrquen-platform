import React, { useState } from 'react';
import { ArrowRight, Eye, EyeOff, KeyRound, Moon, ShieldCheck, Sun, UserPlus } from 'lucide-react';
import { apiRequest, ApiError } from '../lib/api';
import { useZyrquenTheme } from '../lib/theme';
import type { AuthStatus, User } from '../types';
import { SpacetimeFabric } from './SpacetimeFabric';
import { TemporalIntelligenceCore } from './TemporalIntelligenceCore';

interface AuthGateProps {
  authStatus: AuthStatus;
  onAuthenticated: (token: string, user: User) => void;
}

export function AuthGate({ authStatus, onAuthenticated }: AuthGateProps) {
  const { theme, toggleTheme } = useZyrquenTheme();
  const [mode, setMode] = useState<'claim' | 'login' | 'register'>(
    authStatus.initialized ? 'login' : 'claim'
  );
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [passcode, setPasscode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function switchMode(nextMode: 'claim' | 'login' | 'register') {
    setMode(nextMode);
    setError(null);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (mode === 'register') {
      if (displayName.trim().length < 2) {
        setError('ชื่อที่แสดงต้องมีอย่างน้อย 2 ตัวอักษร');
        return;
      }
      if (password.length < 8) {
        setError('รหัสผ่านต้องมีความยาวอย่างน้อย 8 ตัวอักษร');
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
        const res = await apiRequest<{ token: string; user: User }>('/api/auth/register', {
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

  const isCompactHero = mode === 'register';

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
            active={loading}
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

          {authStatus.initialized ? (
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
          )}

          {mode === 'claim' && !authStatus.initialized && (
            <div className="mb-5 flex items-center gap-2.5 text-sm font-medium text-[var(--color-accent)]">
              <ShieldCheck className="h-4 w-4 shrink-0" />
              <span>ตั้งค่าผู้ดูแลระบบเริ่มต้น</span>
            </div>
          )}

          {mode === 'register' && (
            <div className="mb-5 flex items-center gap-2.5 text-sm font-medium text-[var(--color-accent)]">
              <UserPlus className="h-4 w-4 shrink-0" />
              <span>สมัครสมาชิกใหม่ (บัญชีผู้ใช้งานทั่วไป)</span>
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
                  placeholder={mode === 'claim' ? 'หัวหน้าทีมวิจัย' : 'ชื่อของคุณ (อย่างน้อย 2 ตัวอักษร)'}
                  className="h-12 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
                />
              </div>
            )}

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
                placeholder="operator@zyrquen.local"
                className="h-12 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
              />
            </div>

            <div>
              <label
                htmlFor="zyrq-password"
                className="mb-1.5 block text-xs font-medium text-[var(--color-text-secondary)]"
              >
                รหัสผ่าน
              </label>
              <div className="relative">
                <input
                  id="zyrq-password"
                  type={showPassword ? 'text' : 'password'}
                  required
                  minLength={8}
                  maxLength={256}
                  autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="อย่างน้อย 8 ตัวอักษร"
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

            {mode === 'register' && (
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
                  minLength={8}
                  maxLength={256}
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="กรอกรหัสผ่านซ้ำอีกครั้ง"
                  className="h-12 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
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
              disabled={loading}
              className="flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-[var(--color-primary)] px-5 text-sm font-semibold text-white transition-colors hover:bg-[var(--color-primary-hover)] disabled:opacity-60"
            >
              <span>
                {loading
                  ? 'กำลังตรวจสอบ...'
                  : mode === 'claim'
                    ? 'ตั้งค่าผู้ดูแลและเข้าใช้งาน'
                    : mode === 'register'
                      ? 'สมัครสมาชิก'
                      : 'เข้าสู่ระบบ'}
              </span>
              <ArrowRight className="h-4 w-4" />
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
