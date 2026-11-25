import { useEffect, useId, useRef, useState } from 'react';

interface TemporalIntelligenceCoreProps {
  size?: number;
  variant?: 'prominent' | 'compact' | 'ambient';
  active?: boolean;
  animated?: boolean;
  className?: string;
}

export function TemporalIntelligenceCore({
  size = 152,
  variant = 'prominent',
  active = false,
  animated = true,
  className = '',
}: TemporalIntelligenceCoreProps) {
  const uid = useId().replace(/:/g, '');
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const [offscreen, setOffscreen] = useState(false);

  useEffect(() => {
    const el = wrapperRef.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry) {
          setOffscreen(!entry.isIntersecting);
        }
      },
      { threshold: 0.02 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const auroraGradId = `zyrq-tcore-aurora-${uid}`;
  const ringGradA = `zyrq-tcore-ring-a-${uid}`;
  const ringGradB = `zyrq-tcore-ring-b-${uid}`;
  const coreGlowId = `zyrq-tcore-glow-${uid}`;
  const zPathId = `zyrq-tcore-z-${uid}`;
  const bloomId = `zyrq-tcore-bloom-${uid}`;

  const isProminent = variant === 'prominent';
  const showOuterLattice = variant !== 'ambient';

  return (
    <div
      ref={wrapperRef}
      data-temporal-core={variant}
      data-active={active ? 'true' : 'false'}
      data-offscreen={offscreen ? 'true' : 'false'}
      className={`relative inline-flex items-center justify-center ${
        active ? 'zyrq-temporal-active' : ''
      } ${className}`.trim()}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 220 220"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="h-full w-full overflow-visible"
      >
        <defs>
          <radialGradient id={coreGlowId} cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--zyrquen-cyan)" stopOpacity="0.45" />
            <stop offset="42%" stopColor="var(--zyrquen-blue)" stopOpacity="0.22" />
            <stop offset="76%" stopColor="var(--zyrquen-violet)" stopOpacity="0.1" />
            <stop offset="100%" stopColor="var(--color-bg)" stopOpacity="0" />
          </radialGradient>

          <linearGradient id={auroraGradId} x1="25" y1="25" x2="195" y2="195" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="var(--zyrquen-blue)" />
            <stop offset="50%" stopColor="var(--zyrquen-cyan)" />
            <stop offset="100%" stopColor="var(--zyrquen-violet)" />
          </linearGradient>

          <linearGradient id={ringGradA} x1="20" y1="110" x2="200" y2="110" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="var(--zyrquen-cyan)" stopOpacity="0.88" />
            <stop offset="50%" stopColor="var(--zyrquen-blue)" stopOpacity="0.15" />
            <stop offset="100%" stopColor="var(--zyrquen-violet)" stopOpacity="0.88" />
          </linearGradient>

          <linearGradient id={ringGradB} x1="110" y1="20" x2="110" y2="200" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="var(--zyrquen-violet)" stopOpacity="0.72" />
            <stop offset="50%" stopColor="var(--zyrquen-cyan)" stopOpacity="0.1" />
            <stop offset="100%" stopColor="var(--zyrquen-blue)" stopOpacity="0.75" />
          </linearGradient>

          <filter id={bloomId} x="-35%" y="-35%" width="170%" height="170%">
            <feGaussianBlur stdDeviation="2.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>

          <path id={zPathId} d="M90 92H130L90 128H130" />
        </defs>

        {/* Core Pulse halo */}
        <circle
          cx="110"
          cy="110"
          r="94"
          fill={`url(#${coreGlowId})`}
          className={animated ? 'zyrq-temporal-pulse' : ''}
        />

        {/* Local curved spacetime distortion grid around the core */}
        {showOuterLattice && (
          <g className={animated ? 'zyrq-spacetime-warp' : ''} opacity={isProminent ? 0.52 : 0.35}>
            <path
              d="M 16 74 Q 110 100 204 74"
              stroke="var(--color-border)"
              strokeWidth="0.9"
            />
            <path
              d="M 16 146 Q 110 120 204 146"
              stroke="var(--color-border)"
              strokeWidth="0.9"
            />
            <path
              d="M 74 16 Q 100 110 74 204"
              stroke="var(--color-border)"
              strokeWidth="0.9"
            />
            <path
              d="M 146 16 Q 120 110 146 204"
              stroke="var(--color-border)"
              strokeWidth="0.9"
            />
          </g>
        )}

        {/* Layered transparent holographic octagonal frame */}
        <polygon
          points="110,22 172,48 198,110 172,172 110,198 48,172 22,110 48,48"
          fill="var(--aurora-core-bg)"
          fillOpacity="0.48"
          stroke={`url(#${auroraGradId})`}
          strokeOpacity="0.28"
          strokeWidth="1"
        />

        {/* Outer Temporal Orbit Ring (CW) */}
        <g className={animated ? 'zyrq-temporal-ring-cw' : ''}>
          <circle
            cx="110"
            cy="110"
            r="84"
            stroke={`url(#${ringGradA})`}
            strokeWidth="1.4"
            strokeDasharray="56 18 14 26 42 24"
            strokeLinecap="round"
          />
          <circle cx="110" cy="26" r="2.4" fill="var(--zyrquen-cyan)" />
          <circle cx="110" cy="194" r="2.4" fill="var(--zyrquen-violet)" />
        </g>

        {/* Mid Elliptical Orbital Plane + Energy Flow */}
        <g transform="rotate(-24 110 110)">
          <ellipse
            cx="110"
            cy="110"
            rx="78"
            ry="34"
            stroke="var(--zyrquen-indigo)"
            strokeOpacity="0.65"
            strokeWidth="1.1"
          />
          <ellipse
            cx="110"
            cy="110"
            rx="78"
            ry="34"
            pathLength={240}
            stroke={`url(#${auroraGradId})`}
            strokeWidth="1.8"
            strokeLinecap="round"
            className={animated ? 'zyrq-temporal-energy-path' : ''}
          />
        </g>

        {/* Counter-tilted Elliptical Orbital Plane */}
        <g transform="rotate(24 110 110)">
          <ellipse
            cx="110"
            cy="110"
            rx="78"
            ry="34"
            stroke="var(--color-border)"
            strokeOpacity="0.7"
            strokeWidth="1"
          />
          <ellipse
            cx="110"
            cy="110"
            rx="78"
            ry="34"
            pathLength={240}
            stroke="var(--zyrquen-violet)"
            strokeOpacity="0.85"
            strokeWidth="1.5"
            strokeLinecap="round"
            className={animated ? 'zyrq-temporal-energy-path-slow' : ''}
          />
        </g>

        {/* Counter-rotating Dimensional Ring (CCW) */}
        <g className={animated ? 'zyrq-temporal-ring-ccw' : ''}>
          <circle
            cx="110"
            cy="110"
            r="64"
            stroke={`url(#${ringGradB})`}
            strokeWidth="1.35"
            strokeDasharray="34 20 12 22 48 18"
            strokeLinecap="round"
          />
          <polygon
            points="110,49 163,79.5 163,140.5 110,171 57,140.5 57,79.5"
            stroke="var(--zyrquen-cyan)"
            strokeOpacity="0.22"
            strokeWidth="0.9"
          />
        </g>

        {/* Controlled Particle Motion (4 deterministic orbital nodes) */}
        <g className={animated ? 'zyrq-temporal-particle-track-a' : ''}>
          <circle cx="110" cy="36" r="2.2" fill="var(--zyrquen-cyan)" filter={`url(#${bloomId})`} />
          <circle cx="110" cy="184" r="1.8" fill="var(--zyrquen-blue)" />
        </g>
        <g className={animated ? 'zyrq-temporal-particle-track-b' : ''}>
          <circle cx="54" cy="110" r="2" fill="var(--zyrquen-violet)" />
          <circle cx="166" cy="110" r="1.8" fill="var(--zyrquen-cyan)" />
        </g>

        {/* Inner Holographic Core Ring (CW) */}
        <circle
          cx="110"
          cy="110"
          r="42"
          fill="var(--aurora-core-bg)"
          fillOpacity="0.86"
          stroke={`url(#${auroraGradId})`}
          strokeWidth="1.5"
          strokeDasharray="24 8 8 8"
          className={animated ? 'zyrq-temporal-ring-inner' : ''}
        />

        {/* Central ZYRQUEN Geometric Lattice */}
        <path
          d="M90 92H130L90 128H130"
          stroke={`url(#${auroraGradId})`}
          strokeWidth="4.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity="0.24"
          filter={`url(#${bloomId})`}
        />
        <path
          d="M90 92H130L90 128H130"
          stroke={`url(#${auroraGradId})`}
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {animated && (
          <path
            d="M90 92H130L90 128H130"
            pathLength={60}
            stroke="#F4F7FF"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="zyrq-emblem-trace"
          />
        )}

        {/* Luminous Core Terminal Nodes */}
        <circle cx="130" cy="92" r="3" fill="var(--zyrquen-cyan)" />
        <circle cx="90" cy="128" r="3" fill="var(--zyrquen-violet)" />
      </svg>
    </div>
  );
}
