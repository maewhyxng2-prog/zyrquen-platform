import React, { useEffect, useRef, useState } from 'react';
import { Check, Copy } from 'lucide-react';
import { copyTextToClipboard } from '../lib/clipboard';

interface CopyButtonProps {
  text?: string;
  getText?: () => string;
  label?: string;
  copiedLabel?: string;
  ariaLabel?: string;
  title?: string;
  size?: 'sm' | 'xs';
  hideLabelOnMobile?: boolean;
  stopPropagation?: boolean;
  className?: string;
  onCopyResult?: (result: { ok: boolean; error?: string }) => void;
}

export function CopyButton({
  text,
  getText,
  label = 'คัดลอก',
  copiedLabel = 'คัดลอกแล้ว',
  ariaLabel,
  title,
  size = 'sm',
  hideLabelOnMobile = false,
  stopPropagation = false,
  className = '',
  onCopyResult,
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
      }
    };
  }, []);

  async function handleCopy(e: React.MouseEvent<HTMLButtonElement>) {
    if (stopPropagation) {
      e.preventDefault();
      e.stopPropagation();
    }
    const payload = getText ? getText() : text ?? '';
    const result = await copyTextToClipboard(payload);
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
    }
    if (result.ok) {
      setErrorMsg(null);
      setCopied(true);
      timerRef.current = window.setTimeout(() => {
        setCopied(false);
      }, 2000);
    } else {
      setCopied(false);
      setErrorMsg(result.error || 'คัดลอกไม่สำเร็จ (กรุณาคัดลอกด้วยตนเอง)');
      timerRef.current = window.setTimeout(() => {
        setErrorMsg(null);
      }, 3000);
    }
    onCopyResult?.(result);
  }

  const sizeClass =
    size === 'xs'
      ? 'min-h-[44px] min-w-[44px] sm:min-h-[32px] sm:min-w-[36px] px-2.5 py-1 text-[11px]'
      : 'min-h-[44px] min-w-[44px] sm:min-h-[36px] px-3 py-1 text-xs';

  const resolvedAriaLabel = ariaLabel || label;
  const resolvedTitle = title || resolvedAriaLabel;

  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <button
        type="button"
        onClick={(e) => void handleCopy(e)}
        aria-label={resolvedAriaLabel}
        title={resolvedTitle}
        className={`inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] font-medium text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-focus)] ${sizeClass} ${className}`}
      >
        {copied ? (
          <>
            <Check className="h-3.5 w-3.5 shrink-0 text-[var(--color-accent)]" aria-hidden="true" />
            <span className="text-[var(--color-accent)]">{copiedLabel}</span>
          </>
        ) : (
          <>
            <Copy className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span className={hideLabelOnMobile ? 'hidden sm:inline' : ''}>{label}</span>
          </>
        )}
      </button>
      {errorMsg && (
        <span role="status" className="text-[11px] text-[var(--color-warning)]">
          {errorMsg}
        </span>
      )}
    </span>
  );
}
