import React, { useState, useEffect, useCallback } from 'react';
import {
  BookOpen,
  Layers,
  Search,
  FileText,
  Sparkles,
} from 'lucide-react';
import { listDocuments } from '../services/knowledge';
import { listKPIs, resolveTerminology } from '../services/semantic';
import { DocumentSummaryResponse, KPIResponse, SemanticResolveResponse } from '../types/api';
import { formatDate } from '../utils/formatters';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';

export const KnowledgePage: React.FC = () => {
  const [documents, setDocuments] = useState<DocumentSummaryResponse[]>([]);
  const [kpis, setKpis] = useState<KPIResponse[]>([]);
  const [selectedDomain, setSelectedDomain] = useState<string>('all');
  const [searchTerm, setSearchTerm] = useState('');

  // Terminology Resolver Sandbox
  const [testTerm, setTestTerm] = useState('');
  const [resolvedResult, setResolvedResult] = useState<SemanticResolveResponse | null>(null);
  const [resolving, setResolving] = useState(false);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [docsRes, kpisRes] = await Promise.all([
        listDocuments(),
        listKPIs(),
      ]);
      setDocuments(docsRes);
      setKpis(kpisRes);
    } catch (err: any) {
      setError(err?.message || 'Failed to fetch knowledge documents or KPI ontology.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleResolveTest = async () => {
    if (!testTerm.trim()) return;
    setResolving(true);
    try {
      const res = await resolveTerminology(testTerm);
      setResolvedResult(res);
    } catch (err) {
      console.warn('Resolution failed:', err);
    } finally {
      setResolving(false);
    }
  };

  const filteredKpis = kpis.filter((k) => {
    const matchesDomain = selectedDomain === 'all' || k.business_domain === selectedDomain;
    const matchesSearch =
      k.display_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      k.canonical_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      k.synonyms?.some((s) => s.toLowerCase().includes(searchTerm.toLowerCase()));
    return matchesDomain && matchesSearch;
  });

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* Header Banner */}
      <section className="rounded-3xl border border-slate-800 bg-slate-900/80 p-6 sm:p-8 space-y-3">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-950/80 border border-cyan-800/80 text-cyan-400 text-xs font-mono font-medium">
          <BookOpen className="w-3.5 h-3.5" />
          <span>Semantic Layer & Business Context RAG</span>
        </div>
        <h2 className="text-2xl sm:text-3xl font-bold text-white tracking-tight">
          Business Context & Semantic KPI Dictionary
        </h2>
        <p className="text-xs sm:text-sm text-slate-400 max-w-2xl">
          Verified repository of corporate policies, business terminology definitions,
          and deterministic KPI ontology mappings.
        </p>
      </section>

      {loading && <LoadingState message="Loading business documents and KPI catalog..." />}
      {error && <ErrorState message={error} onRetry={fetchData} />}

      {/* Interactive Terminology Resolver Sandbox */}
      <section className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div>
            <h3 className="text-base font-semibold text-white flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-cyan-400" />
              <span>Semantic Terminology Resolver Sandbox</span>
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Test how natural language terms resolve deterministically against approved business KPIs.
            </p>
          </div>
        </div>

        <div className="flex flex-col sm:flex-row gap-2">
          <input
            type="text"
            placeholder="Type a business term (e.g. 'topline', 'gross revenue', 'basket size', 'margin')..."
            value={testTerm}
            onChange={(e) => setTestTerm(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleResolveTest()}
            className="flex-1 rounded-xl bg-slate-950 border border-slate-800 px-4 py-2.5 text-xs text-slate-200 focus:outline-none focus:ring-2 focus:ring-cyan-500 font-sans"
          />
          <button
            onClick={handleResolveTest}
            disabled={resolving || !testTerm.trim()}
            className="px-5 py-2.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-800 text-white text-xs font-semibold shadow-md shadow-cyan-600/20 transition-all"
          >
            {resolving ? 'Resolving...' : 'Test Resolution'}
          </button>
        </div>

        {resolvedResult && (
          <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4 space-y-2 text-xs font-mono">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Query Term: "{resolvedResult.query}"</span>
              <span
                className={`px-2 py-0.5 rounded text-[11px] ${
                  resolvedResult.is_supported
                    ? 'bg-emerald-950/80 text-emerald-300 border border-emerald-800/80'
                    : 'bg-amber-950/80 text-amber-300 border border-amber-800/80'
                }`}
              >
                {resolvedResult.is_supported ? 'Mapped to Canonical KPI' : 'Ambiguous / Unsupported'}
              </span>
            </div>

            {resolvedResult.resolved_kpi && (
              <div className="pt-2 text-slate-200 space-y-1 font-sans">
                <p className="font-bold text-sm text-cyan-400">
                  {resolvedResult.resolved_kpi.display_name} ({resolvedResult.resolved_kpi.canonical_name})
                </p>
                <p className="text-xs text-slate-300">{resolvedResult.resolved_kpi.description}</p>
                <p className="text-[11px] font-mono text-slate-400 pt-1">
                  Bound Tool: {resolvedResult.analytics_tool} • Unit: {resolvedResult.resolved_kpi.unit}
                </p>
              </div>
            )}

            {resolvedResult.unsupported_message && (
              <p className="text-xs text-amber-300/90 font-sans pt-1">
                {resolvedResult.unsupported_message}
              </p>
            )}
          </div>
        )}
      </section>

      {/* Indexed Business Documentation (RAG Sources) */}
      <section className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div>
            <h3 className="text-base font-semibold text-white flex items-center gap-2">
              <FileText className="w-5 h-5 text-violet-400" />
              <span>Business Context Documentation Repository</span>
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Corporate policy documents indexed into vector and full-text knowledge chunks.
            </p>
          </div>
          <span className="text-xs font-mono text-slate-400">
            {documents.length} Indexed Documents
          </span>
        </div>

        {documents.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {documents.map((doc) => (
              <div
                key={doc.id}
                className="p-4 rounded-2xl bg-slate-950/60 border border-slate-800/80 space-y-2 text-xs hover:border-slate-700 transition-colors"
              >
                <div className="flex items-start justify-between gap-2">
                  <h4 className="font-semibold text-slate-200 truncate">{doc.title}</h4>
                  <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px] font-mono shrink-0">
                    v{doc.version}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-[11px] font-mono text-slate-400">
                  <span className="text-cyan-400">{doc.business_domain}</span>
                  <span>•</span>
                  <span>{doc.chunk_count} chunks</span>
                  <span>•</span>
                  <span>{formatDate(doc.created_at)}</span>
                </div>
                {doc.tags && doc.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 pt-1">
                    {doc.tags.map((t, ti) => (
                      <span
                        key={ti}
                        className="px-1.5 py-0.2 rounded bg-slate-900 border border-slate-800 text-[10px] text-slate-400"
                      >
                        #{t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="p-8 text-center text-xs text-slate-400 bg-slate-950/40 rounded-2xl border border-slate-800/60">
            No business context documents currently ingested.
          </div>
        )}
      </section>

      {/* Semantic KPI Dictionary */}
      <section className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 space-y-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-4">
          <div>
            <h3 className="text-base font-semibold text-white flex items-center gap-2">
              <Layers className="w-5 h-5 text-emerald-400" />
              <span>Approved Business Metric (KPI) Dictionary</span>
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Canonical definitions, registered synonyms, and calculation formulas.
            </p>
          </div>

          {/* Search & Domain Filter */}
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-2.5" />
              <input
                type="text"
                placeholder="Search KPI or synonym..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="rounded-xl bg-slate-950 border border-slate-800 pl-8 pr-3 py-1.5 text-xs text-slate-200 focus:outline-none font-sans"
              />
            </div>

            <select
              value={selectedDomain}
              onChange={(e) => setSelectedDomain(e.target.value)}
              className="rounded-xl bg-slate-950 border border-slate-800 px-3 py-1.5 text-xs text-slate-300 focus:outline-none font-sans"
            >
              <option value="all">All Domains</option>
              <option value="finance">Finance</option>
              <option value="product">Product</option>
              <option value="customer">Customer</option>
              <option value="inventory">Inventory</option>
              <option value="diagnostic">Diagnostic</option>
            </select>
          </div>
        </div>

        {/* KPI Cards Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filteredKpis.map((kpi) => (
            <div
              key={kpi.canonical_name}
              className="p-5 rounded-2xl bg-slate-950/60 border border-slate-800/80 space-y-3 text-xs"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h4 className="font-bold text-sm text-slate-100">{kpi.display_name}</h4>
                  <span className="font-mono text-[11px] text-cyan-400">
                    canonical: {kpi.canonical_name}
                  </span>
                </div>
                <span className="px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 text-[10px] font-mono capitalize">
                  {kpi.business_domain}
                </span>
              </div>

              <p className="text-slate-300 leading-relaxed font-sans">{kpi.description}</p>

              <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800/80 text-[11px] font-mono text-slate-300 space-y-0.5">
                <span className="text-slate-500 block text-[10px] uppercase">Formula / Reference:</span>
                <code>{kpi.calculation_reference}</code>
              </div>

              {kpi.synonyms && kpi.synonyms.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5 pt-1">
                  <span className="text-[10px] font-mono text-slate-500">Synonyms:</span>
                  {kpi.synonyms.map((s, si) => (
                    <span
                      key={si}
                      className="px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-[11px] text-slate-400"
                    >
                      {s}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
};
