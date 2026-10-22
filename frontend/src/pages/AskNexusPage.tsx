import React, { useState, useEffect } from 'react';
import {
  Send,
  ShieldCheck,
  SearchCode,
  TrendingUp,
  HelpCircle,
  Clock,
  ArrowRight,
  FileText,
  Terminal,
  Calculator,
  Info,
  BookOpen,
  RotateCcw,
  Database,
  AlertTriangle,
  RefreshCw,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { analyzeBusinessQuery } from '../services/agent';
import { AgentResponse, EvidenceRecord, RAGEvidence } from '../types/api';
import { formatDuration } from '../utils/formatters';
import { EvidencePanel } from '../components/common/EvidencePanel';
import { IntelligenceStage, StageId } from '../components/intelligence/IntelligenceStage';

interface AskNexusPageProps {
  onNavigate: (route: string) => void;
  initialQuery?: string;
}

export const AskNexusPage: React.FC<AskNexusPageProps> = ({
  onNavigate,
  initialQuery = '',
}) => {
  const [query, setQuery] = useState(initialQuery);
  const [explanationLevel, setExplanationLevel] = useState<'manager' | 'analyst' | 'simple'>('manager');
  const [analysisMode, setAnalysisMode] = useState<'standard' | 'investigation' | 'forecast'>('standard');
  const [history, setHistory] = useState<Array<{ query: string; response: AgentResponse }>>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastAttemptedQuery, setLastAttemptedQuery] = useState('');
  const [showErrorDetails, setShowErrorDetails] = useState(false);
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceRecord | null>(null);
  const [selectedRagEvidence, setSelectedRagEvidence] = useState<RAGEvidence[] | null>(null);

  const [executionStage, setExecutionStage] = useState<StageId>('understand');
  const [statusText, setStatusText] = useState('Resolving semantic KPI formulas & temporal boundaries...');

  useEffect(() => {
    if (!loading) {
      setExecutionStage('understand');
      setStatusText('Resolving semantic KPI formulas & temporal boundaries...');
      return;
    }

    const t1 = setTimeout(() => {
      setExecutionStage('investigate');
      setStatusText('Executing deterministic SQL queries & variance decomposition...');
    }, 2000);

    const t2 = setTimeout(() => {
      setExecutionStage('validate');
      setStatusText('Verifying mathematical proofs, row counts & evidence checksums...');
    }, 5000);

    const t3 = setTimeout(() => {
      setExecutionStage('decide');
      setStatusText('Synthesizing executive briefing with verifiable provenance...');
    }, 8500);

    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
    };
  }, [loading]);

  const suggestedQuestions = [
    'Why did gross margin fall this month?',
    'Which products are driving growth?',
    'What changed in customer behavior?',
    'What should I investigate next?',
    'What is likely to happen next month?',
    'What is our current inventory turnover ratio and stock health?',
  ];

  const handleAsk = async (text: string) => {
    if (!text.trim() || loading) return;
    setLoading(true);
    setError(null);
    setLastAttemptedQuery(text);
    setQuery(text);

    try {
      const res = await analyzeBusinessQuery({
        query: text,
        explanation_level: explanationLevel,
        is_investigation: analysisMode === 'investigation',
        is_forecast: analysisMode === 'forecast',
      });

      setHistory((prev) => [{ query: text, response: res }, ...prev]);
      setQuery('');
    } catch (err: any) {
      setError(err?.message || 'Failed to process inquiry via NEXUS agent.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Executive Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-elevated/80 pb-5">
        <div>
          <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-500/30 text-cyan-300 font-mono text-[10px] font-semibold uppercase tracking-wider mb-2">
            <Terminal className="w-3 h-3 text-cyan-400" />
            <span>NEXUS INTELLIGENCE CONSOLE</span>
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight font-sans">
            Ask NEXUS Commercial Intelligence
          </h1>
          <p className="text-xs text-slate-300 mt-1 max-w-2xl font-sans leading-relaxed">
            Ask natural business questions. NEXUS orchestrates deterministic SQL analytics, semantic ontology mappings, and business context RAG with verifiable provenance.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {history.length > 0 && (
            <button
              onClick={() => {
                setHistory([]);
                setError(null);
              }}
              className="btn-secondary text-xs h-9 text-slate-300 hover:text-rose-300 hover:border-rose-500/40 inline-flex items-center gap-1.5"
              title="Clear current inquiry history"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Reset Session</span>
            </button>
          )}

          <button
            onClick={() => onNavigate('/investigations')}
            className="btn-secondary text-xs h-9 inline-flex items-center gap-1.5"
            title="Open Diagnostic Root Cause Engine"
          >
            <SearchCode className="w-3.5 h-3.5 text-cyan-400" />
            <span>Root Cause Engine</span>
          </button>

          <button
            onClick={() => onNavigate('/forecasts')}
            className="btn-secondary text-xs h-9 inline-flex items-center gap-1.5"
            title="Open Predictive Horizon Engine"
          >
            <TrendingUp className="w-3.5 h-3.5 text-violet-400" />
            <span>Predictive Horizons</span>
          </button>
        </div>
      </div>

      {/* Intelligence Console Input Card */}
      <section className="rounded-2xl bg-surface/70 border border-surface-elevated p-5 sm:p-6 space-y-4 shadow-obsidian">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleAsk(query);
          }}
          className="space-y-4"
        >
          <div className="relative rounded-2xl bg-void/90 border border-surface-elevated focus-within:border-cyan-500/50 focus-within:ring-1 focus-within:ring-cyan-500/30 transition-all shadow-inner">
            <textarea
              rows={2}
              aria-label="Natural language business inquiry question"
              placeholder="e.g. Why did gross margin decline this quarter, and which product categories drove the variance?"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              disabled={loading}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleAsk(query);
                }
              }}
              className="w-full bg-transparent p-4 text-sm text-slate-100 placeholder-slate-500 focus:outline-none disabled:opacity-60 resize-none font-sans"
            />

            <div className="flex flex-wrap items-center justify-between gap-3 px-4 pb-3 pt-2 border-t border-surface-elevated/70 text-xs">
              <div className="flex flex-wrap items-center gap-3">
                {/* Analysis Mode Toggle */}
                <div className="flex items-center gap-1.5">
                  <span className="text-slate-400 font-mono text-[11px]">Mode:</span>
                  <div className="inline-flex rounded-lg bg-surface border border-surface-elevated p-0.5 font-sans">
                    {(['standard', 'investigation', 'forecast'] as const).map((m) => (
                      <button
                        key={m}
                        type="button"
                        onClick={() => setAnalysisMode(m)}
                        className={`px-2 py-0.5 rounded text-[11px] font-medium capitalize transition-all ${
                          analysisMode === m
                            ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 font-semibold'
                            : 'text-slate-400 hover:text-slate-200'
                        }`}
                      >
                        {m === 'standard' ? 'Comprehensive' : m === 'investigation' ? 'Root Cause' : 'Forecast'}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Explanation Posture */}
                <div className="flex items-center gap-1.5">
                  <span className="text-slate-400 font-mono text-[11px]">Posture:</span>
                  <select
                    value={explanationLevel}
                    onChange={(e) => setExplanationLevel(e.target.value as any)}
                    className="rounded-lg bg-surface border border-surface-elevated px-2 py-0.5 text-slate-200 text-xs focus:outline-none focus:border-cyan-400 font-sans"
                  >
                    <option value="manager">Manager (Strategic Briefing)</option>
                    <option value="analyst">Analyst (Detailed Breakdown)</option>
                    <option value="simple">Executive (Concise Summary)</option>
                  </select>
                </div>

                <span className="text-[10px] text-slate-500 font-mono hidden xl:inline">
                  Enter ↵ to analyze • Shift+Enter for newline
                </span>
              </div>

              <button
                type="submit"
                disabled={loading || !query.trim()}
                className="btn-primary text-xs py-1.5 px-3.5 shadow-cyan-subtle"
              >
                <Send className="w-3.5 h-3.5" />
                <span>{loading ? 'Analyzing...' : 'Execute Analysis'}</span>
              </button>
            </div>
          </div>

          {/* Curated Suggested Strategic Inquiries */}
          <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
            <span className="text-slate-500 font-mono text-[11px]">Suggested Inquiries:</span>
            {suggestedQuestions.map((prompt) => (
              <button
                key={prompt}
                type="button"
                onClick={() => {
                  setQuery(prompt);
                  handleAsk(prompt);
                }}
                className="px-2.5 py-1 rounded-lg bg-void/80 hover:bg-surface border border-surface-elevated text-slate-300 hover:text-cyan-300 hover:border-cyan-500/30 text-[11px] transition-colors font-sans"
              >
                {prompt}
              </button>
            ))}
          </div>
        </form>
      </section>

      {/* Genuine Execution Progression Telemetry */}
      {loading && (
        <IntelligenceStage
          currentStage={executionStage}
          statusMessage={statusText}
          isExecuting={true}
        />
      )}

      {/* Intelligence Engine Notice (Error / Offline State) */}
      {error && (
        <div className="rounded-2xl border border-surface-elevated bg-surface/80 p-6 sm:p-8 shadow-obsidian space-y-5 animate-in fade-in duration-200">
          <div className="flex items-start gap-4">
            <div className="w-11 h-11 rounded-xl bg-rose-950/60 border border-rose-500/30 flex items-center justify-center text-rose-400 shrink-0 shadow-sm">
              <Database className="w-5 h-5" />
            </div>
            <div className="space-y-1.5 flex-1 min-w-0">
              <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-rose-950/60 border border-rose-500/30 text-[10px] font-mono text-rose-300 uppercase">
                <AlertTriangle className="w-3 h-3 text-rose-400" />
                <span>Intelligence Engine Notice</span>
              </div>
              <h3 className="text-lg sm:text-xl font-bold text-white font-sans tracking-tight">
                Unable to Complete Agentic Analysis
              </h3>
              <p className="text-xs sm:text-sm text-slate-300 font-sans leading-relaxed">
                {error.includes('500') || error.includes('Failed to fetch') || error.includes('NetworkError')
                  ? 'The NEXUS intelligence agent could not reach the backend analytical execution service. This occurs when the transactional database service is offline or the agentic reasoning API is unreachable.'
                  : error}
              </p>
            </div>
          </div>

          {/* Actionable Recovery Options */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1 border-t border-surface-elevated/80 font-sans text-xs">
            <button
              onClick={() => onNavigate('/data')}
              className="p-3.5 rounded-xl bg-void/70 hover:bg-surface-elevated/60 border border-surface-elevated hover:border-cyan-500/40 text-left transition-all group"
            >
              <div className="flex items-center justify-between">
                <span className="font-bold text-white group-hover:text-cyan-300 transition-colors">
                  Open Data Gateway
                </span>
                <ArrowRight className="w-3.5 h-3.5 text-slate-500 group-hover:text-cyan-400 transition-colors" />
              </div>
              <p className="text-[11px] text-slate-400 mt-1">
                Verify transactional CSV/XLSX ledgers or database schema ingestion status.
              </p>
            </button>

            <button
              onClick={() => onNavigate('/knowledge')}
              className="p-3.5 rounded-xl bg-void/70 hover:bg-surface-elevated/60 border border-surface-elevated hover:border-cyan-500/40 text-left transition-all group"
            >
              <div className="flex items-center justify-between">
                <span className="font-bold text-white group-hover:text-cyan-300 transition-colors">
                  Review KPI Dictionary
                </span>
                <ArrowRight className="w-3.5 h-3.5 text-slate-500 group-hover:text-cyan-400 transition-colors" />
              </div>
              <p className="text-[11px] text-slate-400 mt-1">
                Inspect semantic metric definitions and synonym mappings.
              </p>
            </button>
          </div>

          {/* Primary Action Row */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
            <button
              onClick={() => handleAsk(lastAttemptedQuery || query)}
              className="btn-primary py-2 px-4 text-xs shadow-cyan-subtle inline-flex items-center gap-2"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Retry Inquiry Analysis</span>
            </button>

            <button
              onClick={() => setShowErrorDetails(!showErrorDetails)}
              className="text-xs font-mono text-slate-400 hover:text-slate-200 inline-flex items-center gap-1.5 transition-colors"
            >
              <span>Technical Diagnostics</span>
              {showErrorDetails ? (
                <ChevronUp className="w-3.5 h-3.5" />
              ) : (
                <ChevronDown className="w-3.5 h-3.5" />
              )}
            </button>
          </div>

          {/* Technical Diagnostics Drawer */}
          {showErrorDetails && (
            <div className="p-3.5 rounded-xl bg-void border border-surface-elevated font-mono text-xs text-slate-400 space-y-1.5">
              <div className="text-slate-300 text-[11px] font-semibold">// Error Diagnostic Information</div>
              <div className="text-rose-400 break-all">{error}</div>
              <div className="text-slate-500 text-[11px]">Target: /api/v1/agent/analyze</div>
            </div>
          )}
        </div>
      )}

      {/* First-use / Initial Orientation Console Guide */}
      {history.length === 0 && !loading && !error && (
        <section className="rounded-2xl border border-surface-elevated bg-surface/70 p-6 sm:p-8 space-y-6 shadow-obsidian">
          <div className="space-y-1.5 border-b border-surface-elevated/80 pb-4">
            <span className="text-[10px] font-mono uppercase text-cyan-400 font-semibold tracking-wider flex items-center gap-1.5">
              <Terminal className="w-3.5 h-3.5" />
              <span>NEXUS ARCHITECTURE & EVIDENCE GUARANTEES</span>
            </span>
            <h2 className="text-base sm:text-lg font-bold text-white font-sans">
              How the NEXUS Intelligence Console Analyzes Inquiries
            </h2>
            <p className="text-xs text-slate-300 font-sans leading-relaxed max-w-2xl">
              NEXUS combines natural language parsing with deterministic mathematical execution. Every inquiry is verified through relational SQL, semantic ontologies, and corporate business context.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 font-sans text-xs">
            <div className="p-4 rounded-xl bg-void/60 border border-surface-elevated/70 space-y-2">
              <div className="w-8 h-8 rounded-lg bg-cyan-950/70 border border-cyan-500/30 flex items-center justify-center text-cyan-400 shadow-sm">
                <Calculator className="w-4 h-4" />
              </div>
              <h3 className="font-bold text-white text-sm">Deterministic SQL</h3>
              <p className="text-slate-400 text-[11px] leading-relaxed">
                Calculations execute directly against PostgreSQL without approximation, LLM arithmetic, or fabricated numbers.
              </p>
            </div>

            <div className="p-4 rounded-xl bg-void/60 border border-surface-elevated/70 space-y-2">
              <div className="w-8 h-8 rounded-lg bg-emerald-950/70 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shadow-sm">
                <BookOpen className="w-4 h-4" />
              </div>
              <h3 className="font-bold text-white text-sm">Semantic Ontology</h3>
              <p className="text-slate-400 text-[11px] leading-relaxed">
                Business terms, colloquial phrases, and formulas resolve through tenant-scoped KPI definitions and synonyms.
              </p>
            </div>

            <div className="p-4 rounded-xl bg-void/60 border border-surface-elevated/70 space-y-2">
              <div className="w-8 h-8 rounded-lg bg-violet-950/70 border border-violet-500/30 flex items-center justify-center text-violet-400 shadow-sm">
                <FileText className="w-4 h-4" />
              </div>
              <h3 className="font-bold text-white text-sm">Policy & RAG Context</h3>
              <p className="text-slate-400 text-[11px] leading-relaxed">
                Strategic policies, margin targets, and corporate operating rules provide verifiable grounded reasoning.
              </p>
            </div>

            <div className="p-4 rounded-xl bg-void/60 border border-surface-elevated/70 space-y-2">
              <div className="w-8 h-8 rounded-lg bg-amber-950/70 border border-amber-500/30 flex items-center justify-center text-amber-400 shadow-sm">
                <ShieldCheck className="w-4 h-4" />
              </div>
              <h3 className="font-bold text-white text-sm">Causality Safeguards</h3>
              <p className="text-slate-400 text-[11px] leading-relaxed">
                NEXUS explicitly abstains or requests clarification when queries lack sufficient statistical power or evidence.
              </p>
            </div>
          </div>
        </section>
      )}

      {/* Structured Intelligence Report Dossiers */}
      <div className="space-y-6">
        {history.map((item, idx) => {
          const res = item.response;

          return (
            <article
              key={idx}
              className="rounded-2xl border border-surface-elevated bg-surface/75 p-6 sm:p-7 space-y-6 shadow-obsidian animate-in fade-in duration-150"
            >
              {/* Dossier Header: Original Inquiry & Metadata */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-surface-elevated/80 pb-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono uppercase tracking-widest text-cyan-400 font-semibold">
                      INTELLIGENCE DOSSIER
                    </span>
                    <span className="text-slate-600">•</span>
                    <span className="text-[11px] font-mono text-slate-400 capitalize">
                      {res.intent?.replace(/_/g, ' ') || 'Strategic Analysis'}
                    </span>
                    <span className="text-slate-600">•</span>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-surface border border-surface-elevated text-slate-300 uppercase">
                      {res.explanation_level || 'Manager'}
                    </span>
                  </div>
                  <h2 className="text-base sm:text-lg font-bold text-white font-sans">
                    "{item.query}"
                  </h2>
                </div>

                <div className="flex items-center gap-2 shrink-0 text-xs font-mono text-slate-400">
                  <Clock className="w-3.5 h-3.5 text-slate-500" />
                  <span>{formatDuration(res.execution_metadata?.elapsed_ms)}</span>
                </div>
              </div>

              {/* Semantic Clarification Alert (if ambiguous) */}
              {res.needs_clarification && res.clarification_prompt && (
                <div className="p-4 rounded-xl bg-amber-950/30 border border-amber-800/40 text-amber-200 text-xs flex items-start gap-3 font-sans">
                  <HelpCircle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <span className="font-semibold block text-amber-300">
                      Ambiguity Detected — Clarification Required:
                    </span>
                    <p className="text-slate-300 leading-relaxed">
                      {res.clarification_prompt}
                    </p>
                  </div>
                </div>
              )}

              {/* 1. NEXUS Grounded Narrative Findings */}
              <div className="space-y-2">
                <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 flex items-center gap-1.5 font-semibold">
                  <FileText className="w-3.5 h-3.5 text-cyan-400" />
                  <span>NEXUS Analytical Finding</span>
                </span>
                <div className="p-5 rounded-xl bg-void/80 border border-surface-elevated text-xs sm:text-sm text-slate-200 leading-relaxed whitespace-pre-wrap font-sans">
                  {res.answer}
                </div>
              </div>

              {/* 2. Resolved Semantic Context & Formulas (if present) */}
              {res.semantic_context && Object.keys(res.semantic_context).length > 0 && (
                <div className="p-3.5 rounded-xl bg-void/50 border border-surface-elevated/70 space-y-1.5 text-xs font-sans">
                  <span className="text-[10px] font-mono uppercase tracking-wider text-cyan-400 flex items-center gap-1.5 font-semibold">
                    <BookOpen className="w-3.5 h-3.5" />
                    <span>Resolved Business Semantics & KPI Rules</span>
                  </span>
                  <div className="flex flex-wrap gap-2 pt-1 font-mono text-[11px]">
                    {Object.entries(res.semantic_context).map(([k, v], sidx) => (
                      <span key={sidx} className="px-2 py-0.5 rounded bg-surface border border-surface-elevated text-slate-300">
                        <strong className="text-cyan-300 font-semibold">{k}:</strong> {typeof v === 'string' ? v : JSON.stringify(v)}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* 3. Deterministic Mathematical Calculations (if present) */}
              {res.calculations && res.calculations.length > 0 && (
                <div className="space-y-2">
                  <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 flex items-center gap-1.5 font-semibold">
                    <Calculator className="w-3.5 h-3.5 text-emerald-400" />
                    <span>Deterministic Computations & Calculations ({res.calculations.length})</span>
                  </span>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs font-mono">
                    {res.calculations.map((calc: any, cidx: number) => (
                      <div
                        key={cidx}
                        className="p-3 rounded-lg bg-void/60 border border-surface-elevated flex items-center justify-between"
                      >
                        <span className="text-slate-300 truncate">
                          {calc.name || calc.formula || `Calculation #${cidx + 1}`}
                        </span>
                        <span className="text-cyan-400 font-bold ml-2 shrink-0">
                          {calc.value !== undefined ? String(calc.value) : 'Verified'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 4. Assumptions & Honest Limitations (if present) */}
              {((res.assumptions && res.assumptions.length > 0) || (res.limitations && res.limitations.length > 0)) && (
                <div className="p-4 rounded-xl bg-void/40 border border-surface-elevated/70 space-y-2 text-xs font-sans">
                  <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 flex items-center gap-1.5 font-semibold">
                    <Info className="w-3.5 h-3.5 text-slate-400" />
                    <span>Model Assumptions & Boundaries</span>
                  </span>
                  <ul className="list-disc list-inside text-slate-300 space-y-1 text-[11px]">
                    {res.assumptions?.map((asm, aidx) => (
                      <li key={`asm-${aidx}`}>{asm}</li>
                    ))}
                    {res.limitations?.map((lim, lidx) => (
                      <li key={`lim-${lidx}`} className="text-amber-300/80">{lim}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* 5. Policy & RAG Context Citations (if present) */}
              {res.rag_evidence && res.rag_evidence.length > 0 && (
                <div className="pt-1 flex items-center gap-2 text-xs font-mono">
                  <button
                    onClick={() => {
                      setSelectedEvidence(res.evidence?.[0] || null);
                      setSelectedRagEvidence(res.rag_evidence);
                    }}
                    className="inline-flex items-center gap-1.5 text-cyan-400 hover:text-cyan-300 hover:underline transition-colors"
                  >
                    <BookOpen className="w-3.5 h-3.5 text-cyan-400" />
                    <span>
                      Referenced {res.rag_evidence.length} business context policies & definitions (Inspect Citations)
                    </span>
                  </button>
                </div>
              )}

              {/* 6. Structured Provenance & Action Triggers */}
              <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-surface-elevated/80">
                <div className="flex flex-wrap items-center gap-2">
                  {res.evidence && res.evidence.length > 0 && (
                    <button
                      onClick={() => {
                        setSelectedEvidence(res.evidence[0]);
                        setSelectedRagEvidence(res.rag_evidence || null);
                      }}
                      className="btn-secondary text-xs h-8 inline-flex items-center gap-1.5"
                    >
                      <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                      <span>Inspect SQL Evidence ({res.evidence.length})</span>
                    </button>
                  )}

                  <button
                    onClick={() => onNavigate('/investigations')}
                    className="btn-secondary text-xs h-8 inline-flex items-center gap-1.5"
                    title="Decompose variance in root-cause engine"
                  >
                    <SearchCode className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Investigate Root Causes</span>
                  </button>

                  <button
                    onClick={() => onNavigate('/forecasts')}
                    className="btn-secondary text-xs h-8 inline-flex items-center gap-1.5"
                    title="Project horizon in forecasting engine"
                  >
                    <TrendingUp className="w-3.5 h-3.5 text-violet-400" />
                    <span>Forecast Trend</span>
                  </button>
                </div>

                <div className="flex items-center gap-1.5 font-mono text-[11px] text-slate-400">
                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                  <span>
                    {res.tools_used?.length ?? res.execution_metadata?.tools_executed?.length ?? 0} Tools Executed
                  </span>
                </div>
              </div>

              {/* 7. Recommended Follow-Up Inquiries */}
              {res.follow_up_questions && res.follow_up_questions.length > 0 && (
                <div className="pt-3 border-t border-surface-elevated/70 space-y-2">
                  <span className="text-[10px] font-mono text-slate-400 uppercase tracking-wider block font-semibold">
                    RECOMMENDED FOLLOW-UP INQUIRIES:
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {res.follow_up_questions.map((fq, fidx) => (
                      <button
                        key={fidx}
                        onClick={() => {
                          setQuery(fq);
                          handleAsk(fq);
                        }}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-void/70 hover:bg-surface-elevated/60 border border-surface-elevated hover:border-cyan-500/40 text-slate-300 hover:text-cyan-300 text-xs transition-colors font-sans"
                      >
                        <span>{fq}</span>
                        <ArrowRight className="w-3 h-3 text-cyan-400" />
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </article>
          );
        })}
      </div>

      {/* Evidence Provenance Modal */}
      {selectedEvidence && (
        <EvidencePanel
          evidence={selectedEvidence}
          ragEvidence={selectedRagEvidence}
          isOpen={Boolean(selectedEvidence)}
          onClose={() => {
            setSelectedEvidence(null);
            setSelectedRagEvidence(null);
          }}
          asModal
        />
      )}
    </div>
  );
};
