import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { Icon } from "@/components/Icon";

function CapabilityPanel({
  phase,
  title,
  description,
  source,
}: {
  phase: string;
  title: string;
  description: string;
  source: string;
}) {
  return (
    <Panel className="capability-panel">
      <div className="capability-top">
        <span className="phase-label">{phase}</span>
        <StatusBadge tone="info">Core code present · API unavailable</StatusBadge>
      </div>
      <h2>{title}</h2>
      <p>{description}</p>
      <div className="capability-source"><Icon name="terminal" size={14} /><code>{source}</code></div>
    </Panel>
  );
}

export default function TrainingPage() {
  return (
    <div className="page-stack">
      <PageHeader
        description="Inspect the Phase 3.3–3.4 capabilities implemented in the repository. This workspace does not start jobs or report invented run data."
        eyebrow="NATIVE AI / TRAINING"
        icon="layers"
        title="Training workspace"
      />

      <Panel className="training-banner">
        <div className="training-banner-icon"><Icon name="file-check" size={21} /></div>
        <div>
          <StatusBadge tone="good">SOURCE MODULES PRESENT</StatusBadge>
          <h2>Dataset preparation and training pipeline</h2>
          <p>Core implementations are available as Python modules. The FastAPI application currently exposes no dataset, training, metrics, or job-history routes.</p>
        </div>
      </Panel>

      <section className="capability-grid" aria-label="Implemented training capabilities">
        <CapabilityPanel
          description="Imports JSONL and text, cleans and normalizes documents, optionally redacts common PII patterns, filters and deduplicates content, assigns deterministic splits, and writes a hash-verified manifest."
          phase="PHASE 3.3"
          source="apps/core/native/dataset.py"
          title="Dataset preparation"
        />
        <CapabilityPanel
          description="Provides token-stream construction, deterministic batch sampling, warmup/cosine learning-rate scheduling, evaluation, monitoring, and checkpoint-resume hooks."
          phase="PHASE 3.4"
          source="apps/core/native/train.py"
          title="Training pipeline"
        />
      </section>

      <div className="eyebrow section-eyebrow">PIPELINE OBSERVABILITY</div>
      <section className="training-data-grid">
        <Panel className="training-data-card">
          <div className="data-card-heading"><span className="metric-icon"><Icon name="database" /></span><span className="metric-label">DATASET STATUS</span></div>
          <div className="unavailable-block"><strong>Unavailable in web API</strong><p>No dataset listing, validation, upload, or manifest endpoint is exposed.</p></div>
        </Panel>
        <Panel className="training-data-card">
          <div className="data-card-heading"><span className="metric-icon metric-icon-blue"><Icon name="activity" /></span><span className="metric-label">TRAINING EXECUTION</span></div>
          <div className="unavailable-block"><strong>No live run data</strong><p>No job start/stop, configuration, logs, metrics, or history endpoint is exposed.</p></div>
        </Panel>
        <Panel className="training-data-card">
          <div className="data-card-heading"><span className="metric-icon metric-icon-violet"><Icon name="cpu" /></span><span className="metric-label">RESOURCE UTILIZATION</span></div>
          <div className="unavailable-block"><strong>Not reported</strong><p>GPU and compute metrics are not available through the current API.</p></div>
        </Panel>
      </section>

      <section className="future-grid" aria-label="Future training workspace sections">
        <Panel className="future-card">
          <div className="future-title"><Icon name="layers" size={17} /><span>Checkpoint management</span></div>
          <StatusBadge tone="neutral">Planned · not API-integrated</StatusBadge>
          <p>No checkpoint-management endpoint is available to this frontend.</p>
        </Panel>
        <Panel className="future-card">
          <div className="future-title"><Icon name="history" size={17} /><span>Model versioning</span></div>
          <StatusBadge tone="neutral">Planned · not API-integrated</StatusBadge>
          <p>Version records cannot be listed or verified through current API routes.</p>
        </Panel>
        <Panel className="future-card">
          <div className="future-title"><Icon name="check-circle" size={17} /><span>Evaluation engine</span></div>
          <StatusBadge tone="neutral">Planned · not API-integrated</StatusBadge>
          <p>Evaluation scores and validation reports are not exposed by the API.</p>
        </Panel>
      </section>
      <p className="footnote"><Icon name="help" size={14} /> Dataset PII redaction is pattern-based; the core module does not claim complete privacy protection.</p>
    </div>
  );
}
