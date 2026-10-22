import React from 'react';
import { TrendingUp, TrendingDown, Minus, ArrowUpRight } from 'lucide-react';

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
  title,
  metrics,
  className = '',
}) => {
  return (
    <div className={`space-y-3 ${className}`}>
      {title && (
        <div className="text-[11px] font-semibold tracking-wider text-slate-400 uppercase font-sans flex items-center gap-2 px-1">
          <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-[0_0_6px_rgba(6,182,212,0.8)]" />
          <span>{title}</span>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {metrics.map((m, idx) => {
          const isPos = m.changeType === 'positive';
          const isNeg = m.changeType === 'negative';

          return (
            <div
              key={idx}
              onClick={m.onClick}
              className={`p-4 sm:p-5 rounded-2xl bg-surface/80 border border-surface-elevated/90 transition-all ${
                m.onClick
                  ? 'cursor-pointer hover:border-cyan-500/40 hover:bg-surface-elevated/70 hover:shadow-cyan-subtle group'
                  : ''
              }`}
            >
              <div className="flex items-center justify-between gap-2 mb-2">
                <div className="flex items-center gap-1.5 min-w-0">
                  <span className="text-xs font-medium text-slate-400 group-hover:text-slate-200 transition-colors font-sans truncate">
                    {m.label}
                  </span>
                  {m.onClick && (
                    <ArrowUpRight className="w-3 h-3 text-slate-500 opacity-0 group-hover:opacity-100 group-hover:text-cyan-400 transition-all transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5 shrink-0" />
                  )}
                </div>

                {m.change && (
                  <span
                    className={`inline-flex items-center gap-1 text-[11px] font-mono font-semibold px-2 py-0.5 rounded-full border ${
                      isPos
                        ? 'text-emerald-300 bg-emerald-950/60 border-emerald-800/80'
                        : isNeg
                        ? 'text-rose-300 bg-rose-950/60 border-rose-800/80'
                        : 'text-slate-300 bg-surface-elevated border-surface-highlight'
                    }`}
                  >
                    {isPos && <TrendingUp className="w-3 h-3 text-emerald-400" />}
                    {isNeg && <TrendingDown className="w-3 h-3 text-rose-400" />}
                    {!isPos && !isNeg && <Minus className="w-3 h-3 text-slate-400" />}
                    <span>{m.change}</span>
                  </span>
                )}
              </div>

              <div className="text-2xl sm:text-3xl font-bold text-white font-sans tracking-tight group-hover:text-cyan-300 transition-colors">
                {m.value}
              </div>

              {m.annotation && (
                <p className="text-xs text-slate-400 font-sans mt-2 line-clamp-1">
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
