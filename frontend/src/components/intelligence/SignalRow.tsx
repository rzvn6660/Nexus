import React from 'react';
import { SearchCode, ShieldCheck, AlertCircle, TrendingUp, AlertTriangle, Info } from 'lucide-react';

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
  const getSeverityConfig = () => {
    switch (signal.severity) {
      case 'critical':
        return {
          badge: 'bg-rose-950/60 text-rose-300 border-rose-800/80',
          icon: AlertCircle,
          iconColor: 'text-rose-400',
        };
      case 'warning':
        return {
          badge: 'bg-amber-950/60 text-amber-300 border-amber-800/80',
          icon: AlertTriangle,
          iconColor: 'text-amber-400',
        };
      case 'positive':
        return {
          badge: 'bg-emerald-950/60 text-emerald-300 border-emerald-800/80',
          icon: TrendingUp,
          iconColor: 'text-emerald-400',
        };
      default:
        return {
          badge: 'bg-cyan-950/60 text-cyan-300 border-cyan-800/80',
          icon: Info,
          iconColor: 'text-cyan-400',
        };
    }
  };

  const config = getSeverityConfig();
  const IconComponent = config.icon;

  return (
    <div
      className={`p-4 sm:p-5 rounded-2xl bg-surface/70 border border-surface-elevated/80 hover:border-surface-highlight hover:bg-surface/90 transition-all space-y-3 ${className}`}
    >
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
        <div className="space-y-1.5 flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`inline-flex items-center gap-1 text-[10px] font-sans font-semibold uppercase px-2.5 py-0.5 rounded-full border ${config.badge}`}>
              <IconComponent className={`w-3 h-3 ${config.iconColor}`} />
              <span>{signal.category || 'Empirical Signal'}</span>
            </span>
            {signal.timestamp && (
              <span className="text-[10px] font-mono text-slate-500">
                {signal.timestamp}
              </span>
            )}
            <span className="text-[10px] font-sans text-slate-400">
              • Verified Database Signal
            </span>
          </div>

          {/* WHAT CHANGED */}
          <h4 className="text-sm sm:text-base font-semibold text-white font-sans pt-0.5 leading-snug">
            {signal.what}
          </h4>

          {/* WHY IT MATTERS */}
          <p className="text-xs text-slate-300 font-sans leading-relaxed">
            {signal.whyItMatters}
          </p>
        </div>

        {/* ACTIONS */}
        <div className="flex items-center gap-2 shrink-0 pt-1 sm:pt-0">
          {signal.onInvestigate && (
            <button
              onClick={signal.onInvestigate}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-cyan-950/80 hover:bg-cyan-900 border border-cyan-500/30 text-cyan-300 hover:text-white text-xs font-semibold transition-all shadow-sm group"
              title="Decompose variance drivers in diagnostic root-cause engine"
            >
              <SearchCode className="w-3.5 h-3.5 group-hover:scale-110 transition-transform text-cyan-400" />
              <span>Investigate</span>
            </button>
          )}

          {signal.onViewEvidence && (
            <button
              onClick={signal.onViewEvidence}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-surface hover:bg-surface-elevated border border-surface-elevated text-slate-300 hover:text-white text-xs font-medium transition-all"
              title="Inspect calculation lineage and SQL tables"
            >
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>Evidence</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
