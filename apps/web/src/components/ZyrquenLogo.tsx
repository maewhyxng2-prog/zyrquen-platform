"use client";

import { useId } from "react";

export const COGNITIVE_STATE_EVENT = "zyrquen:cognitive-state";

export type CognitiveStateDetail = {
  processing: boolean;
  phase?: string | null;
};

export function emitCognitiveState(
  processing: boolean,
  phase: string | null = null,
): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<CognitiveStateDetail>(COGNITIVE_STATE_EVENT, {
      detail: { processing, phase },
    }),
  );
}

type ZyrquenLogoProps = {
  size?: number;
  processing?: boolean;
  className?: string;
  decorative?: boolean;
  label?: string;
};

export function ZyrquenLogo({
  size = 32,
  processing = false,
  className = "",
  decorative = true,
  label = "ZYRQUEN Ω∞ Cognitive Core",
}: ZyrquenLogoProps) {
  const uid = useId().replace(/:/g, "");
  const ringId = `zq-ring-${uid}`;
  const surfaceId = `zq-surface-${uid}`;
  const nucleusId = `zq-nucleus-${uid}`;
  const glowId = `zq-glow-${uid}`;

  return (
    <svg
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : label}
      className={`zq-logo${processing ? " zq-logo-processing" : ""}${
        className ? ` ${className}` : ""
      }`}
      data-cognitive-state={processing ? "processing" : "idle"}
      height={size}
      role={decorative ? undefined : "img"}
      viewBox="0 0 64 64"
      width={size}
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id={ringId} x1="0%" x2="100%" y1="0%" y2="100%">
          <stop offset="0%" stopColor="#22d3ee" />
          <stop offset="50%" stopColor="#3b82f6" />
          <stop offset="100%" stopColor="#8b5cf6" />
        </linearGradient>
        <linearGradient id={surfaceId} x1="15%" x2="85%" y1="0%" y2="100%">
          <stop offset="0%" stopColor="#17223b" />
          <stop offset="55%" stopColor="#0f172a" />
          <stop offset="100%" stopColor="#070b18" />
        </linearGradient>
        <radialGradient cx="42%" cy="38%" id={nucleusId} r="65%">
          <stop offset="0%" stopColor="#eef2fa" />
          <stop offset="40%" stopColor="#22d3ee" />
          <stop offset="100%" stopColor="#3b82f6" />
        </radialGradient>
        <filter height="180%" id={glowId} width="180%" x="-40%" y="-40%">
          <feGaussianBlur result="blur" stdDeviation="1.8" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      <circle
        className="zq-aura-breathe"
        cx="32"
        cy="32"
        fill="none"
        r="28"
        stroke="#22d3ee"
        strokeOpacity="0.35"
        strokeWidth="1"
      />

      <g className="zq-orbit-outer">
        <circle
          cx="32"
          cy="32"
          fill="none"
          r="26"
          stroke={`url(#${ringId})`}
          strokeDasharray="44 12 10 12"
          strokeOpacity="0.52"
          strokeWidth="1.05"
        />
        <circle
          cx="32"
          cy="6"
          fill="#22d3ee"
          filter={`url(#${glowId})`}
          r="2.1"
        />
        <circle cx="54.5" cy="45" fill="#8b5cf6" r="1.6" />
      </g>

      <g className="zq-orbit-inner">
        <ellipse
          cx="32"
          cy="32"
          fill="none"
          rx="23.5"
          ry="12"
          stroke="#3b82f6"
          strokeOpacity="0.4"
          strokeWidth="0.9"
          transform="rotate(-30 32 32)"
        />
        <circle cx="52.3" cy="20.2" fill="#eef2fa" r="1.4" />
      </g>

      <polygon
        fill={`url(#${surfaceId})`}
        points="32,10 51,21 51,43 32,54 13,43 13,21"
        stroke={`url(#${ringId})`}
        strokeLinejoin="round"
        strokeWidth="1.5"
      />
      <polygon
        className="zq-data-trace"
        fill="none"
        points="32,10 51,21 51,43 32,54 13,43 13,21"
        stroke="#22d3ee"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeOpacity="0.92"
        strokeWidth="1.4"
      />

      <g
        stroke="#60a5fa"
        strokeLinecap="round"
        strokeOpacity="0.45"
        strokeWidth="0.9"
      >
        <line x1="32" x2="32" y1="14" y2="25.5" />
        <line x1="32" x2="32" y1="38.5" y2="50" />
        <line x1="16.4" x2="26.4" y1="23" y2="28.8" />
        <line x1="37.6" x2="47.6" y1="35.2" y2="41" />
        <line x1="47.6" x2="37.6" y1="23" y2="28.8" />
        <line x1="26.4" x2="16.4" y1="35.2" y2="41" />
      </g>

      <g className="zq-node-pulse" fill="#22d3ee">
        <circle cx="32" cy="14" r="1.35" />
        <circle cx="47.6" cy="23" r="1.35" />
        <circle cx="47.6" cy="41" r="1.35" />
        <circle cx="32" cy="50" r="1.35" />
        <circle cx="16.4" cy="41" r="1.35" />
        <circle cx="16.4" cy="23" r="1.35" />
      </g>

      <g className="zq-core-breathe" filter={`url(#${glowId})`}>
        <path
          d="M23.5 32c0-3 2.3-4.8 4.6-4.8 2.6 0 3.9 2.4 3.9 4.8s1.3 4.8 3.9 4.8c2.3 0 4.6-1.8 4.6-4.8s-2.3-4.8-4.6-4.8c-2.6 0-3.9 2.4-3.9 4.8s-1.3 4.8-3.9 4.8c-2.3 0-4.6-1.8-4.6-4.8Z"
          fill="none"
          stroke={`url(#${ringId})`}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="1.9"
        />
        <circle cx="32" cy="32" fill={`url(#${nucleusId})`} r="3" />
        <circle cx="32" cy="32" fill="#eef2fa" r="1.2" />
      </g>
    </svg>
  );
}
