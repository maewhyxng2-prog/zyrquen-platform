import React from 'react';
import { Download } from 'lucide-react';
import {
  copyTextToClipboard,
  parseMarkdownPipeTable,
  redactSensitiveData,
  sanitizeAssistantDisplayContent,
  serializeTableToTsv,
  toPlainAssistantCopyText,
} from '../lib/clipboard';
import { CopyButton } from './CopyButton';

export {
  copyTextToClipboard,
  redactSensitiveData,
  sanitizeAssistantDisplayContent,
  serializeTableToTsv,
  toPlainAssistantCopyText,
};

const CODE_EXTENSION_MAP: Record<string, string> = {
  python: 'py',
  py: 'py',
  typescript: 'ts',
  ts: 'ts',
  tsx: 'tsx',
  javascript: 'js',
  js: 'js',
  jsx: 'jsx',
  json: 'json',
  markdown: 'md',
  md: 'md',
  sql: 'sql',
  bash: 'sh',
  sh: 'sh',
  yaml: 'yml',
  yml: 'yml',
  html: 'html',
  css: 'css',
};

function downloadCodeSnippet(lang: string, code: string) {
  if (typeof document === 'undefined' || typeof URL === 'undefined') return;
  const ext = CODE_EXTENSION_MAP[lang.toLowerCase()] || 'txt';
  const blob = new Blob([code], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `zyrquen-snippet.${ext}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function isSafeHttpUrl(rawUrl: string): boolean {
  try {
    const parsed = new URL(rawUrl.trim());
    return parsed.protocol === 'https:' || parsed.protocol === 'http:';
  } catch {
    return false;
  }
}

function renderInlineSegments(line: string): React.ReactNode[] {
  const parts = line.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)\s]+\)|\*[^*]+\*)/g);
  return parts.map((part, idx) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return (
        <strong key={idx} className="font-semibold text-[var(--color-text)]">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return (
        <code
          key={idx}
          className="rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-1.5 py-0.5 font-mono text-[0.85em] text-[var(--color-accent)]"
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    const linkMatch = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
    if (linkMatch && isSafeHttpUrl(linkMatch[2])) {
      return (
        <a
          key={idx}
          href={linkMatch[2]}
          target="_blank"
          rel="noopener noreferrer"
          className="underline decoration-[var(--color-accent)]/60 underline-offset-2 text-[var(--color-accent)] hover:opacity-85"
        >
          {linkMatch[1]}
        </a>
      );
    }
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
      return (
        <em key={idx} className="italic text-[var(--color-text-secondary)]">
          {part.slice(1, -1)}
        </em>
      );
    }
    return <React.Fragment key={idx}>{part}</React.Fragment>;
  });
}

type MessageBlock =
  | { kind: 'code'; lang: string; code: string }
  | { kind: 'table'; headers: string[]; rows: string[][] }
  | { kind: 'spacer' }
  | { kind: 'divider' }
  | { kind: 'blockquote'; text: string }
  | { kind: 'bullet'; text: string }
  | { kind: 'numbered'; num: string; text: string }
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'paragraph'; text: string };

function parseMessageBlocks(sanitized: string): MessageBlock[] {
  const lines = sanitized.split('\n');
  const blocks: MessageBlock[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const fenceMatch = line.match(/^\s*```([a-zA-Z0-9_-]*)\s*$/);
    if (fenceMatch) {
      const lang = fenceMatch[1] || 'code';
      i += 1;
      const codeLines: string[] = [];
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
        codeLines.push(lines[i]);
        i += 1;
      }
      if (i < lines.length && /^\s*```\s*$/.test(lines[i])) {
        i += 1;
      }
      blocks.push({ kind: 'code', lang, code: codeLines.join('\n') });
      continue;
    }

    const table = parseMarkdownPipeTable(lines, i);
    if (table) {
      blocks.push({ kind: 'table', headers: table.headers, rows: table.rows });
      i = table.nextIndex;
      continue;
    }

    const trimmed = line.trim();
    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    const numberedMatch = trimmed.match(/^(\d+)\.\s+(.+)$/);

    if (!trimmed) {
      blocks.push({ kind: 'spacer' });
    } else if (/^[-*_]{3,}$/.test(trimmed)) {
      blocks.push({ kind: 'divider' });
    } else if (trimmed.startsWith('> ')) {
      blocks.push({ kind: 'blockquote', text: trimmed.slice(2) });
    } else if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      blocks.push({ kind: 'bullet', text: trimmed.slice(2) });
    } else if (numberedMatch) {
      blocks.push({ kind: 'numbered', num: numberedMatch[1], text: numberedMatch[2] });
    } else if (headingMatch) {
      blocks.push({ kind: 'heading', level: headingMatch[1].length, text: headingMatch[2] });
    } else {
      blocks.push({ kind: 'paragraph', text: line });
    }
    i += 1;
  }

  return blocks;
}

export const SafeMessageText = React.memo(function SafeMessageText({ content }: { content: string }) {
  const sanitized = sanitizeAssistantDisplayContent(content);
  const blocks = parseMessageBlocks(sanitized);

  return (
    <div className="min-w-0 space-y-2.5 break-words text-[15px] leading-relaxed text-[var(--color-text)]">
      {blocks.map((block, i) => {
        if (block.kind === 'spacer') {
          return <div key={i} className="h-1" />;
        }
        if (block.kind === 'divider') {
          return <hr key={i} className="my-2.5 border-[var(--color-border)]" />;
        }
        if (block.kind === 'code') {
          return (
            <div
              key={i}
              className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]"
            >
              <div className="flex items-center justify-between gap-2 border-b border-[var(--color-border)] bg-[var(--color-surface-raised)]/70 px-3 py-1.5">
                <span className="truncate font-mono text-[11px] font-medium text-[var(--color-text-secondary)]">
                  {block.lang}
                </span>
                <div className="flex shrink-0 items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => downloadCodeSnippet(block.lang, block.code)}
                    aria-label="ดาวน์โหลดไฟล์โค้ด"
                    title="ดาวน์โหลดไฟล์โค้ดนี้"
                    className="inline-flex min-h-[44px] sm:min-h-[32px] items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-focus)] whitespace-nowrap"
                  >
                    <Download className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                    <span className="hidden sm:inline">บันทึกไฟล์</span>
                  </button>
                  <CopyButton
                    getText={() => block.code}
                    label="คัดลอกโค้ด"
                    ariaLabel="คัดลอกโค้ด"
                    title="คัดลอกโค้ดทั้งหมดแบบไม่ติดเลขบรรทัด"
                    size="xs"
                  />
                </div>
              </div>
              <pre className="overflow-x-auto p-3.5 font-mono text-xs leading-relaxed text-[var(--color-text)]">
                <code>{block.code}</code>
              </pre>
            </div>
          );
        }
        if (block.kind === 'table') {
          return (
            <div
              key={i}
              className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]"
            >
              <div className="flex items-center justify-between gap-2 border-b border-[var(--color-border)] bg-[var(--color-surface-raised)]/70 px-3 py-1.5">
                <span className="text-[11px] font-medium text-[var(--color-text-secondary)] tabular-nums">
                  ตารางข้อมูล ({block.rows.length} แถว)
                </span>
                <CopyButton
                  getText={() => serializeTableToTsv(block.headers, block.rows)}
                  label="คัดลอกตาราง"
                  ariaLabel="คัดลอกตาราง"
                  title="คัดลอกตารางเป็นรูปแบบคั่นด้วยแท็บ (TSV)"
                  size="xs"
                />
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-[var(--color-border)] text-[var(--color-text-secondary)]">
                      {block.headers.map((h, colIdx) => (
                        <th key={colIdx} className="px-3 py-2 font-semibold whitespace-nowrap">
                          {renderInlineSegments(h)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--color-border)]">
                    {block.rows.map((row, rowIdx) => (
                      <tr key={rowIdx}>
                        {row.map((cell, colIdx) => (
                          <td key={colIdx} className="px-3 py-2 text-[var(--color-text)]">
                            {renderInlineSegments(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        }
        if (block.kind === 'blockquote') {
          return (
            <div
              key={i}
              className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-xs leading-relaxed text-[var(--color-accent)]"
            >
              {renderInlineSegments(block.text)}
            </div>
          );
        }
        if (block.kind === 'bullet') {
          return (
            <div key={i} className="flex items-start gap-2.5 pl-1">
              <span
                className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-accent)]"
                aria-hidden="true"
              />
              <span className="min-w-0 flex-1">{renderInlineSegments(block.text)}</span>
            </div>
          );
        }
        if (block.kind === 'numbered') {
          return (
            <div key={i} className="flex items-start gap-2.5 pl-1">
              <span className="mt-0.5 min-w-[1.25rem] shrink-0 text-right font-mono text-xs font-semibold text-[var(--color-accent)] tabular-nums">
                {block.num}.
              </span>
              <span className="min-w-0 flex-1">{renderInlineSegments(block.text)}</span>
            </div>
          );
        }
        if (block.kind === 'heading') {
          const sizeCls =
            block.level === 1
              ? 'text-base font-bold text-[var(--color-text)]'
              : block.level === 2
                ? 'pt-1 text-[15px] font-semibold text-[var(--color-accent)]'
                : 'font-semibold text-[var(--color-text)]';
          return (
            <p key={i} className={sizeCls}>
              {renderInlineSegments(block.text)}
            </p>
          );
        }
        return <p key={i}>{renderInlineSegments(block.text)}</p>;
      })}
    </div>
  );
});
