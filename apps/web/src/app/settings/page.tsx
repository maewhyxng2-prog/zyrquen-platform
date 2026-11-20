"use client";

import { useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { Icon } from "@/components/Icon";

const CONVERSATIONS_KEY = "zyrquen.local-conversations.v1";

export default function SettingsPage() {
  const [cleared, setCleared] = useState(false);

  function clearConversationHistory() {
    window.localStorage.removeItem(CONVERSATIONS_KEY);
    window.dispatchEvent(new Event("zyrquen:conversations-cleared"));
    setCleared(true);
  }

  return (
    <div className="page-stack">
      <PageHeader
        description="Connection targets are configured by the server environment. Secrets and access tokens are never editable in this browser."
        eyebrow="PLATFORM / PREFERENCES"
        icon="settings"
        title="Settings"
      />
      <div className="settings-grid">
        <Panel>
          <div className="panel-heading"><div><div className="eyebrow">API CONNECTION</div><h2>Backend endpoint</h2></div><span className="metric-icon metric-icon-blue"><Icon name="server" /></span></div>
          <div className="settings-info">
            <span>Configuration variable</span><code>ZYRQUEN_API_BASE_URL</code>
            <p>Set this on the Next.js server (for example, <code>http://localhost:8000</code>). Browser requests use the same-origin proxy, which forwards only existing health, authentication, and inference routes.</p>
          </div>
          <div className="security-callout"><Icon name="lock" size={16} /><span>The upstream URL is server-side configuration and is not exposed as a client-editable value.</span></div>
        </Panel>
        <Panel>
          <div className="panel-heading"><div><div className="eyebrow">LOCAL DATA</div><h2>Conversation history</h2></div><span className="metric-icon"><Icon name="history" /></span></div>
          <div className="settings-info">
            <span>Storage location</span><code>This browser · localStorage</code>
            <p>Conversation prompts and responses are saved locally on this device. They are not sent to an account history service.</p>
          </div>
          <button className="button button-danger" onClick={clearConversationHistory} type="button"><Icon name="close" size={16} /> Clear local conversation history</button>
          {cleared && <p className="settings-confirmation" role="status"><Icon name="check-circle" size={15} /> Local conversation history cleared.</p>}
        </Panel>
      </div>
    </div>
  );
}
