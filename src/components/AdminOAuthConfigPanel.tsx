import React, { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, Eye, EyeOff, KeyRound, ShieldCheck, Trash2 } from 'lucide-react';
import { apiRequest, ApiError } from '../lib/api';
import type { AdminOAuthConfigResponse, AdminOAuthProviderConfig } from '../types';
import { CopyButton } from './CopyButton';

interface AdminOAuthConfigPanelProps {
  token: string;
}

type OAuthProviderId = 'google' | 'github';

interface ProviderDraft {
  clientId: string;
  clientSecret: string;
  showSecret: boolean;
}

export function AdminOAuthConfigPanel({ token }: AdminOAuthConfigPanelProps) {
  const [loading, setLoading] = useState(true);
  const [savingProvider, setSavingProvider] = useState<OAuthProviderId | null>(null);
  const [clearingProvider, setClearingProvider] = useState<OAuthProviderId | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [configs, setConfigs] = useState<AdminOAuthConfigResponse['providers'] | null>(null);
  const [drafts, setDrafts] = useState<Record<OAuthProviderId, ProviderDraft>>({
    google: { clientId: '', clientSecret: '', showSecret: false },
    github: { clientId: '', clientSecret: '', showSecret: false },
  });

  const syncFromResponse = useCallback((providers: AdminOAuthConfigResponse['providers']) => {
    setConfigs(providers);
    setDrafts((prev) => ({
      google: {
        clientId: providers.google.clientId || '',
        clientSecret: '',
        showSecret: prev.google.showSecret,
      },
      github: {
        clientId: providers.github.clientId || '',
        clientSecret: '',
        showSecret: prev.github.showSecret,
      },
    }));
  }, []);

  const loadConfigs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiRequest<AdminOAuthConfigResponse>('/api/admin/oauth/config', { token });
      if (res.ok && res.providers) {
        syncFromResponse(res.providers);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ไม่สามารถโหลดการตั้งค่า OAuth 2.0 ได้');
    } finally {
      setLoading(false);
    }
  }, [syncFromResponse, token]);

  useEffect(() => {
    let active = true;
    apiRequest<AdminOAuthConfigResponse>('/api/admin/oauth/config', { token })
      .then((res) => {
        if (active && res.ok && res.providers) {
          syncFromResponse(res.providers);
        }
      })
      .catch((err) => {
        if (active) {
          setError(err instanceof ApiError ? err.message : 'ไม่สามารถโหลดการตั้งค่า OAuth 2.0 ได้');
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [syncFromResponse, token]);

  async function handleSave(provider: OAuthProviderId, e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    const draft = drafts[provider];
    const current = configs?.[provider];
    const clientId = draft.clientId.trim();
    const clientSecret = draft.clientSecret.trim();

    if (clientId.length < 8) {
      setError(`กรุณากรอก ${provider === 'google' ? 'Google' : 'GitHub'} Client ID อย่างน้อย 8 ตัวอักษร`);
      return;
    }
    if (!clientSecret && !(current?.source === 'manual' && current?.hasSecret)) {
      setError(`กรุณากรอก ${provider === 'google' ? 'Google' : 'GitHub'} Client Secret`);
      return;
    }

    setSavingProvider(provider);
    try {
      const res = await apiRequest<AdminOAuthConfigResponse>(
        `/api/admin/oauth/config/${provider}`,
        {
          method: 'PUT',
          token,
          body: {
            clientId,
            ...(clientSecret ? { clientSecret } : {}),
          },
        }
      );
      if (res.ok && res.providers) {
        syncFromResponse(res.providers);
        setNotice(
          `บันทึกการตั้งค่า ${provider === 'google' ? 'Google' : 'GitHub'} OAuth 2.0 เรียบร้อยแล้ว`
        );
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'บันทึกการตั้งค่า OAuth 2.0 ไม่สำเร็จ');
    } finally {
      setSavingProvider(null);
    }
  }

  async function handleClear(provider: OAuthProviderId) {
    setError(null);
    setNotice(null);
    setClearingProvider(provider);
    try {
      const res = await apiRequest<AdminOAuthConfigResponse>(
        `/api/admin/oauth/config/${provider}`,
        {
          method: 'DELETE',
          token,
        }
      );
      if (res.ok && res.providers) {
        syncFromResponse(res.providers);
        setNotice(
          `ล้างค่าที่ตั้งเองของ ${provider === 'google' ? 'Google' : 'GitHub'} OAuth 2.0 แล้ว`
        );
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ล้างการตั้งค่า OAuth 2.0 ไม่สำเร็จ');
    } finally {
      setClearingProvider(null);
    }
  }

  function renderProviderCard(provider: OAuthProviderId, cfg?: AdminOAuthProviderConfig) {
    const label = provider === 'google' ? 'Google OAuth 2.0' : 'GitHub OAuth 2.0';
    const draft = drafts[provider];
    const isSaving = savingProvider === provider;
    const isClearing = clearingProvider === provider;
    const statusText = !cfg?.configured
      ? 'ยังไม่ตั้งค่า'
      : cfg.source === 'manual'
        ? 'พร้อมใช้งาน (Admin)'
        : 'พร้อมใช้งาน (Env)';

    return (
      <form
        key={provider}
        onSubmit={(e) => void handleSave(provider, e)}
        className="space-y-3 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-[var(--color-accent)]" />
            <h4 className="text-xs font-semibold text-[var(--color-text)]">{label}</h4>
          </div>
          <span
            className={`rounded-md border px-2 py-0.5 font-mono text-[11px] font-medium ${
              cfg?.configured
                ? 'border-[var(--color-success)]/40 bg-[var(--color-success-bg)] text-[var(--color-success)]'
                : 'border-[var(--color-border)] bg-[var(--color-surface-raised)] text-[var(--color-text-muted)]'
            }`}
          >
            {statusText}
          </span>
        </div>

        {cfg?.callbackUrl && (
          <div className="flex items-center justify-between gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 py-2">
            <div className="min-w-0">
              <p className="text-[10px] font-medium text-[var(--color-text-muted)] uppercase">
                Callback URL
              </p>
              <p className="truncate font-mono text-[11px] text-[var(--color-text-secondary)]">
                {cfg.callbackUrl}
              </p>
            </div>
            <CopyButton
              getText={() => cfg.callbackUrl}
              label="คัดลอก"
              ariaLabel={`คัดลอก Callback URL สำหรับ ${label}`}
              size="xs"
            />
          </div>
        )}

        <div>
          <label
            htmlFor={`oauth-${provider}-client-id`}
            className="mb-1 block text-[11px] font-medium text-[var(--color-text-secondary)]"
          >
            Client ID
          </label>
          <input
            id={`oauth-${provider}-client-id`}
            type="text"
            autoComplete="off"
            spellCheck={false}
            value={draft.clientId}
            onChange={(e) =>
              setDrafts((prev) => ({
                ...prev,
                [provider]: { ...prev[provider], clientId: e.target.value },
              }))
            }
            placeholder={
              provider === 'google'
                ? 'xxxxx.apps.googleusercontent.com'
                : 'Ov23li...'
            }
            className="h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 font-mono text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
          />
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between gap-2">
            <label
              htmlFor={`oauth-${provider}-client-secret`}
              className="block text-[11px] font-medium text-[var(--color-text-secondary)]"
            >
              Client Secret
            </label>
            {cfg?.hasSecret && (
              <span className="font-mono text-[10px] text-[var(--color-text-muted)]">
                บันทึกไว้แล้ว: {cfg.secretMasked || '••••••••'}
              </span>
            )}
          </div>
          <div className="relative">
            <input
              id={`oauth-${provider}-client-secret`}
              type={draft.showSecret ? 'text' : 'password'}
              autoComplete="new-password"
              spellCheck={false}
              value={draft.clientSecret}
              onChange={(e) =>
                setDrafts((prev) => ({
                  ...prev,
                  [provider]: { ...prev[provider], clientSecret: e.target.value },
                }))
              }
              placeholder={
                cfg?.source === 'manual' && cfg?.hasSecret
                  ? '•••••••• (เว้นว่างเพื่อใช้ Secret เดิม)'
                  : 'กรอก Client Secret'
              }
              className="h-10 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] pr-10 pl-3 font-mono text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
            />
            <button
              type="button"
              onClick={() =>
                setDrafts((prev) => ({
                  ...prev,
                  [provider]: { ...prev[provider], showSecret: !prev[provider].showSecret },
                }))
              }
              aria-label={draft.showSecret ? `ซ่อน ${label} Client Secret` : `แสดง ${label} Client Secret`}
              className="absolute inset-y-0 right-0 flex w-9 items-center justify-center text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
            >
              {draft.showSecret ? (
                <EyeOff className="h-3.5 w-3.5" />
              ) : (
                <Eye className="h-3.5 w-3.5" />
              )}
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
          <div className="text-[11px] text-[var(--color-text-muted)]">
            {cfg?.updatedAt
              ? `อัปเดตล่าสุด ${new Date(cfg.updatedAt).toLocaleString('th-TH')}`
              : 'ค่า Client Secret ถูกเข้ารหัสและปิดบังบนเซิร์ฟเวอร์'}
          </div>
          <div className="flex items-center gap-2">
            {cfg?.source === 'manual' && (
              <button
                type="button"
                disabled={isSaving || isClearing}
                onClick={() => void handleClear(provider)}
                className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-3 text-xs font-medium text-[var(--color-text-secondary)] hover:border-[var(--color-danger)] hover:text-[var(--color-danger)] disabled:opacity-50"
              >
                <Trash2 className="h-3.5 w-3.5" />
                <span>{isClearing ? 'กำลังล้าง...' : 'ล้างค่า'}</span>
              </button>
            )}
            <button
              type="submit"
              disabled={isSaving || isClearing}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[var(--color-primary)] px-3.5 text-xs font-medium text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50"
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              <span>{isSaving ? 'กำลังบันทึก...' : 'บันทึก OAuth'}</span>
            </button>
          </div>
        </div>
      </form>
    );
  }

  return (
    <section
      id="admin-oauth-config"
      className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-[var(--color-text)]">
            ตั้งค่า OAuth 2.0 (Google &amp; GitHub)
          </h3>
          <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
            กำหนด Client ID และ Client Secret ด้วยตนเองสำหรับเข้าสู่ระบบ OAuth 2.0 (Secret จะถูกปิดบังในช่องกรอกและเข้ารหัสฝั่งเซิร์ฟเวอร์)
          </p>
        </div>
        <button
          type="button"
          disabled={loading}
          onClick={() => void loadConfigs()}
          className="h-8 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs font-medium text-[var(--color-text-secondary)] hover:border-[var(--color-accent)] hover:text-[var(--color-text)] disabled:opacity-50"
        >
          {loading ? 'กำลังโหลด...' : 'รีเฟรชสถานะ'}
        </button>
      </div>

      {error && (
        <div
          role="alert"
          className="mt-3 rounded-xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-3.5 py-2.5 text-xs text-[var(--color-danger)]"
        >
          {error}
        </div>
      )}

      {notice && (
        <div
          role="status"
          className="mt-3 flex items-center gap-2 rounded-xl border border-[var(--color-success)]/40 bg-[var(--color-success-bg)] px-3.5 py-2.5 text-xs text-[var(--color-success)]"
        >
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span>{notice}</span>
        </div>
      )}

      {loading && !configs ? (
        <p className="mt-4 text-xs text-[var(--color-text-secondary)]">
          กำลังโหลดสถานะผู้ให้บริการ OAuth 2.0...
        </p>
      ) : (
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {renderProviderCard('google', configs?.google)}
          {renderProviderCard('github', configs?.github)}
        </div>
      )}
    </section>
  );
}
