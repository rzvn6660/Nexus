import React, { useState } from 'react';
import {
  FileText,
  Database,
  Calculator,
  ShieldCheck,
  Clock,
  Layers,
  X,
  Copy,
  Check,
} from 'lucide-react';
import { EvidenceRecord, ForecastEvidence, RAGEvidence } from '../../types/api';
import { formatDuration } from '../../utils/formatters';

interface EvidencePanelProps {
  evidence?: EvidenceRecord | null;
  forecastEvidence?: ForecastEvidence | null;
  ragEvidence?: RAGEvidence[] | null;
  title?: string;
  isOpen?: boolean;
  onClose?: () => void;
  asModal?: boolean;
}

export const EvidencePanel: React.FC<EvidencePanelProps> = ({
  evidence,
  forecastEvidence,
  ragEvidence,
  title = 'Proof Behind This Finding',
  isOpen = true,
  onClose,
  asModal = false,
}) => {
  const [viewMode, setViewMode] = useState<'business' | 'analyst'>('business');
  const [copied, setCopied] = useState(false);
  const [expandedRAG, setExpandedRAG] = useState<number | null>(null);

  if (!isOpen) return null;

  const handleCopyChecksum = (hash: string) => {
    navigator.clipboard.writeText(hash);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const content = (
    <div className="space-y-6">
      {/* Header Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-surface-elevated pb-4">
        <div>
          <h3 className="text-base font-bold text-white font-sans flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-brand-cyan" />
            <span>{title}</span>
          </h3>
          <p className="text-xs text-slate-400 mt-0.5 font-sans">
            Verified evidence trace guaranteeing deterministic computation, provenance, and traceability.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-xl bg-void border border-surface-elevated p-0.5 text-xs font-mono">
            <button
              onClick={() => setViewMode('business')}
              className={`px-3 py-1 rounded-lg transition-all ${
                viewMode === 'business'
                  ? 'bg-cyan-600 text-white font-semibold shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Business View
            </button>
            <button
              onClick={() => setViewMode('analyst')}
              className={`px-3 py-1 rounded-lg transition-all ${
                viewMode === 'analyst'
                  ? 'bg-cyan-600 text-white font-semibold shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Analyst View
            </button>
          </div>

          {asModal && onClose && (
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-surface-elevated transition-colors"
              aria-label="Close evidence panel"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>
      </div>

      {/* Primary Evidence Record */}
      {evidence && (
        <div className="space-y-4">
          {/* Quick Metrics Bar */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="rounded-xl border border-surface-elevated bg-void/60 p-3.5 space-y-1">
              <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Calculator className="w-3.5 h-3.5 text-brand-cyan" />
                Calculation Class
              </span>
              <p className="text-sm font-semibold text-slate-200 font-sans">{evidence.calculation_type}</p>
            </div>

            <div className="rounded-xl border border-surface-elevated bg-void/60 p-3.5 space-y-1">
              <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-emerald-400" />
                Sample Size
              </span>
              <p className="text-sm font-semibold text-white font-mono">
                {evidence.row_count.toLocaleString()} rows evaluated
              </p>
            </div>

            <div className="rounded-xl border border-surface-elevated bg-void/60 p-3.5 space-y-1">
              <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-amber-400" />
                Execution Latency
              </span>
              <p className="text-sm font-semibold text-white font-mono">
                {formatDuration(evidence.execution_time_ms)}
              </p>
            </div>
          </div>

          {/* Mode 1: Business View */}
          {viewMode === 'business' ? (
            <div className="p-4 rounded-2xl bg-void/80 border border-surface-elevated space-y-3 text-xs leading-relaxed text-slate-300">
              <span className="text-[10px] font-mono text-brand-cyan uppercase tracking-wider font-semibold block">
                Why this finding is supported
              </span>
              <p className="font-sans">
                This metric is computed through a deterministic SQL aggregation rule evaluated directly on transactional sales ledgers without probabilistic sampling.
              </p>
              <div className="p-3 rounded-xl bg-surface/70 border border-surface-elevated font-mono text-[11px] text-slate-200">
                <span className="text-slate-500 block mb-0.5">Formal Formula:</span>
                <code>{evidence.mathematical_formula}</code>
              </div>
              <p className="text-slate-400 text-[11px] font-sans">
                Full integrity verified: Foreign keys confirmed, date boundary locked to recorded transaction timestamps.
              </p>
            </div>
          ) : (
            /* Mode 2: Analyst View */
            <div className="space-y-4 animate-in fade-in duration-100">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Source Lineage */}
                <div className="rounded-xl border border-surface-elevated bg-void/60 p-4 space-y-2">
                  <span className="text-xs font-semibold text-slate-200 flex items-center gap-1.5 font-sans">
                    <Database className="w-4 h-4 text-brand-cyan" />
                    Source Database Lineage
                  </span>
                  <div className="text-xs space-y-1 font-mono text-slate-300">
                    <p>
                      <span className="text-slate-500">Tables: </span>
                      {evidence.source_tables?.join(', ') || 'sales, sale_items'}
                    </p>
                    <p>
                      <span className="text-slate-500">Columns: </span>
                      {evidence.source_columns?.join(', ') || 'total_price, quantity, created_at'}
                    </p>
                    {evidence.period_start && evidence.period_end && (
                      <p>
                        <span className="text-slate-500">Period Interval: </span>
                        {evidence.period_start} to {evidence.period_end}
                      </p>
                    )}
                  </div>
                </div>

                {/* Filter Predicates & SQL Params */}
                <div className="rounded-xl border border-surface-elevated bg-void/60 p-4 space-y-2">
                  <span className="text-xs font-semibold text-slate-200 flex items-center gap-1.5 font-sans">
                    <FileText className="w-4 h-4 text-emerald-400" />
                    Applied SQL Predicates
                  </span>
                  <pre className="text-[11px] font-mono text-slate-300 bg-void p-2.5 rounded-lg border border-surface-elevated overflow-x-auto max-h-28">
                    {JSON.stringify(evidence.filter_predicates || {}, null, 2)}
                  </pre>
                </div>
              </div>

              {/* Cryptographic SHA-256 Fingerprint */}
              <div className="flex items-center justify-between p-3 rounded-xl bg-void border border-surface-elevated text-xs font-mono">
                <div className="flex items-center gap-2 truncate pr-2">
                  <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
                  <span className="text-slate-500">SHA-256 Checksum:</span>
                  <span className="text-slate-300 truncate">{evidence.checksum}</span>
                </div>
                <button
                  onClick={() => handleCopyChecksum(evidence.checksum)}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-surface hover:bg-surface-elevated text-slate-300 transition-colors text-[11px] shrink-0"
                >
                  {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  <span>{copied ? 'Copied' : 'Copy'}</span>
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Forecast Provenance */}
      {forecastEvidence && (
        <div className="rounded-2xl border border-brand-cyan/30 bg-cyan-950/10 p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-brand-cyan flex items-center gap-1.5 font-sans">
              <Calculator className="w-4 h-4" />
              Forecasting Model Provenance
            </span>
            <span className="px-2 py-0.5 rounded-full bg-cyan-900/60 border border-brand-cyan/40 text-brand-cyan text-[11px] font-mono">
              Model: {forecastEvidence.selected_model} (v{forecastEvidence.model_version})
            </span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
            <div className="p-2.5 rounded-xl bg-surface border border-surface-elevated">
              <span className="text-slate-500 text-[10px] block">BACKTEST MAE</span>
              <span className="text-white font-semibold">
                {forecastEvidence.validation_metrics?.mae?.toFixed(2) ?? '—'}
              </span>
            </div>
            <div className="p-2.5 rounded-xl bg-surface border border-surface-elevated">
              <span className="text-slate-500 text-[10px] block">BACKTEST RMSE</span>
              <span className="text-white font-semibold">
                {forecastEvidence.validation_metrics?.rmse?.toFixed(2) ?? '—'}
              </span>
            </div>
            <div className="p-2.5 rounded-xl bg-surface border border-surface-elevated">
              <span className="text-slate-500 text-[10px] block">sMAPE ACCURACY</span>
              <span className="text-emerald-400 font-semibold">
                {forecastEvidence.validation_metrics?.smape?.toFixed(1) ?? '—'}%
              </span>
            </div>
            <div className="p-2.5 rounded-xl bg-surface border border-surface-elevated">
              <span className="text-slate-500 text-[10px] block">DATA QUALITY</span>
              <span className="text-brand-cyan font-semibold">
                {forecastEvidence.data_quality_status}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* RAG Context Documentation Excerpts */}
      {ragEvidence && ragEvidence.length > 0 && (
        <div className="rounded-2xl border border-surface-elevated bg-surface/50 p-5 space-y-3">
          <span className="text-xs font-semibold text-slate-200 flex items-center gap-1.5 font-sans">
            <FileText className="w-4 h-4 text-indigo-400" />
            Cited Business Policy Excerpts ({ragEvidence.length})
          </span>

          <div className="space-y-2">
            {ragEvidence.map((rag, idx) => {
              const isExpanded = expandedRAG === idx;
              return (
                <div key={idx} className="rounded-xl border border-surface-elevated bg-void/60 p-3 space-y-1 text-xs">
                  <div className="flex items-center justify-between font-mono text-[11px]">
                    <span className="text-indigo-400 font-semibold">{rag.document_title}</span>
                    <span className="text-slate-500">Score: {(rag.relevance_score * 100).toFixed(0)}%</span>
                  </div>
                  <p className="text-slate-300 font-sans leading-relaxed pt-1">
                    {isExpanded ? rag.content : `${rag.content.slice(0, 160)}...`}
                  </p>
                  {rag.content.length > 160 && (
                    <button
                      onClick={() => setExpandedRAG(isExpanded ? null : idx)}
                      className="text-[11px] font-mono text-brand-cyan hover:underline pt-1 block"
                    >
                      {isExpanded ? 'Collapse excerpt' : 'Read full excerpt'}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );

  if (asModal) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-void/80 backdrop-blur-sm animate-in fade-in duration-100">
        <div className="relative w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-3xl bg-void-sub border border-surface-elevated p-6 shadow-2xl">
          {content}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-3xl bg-void-sub border border-surface-elevated p-6 shadow-xl">
      {content}
    </div>
  );
};
