"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { readSession } from "@/lib/api";
import type {
  WorkflowActiveJobSummary,
  WorkflowExecutionLogItem,
  WorkflowExecutionLogLevel,
  WorkflowLogsResponse,
} from "@/lib/types";
import {
  buildWorkflowLogsQuery,
  filterWorkflowLogs,
  formatWorkflowLogTime,
} from "@/lib/workflow-logs";
import { Icon } from "./Icon";
import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";

const POLL_INTERVAL_MS = 2500;

function toneForLogLevel(level: WorkflowExecutionLogLevel): "info" | "warn" | "bad" {
  switch (level) {
    case "ERROR":
      return "bad";
    case "WARN":
      return "warn";
    default:
      return "info";
  }
}

function readDetailValue(
  details: Record<string, unknown> | null | undefined,
  key: string,
): string | null {
  if (!details) return null;
  const val = details[key];
  if (typeof val === "string" && val.trim()) return val.trim();
  if (typeof val === "number" && Number.isFinite(val)) return String(val);
  return null;
}

export function WorkflowLogsPanel() {
  const [authChecked, setAuthChecked] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const [logs, setLogs] = useState<WorkflowExecutionLogItem[]>([]);
  const [activeRuns, setActiveRuns] = useState<WorkflowActiveJobSummary[]>([]);
  const [polledAt, setPolledAt] = useState<string | null>(null);

  const [activeOnly, setActiveOnly] = useState(true);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [levelFilter, setLevelFilter] = useState<"ALL" | WorkflowExecutionLogLevel>("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [livePolling, setLivePolling] = useState(true);
  const [autoPinTop, setAutoPinTop] = useState(true);

  const feedRef = useRef<HTMLDivElement | null>(null);

  const fetchLogs = useCallback(
    async (options?: { silent?: boolean; isCancelled?: () => boolean }) => {
      const silent = Boolean(options?.silent);
      if (!silent) {
        setRefreshing(true);
      }

      try {
        const session = await readSession();
        if (options?.isCancelled?.()) return;
        setAuthChecked(true);
        if (!session.authenticated) {
          setAuthenticated(false);
          setLogs([]);
          setActiveRuns([]);
          setError("");
          return;
        }
        setAuthenticated(true);

        const query = buildWorkflowLogsQuery({
          activeOnly,
          runId: selectedRunId || undefined,
          limit: 150,
        });
        const response = await fetch(`/api/v1/workflows/logs?${query}`, {
          method: "GET",
          cache: "no-store",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        if (options?.isCancelled?.()) return;

        if (response.status === 401) {
          window.dispatchEvent(new Event("zyrquen:session-change"));
          setAuthenticated(false);
          setLogs([]);
          setActiveRuns([]);
          setError("");
          return;
        }

        const payload = (await response.json().catch(() => null)) as
          | (WorkflowLogsResponse & { detail?: string; error?: string })
          | null;

        if (!response.ok || !payload) {
          throw new Error(
            payload?.detail ||
              payload?.error ||
              `ไม่สามารถดึง Execution Logs ได้ (HTTP ${response.status})`,
          );
        }

        setLogs(Array.isArray(payload.items) ? payload.items : []);
        setActiveRuns(Array.isArray(payload.active_runs) ? payload.active_runs : []);
        setPolledAt(payload.polled_at ?? new Date().toISOString());
        setError("");
      } catch (err) {
        if (options?.isCancelled?.()) return;
        setError(
          err instanceof Error
            ? err.message
            : "ไม่สามารถเชื่อมต่อ /api/v1/workflows/logs ได้",
        );
      } finally {
        if (!options?.isCancelled?.()) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    },
    [activeOnly, selectedRunId],
  );

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (!cancelled) {
        void fetchLogs({ isCancelled: () => cancelled });
      }
    });

    const handleSessionChange = () => {
      if (!cancelled) {
        void fetchLogs({ isCancelled: () => cancelled });
      }
    };
    window.addEventListener("zyrquen:session-change", handleSessionChange);

    return () => {
      cancelled = true;
      window.removeEventListener("zyrquen:session-change", handleSessionChange);
    };
  }, [fetchLogs]);

  useEffect(() => {
    if (!authenticated || !livePolling) return;
    let cancelled = false;
    const intervalId = window.setInterval(() => {
      void fetchLogs({ silent: true, isCancelled: () => cancelled });
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [authenticated, livePolling, fetchLogs]);

  useEffect(() => {
    if (autoPinTop && feedRef.current) {
      feedRef.current.scrollTop = 0;
    }
  }, [logs, autoPinTop]);

  const filteredLogs = useMemo(
    () =>
      filterWorkflowLogs(logs, {
        level: levelFilter,
        search: searchQuery,
      }),
    [logs, levelFilter, searchQuery],
  );

  if (authChecked && !authenticated) {
    return (
      <Panel aria-label="Real-time Workflow Execution Logs" className="workflow-panel">
        <div className="panel-heading">
          <div>
            <div className="eyebrow">
              <Icon name="terminal" size={14} />
              <span>REAL-TIME ORCHESTRATION EXECUTION LOGS</span>
            </div>
            <h2>บันทึกการทำงานแบบเรียลไทม์ของ Workflow Orchestrator</h2>
          </div>
          <StatusBadge tone="neutral">ต้องลงชื่อเข้าใช้</StatusBadge>
        </div>
        <div className="unavailable-block">
          <strong>กรุณาเข้าสู่ระบบเพื่อดู Execution Logs จริงจาก Orchestrator</strong>
          <p>
            แผงนี้ดึงข้อมูลสดจาก <code>/api/v1/workflows/logs</code> และจะไม่สร้างบันทึกการทำงานจำลองเมื่อยังไม่ได้ยืนยันตัวตน
          </p>
          <div className="unavailable-actions">
            <Link className="button button-primary" href="/login">
              เข้าสู่ระบบ
            </Link>
          </div>
        </div>
      </Panel>
    );
  }

  return (
    <Panel aria-label="Real-time Workflow Execution Logs" className="workflow-panel">
      <div className="panel-heading">
        <div>
          <div className="eyebrow">
            <Icon name="terminal" size={14} />
            <span>REAL-TIME ORCHESTRATION LOGS · /API/V1/WORKFLOWS/LOGS</span>
          </div>
          <h2>บันทึกการทำงานแบบเรียลไทม์ (Active Orchestration Jobs)</h2>
        </div>

        <div className="workflow-actions">
          <StatusBadge tone={activeRuns.length > 0 ? "info" : "neutral"}>
            {activeRuns.length} Active {activeRuns.length === 1 ? "Job" : "Jobs"}
          </StatusBadge>
          <StatusBadge tone={livePolling ? "good" : "neutral"}>
            {livePolling ? "Live · 2.5s" : "Paused"}
          </StatusBadge>
          <button
            className="button button-secondary button-compact"
            onClick={() => setLivePolling((prev) => !prev)}
            type="button"
          >
            <Icon name={livePolling ? "clock" : "zap"} size={14} />
            {livePolling ? "Pause Stream" : "Resume Live"}
          </button>
          <button
            className="button button-secondary button-compact"
            disabled={refreshing}
            onClick={() => void fetchLogs()}
            type="button"
          >
            <Icon name="activity" size={14} />
            {refreshing ? "กำลังดึงข้อมูล..." : "รีเฟรช"}
          </button>
        </div>
      </div>

      <div className="workflow-logs-toolbar">
        <div className="workflow-logs-controls">
          <div className="workflow-logs-segmented" role="group" aria-label="ขอบเขตงาน Workflow">
            <button
              aria-pressed={activeOnly}
              className={`button button-compact ${activeOnly ? "button-primary" : "button-secondary"}`}
              onClick={() => {
                setActiveOnly(true);
                setSelectedRunId("");
              }}
              type="button"
            >
              Active Jobs Only
            </button>
            <button
              aria-pressed={!activeOnly}
              className={`button button-compact ${!activeOnly ? "button-primary" : "button-secondary"}`}
              onClick={() => setActiveOnly(false)}
              type="button"
            >
              All Recent Runs
            </button>
          </div>

          <select
            aria-label="เลือก Active Orchestration Job"
            className="input workflow-logs-select"
            onChange={(e) => setSelectedRunId(e.target.value)}
            value={selectedRunId}
          >
            <option value="">
              {activeRuns.length > 0
                ? `ทุก Active Jobs (${activeRuns.length})`
                : "ทุก Job ในขอบเขตที่เลือก"}
            </option>
            {activeRuns.map((run) => (
              <option key={run.id} value={run.id}>
                {run.workflow_key} · {run.status} ({run.id.slice(0, 8)})
              </option>
            ))}
          </select>

          <div className="workflow-logs-levels" role="group" aria-label="กรองระดับ Log">
            {(["ALL", "INFO", "WARN", "ERROR"] as const).map((lvl) => (
              <button
                aria-pressed={levelFilter === lvl}
                className={`workflow-logs-level-btn ${levelFilter === lvl ? "is-active" : ""}`}
                key={lvl}
                onClick={() => setLevelFilter(lvl)}
                type="button"
              >
                {lvl}
              </button>
            ))}
          </div>
        </div>

        <div className="workflow-logs-search-row">
          <label className="workflow-logs-search">
            <Icon name="search" size={14} />
            <input
              aria-label="ค้นหาใน Execution Logs"
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="กรองตาม workflow_key, step_key, run_id หรือข้อความ..."
              type="search"
              value={searchQuery}
            />
            {searchQuery ? (
              <button
                aria-label="ล้างคำค้นหา"
                className="workflow-logs-search-clear"
                onClick={() => setSearchQuery("")}
                type="button"
              >
                <Icon name="close" size={12} />
              </button>
            ) : null}
          </label>

          <label className="workflow-logs-autoscroll">
            <input
              checked={autoPinTop}
              onChange={(e) => setAutoPinTop(e.target.checked)}
              type="checkbox"
            />
            <span>Pin latest</span>
          </label>
        </div>
      </div>

      <div className="workflow-logs-meta-bar tabular-nums">
        <span>
          แสดง {filteredLogs.length} / {logs.length} รายการ
          {activeOnly ? " (เฉพาะงานที่กำลังดำเนินการ)" : " (รวมงานล่าสุดทั้งหมด)"}
        </span>
        <span>
          อัปเดตล่าสุด: {polledAt ? formatWorkflowLogTime(polledAt) : "—"}
        </span>
      </div>

      {error ? (
        <p className="form-alert form-alert-error" role="alert">
          {error}
        </p>
      ) : null}

      {loading && logs.length === 0 ? (
        <div className="unavailable-block">
          <strong>กำลังเชื่อมต่อและโหลด Execution Logs จาก Backend...</strong>
        </div>
      ) : filteredLogs.length === 0 ? (
        <div className="unavailable-block">
          <strong>
            {activeOnly && activeRuns.length === 0
              ? "ไม่มี Active Orchestration Jobs ที่กำลังทำงานในขณะนี้"
              : "ไม่พบ Execution Logs ที่ตรงกับเงื่อนไขตัวกรอง"}
          </strong>
          <p>
            {activeOnly && activeRuns.length === 0
              ? "เมื่อสั่งรัน Workflow ด้านบน ระบบจะแสดง Log ของแต่ละ Step และ Approval Gate ที่นี่แบบเรียลไทม์ หรือสลับไปดูบันทึกจาก All Recent Runs"
              : "ลองปรับระดับ Log Filter ล้างคำค้นหา หรือกดรีเฟรชเพื่อดึงบันทึกล่าสุด"}
          </p>
          {activeOnly && activeRuns.length === 0 ? (
            <div className="unavailable-actions">
              <button
                className="button button-secondary button-compact"
                onClick={() => setActiveOnly(false)}
                type="button"
              >
                แสดง All Recent Runs
              </button>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="workflow-logs-feed" ref={feedRef} role="log" aria-live="polite">
          {filteredLogs.map((entry) => {
            const lane = readDetailValue(entry.details, "lane");
            const attempt = readDetailValue(entry.details, "attempt");
            const verdict = readDetailValue(entry.details, "verdict");

            return (
              <div className="workflow-log-row" key={entry.id}>
                <div className="workflow-log-head">
                  <div className="workflow-log-badges">
                    <span className="workflow-log-time tabular-nums">
                      {formatWorkflowLogTime(entry.timestamp)}
                    </span>
                    <StatusBadge tone={toneForLogLevel(entry.level)}>
                      {entry.level}
                    </StatusBadge>
                    <code className="workflow-log-key">
                      {entry.workflow_key || entry.event_type}
                    </code>
                    {entry.step_key ? (
                      <code className="workflow-log-step">#{entry.step_key}</code>
                    ) : null}
                    {entry.run_id ? (
                      <span className="workflow-log-runid tabular-nums">
                        run:{entry.run_id.slice(0, 8)}
                      </span>
                    ) : null}
                  </div>
                  <span className="workflow-log-status tabular-nums">{entry.status}</span>
                </div>

                <p className="workflow-log-message">{entry.message}</p>

                {lane || attempt || verdict ? (
                  <div className="workflow-log-details tabular-nums">
                    {lane ? <span>lane={lane}</span> : null}
                    {attempt ? <span>attempt={attempt}</span> : null}
                    {verdict ? <span>verdict={verdict}</span> : null}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
