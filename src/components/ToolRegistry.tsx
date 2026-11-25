import React, { useMemo, useState } from 'react';
import { Check, Lock, ShieldCheck, Wrench, X } from 'lucide-react';
import { apiRequest, ApiError } from '../lib/api';
import {
  canRoleExecuteTool,
  externalToolAdapter,
  getAllowedToolsForRole,
  type ToolAuditEntry,
  type ToolId,
} from '../lib/tools';
import type { ExternalToolItem, ToolInvocationItem, ToolsOverview } from '../types';
import { CopyButton } from './CopyButton';

interface ToolRegistryProps {
  token: string;
  userRole: 'admin' | 'user';
  mode: 'developer' | 'admin';
  toolsData?: ToolsOverview | null;
  pendingInvocations?: ToolInvocationItem[];
  adminTools?: ExternalToolItem[];
  onRefresh: () => Promise<void> | void;
  onError?: (message: string) => void;
}

const TOOL_OPTION_LABELS: Record<ToolId, string> = {
  web_search: 'web_search (ค้นหาเว็บ)',
  doc_fetch: 'doc_fetch (อ่าน URL)',
  calc_ast: 'calc_ast (คำนวณ AST)',
  workspace_file_read: 'workspace_file_read (อ่านไฟล์)',
};

export function ToolRegistry({
  token,
  userRole,
  mode,
  toolsData,
  pendingInvocations = [],
  adminTools = [],
  onRefresh,
  onError,
}: ToolRegistryProps) {
  const [selectedToolId, setSelectedToolId] = useState<ToolId>('web_search');
  const [toolParam, setToolParam] = useState('');
  const [toolMessage, setToolMessage] = useState<string | null>(null);
  const [invokingTool, setInvokingTool] = useState(false);
  const [wsFilename, setWsFilename] = useState('');
  const [wsContent, setWsContent] = useState('');
  const [adapterAudit, setAdapterAudit] = useState<ToolAuditEntry[]>([]);

  const devTools = useMemo(() => toolsData?.tools || [], [toolsData?.tools]);
  const evaluatedTools = useMemo(
    () => getAllowedToolsForRole(devTools, userRole),
    [devTools, userRole]
  );
  const policyById = useMemo(
    () => new Map(evaluatedTools.map((t) => [t.id, t])),
    [evaluatedTools]
  );
  const selectedTool = devTools.find((t) => t.id === selectedToolId);
  const selectedPolicy = selectedTool ? canRoleExecuteTool(selectedTool, userRole) : null;
  const allowedCount = evaluatedTools.filter((t) => t.policyDecision.allowed).length;

  async function handleInvokeTool(e: React.FormEvent) {
    e.preventDefault();
    if (selectedPolicy && !selectedPolicy.allowed) {
      setToolMessage(selectedPolicy.modeLabel);
      return;
    }
    setInvokingTool(true);
    setToolMessage(null);
    try {
      const payloadInput: Record<string, unknown> =
        selectedToolId === 'web_search'
          ? { query: toolParam }
          : selectedToolId === 'doc_fetch'
            ? { url: toolParam }
            : selectedToolId === 'calc_ast'
              ? { expression: toolParam }
              : toolParam.trim()
                ? { action: 'read', filename: toolParam.trim() }
                : { action: 'list' };

      const res = await externalToolAdapter.run(selectedToolId, payloadInput, token, {
        toolPolicy: selectedTool,
        userRole,
      });

      setAdapterAudit(
        externalToolAdapter.audit({
          toolId: selectedToolId,
          action: 'REGISTRY_CLIENT_CHECK',
          outcome: res.status,
          invocationId: res.invocation?.id,
          trustGrade: res.analysis?.trust_grade,
          timestamp: new Date().toISOString(),
          detail: res.analysis?.summary || res.error,
        })
      );

      if (!res.ok) {
        setToolMessage(res.error || 'การเรียกเครื่องมือไม่ผ่านเงื่อนไข');
        return;
      }

      setToolMessage(
        res.analysis?.summary ||
          res.invocation?.analysis_summary ||
          `สถานะเครื่องมือ: ${res.status}`
      );
      await onRefresh();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'เรียกใช้เครื่องมือไม่สำเร็จ';
      setToolMessage(msg);
      onError?.(msg);
    } finally {
      setInvokingTool(false);
    }
  }

  async function handleSaveWorkspaceFile(e: React.FormEvent) {
    e.preventDefault();
    setToolMessage(null);
    try {
      await apiRequest('/api/developer/workspace-files', {
        method: 'POST',
        token,
        body: { filename: wsFilename, content: wsContent },
      });
      setToolMessage(`บันทึกไฟล์ "${wsFilename}" ลงใน workspace_files แล้ว`);
      setWsFilename('');
      setWsContent('');
      await onRefresh();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'บันทึกไฟล์ไม่สำเร็จ';
      onError?.(msg);
    }
  }

  async function handleToolInvocationDecision(
    invocationId: string,
    decision: 'approve' | 'reject'
  ) {
    try {
      await apiRequest(`/api/admin/tool-invocations/${invocationId}/decide`, {
        method: 'POST',
        token,
        body: { decision },
      });
      await onRefresh();
    } catch (err) {
      onError?.(err instanceof ApiError ? err.message : 'อนุมัติเครื่องมือภายนอกไม่สำเร็จ');
    }
  }

  async function handleUpdateToolPolicy(
    toolId: string,
    patch: {
      permission_mode?: ExternalToolItem['permission_mode'];
      enabled?: boolean;
      quota_daily?: number;
    }
  ) {
    try {
      await apiRequest(`/api/admin/tools/${toolId}`, {
        method: 'PATCH',
        token,
        body: patch,
      });
      await onRefresh();
    } catch (err) {
      onError?.(err instanceof ApiError ? err.message : 'อัปเดตสิทธิ์เครื่องมือไม่สำเร็จ');
    }
  }

  if (mode === 'admin') {
    return (
      <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-[var(--color-accent)]" />
          <h3 className="text-base font-semibold text-[var(--color-text)]">
            Tool Approval Gate & นโยบายสิทธิ์เครื่องมือภายนอก
          </h3>
        </div>
        <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
          อนุมัติคำขอเรียกใช้เครื่องมือภายนอกตามสิทธิ์บทบาท ({userRole}) และกำหนดระดับนโยบาย P5 Approval Gate
        </p>

        <div className="mt-4 divide-y divide-[var(--color-border)]">
          {pendingInvocations.length === 0 ? (
            <p className="py-3 text-sm text-[var(--color-text-secondary)]">
              ไม่มีคำขอเรียกใช้เครื่องมือภายนอกที่รออนุมัติ
            </p>
          ) : (
            pendingInvocations.map((inv) => (
              <div
                key={inv.id}
                className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <div>
                  <p className="font-mono text-sm font-semibold text-[var(--color-accent)]">{inv.tool_id}</p>
                  <p className="text-xs text-[var(--color-text-secondary)]">{inv.input_json}</p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void handleToolInvocationDecision(inv.id, 'approve')}
                    className="flex h-10 items-center gap-1.5 rounded-xl bg-[var(--color-primary)] px-4 text-xs font-medium text-white hover:bg-[var(--color-primary-hover)]"
                  >
                    <Check className="h-3.5 w-3.5" />
                    <span>อนุมัติเครื่องมือ</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleToolInvocationDecision(inv.id, 'reject')}
                    className="flex h-10 items-center gap-1.5 rounded-xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] px-4 text-xs font-medium text-[var(--color-danger)] hover:opacity-90"
                  >
                    <X className="h-3.5 w-3.5" />
                    <span>ปฏิเสธ</span>
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        {adminTools.length > 0 && (
          <div className="mt-4 divide-y divide-[var(--color-border)] border-t border-[var(--color-border)] pt-3">
            {adminTools.map((tl) => {
              const roleStatus = canRoleExecuteTool(tl, userRole);
              const isEnabled = Boolean(tl.enabled);
              return (
                <div
                  key={tl.id}
                  className="flex flex-col gap-2 py-2.5 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div>
                    <p className="text-xs font-semibold text-[var(--color-text)]">{tl.name}</p>
                    <p className="font-mono text-[11px] text-[var(--color-text-secondary)]">
                      {tl.id} · โควตา {tl.calls_today}/{tl.quota_daily} · {roleStatus.modeLabel}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        void handleUpdateToolPolicy(tl.id, { enabled: !isEnabled })
                      }
                      aria-pressed={isEnabled}
                      className={`h-9 rounded-lg border px-2.5 text-xs font-medium transition-colors ${
                        isEnabled
                          ? 'border-[var(--color-primary)]/45 bg-[var(--color-surface)] text-[var(--color-accent)] hover:border-[var(--color-accent)]'
                          : 'border-[var(--color-danger)]/40 bg-[var(--color-danger-bg)] text-[var(--color-danger)] hover:opacity-90'
                      }`}
                    >
                      {isEnabled ? 'เปิดใช้งาน' : 'ปิดใช้งาน'}
                    </button>
                    <select
                      aria-label={`สิทธิ์ ${tl.id}`}
                      value={tl.permission_mode}
                      onChange={(e) =>
                        void handleUpdateToolPolicy(tl.id, {
                          permission_mode: e.target.value as ExternalToolItem['permission_mode'],
                        })
                      }
                      className="h-9 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
                    >
                      <option value="approval_required">ต้องอนุมัติ (approval_required)</option>
                      <option value="auto">อัตโนมัติ (auto)</option>
                      <option value="disabled">ปิดการใช้งาน (disabled)</option>
                    </select>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    );
  }

  return (
    <section className="rounded-3xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-5 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Wrench className="h-4 w-4 text-[var(--color-accent)]" />
          <h3 className="text-base font-semibold text-[var(--color-text)]">
            Tool Registry & โควตาเครื่องมือภายนอก
          </h3>
        </div>
        <span className="font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums">
          บทบาท: {userRole}
          {devTools.length > 0 ? ` · อนุญาต ${allowedCount}/${devTools.length} เครื่องมือ` : ''}
        </span>
      </div>
      <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
        เครื่องมือเสริมที่ทำงานผ่านสัญญา ExternalToolAdapter ภายใต้การควบคุมสิทธิ์ของ Native AI Core และ P5 Approval Gate (ไม่เชื่อมต่อ LLM ภายนอก)
      </p>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {evaluatedTools.map((tl) => {
          const allowlist = (() => {
            try {
              return JSON.parse(tl.endpoint_allowlist_json || '[]') as string[];
            } catch {
              return [];
            }
          })();
          const roleStatus = tl.policyDecision;
          return (
            <div
              key={tl.id}
              className={`rounded-2xl border p-3.5 ${
                roleStatus.allowed
                  ? 'border-[var(--color-border)] bg-[var(--color-surface)]'
                  : 'border-[var(--color-danger)]/35 bg-[var(--color-surface)]/80 opacity-90'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold text-[var(--color-text)]">{tl.name}</span>
                <span
                  className={`rounded-md border px-2 py-0.5 font-mono text-[10px] ${
                    !roleStatus.allowed
                      ? 'border-[var(--color-danger)]/40 text-[var(--color-danger)]'
                      : roleStatus.requiresApproval
                        ? 'border-[var(--color-warning)]/40 text-[var(--color-warning)]'
                        : 'border-[var(--color-border)] text-[var(--color-accent)]'
                  }`}
                >
                  {tl.permission_mode}
                </span>
              </div>
              <p className="mt-1 text-[11px] text-[var(--color-text-secondary)]">{tl.description}</p>
              <p className="mt-2 font-mono text-[11px] text-[var(--color-text)] tabular-nums">
                โควตาวันนี้: {tl.calls_today}/{tl.quota_daily}
                {allowlist.length > 0 ? ` · allow: ${allowlist.join(', ')}` : ''}
              </p>
              <p
                className={`mt-1 flex items-center gap-1.5 text-[11px] ${
                  roleStatus.allowed ? 'text-[var(--color-accent)]' : 'text-[var(--color-danger)]'
                }`}
              >
                {!roleStatus.allowed && <Lock className="h-3 w-3 shrink-0" />}
                <span>{roleStatus.modeLabel}</span>
              </p>
            </div>
          );
        })}
      </div>

      <form onSubmit={handleInvokeTool} className="mt-4 flex flex-col gap-2 sm:flex-row">
        <select
          aria-label="เลือกเครื่องมือ"
          value={selectedToolId}
          onChange={(e) => setSelectedToolId(e.target.value as ToolId)}
          className="h-11 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)] focus:border-[var(--color-focus)] focus:outline-none"
        >
          {(Object.keys(TOOL_OPTION_LABELS) as ToolId[]).map((tid) => {
            const matched = policyById.get(tid);
            const blocked = matched ? !matched.policyDecision.allowed : false;
            return (
              <option key={tid} value={tid} disabled={blocked}>
                {TOOL_OPTION_LABELS[tid]}
                {blocked ? ' [ถูกปิด/เต็มโควตา]' : ''}
              </option>
            );
          })}
        </select>
        <input
          type="text"
          value={toolParam}
          onChange={(e) => setToolParam(e.target.value)}
          placeholder={
            selectedToolId === 'web_search'
              ? 'คำค้นสาธารณะ (เช่น SQLite)'
              : selectedToolId === 'doc_fetch'
                ? 'https://en.wikipedia.org/wiki/SQLite'
                : selectedToolId === 'calc_ast'
                  ? 'แก้สมการ: 3x + 7 = 22'
                  : 'ชื่อไฟล์ (ว่างเพื่อดูรายการ)'
          }
          className="h-11 flex-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
        />
        <button
          type="submit"
          disabled={invokingTool || Boolean(selectedPolicy && !selectedPolicy.allowed)}
          className="h-11 rounded-xl bg-[var(--color-primary)] px-5 text-xs font-medium text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50 whitespace-nowrap"
        >
          {invokingTool
            ? 'กำลังเรียก...'
            : selectedPolicy && !selectedPolicy.allowed
              ? 'ถูกจำกัดสิทธิ์'
              : 'เรียกเครื่องมือ'}
        </button>
      </form>

      {selectedPolicy && !selectedPolicy.allowed && (
        <p className="mt-2 text-xs text-[var(--color-danger)]">
          ไม่สามารถเรียกใช้ `{selectedToolId}` ได้: {selectedPolicy.modeLabel}
        </p>
      )}
      {selectedPolicy && selectedPolicy.allowed && selectedPolicy.requiresApproval && (
        <p className="mt-2 text-xs text-[var(--color-warning)]">
          เครื่องมือนี้ควบคุมโดย P5 Approval Gate ({selectedPolicy.modeLabel})
        </p>
      )}
      {toolMessage && (
        <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-xs text-[var(--color-accent)]">
          <span className="min-w-0 flex-1 break-words">{toolMessage}</span>
          <CopyButton
            getText={() => toolMessage}
            ariaLabel="คัดลอกผลลัพธ์เครื่องมือ"
            title="คัดลอกผลลัพธ์การทำงานของเครื่องมือ"
            size="xs"
          />
        </div>
      )}

      <form
        onSubmit={handleSaveWorkspaceFile}
        className="mt-5 grid gap-2 border-t border-[var(--color-border)] pt-4 sm:grid-cols-3"
      >
        <input
          type="text"
          required
          value={wsFilename}
          onChange={(e) => setWsFilename(e.target.value)}
          placeholder="ชื่อไฟล์ (เช่น notes.txt)"
          className="h-10 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
        />
        <input
          type="text"
          required
          value={wsContent}
          onChange={(e) => setWsContent(e.target.value)}
          placeholder="เนื้อหาข้อความสำหรับเครื่องมืออ่านไฟล์..."
          className="h-10 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-xs text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-focus)] focus:outline-none"
        />
        <button
          type="submit"
          className="h-10 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 text-xs font-medium text-[var(--color-accent)] hover:border-[var(--color-accent)] hover:bg-[var(--color-surface-hover)]"
        >
          บันทึกไฟล์ใน Sandbox
        </button>
      </form>

      {((toolsData?.invocations || []).length > 0 || adapterAudit.length > 0) && (
        <div className="mt-4 divide-y divide-[var(--color-border)] border-t border-[var(--color-border)] pt-2">
          {(toolsData?.invocations || []).slice(0, 5).map((inv) => (
            <div key={inv.id} className="flex items-center justify-between gap-3 py-2 text-xs">
              <div className="min-w-0 flex-1">
                <span className="font-mono text-[var(--color-accent)]">{inv.tool_id}</span>{' '}
                <span className="text-[var(--color-text-secondary)]">· {inv.analysis_summary || inv.input_json}</span>
              </div>
              <span className="shrink-0 font-mono text-[11px] text-[var(--color-text)]">{inv.status}</span>
            </div>
          ))}
          {adapterAudit.slice(0, 3).map((entry, idx) => (
            <div
              key={`${entry.timestamp}-${idx}`}
              className="flex items-center justify-between gap-3 py-2 text-xs"
            >
              <div className="min-w-0 flex-1">
                <span className="font-mono text-[var(--color-primary)]">{entry.toolId}</span>{' '}
                <span className="text-[var(--color-text-secondary)]">
                  · {entry.action}
                  {entry.trustGrade ? ` · ระดับความน่าเชื่อถือ ${entry.trustGrade}` : ''}
                </span>
              </div>
              <span className="shrink-0 font-mono text-[11px] text-[var(--color-text-secondary)]">{entry.outcome}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
