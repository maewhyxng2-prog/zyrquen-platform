import { apiRequest } from './api';
import type { ExternalToolItem, ReasoningMode, ToolInvocationItem } from '../types';

export type ToolId = 'web_search' | 'doc_fetch' | 'calc_ast' | 'workspace_file_read';

export const BLOCKED_EXTERNAL_AI_HOSTS = [
  'api.openai.com',
  'openai.com',
  'api.anthropic.com',
  'anthropic.com',
  'generativelanguage.googleapis.com',
  'aiplatform.googleapis.com',
  'api.groq.com',
  'api.together.xyz',
  'openrouter.ai',
  'api.cohere.ai',
  'api-inference.huggingface.co',
  'api.mistral.ai',
  'api.perplexity.ai',
] as const;

export interface ToolValidationResult {
  ok: boolean;
  error?: string;
  normalizedInput: Record<string, unknown>;
  requiresApproval?: boolean;
}

export interface ToolAnalysisPayload {
  trust_grade?: string;
  summary?: string;
  limitations?: string[];
  distinct_providers?: string[];
  cross_source_shared_terms?: string[];
  kg_matches?: Array<{ subject: string; relation: string; object: string }>;
}

export interface ToolExecutionResult {
  ok: boolean;
  status: 'COMPLETED' | 'PENDING_APPROVAL' | 'BLOCKED' | 'FAILED' | 'REJECTED' | string;
  invocation?: ToolInvocationItem;
  analysis?: ToolAnalysisPayload;
  tool?: ExternalToolItem;
  error?: string;
}

export interface ToolAuditEntry {
  toolId: ToolId;
  action: string;
  outcome: string;
  invocationId?: string;
  trustGrade?: string;
  timestamp: string;
  detail?: string;
}

export interface ExternalToolAdapter {
  validate(
    toolId: ToolId,
    input: Record<string, unknown>,
    options?: {
      toolPolicy?: ExternalToolItem;
      userRole?: 'admin' | 'user';
    }
  ): ToolValidationResult;
  run(
    toolId: ToolId,
    input: Record<string, unknown>,
    token: string,
    options?: {
      conversationId?: string | null;
      toolPolicy?: ExternalToolItem;
      userRole?: 'admin' | 'user';
    }
  ): Promise<ToolExecutionResult>;
  audit(entry: ToolAuditEntry): ToolAuditEntry[];
}

function validatePublicNonAiUrl(rawUrl: string): { ok: boolean; error?: string; normalized?: string } {
  const trimmed = rawUrl.trim();
  if (!trimmed) {
    return { ok: false, error: 'กรุณาระบุ URL เป้าหมาย (https://...)' };
  }
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return { ok: false, error: 'รูปแบบ URL ไม่ถูกต้อง' };
  }
  if (parsed.protocol !== 'https:') {
    return { ok: false, error: 'อนุญาตเฉพาะโปรโตคอล https:// เท่านั้น' };
  }
  const host = parsed.hostname.toLowerCase();
  if (!host || host === 'localhost' || host === '127.0.0.1' || host === '::1' || host.endsWith('.local')) {
    return { ok: false, error: 'ปฏิเสธการเข้าถึงโฮสต์ภายในเครื่อง' };
  }
  if (BLOCKED_EXTERNAL_AI_HOSTS.some((blocked) => host === blocked || host.endsWith(`.${blocked}`))) {
    return {
      ok: false,
      error: `ไม่อนุญาตให้เชื่อมต่อโฮสต์โมเดล AI ภายนอก (${host})`,
    };
  }
  return { ok: true, normalized: parsed.toString() };
}

export interface RoleToolPolicyDecision {
  allowed: boolean;
  requiresApproval: boolean;
  policyBadge: string;
  modeLabel: string;
}

export function canRoleExecuteTool(
  tool: ExternalToolItem,
  userRole: 'admin' | 'user'
): RoleToolPolicyDecision {
  if (!tool.enabled || tool.permission_mode === 'disabled') {
    return {
      allowed: false,
      requiresApproval: false,
      policyBadge: 'BLOCKED',
      modeLabel: 'ปิดการใช้งานโดยนโยบายระบบ',
    };
  }
  if (tool.calls_today >= tool.quota_daily) {
    return {
      allowed: false,
      requiresApproval: false,
      policyBadge: 'QUOTA_EXCEEDED',
      modeLabel: 'ใช้ครบโควตารายวันแล้ว',
    };
  }
  if (tool.permission_mode === 'approval_required') {
    return {
      allowed: true,
      requiresApproval: true,
      policyBadge: 'P5_GATE',
      modeLabel:
        userRole === 'admin'
          ? 'ต้องส่งคำขอผ่าน P5 Approval Gate (Admin สามารถอนุมัติได้)'
          : 'ต้องส่งคำขอรอผู้ดูแลระบบอนุมัติ (P5 Gate)',
    };
  }
  return {
    allowed: true,
    requiresApproval: false,
    policyBadge: 'AUTO',
    modeLabel: 'พร้อมเรียกใช้ภายใต้การตรวจสอบของ Core',
  };
}

export function getAllowedToolsForRole(
  tools: ExternalToolItem[],
  userRole: 'admin' | 'user'
): Array<ExternalToolItem & { policyDecision: RoleToolPolicyDecision }> {
  return tools.map((tool) => ({
    ...tool,
    policyDecision: canRoleExecuteTool(tool, userRole),
  }));
}

export function createExternalToolAdapter(): ExternalToolAdapter {
  const auditBuffer: ToolAuditEntry[] = [];

  const recordAudit = (entry: ToolAuditEntry): ToolAuditEntry[] => {
    auditBuffer.unshift(entry);
    if (auditBuffer.length > 25) {
      auditBuffer.length = 25;
    }
    return [...auditBuffer];
  };

  return {
    validate(toolId, input, options) {
      const policy = options?.toolPolicy;
      if (policy) {
        if (!policy.enabled || policy.permission_mode === 'disabled') {
          return {
            ok: false,
            error: `เครื่องมือ '${policy.name}' ถูกปิดใช้งานตามนโยบายระบบ`,
            normalizedInput: input,
          };
        }
        if (policy.calls_today >= policy.quota_daily) {
          return {
            ok: false,
            error: `เครื่องมือ '${policy.name}' ใช้ครบโควตารายวันแล้ว (${policy.calls_today}/${policy.quota_daily})`,
            normalizedInput: input,
          };
        }
      }

      if (toolId === 'web_search') {
        const query = String(input.query ?? '').trim();
        if (query.length < 2) {
          return { ok: false, error: 'กรุณาระบุคำค้นหาอย่างน้อย 2 ตัวอักษร', normalizedInput: input };
        }
        return {
          ok: true,
          normalizedInput: { ...input, query },
          requiresApproval: policy?.permission_mode === 'approval_required',
        };
      }

      if (toolId === 'doc_fetch') {
        const check = validatePublicNonAiUrl(String(input.url ?? ''));
        if (!check.ok || !check.normalized) {
          return { ok: false, error: check.error, normalizedInput: input };
        }
        return {
          ok: true,
          normalizedInput: { url: check.normalized },
          requiresApproval: policy?.permission_mode === 'approval_required',
        };
      }

      if (toolId === 'calc_ast') {
        const expression = String(input.expression ?? '').trim();
        if (!expression) {
          return { ok: false, error: 'กรุณาระบุนิพจน์คณิตศาสตร์ สมการ หรือชุดข้อมูลสถิติ', normalizedInput: input };
        }
        return {
          ok: true,
          normalizedInput: { expression },
          requiresApproval: policy?.permission_mode === 'approval_required',
        };
      }

      if (toolId === 'workspace_file_read') {
        const action = String(input.action ?? 'read').trim().toLowerCase();
        if (!['read', 'list', 'write'].includes(action)) {
          return { ok: false, error: 'รองรับเฉพาะ action: read, list หรือ write', normalizedInput: input };
        }
        if (action === 'list') {
          return {
            ok: true,
            normalizedInput: { action: 'list' },
            requiresApproval: policy?.permission_mode === 'approval_required',
          };
        }
        const filename = String(input.filename ?? '').trim();
        if (!filename) {
          return { ok: false, error: 'กรุณาระบุชื่อไฟล์ภายใน Sandbox', normalizedInput: input };
        }
        if (filename.includes('..') || filename.startsWith('/')) {
          return { ok: false, error: 'ไม่อนุญาตเส้นทางไฟล์นอกโฟลเดอร์เวิร์กสเปซ', normalizedInput: input };
        }
        if (action === 'write' && !/\.(txt|md|json|csv)$/i.test(filename)) {
          return { ok: false, error: 'รองรับการเขียนเฉพาะ .txt, .md, .json, .csv เท่านั้น', normalizedInput: input };
        }
        return {
          ok: true,
          normalizedInput: {
            action,
            filename,
            ...(action === 'write' ? { content: String(input.content ?? '') } : {}),
          },
          requiresApproval: action === 'write' || policy?.permission_mode === 'approval_required',
        };
      }

      return { ok: false, error: `ไม่รู้จักเครื่องมือ '${toolId}'`, normalizedInput: input };
    },

    async run(toolId, input, token, options) {
      const validation = this.validate(toolId, input, {
        toolPolicy: options?.toolPolicy,
        userRole: options?.userRole,
      });

      if (!validation.ok) {
        recordAudit({
          toolId,
          action: 'ADAPTER_VALIDATE_REJECTED',
          outcome: 'BLOCKED',
          timestamp: new Date().toISOString(),
          detail: validation.error,
        });
        return {
          ok: false,
          status: 'FAILED',
          error: validation.error || 'ข้อมูลนำเข้าไม่ผ่านสัญญา Tool Contract',
        };
      }

      const res = await apiRequest<ToolExecutionResult>(`/api/developer/tools/${toolId}/invoke`, {
        method: 'POST',
        token,
        body: {
          input: validation.normalizedInput,
          conversationId: options?.conversationId ?? null,
        },
      });

      recordAudit({
        toolId,
        action: `TOOL_INVOKE_${toolId.toUpperCase()}`,
        outcome: res.status || (res.ok ? 'COMPLETED' : 'FAILED'),
        invocationId: res.invocation?.id,
        trustGrade: res.analysis?.trust_grade,
        timestamp: new Date().toISOString(),
        detail: res.analysis?.summary || res.invocation?.analysis_summary || res.error,
      });

      return res;
    },

    audit: recordAudit,
  };
}

export const externalToolAdapter = createExternalToolAdapter();

export function detectPendingToolActivity(
  prompt: string,
  mode: ReasoningMode
): { toolId: ToolId | 'native_core'; label: string } {
  const cleaned = prompt.trim();
  if (/^(?:ค้นคว้า|เปรียบเทียบ|research|investigate|compare|ค้นหาเว็บ|ค้นเว็บ|web_search|websearch|search_web)(?:\s*:|\s|$)/i.test(cleaned)) {
    return {
      toolId: 'web_search',
      label: 'กำลังสืบค้นข้อมูลและตรวจสอบหลักฐาน...',
    };
  }
  if (/^(?:อ่านเอกสาร|ดึงเว็บ|doc_fetch|fetch_doc|fetch)(?:\s*:|\s|$)/i.test(cleaned)) {
    return {
      toolId: 'doc_fetch',
      label: 'กำลังอ่านเอกสารและสกัดโครงสร้าง...',
    };
  }
  if (/^(?:เขียนไฟล์|บันทึกไฟล์|อ่านไฟล์|จัดการไฟล์|ไฟล์เวิร์กสเปซ|ไฟล์|write_file|file_read|read_file)(?:\s*:|\s|$)/i.test(cleaned)) {
    return {
      toolId: 'workspace_file_read',
      label: 'กำลังตรวจสอบไฟล์ในพื้นที่ปลอดภัย...',
    };
  }
  if (
    mode === 'math' ||
    /^(?:คำนวณ|แก้สมการ|สถิติ|mean|median|stdev)(?:\s*:|\s|$)/i.test(cleaned)
  ) {
    return {
      toolId: 'calc_ast',
      label: 'กำลังคำนวณผ่าน AST Engine ภายใน...',
    };
  }
  return {
    toolId: 'native_core',
    label: 'กำลังประมวลผลผ่านแกนสมอง Python ภายใน...',
  };
}
