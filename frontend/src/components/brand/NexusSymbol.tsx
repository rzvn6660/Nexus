import React from 'react';

export const BRAND_ASSET = '/brand/nexus-logo-bg.png';

export interface NexusSymbolProps {
  className?: string;
  size?: number | string;
  alt?: string;
  showBackdrop?: boolean;
}

/**
 * Official Canonical NEXUS Decision Core Symbol.
 * Single source of truth for the approved NEXUS mark.
 */
export const NexusSymbol: React.FC<NexusSymbolProps> = ({
  className = '',
  size = 32,
  alt = 'NEXUS',
}) => {
  const dimension = typeof size === 'number' ? `${size}px` : size;

  return (
    <img
      src={BRAND_ASSET}
      alt={alt}
      style={{ width: dimension, height: dimension }}
      className={`object-contain shrink-0 select-none ${className}`}
      draggable={false}
    />
  );
};
