import React from 'react';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

export interface MetricItem {
  label: string;
  value: string;
  change?: string;
  changeType?: 'positive' | 'negative' | 'neutral';
  annotation?: string;
  onClick?: () => void;
}

interface MetricStatementProps {
  title?: string;
  metrics: MetricItem[];
  className?: string;
}

export const MetricStatement: React.FC<MetricStatementProps> = ({
  title = 'CURRENT BUSINESS STATE',
  metrics,
  className = '',
}) => {
  return (
    <div className={`p-5 rounded-2xl bg-surface/70 border border-surface-elevated ${className}`}>
      {title && (
        <div className="text-[10px] font-mono tracking-widest text-slate-400 uppercase mb-4 flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-brand-cyan" />
          <span>{title}</span>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 divide-y sm:divide-y-0 sm:divide-x divide-surface-elevated">
        {metrics.map((m, idx) => {
          const isPos = m.changeType === 'positive';
          const isNeg = m.changeType === 'negative';

          return (
            <div
              key={idx}
              onClick={m.onClick}
              className={`pt-3 sm:pt-0 sm:px-5 first:pl-0 last:pr-0 space-y-1 ${
                m.onClick ? 'cursor-pointer group' : ''
              }`}
            >
              <div className="text-xs font-mono text-slate-400 group-hover:text-slate-200 transition-colors">
                {m.label}
              </div>

              <div className="flex items-baseline gap-2.5">
                <span className="text-2xl sm:text-3xl font-extrabold text-white font-mono tracking-tight group-hover:text-brand-cyan transition-colors">
                  {m.value}
                </span>

                {m.change && (
                  <span
                    className={`inline-flex items-center gap-0.5 text-xs font-mono font-semibold px-1.5 py-0.5 rounded ${
                      isPos
                        ? 'text-emerald-400 bg-emerald-950/70 border border-emerald-900/60'
                        : isNeg
                        ? 'text-rose-400 bg-rose-950/70 border border-rose-900/60'
                        : 'text-slate-400 bg-surface-elevated/70'
                    }`}
                  >
                    {isPos && <TrendingUp className="w-3 h-3" />}
                    {isNeg && <TrendingDown className="w-3 h-3" />}
                    {!isPos && !isNeg && <Minus className="w-3 h-3" />}
                    <span>{m.change}</span>
                  </span>
                )}
              </div>

              {m.annotation && (
                <p className="text-[11px] text-slate-400 font-sans truncate">
                  {m.annotation}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
