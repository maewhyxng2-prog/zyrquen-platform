"use client";

import { useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { Icon, type IconName } from "@/components/Icon";
import { usePlatformHealth } from "@/hooks/usePlatformHealth";
import { readSession } from "@/lib/api";
import type { Session } from "@/lib/types";

function SystemRow({
  icon,
  title,
  detail,
  state,
  tone,
}: {
  icon: IconName;
  title: string;
  detail: string;
  state: string;
  tone: "good" | "warn" | "bad" | "neutral" | "info";
}) {
  return (
    <div className="system-row">
      <span className="system-row-icon"><Icon name={icon} size={18} /></span>
      <div className="system-row-copy"><strong>{title}</strong><small>{detail}</small></div>
      <StatusBadge tone={tone}>{state}</StatusBadge>
    </div>
  );
}

export default function SystemPage() {
  const { apiHealth, nativeHealth, apiError, nativeError, loading, lastChecked, refresh } =
    usePlatformHealth();
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    readSession().then(setSession).catch(() => setSession(null));
  }, []);

  return (
    <div className="page-stack">
      <PageHeader
        action={<button className="button button-secondary" onClick={() => void refresh()} type="button"><Icon name="activity" size={16} /> Recheck services</button>}
        description="Live API health is checked against the existing FastAPI endpoints. Unsupported infrastructure signals remain unavailable."
        eyebrow="PLATFORM / OPERATIONS"
        icon="activity"
        title="System health"
      />
      <Panel>
        <div className="panel-heading">
          <div><div className="eyebrow">SERVICE INVENTORY</div><h2>Current service state</h2></div>
          <span className="updated-label">{lastChecked ? `Last checked ${lastChecked.toLocaleTimeString()}` : loading ? "Checking..." : "Not checked"}</span>
        </div>
        <div className="system-list">
          <SystemRow
            detail={apiError || `GET /health${apiHealth?.service ? ` · ${apiHealth.service}` : ""}`}
            icon="server"
            state={apiHealth?.status === "healthy" ? "Healthy" : apiHealth ? "Degraded" : "Unavailable"}
            title="API service"
            tone={apiHealth?.status === "healthy" ? "good" : apiHealth ? "warn" : "neutral"}
          />
          <SystemRow
            detail={nativeError || nativeHealth?.authority || "GET /v1/native-ai/health"}
            icon="cpu"
            state={nativeHealth?.runtime_status || "Unavailable"}
            title="Native runtime"
            tone={nativeHealth?.inference_available ? "good" : nativeHealth ? "warn" : "neutral"}
          />
          <SystemRow
            detail={session?.authenticated ? `Signed in${session.email ? ` as ${session.email}` : ""}` : "JWT login and registration are implemented"}
            icon="shield"
            state={session?.authenticated ? "Session present" : session ? "Signed out" : "Unknown"}
            title="Authentication"
            tone={session?.authenticated ? "good" : session ? "info" : "neutral"}
          />
          <SystemRow
            detail="No database health endpoint is implemented"
            icon="database"
            state="Unavailable"
            title="Database connectivity"
            tone="neutral"
          />
          <SystemRow
            detail="No storage health endpoint is implemented"
            icon="layers"
            state="Unavailable"
            title="Model and dataset storage"
            tone="neutral"
          />
          <SystemRow
            detail="No cloud provider or infrastructure telemetry endpoint is configured"
            icon="activity"
            state="Unavailable"
            title="Infrastructure telemetry"
            tone="neutral"
          />
        </div>
      </Panel>
      <Panel className="notice-panel">
        <span className="notice-icon"><Icon name="help" size={18} /></span>
        <div><strong>Health scope</strong><p>The API reports overall service health and native runtime readiness. Database, storage, GPU utilization, and event history are not independently exposed by current API routes.</p></div>
      </Panel>
    </div>
  );
}
