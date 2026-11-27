"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Icon } from "./Icon";

export function MetricHelpTooltip({
  label,
  description,
}: {
  label: string;
  description: string;
}) {
  const [open, setOpen] = useState(false);
  const tooltipId = useId();
  const wrapperRef = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: MouseEvent | TouchEvent) => {
      if (
        wrapperRef.current &&
        !wrapperRef.current.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("touchstart", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("touchstart", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  return (
    <span
      className="metric-help-wrapper"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      ref={wrapperRef}
    >
      <button
        aria-describedby={open ? tooltipId : undefined}
        aria-expanded={open}
        aria-label={`คำอธิบายตัวชี้วัด ${label}`}
        className="metric-help-trigger"
        onBlur={(event) => {
          const next = event.relatedTarget as Node | null;
          if (!next || !wrapperRef.current?.contains(next)) {
            setOpen(false);
          }
        }}
        onClick={() => setOpen((prev) => !prev)}
        onFocus={() => setOpen(true)}
        type="button"
      >
        <Icon name="help" size={14} />
      </button>
      {open ? (
        <span className="metric-help-popover" id={tooltipId} role="tooltip">
          {description}
        </span>
      ) : null}
    </span>
  );
}
