import React, { useState } from 'react';
import {
  FileText,
  Database,
  Calculator,
  ShieldCheck,
  Clock,
  Layers,
  ChevronDown,
  ChevronUp,
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
  title = 'Calculation Evidence & Provenance',
  isOpen = true,
  onClose,
  asModal = false,
}) => {
  const [viewMode, setViewMode] = useState<'business' | 'audit'>('business');
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
      {/* Header controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-4">
        <div>
          <h3 className="text-base font-semibold text-slate-100 flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-cyan-400" />
            <span>{title}</span>
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Audit-grade deterministic calculation trace and cryptographic validation.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-lg bg-slate-900 border border-slate-800 p-0.5 text-xs font-mono">
            <button
              onClick={() => setViewMode('business')}
              className={`px-3 py-1 rounded-md transition-all ${
                viewMode === 'business'
                  ? 'bg-cyan-600 text-white font-medium shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Executive View
            </button>
            <button
              onClick={() => setViewMode('audit')}
              className={`px-3 py-1 rounded-md transition-all ${
                viewMode === 'audit'
                  ? 'bg-cyan-600 text-white font-medium shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Analyst Audit View
            </button>
          </div>

          {asModal && onClose && (
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
              aria-label="Close evidence panel"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>
      </div>

      {/* Primary Evidence Record (Deterministic Analytics) */}
      {evidence && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="rounded-xl border border-slate-800/80 bg-slate-900/60 p-3.5 space-y-1">
              <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Calculator className="w-3.5 h-3.5 text-cyan-400" />
                Calculation Type
              </span>
              <p className="text-sm font-semibold text-slate-200">{evidence.calculation_type}</p>
            </div>

            <div className="rounded-xl border border-slate-800/80 bg-slate-900/60 p-3.5 space-y-1">
              <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-emerald-400" />
                Sample Size
              </span>
              <p className="text-sm font-semibold text-slate-200 font-mono">
                {evidence.row_count.toLocaleString()} rows evaluated
              </p>
            </div>

            <div className="rounded-xl border border-slate-800/80 bg-slate-900/60 p-3.5 space-y-1">
              <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-amber-400" />
                Execution Time
              </span>
              <p className="text-sm font-semibold text-slate-200 font-mono">
                {formatDuration(evidence.execution_time_ms)}
              </p>
            </div>
          </div>

          {/* Mathematical Formula */}
          <div className="rounded-xl border border-slate-800/80 bg-slate-950/70 p-4 space-y-2">
            <span className="text-[11px] font-mono text-cyan-400 uppercase tracking-wider font-semibold">
              Deterministic Mathematical Formula
            </span>
            <code className="block text-xs font-mono text-slate-300 bg-slate-900 p-2.5 rounded-lg border border-slate-800/80 break-words">
              {evidence.mathematical_formula}
            </code>
          </div>

          {/* Detailed Audit Mode Data */}
          {viewMode === 'audit' && (
            <div className="space-y-4 pt-2">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Source Lineage */}
                <div className="rounded-xl border border-slate-800/80 bg-slate-900/40 p-4 space-y-2">
                  <span className="text-xs font-semibold text-slate-200 flex items-center gap-1.5">
                    <Database className="w-4 h-4 text-cyan-400" />
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
                        <span className="text-slate-500">Period: </span>
                        {evidence.period_start} to {evidence.period_end}
                      </p>
                    )}
                  </div>
                </div>

                {/* Filter Predicates & Params */}
                <div className="rounded-xl border border-slate-800/80 bg-slate-900/40 p-4 space-y-2">
                  <span className="text-xs font-semibold text-slate-200 flex items-center gap-1.5">
                    <FileText className="w-4 h-4 text-emerald-400" />
                    Applied SQL Predicates
                  </span>
                  <pre className="text-[11px] font-mono text-slate-300 bg-slate-950 p-2.5 rounded-lg border border-slate-800/60 overflow-x-auto max-h-28">
                    {JSON.stringify(evidence.filter_predicates || {}, null, 2)}
                  </pre>
                </div>
              </div>

              {/* Cryptographic Verification */}
              <div className="flex items-center justify-between p-3 rounded-xl bg-slate-950/80 border border-slate-800/80 text-xs font-mono">
                <div className="flex items-center gap-2 truncate pr-2">
                  <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
                  <span className="text-slate-400">SHA-256 Checksum:</span>
                  <span className="text-slate-300 truncate">{evidence.checksum}</span>
                </div>
                <button
                  onClick={() => handleCopyChecksum(evidence.checksum)}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors text-[11px] shrink-0"
                >
                  {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  <span>{copied ? 'Copied' : 'Copy'}</span>
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Forecast Provenance Evidence (Phase 7) */}
      {forecastEvidence && (
        <div className="rounded-xl border border-cyan-800/40 bg-cyan-950/10 p-4 space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-cyan-300 flex items-center gap-1.5">
              <Calculator className="w-4 h-4 text-cyan-400" />
              Forecasting Model Provenance
            </span>
            <span className="px-2 py-0.5 rounded-full bg-cyan-900/60 border border-cyan-700/60 text-cyan-300 text-[11px] font-mono">
              Model: {forecastEvidence.selected_model} (v{forecastEvidence.model_version})
            </span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
            <div className="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800">
              <span className="text-slate-500 text-[10px] block">BACKTEST MAE</span>
              <span className="text-slate-200 font-semibold">
                {forecastEvidence.validation_metrics?.mae?.toFixed(2) ?? '—'}
              </span>
            </div>
            <div className="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800">
              <span className="text-slate-500 text-[10px] block">BACKTEST RMSE</span>
              <span className="text-slate-200 font-semibold">
                {forecastEvidence.validation_metrics?.rmse?.toFixed(2) ?? '—'}
              </span>
            </div>
            <div className="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800">
              <span className="text-slate-500 text-[10px] block">sMAPE</span>
              <span className="text-slate-200 font-semibold">
                {forecastEvidence.validation_metrics?.smape?.toFixed(1) ?? '—'}%
              </span>
            </div>
            <div className="p-2.5 rounded-lg bg-slate-900/80 border border-slate-800">
              <span className="text-slate-500 text-[10px] block">QUALITY</span>
              <span className="text-emerald-400 font-semibold">
                {forecastEvidence.data_quality_status}
              </span>
            </div>
          </div>

          <div className="text-xs text-slate-300 leading-relaxed bg-slate-950/60 p-3 rounded-lg border border-slate-800/80">
            <span className="text-slate-400 font-semibold block mb-1">Model Selection Rationale:</span>
            {forecastEvidence.selection_reason}
          </div>
        </div>
      )}

      {/* RAG Context Documentation Provenance (Phase 5) */}
      {ragEvidence && ragEvidence.length > 0 && (
        <div className="space-y-3">
          <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
            <FileText className="w-4 h-4 text-violet-400" />
            Referenced Business Policy & Context ({ragEvidence.length} sources)
          </span>

          <div className="space-y-2">
            {ragEvidence.map((rag, idx) => (
              <div
                key={rag.evidence_id || idx}
                className="rounded-xl border border-slate-800 bg-slate-900/40 p-3 text-xs space-y-2"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-slate-200">{rag.document_title}</span>
                    <span className="px-1.5 py-0.5 rounded bg-violet-950/60 text-violet-300 border border-violet-800/60 text-[10px] font-mono">
                      Domain: {rag.business_domain}
                    </span>
                  </div>
                  <button
                    onClick={() => setExpandedRAG(expandedRAG === idx ? null : idx)}
                    className="text-slate-400 hover:text-slate-200"
                  >
                    {expandedRAG === idx ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                  </button>
                </div>

                {expandedRAG === idx && (
                  <div className="pt-2 border-t border-slate-800/60 text-slate-300 font-sans leading-relaxed whitespace-pre-wrap">
                    {rag.content}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );

  if (asModal) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-150">
        <div className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-3xl bg-slate-900 border border-slate-700/80 p-6 shadow-2xl shadow-cyan-950/50">
          {content}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-slate-800/80 bg-slate-900/50 p-5 shadow-sm">
      {content}
    </div>
  );
};
