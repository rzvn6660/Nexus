import React from 'react';
import { NexusSymbol } from './NexusSymbol';

export interface NexusLogoProps {
  className?: string;
  size?: number;
  imageSize?: number;
  symbolSize?: number;
  showTagline?: boolean;
  tagline?: string;
  collapsed?: boolean;
}

/**
 * Official NEXUS Brand Lockup: Canonical Symbol + Professional Wordmark.
 *
 * Implements architectural typography:
 * - Geometric sans-serif (Inter) with precision letter-spacing
 * - Deliberate symbol-to-wordmark proximity
 * - High-contrast, clean enterprise styling (no neon/gaming effects)
 * - Seamless collapsed state rendering the official mark
 */
export const NexusLogo: React.FC<NexusLogoProps> = ({
  className = '',
  size,
  imageSize = 34,
  symbolSize,
  showTagline = false,
  tagline,
  collapsed = false,
}) => {
  const markSize = size ?? symbolSize ?? imageSize;

  if (collapsed) {
    return (
      <div className={`flex items-center justify-center select-none ${className}`}>
        <NexusSymbol size={markSize} />
      </div>
    );
  }

  return (
    <div className={`flex items-center gap-2.5 select-none ${className}`}>
      <NexusSymbol size={markSize} />
      <div className="flex flex-col justify-center min-w-0">
        <span
          className="font-bold text-[15px] tracking-[0.24em] text-slate-100 font-sans uppercase leading-none select-none"
          style={{ letterSpacing: '0.24em' }}
        >
          NEXUS
        </span>
        {showTagline && tagline && (
          <span className="text-[9px] font-mono tracking-[0.16em] text-slate-400 uppercase leading-none mt-1 font-medium select-none truncate">
            {tagline}
          </span>
        )}
      </div>
    </div>
  );
};
