import { useId } from 'react';

interface ZyrquenEmblemProps {
  size?: number;
  className?: string;
  animated?: boolean;
  active?: boolean;
}

export function ZyrquenEmblem({
  size = 28,
  className = '',
  animated = true,
  active = false,
}: ZyrquenEmblemProps) {
  const uid = useId().replace(/:/g, '');
  const borderId = `zyrq-border-${uid}`;
  const strokeId = `zyrq-stroke-${uid}`;
  const pulseId = `zyrq-pulse-${uid}`;
  const glowId = `zyrq-glow-${uid}`;
  const orbitId = `zyrq-orbit-${uid}`;
  const orbitRevId = `zyrq-orbit-rev-${uid}`;
  const bloomId = `zyrq-bloom-${uid}`;
  const zPathId = `zyrq-path-${uid}`;

  const traceDur = active ? '0.95s' : '2.8s';
  const orbitDur = active ? '2.8s' : '11s';
  const orbitRevDur = active ? '4s' : '16s';
  const breatheDur = active ? '1.1s' : '3.6s';

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 36 36"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`zyrq-emblem-root ${active ? 'zyrq-emblem-active' : ''} ${className}`.trim()}
      data-animated={animated ? 'true' : 'false'}
      data-processing={active ? 'true' : 'false'}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={borderId} x1="2" y1="2" x2="34" y2="34" gradientUnits="userSpaceOnUse">
          <stop stopColor="#5865F2" stopOpacity="0.88" />
          <stop offset="0.5" stopColor="#21D4FD" stopOpacity="0.72" />
          <stop offset="1" stopColor="#B47AFF" stopOpacity="0.88" />
        </linearGradient>
        <linearGradient id={strokeId} x1="9" y1="9" x2="27" y2="27" gradientUnits="userSpaceOnUse">
          <stop stopColor="#21D4FD" />
          <stop offset="0.52" stopColor="#5865F2" />
          <stop offset="1" stopColor="#B47AFF" />
        </linearGradient>
        <linearGradient id={pulseId} x1="10" y1="11" x2="26" y2="25" gradientUnits="userSpaceOnUse">
          <stop stopColor="#21D4FD" />
          <stop offset="0.5" stopColor="#F4F7FF" />
          <stop offset="1" stopColor="#B47AFF" />
        </linearGradient>
        <radialGradient id={glowId} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#21D4FD" stopOpacity="0.42" />
          <stop offset="55%" stopColor="#5865F2" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#090E1F" stopOpacity="0" />
        </radialGradient>
        <linearGradient id={orbitId} x1="5" y1="5" x2="31" y2="31" gradientUnits="userSpaceOnUse">
          <stop stopColor="#21D4FD" stopOpacity="0.78" />
          <stop offset="0.5" stopColor="#5865F2" stopOpacity="0.12" />
          <stop offset="1" stopColor="#B47AFF" stopOpacity="0.78" />
        </linearGradient>
        <linearGradient id={orbitRevId} x1="31" y1="5" x2="5" y2="31" gradientUnits="userSpaceOnUse">
          <stop stopColor="#B47AFF" stopOpacity="0.56" />
          <stop offset="0.5" stopColor="#21D4FD" stopOpacity="0.08" />
          <stop offset="1" stopColor="#5865F2" stopOpacity="0.56" />
        </linearGradient>
        <filter id={bloomId} x="-35%" y="-35%" width="170%" height="170%">
          <feGaussianBlur stdDeviation="1.25" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <path id={zPathId} d="M11 11.5H25L11 24.5H25" />
      </defs>

      <rect
        x="1.5"
        y="1.5"
        width="33"
        height="33"
        rx="10"
        fill="#090E1F"
        stroke={`url(#${borderId})`}
        strokeWidth="1.4"
      />

      {animated && (
        <circle
          cx="18"
          cy="18"
          r="12.2"
          fill={`url(#${glowId})`}
          className="zyrq-emblem-core"
        >
          <animate attributeName="opacity" values="0.32;0.82;0.32" dur={breatheDur} repeatCount="indefinite" />
        </circle>
      )}

      {/* Minimalist Geometric Cognitive Core Lattice & Synaptic Spokes */}
      <polygon
        points="18,6.5 27.9,12.2 27.9,23.8 18,29.5 8.1,23.8 8.1,12.2"
        stroke="#38BDF8"
        strokeOpacity="0.22"
        strokeWidth="0.9"
        strokeLinejoin="round"
      />
      <g stroke="#22D3EE" strokeOpacity="0.24" strokeWidth="0.85" strokeLinecap="round">
        <line x1="18" y1="6.5" x2="18" y2="14.5" />
        <line x1="18" y1="21.5" x2="18" y2="29.5" />
        <line x1="8.1" y1="12.2" x2="14.6" y2="16" />
        <line x1="21.4" y1="20" x2="27.9" y2="23.8" />
      </g>

      {animated && (
        <>
          <circle
            cx="18"
            cy="18"
            r="13.6"
            stroke={`url(#${orbitId})`}
            strokeWidth="0.95"
            strokeDasharray="16 20 6 36"
            strokeLinecap="round"
            className="zyrq-emblem-orbit"
          >
            <animateTransform
              attributeName="transform"
              type="rotate"
              from="0 18 18"
              to="360 18 18"
              dur={orbitDur}
              repeatCount="indefinite"
            />
          </circle>
          <circle
            cx="18"
            cy="18"
            r="10.6"
            stroke={`url(#${orbitRevId})`}
            strokeWidth="0.75"
            strokeDasharray="10 24 4 26"
            strokeLinecap="round"
            className="zyrq-emblem-orbit-rev"
          >
            <animateTransform
              attributeName="transform"
              type="rotate"
              from="360 18 18"
              to="0 18 18"
              dur={orbitRevDur}
              repeatCount="indefinite"
            />
          </circle>
        </>
      )}

      {/* Central Cognitive Nucleus (Breathe) */}
      <circle
        cx="18"
        cy="18"
        r="2.1"
        fill="#22D3EE"
        fillOpacity="0.26"
        stroke="#38BDF8"
        strokeOpacity="0.65"
        strokeWidth="0.8"
        className="zyrq-emblem-nucleus"
      >
        {animated && (
          <animate attributeName="r" values="1.8;2.6;1.8" dur={breatheDur} repeatCount="indefinite" />
        )}
      </circle>

      {/* Soft neon glow aura under the Z */}
      <path
        d="M11 11.5H25L11 24.5H25"
        stroke={`url(#${strokeId})`}
        strokeWidth="3.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.2"
        filter={`url(#${bloomId})`}
      />

      {/* Crisp primary geometric Z-glyph */}
      <path
        d="M11 11.5H25L11 24.5H25"
        stroke={`url(#${strokeId})`}
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Luminous traveling plasma comet along the Z-path */}
      {animated && (
        <>
          <path
            d="M11 11.5H25L11 24.5H25"
            pathLength={60}
            stroke={`url(#${pulseId})`}
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeDasharray="14 46"
            filter={`url(#${bloomId})`}
            className="zyrq-emblem-trace"
          >
            <animate attributeName="stroke-dashoffset" from="60" to="0" dur={traceDur} repeatCount="indefinite" />
          </path>
          <circle r="1.35" fill="#ECFEFF" filter={`url(#${bloomId})`}>
            <animateMotion dur={traceDur} repeatCount="indefinite" rotate="auto">
              <mpath href={`#${zPathId}`} />
            </animateMotion>
            <animate attributeName="opacity" values="0.25;1;1;0.25" dur={traceDur} repeatCount="indefinite" />
          </circle>
        </>
      )}

      {/* Terminal node ripples */}
      {animated && (
        <>
          <circle
            cx="25"
            cy="11.5"
            r="2.0"
            stroke="#22D3EE"
            strokeWidth="0.95"
            className="zyrq-emblem-node-a"
          >
            <animate attributeName="r" values="1.9;3.9;1.9" dur={traceDur} repeatCount="indefinite" />
            <animate attributeName="opacity" values="0.82;0.08;0.82" dur={traceDur} repeatCount="indefinite" />
          </circle>
          <circle
            cx="11"
            cy="24.5"
            r="2.0"
            stroke="#A78BFA"
            strokeWidth="0.95"
            className="zyrq-emblem-node-b"
          >
            <animate attributeName="r" values="1.9;3.9;1.9" dur={traceDur} begin="0.45s" repeatCount="indefinite" />
            <animate attributeName="opacity" values="0.82;0.08;0.82" dur={traceDur} begin="0.45s" repeatCount="indefinite" />
          </circle>
        </>
      )}

      <circle cx="25" cy="11.5" r="1.95" fill="#22D3EE" />
      <circle cx="25" cy="11.5" r="0.8" fill="#ECFEFF" />
      <circle cx="11" cy="24.5" r="1.95" fill="#8B5CF6" />
      <circle cx="11" cy="24.5" r="0.8" fill="#EDE9FE" />
      <circle cx="18" cy="6.5" r="1.0" fill="#38BDF8" fillOpacity="0.75" />
      <circle cx="18" cy="29.5" r="1.0" fill="#A78BFA" fillOpacity="0.75" />
    </svg>
  );
}
