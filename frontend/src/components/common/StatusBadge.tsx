import React from 'react';
import { CheckCircle2, AlertTriangle, XCircle, Info, ShieldAlert } from 'lucide-react';

interface StatusBadgeProps {
  status: string;
  size?: 'sm' | 'md';
  className?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  status,
  size = 'md',
  className = '',
}) => {
  const norm = status.toUpperCase().trim();

  let colorClasses = 'bg-slate-800 text-slate-300 border-slate-700';
  let Icon = Info;
  let label = status;

  switch (norm) {
    case 'READY':
    case 'PASSED':
    case 'HEALTHY':
    case 'CONNECTED':
    case 'COMPLETED':
      colorClasses = 'bg-emerald-950/60 text-emerald-300 border-emerald-800/80';
      Icon = CheckCircle2;
      label = norm === 'READY' ? 'Data Quality: Ready' : status;
      break;

    case 'READY_WITH_WARNINGS':
    case 'WARNING':
    case 'DEGRADED':
      colorClasses = 'bg-amber-950/60 text-amber-300 border-amber-800/80';
      Icon = AlertTriangle;
      label = norm === 'READY_WITH_WARNINGS' ? 'Ready with Warnings' : status;
      break;

    case 'INSUFFICIENT_DATA':
      colorClasses = 'bg-sky-950/60 text-sky-300 border-sky-800/80';
      Icon = ShieldAlert;
      label = 'Insufficient Historical Data';
      break;

    case 'INVALID':
    case 'FAILED':
    case 'ERROR':
    case 'DISCONNECTED':
      colorClasses = 'bg-rose-950/60 text-rose-300 border-rose-800/80';
      Icon = XCircle;
      label = status;
      break;

    default:
      break;
  }

  const padding = size === 'sm' ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-xs';

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-mono font-medium ${padding} ${colorClasses} ${className}`}
    >
      <Icon className={size === 'sm' ? 'w-3 h-3' : 'w-3.5 h-3.5'} />
      <span>{label}</span>
    </span>
  );
};
