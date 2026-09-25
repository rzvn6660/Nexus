import React from 'react';
import { NexusSymbol } from './NexusSymbol';

interface NexusLogoProps {
  className?: string;
  symbolSize?: number;
  showTagline?: boolean;
  collapsed?: boolean;
}

export const NexusLogo: React.FC<NexusLogoProps> = ({
  className = '',
  symbolSize = 32,
  showTagline = true,
  collapsed = false,
}) => {
  return (
    <div className={`flex items-center gap-3 select-none ${className}`}>
      <NexusSymbol size={symbolSize} />
      {!collapsed && (
        <div className="flex flex-col min-w-0">
          <span className="font-extrabold text-base tracking-wider text-white font-sans leading-none">
            NEXUS
          </span>
          {showTagline && (
            <span className="text-[10px] font-mono text-cyan-400 uppercase tracking-widest leading-normal mt-0.5 truncate">
              Intelligence Workspace
            </span>
          )}
        </div>
      )}
    </div>
  );
};
