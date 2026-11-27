"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { ApiKeyUsageChart } from "@/components/ApiKeyUsageChart";
import { DeveloperNav } from "@/components/DeveloperNav";
import { Icon } from "@/components/Icon";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { readSession } from "@/lib/api";
import {
  AUTO_ROTATE_PRESETS,
  bulkRevokeApiKeys,
  createApiKey,
  getApiKeyUsage,
  listApiKeys,
  revokeApiKey,
  rotateApiKey,
  updateApiKeyAutoRotate,
  validateAutoRotateInterval,
} from "@/lib/api-access";
import { belongsToAccount } from "@/lib/user-state";
import type { ApiKeyMetadata, ApiKeyUsage, Session } from "@/lib/types";

function draftFromKey(key: ApiKeyMetadata): {
  enabled: boolean;
  preset: string;
  customDays: string;
} {
  const days = key.autoRotateIntervalDays ?? 30;
  const isPreset = (AUTO_ROTATE_PRESETS as readonly number[]).includes(days);
  return {
    enabled: key.autoRotateEnabled,
    preset: isPreset ? String(days) : "custom",
    customDays: String(days),
  };
}

function buildRotateDraftMap(keys: ApiKeyMetadata[]) {
  const next: Record<
    string,
    { enabled: boolean; preset: string; customDays: string }
  > = {};
  for (const key of keys) {
    next[key.id] = draftFromKey(key);
  }
  return next;
}

function resolveIntervalDays(
  enabled: boolean,
  preset: string,
  customDays: string,
): number | null {
  if (!enabled) return null;
  const raw = preset === "custom" ? customDays : preset;
  const parsed = Number(raw);
  return Number.isInteger(parsed) ? parsed : Number.NaN;
}

export default function DeveloperApiKeysPage() {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const sessionRef = useRef<Session | null>(null);
  const [sessionReady, setSessionReady] = useState(false);

  const [apiKeys, setApiKeys] = useState<ApiKeyMetadata[]>([]);
  const [apiKeysLoading, setApiKeysLoading] = useState(true);
  const [apiKeysOwnerId, setApiKeysOwnerId] = useState<string | null>(null);
  const [apiKeysError, setApiKeysError] = useState("");
  const [apiKeysNotice, setApiKeysNotice] = useState("");
  const [apiKeyName, setApiKeyName] = useState("");
  const [apiKeyExpiresAt, setApiKeyExpiresAt] = useState("");
  const [createAutoRotateEnabled, setCreateAutoRotateEnabled] = useState(true);
  const [createRotatePreset, setCreateRotatePreset] = useState<string>("30");
  const [createRotateCustomDays, setCreateRotateCustomDays] =
    useState<string>("30");
  const [apiKeySaving, setApiKeySaving] = useState(false);
  const apiKeySavingRef = useRef(false);
  const [newApiKey, setNewApiKey] = useState("");
  const [newApiKeyLabel, setNewApiKeyLabel] = useState("");
  const [newApiKeyOwnerId, setNewApiKeyOwnerId] = useState<string | null>(null);
  const [copiedSecret, setCopiedSecret] = useState(false);
  const [revokingApiKeyId, setRevokingApiKeyId] = useState<string | null>(null);
  const [rotatingApiKeyId, setRotatingApiKeyId] = useState<string | null>(null);
  const [savingScheduleKeyId, setSavingScheduleKeyId] = useState<string | null>(
    null,
  );
  const [rotateDrafts, setRotateDrafts] = useState<
    Record<string, { enabled: boolean; preset: string; customDays: string }>
  >({});
  const [apiKeyUsage, setApiKeyUsage] = useState<ApiKeyUsage | null>(null);
  const [selectedUsageKeyId, setSelectedUsageKeyId] = useState<string | null>(
    null,
  );
  const [apiKeyUsageOwnerId, setApiKeyUsageOwnerId] = useState<string | null>(
    null,
  );
  const [apiKeyUsageLoadingId, setApiKeyUsageLoadingId] = useState<
    string | null
  >(null);
  const [apiKeyUsageError, setApiKeyUsageError] = useState("");
  const [selectedKeyIds, setSelectedKeyIds] = useState<string[]>([]);
  const [bulkConfirmOpen, setBulkConfirmOpen] = useState(false);
  const [bulkRevoking, setBulkRevoking] = useState(false);

  useEffect(() => {
    const refreshSession = () => {
      readSession()
        .then((current) => {
          if (sessionRef.current?.userId !== current.userId) {
            setApiKeys([]);
            setApiKeysOwnerId(null);
            setApiKeysLoading(true);
            setNewApiKey("");
            setNewApiKeyLabel("");
            setNewApiKeyOwnerId(null);
            setApiKeysNotice("");
            setRotateDrafts({});
            setApiKeyUsage(null);
            setSelectedUsageKeyId(null);
            setApiKeyUsageOwnerId(null);
            setApiKeyUsageError("");
            setSelectedKeyIds([]);
            setBulkConfirmOpen(false);
          }
          sessionRef.current = current;
          setSession(current);
          setSessionReady(true);
        })
        .catch(() => {
          setApiKeys([]);
          setApiKeysOwnerId(null);
          setApiKeysLoading(true);
          setNewApiKey("");
          setNewApiKeyLabel("");
          setNewApiKeyOwnerId(null);
          setApiKeysNotice("");
          setRotateDrafts({});
          setApiKeyUsage(null);
          setSelectedUsageKeyId(null);
          setApiKeyUsageOwnerId(null);
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
    return () =>
      window.removeEventListener("zyrquen:session-change", refreshSession);
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

    void listApiKeys(ownerId)
      .then((keys) => {
        if (!isCurrentOwner()) return;
        setApiKeys(keys);
        setRotateDrafts(buildRotateDraftMap(keys));
        setApiKeysError("");
        const initialKey = keys.find((k) => !k.revokedAt) ?? keys[0] ?? null;
        if (initialKey) {
          setSelectedUsageKeyId(initialKey.id);
          setApiKeyUsageLoadingId(initialKey.id);
          void getApiKeyUsage(ownerId, initialKey.id)
            .then((initialUsage) => {
              if (!isCurrentOwner()) return;
              setApiKeyUsage(initialUsage);
              setApiKeyUsageOwnerId(ownerId);
              setApiKeyUsageError("");
            })
            .catch((reason: unknown) => {
              if (!isCurrentOwner()) return;
              setApiKeyUsageError(
                reason instanceof Error
                  ? reason.message
                  : "ไม่สามารถโหลด Usage ของ API Key ได้",
              );
            })
            .finally(() => {
              if (!isCurrentOwner()) return;
              setApiKeyUsageLoadingId(null);
            });
        } else {
          setSelectedUsageKeyId(null);
          setApiKeyUsage(null);
        }
      })
      .catch((reason: unknown) => {
        if (!isCurrentOwner()) return;
        setApiKeys([]);
        setApiKeysError(
          reason instanceof Error
            ? reason.message
            : "ไม่สามารถโหลดรายการ API Key ได้",
        );
      })
      .finally(() => {
        if (!isCurrentOwner()) return;
        setApiKeysOwnerId(ownerId);
        setApiKeysLoading(false);
      });

    return () => {
      active = false;
    };
  }, [sessionReady, session?.authenticated, session?.userId]);

  async function submitApiKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ownerId = session?.userId;
    const expiry = new Date(apiKeyExpiresAt);
    if (!ownerId || sessionRef.current?.userId !== ownerId) {
      setApiKeysError("ไม่สามารถยืนยันบัญชีผู้ใช้ปัจจุบันได้");
      return;
    }
    if (
      !apiKeyName.trim() ||
      Number.isNaN(expiry.getTime()) ||
      expiry <= new Date()
    ) {
      setApiKeysError("กรุณาระบุชื่อและวันหมดอายุในอนาคต");
      return;
    }
    const intervalDays = resolveIntervalDays(
      createAutoRotateEnabled,
      createRotatePreset,
      createRotateCustomDays,
    );
    const scheduleError = validateAutoRotateInterval(
      createAutoRotateEnabled,
      intervalDays,
    );
    if (scheduleError) {
      setApiKeysError(scheduleError);
      return;
    }
    if (apiKeySavingRef.current) return;
    apiKeySavingRef.current = true;
    setApiKeySaving(true);
    setApiKeysError("");
    setApiKeysNotice("");
    setNewApiKey("");
    setNewApiKeyLabel("");
    setCopiedSecret(false);
    try {
      const created = await createApiKey(
        ownerId,
        apiKeyName.trim(),
        expiry.toISOString(),
        {
          enabled: createAutoRotateEnabled,
          intervalDays,
        },
      );
      const verifiedSession = await readSession();
      if (!verifiedSession.authenticated || verifiedSession.userId !== ownerId) {
        throw new Error("บัญชีผู้ใช้เปลี่ยนระหว่างสร้าง API Key");
      }
      const nextKeys = [created, ...apiKeys];
      setApiKeys(nextKeys);
      setRotateDrafts((prev) => ({
        ...prev,
        [created.id]: draftFromKey(created),
      }));
      setNewApiKey(created.key);
      setNewApiKeyLabel(`สร้าง API Key "${created.name}" แล้ว`);
      setNewApiKeyOwnerId(ownerId);
      setApiKeyName("");
      setApiKeyExpiresAt("");
    } catch (reason) {
      if (sessionRef.current?.userId !== ownerId) return;
      setApiKeysError(
        reason instanceof Error ? reason.message : "ไม่สามารถสร้าง API Key ได้",
      );
    } finally {
      apiKeySavingRef.current = false;
      setApiKeySaving(false);
    }
  }

  async function saveAutoRotateSchedule(key: ApiKeyMetadata) {
    const ownerId = session?.userId;
    if (!ownerId || sessionRef.current?.userId !== ownerId) {
      setApiKeysError("ไม่สามารถยืนยันบัญชีผู้ใช้ปัจจุบันได้");
      return;
    }
    const draft = rotateDrafts[key.id] ?? draftFromKey(key);
    const intervalDays = resolveIntervalDays(
      draft.enabled,
      draft.preset,
      draft.customDays,
    );
    const validationError = validateAutoRotateInterval(
      draft.enabled,
      intervalDays,
    );
    if (validationError) {
      setApiKeysError(validationError);
      return;
    }
    setSavingScheduleKeyId(key.id);
    setApiKeysError("");
    setApiKeysNotice("");
    try {
      const updated = await updateApiKeyAutoRotate(
        ownerId,
        key.id,
        draft.enabled,
        intervalDays,
      );
      const verifiedSession = await readSession();
      if (!verifiedSession.authenticated || verifiedSession.userId !== ownerId) {
        throw new Error("บัญชีผู้ใช้เปลี่ยนระหว่างอัปเดตตาราง Auto-rotate");
      }
      setApiKeys((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setRotateDrafts((current) => ({
        ...current,
        [updated.id]: draftFromKey(updated),
      }));
      setApiKeysNotice(
        updated.autoRotateEnabled && updated.autoRotateIntervalDays
          ? `ตั้งค่า Auto-rotate สำหรับ "${updated.name}" ทุก ${updated.autoRotateIntervalDays} วันแล้ว`
          : `ปิด Auto-rotate สำหรับ "${updated.name}" แล้ว`,
      );
    } catch (reason) {
      if (sessionRef.current?.userId !== ownerId) return;
      setApiKeysError(
        reason instanceof Error
          ? reason.message
          : "ไม่สามารถบันทึกตาราง Auto-rotate ได้",
      );
    } finally {
      setSavingScheduleKeyId(null);
    }
  }

  async function rotateKeyNow(key: ApiKeyMetadata) {
    const ownerId = session?.userId;
    if (!ownerId || sessionRef.current?.userId !== ownerId) {
      setApiKeysError("ไม่สามารถยืนยันบัญชีผู้ใช้ปัจจุบันได้");
      return;
    }
    setRotatingApiKeyId(key.id);
    setApiKeysError("");
    setApiKeysNotice("");
    setCopiedSecret(false);
    try {
      const rotated = await rotateApiKey(ownerId, key.id);
      const verifiedSession = await readSession();
      if (!verifiedSession.authenticated || verifiedSession.userId !== ownerId) {
        throw new Error("บัญชีผู้ใช้เปลี่ยนระหว่างหมุนเวียน API Key");
      }
      setApiKeys((current) =>
        current.map((item) => (item.id === rotated.id ? rotated : item)),
      );
      setRotateDrafts((current) => ({
        ...current,
        [rotated.id]: draftFromKey(rotated),
      }));
      setNewApiKey(rotated.key);
      setNewApiKeyLabel(
        `หมุนเวียนคีย์ "${rotated.name}" สำเร็จ (ครั้งที่ ${rotated.rotationCount})`,
      );
      setNewApiKeyOwnerId(ownerId);
    } catch (reason) {
      if (sessionRef.current?.userId !== ownerId) return;
      setApiKeysError(
        reason instanceof Error
          ? reason.message
          : "ไม่สามารถหมุนเวียน API Key ได้",
      );
    } finally {
      setRotatingApiKeyId(null);
    }
  }

  async function copyNewSecret() {
    if (!newApiKey) return;
    try {
      await navigator.clipboard.writeText(newApiKey);
      setCopiedSecret(true);
    } catch {
      setCopiedSecret(false);
    }
  }

  async function removeApiKey(keyId: string) {
    const ownerId = session?.userId;
    if (!ownerId || sessionRef.current?.userId !== ownerId) {
      setApiKeysError("ไม่สามารถยืนยันบัญชีผู้ใช้ปัจจุบันได้");
      return;
    }
    setRevokingApiKeyId(keyId);
    setApiKeysError("");
    setApiKeysNotice("");
    try {
      await revokeApiKey(ownerId, keyId);
      const verifiedSession = await readSession();
      if (!verifiedSession.authenticated || verifiedSession.userId !== ownerId) {
        throw new Error("บัญชีผู้ใช้เปลี่ยนระหว่างเพิกถอน API Key");
      }
      const nextKeys = await listApiKeys(ownerId);
      setApiKeys(nextKeys);
      setRotateDrafts(buildRotateDraftMap(nextKeys));
      setNewApiKey("");
      setNewApiKeyLabel("");
    } catch (reason) {
      if (sessionRef.current?.userId !== ownerId) return;
      setApiKeysError(
        reason instanceof Error
          ? reason.message
          : "ไม่สามารถเพิกถอน API Key ได้",
      );
    } finally {
      setRevokingApiKeyId(null);
    }
  }

  async function confirmBulkRevoke() {
    const ownerId = session?.userId;
    if (!ownerId || sessionRef.current?.userId !== ownerId) {
      setApiKeysError("ไม่สามารถยืนยันบัญชีผู้ใช้ปัจจุบันได้");
      return;
    }
    const activeSelected = selectedKeyIds.filter((id) =>
      apiKeys.some((k) => k.id === id && !k.revokedAt),
    );
    if (activeSelected.length === 0) {
      setBulkConfirmOpen(false);
      setSelectedKeyIds([]);
      return;
    }
    setBulkRevoking(true);
    setApiKeysError("");
    setApiKeysNotice("");
    try {
      const result = await bulkRevokeApiKeys(ownerId, activeSelected);
      const verifiedSession = await readSession();
      if (!verifiedSession.authenticated || verifiedSession.userId !== ownerId) {
        throw new Error("บัญชีผู้ใช้เปลี่ยนระหว่างเพิกถอน API Keys");
      }
      const nextKeys = await listApiKeys(ownerId);
      setApiKeys(nextKeys);
      setRotateDrafts(buildRotateDraftMap(nextKeys));
      setSelectedKeyIds([]);
      setBulkConfirmOpen(false);
      setNewApiKey("");
      setNewApiKeyLabel("");
      setApiKeysNotice(`เพิกถอน API Keys จำนวน ${result.revokedCount} รายการแล้ว`);
    } catch (reason) {
      if (sessionRef.current?.userId !== ownerId) return;
      setApiKeysError(
        reason instanceof Error
          ? reason.message
          : "ไม่สามารถเพิกถอน API Keys แบบกลุ่มได้",
      );
    } finally {
      setBulkRevoking(false);
    }
  }

  async function loadApiKeyUsage(keyId: string) {
    const ownerId = session?.userId;
    if (!ownerId || sessionRef.current?.userId !== ownerId) {
      setApiKeysError("ไม่สามารถยืนยันบัญชีผู้ใช้ปัจจุบันได้");
      return;
    }
    setSelectedUsageKeyId(keyId);
    setApiKeyUsageLoadingId(keyId);
    setApiKeyUsageError("");
    setApiKeyUsage(null);
    setApiKeyUsageOwnerId(null);
    try {
      const usage = await getApiKeyUsage(ownerId, keyId);
      if (sessionRef.current?.userId !== ownerId) return;
      setApiKeyUsage(usage);
      setApiKeyUsageOwnerId(ownerId);
    } catch (reason) {
      if (sessionRef.current?.userId !== ownerId) return;
      setApiKeyUsageError(
        reason instanceof Error
          ? reason.message
          : "ไม่สามารถโหลด Usage ของ API Key ได้",
      );
    } finally {
      setApiKeyUsageLoadingId(null);
    }
  }

  if (!sessionReady || !session?.authenticated) {
    return (
      <div className="page-stack">
        <PageHeader
          description="สร้าง หมุนเวียน และติดตามปริมาณการใช้งาน API Keys สำหรับการเชื่อมต่อ Native Inference"
          eyebrow="DEVELOPER & ADVANCED / API KEYS"
          icon="key"
          title="API Keys"
        />
        <DeveloperNav />
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
                  : "จำเป็นต้องเข้าสู่ระบบเพื่อจัดการ API Keys"}
            </strong>
            <p>
              {!sessionReady
                ? "ระบบกำลังยืนยันตัวตนเพื่อปกป้อง API Keys ประจำบัญชี"
                : session?.error ||
                  "กรุณาเข้าสู่ระบบด้วยบัญชีของคุณก่อนสร้างหรือหมุนเวียน API Keys"}
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

  const apiKeysAreLoading =
    apiKeysLoading || !belongsToAccount(apiKeysOwnerId, session.userId);
  const activeApiKeys = apiKeys.filter((k) => !k.revokedAt);
  const selectedActiveKeyIds = selectedKeyIds.filter((id) =>
    activeApiKeys.some((k) => k.id === id),
  );
  const allActiveSelected =
    activeApiKeys.length > 0 &&
    selectedActiveKeyIds.length === activeApiKeys.length;

  return (
    <div className="page-stack">
      <PageHeader
        description="สร้าง API Key ตั้งรอบหมุนเวียนอัตโนมัติ (Auto-rotate) เพิกถอนคีย์ และดูกราฟการใช้งาน 7 วันล่าสุด"
        eyebrow="DEVELOPER & ADVANCED / API KEYS"
        icon="key"
        title="API Keys สำหรับ Native Inference"
      />

      <DeveloperNav />

      <Panel className="settings-panel-wide">
        <div className="panel-heading">
          <div>
            <div className="eyebrow">การเข้าถึง API</div>
            <h2>จัดการคีย์ประจำบัญชี ({session.email || "เข้าสู่ระบบแล้ว"})</h2>
          </div>
          <span className="metric-icon metric-icon-cyan">
            <Icon name="key" />
          </span>
        </div>
        {apiKeysAreLoading ? (
          <p className="settings-confirmation" role="status">
            กำลังโหลด API Key จาก Backend...
          </p>
        ) : !belongsToAccount(apiKeysOwnerId, session.userId) ? (
          <p className="settings-confirmation" role="status">
            กำลังยืนยันบัญชีเพื่อแสดง API Key
          </p>
        ) : (
          <>
            <form
              className="settings-form"
              onSubmit={(event) => void submitApiKey(event)}
            >
              <div className="settings-form-grid">
                <div className="settings-field">
                  <label htmlFor="api-key-name">ชื่อ API Key</label>
                  <input
                    id="api-key-name"
                    className="settings-input"
                    value={apiKeyName}
                    maxLength={80}
                    placeholder="เช่น production-worker"
                    onChange={(event) => setApiKeyName(event.target.value)}
                    disabled={apiKeySaving}
                    required
                  />
                </div>
                <div className="settings-field">
                  <label htmlFor="api-key-expires">วันหมดอายุ</label>
                  <input
                    id="api-key-expires"
                    className="settings-input"
                    type="datetime-local"
                    value={apiKeyExpiresAt}
                    onChange={(event) => setApiKeyExpiresAt(event.target.value)}
                    disabled={apiKeySaving}
                    required
                  />
                </div>
              </div>
              <div className="settings-field">
                <label
                  className="settings-checkbox-row"
                  htmlFor="api-key-auto-rotate"
                >
                  <input
                    id="api-key-auto-rotate"
                    type="checkbox"
                    checked={createAutoRotateEnabled}
                    disabled={apiKeySaving}
                    onChange={(event) =>
                      setCreateAutoRotateEnabled(event.target.checked)
                    }
                  />
                  <span>เปิดใช้ Auto-rotate (หมุนเวียนคีย์อัตโนมัติตามกำหนด)</span>
                </label>
                {createAutoRotateEnabled && (
                  <div className="settings-rotate-fields">
                    <select
                      id="api-key-rotate-preset"
                      aria-label="รอบเวลา Auto-rotate"
                      className="settings-select"
                      value={createRotatePreset}
                      disabled={apiKeySaving}
                      onChange={(event) =>
                        setCreateRotatePreset(event.target.value)
                      }
                    >
                      {AUTO_ROTATE_PRESETS.map((days) => (
                        <option key={days} value={String(days)}>
                          หมุนเวียนอัตโนมัติทุก {days} วัน
                        </option>
                      ))}
                      <option value="custom">กำหนดจำนวนวันเอง (1–365 วัน)</option>
                    </select>
                    {createRotatePreset === "custom" && (
                      <input
                        id="api-key-rotate-days"
                        aria-label="จำนวนวัน Auto-rotate"
                        className="settings-input"
                        type="number"
                        min={1}
                        max={365}
                        value={createRotateCustomDays}
                        disabled={apiKeySaving}
                        onChange={(event) =>
                          setCreateRotateCustomDays(event.target.value)
                        }
                      />
                    )}
                  </div>
                )}
              </div>
              <button
                className="button button-primary"
                type="submit"
                disabled={apiKeySaving}
              >
                <Icon name="plus" size={15} />
                {apiKeySaving ? "กำลังสร้าง..." : "สร้าง API Key"}
              </button>
            </form>
            {newApiKey &&
              belongsToAccount(newApiKeyOwnerId, session.userId) && (
                <div className="settings-secret-banner" role="status">
                  <strong>
                    {newApiKeyLabel || "สร้าง API Key แล้ว"} · คัดลอกไว้ ข้อมูลลับจะแสดงเพียงครั้งเดียว
                  </strong>
                  <div className="settings-secret-row">
                    <code>{newApiKey}</code>
                    <button
                      className="button button-secondary"
                      type="button"
                      onClick={() => void copyNewSecret()}
                    >
                      {copiedSecret ? "คัดลอกแล้ว" : "คัดลอกคีย์"}
                    </button>
                  </div>
                </div>
              )}
            {apiKeysNotice && (
              <p className="settings-confirmation" role="status">
                <Icon name="check-circle" size={15} /> {apiKeysNotice}
              </p>
            )}
            {apiKeys.length === 0 ? (
              <p className="settings-key-meta">ยังไม่มี API Key ที่บันทึกไว้</p>
            ) : (
              <div className="settings-key-list">
                {activeApiKeys.length > 0 && (
                  <div
                    className="settings-key-head"
                    style={{
                      paddingBottom: "8px",
                      borderBottom: "1px solid var(--line)",
                    }}
                  >
                    <label
                      className="settings-checkbox-row"
                      htmlFor="api-keys-select-all"
                    >
                      <input
                        checked={allActiveSelected}
                        disabled={bulkRevoking}
                        id="api-keys-select-all"
                        onChange={(event) => {
                          if (event.target.checked) {
                            setSelectedKeyIds(activeApiKeys.map((k) => k.id));
                          } else {
                            setSelectedKeyIds([]);
                          }
                        }}
                        type="checkbox"
                      />
                      <span>
                        เลือกทั้งหมด ({selectedActiveKeyIds.length}/{activeApiKeys.length})
                      </span>
                    </label>
                    {selectedActiveKeyIds.length > 0 && (
                      <button
                        className="button button-danger"
                        disabled={bulkRevoking}
                        onClick={() => setBulkConfirmOpen(true)}
                        type="button"
                      >
                        Bulk Revoke ({selectedActiveKeyIds.length})
                      </button>
                    )}
                  </div>
                )}
                {apiKeys.map((key) => {
                  const draft = rotateDrafts[key.id] ?? draftFromKey(key);
                  const draftIntervalDays = resolveIntervalDays(
                    draft.enabled,
                    draft.preset,
                    draft.customDays,
                  );
                  const hasScheduleChanges =
                    draft.enabled !== key.autoRotateEnabled ||
                    (draft.enabled &&
                      draftIntervalDays !== key.autoRotateIntervalDays);
                  const isSelected = selectedActiveKeyIds.includes(key.id);
                  return (
                    <div className="settings-key-card" key={key.id}>
                      <div className="settings-key-head">
                        <label
                          className="settings-checkbox-row"
                          htmlFor={`select-api-key-${key.id}`}
                        >
                          <input
                            aria-label={`Select API Key ${key.name}`}
                            checked={isSelected}
                            disabled={Boolean(key.revokedAt) || bulkRevoking}
                            id={`select-api-key-${key.id}`}
                            onChange={(event) => {
                              setSelectedKeyIds((prev) =>
                                event.target.checked
                                  ? [...new Set([...prev, key.id])]
                                  : prev.filter((id) => id !== key.id),
                              );
                            }}
                            type="checkbox"
                          />
                          <strong>{key.name}</strong>
                        </label>
                        <StatusBadge
                          tone={
                            key.revokedAt
                              ? "bad"
                              : key.autoRotateEnabled
                                ? "info"
                                : "neutral"
                          }
                        >
                          {key.revokedAt
                            ? "เพิกถอนแล้ว"
                            : key.autoRotateEnabled && key.autoRotateIntervalDays
                              ? `Auto-rotate ทุก ${key.autoRotateIntervalDays} วัน`
                              : "ปิด Auto-rotate"}
                        </StatusBadge>
                      </div>
                      <code>
                        {key.keyPrefix}… · {key.scope}
                      </code>
                      <p className="settings-key-meta">
                        หมดอายุ {new Date(key.expiresAt).toLocaleString("th-TH")}
                        {key.lastRotatedAt
                          ? ` · หมุนเวียนล่าสุด ${new Date(key.lastRotatedAt).toLocaleString("th-TH")}`
                          : ""}
                        {key.nextRotationAt && !key.revokedAt
                          ? ` · รอบหมุนเวียนถัดไป ${new Date(key.nextRotationAt).toLocaleString("th-TH")}`
                          : ""}
                        {key.rotationCount > 0
                          ? ` · หมุนเวียนแล้ว ${key.rotationCount.toLocaleString("th-TH")} ครั้ง`
                          : ""}
                        {key.revokedAt
                          ? ` · เพิกถอน ${new Date(key.revokedAt).toLocaleString("th-TH")}`
                          : ""}
                      </p>
                      {!key.revokedAt && (
                        <div className="settings-rotate-box">
                          <label
                            className="settings-checkbox-row"
                            htmlFor={`auto-rotate-toggle-${key.id}`}
                          >
                            <input
                              id={`auto-rotate-toggle-${key.id}`}
                              type="checkbox"
                              checked={draft.enabled}
                              disabled={savingScheduleKeyId === key.id}
                              onChange={(event) =>
                                setRotateDrafts((prev) => ({
                                  ...prev,
                                  [key.id]: {
                                    ...draft,
                                    enabled: event.target.checked,
                                  },
                                }))
                              }
                            />
                            <span>เปิดใช้ Auto-rotate สำหรับคีย์นี้</span>
                          </label>
                          {draft.enabled && (
                            <div className="settings-rotate-fields">
                              <select
                                aria-label={`ตาราง Auto-rotate ของ ${key.name}`}
                                className="settings-select"
                                value={draft.preset}
                                disabled={savingScheduleKeyId === key.id}
                                onChange={(event) =>
                                  setRotateDrafts((prev) => ({
                                    ...prev,
                                    [key.id]: {
                                      ...draft,
                                      preset: event.target.value,
                                    },
                                  }))
                                }
                              >
                                {AUTO_ROTATE_PRESETS.map((days) => (
                                  <option key={days} value={String(days)}>
                                    ทุก {days} วัน
                                  </option>
                                ))}
                                <option value="custom">กำหนดวันเอง</option>
                              </select>
                              {draft.preset === "custom" && (
                                <input
                                  aria-label={`จำนวนวัน Auto-rotate ของ ${key.name}`}
                                  className="settings-input"
                                  type="number"
                                  min={1}
                                  max={365}
                                  value={draft.customDays}
                                  disabled={savingScheduleKeyId === key.id}
                                  onChange={(event) =>
                                    setRotateDrafts((prev) => ({
                                      ...prev,
                                      [key.id]: {
                                        ...draft,
                                        customDays: event.target.value,
                                      },
                                    }))
                                  }
                                />
                              )}
                            </div>
                          )}
                        </div>
                      )}
                      <div className="settings-key-actions">
                        {!key.revokedAt && (
                          <>
                            <button
                              className="button button-secondary"
                              type="button"
                              disabled={
                                !hasScheduleChanges ||
                                savingScheduleKeyId === key.id
                              }
                              onClick={() => void saveAutoRotateSchedule(key)}
                            >
                              {savingScheduleKeyId === key.id
                                ? "กำลังบันทึกตาราง..."
                                : "บันทึกตาราง Auto-rotate"}
                            </button>
                            <button
                              className="button button-secondary"
                              type="button"
                              disabled={rotatingApiKeyId === key.id}
                              onClick={() => void rotateKeyNow(key)}
                            >
                              {rotatingApiKeyId === key.id
                                ? "กำลังหมุนเวียน..."
                                : "หมุนเวียนคีย์ทันที"}
                            </button>
                          </>
                        )}
                        <button
                          className="button button-secondary"
                          type="button"
                          disabled={apiKeyUsageLoadingId === key.id}
                          onClick={() => void loadApiKeyUsage(key.id)}
                        >
                          {apiKeyUsageLoadingId === key.id
                            ? "กำลังโหลดกราฟ..."
                            : "ดู Usage 7 วัน"}
                        </button>
                        {!key.revokedAt && (
                          <button
                            className="button button-danger"
                            type="button"
                            disabled={revokingApiKeyId === key.id}
                            onClick={() => void removeApiKey(key.id)}
                          >
                            {revokingApiKeyId === key.id
                              ? "กำลังเพิกถอน..."
                              : "เพิกถอน"}
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            {apiKeys.length > 0 && (
              <div className="settings-usage-section">
                <div className="settings-usage-toolbar">
                  <label htmlFor="api-key-usage-select">
                    กราฟประสิทธิภาพ API Key (7 วันล่าสุด)
                  </label>
                  <select
                    id="api-key-usage-select"
                    className="settings-select"
                    value={selectedUsageKeyId ?? apiKeys[0]?.id ?? ""}
                    disabled={apiKeyUsageLoadingId !== null}
                    onChange={(event) => void loadApiKeyUsage(event.target.value)}
                  >
                    {apiKeys.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name} ({item.keyPrefix}…)
                      </option>
                    ))}
                  </select>
                </div>
                <ApiKeyUsageChart
                  selectedKey={
                    apiKeys.find((item) => item.id === selectedUsageKeyId) ??
                    apiKeys[0] ??
                    null
                  }
                  usage={
                    belongsToAccount(apiKeyUsageOwnerId, session.userId)
                      ? apiKeyUsage
                      : null
                  }
                  loading={apiKeyUsageLoadingId !== null}
                />
              </div>
            )}
            {apiKeyUsageError && (
              <p className="form-alert form-alert-error" role="alert">
                {apiKeyUsageError}
              </p>
            )}
            {apiKeysError && (
              <p className="form-alert form-alert-error" role="alert">
                {apiKeysError}
              </p>
            )}
          </>
        )}
      </Panel>

      {bulkConfirmOpen && (
        <div
          aria-labelledby="bulk-revoke-dialog-title"
          aria-modal="true"
          className="modal-backdrop"
          role="dialog"
        >
          <div className="panel modal-dialog">
            <div className="modal-header">
              <div>
                <div className="eyebrow">ยืนยันการดำเนินการ</div>
                <h2 id="bulk-revoke-dialog-title">
                  ยืนยันเพิกถอน API Keys ({selectedActiveKeyIds.length} รายการ)
                </h2>
              </div>
              <button
                aria-label="ปิดหน้าต่างยืนยัน"
                className="button button-secondary"
                disabled={bulkRevoking}
                onClick={() => setBulkConfirmOpen(false)}
                type="button"
              >
                <Icon name="close" size={16} />
              </button>
            </div>
            <div className="modal-body">
              <p>
                คีย์ที่เลือกจะถูกเพิกถอนทันทีและไม่สามารถนำกลับมาใช้งานได้อีก
                แอปพลิเคชันที่ใช้คีย์เหล่านี้จะไม่สามารถเรียก Native Inference ได้
              </p>
              <ul className="settings-key-meta">
                {activeApiKeys
                  .filter((k) => selectedActiveKeyIds.includes(k.id))
                  .map((k) => (
                    <li key={k.id}>
                      <strong>{k.name}</strong> ({k.keyPrefix}…)
                    </li>
                  ))}
              </ul>
            </div>
            <div className="modal-footer">
              <button
                className="button button-secondary"
                disabled={bulkRevoking}
                onClick={() => setBulkConfirmOpen(false)}
                type="button"
              >
                ยกเลิก
              </button>
              <button
                className="button button-danger"
                disabled={bulkRevoking}
                onClick={() => void confirmBulkRevoke()}
                type="button"
              >
                {bulkRevoking
                  ? "กำลังเพิกถอน..."
                  : `ยืนยันเพิกถอน ${selectedActiveKeyIds.length} คีย์`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
