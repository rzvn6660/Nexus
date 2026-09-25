import React from 'react';
import { SearchCode, ShieldCheck } from 'lucide-react';

export interface SignalData {
  id: string;
  what: string;
  whyItMatters: string;
  severity?: 'critical' | 'warning' | 'info' | 'positive';
  category?: string;
  timestamp?: string;
  onInvestigate?: () => void;
  onViewEvidence?: () => void;
}

interface SignalRowProps {
  signal: SignalData;
  className?: string;
}

export const SignalRow: React.FC<SignalRowProps> = ({ signal, className = '' }) => {
  const getBadgeStyle = () => {
    switch (signal.severity) {
      case 'critical':
        return 'bg-rose-950/80 text-rose-300 border-rose-800/80';
      case 'warning':
        return 'bg-amber-950/80 text-amber-300 border-amber-800/80';
      case 'positive':
        return 'bg-emerald-950/80 text-emerald-300 border-emerald-800/80';
      default:
        return 'bg-cyan-950/80 text-cyan-300 border-cyan-800/80';
    }
  };

  return (
    <div
      className={`p-4 sm:p-5 rounded-2xl bg-surface/60 border border-surface-elevated hover:border-surface-highlight transition-all space-y-3 ${className}`}
    >
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
        <div className="space-y-1 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-[10px] font-mono uppercase px-2 py-0.5 rounded-full border ${getBadgeStyle()}`}>
              {signal.category || 'Observed Signal'}
            </span>
            {signal.timestamp && (
              <span className="text-[10px] font-mono text-slate-500">
                {signal.timestamp}
              </span>
            )}
          </div>

          {/* WHAT */}
          <h4 className="text-sm sm:text-base font-bold text-white font-sans pt-1">
            {signal.what}
          </h4>

          {/* WHY IT MATTERS */}
          <p className="text-xs sm:text-sm text-slate-300 font-sans leading-relaxed">
            {signal.whyItMatters}
          </p>
        </div>

        {/* INSPECT ACTIONS */}
        <div className="flex items-center gap-2 shrink-0 pt-1 sm:pt-0">
          {signal.onInvestigate && (
            <button
              onClick={signal.onInvestigate}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-cyan-950/90 hover:bg-cyan-900 border border-cyan-800/70 text-brand-cyan text-xs font-medium transition-all shadow-sm group"
            >
              <SearchCode className="w-3.5 h-3.5 group-hover:scale-110 transition-transform" />
              <span>Investigate</span>
            </button>
          )}

          {signal.onViewEvidence && (
            <button
              onClick={signal.onViewEvidence}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-surface-elevated hover:bg-surface-highlight border border-surface-highlight text-slate-300 hover:text-white text-xs font-medium transition-all"
            >
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>View Evidence</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
