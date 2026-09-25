import React from 'react';

interface NexusSymbolProps {
  className?: string;
  size?: number | string;
  showBackdrop?: boolean;
}

export const NexusSymbol: React.FC<NexusSymbolProps> = ({
  className = '',
  size = 32,
  showBackdrop = true,
}) => {
  const id = React.useId().replace(/:/g, '');

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 256 256"
      width={size}
      height={size}
      className={`shrink-0 ${className}`}
      aria-label="NEXUS Decision Core Symbol"
    >
      <defs>
        <radialGradient id={`bg-glow-${id}`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#0f172a" />
          <stop offset="100%" stopColor="#060911" />
        </radialGradient>

        <linearGradient id={`left-rail-${id}`} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#38bdf8" />
          <stop offset="100%" stopColor="#0284c7" />
        </linearGradient>

        <linearGradient id={`diagonal-${id}`} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#38bdf8" />
          <stop offset="50%" stopColor="#ffffff" />
          <stop offset="100%" stopColor="#6366f1" />
        </linearGradient>

        <linearGradient id={`right-rail-${id}`} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#0284c7" />
          <stop offset="100%" stopColor="#4f46e5" />
        </linearGradient>

        <filter id={`core-glow-${id}`} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="8" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {showBackdrop && (
        <rect width="256" height="256" rx="48" fill={`url(#bg-glow-${id})`} />
      )}

      {/* Subtle Precision Framing Grid */}
      <circle
        cx="128"
        cy="128"
        r="88"
        fill="none"
        stroke="#1e293b"
        strokeWidth="1.5"
        strokeDasharray="4 8"
        opacity="0.6"
      />

      {/* Connecting Vector Pathways (Architectural 'N' & Convergence) */}
      <g strokeLinecap="round" strokeLinejoin="round">
        <line
          x1="68"
          y1="64"
          x2="68"
          y2="192"
          stroke={`url(#left-rail-${id})`}
          strokeWidth="18"
        />
        <line
          x1="188"
          y1="64"
          x2="188"
          y2="192"
          stroke={`url(#right-rail-${id})`}
          strokeWidth="18"
        />
        <line
          x1="68"
          y1="64"
          x2="188"
          y2="192"
          stroke={`url(#diagonal-${id})`}
          strokeWidth="18"
        />
      </g>

      {/* Peripheral Evidence Anchors */}
      <circle cx="68" cy="64" r="8" fill="#38bdf8" />
      <circle cx="68" cy="192" r="8" fill="#0284c7" />
      <circle cx="188" cy="64" r="8" fill="#0284c7" />
      <circle cx="188" cy="192" r="8" fill="#4f46e5" />

      {/* Central Nexus Core (The Decision Node) */}
      <g filter={`url(#core-glow-${id})`}>
        <polygon points="128,104 152,128 128,152 104,128" fill="#00f2fe" opacity="0.4" />
        <polygon points="128,110 146,128 128,146 110,128" fill="#ffffff" />
      </g>
    </svg>
  );
};
