import React from 'react';
import { NexusSymbol } from './NexusSymbol';

interface NexusLogoProps {
  className?: string;
  symbolSize?: number;
  showTagline?: boolean;
  tagline?: string;
  collapsed?: boolean;
}

export const NexusLogo: React.FC<NexusLogoProps> = ({
  className = '',
  symbolSize = 32,
  showTagline = true,
  tagline = 'Intelligence Workspace',
  collapsed = false,
}) => {
  return (
    <div className={`flex items-center gap-3 select-none ${className}`}>
      <NexusSymbol size={symbolSize} />
      {!collapsed && (
        <div className="flex flex-col min-w-0">
          <span className="font-extrabold text-base tracking-[0.14em] text-white font-sans leading-none">
            NEXUS
          </span>
          {showTagline && (
            <span className="text-[9.5px] font-mono text-cyan-400 uppercase tracking-[0.2em] leading-normal mt-1 truncate">
              {tagline}
            </span>
          )}
        </div>
      )}
    </div>
  );
};
