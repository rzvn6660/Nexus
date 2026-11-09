import React from 'react';
import { AlertTriangle, Info } from 'lucide-react';
import { SeasonalCautionDisclosure } from '../../types/api';

interface SeasonalCautionBannerProps {
  disclosure: SeasonalCautionDisclosure;
  compact?: boolean;
  className?: string;
}

export const SeasonalCautionBanner: React.FC<SeasonalCautionBannerProps> = ({
  disclosure,
  compact = false,
  className = '',
}) => {
  if (!disclosure || !disclosure.has_seasonal_caution) {
    return null;
  }

  const isConfirmed = disclosure.context_type === 'confirmed_seasonal';

  return (
    <div
      role="region"
      aria-label="Seasonal Context Advisory"
      className={`rounded-lg border p-4 ${
        isConfirmed
          ? 'bg-amber-950/40 border-amber-500/40 text-amber-200'
          : 'bg-slate-900/60 border-cyan-500/30 text-cyan-200'
      } ${className}`}
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 shrink-0">
          {isConfirmed ? (
            <AlertTriangle className="w-5 h-5 text-amber-400" aria-hidden="true" />
          ) : (
            <Info className="w-5 h-5 text-cyan-400" aria-hidden="true" />
          )}
        </div>
        <div className="space-y-1.5 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-sm tracking-wide">
              {disclosure.caution_title || (isConfirmed ? 'Seasonal Inactivity Caution' : 'Uncharacterized Seasonality Advisory')}
            </span>
            <span
              className={`text-[10px] uppercase font-mono px-2 py-0.5 rounded ${
                isConfirmed
                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                  : 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30'
              }`}
            >
              {isConfirmed ? 'Confirmed Seasonal Context' : 'Cautionary Disclosure'}
            </span>
          </div>

          <p className="text-xs leading-relaxed opacity-90">
            {disclosure.caution_message ||
              'Extended purchasing intervals may reflect expected seasonal pauses rather than customer attrition. Do not treat dormancy as definitive churn.'}
          </p>

          {!compact && (
            <div className="pt-1 border-t border-white/10 text-[11px] opacity-80 flex flex-wrap gap-x-4 gap-y-1">
              <span>⚠️ Normal seasonal dormancy naturally resembles churn.</span>
              <span>🔒 Individual customers are never classified as seasonal without verified order evidence.</span>
              <span>👤 All customer interventions require mandatory human review.</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
