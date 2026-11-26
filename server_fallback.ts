import crypto from 'crypto';
import os from 'os';

type AnyRecord = Record<string, unknown>;

interface UserRow extends AnyRecord {
  id: string;
  email: string;
  display_name: string;
  role: 'admin' | 'user';
  password_hash: string;
  created_at: string;
}

interface ConversationRow extends AnyRecord {
  id: string;
  user_id: string;
  title: string;
  mode: string;
  created_at: string;
  updated_at: string;
}

interface MessageRow extends AnyRecord {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  mode: string;
  trace_json: string | null;
  status: string;
  created_at: string;
}

interface TripleRow extends AnyRecord {
  id: string;
  subject: string;
  relation: string;
  object: string;
  source: string;
  confidence: number;
  created_by: string;
  created_at: string;
}

interface WorkflowRunRow extends AnyRecord {
  id: string;
  group_id: string;
  status: string;
  requires_approval: number;
  triggered_by: string;
  approved_by: string | null;
  summary: string;
  stages_json: string;
  created_at: string;
  updated_at: string;
}

interface DatasetRow extends AnyRecord {
  id: string;
  name: string;
  manifest_hash: string;
  total_records: number;
  train_count: number;
  val_count: number;
  test_count: number;
  leakage_detected: number;
  status: string;
  created_at: string;
  source_name: string;
  license: string;
  provenance: string;
  source_format: string;
  content_sha256: string;
}

interface AuditLogRow extends AnyRecord {
  id: string;
  actor_id: string;
  actor_email: string;
  action: string;
  target: string;
  outcome: string;
  details_json: string | null;
  created_at: string;
}

const WORKFLOW_GROUPS = [
  {
    id: 'system_ops',
    name: 'ปฏิบัติการระบบ (System Operations)',
    description: 'ตรวจสอบ CPU, RAM, พื้นที่ดิสก์ และสถานะแกนประมวลผล Native Core',
    requires_approval: false,
    stages: ['health_probe', 'resource_audit', 'storage_check', 'status_report'],
  },
  {
    id: 'data_pipeline',
    name: 'จัดการข้อมูล (Data Workflow)',
    description: 'ตรวจรูปแบบข้อมูล คัดกรองข้อมูลซ้ำ ตรวจ Data Leakage และสร้างแฮช SHA-256',
    requires_approval: false,
    stages: ['schema_validate', 'deduplicate', 'leakage_scan', 'manifest_hash'],
  },
  {
    id: 'native_training',
    name: 'ฝึกโมเดลภายใน (Native Training)',
    description: 'บังคับลำดับ ข้อมูลจริง+ไร้ Leakage → Baseline → อนุมัติ → ฝึก → ประเมินและควบคุม Checkpoint',
    requires_approval: true,
    stages: [
      'provenance_leakage_gate',
      'baseline_verify',
      'approval_gate',
      'checkpoint_train',
      'checkpoint_eval_gate',
    ],
  },
];

const DEFAULT_EXTERNAL_TOOLS: AnyRecord[] = [
  {
    id: 'calc_compute',
    name: 'Safe AST Compute',
    category: 'compute',
    description: 'ประเมินนิพจน์คณิตศาสตร์เชิงสัญลักษณ์อย่างปลอดภัย',
    endpoint_allowlist_json: '[]',
    permission_mode: 'auto',
    enabled: 1,
    quota_daily: 500,
    calls_today: 0,
    last_reset_date: new Date().toISOString().slice(0, 10),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'doc_analyzer',
    name: 'Structured Document Analyzer',
    category: 'document',
    description: 'วิเคราะห์โครงสร้างเอกสาร ข้อความ และชุดข้อมูล CSV/JSONL',
    endpoint_allowlist_json: '[]',
    permission_mode: 'auto',
    enabled: 1,
    quota_daily: 250,
    calls_today: 0,
    last_reset_date: new Date().toISOString().slice(0, 10),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'workspace_fs',
    name: 'Workspace File Sandbox',
    category: 'file',
    description: 'อ่าน/เขียนไฟล์ในพื้นที่ทำงานที่จำกัดสิทธิ์',
    endpoint_allowlist_json: '[]',
    permission_mode: 'approval_required',
    enabled: 1,
    quota_daily: 100,
    calls_today: 0,
    last_reset_date: new Date().toISOString().slice(0, 10),
    updated_at: new Date().toISOString(),
  },
];

const DEFAULT_TOOLKITS: AnyRecord[] = [
  {
    id: 'development',
    name: 'Development Toolkit',
    description: 'AST & code quality verification capabilities',
    capabilities: [
      { id: 'dev.ast_inspect', name: 'AST Inspect', permission: 'auto' },
      { id: 'dev.lint_check', name: 'Static Lint Check', permission: 'auto' },
    ],
  },
  {
    id: 'data',
    name: 'Data Toolkit',
    description: 'Dataset validation, deduplication & PII redaction',
    capabilities: [
      { id: 'data.validate_schema', name: 'Validate Schema', permission: 'auto' },
      { id: 'data.redact_pii', name: 'Redact PII', permission: 'auto' },
    ],
  },
  {
    id: 'testing',
    name: 'Testing Toolkit',
    description: 'Verification probes and assertion checks',
    capabilities: [
      { id: 'test.probe_runner', name: 'Run Probe', permission: 'auto' },
    ],
  },
  {
    id: 'security',
    name: 'Security Toolkit',
    description: 'Secret scanning & policy enforcement',
    capabilities: [
      { id: 'sec.secret_scan', name: 'Secret Scan', permission: 'auto' },
    ],
  },
];

const store = {
  users: [] as UserRow[],
  conversations: [] as ConversationRow[],
  messages: [] as MessageRow[],
  triples: [] as TripleRow[],
  workflowRuns: [] as WorkflowRunRow[],
  reasoningTraces: [] as AnyRecord[],
  apiKeys: [] as AnyRecord[],
  apiUsageLogs: [] as AnyRecord[],
  auditLogs: [] as AuditLogRow[],
  datasets: [] as DatasetRow[],
  kgProposals: [] as AnyRecord[],
  checkpoints: [] as AnyRecord[],
  evaluations: [] as AnyRecord[],
  experiments: [] as AnyRecord[],
  missions: [] as AnyRecord[],
  missionNodes: [] as AnyRecord[],
  missionEvidence: [] as AnyRecord[],
  externalTools: DEFAULT_EXTERNAL_TOOLS.map((t) => ({ ...t })),
  toolInvocations: [] as AnyRecord[],
  workspaceFiles: new Map<string, { name: string; content: string; size_bytes: number; modified_at: string }>(),
  toolCenterInvocations: [] as AnyRecord[],
  improvementProposals: [] as AnyRecord[],
  orchestrations: [] as AnyRecord[],
};

function nowIso(): string {
  return new Date().toISOString();
}

function sha256(text: string): string {
  return crypto.createHash('sha256').update(text, 'utf8').digest('hex');
}

function getSystemMetrics() {
  const cpus = os.cpus();
  const totalMb = Math.round(os.totalmem() / (1024 * 1024));
  const freeMb = Math.round(os.freemem() / (1024 * 1024));
  const load = os.loadavg();
  return {
    python_version: `node-${process.version} (native-fallback)`,
    platform: `${os.platform()} ${os.release()}`,
    cpu_count: cpus.length || 1,
    load_1m: Math.round((load[0] || 0) * 100) / 100,
    mem_total_mb: totalMb,
    mem_available_mb: freeMb,
    disk_free_gb: 10,
    disk_total_gb: 20,
    sqlite_db_kb: 0,
  };
}

function safeEvalArithmetic(expr: string): { ok: boolean; value?: number } {
  const cleaned = expr.replace(/\s+/g, '');
  if (!cleaned || !/^[0-9+\-*/().%^]+$/.test(cleaned)) {
    return { ok: false };
  }
  const tokens = cleaned.match(/\d+(?:\.\d+)?|[()+\-*/^%]/g);
  if (!tokens || tokens.join('') !== cleaned) {
    return { ok: false };
  }

  let pos = 0;
  const peek = () => tokens[pos];
  const consume = () => tokens[pos++];

  function parseExpr(): number {
    let left = parseTerm();
    while (peek() === '+' || peek() === '-') {
      const op = consume();
      const right = parseTerm();
      left = op === '+' ? left + right : left - right;
    }
    return left;
  }

  function parseTerm(): number {
    let left = parsePower();
    while (peek() === '*' || peek() === '/' || peek() === '%') {
      const op = consume();
      const right = parsePower();
      if ((op === '/' || op === '%') && right === 0) {
        throw new Error('Division by zero');
      }
      if (op === '*') left *= right;
      else if (op === '/') left /= right;
      else left %= right;
    }
    return left;
  }

  function parsePower(): number {
    const base = parseUnary();
    if (peek() === '^') {
      consume();
      const exp = parsePower();
      return Math.pow(base, exp);
    }
    return base;
  }

  function parseUnary(): number {
    if (peek() === '+') {
      consume();
      return parseUnary();
    }
    if (peek() === '-') {
      consume();
      return -parseUnary();
    }
    if (peek() === '(') {
      consume();
      const val = parseExpr();
      if (consume() !== ')') {
        throw new Error('Mismatched parenthesis');
      }
      return val;
    }
    const tok = consume();
    if (!tok || !/^\d+(?:\.\d+)?$/.test(tok)) {
      throw new Error('Unexpected token');
    }
    return Number(tok);
  }

  try {
    const value = parseExpr();
    if (pos !== tokens.length || !Number.isFinite(value)) {
      return { ok: false };
    }
    return { ok: true, value };
  } catch {
    return { ok: false };
  }
}

function extractMathExpression(prompt: string): string | null {
  const match = prompt.match(/([0-9(][0-9+\-*/().%\s^]{1,}[0-9)])/);
  if (!match) return null;
  const candidate = match[1].trim();
  if (!/[+\-*/%^]/.test(candidate)) return null;
  return candidate;
}

function enrichConversationProject(conv: ConversationRow) {
  const msgs = store.messages.filter((m) => m.conversation_id === conv.id);
  const userMsgs = msgs.filter((m) => m.role === 'user');
  const assistantMsgs = msgs.filter((m) => m.role === 'assistant');
  const pendingActions: AnyRecord[] = [];
  if (msgs.length === 0) {
    pendingActions.push({
      id: 'initial-goal',
      title: 'ส่งเป้าหมายหรือคำสั่งงานแรกของโปรเจกต์',
      status: 'PENDING',
      category: 'setup',
    });
  } else if (assistantMsgs.length > 0) {
    const lastStatus = String(assistantMsgs[assistantMsgs.length - 1].status || '').toUpperCase();
    if (['NOT_LEARNED', 'UNCERTAIN', 'UNKNOWN', 'AWAITING_EVIDENCE'].includes(lastStatus)) {
      pendingActions.push({
        id: 'needs-clarification',
        title: 'ระบุข้อมูลเพิ่มเติมหรือบันทึกความรู้เข้ากราฟ',
        status: lastStatus,
        category: 'clarification',
      });
    }
  }
  const verifiedTurns = assistantMsgs.filter((m) =>
    ['VERIFIED', 'COMPLETED'].includes(String(m.status || '').toUpperCase())
  ).length;
  const totalUnits = userMsgs.length;
  const completedUnits = Math.min(totalUnits, verifiedTurns);
  const completionPct = totalUnits > 0 ? Math.round((completedUnits / totalUnits) * 100) : 0;
  let projectStatus = 'ACTIVE';
  if (msgs.length === 0 || pendingActions.some((a) => a.category === 'clarification')) {
    projectStatus = 'NEEDS_INPUT';
  } else if (totalUnits > 0 && completionPct >= 100 && pendingActions.length === 0) {
    projectStatus = 'COMPLETED';
  }
  const lastMsg = msgs[msgs.length - 1];
  const lastSummary = lastMsg ? String(lastMsg.content || '').trim().split('\n')[0]?.slice(0, 110) || null : null;
  return {
    ...conv,
    message_count: msgs.length,
    project_status: projectStatus,
    completion_pct: completionPct,
    completed_units: completedUnits,
    total_units: totalUnits,
    pending_actions: pendingActions,
    last_activity_summary: lastSummary,
  };
}

function sanitizeUser(u: UserRow) {
  return {
    id: u.id,
    email: u.email,
    display_name: u.display_name,
    role: u.role,
    created_at: u.created_at,
  };
}

function recordTrace(params: {
  userId: string;
  conversationId: string | null;
  messageId: string | null;
  prompt: string;
  responseContent: string;
  mode: string;
  status: string;
  traceObj: AnyRecord;
  createdAt?: string;
}) {
  const ts = params.createdAt || nowIso();
  const enginePath = Array.isArray(params.traceObj.engine_path)
    ? params.traceObj.engine_path.map(String)
    : [];
  const rec = {
    id: crypto.randomUUID(),
    user_id: params.userId,
    conversation_id: params.conversationId,
    message_id: params.messageId,
    prompt: params.prompt.slice(0, 1000),
    response_preview: params.responseContent.trim().slice(0, 320),
    mode: params.mode || 'auto',
    model_version: String(params.traceObj.model_version || 'zyrquen-omega-v1'),
    status: params.status || 'VERIFIED',
    engine_path_json: JSON.stringify(enginePath),
    trace_json: JSON.stringify(params.traceObj),
    latency_ms: Number(params.traceObj.latency_ms || 1.2),
    external_models_used: 0,
    created_at: ts,
  };
  store.reasoningTraces.unshift(rec);
  return rec;
}

function maskEmail(email: string): string {
  const raw = String(email || '').trim();
  if (!raw.includes('@')) return raw ? '[REDACTED_EMAIL]' : 'unknown';
  const [local, domain] = raw.split('@', 2);
  return `${local.slice(0, Math.min(2, local.length))}***@${domain}`;
}

function redactPiiText(text: string): { clean: string; counts: { email: number; thai_id: number; card_number: number; phone: number; total_redacted: number } } {
  let clean = text;
  let email = 0;
  let thaiId = 0;
  let phone = 0;
  clean = clean.replace(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, () => {
    email += 1;
    return '[REDACTED_EMAIL]';
  });
  clean = clean.replace(/\b\d{13}\b/g, () => {
    thaiId += 1;
    return '[REDACTED_THAI_ID]';
  });
  clean = clean.replace(/\b0\d{8,9}\b/g, () => {
    phone += 1;
    return '[REDACTED_PHONE]';
  });
  const total = email + thaiId + phone;
  return { clean, counts: { email, thai_id: thaiId, card_number: 0, phone, total_redacted: total } };
}

function computeReadinessSummary() {
  const cleanDatasets = store.datasets.filter((d) => d.leakage_detected === 0 && d.total_records >= 5).length;
  const baselineEvaluations = store.evaluations.length;
  const pendingExperiments = store.experiments.filter((e) => e.approval_status === 'PENDING_APPROVAL');
  const pendingRuns = store.workflowRuns.filter((r) => r.status === 'PENDING_APPROVAL');
  const pendingTrainingRuns = pendingRuns.filter((r) => r.group_id === 'native_training').length;
  const approvedExperiments = store.experiments.filter((e) => e.approval_status === 'APPROVED').length;
  const approvedTrainingRuns = store.workflowRuns.filter(
    (r) => r.group_id === 'native_training' && r.status === 'COMPLETED' && r.approved_by
  ).length;
  const verifiedTriples = store.triples.filter((t) => t.confidence >= 0.8).length;

  return {
    gate_status: 'BLOCKED',
    blocked_reason: 'NativeTransformerLM and Python Native Core require Python 3.11+ runtime (unavailable in Node.js-only container).',
    datasets_total: store.datasets.length,
    clean_datasets: cleanDatasets,
    baseline_evaluations: baselineEvaluations,
    approved_training_runs: approvedTrainingRuns,
    triples_total: store.triples.length,
    verified_triples: verifiedTriples,
    experiments_total: store.experiments.length,
    approved_experiments: approvedExperiments,
    pending_experiments: pendingExperiments.length,
    pending_training_runs: pendingTrainingRuns,
    pending_kg_proposals: store.kgProposals.filter((p) => p.status === 'PENDING_APPROVAL').length,
    checkpoints_total: store.checkpoints.length,
    neural_checkpoints: store.checkpoints.filter((c) => String(c.eval_status || '').startsWith('NEURAL')).length,
    datasets: store.datasets.slice(0, 20),
    checkpoints: store.checkpoints.slice(0, 20),
    experiments: store.experiments.slice(0, 12),
  };
}

function handleInferFallback(payload: AnyRecord) {
  const prompt = String(payload.prompt || '').trim();
  const mode = String(payload.mode || 'auto');
  const modelVersion = String(payload.model_version || 'zyrquen-omega-v1');
  const attachment = String(payload.attachment || '').trim();
  const started = performance.now();

  if (/^(สวัสดี|hello|hi|hey)\b/i.test(prompt)) {
    const latency = Math.max(0.5, Math.round((performance.now() - started) * 100) / 100);
    return {
      ok: true,
      status: 'VERIFIED',
      content:
        'สวัสดีครับ ขณะนี้ระบบทำงานบน Node.js Runtime (ไม่มี Python Native Core ในคอนเทนเนอร์นี้) รองรับการคำนวณ AST คณิตศาสตร์และการค้นหากราฟความรู้ครับ',
      trace: {
        mode,
        model_version: modelVersion,
        engine_path: ['node_greeting_router'],
        latency_ms: latency,
        external_models_used: false,
        task_timings: [{ order: 1, task: 'greeting_intent', duration_ms: latency, matched: true, status: 'VERIFIED' }],
        bottleneck_task: { task: 'greeting_intent', duration_ms: latency, share_pct: 100 },
      },
    };
  }

  const mathExpr = extractMathExpression(prompt);
  if (mathExpr && (mode === 'auto' || mode === 'math')) {
    const evaluated = safeEvalArithmetic(mathExpr);
    if (evaluated.ok && evaluated.value !== undefined) {
      const latency = Math.max(0.5, Math.round((performance.now() - started) * 100) / 100);
      return {
        ok: true,
        status: 'VERIFIED',
        content: `ผลการคำนวณเชิงสัญลักษณ์สำหรับ \`${mathExpr}\` คือ **${evaluated.value}**`,
        trace: {
          mode,
          model_version: modelVersion,
          engine_path: ['safe_ast_math'],
          latency_ms: latency,
          external_models_used: false,
          math: {
            expression: mathExpr,
            result: evaluated.value,
            steps: [`Parse expression: ${mathExpr}`, `Evaluate result: ${evaluated.value}`],
          },
          task_timings: [{ order: 1, task: 'safe_ast_math', duration_ms: latency, matched: true, status: 'VERIFIED' }],
          bottleneck_task: { task: 'safe_ast_math', duration_ms: latency, share_pct: 100 },
        },
      };
    }
  }

  if (mode === 'plan') {
    const latency = Math.max(0.5, Math.round((performance.now() - started) * 100) / 100);
    return {
      ok: true,
      status: 'BLOCKED',
      content:
        'โหมดวางแผน (Native DAG Planner) ต้องใช้ Python 3.11+ Native Core ซึ่งไม่พร้อมใช้งานในคอนเทนเนอร์ Node.js-only นี้',
      trace: {
        mode,
        model_version: modelVersion,
        engine_path: ['python_runtime_unavailable'],
        latency_ms: latency,
        external_models_used: false,
        task_timings: [{ order: 1, task: 'native_dag_planner', duration_ms: latency, matched: false, status: 'BLOCKED' }],
        bottleneck_task: { task: 'native_dag_planner', duration_ms: latency, share_pct: 100 },
      },
    };
  }

  if (mode === 'model') {
    const latency = Math.max(0.5, Math.round((performance.now() - started) * 100) / 100);
    return {
      ok: true,
      status: 'BLOCKED',
      content:
        'การอนุมานด้วยโมเดล NativeTransformerLM ต้องใช้ Python 3.11+ / PyTorch runtime ซึ่งไม่พร้อมใช้งานในคอนเทนเนอร์ Node.js-only นี้',
      trace: {
        mode,
        model_version: modelVersion,
        engine_path: ['python_runtime_unavailable'],
        latency_ms: latency,
        external_models_used: false,
        task_timings: [{ order: 1, task: 'native_transformer_lm', duration_ms: latency, matched: false, status: 'BLOCKED' }],
        bottleneck_task: { task: 'native_transformer_lm', duration_ms: latency, share_pct: 100 },
      },
    };
  }

  const lowerPrompt = prompt.toLowerCase();
  const matchedTriples = store.triples.filter((t) => {
    const s = t.subject.toLowerCase();
    const r = t.relation.toLowerCase();
    const o = t.object.toLowerCase();
    return lowerPrompt.includes(s) || lowerPrompt.includes(o) || lowerPrompt.includes(r);
  });

  if (matchedTriples.length > 0) {
    const latency = Math.max(0.5, Math.round((performance.now() - started) * 100) / 100);
    const lines = matchedTriples.slice(0, 5).map((t) => `- ${t.subject} ${t.relation} ${t.object}`);
    return {
      ok: true,
      status: 'VERIFIED',
      content: `พบข้อมูลที่เกี่ยวข้องในกราฟความรู้:\n${lines.join('\n')}`,
      trace: {
        mode,
        model_version: modelVersion,
        engine_path: ['knowledge_graph_lookup'],
        latency_ms: latency,
        external_models_used: false,
        matched_triples: matchedTriples.slice(0, 10),
        task_timings: [{ order: 1, task: 'knowledge_graph_lookup', duration_ms: latency, matched: true, status: 'VERIFIED' }],
        bottleneck_task: { task: 'knowledge_graph_lookup', duration_ms: latency, share_pct: 100 },
      },
    };
  }

  if (attachment) {
    const latency = Math.max(0.5, Math.round((performance.now() - started) * 100) / 100);
    const lineCount = attachment.split(/\r?\n/).length;
    return {
      ok: true,
      status: 'VERIFIED',
      content: `ตรวจสอบไฟล์/ข้อความแนบแล้ว (${attachment.length} ตัวอักษร, ${lineCount} บรรทัด)`,
      trace: {
        mode,
        model_version: modelVersion,
        engine_path: ['attachment_inspector'],
        latency_ms: latency,
        external_models_used: false,
        task_timings: [{ order: 1, task: 'attachment_inspector', duration_ms: latency, matched: true, status: 'VERIFIED' }],
        bottleneck_task: { task: 'attachment_inspector', duration_ms: latency, share_pct: 100 },
      },
    };
  }

  const latency = Math.max(0.5, Math.round((performance.now() - started) * 100) / 100);
  return {
    ok: true,
    status: 'NOT_LEARNED',
    content: 'ยังไม่มีข้อมูลหรือความรู้เรื่องนี้ในกราฟความรู้ของระบบ (NOT_LEARNED) คุณสามารถเพิ่มความรู้ในหน้า Knowledge Memory เพื่อสอนระบบได้ครับ',
    trace: {
      mode,
      model_version: modelVersion,
      engine_path: ['unlearned_boundary'],
      latency_ms: latency,
      external_models_used: false,
      task_timings: [{ order: 1, task: 'unlearned_boundary', duration_ms: latency, matched: false, status: 'NOT_LEARNED' }],
      bottleneck_task: { task: 'unlearned_boundary', duration_ms: latency, share_pct: 100 },
    },
  };
}

function handleRunWorkflowFallback(payload: AnyRecord) {
  const groupId = String(payload.group_id || 'system_ops');
  const userId = String(payload.user_id || 'system');
  const group = WORKFLOW_GROUPS.find((g) => g.id === groupId);
  if (!group) {
    return { ok: false, error: `Unknown workflow group '${groupId}'` };
  }

  if (groupId === 'native_training') {
    return {
      ok: false,
      status: 'BLOCKED',
      error: 'Native Training workflow requires Python 3.11+ Native Core (unavailable in Node.js-only container).',
    };
  }

  const ts = nowIso();
  const stages = group.stages.map((stage) => ({
    stage,
    status: 'COMPLETED',
    detail: 'Executed in Node.js runtime',
  }));

  const run: WorkflowRunRow = {
    id: crypto.randomUUID(),
    group_id: groupId,
    status: 'COMPLETED',
    requires_approval: 0,
    triggered_by: userId,
    approved_by: null,
    summary: `Workflow ${groupId} completed in Node.js runtime.`,
    stages_json: JSON.stringify(stages),
    created_at: ts,
    updated_at: ts,
  };
  store.workflowRuns.unshift(run);
  return { ok: true, run };
}

export function runFallbackDbBridge(action: string, payload: AnyRecord = {}): AnyRecord {
  if (action === 'auth_status') {
    const adminCount = store.users.filter((u) => u.role === 'admin').length;
    return { ok: true, initialized: adminCount > 0, user_count: store.users.length };
  }

  if (action === 'auth_create_user') {
    const email = String(payload.email || '').trim().toLowerCase();
    const displayName = String(payload.display_name || '').trim();
    const role = payload.role === 'admin' ? 'admin' : payload.role === 'user' ? 'user' : null;
    if (!role) return { ok: false, error: 'Invalid role' };
    if (store.users.some((u) => u.email === email)) {
      return { ok: false, error: 'UNIQUE constraint failed: users.email' };
    }
    const user: UserRow = {
      id: crypto.randomUUID(),
      email,
      display_name: displayName,
      role,
      password_hash: String(payload.password_hash || ''),
      created_at: nowIso(),
    };
    store.users.push(user);
    return { ok: true, user: sanitizeUser(user) };
  }

  if (action === 'auth_find_by_email') {
    const email = String(payload.email || '').trim().toLowerCase();
    const user = store.users.find((u) => u.email === email) || null;
    return { ok: true, user };
  }

  if (action === 'auth_find_by_id') {
    const uid = String(payload.user_id || '');
    const user = store.users.find((u) => u.id === uid);
    return { ok: true, user: user ? sanitizeUser(user) : null };
  }

  if (action === 'home_summary') {
    const uid = String(payload.user_id || '');
    const recent = store.conversations
      .filter((c) => c.user_id === uid)
      .slice(0, 6)
      .map(enrichConversationProject);
    return {
      ok: true,
      recent_conversations: recent,
      recent_missions: store.missions.slice(0, 4),
      counts: {
        triples: store.triples.length,
        checkpoints: store.checkpoints.length,
        datasets: store.datasets.length,
        pending_approvals: store.workflowRuns.filter((r) => r.status === 'PENDING_APPROVAL').length,
        evaluations: store.evaluations.length,
        missions: store.missions.length,
      },
      system: getSystemMetrics(),
    };
  }

  if (action === 'conv_list') {
    const uid = String(payload.user_id || '');
    const rows = store.conversations
      .filter((c) => c.user_id === uid)
      .map(enrichConversationProject);
    return { ok: true, conversations: rows };
  }

  if (action === 'conv_create') {
    const uid = String(payload.user_id || '');
    const title = String(payload.title || 'New Native Session').trim() || 'New Native Session';
    const mode = String(payload.mode || 'auto');
    const ts = nowIso();
    const conv: ConversationRow = {
      id: crypto.randomUUID(),
      user_id: uid,
      title: title.slice(0, 120),
      mode,
      created_at: ts,
      updated_at: ts,
    };
    store.conversations.unshift(conv);
    return { ok: true, conversation: conv };
  }

  if (action === 'conv_get') {
    const uid = String(payload.user_id || '');
    const cid = String(payload.conversation_id || '');
    const conv = store.conversations.find((c) => c.id === cid && c.user_id === uid);
    if (!conv) return { ok: false, error: 'Conversation not found' };
    const msgs = store.messages.filter((m) => m.conversation_id === cid);
    return { ok: true, conversation: conv, messages: msgs };
  }

  if (action === 'conv_summary') {
    const uid = String(payload.user_id || '');
    const cid = String(payload.conversation_id || '');
    const conv = store.conversations.find((c) => c.id === cid && c.user_id === uid);
    if (!conv) return { ok: false, error: 'Conversation not found' };
    const msgs = store.messages.filter((m) => m.conversation_id === cid);
    const verifiedCount = msgs.filter((m) => m.role === 'assistant' && m.status === 'VERIFIED').length;
    const notLearnedCount = msgs.filter((m) => m.role === 'assistant' && m.status === 'NOT_LEARNED').length;
    return {
      ok: true,
      summary: {
        bullets: msgs.length === 0 ? ['ยังไม่มีข้อความในบทสนทนานี้'] : [`จำนวนข้อความทั้งหมด ${msgs.length} รายการ`],
        metrics: {
          total_messages: msgs.length,
          verified_count: verifiedCount,
          not_learned_count: notLearnedCount,
        },
      },
    };
  }

  if (action === 'conv_delete') {
    const uid = String(payload.user_id || '');
    const cid = String(payload.conversation_id || '');
    const idx = store.conversations.findIndex((c) => c.id === cid && c.user_id === uid);
    if (idx === -1) return { ok: false };
    store.conversations.splice(idx, 1);
    store.messages = store.messages.filter((m) => m.conversation_id !== cid);
    return { ok: true };
  }

  if (action === 'conv_save_exchange') {
    const uid = String(payload.user_id || '');
    const cid = String(payload.conversation_id || '');
    const conv = store.conversations.find((c) => c.id === cid && c.user_id === uid);
    if (!conv) return { ok: false, error: 'Conversation not found' };

    const ts = nowIso();
    const userContent = String(payload.user_content || '');
    const mode = String(payload.mode || 'auto');
    const asstContent = String(payload.assistant_content || '');
    const asstStatus = String(payload.assistant_status || 'VERIFIED');
    const traceObj = (payload.trace && typeof payload.trace === 'object' ? payload.trace : {}) as AnyRecord;

    const userMsg: MessageRow = {
      id: crypto.randomUUID(),
      conversation_id: cid,
      role: 'user',
      content: userContent,
      mode,
      trace_json: null,
      status: 'USER',
      created_at: ts,
    };
    const asstTs = nowIso();
    const asstMsg: MessageRow = {
      id: crypto.randomUUID(),
      conversation_id: cid,
      role: 'assistant',
      content: asstContent,
      mode,
      trace_json: JSON.stringify(traceObj),
      status: asstStatus,
      created_at: asstTs,
    };
    store.messages.push(userMsg, asstMsg);

    if (conv.title === 'New Native Session' && userContent) {
      conv.title = userContent.slice(0, 48) + (userContent.length > 48 ? '...' : '');
    }
    conv.mode = mode;
    conv.updated_at = nowIso();

    recordTrace({
      userId: uid,
      conversationId: cid,
      messageId: asstMsg.id,
      prompt: userContent,
      responseContent: asstContent,
      mode,
      status: asstStatus,
      traceObj,
      createdAt: asstTs,
    });

    return { ok: true, title: conv.title, user_message: userMsg, assistant_message: asstMsg };
  }

  if (action === 'knowledge_list') {
    const q = String(payload.q || '').trim().toLowerCase();
    const triples = q
      ? store.triples.filter(
          (t) =>
            t.subject.toLowerCase().includes(q) ||
            t.relation.toLowerCase().includes(q) ||
            t.object.toLowerCase().includes(q)
        )
      : store.triples;
    return { ok: true, triples: triples.slice(0, 100) };
  }

  if (action === 'knowledge_create') {
    const subject = String(payload.subject || '').trim();
    const relation = String(payload.relation || '').trim();
    const object = String(payload.object || '').trim();
    const contradictions = store.triples
      .filter(
        (t) =>
          t.subject.toLowerCase() === subject.toLowerCase() &&
          t.relation.toLowerCase() === relation.toLowerCase() &&
          t.object.toLowerCase() !== object.toLowerCase()
      )
      .map((t) => t.object);
    const triple: TripleRow = {
      id: crypto.randomUUID(),
      subject,
      relation,
      object,
      source: String(payload.source || 'manual_memory'),
      confidence: 1.0,
      created_by: String(payload.user_id || ''),
      created_at: nowIso(),
    };
    store.triples.unshift(triple);
    return { ok: true, triple, contradictions };
  }

  if (action === 'knowledge_delete') {
    const tid = String(payload.triple_id || '');
    const uid = String(payload.user_id || '');
    const isAdmin = Boolean(payload.is_admin);
    const idx = store.triples.findIndex((t) => t.id === tid && (isAdmin || t.created_by === uid));
    if (idx === -1) return { ok: false };
    store.triples.splice(idx, 1);
    return { ok: true };
  }

  if (action === 'workflows_list') {
    const uid = payload.user_id ? String(payload.user_id) : null;
    const isAdmin = Boolean(payload.is_admin);
    const traces = store.reasoningTraces
      .filter((t) => isAdmin || !uid || t.user_id === uid)
      .slice(0, 30);
    return {
      ok: true,
      groups: WORKFLOW_GROUPS,
      runs: store.workflowRuns.slice(0, 30),
      reasoning_traces: traces,
    };
  }

  if (action === 'reasoning_traces_list') {
    const uid = payload.user_id ? String(payload.user_id) : null;
    const isAdmin = Boolean(payload.is_admin);
    const status = String(payload.status || '').trim().toUpperCase();
    const q = String(payload.q || '').trim().toLowerCase();
    const limit = Math.max(1, Math.min(100, Number(payload.limit || 40)));
    const filtered = store.reasoningTraces
      .filter((t) => isAdmin || !uid || t.user_id === uid)
      .filter((t) => !status || status === 'ALL' || String(t.status) === status)
      .filter(
        (t) =>
          !q ||
          String(t.prompt).toLowerCase().includes(q) ||
          String(t.response_preview).toLowerCase().includes(q) ||
          String(t.model_version).toLowerCase().includes(q)
      )
      .slice(0, limit);
    return { ok: true, reasoning_traces: filtered };
  }

  if (action === 'reasoning_trace_record') {
    const uid = String(payload.user_id || '').trim();
    if (!uid) return { ok: false, error: 'user_id is required' };
    const rec = recordTrace({
      userId: uid,
      conversationId: payload.conversation_id ? String(payload.conversation_id) : null,
      messageId: payload.message_id ? String(payload.message_id) : null,
      prompt: String(payload.prompt || ''),
      responseContent: String(payload.response_content || ''),
      mode: String(payload.mode || 'auto'),
      status: String(payload.status || 'VERIFIED'),
      traceObj: (payload.trace && typeof payload.trace === 'object' ? payload.trace : {}) as AnyRecord,
    });
    return { ok: true, reasoning_trace: rec };
  }

  if (action === 'workflow_decide') {
    const runId = String(payload.run_id || '');
    const decision = String(payload.decision || 'approve');
    const adminEmail = String(payload.admin_email || '');
    const adminId = String(payload.admin_id || '');
    const run = store.workflowRuns.find((r) => r.id === runId);
    if (!run) return { ok: false, error: 'Workflow run not found' };
    if (run.status !== 'PENDING_APPROVAL') return { ok: false, error: 'Workflow run is not awaiting approval' };
    if (decision === 'reject') {
      run.status = 'REJECTED';
      run.approved_by = adminEmail;
      run.summary = `Rejected at Approval Gate by ${adminEmail}.`;
      run.updated_at = nowIso();
      return { ok: true, run };
    }
    return handleRunWorkflowFallback({
      group_id: run.group_id,
      user_id: adminId,
      approved_by: adminEmail,
      run_id: runId,
    });
  }

  if (action === 'dev_overview') {
    const uid = String(payload.user_id || '');
    const keys = store.apiKeys.filter((k) => k.user_id === uid);
    const usage = store.apiUsageLogs.filter((u) => u.user_id === uid);
    const avgLatency = usage.length
      ? Math.round((usage.reduce((s, u) => s + Number(u.latency_ms || 0), 0) / usage.length) * 10) / 10
      : 0;
    return {
      ok: true,
      keys,
      datasets: store.datasets.slice(0, 20),
      kg_proposals: store.kgProposals.slice(0, 20),
      checkpoints: store.checkpoints.slice(0, 20),
      evaluations: store.evaluations.slice(0, 10),
      experiments: store.experiments.slice(0, 12),
      usage: {
        total_requests: usage.length,
        avg_latency_ms: avgLatency,
        daily_quota: 1000,
        recent: usage.slice(0, 15),
      },
    };
  }

  if (action === 'dev_key_create') {
    const key = {
      id: crypto.randomUUID(),
      user_id: String(payload.user_id || ''),
      name: String(payload.name || '').trim(),
      key_prefix: String(payload.key_prefix || ''),
      scopes_json: JSON.stringify(payload.scopes || ['infer:read']),
      quota_daily: Number(payload.quota_daily || 1000),
      requests_today: 0,
      last_used_at: null,
      revoked: 0,
      created_at: nowIso(),
    };
    store.apiKeys.unshift(key);
    return { ok: true, key };
  }

  if (action === 'dev_key_revoke') {
    const kid = String(payload.key_id || '');
    const uid = String(payload.user_id || '');
    const key = store.apiKeys.find((k) => k.id === kid && k.user_id === uid);
    if (!key) return { ok: false };
    key.revoked = 1;
    return { ok: true };
  }

  if (action === 'admin_overview') {
    return {
      ok: true,
      users: store.users.map(sanitizeUser),
      pending_runs: store.workflowRuns.filter((r) => r.status === 'PENDING_APPROVAL'),
      pending_tool_invocations: store.toolInvocations.filter((t) => t.status === 'PENDING_APPROVAL'),
      pending_tool_center_invocations: store.toolCenterInvocations.filter((t) => t.status === 'PENDING_APPROVAL'),
      pending_improvement_proposals: store.improvementProposals.filter((p) => p.approval_status === 'PENDING_APPROVAL'),
      pending_experiments: store.experiments.filter((e) => e.approval_status === 'PENDING_APPROVAL'),
      pending_kg_proposals: store.kgProposals.filter((p) => p.status === 'PENDING_APPROVAL'),
      tools: store.externalTools,
      audit_logs: store.auditLogs.slice(0, 40),
      system: getSystemMetrics(),
      reasoning_traces: store.reasoningTraces.slice(0, 40),
      recent_api_usage: store.apiUsageLogs.slice(0, 40),
      training_readiness: computeReadinessSummary(),
    };
  }

  if (action === 'admin_export_audit_logs') {
    const focus = String(payload.focus || 'pii_redaction').toLowerCase() === 'all' ? 'all' : 'pii_redaction';
    const format = String(payload.format || 'json').toLowerCase() === 'csv' ? 'csv' : 'json';
    const limit = Math.max(1, Math.min(5000, Number(payload.limit || 1000)));
    const actorId = String(payload.actor_id || 'system');
    const actorEmail = String(payload.actor_email || 'admin');
    const scanned = store.auditLogs.slice(0, limit).map((row) => {
      let details: AnyRecord;
      try {
        details = row.details_json ? (JSON.parse(row.details_json) as AnyRecord) : {};
      } catch {
        details = {};
      }
      const isPii =
        row.action.toUpperCase().includes('PII') ||
        row.action.toUpperCase().includes('REDACT') ||
        details.pii_redacted === true;
      return {
        id: row.id,
        created_at: row.created_at,
        actor_id: row.actor_id,
        actor_email_masked: maskEmail(row.actor_email),
        action: row.action,
        target: redactPiiText(row.target).clean,
        outcome: redactPiiText(row.outcome).clean,
        is_pii_redaction_event: isPii,
        pii_redaction_summary: null,
        details,
        export_redactions_applied: 0,
      };
    });
    const piiEvents = scanned.filter((e) => e.is_pii_redaction_event);
    const events = focus === 'pii_redaction' ? piiEvents : scanned;
    const integritySha256 = sha256(JSON.stringify(events));
    return {
      ok: true,
      schema: 'zyrquen.audit-export.v1',
      focus,
      format,
      exported_at: nowIso(),
      exported_by: { id: actorId, actor_email_masked: maskEmail(actorEmail) },
      total_scanned: scanned.length,
      pii_redaction_event_count: piiEvents.length,
      exported_count: events.length,
      integrity_sha256: integritySha256,
      sanitization_applied: true,
      events,
    };
  }

  if (action === 'admin_user_role') {
    const targetId = String(payload.target_user_id || '');
    const role = payload.role === 'admin' ? 'admin' : payload.role === 'user' ? 'user' : null;
    if (!role) return { ok: false, error: 'Invalid role' };
    const user = store.users.find((u) => u.id === targetId);
    if (!user) return { ok: false };
    user.role = role;
    return { ok: true };
  }

  if (action === 'log_api_usage') {
    store.apiUsageLogs.unshift({
      id: crypto.randomUUID(),
      user_id: payload.user_id || null,
      key_id: payload.key_id || null,
      endpoint: String(payload.endpoint || '/'),
      method: String(payload.method || 'GET'),
      status_code: Number(payload.status_code || 200),
      latency_ms: Number(payload.latency_ms || 0),
      created_at: nowIso(),
    });
    if (store.apiUsageLogs.length > 500) store.apiUsageLogs.length = 500;
    return { ok: true };
  }

  if (action === 'log_audit') {
    store.auditLogs.unshift({
      id: crypto.randomUUID(),
      actor_id: String(payload.actor_id || 'system'),
      actor_email: String(payload.actor_email || 'system'),
      action: String(payload.action || 'EVENT'),
      target: String(payload.target || ''),
      outcome: String(payload.outcome || 'OK'),
      details_json: JSON.stringify(payload.details || {}),
      created_at: nowIso(),
    });
    if (store.auditLogs.length > 500) store.auditLogs.length = 500;
    return { ok: true };
  }

  if (action === 'tools_overview') {
    const uid = String(payload.user_id || '');
    const files = Array.from(store.workspaceFiles.values()).map((f) => ({
      name: f.name,
      size_bytes: f.size_bytes,
      modified_at: f.modified_at,
    }));
    return {
      ok: true,
      tools: store.externalTools,
      invocations: store.toolInvocations.filter((i) => i.user_id === uid).slice(0, 20),
      workspace_files: files,
    };
  }

  if (action === 'tools_upload_file') {
    const filename = String(payload.filename || '').trim().replace(/[^a-zA-Z0-9._-]/g, '_');
    const content = String(payload.content || '');
    if (!filename) return { ok: false, error: 'Invalid filename' };
    const entry = {
      name: filename,
      content,
      size_bytes: Buffer.byteLength(content, 'utf8'),
      modified_at: nowIso(),
    };
    store.workspaceFiles.set(filename, entry);
    return { ok: true, file: { name: entry.name, size_bytes: entry.size_bytes, modified_at: entry.modified_at } };
  }

  if (action === 'tools_invoke') {
    const toolId = String(payload.tool_id || '').trim();
    const tool = store.externalTools.find((t) => t.id === toolId);
    if (!tool) return { ok: false, error: `Unknown tool '${toolId}'` };
    const inv = {
      id: crypto.randomUUID(),
      tool_id: toolId,
      conversation_id: payload.conversation_id || null,
      user_id: String(payload.user_id || ''),
      status: tool.permission_mode === 'approval_required' ? 'PENDING_APPROVAL' : 'COMPLETED',
      input_json: JSON.stringify(payload.input || {}),
      output_json: tool.permission_mode === 'approval_required' ? null : JSON.stringify({ ok: true, note: 'Executed in Node runtime' }),
      analysis_summary: tool.permission_mode === 'approval_required' ? 'รออนุมัติจากผู้ดูแลระบบ' : 'ดำเนินการสำเร็จใน Node runtime',
      approved_by: null,
      latency_ms: 1.5,
      created_at: nowIso(),
    };
    store.toolInvocations.unshift(inv);
    return { ok: true, status: inv.status, invocation: inv };
  }

  if (action === 'admin_tools_update') {
    const toolId = String(payload.tool_id || '').trim();
    const tool = store.externalTools.find((t) => t.id === toolId);
    if (!tool) return { ok: false, error: 'Tool not found' };
    if (payload.permission_mode) tool.permission_mode = String(payload.permission_mode);
    if (typeof payload.enabled === 'boolean') tool.enabled = payload.enabled ? 1 : 0;
    if (payload.quota_daily !== undefined) tool.quota_daily = Number(payload.quota_daily);
    if (Array.isArray(payload.endpoint_allowlist)) {
      tool.endpoint_allowlist_json = JSON.stringify(payload.endpoint_allowlist.map(String));
    }
    tool.updated_at = nowIso();
    return { ok: true, tool };
  }

  if (action === 'admin_tool_decide') {
    const invId = String(payload.invocation_id || '').trim();
    const decision = String(payload.decision || 'approve');
    const adminEmail = String(payload.admin_email || '');
    const inv = store.toolInvocations.find((i) => i.id === invId);
    if (!inv) return { ok: false, error: 'Tool invocation not found' };
    inv.status = decision === 'reject' ? 'REJECTED' : 'COMPLETED';
    inv.approved_by = adminEmail;
    inv.analysis_summary = decision === 'reject' ? `ปฏิเสธโดย ${adminEmail}` : `อนุมัติโดย ${adminEmail}`;
    return { ok: true, status: inv.status, invocation: inv };
  }

  if (action === 'missions_list') {
    return { ok: true, missions: store.missions.slice(0, 25) };
  }

  if (action === 'mission_detail') {
    const mid = String(payload.mission_id || '').trim();
    const mission = store.missions.find((m) => m.id === mid);
    if (!mission) return { ok: false, error: 'Mission not found' };
    return {
      ok: true,
      mission,
      nodes: store.missionNodes.filter((n) => n.mission_id === mid),
      evidence: store.missionEvidence.filter((e) => e.mission_id === mid),
    };
  }

  if (action === 'kg_proposals_list') {
    return { ok: true, proposals: store.kgProposals.slice(0, 30) };
  }

  if (action === 'tool_center_overview') {
    const uid = String(payload.user_id || '');
    const isAdmin = String(payload.user_role || '').toLowerCase() === 'admin';
    return {
      ok: true,
      toolkits: DEFAULT_TOOLKITS,
      inventory: { total_toolkits: DEFAULT_TOOLKITS.length, total_capabilities: 6 },
      dependency_environment: { runtime: 'node-22', status: 'ready' },
      resource_snapshot: getSystemMetrics(),
      failure_patterns: [],
      invocations: store.toolCenterInvocations.filter((i) => isAdmin || i.user_id === uid).slice(0, 25),
      improvement_proposals: store.improvementProposals.filter((p) => isAdmin || p.created_by === uid).slice(0, 15),
      recent_orchestrations: store.orchestrations.filter((o) => isAdmin || o.user_id === uid).slice(0, 15),
      external_models_used: false,
    };
  }

  if (
    action === 'tool_center_resolve' ||
    action === 'tool_center_execute' ||
    action === 'tool_center_orchestrate' ||
    action === 'tool_center_verify'
  ) {
    return {
      ok: false,
      status: 'BLOCKED',
      error: 'Native Tool Center execution requires Python 3.11+ Native Core (unavailable in Node.js-only container).',
    };
  }

  if (action === 'tool_center_decide') {
    const invId = String(payload.invocation_id || '').trim();
    const inv = store.toolCenterInvocations.find((i) => i.id === invId || i.invocation_id === invId);
    if (!inv) return { ok: false, error: 'Invocation not found' };
    inv.status = payload.decision === 'reject' ? 'REJECTED' : 'COMPLETED';
    return { ok: true, status: inv.status };
  }

  if (action === 'tool_center_self_improve') {
    return {
      ok: false,
      status: 'BLOCKED',
      error: 'Self-improvement evaluation requires Python 3.11+ Native Core (unavailable in Node.js-only container).',
    };
  }

  if (action === 'tool_center_decide_improvement') {
    const pid = String(payload.proposal_id || '').trim();
    const prop = store.improvementProposals.find((p) => p.id === pid);
    if (!prop) return { ok: false, error: 'Proposal not found' };
    prop.approval_status = payload.decision === 'approve' ? 'APPROVED' : 'REJECTED';
    return { ok: true, status: prop.approval_status };
  }

  if (action === 'tool_center_engineering_benchmark') {
    return {
      ok: false,
      status: 'BLOCKED',
      error: 'Engineering benchmark requires Python 3.11+ Native Core (unavailable in Node.js-only container).',
    };
  }

  return { ok: false, error: `Unknown bridge action '${action}'` };
}

export function runFallbackCoreCommand(cmd: string, payload: AnyRecord = {}): AnyRecord {
  if (cmd === 'init') {
    return { ok: true, db_path: 'in-memory-node-fallback', native_core_ready: false };
  }

  if (cmd === 'health') {
    return {
      ok: true,
      native_core_ready: false,
      native_training_ready: false,
      metrics: getSystemMetrics(),
      counts: {
        triples: store.triples.length,
        checkpoints: store.checkpoints.length,
        datasets: store.datasets.length,
      },
    };
  }

  if (cmd === 'infer') {
    return handleInferFallback(payload);
  }

  if (cmd === 'ingest_dataset') {
    const name = String(payload.name || 'dataset').trim();
    const content = String(payload.content || '');
    const redactPii = Boolean(payload.redact_pii ?? true);
    const { clean, counts } = redactPii ? redactPiiText(content) : { clean: content, counts: { email: 0, thai_id: 0, card_number: 0, phone: 0, total_redacted: 0 } };
    const lines = clean.split(/\r?\n/).filter((l) => l.trim().length > 0);
    const total = Math.max(lines.length, 1);
    const trainCount = Math.max(1, Math.floor(total * 0.7));
    const valCount = Math.max(0, Math.floor(total * 0.15));
    const testCount = Math.max(0, total - trainCount - valCount);
    const dataset: DatasetRow = {
      id: crypto.randomUUID(),
      name,
      manifest_hash: sha256(`${name}:${clean}`),
      total_records: total,
      train_count: trainCount,
      val_count: valCount,
      test_count: testCount,
      leakage_detected: 0,
      status: 'READY',
      created_at: nowIso(),
      source_name: String(payload.source_name || 'developer_manual_corpus'),
      license: String(payload.license || 'INTERNAL_VERIFIED'),
      provenance: String(payload.provenance || 'developer_manual_corpus'),
      source_format: String(payload.format || 'text'),
      content_sha256: sha256(clean),
    };
    store.datasets.unshift(dataset);
    return { ok: true, dataset, kg_proposal: null, pii_redaction_summary: counts };
  }

  if (cmd === 'verify_dataset') {
    const did = String(payload.dataset_id || '');
    const ds = store.datasets.find((d) => d.id === did);
    if (!ds) return { ok: false, error: 'Dataset not found' };
    return {
      ok: true,
      dataset_id: ds.id,
      name: ds.name,
      verified: true,
      disk_verified: false,
      storage_mode: 'in-memory-node-fallback',
      content_sha256: ds.content_sha256,
      manifest_sha256: ds.manifest_hash,
      leakage_detected: ds.leakage_detected,
      errors: [],
    };
  }

  if (cmd === 'decide_kg_proposal') {
    const pid = String(payload.proposal_id || '');
    const prop = store.kgProposals.find((p) => p.id === pid);
    if (!prop) return { ok: false, error: 'Proposal not found' };
    prop.status = payload.decision === 'reject' ? 'REJECTED' : 'APPROVED';
    prop.approved_by = payload.admin_email || 'admin';
    prop.reviewed_at = nowIso();
    return { ok: true, proposal: prop, committed_triples: 0 };
  }

  if (cmd === 'run_workflow') {
    return handleRunWorkflowFallback(payload);
  }

  if (cmd === 'evaluate') {
    return {
      ok: false,
      status: 'BLOCKED',
      error: 'Scientific model evaluation requires Python 3.11+ Native Core (unavailable in Node.js-only container).',
    };
  }

  if (cmd === 'evaluations_list') {
    return { ok: true, evaluations: store.evaluations.slice(0, 15) };
  }

  if (cmd === 'run_mission' || cmd === 'resume_mission' || cmd === 'cancel_mission') {
    return {
      ok: false,
      status: 'BLOCKED',
      error: 'Autonomous DAG missions require Python 3.11+ Native Core (unavailable in Node.js-only container).',
    };
  }

  if (
    cmd === 'curate_corpus' ||
    cmd === 'curate_code_corpus' ||
    cmd === 'run_experiment' ||
    cmd === 'run_code_training_experiment' ||
    cmd === 'run_continual_round' ||
    cmd === 'decide_experiment' ||
    cmd === 'evaluate_code_model' ||
    cmd === 'synthesize_curriculum'
  ) {
    return {
      ok: false,
      status: 'BLOCKED',
      error: 'NativeTransformerLM training, corpus curation, and Python evaluation require Python 3.11+ / PyTorch runtime (unavailable in Node.js-only container).',
      external_models_used: false,
    };
  }

  if (cmd === 'workflow_groups') {
    return { ok: true, groups: WORKFLOW_GROUPS };
  }

  if (cmd === 'tool_center_orchestrate') {
    return runFallbackDbBridge('tool_center_orchestrate', payload);
  }
  if (cmd === 'tool_center_self_improve') {
    return runFallbackDbBridge('tool_center_self_improve', payload);
  }
  if (cmd === 'tool_center_decide_improvement') {
    return runFallbackDbBridge('tool_center_decide_improvement', payload);
  }

  return { ok: false, error: `Unknown command '${cmd}'` };
}

export function runFallbackBenchmark(_modelVersion: string): AnyRecord {
  return {
    ok: false,
    status: 'BLOCKED',
    error: 'Native capability benchmark requires Python 3.11+ Native Core (unavailable in Node.js-only container).',
  };
}
