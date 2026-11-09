import React from 'react';
import { ShieldCheck, ShieldAlert } from 'lucide-react';
import { CadenceSafetyVerdict } from '../../types/api';

interface CadenceSafetyBadgeProps {
  verdict: CadenceSafetyVerdict;
  className?: string;
}

export const CadenceSafetyBadge: React.FC<CadenceSafetyBadgeProps> = ({
  verdict,
  className = '',
}) => {
  if (!verdict) return null;

  if (verdict.is_actionable) {
    return (
      <div
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-emerald-950/60 text-emerald-300 border border-emerald-500/30 ${className}`}
        title={`Verified Actionable: Complete through ${verdict.effective_complete_through_dt || 'verified watermark'}`}
      >
        <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
        <span>Verified Actionable</span>
      </div>
    );
  }

  return (
    <div
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-amber-950/60 text-amber-300 border border-amber-500/30 ${className}`}
      title={verdict.explanation}
    >
      <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
      <span>Diagnostic Telemetry Only ({verdict.reason_code})</span>
    </div>
  );
};
