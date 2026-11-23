"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { Icon } from "@/components/Icon";
import { StatusBadge } from "@/components/StatusBadge";
import { ApiKeyUsageChart } from "@/components/ApiKeyUsageChart";
import { readSession } from "@/lib/api";
import {
  AUTO_ROTATE_PRESETS,
  createApiKey,
  getApiKeyUsage,
  listApiKeys,
  revokeApiKey,
  rotateApiKey,
  updateApiKeyAutoRotate,
  validateAutoRotateInterval,
} from "@/lib/api-access";
import {
  deleteConversation,
  listConversations,
} from "@/lib/conversation-api";
import { getMyProfile, getMyUsage, getMyQuota, updateMyProfile } from "@/lib/user-api";
import {
  belongsToAccount,
  quotaPercent,
  quotaState,
} from "@/lib/user-state";
import type { QuotaSummary, UsageSummary } from "@/lib/types";
import type { Session } from "@/lib/types";
import type { ApiKeyMetadata, ApiKeyUsage } from "@/lib/types";

function QuotaMetric({
  label,
  used,
  limit,
}: {
  label: string;
  used: number;
  limit: number | null;
}) {
  const percent = quotaPercent(used, limit);
  return (
    <div className="settings-info">
      <span>{label}</span>
      {limit === null ? (
        <p>Backend ไม่ได้กำหนดขีดจำกัดสำหรับรายการนี้</p>
      ) : (
        <>
          <code>{used.toLocaleString("th-TH")} / {limit.toLocaleString("th-TH")}</code>
          <progress aria-label={`สัดส่วน ${label}`} max={100} value={percent ?? 0} />
          <p>{percent}% · {quotaState(used, limit)}</p>
        </>
      )}
    </div>
  );
}

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
  const next: Record<string, { enabled: boolean; preset: string; customDays: string }> = {};
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

export default function SettingsPage() {
  const router = useRouter();
  const [cleared, setCleared] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [clearError, setClearError] = useState("");
  const [session, setSession] = useState<Session | null>(null);
  const sessionRef = useRef<Session | null>(null);
  const [sessionReady, setSessionReady] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState("");
  const [profileEmail, setProfileEmail] = useState("");
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileOwnerId, setProfileOwnerId] = useState<string | null>(null);
  const [profileSavingUserId, setProfileSavingUserId] = useState<string | null>(null);
  const profileSavingRef = useRef<string | null>(null);
  const [profileError, setProfileError] = useState("");
  const [profileSuccess, setProfileSuccess] = useState("");
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [quota, setQuota] = useState<QuotaSummary | null>(null);
  const [usageLoading, setUsageLoading] = useState(true);
  const [usageOwnerId, setUsageOwnerId] = useState<string | null>(null);
  const [usageError, setUsageError] = useState("");
  const [quotaError, setQuotaError] = useState("");
  const [apiKeys, setApiKeys] = useState<ApiKeyMetadata[]>([]);
  const [apiKeysLoading, setApiKeysLoading] = useState(true);
  const [apiKeysOwnerId, setApiKeysOwnerId] = useState<string | null>(null);
  const [apiKeysError, setApiKeysError] = useState("");
  const [apiKeysNotice, setApiKeysNotice] = useState("");
  const [apiKeyName, setApiKeyName] = useState("");
  const [apiKeyExpiresAt, setApiKeyExpiresAt] = useState("");
  const [createAutoRotateEnabled, setCreateAutoRotateEnabled] = useState(true);
  const [createRotatePreset, setCreateRotatePreset] = useState<string>("30");
  const [createRotateCustomDays, setCreateRotateCustomDays] = useState<string>("30");
  const [apiKeySaving, setApiKeySaving] = useState(false);
  const apiKeySavingRef = useRef(false);
  const [newApiKey, setNewApiKey] = useState("");
  const [newApiKeyLabel, setNewApiKeyLabel] = useState("");
  const [newApiKeyOwnerId, setNewApiKeyOwnerId] = useState<string | null>(null);
  const [copiedSecret, setCopiedSecret] = useState(false);
  const [revokingApiKeyId, setRevokingApiKeyId] = useState<string | null>(null);
  const [rotatingApiKeyId, setRotatingApiKeyId] = useState<string | null>(null);
  const [savingScheduleKeyId, setSavingScheduleKeyId] = useState<string | null>(null);
  const [rotateDrafts, setRotateDrafts] = useState<
    Record<string, { enabled: boolean; preset: string; customDays: string }>
  >({});
  const [apiKeyUsage, setApiKeyUsage] = useState<ApiKeyUsage | null>(null);
  const [selectedUsageKeyId, setSelectedUsageKeyId] = useState<string | null>(null);
  const [apiKeyUsageOwnerId, setApiKeyUsageOwnerId] = useState<string | null>(null);
  const [apiKeyUsageLoadingId, setApiKeyUsageLoadingId] = useState<string | null>(null);
  const [apiKeyUsageError, setApiKeyUsageError] = useState("");

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
    return () => window.removeEventListener("zyrquen:session-change", refreshSession);
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

    void getMyProfile(ownerId)
      .then((nextProfile) => {
        if (!isCurrentOwner()) return;
        setProfileEmail(nextProfile.email);
        setProfileError("");
        setProfileSuccess("");
      })
      .catch((reason: unknown) => {
        if (!isCurrentOwner()) return;
        setProfileEmail("");
        setProfileSuccess("");
        setProfileError(
          reason instanceof Error
            ? reason.message
            : "ไม่สามารถโหลดข้อมูลโปรไฟล์ได้",
        );
      })
      .finally(() => {
        if (!isCurrentOwner()) return;
        setProfileOwnerId(ownerId);
        setProfileLoading(false);
      });

    void Promise.allSettled([getMyUsage(ownerId), getMyQuota(ownerId)])
      .then(([usageResult, quotaResult]) => {
        if (!isCurrentOwner()) return;
        if (usageResult.status === "fulfilled") {
          setUsage(usageResult.value);
          setUsageError("");
        } else {
          setUsage(null);
          setUsageError(
            usageResult.reason instanceof Error
              ? usageResult.reason.message
              : "ไม่สามารถโหลดข้อมูล Usage ได้",
          );
        }
        if (quotaResult.status === "fulfilled") {
          setQuota(quotaResult.value);
          setQuotaError("");
        } else {
          setQuota(null);
          setQuotaError(
            quotaResult.reason instanceof Error
              ? quotaResult.reason.message
              : "ไม่สามารถโหลดข้อมูลโควตาได้",
          );
        }
      })
      .finally(() => {
        if (!isCurrentOwner()) return;
        setUsageOwnerId(ownerId);
        setUsageLoading(false);
      });
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
    if (!apiKeyName.trim() || Number.isNaN(expiry.getTime()) || expiry <= new Date()) {
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
      setRotateDrafts((prev) => ({ ...prev, [created.id]: draftFromKey(created) }));
      setNewApiKey(created.key);
      setNewApiKeyLabel(`สร้าง API Key "${created.name}" แล้ว`);
      setNewApiKeyOwnerId(ownerId);
      setApiKeyName("");
      setApiKeyExpiresAt("");
    } catch (reason) {
      if (sessionRef.current?.userId !== ownerId) return;
      setApiKeysError(
        reason instanceof Error
          ? reason.message
          : "ไม่สามารถสร้าง API Key ได้",
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
    const validationError = validateAutoRotateInterval(draft.enabled, intervalDays);
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
      setNewApiKeyLabel(`หมุนเวียนคีย์ "${rotated.name}" สำเร็จ (ครั้งที่ ${rotated.rotationCount})`);
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

  async function clearConversationHistory() {
    setClearing(true);
    setClearError("");
    setCleared(false);
    try {
      const ownerId = session?.userId;
      if (!ownerId) throw new Error("ไม่พบรหัสบัญชีที่ยืนยันตัวตนแล้ว");
      const conversations = await listConversations(ownerId);
      const verifiedSession = await readSession();
      if (!verifiedSession.authenticated || verifiedSession.userId !== ownerId) {
        throw new Error("บัญชีผู้ใช้เปลี่ยนระหว่างล้างประวัติ");
      }
      for (const conversation of conversations) {
        const currentSession = await readSession();
        if (!currentSession.authenticated || currentSession.userId !== ownerId) {
          throw new Error("บัญชีผู้ใช้เปลี่ยนระหว่างล้างประวัติ");
        }
        await deleteConversation(conversation.id, ownerId);
      }
      const finalSession = await readSession();
      if (!finalSession.authenticated || finalSession.userId !== ownerId) {
        throw new Error("บัญชีผู้ใช้เปลี่ยนระหว่างล้างประวัติ");
      }
      window.dispatchEvent(new Event("zyrquen:conversations-cleared"));
      setCleared(true);
    } catch (reason) {
      setClearError(
        reason instanceof Error
          ? reason.message
          : "ล้างประวัติการสนทนาไม่สำเร็จ",
      );
    } finally {
      setClearing(false);
    }
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ownerId = session?.userId;
    if (!ownerId || sessionRef.current?.userId !== ownerId) {
      setProfileError("ไม่สามารถยืนยันบัญชีผู้ใช้ปัจจุบันได้");
      return;
    }
    if (profileSavingRef.current === ownerId) return;
    const email = profileEmail.trim().toLowerCase();
    if (!email || email.length > 320) {
      setProfileError("กรุณากรอกอีเมลที่ถูกต้อง");
      return;
    }
    profileSavingRef.current = ownerId;
    setProfileSavingUserId(ownerId);
    setProfileError("");
    setProfileSuccess("");
    try {
      const nextProfile = await updateMyProfile(email, ownerId);
      if (sessionRef.current?.userId !== ownerId) return;
      setProfileEmail(nextProfile.email);
      const nextSession = { ...sessionRef.current, email: nextProfile.email };
      sessionRef.current = nextSession;
      setSession(nextSession);
      setProfileSuccess("บันทึกข้อมูลบัญชีเรียบร้อยแล้ว");
    } catch (reason) {
      if (sessionRef.current?.userId !== ownerId) return;
      setProfileError(
        reason instanceof Error ? reason.message : "ไม่สามารถบันทึกข้อมูลบัญชีได้",
      );
    } finally {
      if (profileSavingRef.current === ownerId) {
        profileSavingRef.current = null;
        setProfileSavingUserId(null);
      }
    }
  }

  async function signOut() {
    setSigningOut(true);
    setSignOutError("");
    try {
      const response = await fetch("/api/logout", { method: "POST" });
      const payload = (await response.json().catch(() => null)) as {
        detail?: unknown;
      } | null;
      const signedOutSession = {
        authenticated: false,
        email: null,
        verified: true,
      };
      sessionRef.current = signedOutSession;
      setSession(signedOutSession);
      window.dispatchEvent(new Event("zyrquen:session-change"));

      if (!response.ok) {
        const message =
          typeof payload?.detail === "string"
            ? payload.detail
            : "ไม่สามารถเพิกถอนเซสชันกับ Backend ได้ กรุณาลองใหม่อีกครั้ง";
        throw new Error(message);
      }

      router.push("/login");
      router.refresh();
    } catch (reason) {
      setSignOutError(
        reason instanceof Error
          ? reason.message
          : "ไม่สามารถออกจากระบบได้ กรุณาลองใหม่อีกครั้ง",
      );
    } finally {
      setSigningOut(false);
    }
  }

  if (!sessionReady || !session?.authenticated) {
    return (
      <div className="page-stack">
        <PageHeader
          description="ตรวจสอบข้อมูลบัญชี จัดการการตั้งค่าที่เปิดให้ใช้งาน และดูรายละเอียดการเชื่อมต่อ API ฝั่งเซิร์ฟเวอร์"
          eyebrow="แพลตฟอร์ม / การตั้งค่า"
          icon="settings"
          title="การตั้งค่า"
        />
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
                  : "จำเป็นต้องเข้าสู่ระบบเพื่อเข้าถึงการตั้งค่าบัญชี"}
            </strong>
            <p>
              {!sessionReady
                ? "ระบบกำลังยืนยันตัวตนกับบริการ ZYRQUEN API เพื่อปกป้องข้อมูลบัญชีของคุณ"
                : session?.error ||
                  "กรุณาเข้าสู่ระบบด้วยบัญชีของคุณก่อนจัดการการตั้งค่าและประวัติการสนทนา"}
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

  const profileIsLoading =
    profileLoading || !belongsToAccount(profileOwnerId, session.userId);
  const usageIsLoading =
    usageLoading || !belongsToAccount(usageOwnerId, session.userId);
  const apiKeysAreLoading =
    apiKeysLoading || !belongsToAccount(apiKeysOwnerId, session.userId);
  const profileSaving = profileSavingUserId === session.userId;

  return (
    <div className="page-stack">
      <PageHeader
        description="ตรวจสอบข้อมูลบัญชี จัดการการตั้งค่าที่เปิดให้ใช้งาน และดูรายละเอียดการเชื่อมต่อ API ฝั่งเซิร์ฟเวอร์"
        eyebrow="แพลตฟอร์ม / การตั้งค่า"
        icon="settings"
        title="การตั้งค่า"
      />
      <div className="settings-grid">
        <Panel>
          <div className="panel-heading"><div><div className="eyebrow">การตั้งค่าบัญชี</div><h2>ข้อมูลบัญชีและเซสชัน</h2></div><span className="metric-icon"><Icon name="user" /></span></div>
          <div className="settings-info">
            <span>สถานะบัญชี</span>
            <code>{session.email || "เข้าสู่ระบบแล้ว"}</code>
            <p>ตรวจสอบข้อมูลบัญชีของคุณ จัดการการตั้งค่าที่เปิดให้ใช้งาน และออกจากระบบเมื่อใช้งานเสร็จสิ้น</p>
          </div>
          {!session.userId ? (
            <p className="form-alert form-alert-error" role="alert">ข้อมูลเซสชันไม่มีรหัสบัญชีที่ยืนยันแล้ว</p>
          ) : profileIsLoading ? (
            <p className="settings-confirmation" role="status">กำลังโหลดข้อมูลโปรไฟล์...</p>
          ) : (
            <form onSubmit={saveProfile}>
              <label htmlFor="profile-email">อีเมลบัญชี</label>
              <input
                id="profile-email"
                type="email"
                value={profileEmail}
                maxLength={320}
                disabled={profileSaving}
                onChange={(event) => setProfileEmail(event.target.value)}
                required
              />
              <button className="button button-secondary" disabled={profileSaving || !profileEmail.trim()} type="submit">
                {profileSaving ? "กำลังบันทึก..." : "บันทึกอีเมล"}
              </button>
            </form>
          )}
          {belongsToAccount(profileOwnerId, session.userId) && profileSuccess && <p className="settings-confirmation" role="status"><Icon name="check-circle" size={15} /> {profileSuccess}</p>}
          {belongsToAccount(profileOwnerId, session.userId) && profileError && <p className="form-alert form-alert-error" role="alert"><Icon name="close" size={15} /> {profileError}</p>}
          <button className="button button-secondary" disabled={signingOut} onClick={() => void signOut()} type="button">
            <Icon name="logout" size={16} /> {signingOut ? "กำลังออกจากระบบ..." : "ออกจากระบบ"}
          </button>
          {signOutError && <p className="form-alert form-alert-error" role="alert"><Icon name="close" size={15} /> {signOutError}</p>}
        </Panel>
        <Panel>
          <div className="panel-heading"><div><div className="eyebrow">การใช้งานจริง</div><h2>Usage และโควตา</h2></div><span className="metric-icon metric-icon-blue"><Icon name="server" /></span></div>
          {usageIsLoading ? (
            <p className="settings-confirmation" role="status">กำลังโหลดข้อมูลจาก Backend...</p>
          ) : (
            <>
              {usageError ? (
                <p className="form-alert form-alert-error" role="alert"><Icon name="close" size={15} /> {usageError}</p>
              ) : usage && (
                <div className="settings-info">
                  <span>Inference สำเร็จ</span>
                  <code>{usage.successfulRequests.toLocaleString("th-TH")} ครั้ง</code>
                  <p>Input {usage.inputTokens.toLocaleString("th-TH")} · Output {usage.outputTokens.toLocaleString("th-TH")} · รวม {usage.totalTokens.toLocaleString("th-TH")} Tokens</p>
                  {usage.updatedAt && <p>อัปเดตล่าสุดจาก Backend: {new Date(usage.updatedAt).toLocaleString("th-TH")}</p>}
                </div>
              )}
              {quotaError ? (
                <p className="form-alert form-alert-error" role="alert"><Icon name="close" size={15} /> {quotaError}</p>
              ) : !quota?.configured ? (
                <div className="security-callout"><Icon name="lock" size={16} /><span>ยังไม่มี Policy โควตาที่ Backend ยืนยันได้ Native Inference จะถูกปฏิเสธแบบ fail-closed</span></div>
              ) : !quota.active ? (
                <div className="security-callout"><Icon name="lock" size={16} /><span>Policy โควตาหมดอายุหรือยังไม่เริ่มใช้งาน Native Inference จึงถูกปฏิเสธ</span></div>
              ) : (
                <>
                  <QuotaMetric label="Requests ที่ใช้หรือกำลังประมวลผล" used={quota.requestsInUse} limit={quota.maxRequests} />
                  <QuotaMetric label="Input Tokens ที่ใช้หรือจอง" used={quota.inputTokens} limit={quota.maxInputTokens} />
                  <QuotaMetric label="Output Tokens ที่ใช้หรือจอง" used={quota.outputTokens} limit={quota.maxOutputTokens} />
                  <QuotaMetric label="Total Tokens ที่ใช้หรือจอง" used={quota.totalTokens} limit={quota.maxTotalTokens} />
                  {quota.windowStartedAt && quota.windowEndsAt && (
                    <p>ช่วงโควตา: {new Date(quota.windowStartedAt).toLocaleString("th-TH")} – {new Date(quota.windowEndsAt).toLocaleString("th-TH")}</p>
                  )}
                  {quota.runningRequests > 0 && <p>กำลังประมวลผลอยู่ {quota.runningRequests.toLocaleString("th-TH")} Request</p>}
                </>
              )}
            </>
          )}
        </Panel>
        <Panel>
          <div className="panel-heading"><div><div className="eyebrow">ข้อมูลเฉพาะบัญชี</div><h2>ประวัติการสนทนา</h2></div><span className="metric-icon"><Icon name="history" /></span></div>
          <div className="settings-info">
            <span>ตำแหน่งจัดเก็บ</span><code>Backend · แยกตามบัญชี ({session.email})</code>
            <p>บทสนทนาและข้อความถูกจัดเก็บบน Backend โดยผูกกับบัญชีผู้ใช้ และไม่ปะปนกับบัญชีอื่น</p>
          </div>
          <button className="button button-danger" disabled={clearing} onClick={() => void clearConversationHistory()} type="button"><Icon name="close" size={16} /> {clearing ? "กำลังล้างประวัติ..." : "ล้างประวัติการสนทนาของบัญชีนี้"}</button>
          {cleared && <p className="settings-confirmation" role="status"><Icon name="check-circle" size={15} /> ล้างประวัติการสนทนาของบัญชีนี้เรียบร้อยแล้ว</p>}
          {clearError && <p className="form-alert form-alert-error" role="alert"><Icon name="close" size={15} /> {clearError}</p>}
        </Panel>
        <Panel>
          <div className="panel-heading"><div><div className="eyebrow">การเชื่อมต่อ API</div><h2>Endpoint ฝั่งเซิร์ฟเวอร์</h2></div><span className="metric-icon metric-icon-blue"><Icon name="server" /></span></div>
          <div className="settings-info">
            <span>ตัวแปรกำหนดค่า</span><code>ZYRQUEN_API_BASE_URL</code>
            <p>กำหนดค่าบนเซิร์ฟเวอร์ Next.js (เช่น <code>http://localhost:8000</code>) คำขอจากเบราว์เซอร์จะส่งผ่านพร็อกซีแบบ same-origin โดยส่งต่อเฉพาะเส้นทางตรวจสอบสถานะ การยืนยันตัวตน และการประมวลผลที่มีอยู่จริง</p>
          </div>
          <div className="security-callout"><Icon name="lock" size={16} /><span>URL ปลายทางเป็นค่ากำหนดฝั่งเซิร์ฟเวอร์ จึงไม่เปิดให้แก้ไขจากฝั่งเบราว์เซอร์</span></div>
        </Panel>
        <Panel>
          <div className="panel-heading"><div><div className="eyebrow">การเข้าถึง API</div><h2>API Key สำหรับ Native Inference</h2></div><span className="metric-icon metric-icon-blue"><Icon name="lock" /></span></div>
          {apiKeysAreLoading ? (
            <p className="settings-confirmation" role="status">กำลังโหลด API Key จาก Backend...</p>
          ) : !belongsToAccount(apiKeysOwnerId, session.userId) ? (
            <p className="settings-confirmation" role="status">กำลังยืนยันบัญชีเพื่อแสดง API Key</p>
          ) : (
            <>
              <form className="settings-form" onSubmit={(event) => void submitApiKey(event)}>
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
                <div className="settings-field">
                  <label className="settings-checkbox-row" htmlFor="api-key-auto-rotate">
                    <input
                      id="api-key-auto-rotate"
                      type="checkbox"
                      checked={createAutoRotateEnabled}
                      disabled={apiKeySaving}
                      onChange={(event) => setCreateAutoRotateEnabled(event.target.checked)}
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
                        onChange={(event) => setCreateRotatePreset(event.target.value)}
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
                          onChange={(event) => setCreateRotateCustomDays(event.target.value)}
                        />
                      )}
                    </div>
                  )}
                </div>
                <button className="button button-secondary" type="submit" disabled={apiKeySaving}>
                  {apiKeySaving ? "กำลังสร้าง..." : "สร้าง API Key"}
                </button>
              </form>
              {newApiKey && belongsToAccount(newApiKeyOwnerId, session.userId) && (
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
                  {apiKeys.map((key) => {
                    const draft = rotateDrafts[key.id] ?? draftFromKey(key);
                    const draftIntervalDays = resolveIntervalDays(
                      draft.enabled,
                      draft.preset,
                      draft.customDays,
                    );
                    const hasScheduleChanges =
                      draft.enabled !== key.autoRotateEnabled ||
                      (draft.enabled && draftIntervalDays !== key.autoRotateIntervalDays);
                    return (
                      <div className="settings-key-card" key={key.id}>
                        <div className="settings-key-head">
                          <strong>{key.name}</strong>
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
                        <code>{key.keyPrefix}… · {key.scope}</code>
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
                                  !hasScheduleChanges || savingScheduleKeyId === key.id
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
                            {apiKeyUsageLoadingId === key.id ? "กำลังโหลดกราฟ..." : "ดู Usage 7 วัน"}
                          </button>
                          {!key.revokedAt && (
                            <button
                              className="button button-danger"
                              type="button"
                              disabled={revokingApiKeyId === key.id}
                              onClick={() => void removeApiKey(key.id)}
                            >
                              {revokingApiKeyId === key.id ? "กำลังเพิกถอน..." : "เพิกถอน"}
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
              {apiKeyUsageError && <p className="form-alert form-alert-error" role="alert">{apiKeyUsageError}</p>}
              {apiKeysError && <p className="form-alert form-alert-error" role="alert">{apiKeysError}</p>}
            </>
          )}
        </Panel>
        <Panel>
          <div className="panel-heading"><div><div className="eyebrow">ผู้ดูแลระบบ</div><h2>แดชบอร์ดแพลตฟอร์ม</h2></div><span className="metric-icon"><Icon name="settings" /></span></div>
          <p>ข้อมูลส่วนผู้ดูแลระบบจะเปิดให้เฉพาะบัญชีที่มีบทบาทซึ่งกำหนดจาก Backend เท่านั้น</p>
          <Link className="button button-secondary" href="/admin">เปิดแดชบอร์ดผู้ดูแลระบบ</Link>
        </Panel>
        <Panel>
          <div className="panel-heading"><div><div className="eyebrow">คำแนะนำการใช้งาน</div><h2>การจัดการบัญชีและการตั้งค่า</h2></div><StatusBadge tone="info">เปิดให้ใช้งาน</StatusBadge></div>
          <div className="guidance-list">
            <div className="guidance-group">
              <strong>การตั้งค่าบัญชี</strong>
              <ul>
                <li>ตรวจสอบข้อมูลบัญชีของคุณ</li>
                <li>จัดการการตั้งค่าที่เปิดให้ใช้งาน</li>
                <li>ออกจากระบบเมื่อใช้งานเสร็จสิ้น</li>
              </ul>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
