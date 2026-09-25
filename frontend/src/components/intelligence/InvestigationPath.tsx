import React from 'react';
import {
  CheckCircle2,
  XCircle,
  HelpCircle,
  GitBranch,
} from 'lucide-react';
import { InvestigationObservation, InvestigationHypothesis } from '../../types/api';

interface InvestigationPathProps {
  rootSymptom: string;
  observations: InvestigationObservation[];
  hypotheses: InvestigationHypothesis[];
  onSelectHypothesis?: (hypothesis: InvestigationHypothesis) => void;
  className?: string;
}

export const InvestigationPath: React.FC<InvestigationPathProps> = ({
  rootSymptom,
  observations,
  hypotheses,
  onSelectHypothesis,
  className = '',
}) => {
  return (
    <div className={`p-6 rounded-3xl bg-void-sub border border-surface-elevated space-y-6 ${className}`}>
      {/* Root Node: The Observed Anomaly / Symptom */}
      <div className="flex items-start gap-3 pb-2 border-b border-surface-elevated">
        <div className="w-9 h-9 rounded-xl bg-cyan-950/80 border border-brand-cyan/40 flex items-center justify-center text-brand-cyan shrink-0">
          <GitBranch className="w-5 h-5" />
        </div>
        <div>
          <span className="text-[10px] font-mono uppercase tracking-widest text-brand-cyan font-semibold block">
            Diagnostic Starting Point
          </span>
          <h3 className="text-base font-bold text-white font-sans">
            {rootSymptom || 'Observed Variance Anomaly'}
          </h3>
        </div>
      </div>

      {/* Visual Diagnostic Decomposition Tree */}
      <div className="relative pl-6 sm:pl-8 space-y-6 before:absolute before:left-3 before:top-2 before:bottom-2 before:w-0.5 before:bg-surface-highlight">
        {/* Stage 1: Empirical Fact Observations */}
        <div className="relative space-y-3">
          <div className="flex items-center gap-2 -ml-6 sm:-ml-8">
            <span className="w-6 h-6 rounded-full bg-emerald-950 border border-emerald-500 text-emerald-400 flex items-center justify-center text-[10px] font-mono font-bold">
              1
            </span>
            <span className="text-xs font-mono uppercase text-emerald-400 font-semibold tracking-wider">
              Observed Empirical Signals ({observations.length})
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pl-2">
            {observations.map((obs) => (
              <div
                key={obs.observation_id}
                className="p-3.5 rounded-xl bg-surface/70 border border-surface-elevated text-xs space-y-1.5"
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-slate-200 capitalize font-sans">{obs.metric}</span>
                  <span
                    className={`font-mono text-[11px] px-2 py-0.5 rounded font-semibold ${
                      obs.variance_pct < 0
                        ? 'bg-rose-950/70 text-rose-300 border border-rose-900/60'
                        : 'bg-emerald-950/70 text-emerald-300 border border-emerald-900/60'
                    }`}
                  >
                    {obs.variance_pct >= 0 ? '+' : ''}
                    {obs.variance_pct?.toFixed(1)}%
                  </span>
                </div>
                <p className="text-slate-400 text-[11px] leading-relaxed font-sans">{obs.finding}</p>
                <div className="text-[10px] font-mono text-slate-500 pt-0.5">
                  Observed: {obs.observed_value?.toLocaleString()} • Baseline: {obs.baseline_value?.toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Stage 2: Tested Hypotheses Tournament */}
        <div className="relative space-y-3 pt-2">
          <div className="flex items-center gap-2 -ml-6 sm:-ml-8">
            <span className="w-6 h-6 rounded-full bg-cyan-950 border border-brand-cyan text-brand-cyan flex items-center justify-center text-[10px] font-mono font-bold">
              2
            </span>
            <span className="text-xs font-mono uppercase text-brand-cyan font-semibold tracking-wider">
              Tested Driver Hypotheses ({hypotheses.length})
            </span>
          </div>

          <div className="space-y-3 pl-2">
            {hypotheses.map((hyp) => {
              const isConfirmed = hyp.status === 'confirmed';
              const isRejected = hyp.status === 'rejected';

              return (
                <div
                  key={hyp.hypothesis_id}
                  onClick={() => onSelectHypothesis?.(hyp)}
                  className={`p-4 rounded-xl border transition-all ${
                    isConfirmed
                      ? 'bg-cyan-950/30 border-cyan-800/80 hover:border-cyan-600'
                      : isRejected
                      ? 'bg-surface/40 border-surface-elevated opacity-70 hover:opacity-100'
                      : 'bg-surface/70 border-surface-elevated'
                  } ${onSelectHypothesis ? 'cursor-pointer' : ''}`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="space-y-1 flex-1">
                      <div className="flex items-center gap-2">
                        {isConfirmed && <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />}
                        {isRejected && <XCircle className="w-4 h-4 text-rose-400 shrink-0" />}
                        {!isConfirmed && !isRejected && <HelpCircle className="w-4 h-4 text-amber-400 shrink-0" />}

                        <h4 className="text-xs sm:text-sm font-semibold text-slate-100 font-sans">
                          {hyp.statement}
                        </h4>
                      </div>

                      <p className="text-xs text-slate-300 leading-relaxed font-sans pl-6">
                        {hyp.evidence_summary}
                      </p>
                    </div>

                    <div className="text-right shrink-0">
                      <span
                        className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-mono uppercase font-semibold ${
                          isConfirmed
                            ? 'bg-emerald-950/80 text-emerald-300 border border-emerald-800'
                            : isRejected
                            ? 'bg-rose-950/80 text-rose-300 border border-rose-800'
                            : 'bg-slate-800 text-slate-300 border border-slate-700'
                        }`}
                      >
                        {hyp.status}
                      </span>

                      <div className="text-[10px] font-mono text-slate-400 pt-1">
                        Confidence: {(hyp.confidence * 100).toFixed(0)}%
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
