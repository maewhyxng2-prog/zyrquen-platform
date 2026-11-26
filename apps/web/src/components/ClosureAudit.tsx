"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Icon } from "@/components/Icon";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { apiRequest } from "@/lib/api";
import {
  computeV11ProgressMetrics,
  describeBlocker,
  labelForAuditStatus,
  toneForAuditStatus,
} from "@/lib/closure-audit";
import type { V10ClosureAudit } from "@/lib/types";

export function ClosureAudit({
  refreshTrigger = 0,
}: {
  refreshTrigger?: number;
}) {
  const [audit, setAudit] = useState<V10ClosureAudit | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestIdRef = useRef(0);

  const loadAudit = useCallback(async () => {
    const reqId = ++requestIdRef.current;
    setLoading(true);
    try {
      const data = await apiRequest<V10ClosureAudit>("v1/v10/closure-audit");
      if (reqId !== requestIdRef.current) return;
      if (!data || data.schema !== "zyrquen.v10.closure_audit.v1") {
        setAudit(null);
        setError(
          "ข้อมูลจาก /v1/v10/closure-audit ไม่ตรงตามสคีมา zyrquen.v10.closure_audit.v1",
        );
      } else {
        setAudit(data);
        setError(null);
      }
    } catch (reason) {
      if (reqId !== requestIdRef.current) return;
      setAudit(null);
      setError(
        reason instanceof Error
          ? reason.message
          : "ไม่สามารถดึงสถานะ Closure Audit จาก Backend ได้",
      );
    } finally {
      if (reqId === requestIdRef.current) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadAudit();
    }, 0);
    return () => {
      window.clearTimeout(timer);
      requestIdRef.current += 1;
    };
  }, [loadAudit, refreshTrigger]);

  const metrics = audit ? computeV11ProgressMetrics(audit) : null;

  return (
    <Panel className="closure-audit-panel">
      <div className="panel-heading">
        <div>
          <div className="eyebrow">
            V10 → V11 CLOSURE AUDIT · zyrquen.v10.closure_audit.v1
          </div>
          <h2>Closure Audit — สถานะการปิดงาน V10 และเกณฑ์สู่ V11</h2>
        </div>

        <div className="closure-audit-head-actions">
          {audit && (
            <>
              <StatusBadge tone={toneForAuditStatus(audit.overall_status)}>
                V10 · {audit.overall_status}
              </StatusBadge>
              <StatusBadge
                icon={audit.v11_gate.unlocked ? "check-circle" : "lock"}
                tone={toneForAuditStatus(audit.v11_gate.status)}
              >
                V11 · {audit.v11_gate.status}
              </StatusBadge>
            </>
          )}
          <button
            className="button button-secondary closure-refresh-btn"
            disabled={loading}
            onClick={() => void loadAudit()}
            type="button"
          >
            <Icon name="activity" size={14} />
            {loading ? "กำลังตรวจสอบ..." : "ตรวจซ้ำ"}
          </button>
        </div>
      </div>

      {loading && !audit && !error ? (
        <div className="unavailable-block">
          <strong>กำลังตรวจสอบสัญญา Integration Contracts 1–5 และสถานะ V10 Closure จาก Backend</strong>
          <p>
            กำลังเรียก GET /v1/v10/closure-audit เพื่อยืนยันความพร้อมของสถาปัตยกรรม รันไทม์ PyTorch และหลักฐานการประเมินจริง
          </p>
        </div>
      ) : error ? (
        <div className="unavailable-block">
          <strong>ไม่สามารถตรวจสอบ V10 Closure Audit จาก Backend ได้</strong>
          <p>{error}</p>
        </div>
      ) : audit && metrics ? (
        <>
          <div className="closure-kpi-grid">
            <div className="closure-kpi-cell">
              <span className="metric-label">CONTRACTS 1–5 (V10-A)</span>
              <div className="closure-kpi-value tabular-nums">
                {audit.contracts_passed_count} / {audit.contracts_total}
              </div>
              <span className="closure-kpi-note tabular-nums">
                {audit.static_status} · {metrics.contractsRatioPct}% ผ่านเกณฑ์สถิต
              </span>
            </div>

            <div className="closure-kpi-cell">
              <span className="metric-label">PYTORCH RUNTIME (V10-D)</span>
              <div className="closure-kpi-value">
                {audit.runtime_environment.torch_installed ? "พร้อมใช้งาน" : "ไม่พบ torch"}
              </div>
              <span className="closure-kpi-note">
                Runtime: {audit.runtime_environment.native_runtime_status} · Trained:{" "}
                {audit.runtime_environment.is_trained ? "Yes" : "No"}
              </span>
            </div>

            <div className="closure-kpi-cell">
              <span className="metric-label">หลักฐาน EVAL & REGISTRY</span>
              <div className="closure-kpi-value tabular-nums">
                {audit.runtime_environment.verified_v10_models} รุ่นยืนยัน
              </div>
              <span className="closure-kpi-note">
                Eval:{" "}
                {audit.runtime_environment.eval_report_configured
                  ? audit.runtime_environment.eval_report_status || "CONFIGURED"
                  : "ยังไม่กำหนดค่า"}
              </span>
            </div>

            <div className="closure-kpi-cell">
              <span className="metric-label">ประตูอนุมัติสู่ V11</span>
              <div className="closure-kpi-value">
                {audit.v11_gate.unlocked ? "READY · ปลดล็อกแล้ว" : "LOCKED · รอปิด V10-D"}
              </div>
              <span className="closure-kpi-note tabular-nums">
                ผ่านแล้ว {metrics.stagesReadyCount}/{metrics.stagesTotal} ขั้นตอน
              </span>
            </div>
          </div>

          <div className="closure-gate-notice">
            <div className="closure-gate-copy">
              <strong>{audit.v11_gate.prerequisite_summary}</strong>
              {audit.blockers.length > 0 && (
                <ul className="closure-blocker-list">
                  {audit.blockers.map((code) => (
                    <li key={code}>
                      <code>{code}</code> — {describeBlocker(code)}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div className="closure-breakdown-grid">
            <div className="closure-section">
              <div className="closure-section-head">
                <span className="metric-label">INTEGRATION & ARCHITECTURE CONTRACTS 1–5</span>
                <span className="closure-section-meta tabular-nums">
                  อัปเดตเมื่อ {new Date(audit.checked_at).toLocaleTimeString("th-TH")}
                </span>
              </div>

              <div className="workflow-table-wrap">
                <table className="workflow-table">
                  <thead>
                    <tr>
                      <th>Contract</th>
                      <th>รายละเอียดและหลักฐานที่ตรวจจริง</th>
                      <th>สถานะ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {audit.contracts.map((contract) => (
                      <tr key={contract.id}>
                        <td>
                          <strong>{contract.id}</strong>
                          <div className="workflow-table-sub">
                            <code>{contract.code}</code>
                          </div>
                        </td>
                        <td>
                          <strong>{contract.title}</strong>
                          <div className="workflow-table-sub">{contract.summary}</div>
                          <div className="closure-anchor-line">
                            <code>{contract.anchor}</code>
                          </div>
                        </td>
                        <td>
                          <StatusBadge tone={toneForAuditStatus(contract.status)}>
                            {labelForAuditStatus(contract.status)}
                          </StatusBadge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="closure-section">
              <div className="closure-section-head">
                <span className="metric-label">V10 CLOSURE TRACKS · V10-A → V10-D → V11</span>
                <span className="closure-section-meta tabular-nums">
                  {metrics.stagesReadyCount}/{metrics.stagesTotal} stages ready
                </span>
              </div>

              <div className="closure-stage-list">
                {audit.stages.map((stage) => (
                  <div className="closure-stage-row" key={stage.id}>
                    <div className="closure-stage-head">
                      <span className="closure-stage-id">
                        <code>{stage.id}</code> · {stage.title}
                      </span>
                      <StatusBadge tone={toneForAuditStatus(stage.status)}>
                        {labelForAuditStatus(stage.status)}
                      </StatusBadge>
                    </div>
                    <p className="closure-stage-summary">{stage.summary}</p>
                    {stage.blockers.length > 0 && (
                      <div className="closure-stage-blockers">
                        Blockers: {stage.blockers.join(" · ")}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="panel-link-row closure-footer-links">
            <Link className="text-link" href="/training">
              เปิดคอนโซล Workflow & Model Registry
              <Icon name="arrow-right" size={15} />
            </Link>
            <Link className="text-link" href="/system">
              ตรวจสอบสถานะระบบและสภาพแวดล้อม
              <Icon name="arrow-right" size={15} />
            </Link>
          </div>
        </>
      ) : null}
    </Panel>
  );
}
