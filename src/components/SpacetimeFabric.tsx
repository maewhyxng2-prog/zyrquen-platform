import { useEffect, useId, useRef, useState } from 'react';

interface SpacetimeFabricProps {
  density?: 'minimal' | 'balanced' | 'expansive';
  className?: string;
}

export function SpacetimeFabric({
  density = 'balanced',
  className = '',
}: SpacetimeFabricProps) {
  const uid = useId().replace(/:/g, '');
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [offscreen, setOffscreen] = useState(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry) {
          setOffscreen(!entry.isIntersecting);
        }
      },
      { threshold: 0.01 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const auroraGradId = `zyrq-fabric-aurora-${uid}`;
  const gridFadeId = `zyrq-fabric-fade-${uid}`;
  const energyLineId = `zyrq-fabric-energy-${uid}`;

  const gridOpacity =
    density === 'expansive' ? 0.42 : density === 'balanced' ? 0.3 : 0.2;

  return (
    <div
      ref={containerRef}
      data-spacetime-fabric={density}
      data-offscreen={offscreen ? 'true' : 'false'}
      aria-hidden="true"
      className={`pointer-events-none select-none overflow-hidden ${className}`.trim()}
    >
      <svg
        viewBox="0 0 1200 640"
        preserveAspectRatio="xMidYMid slice"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="h-full w-full"
      >
        <defs>
          <radialGradient id={auroraGradId} cx="50%" cy="38%" r="60%">
            <stop offset="0%" stopColor="var(--zyrquen-cyan)" stopOpacity="0.22" />
            <stop offset="38%" stopColor="var(--zyrquen-blue)" stopOpacity="0.16" />
            <stop offset="72%" stopColor="var(--zyrquen-violet)" stopOpacity="0.1" />
            <stop offset="100%" stopColor="var(--color-bg)" stopOpacity="0" />
          </radialGradient>

          <linearGradient id={energyLineId} x1="0" y1="0" x2="1200" y2="640" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="var(--zyrquen-blue)" stopOpacity="0.7" />
            <stop offset="50%" stopColor="var(--zyrquen-cyan)" stopOpacity="0.85" />
            <stop offset="100%" stopColor="var(--zyrquen-violet)" stopOpacity="0.7" />
          </linearGradient>

          <radialGradient id={gridFadeId} cx="50%" cy="45%" r="54%">
            <stop offset="0%" stopColor="#FFFFFF" stopOpacity="1" />
            <stop offset="70%" stopColor="#FFFFFF" stopOpacity="0.45" />
            <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0" />
          </radialGradient>

          <mask id={`zyrq-mask-${uid}`}>
            <rect x="0" y="0" width="1200" height="640" fill={`url(#${gridFadeId})`} />
          </mask>
        </defs>

        {/* Aurora ambient depth */}
        <ellipse
          cx="600"
          cy="240"
          rx="520"
          ry="260"
          fill={`url(#${auroraGradId})`}
          className="zyrq-aurora-field"
          style={{ opacity: 'var(--aurora-halo-opacity)' }}
        />

        {/* Curved spacetime grid */}
        <g
          mask={`url(#zyrq-mask-${uid})`}
          className="zyrq-spacetime-warp"
          opacity={gridOpacity}
        >
          {/* Curved latitude geodesics */}
          <path d="M 40 120 Q 600 185 1160 120" stroke="var(--color-border)" strokeWidth="1" />
          <path d="M 0 200 Q 600 285 1200 200" stroke="var(--zyrquen-indigo)" strokeWidth="1" />
          <path d="M 0 290 Q 600 375 1200 290" stroke="var(--zyrquen-blue)" strokeOpacity="0.45" strokeWidth="1.1" />
          <path d="M 0 385 Q 600 455 1200 385" stroke="var(--zyrquen-indigo)" strokeWidth="1" />
          <path d="M 40 480 Q 600 535 1160 480" stroke="var(--color-border)" strokeWidth="1" />

          {density !== 'minimal' && (
            <>
              <path d="M 120 55 Q 600 105 1080 55" stroke="var(--color-border)" strokeWidth="0.85" />
              <path d="M 100 560 Q 600 595 1100 560" stroke="var(--color-border)" strokeWidth="0.85" />
            </>
          )}

          {/* Curved meridian geodesics */}
          <path d="M 210 10 Q 320 320 190 630" stroke="var(--color-border)" strokeWidth="0.9" />
          <path d="M 380 10 Q 455 320 370 630" stroke="var(--zyrquen-indigo)" strokeWidth="0.95" />
          <path d="M 600 0 L 600 640" stroke="var(--zyrquen-cyan)" strokeOpacity="0.28" strokeWidth="1" />
          <path d="M 820 10 Q 745 320 830 630" stroke="var(--zyrquen-indigo)" strokeWidth="0.95" />
          <path d="M 990 10 Q 880 320 1010 630" stroke="var(--color-border)" strokeWidth="0.9" />

          {/* Elliptical dimensional horizons */}
          <ellipse
            cx="600"
            cy="300"
            rx="240"
            ry="88"
            stroke={`url(#${energyLineId})`}
            strokeOpacity="0.35"
            strokeWidth="1"
            strokeDasharray="6 10"
          />
          {density === 'expansive' && (
            <ellipse
              cx="600"
              cy="300"
              rx="410"
              ry="155"
              stroke={`url(#${energyLineId})`}
              strokeOpacity="0.24"
              strokeWidth="1"
            />
          )}

          {/* Subtle energy pulse along spacetime horizon */}
          <path
            d="M 80 290 Q 600 375 1120 290"
            pathLength={240}
            stroke={`url(#${energyLineId})`}
            strokeWidth="1.4"
            strokeLinecap="round"
            className="zyrq-temporal-energy-path"
          />
        </g>
      </svg>
    </div>
  );
}
