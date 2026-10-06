import React from 'react';
import {
  CheckCircle2,
  XCircle,
  HelpCircle,
  GitBranch,
  AlertTriangle,
} from 'lucide-react';
import { InvestigationObservation, InvestigationHypothesis } from '../../types/api';

interface InvestigationPathProps {
  rootSymptom: string;
  observations: InvestigationObservation[];
  hypotheses: InvestigationHypothesis[];
  onSelectHypothesis?: (hypothesis: InvestigationHypothesis) => void;
  className?: string;
}

export const formatMetricLabel = (metric?: string | null): string => {
  if (!metric) return 'Diagnostic Metric';
  const lower = metric.toLowerCase();
  if (lower === 'net_sales') return 'Net Sales (Revenue)';
  if (lower === 'price_volume_mix') return 'Price / Volume / Mix (PVM)';
  if (lower.startsWith('variance_')) {
    const dim = lower.replace('variance_', '');
    return `${dim.charAt(0).toUpperCase() + dim.slice(1)} Variance`;
  }
  return metric.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
};

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
            {observations.map((obs, idx) => {
              const obsId = obs.observation_id || (obs as any).id || `obs-${idx}`;
              const metricLabel = formatMetricLabel(obs.metric);
              const statement = obs.finding || (obs as any).statement || '';

              const obsVal =
                obs.observed_value !== undefined && obs.observed_value !== null
                  ? obs.observed_value
                  : (obs as any).value_current;
              const baseVal =
                obs.baseline_value !== undefined && obs.baseline_value !== null
                  ? obs.baseline_value
                  : (obs as any).value_baseline;
              const variancePct =
                obs.variance_pct !== undefined && obs.variance_pct !== null
                  ? obs.variance_pct
                  : (obs as any).change_pct;

              const isTelemetryUnavailable =
                obsVal === null ||
                obsVal === undefined ||
                obsVal === '-' ||
                obsVal === '' ||
                statement.toLowerCase().includes('unavailable') ||
                statement.toLowerCase().includes('lacks required') ||
                statement.toLowerCase().includes('line-item');

              const hasValidVariance =
                !isTelemetryUnavailable &&
                typeof variancePct === 'number' &&
                !isNaN(variancePct);

              return (
                <div
                  key={obsId}
                  className="p-3.5 rounded-xl bg-surface/70 border border-surface-elevated text-xs space-y-1.5"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-slate-200 capitalize font-sans">{metricLabel}</span>
                    {hasValidVariance ? (
                      <span
                        className={`font-mono text-[11px] px-2 py-0.5 rounded font-semibold ${
                          variancePct < 0
                            ? 'bg-rose-950/70 text-rose-300 border border-rose-900/60'
                            : 'bg-emerald-950/70 text-emerald-300 border border-emerald-900/60'
                        }`}
                      >
                        {variancePct >= 0 ? '+' : ''}
                        {variancePct.toFixed(1)}%
                      </span>
                    ) : isTelemetryUnavailable ? (
                      <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-amber-950/70 text-amber-300 border border-amber-900/60 font-semibold">
                        Telemetry Unavailable
                      </span>
                    ) : (
                      <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
                        Single Period
                      </span>
                    )}
                  </div>
                  <p className="text-slate-400 text-[11px] leading-relaxed font-sans">{statement}</p>
                  {isTelemetryUnavailable ? (
                    <div className="text-[10px] font-mono text-amber-400/90 pt-0.5 flex items-center gap-1.5">
                      <AlertTriangle className="w-3 h-3 text-amber-400 shrink-0" />
                      <span>Unavailable — line-item/product data required</span>
                    </div>
                  ) : (
                    <div className="text-[10px] font-mono text-slate-500 pt-0.5">
                      Observed: {typeof obsVal === 'number' ? obsVal.toLocaleString() : (obsVal && obsVal !== '-' ? String(obsVal) : 'Unavailable')} • Baseline:{' '}
                      {typeof baseVal === 'number' ? baseVal.toLocaleString() : (baseVal && baseVal !== '-' ? String(baseVal) : 'Single period baseline')}
                    </div>
                  )}
                </div>
              );
            })}
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
            {hypotheses.map((hyp, idx) => {
              const hypId = hyp.hypothesis_id || (hyp as any).id || `hyp-${idx}`;
              const rawStatus = (hyp.status || '').toUpperCase();
              const isConfirmed = rawStatus === 'CONFIRMED' || rawStatus === 'SUPPORTED';
              const isPartiallySupported = rawStatus === 'PARTIALLY_SUPPORTED';
              const isRejected = rawStatus === 'REJECTED' || rawStatus === 'NOT_SUPPORTED';

              const evidenceStrength = (hyp as any).evidence_strength
                ? String((hyp as any).evidence_strength).toUpperCase()
                : '';
              const reasonText = (hyp as any).confidence_reason || '';
              const hasInsufficientTelemetry =
                evidenceStrength === 'INSUFFICIENT' ||
                reasonText.toLowerCase().includes('zero categorized') ||
                reasonText.toLowerCase().includes('unavailable') ||
                reasonText.toLowerCase().includes('could not') ||
                reasonText.toLowerCase().includes('returned 0') ||
                reasonText.toLowerCase().includes('zero line') ||
                reasonText.toLowerCase().includes('lacks required') ||
                reasonText.toLowerCase().includes('insufficient') ||
                (!hyp.supporting_evidence?.length && !(hyp as any).contradicting_evidence?.length);

              // Accurately determine evidence-status label (do NOT imply confidence in unsupported conclusion)
              let statusLabel = '';
              if (isRejected) {
                if (hasInsufficientTelemetry || evidenceStrength === 'INSUFFICIENT') {
                  statusLabel = 'Evidence: Insufficient telemetry';
                } else {
                  statusLabel = 'Evidence: Refuted by empirical data';
                }
              } else if (isConfirmed) {
                if (typeof hyp.confidence === 'number' && !isNaN(hyp.confidence)) {
                  statusLabel = `Confidence: ${Math.round(hyp.confidence <= 1 ? hyp.confidence * 100 : hyp.confidence)}%`;
                } else if (evidenceStrength) {
                  statusLabel = `Confidence: ${evidenceStrength}`;
                } else {
                  statusLabel = 'Confidence: DIRECT';
                }
              } else if (isPartiallySupported) {
                statusLabel = `Confidence: ${evidenceStrength || 'MODERATE'}`;
              } else {
                statusLabel = 'Evidence: Inconclusive';
              }

              return (
                <div
                  key={hypId}
                  onClick={() => onSelectHypothesis?.(hyp)}
                  className={`p-4 rounded-xl border transition-all ${
                    isConfirmed
                      ? 'bg-cyan-950/30 border-cyan-800/80 hover:border-cyan-600'
                      : isPartiallySupported
                      ? 'bg-surface/60 border-cyan-900/60'
                      : isRejected
                      ? 'bg-surface/40 border-surface-elevated opacity-80 hover:opacity-100'
                      : 'bg-surface/70 border-surface-elevated'
                  } ${onSelectHypothesis ? 'cursor-pointer' : ''}`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="space-y-1 flex-1">
                      <div className="flex items-center gap-2">
                        {isConfirmed && <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />}
                        {isPartiallySupported && <CheckCircle2 className="w-4 h-4 text-cyan-400 shrink-0" />}
                        {isRejected && <XCircle className="w-4 h-4 text-rose-400 shrink-0" />}
                        {!isConfirmed && !isPartiallySupported && !isRejected && (
                          <HelpCircle className="w-4 h-4 text-amber-400 shrink-0" />
                        )}

                        <h4 className="text-xs sm:text-sm font-semibold text-slate-100 font-sans">
                          {hyp.statement}
                        </h4>
                      </div>

                      <p className="text-xs text-slate-300 leading-relaxed font-sans pl-6">
                        {hyp.evidence_summary || reasonText}
                      </p>
                    </div>

                    <div className="text-right shrink-0">
                      <span
                        className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-mono uppercase font-semibold ${
                          isConfirmed
                            ? 'bg-emerald-950/80 text-emerald-300 border border-emerald-800'
                            : isPartiallySupported
                            ? 'bg-cyan-950/80 text-brand-cyan border border-cyan-800'
                            : isRejected
                            ? 'bg-rose-950/80 text-rose-300 border border-rose-800'
                            : 'bg-slate-800 text-slate-300 border border-slate-700'
                        }`}
                      >
                        {hyp.status}
                      </span>

                      <div className="text-[10px] font-mono text-slate-400 pt-1">
                        {statusLabel}
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
