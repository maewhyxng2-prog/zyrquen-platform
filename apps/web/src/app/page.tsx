"use client";

import Link from "next/link";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { Icon } from "@/components/Icon";
import { usePlatformHealth } from "@/hooks/usePlatformHealth";

function valueForHealth(ok: boolean | null, label: string) {
  if (ok === null) return { text: "Unavailable", tone: "neutral" as const };
  return ok
    ? { text: label, tone: "good" as const }
    : { text: "Degraded", tone: "warn" as const };
}

export default function DashboardPage() {
  const { apiHealth, nativeHealth, apiError, nativeError, loading, lastChecked, refresh } =
    usePlatformHealth();
  const apiStatus = valueForHealth(apiHealth?.status === "healthy", "Operational");
  const nativeStatus = valueForHealth(
    nativeHealth ? nativeHealth.inference_available : null,
    "Inference ready",
  );

  return (
    <div className="page-stack">
      <PageHeader
        action={
          <button className="button button-secondary" onClick={() => void refresh()} type="button">
            <Icon name="activity" size={16} /> Refresh status
          </button>
        }
        description="A live overview of the platform services that expose health data."
        eyebrow="PLATFORM / OVERVIEW"
        icon="gauge"
        title="Command center"
      />

      <section aria-label="Operational status" className="status-grid">
        <Panel className="metric-card">
          <div className="metric-topline"><span className="metric-icon"><Icon name="server" /></span><span className="metric-label">API SERVICE</span></div>
          <div className="metric-value">{loading && !apiHealth ? "Checking" : apiStatus.text}</div>
          <div className="metric-foot">
            <StatusBadge tone={apiStatus.tone}>{apiStatus.text}</StatusBadge>
            <span className="metric-caption">{apiError || apiHealth?.service || "GET /health"}</span>
          </div>
        </Panel>
        <Panel className="metric-card">
          <div className="metric-topline"><span className="metric-icon metric-icon-cyan"><Icon name="cpu" /></span><span className="metric-label">NATIVE AI RUNTIME</span></div>
          <div className="metric-value">{loading && !nativeHealth ? "Checking" : nativeStatus.text}</div>
          <div className="metric-foot">
            <StatusBadge tone={nativeStatus.tone}>{nativeHealth?.runtime_status || (nativeError ? "Unavailable" : "Checking")}</StatusBadge>
            <span className="metric-caption">{nativeHealth ? (nativeHealth.native_model_loaded ? "Model loaded" : "Model not loaded") : "Model state unavailable"}</span>
          </div>
        </Panel>
        <Panel className="metric-card">
          <div className="metric-topline"><span className="metric-icon metric-icon-blue"><Icon name="database" /></span><span className="metric-label">DATASET PIPELINE</span></div>
          <div className="metric-value metric-value-small">Core module present</div>
          <div className="metric-foot">
            <StatusBadge tone="info">API unavailable</StatusBadge>
            <span className="metric-caption">No dataset status endpoint</span>
          </div>
        </Panel>
        <Panel className="metric-card">
          <div className="metric-topline"><span className="metric-icon metric-icon-violet"><Icon name="layers" /></span><span className="metric-label">TRAINING PIPELINE</span></div>
          <div className="metric-value metric-value-small">Core module present</div>
          <div className="metric-foot">
            <StatusBadge tone="info">API unavailable</StatusBadge>
            <span className="metric-caption">No training execution endpoint</span>
          </div>
        </Panel>
      </section>

      <section className="dashboard-grid">
        <Panel className="dashboard-primary">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">RUNTIME TELEMETRY</div>
              <h2>Service readiness</h2>
            </div>
            <span className="updated-label">
              <span className="status-dot" /> {lastChecked ? `Checked ${lastChecked.toLocaleTimeString()}` : "Awaiting health check"}
            </span>
          </div>
          <div className="readiness-list">
            <div className="readiness-row">
              <span className="readiness-symbol"><Icon name="server" size={17} /></span>
              <div className="readiness-copy"><strong>FastAPI service</strong><small>{apiError || "Health endpoint: /health"}</small></div>
              <StatusBadge tone={apiStatus.tone}>{apiHealth ? apiStatus.text : "Unavailable"}</StatusBadge>
            </div>
            <div className="readiness-row">
              <span className="readiness-symbol"><Icon name="cpu" size={17} /></span>
              <div className="readiness-copy"><strong>Native inference</strong><small>{nativeHealth?.authority || nativeError || "Health endpoint: /v1/native-ai/health"}</small></div>
              <StatusBadge tone={nativeStatus.tone}>{nativeHealth?.inference_available ? "Ready" : nativeHealth ? "Unavailable" : "Unknown"}</StatusBadge>
            </div>
            <div className="readiness-row">
              <span className="readiness-symbol"><Icon name="shield" size={17} /></span>
              <div className="readiness-copy"><strong>Authentication</strong><small>JWT login and registration routes are available</small></div>
              <StatusBadge tone="info">Route available</StatusBadge>
            </div>
          </div>
          <div className="panel-link-row">
            <Link className="text-link" href="/system">View system details <Icon name="arrow-right" size={15} /></Link>
          </div>
        </Panel>

        <Panel className="quick-panel">
          <div className="eyebrow">WORKSPACE</div>
          <h2>Continue with ZYRQUEN</h2>
          <p>Use the native inference service when its runtime reports ready. Conversations are kept in this browser.</p>
          <Link className="button button-primary full-button" href="/workspace">
            <Icon name="sparkles" size={16} /> Open AI workspace <Icon name="arrow-right" size={16} />
          </Link>
          <div className="quick-divider" />
          <Link className="quick-link" href="/training"><span className="quick-link-icon"><Icon name="layers" size={16} /></span><span><strong>Training workspace</strong><small>Inspect available core modules</small></span><Icon name="chevron-right" size={16} /></Link>
        </Panel>
      </section>

      <section className="dashboard-grid dashboard-lower">
        <Panel>
          <div className="panel-heading">
            <div><div className="eyebrow">SYSTEM ACTIVITY</div><h2>Recent events</h2></div>
            <StatusBadge tone="neutral">No feed</StatusBadge>
          </div>
          <div className="empty-inline">
            <span className="empty-icon"><Icon name="activity" size={19} /></span>
            <div><strong>Activity data is not exposed</strong><p>The API has no events or audit-log endpoint.</p></div>
          </div>
        </Panel>
        <Panel>
          <div className="panel-heading">
            <div><div className="eyebrow">PLATFORM CAPABILITIES</div><h2>Core, connected honestly</h2></div>
            <Icon name="layers" size={18} className="subtle-icon" />
          </div>
          <p className="panel-body-copy">Dataset preparation and training modules exist in the core. They are not currently exposed as API operations, so no live runs, counts, or metrics are shown.</p>
          <Link className="text-link" href="/training">Explore training workspace <Icon name="arrow-right" size={15} /></Link>
        </Panel>
      </section>
    </div>
  );
}
