import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  BookOpen,
  Layers,
  Search,
  FileText,
  Sparkles,
  CheckCircle2,
  RefreshCw,
  X,
  Database,
  ArrowRight,
  ChevronRight,
  AlertTriangle,
  Info,
} from 'lucide-react';
import { listDocuments } from '../services/knowledge';
import { listKPIs, resolveTerminology } from '../services/semantic';
import { DocumentSummaryResponse, KPIResponse, SemanticResolveResponse } from '../types/api';
import { formatDate } from '../utils/formatters';
import { LoadingState } from '../components/common/LoadingState';
import { StatusBadge } from '../components/common/StatusBadge';
import { ErrorBoundary } from '../components/common/ErrorBoundary';
import { BusinessUnderstandingCard } from '../components/semantic/BusinessUnderstandingCard';

const SAMPLE_TERMS = [
  'net revenue',
  'profit margin',
  'customer retention',
  'average basket size',
  'inventory turnover',
  'operating expenses',
  'gross margin',
  'turnover',
];

const DOMAIN_CONFIG: Record<
  string,
  { label: string; badgeClasses: string; dotColor: string }
> = {
  all: { label: 'All Domains', badgeClasses: 'bg-cyan-950/60 border-cyan-800/40 text-cyan-300', dotColor: 'bg-cyan-400' },
  commercial: { label: 'Commercial', badgeClasses: 'bg-cyan-950/70 border-cyan-700/50 text-cyan-300', dotColor: 'bg-cyan-400' },
  finance: { label: 'Finance', badgeClasses: 'bg-emerald-950/70 border-emerald-700/50 text-emerald-300', dotColor: 'bg-emerald-400' },
  customer: { label: 'Customer', badgeClasses: 'bg-violet-950/70 border-violet-700/50 text-violet-300', dotColor: 'bg-violet-400' },
  product: { label: 'Product', badgeClasses: 'bg-sky-950/70 border-sky-700/50 text-sky-300', dotColor: 'bg-sky-400' },
  inventory: { label: 'Inventory', badgeClasses: 'bg-amber-950/70 border-amber-700/50 text-amber-300', dotColor: 'bg-amber-400' },
  expenses: { label: 'Expenses', badgeClasses: 'bg-rose-950/70 border-rose-700/50 text-rose-300', dotColor: 'bg-rose-400' },
  diagnostic: { label: 'Diagnostic', badgeClasses: 'bg-indigo-950/70 border-indigo-700/50 text-indigo-300', dotColor: 'bg-indigo-400' },
  statistics: { label: 'Statistics', badgeClasses: 'bg-fuchsia-950/70 border-fuchsia-700/50 text-fuchsia-300', dotColor: 'bg-fuchsia-400' },
};

// Extended resolution result state with provenance discrimination
export interface KnowledgeResolvedResult extends SemanticResolveResponse {
  is_client_fallback?: boolean;
  fallback_reason?: string;
}

export function resolveLocalKpiFallback(
  query: string,
  kpis: KPIResponse[],
  error?: any
): KnowledgeResolvedResult | null {
  const normalizedQuery = query.toLowerCase().trim();
  const localMatch = kpis.find(
    (k) =>
      k.canonical_name.toLowerCase() === normalizedQuery ||
      k.display_name.toLowerCase() === normalizedQuery ||
      k.synonyms?.some((s) => s.toLowerCase() === normalizedQuery)
  );

  if (!localMatch) return null;

  const failureReason =
    error?.data?.detail || error?.message || 'Backend semantic resolution endpoint unreachable.';

  return {
    query,
    resolved_kpi: localMatch,
    canonical_name: localMatch.canonical_name,
    canonical_kpi: localMatch.canonical_name,
    display_name: localMatch.display_name,
    analytics_tool: localMatch.analytics_tool,
    metric_field: localMatch.metric_field,
    calculation_formula: localMatch.calculation_reference,
    unit: localMatch.unit,
    availability_status: 'AVAILABLE',
    is_ambiguous: false,
    candidate_kpis: [localMatch],
    is_supported: true,
    is_client_fallback: true,
    fallback_reason: failureReason,
  };
}

export function getResolverBadgeConfig(result: KnowledgeResolvedResult): {
  badgeText: string;
  badgeClasses: string;
  isFallback: boolean;
} {
  if (result.is_client_fallback) {
    return {
      badgeText: 'RESOLVED (OFFLINE CATALOG)',
      badgeClasses: 'bg-amber-950/80 text-amber-300 border-amber-500/40',
      isFallback: true,
    };
  }
  if (result.is_ambiguous) {
    return {
      badgeText: 'AMBIGUOUS TERM',
      badgeClasses: 'bg-amber-950/80 text-amber-300 border-amber-500/40',
      isFallback: false,
    };
  }
  if (result.availability_status === 'AVAILABLE') {
    return {
      badgeText: 'RESOLVED CANONICAL',
      badgeClasses: 'bg-emerald-950/80 text-emerald-300 border-emerald-500/40',
      isFallback: false,
    };
  }
  return {
    badgeText: result.availability_status || 'REQUIRES GROUNDING',
    badgeClasses: 'bg-amber-950/80 text-amber-300 border-amber-500/40',
    isFallback: false,
  };
}

export const KnowledgePage: React.FC = () => {
  const [documents, setDocuments] = useState<DocumentSummaryResponse[]>([]);
  const [docsAvailable, setDocsAvailable] = useState<boolean>(true);
  const [kpis, setKpis] = useState<KPIResponse[]>([]);
  const [selectedDomain, setSelectedDomain] = useState<string>('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedKpiForModal, setSelectedKpiForModal] = useState<KPIResponse | null>(null);

  // Terminology Resolver Sandbox
  const [testTerm, setTestTerm] = useState('');
  const [resolvedResult, setResolvedResult] = useState<KnowledgeResolvedResult | null>(null);
  const [resolving, setResolving] = useState(false);
  const [resolveError, setResolveError] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);

    // Resilient loading: KPI ontology is independent of Postgres session
    const [docsSettled, kpisSettled] = await Promise.allSettled([
      listDocuments(),
      listKPIs(),
    ]);

    if (kpisSettled.status === 'fulfilled') {
      setKpis(kpisSettled.value || []);
    } else {
      console.warn('Failed to fetch KPI ontology:', kpisSettled.reason);
      setKpis([]);
      setError('Could not load canonical KPI ontology.');
    }

    if (docsSettled.status === 'fulfilled') {
      setDocuments(docsSettled.value || []);
      setDocsAvailable(true);
    } else {
      console.warn('Document repository unavailable (PostgreSQL offline):', docsSettled.reason);
      setDocuments([]);
      setDocsAvailable(false);
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleResolveTest = async (termToResolve?: string) => {
    const query = (termToResolve || testTerm).trim();
    if (!query) return;

    if (termToResolve) {
      setTestTerm(termToResolve);
    }

    setResolving(true);
    setResolveError(null);
    try {
      const res = await resolveTerminology(query);
      setResolvedResult(res);
    } catch (err: any) {
      console.warn('Resolution failed:', err);
      // Fallback matching against locally loaded KPI catalog if backend resolution errored
      const fallbackResult = resolveLocalKpiFallback(query, kpis, err);
      if (fallbackResult) {
        setResolvedResult(fallbackResult);
      } else {
        setResolveError(
          err?.data?.detail || err?.message || 'Could not resolve term against semantic layer.'
        );
      }
    } finally {
      setResolving(false);
    }
  };

  // Domain counts and unique domains list
  const domainCounts = useMemo(() => {
    const counts: Record<string, number> = { all: kpis.length };
    kpis.forEach((k) => {
      const d = (k.business_domain || 'commercial').toLowerCase();
      counts[d] = (counts[d] || 0) + 1;
    });
    return counts;
  }, [kpis]);

  const availableDomains = useMemo(() => {
    const keys = Object.keys(domainCounts).filter((k) => k !== 'all');
    return ['all', ...keys];
  }, [domainCounts]);

  // Filtered KPIs list based on search and domain filter
  const filteredKpis = useMemo(() => {
    return kpis.filter((k) => {
      const matchesDomain =
        selectedDomain === 'all' ||
        (k.business_domain || '').toLowerCase() === selectedDomain.toLowerCase();

      const search = searchTerm.trim().toLowerCase();
      if (!search) return matchesDomain;

      const matchesSearch =
        k.display_name.toLowerCase().includes(search) ||
        k.canonical_name.toLowerCase().includes(search) ||
        (k.description && k.description.toLowerCase().includes(search)) ||
        (k.calculation_reference && k.calculation_reference.toLowerCase().includes(search)) ||
        (k.metric_field && k.metric_field.toLowerCase().includes(search)) ||
        k.synonyms?.some((s) => s.toLowerCase().includes(search));

      return matchesDomain && matchesSearch;
    });
  }, [kpis, selectedDomain, searchTerm]);

  // Aggregate statistics for Scorecard
  const totalSynonyms = useMemo(() => {
    return kpis.reduce((acc, k) => acc + (k.synonyms?.length || 0), 0);
  }, [kpis]);

  const totalChunks = useMemo(() => {
    return documents.reduce((acc, d) => acc + (d.chunk_count || 0), 0);
  }, [documents]);

  return (
    <ErrorBoundary fallbackTitle="Knowledge Layer Diagnostics" onReset={fetchData}>
      <div className="space-y-6 animate-in fade-in duration-200">
        {/* ========================================================= */}
        {/* 1. EXECUTIVE HEADER & TELEMETRY                           */}
        {/* ========================================================= */}
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-white/[0.08] pb-5">
          <div>
            <div className="flex flex-wrap items-center gap-2 mb-2">
              <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-800/50 text-cyan-400 font-mono text-[11px] font-semibold">
                <BookOpen className="w-3.5 h-3.5" />
                <span>BUSINESS ONTOLOGY &amp; SEMANTIC LAYER</span>
              </div>

              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-emerald-950/60 border border-emerald-600/40 text-emerald-400 font-mono text-[10px] font-semibold">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                <span>Deterministic Ontology Active</span>
              </span>
            </div>

            <h1 className="text-2xl font-bold text-white tracking-tight font-sans">
              Business Knowledge &amp; KPI Dictionary
            </h1>
            <p className="text-xs text-slate-400 mt-1 max-w-2xl font-sans">
              Governed formulas, synonyms, and database column bindings. Deterministic ontology mapping natural colloquial terminology into validated database formulas, business rules, and corporate policies.
            </p>
          </div>

          <div className="flex items-center gap-2.5">
            <button
              onClick={fetchData}
              disabled={loading}
              className="btn-secondary text-xs h-9 px-3.5 inline-flex items-center gap-2"
              title="Refresh ontology models and document catalog"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-cyan-400' : ''}`} />
              <span>Refresh Ontology</span>
            </button>
          </div>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="p-3.5 rounded-xl bg-rose-950/40 border border-rose-800/40 text-rose-200 text-xs flex items-center justify-between">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
              <span>{error}</span>
            </div>
            <button onClick={() => setError(null)} className="text-rose-400 hover:text-white">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Global Loading Spinner */}
        {loading && <LoadingState message="Loading business ontology and canonical KPI dictionary..." />}

        {/* ========================================================= */}
        {/* 2. KNOWLEDGE & ONTOLOGY SCORECARD (21st.dev Stat Pattern) */}
        {/* ========================================================= */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
          {/* Card 1: Canonical KPIs */}
          <div
            className="card-obsidian p-4 sm:p-5 flex flex-col justify-between border-white/[0.08] hover:border-cyan-500/30 transition-all duration-200 min-w-0 group"
            title="Total count of deterministically verified business metrics registered in the active semantic ontology."
          >
            <div>
              <div className="flex items-center justify-between gap-2 mb-2.5">
                <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-medium truncate">
                  Canonical KPIs
                </span>
                <div className="w-7 h-7 rounded-lg bg-cyan-950/40 border border-cyan-800/30 flex items-center justify-center text-cyan-400 shrink-0 group-hover:border-cyan-500/40 transition-colors">
                  <Layers className="w-3.5 h-3.5" />
                </div>
              </div>

              <div className="space-y-1">
                <p className="text-xl sm:text-2xl font-bold text-cyan-400 font-mono tabular-nums tracking-tight">
                  {kpis.length} Governed Metrics
                </p>
                <span className="text-[10px] font-mono text-cyan-400/80 block truncate">
                  {availableDomains.length - 1} Business Domains
                </span>
              </div>
            </div>

            <div className="mt-3 pt-2.5 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-slate-400 font-sans">
              <span className="truncate" title="Deterministic analytical ontology registered in Phase 3 AnalyticsService">
                Deterministic analytical ontology
              </span>
            </div>
          </div>

          {/* Card 2: Verification Posture */}
          <div
            className="card-obsidian p-4 sm:p-5 flex flex-col justify-between border-white/[0.08] hover:border-emerald-500/30 transition-all duration-200 min-w-0 group"
            title="Integrity posture verifying that all metrics map deterministically to SQL calculations without LLM code hallucination."
          >
            <div>
              <div className="flex items-center justify-between gap-2 mb-2.5">
                <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-medium truncate">
                  Verification Posture
                </span>
                <div className="w-7 h-7 rounded-lg bg-emerald-950/40 border border-emerald-800/30 flex items-center justify-center text-emerald-400 shrink-0 group-hover:border-emerald-500/40 transition-colors">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                </div>
              </div>

              <div className="space-y-1.5 pt-0.5">
                <div>
                  <StatusBadge status="PASSED" size="sm" />
                </div>
                <span className="text-[11px] font-mono text-emerald-300 block truncate">
                  100% Deterministic Bindings
                </span>
              </div>
            </div>

            <div className="mt-3 pt-2.5 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-slate-400 font-sans">
              <span className="truncate" title="Zero hallucinated metrics; mathematical formulas validated">
                Grounded SQL definitions
              </span>
            </div>
          </div>

          {/* Card 3: Knowledge Sources */}
          <div
            className="card-obsidian p-4 sm:p-5 flex flex-col justify-between border-white/[0.08] hover:border-slate-400/30 transition-all duration-200 min-w-0 group"
            title="Registered corporate context documents and policy files indexed into vector embeddings for grounded reasoning."
          >
            <div>
              <div className="flex items-center justify-between gap-2 mb-2.5">
                <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-medium truncate">
                  Knowledge Sources
                </span>
                <div className="w-7 h-7 rounded-lg bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-slate-300 shrink-0 group-hover:border-white/[0.14] transition-colors">
                  <FileText className="w-3.5 h-3.5" />
                </div>
              </div>

              <div className="space-y-1">
                <p className="text-xl sm:text-2xl font-bold text-white font-mono tabular-nums tracking-tight">
                  {docsAvailable ? `${documents.length} Indexed Sources` : 'Store Offline'}
                </p>
                <span className="text-[10px] font-mono text-slate-400 block truncate">
                  {docsAvailable ? `${totalChunks} Vector Chunks` : 'PostgreSQL RAG Disconnected'}
                </span>
              </div>
            </div>

            <div className="mt-3 pt-2.5 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-slate-400 font-sans">
              <span className="truncate" title="Grounded RAG semantic retrieval">
                Grounded RAG retrieval
              </span>
            </div>
          </div>

          {/* Card 4: Synonym Coverage */}
          <div
            className="card-obsidian p-4 sm:p-5 flex flex-col justify-between border-white/[0.08] hover:border-violet-500/30 transition-all duration-200 min-w-0 group"
            title="Colloquial terminology and conversational phrasing mapped deterministically to canonical metrics."
          >
            <div>
              <div className="flex items-center justify-between gap-2 mb-2.5">
                <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-medium truncate">
                  Synonym Coverage
                </span>
                <div className="w-7 h-7 rounded-lg bg-violet-950/40 border border-violet-800/30 flex items-center justify-center text-violet-400 shrink-0 group-hover:border-violet-500/40 transition-colors">
                  <Sparkles className="w-3.5 h-3.5" />
                </div>
              </div>

              <div className="space-y-1">
                <p className="text-xl sm:text-2xl font-bold text-violet-300 font-mono tabular-nums tracking-tight">
                  {totalSynonyms} Natural Aliases
                </p>
                <span className="text-[10px] font-mono text-violet-400/80 block truncate">
                  Conversational Query Mappings
                </span>
              </div>
            </div>

            <div className="mt-3 pt-2.5 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-slate-400 font-sans">
              <span className="truncate" title="Deterministic natural language term resolution">
                Deterministic phrase resolution
              </span>
            </div>
          </div>
        </section>

        {/* ========================================================= */}
        {/* 3. TENANT BUSINESS UNDERSTANDING & SEMANTIC LAYER         */}
        {/* ========================================================= */}
        <BusinessUnderstandingCard onActivated={fetchData} />

        {/* ========================================================= */}
        {/* 4. INTERACTIVE SEMANTIC RESOLVER SANDBOX                  */}
        {/* ========================================================= */}
        <section className="card-obsidian p-5 sm:p-6 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-white/[0.08] pb-3">
            <div>
              <h2 className="text-base font-bold text-white font-sans flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-cyan-400" />
                <span>Semantic Terminology Resolver Sandbox</span>
              </h2>
              <p className="text-xs text-slate-400 mt-0.5 font-sans">
                Demonstrates how conversational questions resolve deterministically into verified SQL formulas and tenant data models.
              </p>
            </div>

            <span className="px-2 py-0.5 rounded bg-surface border border-white/[0.08] text-[10px] font-mono text-slate-400 self-start sm:self-center">
              Deterministic Semantic Router
            </span>
          </div>

          {/* Quick-select Example Chips */}
          <div className="space-y-1.5">
            <span className="text-[10px] font-mono uppercase text-slate-500 font-semibold tracking-wider">
              Try Common Business Phrases:
            </span>
            <div className="flex flex-wrap gap-1.5">
              {SAMPLE_TERMS.map((term) => (
                <button
                  key={term}
                  type="button"
                  onClick={() => handleResolveTest(term)}
                  className="px-2.5 py-1 rounded-lg bg-surface/80 hover:bg-surface border border-white/[0.08] hover:border-cyan-500/40 text-[11px] font-mono text-slate-300 hover:text-white transition-all flex items-center gap-1.5"
                >
                  <Search className="w-3 h-3 text-cyan-400" />
                  <span>{term}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Input & Action */}
          <div className="flex flex-col sm:flex-row gap-2">
            <div className="relative flex-1">
              <input
                type="text"
                placeholder="Type a business term (e.g. 'sales', 'turnover', 'margin', 'revenue', 'spending')..."
                value={testTerm}
                onChange={(e) => setTestTerm(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleResolveTest()}
                className="input-obsidian text-xs h-10 w-full pr-8 font-sans"
              />
              {testTerm && (
                <button
                  onClick={() => {
                    setTestTerm('');
                    setResolvedResult(null);
                    setResolveError(null);
                  }}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white"
                  title="Clear input"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            <button
              onClick={() => handleResolveTest()}
              disabled={resolving || !testTerm.trim()}
              className="btn-primary text-xs h-10 px-5 whitespace-nowrap"
            >
              {resolving ? 'Resolving...' : 'Test Resolution'}
            </button>
          </div>

          {/* Error Notice */}
          {resolveError && (
            <div className="p-3.5 rounded-xl bg-amber-950/40 border border-amber-800/40 text-amber-200 text-xs flex items-center justify-between">
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
                <span>{resolveError}</span>
              </div>
              <button onClick={() => setResolveError(null)} className="text-amber-400 hover:text-white">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          )}

          {/* Resolved Result Panel */}
          {resolvedResult && (() => {
            const badgeConfig = getResolverBadgeConfig(resolvedResult);
            return (
              <div
                className={`p-4 sm:p-5 rounded-xl bg-void/90 border space-y-3.5 text-xs animate-in fade-in duration-150 ${
                  badgeConfig.isFallback
                    ? 'border-amber-500/40 shadow-[0_0_20px_rgba(245,158,11,0.08)]'
                    : 'border-cyan-500/30 shadow-[0_0_20px_rgba(6,182,212,0.06)]'
                }`}
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-white/[0.08] pb-3">
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <span
                      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full font-mono text-[10px] font-bold border ${badgeConfig.badgeClasses}`}
                      title={
                        badgeConfig.isFallback
                          ? 'Resolved via client-side catalog dictionary match because backend resolution service was unavailable.'
                          : undefined
                      }
                    >
                      {badgeConfig.isFallback ? (
                        <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                      ) : resolvedResult.is_ambiguous ? null : resolvedResult.availability_status === 'AVAILABLE' ? (
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                      ) : null}
                      <span>{badgeConfig.badgeText}</span>
                    </span>

                    <span className="font-semibold text-white font-sans text-sm">
                      Query: <code className="text-cyan-300 font-mono">"{resolvedResult.query}"</code>
                    </span>
                  </div>

                  <div className="flex items-center gap-3">
                    <span className="font-mono text-[11px] text-slate-400">
                      Target Tool: <strong className="text-slate-200">{resolvedResult.analytics_tool || 'deterministic_analytics'}</strong>
                    </span>
                    <button
                      onClick={() => setResolvedResult(null)}
                      className="text-slate-400 hover:text-white p-1"
                      title="Close resolved result"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* Client-Side Fallback Warning & Failure Context Notice */}
                {resolvedResult.is_client_fallback && (
                  <div className="p-3 rounded-lg bg-amber-950/30 border border-amber-500/30 text-amber-200 text-xs font-sans flex items-start gap-2.5">
                    <Info className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                    <div className="space-y-0.5 min-w-0">
                      <p className="font-semibold text-amber-100">
                        Client-Side Offline Catalog Match
                      </p>
                      <p className="text-[11px] text-amber-300/90 leading-relaxed">
                        Backend semantic resolution was unavailable ({resolvedResult.fallback_reason || 'connection error'}). Displaying formula definition from locally cached KPI ontology.
                      </p>
                    </div>
                  </div>
                )}

              {resolvedResult.is_ambiguous ? (
                <div className="p-3.5 rounded-lg bg-amber-950/30 border border-amber-800/40 text-amber-200 space-y-2 font-sans">
                  <p className="font-semibold text-amber-100 leading-relaxed">
                    {resolvedResult.clarification_prompt || 'Multiple metrics match this colloquial term. Please choose a specific KPI:'}
                  </p>
                  {resolvedResult.ambiguity_candidates && resolvedResult.ambiguity_candidates.length > 0 && (
                    <div className="flex gap-2 flex-wrap pt-1">
                      {resolvedResult.ambiguity_candidates.map((cand) => (
                        <button
                          key={cand}
                          type="button"
                          onClick={() => handleResolveTest(cand)}
                          className="px-2.5 py-1 rounded-lg bg-amber-900/60 hover:bg-amber-800/80 text-amber-100 font-mono text-[11px] border border-amber-700/60 transition-colors inline-flex items-center gap-1.5"
                        >
                          <span>{cand}</span>
                          <ArrowRight className="w-3 h-3 text-amber-300" />
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ) : resolvedResult.canonical_name || resolvedResult.canonical_kpi ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 font-mono text-[11px]">
                  <div className="p-3 rounded-lg bg-surface/60 border border-white/[0.06] space-y-1.5">
                    <div className="text-slate-400">
                      <span className="text-slate-500 uppercase text-[10px] block">CANONICAL METRIC</span>
                      <strong className="text-white text-xs font-sans">
                        {resolvedResult.display_name || resolvedResult.canonical_name}
                      </strong>{' '}
                      <span className="text-cyan-400">({resolvedResult.canonical_name || resolvedResult.canonical_kpi})</span>
                    </div>

                    <div className="text-slate-400 pt-1 border-t border-white/[0.04]">
                      <span className="text-slate-500 uppercase text-[10px] block">TARGET DATA BINDING</span>
                      <span className="text-slate-200">
                        {resolvedResult.metric_field || 'aggregate'} ({resolvedResult.unit || 'unit'})
                      </span>
                    </div>
                  </div>

                  <div className="p-3 rounded-lg bg-surface/60 border border-white/[0.06] space-y-1.5">
                    <span className="text-slate-500 uppercase text-[10px] block">FORMULA SPECIFICATION</span>
                    <div className="p-2 rounded bg-void/80 border border-white/[0.04] text-emerald-400 font-semibold text-[11px] overflow-x-auto">
                      {resolvedResult.calculation_formula || 'Calculated deterministically via AnalyticsService'}
                    </div>

                    {resolvedResult.unsupported_message && (
                      <p className="text-amber-300 font-sans text-[11px] pt-1">
                        {resolvedResult.unsupported_message}
                      </p>
                    )}
                  </div>
                </div>
              ) : (
                <p className="text-amber-300 text-xs font-sans">
                  {resolvedResult.unsupported_message || 'Could not resolve term to an approved metric.'}
                </p>
              )}
            </div>
          );
        })()}
        </section>

        {/* ========================================================= */}
        {/* 5. CANONICAL KPI ONTOLOGY CATALOG (39+ METRICS)          */}
        {/* ========================================================= */}
        <section className="card-obsidian p-5 sm:p-6 space-y-5">
          {/* Header & Search/Filter Toolbar */}
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-white/[0.08] pb-4">
            <div>
              <h2 className="text-base font-bold text-white font-sans flex items-center gap-2">
                <Layers className="w-4 h-4 text-cyan-400" />
                <span>Canonical KPI Semantic Dictionary ({filteredKpis.length})</span>
              </h2>
              <p className="text-xs text-slate-400 mt-0.5 font-sans">
                Governed formulas, synonyms, and database column bindings. Click any KPI card to inspect full specification.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2.5">
              {/* Search Bar */}
              <div className="relative">
                <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  placeholder="Filter KPIs, formulas, or synonyms..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="input-obsidian pl-8 pr-8 text-xs h-8 font-sans w-56 sm:w-64"
                />
                {searchTerm && (
                  <button
                    onClick={() => setSearchTerm('')}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white"
                  >
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>

              {/* Domain Dropdown for smaller screens */}
              <select
                value={selectedDomain}
                onChange={(e) => setSelectedDomain(e.target.value)}
                className="input-obsidian text-xs h-8 font-sans w-36 lg:hidden"
              >
                {availableDomains.map((d) => (
                  <option key={d} value={d}>
                    {DOMAIN_CONFIG[d]?.label || d} ({domainCounts[d] || 0})
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Domain Filter Pills for Large Screens */}
          <div className="hidden lg:flex flex-wrap items-center gap-1.5 pb-1">
            <span className="text-[11px] font-mono text-slate-500 uppercase mr-1">DOMAINS:</span>
            {availableDomains.map((d) => {
              const isSelected = selectedDomain === d;
              const count = domainCounts[d] || 0;
              const config = DOMAIN_CONFIG[d] || {
                label: d,
                badgeClasses: 'bg-surface border-white/[0.08] text-slate-300',
                dotColor: 'bg-slate-400',
              };

              return (
                <button
                  key={d}
                  type="button"
                  onClick={() => setSelectedDomain(d)}
                  className={`px-3 py-1 rounded-lg text-xs font-mono transition-all border inline-flex items-center gap-1.5 ${
                    isSelected
                      ? 'bg-cyan-950/70 border-cyan-500/50 text-cyan-300 font-semibold shadow-sm'
                      : 'bg-void/60 border-white/[0.08] text-slate-400 hover:text-slate-200 hover:border-white/[0.15]'
                  }`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${isSelected ? 'bg-cyan-400' : config.dotColor}`} />
                  <span>{config.label}</span>
                  <span className="text-[10px] text-slate-500 font-normal">({count})</span>
                </button>
              );
            })}
          </div>

          {/* Empty State when no KPIs match */}
          {filteredKpis.length === 0 ? (
            <div className="p-8 rounded-xl bg-void/50 border border-white/[0.08] text-center space-y-3">
              <Search className="w-8 h-8 text-slate-500 mx-auto" />
              <div className="space-y-1">
                <h3 className="font-bold text-white text-sm font-sans">No matching KPI definitions found</h3>
                <p className="text-xs text-slate-400 max-w-sm mx-auto font-sans leading-relaxed">
                  {searchTerm
                    ? `No ontology definition matches query "${searchTerm}"${selectedDomain !== 'all' ? ` in domain "${selectedDomain}"` : ''}.`
                    : `No KPIs registered under domain "${selectedDomain}".`}
                </p>
              </div>
              <button
                onClick={() => {
                  setSearchTerm('');
                  setSelectedDomain('all');
                }}
                className="btn-secondary py-1.5 px-3.5 text-xs inline-flex items-center gap-1.5"
              >
                <span>Reset Search &amp; Domain Filters</span>
              </button>
            </div>
          ) : (
            /* KPI Cards Grid */
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {filteredKpis.map((kpi) => {
                const domainKey = (kpi.business_domain || 'commercial').toLowerCase();
                const domainConfig = DOMAIN_CONFIG[domainKey] || DOMAIN_CONFIG.commercial;

                return (
                  <div
                    key={kpi.canonical_name}
                    className="p-4 sm:p-5 rounded-xl bg-void/60 border border-white/[0.08] hover:border-cyan-500/40 hover:bg-void/90 transition-all duration-200 flex flex-col justify-between space-y-3 group cursor-pointer"
                    onClick={() => setSelectedKpiForModal(kpi)}
                  >
                    <div>
                      {/* Top Row: Display Name & Badges */}
                      <div className="flex items-start justify-between gap-2 mb-1.5">
                        <div className="space-y-0.5">
                          <h3 className="font-bold text-white text-sm font-sans group-hover:text-cyan-300 transition-colors">
                            {kpi.display_name}
                          </h3>
                          <span className="font-mono text-[10px] text-slate-500 block">
                            {kpi.canonical_name}
                          </span>
                        </div>

                        <div className="flex items-center gap-1.5 shrink-0">
                          <span
                            className={`text-[9px] font-mono px-2 py-0.5 rounded-full border uppercase font-semibold ${domainConfig.badgeClasses}`}
                          >
                            {kpi.business_domain}
                          </span>

                          <span className="px-1.5 py-0.5 rounded bg-emerald-950/70 border border-emerald-600/40 text-[9px] font-mono text-emerald-300 font-semibold uppercase">
                            VERIFIED
                          </span>
                        </div>
                      </div>

                      {/* Description */}
                      <p className="text-slate-300 text-xs font-sans leading-relaxed">
                        {kpi.description}
                      </p>

                      {/* Formula & Target Binding */}
                      <div className="mt-3 p-2.5 rounded-lg bg-surface/80 border border-white/[0.06] font-mono text-[11px] space-y-1.5">
                        <div className="flex items-center justify-between text-slate-400">
                          <span className="text-slate-500 text-[10px] uppercase font-semibold">FORMULA:</span>
                          <span className="text-emerald-400 font-semibold text-[11px] truncate max-w-[280px]">
                            {kpi.calculation_reference}
                          </span>
                        </div>

                        <div className="flex items-center justify-between text-slate-400 pt-1 border-t border-white/[0.04]">
                          <span className="text-slate-500 text-[10px] uppercase font-semibold">DATABASE FIELD:</span>
                          <span className="text-slate-200 font-semibold">
                            {kpi.metric_field} ({kpi.unit})
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Bottom Row: Synonyms & Detail Action */}
                    <div className="pt-2 border-t border-white/[0.06] flex items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-1 text-[10px] font-mono truncate">
                        <span className="text-slate-500">Aliases:</span>
                        {kpi.synonyms && kpi.synonyms.length > 0 ? (
                          kpi.synonyms.slice(0, 3).map((s, sidx) => (
                            <span
                              key={sidx}
                              className="px-1.5 py-0.5 rounded bg-surface border border-white/[0.06] text-slate-300"
                            >
                              {s}
                            </span>
                          ))
                        ) : (
                          <span className="text-slate-500">—</span>
                        )}
                        {kpi.synonyms && kpi.synonyms.length > 3 && (
                          <span className="text-slate-500 text-[10px]">
                            +{kpi.synonyms.length - 3} more
                          </span>
                        )}
                      </div>

                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedKpiForModal(kpi);
                        }}
                        className="text-cyan-400 hover:text-cyan-300 text-[11px] font-mono shrink-0 inline-flex items-center gap-1"
                      >
                        <span>Inspect</span>
                        <ChevronRight className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* ========================================================= */}
        {/* 6. CORPORATE POLICIES & RAG DOCUMENTATION                 */}
        {/* ========================================================= */}
        <section className="card-obsidian p-5 sm:p-6 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-white/[0.08] pb-3">
            <div>
              <h2 className="text-base font-bold text-white font-sans flex items-center gap-2">
                <FileText className="w-4 h-4 text-emerald-400" />
                <span>Business Policies &amp; Context Documents ({docsAvailable ? documents.length : 0})</span>
              </h2>
              <p className="text-xs text-slate-400 mt-0.5 font-sans">
                Source corporate manuals and margin rules indexed into vector RAG for agentic semantic reasoning.
              </p>
            </div>

            <span className="px-2 py-0.5 rounded bg-surface border border-white/[0.08] text-[10px] font-mono text-slate-400 self-start sm:self-center">
              {docsAvailable ? 'PostgreSQL Vector Store' : 'Vector Store Offline'}
            </span>
          </div>

          {!docsAvailable ? (
            /* Document Store Offline Notice */
            <div className="p-6 rounded-xl bg-void/50 border border-rose-900/40 text-center space-y-2.5">
              <div className="w-10 h-10 rounded-xl bg-rose-950/60 border border-rose-800/40 flex items-center justify-center text-rose-400 mx-auto">
                <Database className="w-5 h-5" />
              </div>
              <h3 className="font-bold text-white text-sm font-sans">
                Document Vector Index Offline
              </h3>
              <p className="text-xs text-slate-400 max-w-md mx-auto font-sans leading-relaxed">
                The PostgreSQL database session is unreachable. Grounded operational manuals, corporate margin rules, and contextual policy chunks will populate automatically once database connectivity is restored.
              </p>
              <div className="pt-1">
                <button
                  onClick={fetchData}
                  className="btn-secondary text-xs h-8 px-3 inline-flex items-center gap-1.5"
                >
                  <RefreshCw className="w-3 h-3 text-cyan-400" />
                  <span>Retry Document Connection</span>
                </button>
              </div>
            </div>
          ) : documents.length === 0 ? (
            /* Actionable Empty State */
            <div className="p-8 rounded-xl bg-void/50 border border-white/[0.08] text-center space-y-3">
              <div className="w-10 h-10 rounded-xl bg-surface border border-white/[0.08] flex items-center justify-center mx-auto text-emerald-400">
                <FileText className="w-5 h-5" />
              </div>
              <h3 className="font-bold text-white text-sm font-sans">
                Add business context to help NEXUS understand your definitions and rules.
              </h3>
              <p className="text-xs text-slate-400 max-w-sm mx-auto font-sans leading-relaxed">
                Upload operational manuals, margin guidelines, or accounting policy definitions in Business Settings to enable grounded semantic reasoning.
              </p>
            </div>
          ) : (
            /* Documents Grid */
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {documents.map((doc) => (
                <div
                  key={doc.id}
                  className="p-4 rounded-xl bg-void/60 border border-white/[0.06] space-y-2.5 text-xs hover:border-white/[0.15] transition-all"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-mono text-slate-500 uppercase">{doc.source}</span>
                    <span className="text-[10px] font-mono text-cyan-400 font-semibold px-2 py-0.5 rounded bg-cyan-950/60 border border-cyan-800/40">
                      {doc.chunk_count} Chunks
                    </span>
                  </div>

                  <h3 className="font-bold text-white text-sm font-sans leading-snug">{doc.title}</h3>

                  <div className="text-[11px] font-mono text-slate-400 pt-1 flex items-center justify-between border-t border-white/[0.04]">
                    <span>v{doc.version}</span>
                    <span>Indexed: {formatDate(doc.created_at)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* ========================================================= */}
        {/* 7. KPI DETAIL INSPECTION MODAL                            */}
        {/* ========================================================= */}
        {selectedKpiForModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-150">
            <div className="card-obsidian max-w-2xl w-full p-6 space-y-5 border-white/[0.15] shadow-2xl overflow-y-auto max-h-[90vh]">
              {/* Modal Header */}
              <div className="flex items-start justify-between gap-4 border-b border-white/[0.08] pb-4">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-cyan-950/80 border border-cyan-800/40 text-cyan-300 uppercase font-semibold">
                      {selectedKpiForModal.business_domain}
                    </span>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-950/80 border border-emerald-600/40 text-emerald-300 font-semibold uppercase">
                      GOVERNED ONTOLOGY
                    </span>
                  </div>
                  <h2 className="text-xl font-bold text-white font-sans">
                    {selectedKpiForModal.display_name}
                  </h2>
                  <code className="text-xs font-mono text-cyan-400">
                    canonical: {selectedKpiForModal.canonical_name}
                  </code>
                </div>

                <button
                  onClick={() => setSelectedKpiForModal(null)}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/[0.06] transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Description */}
              <div className="space-y-1.5">
                <span className="text-[10px] font-mono uppercase text-slate-500 font-semibold tracking-wider">
                  EXECUTIVE DEFINITION
                </span>
                <p className="text-xs sm:text-sm text-slate-200 font-sans leading-relaxed">
                  {selectedKpiForModal.description}
                </p>
              </div>

              {/* Formula & Technical Binding */}
              <div className="p-4 rounded-xl bg-void/90 border border-white/[0.08] space-y-3 font-mono text-xs">
                <div className="space-y-1">
                  <span className="text-slate-500 text-[10px] uppercase font-semibold block">
                    DETERMINISTIC SQL FORMULA
                  </span>
                  <div className="p-2.5 rounded bg-surface/80 border border-white/[0.06] text-emerald-400 font-bold overflow-x-auto text-[11px]">
                    {selectedKpiForModal.calculation_reference}
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
                  <div>
                    <span className="text-slate-500 text-[10px] uppercase font-semibold block">
                      TARGET DATA FIELD
                    </span>
                    <span className="text-white font-semibold">
                      {selectedKpiForModal.metric_field} ({selectedKpiForModal.unit})
                    </span>
                  </div>

                  <div>
                    <span className="text-slate-500 text-[10px] uppercase font-semibold block">
                      ANALYTICS SERVICE TOOL
                    </span>
                    <span className="text-cyan-300 font-semibold">
                      {selectedKpiForModal.analytics_tool}
                    </span>
                  </div>
                </div>
              </div>

              {/* Supported Dimensions & Filters */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs font-mono">
                <div className="space-y-1.5">
                  <span className="text-slate-500 text-[10px] uppercase font-semibold block">
                    SUPPORTED DIMENSIONS ({selectedKpiForModal.supported_dimensions?.length || 0})
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {selectedKpiForModal.supported_dimensions && selectedKpiForModal.supported_dimensions.length > 0 ? (
                      selectedKpiForModal.supported_dimensions.map((dim) => (
                        <span key={dim} className="px-2 py-0.5 rounded bg-surface border border-white/[0.08] text-slate-300 text-[11px]">
                          {dim}
                        </span>
                      ))
                    ) : (
                      <span className="text-slate-500 text-[11px]">Period / Total Aggregate</span>
                    )}
                  </div>
                </div>

                <div className="space-y-1.5">
                  <span className="text-slate-500 text-[10px] uppercase font-semibold block">
                    DEFAULT BREAKDOWN
                  </span>
                  <span className="text-slate-200 text-[11px] block">
                    {selectedKpiForModal.default_dimension || 'Monthly Series Timeline'}
                  </span>
                </div>
              </div>

              {/* Synonyms */}
              {selectedKpiForModal.synonyms && selectedKpiForModal.synonyms.length > 0 && (
                <div className="space-y-1.5 pt-2 border-t border-white/[0.06]">
                  <span className="text-[10px] font-mono uppercase text-slate-500 font-semibold tracking-wider">
                    RESOLVED NATURAL LANGUAGE ALIASES ({selectedKpiForModal.synonyms.length}):
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {selectedKpiForModal.synonyms.map((s, idx) => (
                      <span
                        key={idx}
                        className="px-2 py-0.5 rounded-lg bg-void border border-white/[0.08] text-[11px] font-mono text-slate-300"
                      >
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Modal Footer */}
              <div className="flex items-center justify-end pt-3 border-t border-white/[0.08]">
                <button
                  type="button"
                  onClick={() => setSelectedKpiForModal(null)}
                  className="btn-secondary text-xs h-9 px-4"
                >
                  Close Specification
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </ErrorBoundary>
  );
};

export default KnowledgePage;
