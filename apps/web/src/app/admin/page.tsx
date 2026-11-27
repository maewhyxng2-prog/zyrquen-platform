"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { DeveloperNav } from "@/components/DeveloperNav";
import { Icon } from "@/components/Icon";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import {
  apiRequest,
  buildModelRegistryMetadataFilename,
  downloadBackendFile,
  normalizeAuditLogEntry,
  readSession,
} from "@/lib/api";
import type { AuditEntry, Session } from "@/lib/types";

type AdminOverview = {
  users: number;
  successful_inference_requests: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  active_api_keys: number;
  configured_quota_policies: number;
  active_quota_policies: number;
  native_ai: {
    runtime_status?: string;
    native_model_loaded?: boolean;
    inference_available?: boolean;
    model_version?: string | null;
    platform_version?: string | null;
    artifact_origin?: string | null;
    is_trained?: boolean;
  };
};

type ModelArtifactLineageNode = {
  version: string;
  parent?: string | null;
  lifecycle_status: string;
  created_at?: string | null;
  dataset_version?: string | null;
  dataset_sha256?: string | null;
  checkpoint_sha256?: string | null;
  tokenizer_sha256?: string | null;
  eval_report_sha256?: string | null;
  eval_passed?: boolean | null;
  workflow_lineage?: Record<string, unknown>;
};

type ModelRegistryVersionRecord = {
  version: string;
  parent?: string | null;
  lifecycle_status?: string;
  created_at?: string;
  frozen?: boolean;
  checkpoint?: { path?: string; step?: number; sha256?: string } | null;
  dataset?: { version?: string; path?: string; content_sha256?: string } | null;
  tokenizer?: { path?: string; sha256?: string } | null;
  evaluation_evidence?: {
    eval_run_id?: string;
    passed?: boolean;
    zero_regression?: boolean;
    report_sha256?: string;
    evaluated_at?: string;
  } | null;
  workflow_lineage?: Record<string, unknown>;
};

type ModelLineageResponse = {
  record: ModelRegistryVersionRecord;
  lineage: {
    version: string;
    depth: number;
    ancestors: ModelArtifactLineageNode[];
  };
  compatibility: {
    version: string;
    compatible: boolean;
    checks: {
      artifacts_sha256: boolean;
      tokenizer_sha256: boolean;
      architecture_config: boolean;
    };
    reasons: string[];
  };
};

type ModelRegistrySummary = {
  configured?: boolean;
  active_version?: string | null;
  versions?: Array<{ version: string; lifecycle_status?: string }>;
};

function shortDigest(value?: string | null): string {
  if (!value) return "—";
  if (value.length <= 16) return value;
  return `${value.slice(0, 12)}…${value.slice(-6)}`;
}

function formatLineageTimestamp(value?: string | null): string {
  if (!value) return "ไม่ระบุ";
  const ms = Date.parse(value);
  if (Number.isNaN(ms)) return value;
  return new Date(ms).toLocaleString("th-TH");
}

function lifecycleTone(status?: string | null): "good" | "warn" | "bad" | "info" | "neutral" {
  switch (status) {
    case "production":
    case "verified":
      return "good";
    case "staging":
    case "evaluated":
      return "warn";
    case "quarantined":
    case "rejected":
      return "bad";
    case "registered":
      return "info";
    default:
      return "neutral";
  }
}

type AdminUser = {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
};

export default function AdminPage() {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const sessionRef = useRef<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState("");
  const [lineageOpen, setLineageOpen] = useState(false);
  const [lineageLoading, setLineageLoading] = useState(false);
  const [lineageError, setLineageError] = useState("");
  const [lineageData, setLineageData] = useState<ModelLineageResponse | null>(null);
  const [resolvedModelVersion, setResolvedModelVersion] = useState<string | null>(null);
  const [artifactBusy, setArtifactBusy] = useState<"logs" | "manifest" | "metadata" | null>(null);
  const [artifactError, setArtifactError] = useState("");
  const [artifactNotice, setArtifactNotice] = useState("");
  const modalDialogRef = useRef<HTMLDivElement | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  const fetchAdminData = useCallback(async (isCancelled?: () => boolean) => {
    try {
      const currentSession = await readSession();
      if (isCancelled?.()) return;
      sessionRef.current = currentSession;
      setSession(currentSession);

      if (!currentSession.authenticated || !currentSession.userId) {
        router.replace("/login");
        return;
      }
      if (currentSession.role !== "admin") {
        setOverview(null);
        setUsers(null);
        setAuditLogs(null);
        setError("บัญชีนี้ไม่มีสิทธิ์ผู้ดูแลระบบ (Admin Access Required)");
        return;
      }
      const results = await Promise.allSettled([
        apiRequest<AdminOverview>("admin/overview"),
        apiRequest<AdminUser[]>("admin/users"),
        apiRequest<unknown[]>("admin/audit-logs"),
      ]);
      if (isCancelled?.()) return;
      const failures = results.filter(
        (result): result is PromiseRejectedResult =>
          result.status === "rejected",
      );
      if (failures.length > 0) {
        const first = failures[0].reason;
        setError(
          first instanceof Error
            ? first.message
            : "ไม่สามารถโหลดข้อมูลผู้ดูแลระบบได้",
        );
      } else {
        setError("");
      }
      if (results[0].status === "fulfilled") setOverview(results[0].value);
      const resolvedUsers =
        results[1].status === "fulfilled" ? results[1].value : null;
      if (resolvedUsers) setUsers(resolvedUsers);

      if (results[2].status === "fulfilled") {
        const userIdByEmail = new Map<string, string>();
        for (const u of resolvedUsers ?? []) {
          if (u.email && u.id) {
            userIdByEmail.set(u.email.trim().toLowerCase(), u.id);
          }
        }
        const normalizedEntries = Array.isArray(results[2].value)
          ? results[2].value.map((entry) =>
              normalizeAuditLogEntry(entry, currentSession, userIdByEmail),
            )
          : [];
        setAuditLogs(normalizedEntries);
      }
    } catch (reason) {
      if (isCancelled?.()) return;
      setError(
        reason instanceof Error
          ? reason.message
          : "ไม่สามารถยืนยันเซสชันได้",
      );
    } finally {
      if (!isCancelled?.()) setLoading(false);
    }
  }, [router]);

  const handleRefresh = useCallback(async () => {
    setLoading(true);
    setError("");
    await fetchAdminData();
  }, [fetchAdminData]);

  const overviewModelVersion = overview?.native_ai.model_version?.trim() || null;

  const loadModelLineage = useCallback(async () => {
    setLineageLoading(true);
    setLineageError("");
    try {
      let targetVersion = overviewModelVersion;
      if (!targetVersion) {
        const registry = await apiRequest<ModelRegistrySummary>("v1/models/registry");
        targetVersion =
          registry.active_version?.trim() ||
          registry.versions?.find((item) => item.lifecycle_status === "production")?.version ||
          registry.versions?.[0]?.version ||
          null;
      }
      setResolvedModelVersion(targetVersion);
      if (!targetVersion) {
        setLineageData(null);
        return;
      }
      const data = await apiRequest<ModelLineageResponse>(
        `v1/models/registry/${encodeURIComponent(targetVersion)}/lineage`,
      );
      setLineageData(data);
    } catch (reason) {
      setLineageData(null);
      setLineageError(
        reason instanceof Error
          ? reason.message
          : "ไม่สามารถโหลดประวัติ Training Artifact Lineage ได้",
      );
    } finally {
      setLineageLoading(false);
    }
  }, [overviewModelVersion]);

  const handleToggleLineage = useCallback(() => {
    setLineageOpen((prev) => {
      const next = !prev;
      if (next) {
        setArtifactError("");
        setArtifactNotice("");
        void loadModelLineage();
      }
      return next;
    });
  }, [loadModelLineage]);

  const handleDownloadArtifact = useCallback(
    async (version: string, kind: "logs" | "manifest" | "metadata") => {
      setArtifactBusy(kind);
      setArtifactError("");
      setArtifactNotice("");
      try {
        const apiKind = kind === "metadata" ? "manifest" : kind;
        const fallback =
          kind === "logs"
            ? `${version}-training-logs.jsonl`
            : kind === "metadata"
              ? buildModelRegistryMetadataFilename(version)
              : `${version}-manifest.json`;
        const filename = await downloadBackendFile(
          `v1/models/registry/${encodeURIComponent(version)}/artifacts/${apiKind}`,
          fallback,
          kind === "metadata" ? { overrideFilename: true } : undefined,
        );
        setArtifactNotice(
          kind === "metadata"
            ? `ส่งออก Metadata JSON (${filename}) สำหรับ ${version} สำเร็จ`
            : `ดาวน์โหลด ${filename} สำหรับ ${version} สำเร็จ`,
        );
      } catch (reason) {
        setArtifactError(
          reason instanceof Error
            ? reason.message
            : kind === "metadata"
              ? `ไม่สามารถส่งออก Metadata JSON สำหรับ ${version} ได้`
              : `ไม่สามารถดาวน์โหลดไฟล์ ${kind} สำหรับ ${version} ได้`,
        );
      } finally {
        setArtifactBusy(null);
      }
    },
    [],
  );

  useEffect(() => {
    if (!lineageOpen) return;

    previousFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const getFocusableElements = (): HTMLElement[] => {
      const dialog = modalDialogRef.current;
      if (!dialog) return [];
      const selector = [
        'a[href]',
        'button:not([disabled])',
        'textarea:not([disabled])',
        'input:not([disabled])',
        'select:not([disabled])',
        '[tabindex]:not([tabindex="-1"])',
      ].join(", ");
      return Array.from(dialog.querySelectorAll<HTMLElement>(selector)).filter((el) => {
        if (el.hasAttribute("hidden") || el.closest('[hidden], [aria-hidden="true"]')) {
          return false;
        }
        const style = window.getComputedStyle(el);
        return style.display !== "none" && style.visibility !== "hidden";
      });
    };

    const focusInitialElement = () => {
      const dialog = modalDialogRef.current;
      if (!dialog) return;
      const focusable = getFocusableElements();
      if (focusable.length > 0) {
        focusable[0].focus();
      } else {
        dialog.focus();
      }
    };

    focusInitialElement();
    const rafId = window.requestAnimationFrame(() => {
      const dialog = modalDialogRef.current;
      if (dialog && !dialog.contains(document.activeElement)) {
        focusInitialElement();
      }
    });

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setLineageOpen(false);
        return;
      }

      if (event.key !== "Tab") return;

      const dialog = modalDialogRef.current;
      if (!dialog) return;

      const focusable = getFocusableElements();
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;

      if (!dialog.contains(active)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
        return;
      }

      if (event.shiftKey && (active === first || active === dialog)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(rafId);
      window.removeEventListener("keydown", onKeyDown);
      const previous = previousFocusRef.current;
      previousFocusRef.current = null;
      if (previous && previous.isConnected) {
        previous.focus();
      }
    };
  }, [lineageOpen]);

  useEffect(() => {
    let active = true;
    const syncAndLoad = () => {
      if (!active) return;
      void fetchAdminData(() => !active);
    };
    void Promise.resolve().then(syncAndLoad);
    window.addEventListener("zyrquen:session-change", syncAndLoad);
    return () => {
      active = false;
      window.removeEventListener("zyrquen:session-change", syncAndLoad);
    };
  }, [fetchAdminData]);

  return (
    <div className="page-stack">
      <PageHeader
        action={
          <button
            className="button button-secondary"
            disabled={loading}
            onClick={() => void handleRefresh()}
            type="button"
          >
            <Icon name="activity" size={16} />
            {loading ? "กำลังโหลด..." : "รีเฟรชข้อมูล"}
          </button>
        }
        description="ข้อมูลผู้ดูแลระบบจาก Backend พร้อมการตรวจสิทธิ์ฝั่งเซิร์ฟเวอร์"
        eyebrow="DEVELOPER & ADVANCED / ผู้ดูแลระบบ"
        icon="shield"
        title="แดชบอร์ดผู้ดูแลระบบ"
      />

      <DeveloperNav />

      {loading && !overview ? (
        <Panel className="notice-panel">
          <span className="notice-icon">
            <Icon name="shield" size={18} />
          </span>
          <div>
            <strong>กำลังตรวจสอบสิทธิ์และโหลดข้อมูลจาก Backend</strong>
            <p role="status">
              กำลังดึงข้อมูลภาพรวม บัญชีผู้ใช้ และ Audit Log จาก Endpoint ผู้ดูแลระบบ...
            </p>
          </div>
        </Panel>
      ) : error ? (
        <Panel className="notice-panel">
          <span className="notice-icon">
            <Icon name="lock" size={18} />
          </span>
          <div>
            <strong>ไม่สามารถเข้าถึงข้อมูลผู้ดูแลระบบได้</strong>
            <p className="form-alert form-alert-error" role="alert">
              <Icon name="close" size={15} />
              <span>{error}</span>
            </p>
            <div className="unavailable-actions">
              <Link className="button button-secondary" href="/settings">
                กลับไปยังการตั้งค่าบัญชี
              </Link>
            </div>
          </div>
        </Panel>
      ) : (
        <>
          {overview && (
            <section aria-label="ภาพรวมผู้ดูแลระบบ" className="admin-kpi-grid">
              <Panel className="metric-card">
                <div className="metric-topline">
                  <span className="metric-icon">
                    <Icon name="user" />
                  </span>
                  <span className="metric-label">บัญชีผู้ใช้ทั้งหมด</span>
                </div>
                <div className="metric-value tabular-nums">
                  {overview.users.toLocaleString("th-TH")}
                </div>
                <div className="metric-foot">
                  <StatusBadge tone="info">Backend Users</StatusBadge>
                  <span className="metric-caption">บัญชีในระบบ</span>
                </div>
              </Panel>

              <Panel className="metric-card">
                <div className="metric-topline">
                  <span className="metric-icon metric-icon-cyan">
                    <Icon name="zap" />
                  </span>
                  <span className="metric-label">INFERENCE สำเร็จ</span>
                </div>
                <div className="metric-value tabular-nums">
                  {overview.successful_inference_requests.toLocaleString("th-TH")}
                </div>
                <div className="metric-foot">
                  <StatusBadge tone="good">Requests</StatusBadge>
                  <span className="metric-caption">คำขอที่ประมวลผลสำเร็จ</span>
                </div>
              </Panel>

              <Panel className="metric-card">
                <div className="metric-topline">
                  <span className="metric-icon metric-icon-blue">
                    <Icon name="database" />
                  </span>
                  <span className="metric-label">TOTAL TOKENS</span>
                </div>
                <div className="metric-value tabular-nums">
                  {overview.total_tokens.toLocaleString("th-TH")}
                </div>
                <div className="metric-foot">
                  <StatusBadge tone="neutral">
                    In {overview.input_tokens.toLocaleString("th-TH")}
                  </StatusBadge>
                  <span className="metric-caption tabular-nums">
                    Out {overview.output_tokens.toLocaleString("th-TH")}
                  </span>
                </div>
              </Panel>

              <Panel className="metric-card">
                <div className="metric-topline">
                  <span className="metric-icon metric-icon-violet">
                    <Icon name="key" />
                  </span>
                  <span className="metric-label">API KEY ที่ใช้งานได้</span>
                </div>
                <div className="metric-value tabular-nums">
                  {overview.active_api_keys.toLocaleString("th-TH")}
                </div>
                <div className="metric-foot">
                  <StatusBadge tone="info">
                    Policy {overview.active_quota_policies}/{overview.configured_quota_policies}
                  </StatusBadge>
                  <span className="metric-caption">โควตาที่เปิดใช้งาน</span>
                </div>
              </Panel>
            </section>
          )}

          <div className="settings-grid">
            <Panel>
              <div className="panel-heading">
                <div>
                  <div className="eyebrow">รันไทม์โมเดล</div>
                  <h2>สถานะ Native Model</h2>
                </div>
                <div className="panel-heading-actions">
                  <button
                    aria-expanded={lineageOpen}
                    aria-haspopup="dialog"
                    className="button button-secondary button-compact"
                    onClick={handleToggleLineage}
                    type="button"
                  >
                    <Icon name="history" size={15} />
                    View Lineage
                  </button>
                  <span className="metric-icon metric-icon-cyan">
                    <Icon name="cpu" />
                  </span>
                </div>
              </div>
              {overview ? (
                <div className="readiness-list">
                  <div className="readiness-row">
                    <span className="readiness-symbol">
                      <Icon name="activity" size={16} />
                    </span>
                    <div className="readiness-copy">
                      <strong>Runtime Status</strong>
                      <small>สถานะการทำงานที่ Backend รายงาน</small>
                    </div>
                    <StatusBadge
                      tone={
                        overview.native_ai.runtime_status ? "info" : "neutral"
                      }
                    >
                      {overview.native_ai.runtime_status ?? "ไม่ระบุ"}
                    </StatusBadge>
                  </div>
                  <div className="readiness-row">
                    <span className="readiness-symbol">
                      <Icon name="layers" size={16} />
                    </span>
                    <div className="readiness-copy">
                      <strong>การโหลด Native Model</strong>
                      <small>สถานะหน่วยความจำของโมเดลหลัก</small>
                    </div>
                    <StatusBadge
                      tone={
                        overview.native_ai.native_model_loaded === undefined
                          ? "neutral"
                          : overview.native_ai.native_model_loaded
                            ? "good"
                            : "warn"
                      }
                    >
                      {overview.native_ai.native_model_loaded === undefined
                        ? "ไม่ระบุ"
                        : overview.native_ai.native_model_loaded
                          ? "โหลดแล้ว"
                          : "ยังไม่โหลด"}
                    </StatusBadge>
                  </div>
                  <div className="readiness-row">
                    <span className="readiness-symbol">
                      <Icon name="sparkles" size={16} />
                    </span>
                    <div className="readiness-copy">
                      <strong>Native Inference</strong>
                      <small>ความพร้อมรับคำขอสร้างข้อความ</small>
                    </div>
                    <StatusBadge
                      tone={
                        overview.native_ai.inference_available === undefined
                          ? "neutral"
                          : overview.native_ai.inference_available
                            ? "good"
                            : "warn"
                      }
                    >
                      {overview.native_ai.inference_available === undefined
                        ? "ไม่ระบุ"
                        : overview.native_ai.inference_available
                          ? "พร้อมใช้งาน"
                          : "ไม่พร้อมใช้งาน"}
                    </StatusBadge>
                  </div>
                  {overview.native_ai.model_version ? (
                    <div className="readiness-row">
                      <span className="readiness-symbol">
                        <Icon name="file-check" size={16} />
                      </span>
                      <div className="readiness-copy">
                        <strong>Loaded Model Version</strong>
                        <small>รุ่นโมเดลที่โหลดหรืออ้างอิงในระบบ</small>
                      </div>
                      <StatusBadge tone="info">
                        {overview.native_ai.model_version}
                      </StatusBadge>
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="unavailable-block">
                  <strong>สถานะ Native Model ไม่พร้อมใช้งาน</strong>
                  <p>Backend ไม่สามารถยืนยันข้อมูลภาพรวมรันไทม์ได้</p>
                </div>
              )}
            </Panel>

            <Panel>
              <div className="panel-heading">
                <div>
                  <div className="eyebrow">โควตาและทรัพยากร</div>
                  <h2>รายละเอียด Token และ Policy</h2>
                </div>
                <span className="metric-icon metric-icon-blue">
                  <Icon name="server" />
                </span>
              </div>
              {overview ? (
                <div className="readiness-list">
                  <div className="readiness-row">
                    <span className="readiness-symbol">
                      <Icon name="arrow-up-right" size={16} />
                    </span>
                    <div className="readiness-copy">
                      <strong>Input Tokens สะสม</strong>
                      <small>ปริมาณโทเค็นขาเข้าทั้งหมด</small>
                    </div>
                    <StatusBadge tone="info">
                      {overview.input_tokens.toLocaleString("th-TH")}
                    </StatusBadge>
                  </div>
                  <div className="readiness-row">
                    <span className="readiness-symbol">
                      <Icon name="arrow-down-right" size={16} />
                    </span>
                    <div className="readiness-copy">
                      <strong>Output Tokens สะสม</strong>
                      <small>ปริมาณโทเค็นขาออกทั้งหมด</small>
                    </div>
                    <StatusBadge tone="info">
                      {overview.output_tokens.toLocaleString("th-TH")}
                    </StatusBadge>
                  </div>
                  <div className="readiness-row">
                    <span className="readiness-symbol">
                      <Icon name="shield" size={16} />
                    </span>
                    <div className="readiness-copy">
                      <strong>นโยบายโควตา (Quota Policies)</strong>
                      <small>กำหนดค่าแล้ว {overview.configured_quota_policies} นโยบาย</small>
                    </div>
                    <StatusBadge tone="good">
                      ใช้งาน {overview.active_quota_policies.toLocaleString("th-TH")}
                    </StatusBadge>
                  </div>
                </div>
              ) : (
                <div className="unavailable-block">
                  <strong>Backend ไม่สามารถยืนยันข้อมูลภาพรวมได้</strong>
                </div>
              )}
              <div className="panel-link-row">
                <Link className="text-link" href="/developer/console">
                  เปิดคอนโซล Workflow และ Tier-2 Approvals
                  <Icon name="arrow-right" size={15} />
                </Link>
              </div>
            </Panel>

            <Panel className="settings-panel-wide">
              <div className="panel-heading">
                <div>
                  <div className="eyebrow">การจัดการผู้ใช้</div>
                  <h2>บัญชีผู้ใช้ในระบบ</h2>
                </div>
                <StatusBadge tone="neutral">
                  {users ? `${users.length} บัญชี` : "ไม่ระบุ"}
                </StatusBadge>
              </div>
              {users ? (
                users.length === 0 ? (
                  <div className="unavailable-block">
                    <strong>Backend ไม่พบผู้ใช้</strong>
                  </div>
                ) : (
                  <div className="admin-list">
                    {users.map((user) => (
                      <div className="admin-list-row" key={user.id}>
                        <div className="admin-list-main">
                          <strong>{user.email}</strong>
                          <span className="admin-list-meta tabular-nums">
                            ID: <code>{user.id}</code> · สร้างเมื่อ{" "}
                            {new Date(user.created_at).toLocaleString("th-TH")}
                          </span>
                        </div>
                        <div className="workflow-actions">
                          <StatusBadge tone="info">{user.role}</StatusBadge>
                          <StatusBadge tone={user.is_active ? "good" : "bad"}>
                            {user.is_active ? "ใช้งานอยู่" : "ปิดใช้งาน"}
                          </StatusBadge>
                        </div>
                      </div>
                    ))}
                  </div>
                )
              ) : (
                <div className="unavailable-block">
                  <strong>Backend ไม่สามารถยืนยันรายการผู้ใช้ได้</strong>
                </div>
              )}
            </Panel>

            <Panel className="settings-panel-wide">
              <div className="panel-heading">
                <div>
                  <div className="eyebrow">การตรวจสอบความปลอดภัย</div>
                  <h2>
                    Audit Log
                    {session?.authenticated && session.email
                      ? ` · ${session.email} (${session.userId})`
                      : ""}
                  </h2>
                </div>
                <StatusBadge tone="neutral">
                  {auditLogs ? `${auditLogs.length} เหตุการณ์` : "ไม่ระบุ"}
                </StatusBadge>
              </div>
              {auditLogs ? (
                auditLogs.length === 0 ? (
                  <div className="unavailable-block">
                    <strong>ยังไม่มีเหตุการณ์ที่บันทึกไว้</strong>
                  </div>
                ) : (
                  <div className="admin-list">
                    {auditLogs.map((entry) => (
                      <div className="admin-list-row" key={entry.id}>
                        <div className="admin-list-main">
                          <strong>{entry.action}</strong>
                          <span className="admin-list-meta tabular-nums">
                            actor_user_id: <code>{entry.actor_user_id ?? "system/deleted"}</code> ·
                            ทรัพยากร {entry.resource_id ?? "ไม่ระบุ"} ·{" "}
                            {new Date(entry.created_at).toLocaleString("th-TH")}
                          </span>
                        </div>
                        <StatusBadge tone="neutral">
                          {entry.outcome || "AUDIT"}
                        </StatusBadge>
                      </div>
                    ))}
                  </div>
                )
              ) : (
                <div className="unavailable-block">
                  <strong>Backend ไม่สามารถยืนยัน Audit Log ได้</strong>
                </div>
              )}
            </Panel>
          </div>
        </>
      )}

      {lineageOpen ? (
        <div
          className="modal-backdrop"
          onClick={() => setLineageOpen(false)}
          role="presentation"
        >
          <div
            aria-labelledby="native-lineage-modal-title"
            aria-modal="true"
            className="modal-dialog panel"
            onClick={(event) => event.stopPropagation()}
            ref={modalDialogRef}
            role="dialog"
            tabIndex={-1}
          >
            <div className="modal-header">
              <div>
                <div className="eyebrow">
                  <Icon name="history" size={14} />
                  <span>MODEL ARTIFACT HISTORY</span>
                </div>
                <h2 id="native-lineage-modal-title">
                  Training Artifact Lineage
                  {resolvedModelVersion || overview?.native_ai.model_version
                    ? ` · ${resolvedModelVersion ?? overview?.native_ai.model_version}`
                    : ""}
                </h2>
              </div>
              <button
                aria-label="ปิดหน้าต่าง Lineage"
                className="icon-button"
                onClick={() => setLineageOpen(false)}
                type="button"
              >
                <Icon name="close" size={18} />
              </button>
            </div>

            <div className="modal-body">
              {lineageLoading ? (
                <div className="unavailable-block" role="status">
                  <strong>กำลังโหลดประวัติ Training Artifacts...</strong>
                  <p>กำลังตรวจสอบข้อมูลจาก Model Registry และสายประวัติ Checkpoint</p>
                </div>
              ) : lineageError ? (
                <div className="unavailable-block">
                  <strong>ไม่สามารถโหลดประวัติ Lineage ได้</strong>
                  <p className="form-alert form-alert-error" role="alert">
                    <Icon name="close" size={15} />
                    <span>{lineageError}</span>
                  </p>
                </div>
              ) : !lineageData ? (
                <div className="unavailable-block">
                  <strong>ยังไม่มีข้อมูลโมเดลที่โหลดอยู่ในขณะนี้</strong>
                  <p>
                    {overview?.native_ai.native_model_loaded === false
                      ? "Runtime รายงานว่ายังไม่ได้โหลด Native Model และไม่พบ Active Version ใน Registry"
                      : "ไม่พบข้อมูล Training Artifact สำหรับโมเดลปัจจุบัน"}
                  </p>
                </div>
              ) : (
                <>
                  <div className="lineage-summary-strip">
                    <div className="lineage-badges">
                      <StatusBadge tone={lifecycleTone(lineageData.record.lifecycle_status)}>
                        {lineageData.record.lifecycle_status ?? "registered"}
                      </StatusBadge>
                      <StatusBadge
                        tone={lineageData.compatibility.compatible ? "good" : "bad"}
                      >
                        {lineageData.compatibility.compatible
                          ? "Compatibility PASS"
                          : "Compatibility FAIL"}
                      </StatusBadge>
                      <StatusBadge tone="info">
                        Depth {lineageData.lineage.depth}
                      </StatusBadge>
                    </div>
                    {lineageData.compatibility.reasons.length > 0 ? (
                      <ul className="lineage-reasons">
                        {lineageData.compatibility.reasons.map((reason) => (
                          <li key={reason}>{reason}</li>
                        ))}
                      </ul>
                    ) : null}
                  </div>

                  <div className="lineage-artifact-grid tabular-nums">
                    <div className="lineage-artifact-item">
                      <span>Checkpoint</span>
                      <strong>
                        {lineageData.record.checkpoint?.path ??
                          (lineageData.record.checkpoint?.step !== undefined
                            ? `step ${lineageData.record.checkpoint.step}`
                            : "—")}
                      </strong>
                      <code>{shortDigest(lineageData.record.checkpoint?.sha256)}</code>
                    </div>
                    <div className="lineage-artifact-item">
                      <span>Dataset</span>
                      <strong>{lineageData.record.dataset?.version ?? "—"}</strong>
                      <code>{shortDigest(lineageData.record.dataset?.content_sha256)}</code>
                    </div>
                    <div className="lineage-artifact-item">
                      <span>Tokenizer</span>
                      <strong>{lineageData.record.tokenizer?.path ?? "—"}</strong>
                      <code>{shortDigest(lineageData.record.tokenizer?.sha256)}</code>
                    </div>
                    <div className="lineage-artifact-item">
                      <span>Evaluation Evidence</span>
                      <strong>
                        {lineageData.record.evaluation_evidence
                          ? lineageData.record.evaluation_evidence.passed
                            ? "PASS"
                            : "FAIL"
                          : "NOT RUN"}
                      </strong>
                      <code>
                        {shortDigest(lineageData.record.evaluation_evidence?.report_sha256)}
                      </code>
                    </div>
                  </div>

                  <div className="lineage-chain-section">
                    <div className="lineage-section-title">
                      <div>
                        <strong>Training Artifact History ({lineageData.lineage.ancestors.length})</strong>
                        <small>เรียงจากรุ่นที่โหลดปัจจุบันย้อนกลับไปยัง Baseline</small>
                      </div>
                      <div className="workflow-actions">
                        <button
                          className="button button-secondary button-compact"
                          disabled={artifactBusy !== null}
                          onClick={() => void handleDownloadArtifact(lineageData.record.version, "logs")}
                          type="button"
                        >
                          <Icon name="download" size={14} />
                          {artifactBusy === "logs" ? "กำลังดาวน์โหลด..." : "Download Raw Training Logs"}
                        </button>
                        <button
                          className="button button-secondary button-compact"
                          disabled={artifactBusy !== null}
                          onClick={() => void handleDownloadArtifact(lineageData.record.version, "manifest")}
                          type="button"
                        >
                          <Icon name="download" size={14} />
                          {artifactBusy === "manifest" ? "กำลังดาวน์โหลด..." : "Download Manifest JSON"}
                        </button>
                        <button
                          className="button button-secondary button-compact"
                          disabled={artifactBusy !== null}
                          onClick={() => void handleDownloadArtifact(lineageData.record.version, "metadata")}
                          type="button"
                        >
                          <Icon name="download" size={14} />
                          {artifactBusy === "metadata" ? "กำลังส่งออก..." : "Export Metadata JSON"}
                        </button>
                      </div>
                    </div>
                    {artifactError ? (
                      <p className="form-alert form-alert-error" role="alert">
                        <Icon name="close" size={15} />
                        <span>{artifactError}</span>
                      </p>
                    ) : null}
                    {artifactNotice ? (
                      <p className="form-alert" role="status">
                        <Icon name="check-circle" size={15} />
                        <span>{artifactNotice}</span>
                      </p>
                    ) : null}
                    <div className="lineage-chain">
                      {lineageData.lineage.ancestors.map((node, index) => {
                        const workflowEntries = Object.entries(
                          node.workflow_lineage ?? {},
                        ).filter(([, val]) => val !== null && val !== undefined && val !== "");
                        return (
                          <div className="lineage-node-card" key={`${node.version}-${index}`}>
                            <div className="lineage-node-head">
                              <div className="lineage-node-title">
                                <strong>{node.version}</strong>
                                {index === 0 ? (
                                  <StatusBadge tone="info">Current</StatusBadge>
                                ) : null}
                                {node.parent ? (
                                  <span className="lineage-parent-tag">
                                    parent: <code>{node.parent}</code>
                                  </span>
                                ) : (
                                  <span className="lineage-parent-tag">root baseline</span>
                                )}
                              </div>
                              <StatusBadge tone={lifecycleTone(node.lifecycle_status)}>
                                {node.lifecycle_status}
                              </StatusBadge>
                            </div>

                            <div className="lineage-meta-grid tabular-nums">
                              <div>
                                <span>Dataset</span>
                                <code>
                                  {node.dataset_version ?? "—"}{" "}
                                  {node.dataset_sha256 ? `(${shortDigest(node.dataset_sha256)})` : ""}
                                </code>
                              </div>
                              <div>
                                <span>Checkpoint SHA-256</span>
                                <code>{shortDigest(node.checkpoint_sha256)}</code>
                              </div>
                              <div>
                                <span>Tokenizer SHA-256</span>
                                <code>{shortDigest(node.tokenizer_sha256)}</code>
                              </div>
                              <div>
                                <span>Evaluation</span>
                                <code>
                                  {node.eval_passed === null || node.eval_passed === undefined
                                    ? "NOT RUN"
                                    : node.eval_passed
                                      ? "PASS"
                                      : "FAIL"}
                                  {node.eval_report_sha256
                                    ? ` (${shortDigest(node.eval_report_sha256)})`
                                    : ""}
                                </code>
                              </div>
                              {node.created_at ? (
                                <div>
                                  <span>Created</span>
                                  <code>{formatLineageTimestamp(node.created_at)}</code>
                                </div>
                              ) : null}
                              {workflowEntries.map(([key, val]) => (
                                <div key={key}>
                                  <span>{key}</span>
                                  <code>{String(val)}</code>
                                </div>
                              ))}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </>
              )}
            </div>

            <div className="modal-footer">
              <Link className="text-link" href="/developer/console">
                เปิด Model Registry &amp; Workflows
                <Icon name="arrow-right" size={15} />
              </Link>
              <button
                className="button button-secondary"
                onClick={() => setLineageOpen(false)}
                type="button"
              >
                ปิด
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
