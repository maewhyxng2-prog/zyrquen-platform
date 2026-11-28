"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Icon } from "@/components/Icon";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { apiRequest } from "@/lib/api";

type ProviderId = "google" | "github";

type ProviderConfigEntry = {
  id: ProviderId;
  name: string;
  configured: boolean;
  source: "manual" | "env" | "none";
  clientId: string;
  hasSecret: boolean;
  secretMasked: string;
  callbackUrl: string;
  updatedAt?: string | null;
  updatedBy?: string | null;
};

type AdminOAuthConfigPayload = {
  ok: boolean;
  providers: {
    google: ProviderConfigEntry;
    github: ProviderConfigEntry;
  };
};

type ProviderDraft = {
  clientId: string;
  clientSecret: string;
  showSecret: boolean;
};

export function OAuthProvidersConfigCard({ className }: { className?: string }) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<ProviderId | null>(null);
  const [clearing, setClearing] = useState<ProviderId | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [configs, setConfigs] = useState<AdminOAuthConfigPayload["providers"] | null>(null);
  const [drafts, setDrafts] = useState<Record<ProviderId, ProviderDraft>>({
    google: { clientId: "", clientSecret: "", showSecret: false },
    github: { clientId: "", clientSecret: "", showSecret: false },
  });

  const syncFromPayload = useCallback((providers: AdminOAuthConfigPayload["providers"]) => {
    setConfigs(providers);
    setDrafts((prev) => ({
      google: {
        clientId: providers.google.clientId || "",
        clientSecret: "",
        showSecret: prev.google.showSecret,
      },
      github: {
        clientId: providers.github.clientId || "",
        clientSecret: "",
        showSecret: prev.github.showSecret,
      },
    }));
  }, []);

  const loadConfig = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const payload = await apiRequest<AdminOAuthConfigPayload>("admin/oauth/config");
      if (payload.providers) {
        syncFromPayload(payload.providers);
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "ไม่สามารถโหลดการตั้งค่า OAuth 2.0 ได้",
      );
    } finally {
      setLoading(false);
    }
  }, [syncFromPayload]);

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  async function handleSave(provider: ProviderId, event: FormEvent) {
    event.preventDefault();
    setError("");
    setNotice("");
    const draft = drafts[provider];
    const current = configs?.[provider];
    const clientId = draft.clientId.trim();
    const clientSecret = draft.clientSecret.trim();

    if (clientId.length < 8) {
      setError(`กรุณากรอก ${provider === "google" ? "Google" : "GitHub"} Client ID อย่างน้อย 8 ตัวอักษร`);
      return;
    }
    if (!clientSecret && !(current?.source === "manual" && current?.hasSecret)) {
      setError(`กรุณากรอก ${provider === "google" ? "Google" : "GitHub"} Client Secret`);
      return;
    }

    setSaving(provider);
    try {
      const payload = await apiRequest<AdminOAuthConfigPayload>(
        `admin/oauth/config/${provider}`,
        {
          method: "PUT",
          body: JSON.stringify({
            clientId,
            ...(clientSecret ? { clientSecret } : {}),
          }),
        },
      );
      if (payload.providers) {
        syncFromPayload(payload.providers);
        setNotice(`บันทึก ${provider === "google" ? "Google" : "GitHub"} OAuth 2.0 แล้ว`);
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "บันทึกการตั้งค่า OAuth 2.0 ไม่สำเร็จ",
      );
    } finally {
      setSaving(null);
    }
  }

  async function handleClear(provider: ProviderId) {
    setError("");
    setNotice("");
    setClearing(provider);
    try {
      const payload = await apiRequest<AdminOAuthConfigPayload>(
        `admin/oauth/config/${provider}`,
        { method: "DELETE" },
      );
      if (payload.providers) {
        syncFromPayload(payload.providers);
        setNotice(`ล้างค่า ${provider === "google" ? "Google" : "GitHub"} OAuth 2.0 แล้ว`);
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "ล้างการตั้งค่า OAuth 2.0 ไม่สำเร็จ",
      );
    } finally {
      setClearing(null);
    }
  }

  function renderProviderForm(provider: ProviderId, cfg?: ProviderConfigEntry) {
    const label = provider === "google" ? "Google OAuth 2.0" : "GitHub OAuth 2.0";
    const draft = drafts[provider];
    const isBusy = saving === provider || clearing === provider;

    return (
      <form
        className="settings-form"
        key={provider}
        onSubmit={(event) => void handleSave(provider, event)}
      >
        <div className="panel-heading">
          <div>
            <div className="eyebrow">{provider.toUpperCase()} OAUTH 2.0</div>
            <h3>{label}</h3>
          </div>
          <StatusBadge
            icon={cfg?.configured ? "check-circle" : undefined}
            tone={cfg?.configured ? "good" : "neutral"}
          >
            {!cfg?.configured
              ? "ยังไม่ตั้งค่า"
              : cfg.source === "manual"
                ? "Configured (Admin)"
                : "Configured (Env)"}
          </StatusBadge>
        </div>

        <div className="settings-form-grid">
          <div className="settings-field">
            <label htmlFor={`apps-web-oauth-${provider}-id`}>Client ID</label>
            <input
              autoComplete="off"
              className="settings-input"
              id={`apps-web-oauth-${provider}-id`}
              onChange={(event) =>
                setDrafts((prev) => ({
                  ...prev,
                  [provider]: { ...prev[provider], clientId: event.target.value },
                }))
              }
              placeholder={provider === "google" ? "xxxxx.apps.googleusercontent.com" : "Ov23li..."}
              spellCheck={false}
              type="text"
              value={draft.clientId}
            />
          </div>

          <div className="settings-field">
            <label htmlFor={`apps-web-oauth-${provider}-secret`}>
              Client Secret{" "}
              {cfg?.hasSecret ? `(${cfg.secretMasked || "••••••••"})` : ""}
            </label>
            <div className="workflow-actions">
              <input
                autoComplete="new-password"
                className="settings-input"
                id={`apps-web-oauth-${provider}-secret`}
                onChange={(event) =>
                  setDrafts((prev) => ({
                    ...prev,
                    [provider]: { ...prev[provider], clientSecret: event.target.value },
                  }))
                }
                placeholder={
                  cfg?.source === "manual" && cfg?.hasSecret
                    ? "•••••••• (เว้นว่างเพื่อใช้ Secret เดิม)"
                    : "กรอก Client Secret"
                }
                spellCheck={false}
                type={draft.showSecret ? "text" : "password"}
                value={draft.clientSecret}
              />
              <button
                className="button button-secondary button-compact"
                onClick={() =>
                  setDrafts((prev) => ({
                    ...prev,
                    [provider]: { ...prev[provider], showSecret: !prev[provider].showSecret },
                  }))
                }
                type="button"
              >
                {draft.showSecret ? "Hide" : "Show"}
              </button>
            </div>
          </div>
        </div>

        <div className="panel-link-row">
          <small>
            Callback URL: <code>{cfg?.callbackUrl ?? "—"}</code>
          </small>
          <div className="workflow-actions">
            {cfg?.source === "manual" ? (
              <button
                className="button button-secondary button-compact"
                disabled={isBusy}
                onClick={() => void handleClear(provider)}
                type="button"
              >
                ล้างค่า
              </button>
            ) : null}
            <button
              className="button button-primary button-compact"
              disabled={isBusy}
              type="submit"
            >
              <Icon name="shield" size={14} />
              {saving === provider ? "กำลังบันทึก..." : "บันทึก OAuth"}
            </button>
          </div>
        </div>
      </form>
    );
  }

  return (
    <Panel className={className}>
      <div className="panel-heading">
        <div>
          <div className="eyebrow">AUTHENTICATION PROVIDERS</div>
          <h2>ตั้งค่า Google และ GitHub OAuth 2.0</h2>
        </div>
        <button
          className="button button-secondary button-compact"
          disabled={loading}
          onClick={() => void loadConfig()}
          type="button"
        >
          {loading ? "กำลังโหลด..." : "Refresh"}
        </button>
      </div>

      {error ? (
        <p className="form-alert form-alert-error" role="alert">
          <Icon name="close" size={15} />
          <span>{error}</span>
        </p>
      ) : null}

      {notice ? (
        <p className="form-alert form-alert-success" role="status">
          <Icon name="check-circle" size={15} />
          <span>{notice}</span>
        </p>
      ) : null}

      {loading && !configs ? (
        <div className="unavailable-block" role="status">
          <strong>กำลังโหลดสถานะ OAuth 2.0...</strong>
        </div>
      ) : (
        <div className="readiness-list">
          {renderProviderForm("google", configs?.google)}
          {renderProviderForm("github", configs?.github)}
        </div>
      )}
    </Panel>
  );
}
