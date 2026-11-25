import type { NativeTrace } from '../types';

const INTERNAL_DIAGNOSTIC_KEYS = new Set([
  'cognitive_pipeline',
  'inference_gap',
  'epistemic_state',
  'cognitive_state',
  'model_weights_changed',
  'pipeline_trace',
  'task_timings',
  'bottleneck_task',
  'engine_path',
  'attempted_inferences',
  'external_models_used',
]);

const SENSITIVE_METADATA_KEYS = new Set([
  'token',
  'access_token',
  'refresh_token',
  'id_token',
  'password',
  'password_hash',
  'secret',
  'secret_hash',
  'plaintextKey',
  'api_key',
  'apiKey',
  'authorization',
  'cookie',
  'set-cookie',
  'private_key',
  'session_id',
  'internal_reasoning',
  'hidden_metadata',
]);

const INTERNAL_LINE_PREFIX_RE =
  /^\s*(?:cognitive_pipeline|inference_gap|epistemic_state|model_weights_changed|pipeline_trace|internal_diagnostics|retrieval_diagnostics|internal_reasoning|hidden_metadata|password_hash|secret_hash|access_token|refresh_token)\s*[:=]/i;

const INTERNAL_DIAGNOSTIC_LINE_RES = [
  /^\s*Knowledge Graph contains 0 records\b/i,
  /^\s*No trained checkpoint\b/i,
  /^\s*AST parsing failure\b/i,
];

const TRACE_PLACEHOLDER_ONLY_RE =
  /^(?:undefined|null|none|nan|\[object\s+object\]|tbd|todo|n\/?a|placeholder|[-—_.•:;\s]+)$/i;

const TRACE_METADATA_LABEL_RE =
  /^\s*(?:รายละเอียดและข้อกำหนด|อ้างอิงไฟล์แนบ|เป้าหมาย)\s*[:：]\s*(.*)$/;

const TRACE_WRAPPER_PREFIX_RE =
  /^(?:วางแผนและพัฒนาซอร์สโค้ด|สร้างเอกสารและรายงานเชิงโครงสร้าง|ออกแบบและสร้างโครงสร้างข้อมูล\/ตาราง|วางแผน)\s*[:：]?\s*$/;

const THAI_CONSONANT_RE = /[\u0E01-\u0E2E]/;
const THAI_CHAR_ONLY_RE = /^[\u0E00-\u0E7F]+$/;

const VALID_PLAN_TOP_STATUSES = new Set([
  'PLANNED',
  'READY',
  'RUNNING',
  'EXECUTING',
  'COMPLETED',
  'VERIFIED',
  'PENDING_APPROVAL',
  'AWAITING_APPROVAL',
]);

const VALID_PLAN_STEP_STATUSES = new Set([
  'READY',
  'BLOCKED',
  'RUNNING',
  'EXECUTING',
  'COMPLETED',
  'VERIFIED',
  'PENDING_APPROVAL',
  'AWAITING_APPROVAL',
  'FAILED',
  'CANCELLED',
]);

function isThaiNonBaseMarkCode(code: number): boolean {
  return (
    (code >= 0x0e30 && code <= 0x0e3a) ||
    (code >= 0x0e40 && code <= 0x0e4e)
  );
}

function isThaiRepeatedToneOrSaraACode(code: number): boolean {
  return code === 0x0e30 || (code >= 0x0e47 && code <= 0x0e4c);
}

function hasCorruptThaiToken(text: string): boolean {
  const tokens = text.split(/[\s,.;:!?()[\]{}"'`]+/).filter(Boolean);
  for (const tok of tokens) {
    if (THAI_CHAR_ONLY_RE.test(tok) && !THAI_CONSONANT_RE.test(tok)) {
      return true;
    }
    const codes = Array.from(tok, (ch) => ch.codePointAt(0) ?? 0);
    if (codes.length > 0 && codes.every(isThaiNonBaseMarkCode)) {
      return true;
    }
    // Repeated sara-a / tone mark artifact like "กาะะะ" or "ะะี"
    for (let i = 1; i < codes.length; i += 1) {
      if (
        isThaiRepeatedToneOrSaraACode(codes[i]) &&
        isThaiRepeatedToneOrSaraACode(codes[i - 1])
      ) {
        return true;
      }
    }
  }
  return false;
}

export function isMalformedOrEmptyTraceText(raw?: string | null): boolean {
  const input = String(raw ?? '').trim();
  if (!input) return true;
  if (TRACE_PLACEHOLDER_ONLY_RE.test(input)) return true;
  if (/\b(?:undefined|\[object Object\])\b/i.test(input) && input.length < 40) return true;

  // Inspect lines independently so wrapper headers like "วางแผนและพัฒนาซอร์สโค้ด\n\nรายละเอียดและข้อกำหนด:\nะะี"
  // do not mask a completely malformed or empty payload.
  const lines = input
    .split(/\r?\n/)
    .map((ln) => ln.trim())
    .filter(Boolean);
  if (lines.length === 0) return true;

  const meaningfulPayloads: string[] = [];
  for (const ln of lines) {
    const labelMatch = ln.match(TRACE_METADATA_LABEL_RE);
    if (labelMatch) {
      const payload = labelMatch[1].trim();
      if (!payload) continue;
      if (TRACE_PLACEHOLDER_ONLY_RE.test(payload) || hasCorruptThaiToken(payload)) {
        return true;
      }
      meaningfulPayloads.push(payload);
      continue;
    }
    if (TRACE_WRAPPER_PREFIX_RE.test(ln)) {
      continue;
    }
    if (TRACE_PLACEHOLDER_ONLY_RE.test(ln) || hasCorruptThaiToken(ln)) {
      return true;
    }
    if (/(.)\1{5,}/.test(ln.replace(/\s+/g, '')) && ln.replace(/\s+/g, '').length <= 24) {
      return true;
    }
    meaningfulPayloads.push(ln);
  }

  return meaningfulPayloads.length === 0;
}

export function sanitizeTraceDisplayText(raw?: string | null): string {
  const input = String(raw ?? '');
  if (!input.trim()) return '';

  const lines = input.split(/\r?\n/);
  const kept: string[] = [];
  let inCodeBlock = false;
  let pendingSpecHeader = false;

  for (const line of lines) {
    if (/^\s*```/.test(line)) {
      inCodeBlock = !inCodeBlock;
      pendingSpecHeader = false;
      kept.push(line);
      continue;
    }
    if (inCodeBlock) {
      kept.push(line);
      continue;
    }

    const trimmed = line.trim();
    if (!trimmed) {
      if (kept.length > 0 && kept[kept.length - 1] !== '') {
        kept.push('');
      }
      continue;
    }

    if (
      INTERNAL_LINE_PREFIX_RE.test(line) ||
      INTERNAL_DIAGNOSTIC_LINE_RES.some((re) => re.test(line))
    ) {
      continue;
    }

    const labelMatch = trimmed.match(TRACE_METADATA_LABEL_RE);
    if (labelMatch) {
      const payload = labelMatch[1].trim();
      if (!payload) {
        pendingSpecHeader = true;
        continue;
      }
      pendingSpecHeader = false;
      if (TRACE_PLACEHOLDER_ONLY_RE.test(payload) || hasCorruptThaiToken(payload)) {
        continue;
      }
      kept.push(line);
      continue;
    }

    if (TRACE_PLACEHOLDER_ONLY_RE.test(trimmed) || hasCorruptThaiToken(trimmed)) {
      pendingSpecHeader = false;
      continue;
    }

    if (/(.)\1{5,}/.test(trimmed.replace(/\s+/g, '')) && trimmed.replace(/\s+/g, '').length <= 24) {
      pendingSpecHeader = false;
      continue;
    }

    if (pendingSpecHeader) {
      kept.push(`รายละเอียดและข้อกำหนด: ${trimmed}`);
      pendingSpecHeader = false;
      continue;
    }

    kept.push(line);
  }

  while (kept.length > 0 && kept[kept.length - 1] === '') {
    kept.pop();
  }
  const result = kept.join('\n').trim();
  if (!result || TRACE_WRAPPER_PREFIX_RE.test(result)) {
    return '';
  }
  return result;
}

export function filterValidTraceSteps(
  steps: Array<string | null | undefined>
): string[] {
  const out: string[] = [];
  for (const step of steps) {
    const clean = sanitizeTraceDisplayText(step);
    if (!clean) continue;
    if (isMalformedOrEmptyTraceText(clean)) continue;
    if (/\[(undefined|null|none)\]/i.test(clean)) continue;
    out.push(clean);
  }
  return out;
}

export interface ValidatedTracePlanResult {
  valid: boolean;
  goal: string;
  planStatus: string;
  steps: Array<{
    step_id: string;
    title: string;
    status: string;
    depends_on: string[];
    requires_approval: boolean;
    detail: string;
  }>;
  statusTransitions: Array<{
    step_id?: string;
    from_status: string;
    to_status: string;
    reason?: string;
  }>;
}

export function validateTracePlan(
  plan?: NativeTrace['plan'] | null
): ValidatedTracePlanResult {
  const empty: ValidatedTracePlanResult = {
    valid: false,
    goal: '',
    planStatus: 'NEEDS_CLARIFICATION',
    steps: [],
    statusTransitions: [],
  };
  if (!plan || typeof plan !== 'object') return empty;
  if (plan.plan_valid === false || plan.is_actionable_goal === false) return empty;

  const rawPlanStatus = String(plan.plan_status || plan.status || 'PLANNED')
    .trim()
    .toUpperCase();
  if (!VALID_PLAN_TOP_STATUSES.has(rawPlanStatus)) {
    return empty;
  }

  const cleanGoal = sanitizeTraceDisplayText(plan.goal);
  if (!cleanGoal || isMalformedOrEmptyTraceText(cleanGoal)) {
    return empty;
  }

  const rawSteps = Array.isArray(plan.steps) ? plan.steps : [];
  const validSteps = rawSteps
    .map((s) => {
      const stepId = String(s?.step_id ?? '').trim();
      const title = sanitizeTraceDisplayText(s?.title);
      const detail = sanitizeTraceDisplayText(s?.detail);
      const status = String(s?.status ?? '')
        .trim()
        .toUpperCase();
      if (
        !stepId ||
        TRACE_PLACEHOLDER_ONLY_RE.test(stepId) ||
        !title ||
        isMalformedOrEmptyTraceText(title) ||
        !detail ||
        isMalformedOrEmptyTraceText(detail) ||
        !VALID_PLAN_STEP_STATUSES.has(status)
      ) {
        return null;
      }
      return {
        step_id: stepId,
        title,
        status,
        depends_on: Array.isArray(s?.depends_on)
          ? s.depends_on.map((d) => String(d).trim()).filter(Boolean)
          : [],
        requires_approval: Boolean(s?.requires_approval),
        detail,
      };
    })
    .filter((s): s is NonNullable<typeof s> => s !== null);

  if (validSteps.length === 0) {
    return empty;
  }

  const transitions = Array.isArray(plan.status_transitions)
    ? plan.status_transitions
        .filter((tr) => {
          const from = String(tr?.from_status ?? '').trim();
          const to = String(tr?.to_status ?? '').trim();
          return (
            Boolean(from) &&
            Boolean(to) &&
            !TRACE_PLACEHOLDER_ONLY_RE.test(from) &&
            !TRACE_PLACEHOLDER_ONLY_RE.test(to)
          );
        })
        .map((tr) => ({
          step_id: tr.step_id ? String(tr.step_id).trim() : undefined,
          from_status: String(tr.from_status).trim().toUpperCase(),
          to_status: String(tr.to_status).trim().toUpperCase(),
          reason: tr.reason ? sanitizeTraceDisplayText(tr.reason) : undefined,
        }))
    : [];

  return {
    valid: true,
    goal: cleanGoal,
    planStatus: rawPlanStatus,
    steps: validSteps,
    statusTransitions: transitions,
  };
}

export function redactSensitiveData(value: unknown, depth = 0): unknown {
  if (depth > 8 || value === null || value === undefined) return value;
  if (Array.isArray(value)) {
    return value.map((item) => redactSensitiveData(item, depth + 1));
  }
  if (typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (SENSITIVE_METADATA_KEYS.has(k) || SENSITIVE_METADATA_KEYS.has(k.toLowerCase())) {
        continue;
      }
      out[k] = redactSensitiveData(v, depth + 1);
    }
    return out;
  }
  return value;
}

function extractResponseFromDiagnosticJson(raw: string): string | null {
  let candidate = raw.trim();
  const fenced = candidate.match(/^```(?:json)?\s*\n([\s\S]*?)\n```$/i);
  if (fenced) {
    candidate = fenced[1].trim();
  }
  if (!(candidate.startsWith('{') && candidate.endsWith('}'))) {
    return null;
  }
  try {
    const parsed = JSON.parse(candidate) as Record<string, unknown>;
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const hasInternalKey = Object.keys(parsed).some((k) => INTERNAL_DIAGNOSTIC_KEYS.has(k));
      if (hasInternalKey) {
        for (const candidateKey of ['response', 'content', 'message', 'text', 'answer']) {
          const val = parsed[candidateKey];
          if (typeof val === 'string' && val.trim()) {
            return sanitizeAssistantDisplayContent(val);
          }
        }
        return 'พร้อมให้บริการครับ หากมีคำถามหรือเรื่องที่ต้องการให้ช่วย สามารถพิมพ์บอกได้เลยครับ';
      }
    }
  } catch {
    return null;
  }
  return null;
}

export function sanitizeAssistantDisplayContent(rawContent: string): string {
  const input = String(rawContent ?? '');
  const trimmed = input.trim();
  if (!trimmed) return '';

  const unwrapped = extractResponseFromDiagnosticJson(trimmed);
  if (unwrapped !== null) {
    return unwrapped;
  }

  const lines = input.split('\n');
  const kept: string[] = [];
  let inCodeBlock = false;
  let strippedAny = false;
  for (const line of lines) {
    if (/^\s*```/.test(line)) {
      inCodeBlock = !inCodeBlock;
      kept.push(line);
      continue;
    }
    if (!inCodeBlock) {
      if (
        INTERNAL_LINE_PREFIX_RE.test(line) ||
        INTERNAL_DIAGNOSTIC_LINE_RES.some((re) => re.test(line))
      ) {
        strippedAny = true;
        continue;
      }
      const lineTrim = line.trim();
      const labelMatch = lineTrim.match(TRACE_METADATA_LABEL_RE);
      if (
        labelMatch &&
        (!labelMatch[1].trim() ||
          TRACE_PLACEHOLDER_ONLY_RE.test(labelMatch[1].trim()) ||
          hasCorruptThaiToken(labelMatch[1].trim()))
      ) {
        strippedAny = true;
        continue;
      }
      if (lineTrim && hasCorruptThaiToken(lineTrim) && isMalformedOrEmptyTraceText(lineTrim)) {
        strippedAny = true;
        continue;
      }
      if (lineTrim.startsWith('{') && lineTrim.endsWith('}')) {
        const extracted = extractResponseFromDiagnosticJson(lineTrim);
        if (extracted !== null) {
          kept.push(extracted);
          continue;
        }
      }
    }
    kept.push(line);
  }

  const joined = kept.join('\n').trim();
  if (strippedAny) {
    return joined;
  }
  return joined || input.trim();
}

export function serializeTableToTsv(
  headers: string[],
  rows: Array<Array<string | number | boolean | null | undefined>>
): string {
  const cleanCell = (val: string | number | boolean | null | undefined): string => {
    if (val === null || val === undefined) return '';
    return String(val)
      .replace(/\r?\n+/g, ' ')
      .replace(/\t+/g, ' ')
      .trim();
  };
  const headerLine = headers.map(cleanCell).join('\t');
  const bodyLines = rows.map((row) => row.map(cleanCell).join('\t'));
  return [headerLine, ...bodyLines].filter((line) => line.length > 0).join('\n');
}

function splitMarkdownTableRow(line: string): string[] | null {
  const trimmed = line.trim();
  if (!trimmed.includes('|')) return null;
  const inner = trimmed.replace(/^\|/, '').replace(/\|$/, '');
  const cells = inner.split('|').map((c) => c.trim());
  return cells.length >= 2 ? cells : null;
}

function isMarkdownTableSeparator(line: string): boolean {
  const cells = splitMarkdownTableRow(line);
  if (!cells) return false;
  return cells.every((c) => /^:?-{3,}:?$/.test(c));
}

export function parseMarkdownPipeTable(
  lines: string[],
  startIndex: number
): { headers: string[]; rows: string[][]; nextIndex: number } | null {
  if (startIndex + 1 >= lines.length) return null;
  const headers = splitMarkdownTableRow(lines[startIndex]);
  if (!headers || !isMarkdownTableSeparator(lines[startIndex + 1])) return null;
  const rows: string[][] = [];
  let idx = startIndex + 2;
  while (idx < lines.length) {
    const row = splitMarkdownTableRow(lines[idx]);
    if (!row) break;
    const normalized = headers.map((_, colIdx) => row[colIdx] ?? '');
    rows.push(normalized);
    idx += 1;
  }
  return { headers, rows, nextIndex: idx };
}

function stripInlineMarkdown(line: string): string {
  let out = line;
  out = out.replace(/^(\s*)>\s?/, '$1');
  out = out.replace(/^(\s*)#{1,6}\s+/, '$1');
  out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '$1 ($2)');
  out = out.replace(/\*\*([^*]+)\*\*/g, '$1');
  out = out.replace(/`([^`]+)`/g, '$1');
  out = out.replace(/(^|[^\w])\*([^*\n]+)\*([^\w]|$)/g, '$1$2$3');
  return out;
}

export function toPlainAssistantCopyText(rawContent: string): string {
  const clean = sanitizeAssistantDisplayContent(rawContent);
  if (!clean) return '';

  const lines = clean.split('\n');
  const outLines: string[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Preserve fenced code block contents verbatim (including indentation and # comments)
    if (/^\s*```[a-zA-Z0-9_-]*\s*$/.test(line)) {
      i += 1;
      const codeLines: string[] = [];
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
        codeLines.push(lines[i]);
        i += 1;
      }
      if (i < lines.length && /^\s*```\s*$/.test(lines[i])) {
        i += 1;
      }
      outLines.push(...codeLines);
      continue;
    }

    // Convert Markdown pipe tables to tab-separated format
    const table = parseMarkdownPipeTable(lines, i);
    if (table) {
      outLines.push(
        serializeTableToTsv(
          table.headers.map(stripInlineMarkdown),
          table.rows.map((r) => r.map(stripInlineMarkdown))
        )
      );
      i = table.nextIndex;
      continue;
    }

    outLines.push(stripInlineMarkdown(line));
    i += 1;
  }

  return outLines
    .filter((line, idx, arr) => !(line === '' && (idx === 0 || idx === arr.length - 1)))
    .join('\n');
}

export async function copyTextToClipboard(
  text: string
): Promise<{ ok: boolean; error?: string }> {
  if (!text) {
    return { ok: false, error: 'ไม่มีข้อความให้คัดลอก' };
  }

  // 1. Primary modern Clipboard API
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return { ok: true };
    } catch {
      // Fall through to execCommand fallback (e.g. Android WebView / restricted context)
    }
  }

  // 2. Fallback off-screen textarea selection for Android/legacy browsers
  if (typeof document !== 'undefined' && document.body) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    textarea.style.top = '0';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    try {
      textarea.focus();
      textarea.select();
      textarea.setSelectionRange(0, text.length);
      const copied =
        typeof document.execCommand === 'function' ? document.execCommand('copy') : false;
      if (copied) {
        return { ok: true };
      }
    } catch {
      // Handled below
    } finally {
      if (textarea.parentNode) {
        textarea.parentNode.removeChild(textarea);
      }
    }
  }

  return { ok: false, error: 'คัดลอกไม่สำเร็จ (คลิปบอร์ดถูกจำกัดสิทธิ์)' };
}
