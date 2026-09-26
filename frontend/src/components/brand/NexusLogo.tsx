import React from 'react';
import { NexusSymbol } from './NexusSymbol';

interface NexusLogoProps {
  className?: string;
  imageSize?: number;
  symbolSize?: number;
  showTagline?: boolean;
  tagline?: string;
  collapsed?: boolean;
}

export const NexusLogo: React.FC<NexusLogoProps> = ({
  className = '',
  imageSize = 42,
  symbolSize,
  showTagline = true,
  tagline = 'Intelligence Workspace',
  collapsed = false,
}) => {
  const size = symbolSize ?? imageSize;

  if (collapsed) {
    return (
      <div className={`flex items-center justify-center select-none ${className}`}>
        <NexusSymbol size={34} />
      </div>
    );
  }

  return (
    <div className={`flex items-center gap-3 select-none ${className}`}>
      <div className="relative shrink-0 flex items-center justify-center">
        <img
          src="/brand/nexus-logo-bg.png"
          alt="NEXUS"
          style={{ width: `${size}px`, height: `${size}px` }}
          className="object-contain shrink-0 select-none"
          draggable={false}
        />
      </div>
      <div className="flex flex-col min-w-0 justify-center">
        <span className="font-extrabold text-base tracking-[0.14em] text-white font-sans leading-none">
          NEXUS
        </span>
        {showTagline && (
          <span className="text-[9.5px] font-mono text-cyan-400 uppercase tracking-[0.2em] leading-normal mt-1 truncate">
            {tagline}
          </span>
        )}
      </div>
    </div>
  );
};
