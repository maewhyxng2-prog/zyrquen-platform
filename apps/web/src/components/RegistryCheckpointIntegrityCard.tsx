"use client";

import { useCallback, useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import {
  fetchAndVerifyLatestCheckpoint,
  shortSha256,
  type LatestCheckpointVerificationSnapshot,
} from "@/lib/checkpoint-integrity";

function formatCheckedAt(value?: string | null): string {
  if (!value) return "—";
  const ms = Date.parse(value);
  if (Number.isNaN(ms)) return value;
  return new Date(ms).toLocaleString("th-TH");
}

export function RegistryCheckpointIntegrityCard({
  refreshSignal = 0,
  className,
}: {
  refreshSignal?: number;
  className?: string;
}) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [snapshot, setSnapshot] =
    useState<LatestCheckpointVerificationSnapshot | null>(null);

  const runVerification = useCallback(async (isCancelled?: () => boolean) => {
    setLoading(true);
    setError("");
    try {
      const next = await fetchAndVerifyLatestCheckpoint();
      if (isCancelled?.()) return;
      setSnapshot(next);
    } catch (reason) {
      if (isCancelled?.()) return;
      setSnapshot(null);
      setError(
        reason instanceof Error
          ? reason.message
          : "ไม่สามารถตรวจสอบความสมบูรณ์ของ Checkpoint จาก Registry ได้",
      );
    } finally {
      if (!isCancelled?.()) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    let active = true;
    void runVerification(() => !active);
    return () => {
      active = false;
    };
  }, [refreshSignal, runVerification]);

  const verification = snapshot?.verification ?? null;
  const latestVersion = snapshot?.latestVersion ?? null;

  return (
    <Panel className={className}>
      <div className="panel-heading">
        <div>
          <div className="eyebrow">MODEL REGISTRY INTEGRITY</div>
          <h2>ความสมบูรณ์ Checkpoint ล่าสุด (.sha256)</h2>
        </div>
        <div className="panel-heading-actions">
          {loading && !verification ? (
            <StatusBadge tone="info">Checking...</StatusBadge>
          ) : error ? (
            <StatusBadge icon="close" tone="bad">
              Error
            </StatusBadge>
          ) : verification ? (
            <StatusBadge
              icon={verification.status === "Verified" ? "check-circle" : "close"}
              tone={verification.status === "Verified" ? "good" : "bad"}
            >
              {verification.status}
            </StatusBadge>
          ) : (
            <StatusBadge tone="neutral">Not Available</StatusBadge>
          )}
          <button
            className="button button-secondary button-compact"
            disabled={loading}
            onClick={() => void runVerification()}
            type="button"
          >
            <Icon name="shield" size={14} />
            {loading ? "กำลังตรวจสอบ..." : "Verify Now"}
          </button>
        </div>
      </div>

      {error ? (
        <p className="form-alert form-alert-error" role="alert">
          <Icon name="close" size={15} />
          <span>{error}</span>
        </p>
      ) : !snapshot && loading ? (
        <div className="unavailable-block" role="status">
          <strong>กำลังดึง Checkpoint ล่าสุดจาก Model Registry</strong>
          <p>กำลังคำนวณและเปรียบเทียบค่า SHA-256 กับไฟล์ .sha256...</p>
        </div>
      ) : !snapshot?.configured || !latestVersion || !verification ? (
        <div className="unavailable-block">
          <strong>ยังไม่มี Checkpoint ที่พร้อมตรวจสอบใน Registry</strong>
          <p>
            {snapshot?.registryDetail ??
              "Model Registry ยังไม่ถูกตั้งค่าหรือยังไม่มีเวอร์ชันที่ลงทะเบียน"}
          </p>
        </div>
      ) : (
        <div className="readiness-list">
          <div className="readiness-row">
            <span className="readiness-symbol">
              <Icon name="layers" size={16} />
            </span>
            <div className="readiness-copy">
              <strong>Latest Checkpoint Version</strong>
              <small>
                รุ่นล่าสุดใน Registry ({latestVersion.lifecycle_status ?? "registered"}
                {typeof latestVersion.checkpoint?.step === "number"
                  ? ` · step ${latestVersion.checkpoint.step}`
                  : ""}
                )
              </small>
            </div>
            <StatusBadge tone="info">{latestVersion.version}</StatusBadge>
          </div>

          <div className="readiness-row">
            <span className="readiness-symbol">
              <Icon name="file-check" size={16} />
            </span>
            <div className="readiness-copy">
              <strong>.sha256 Sidecar File</strong>
              <small>
                <code>{verification.sidecar_path ?? "—"}</code>
              </small>
            </div>
            <StatusBadge tone={verification.sidecar_present ? "good" : "bad"}>
              {verification.sidecar_present ? "Found" : "Missing"}
            </StatusBadge>
          </div>

          <div className="readiness-row">
            <span className="readiness-symbol">
              <Icon name="shield" size={16} />
            </span>
            <div className="readiness-copy">
              <strong>SHA-256 Verification</strong>
              <small className="tabular-nums">
                Expected: <code>{shortSha256(verification.expected_sha256)}</code> ·
                Actual: <code>{shortSha256(verification.actual_sha256)}</code>
              </small>
            </div>
            <StatusBadge
              icon={verification.status === "Verified" ? "check-circle" : "close"}
              tone={verification.status === "Verified" ? "good" : "bad"}
            >
              {verification.status}
            </StatusBadge>
          </div>

          <div className="readiness-row">
            <span className="readiness-symbol">
              <Icon name="clock" size={16} />
            </span>
            <div className="readiness-copy">
              <strong>{verification.detail}</strong>
              <small className="tabular-nums">
                ตรวจสอบเมื่อ {formatCheckedAt(verification.checked_at)}
              </small>
            </div>
          </div>
        </div>
      )}
    </Panel>
  );
}
