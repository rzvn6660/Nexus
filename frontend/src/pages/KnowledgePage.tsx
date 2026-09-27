import React, { useState, useEffect, useCallback } from 'react';
import {
  BookOpen,
  Layers,
  Search,
  FileText,
  Sparkles,
  CheckCircle2,
} from 'lucide-react';
import { listDocuments } from '../services/knowledge';
import { listKPIs, resolveTerminology } from '../services/semantic';
import { DocumentSummaryResponse, KPIResponse, SemanticResolveResponse } from '../types/api';
import { formatDate } from '../utils/formatters';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { IntelligenceHeader } from '../components/intelligence/IntelligenceHeader';
import { BusinessUnderstandingCard } from '../components/semantic/BusinessUnderstandingCard';

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
      {/* Header */}
      <IntelligenceHeader
        eyebrow="BUSINESS ONTOLOGY & SEMANTIC LAYER"
        title="Business Knowledge & KPI Dictionary"
        subtitle="How NEXUS understands this business. Deterministic ontology mapping natural phrases into validated database formulas, business rules, and corporate policies."
        icon={BookOpen}
      />

      {loading && <LoadingState message="Loading enterprise ontology and policy catalog..." />}
      {error && <ErrorState message={error} onRetry={fetchData} />}

      {/* 0. TENANT BUSINESS UNDERSTANDING & SEMANTIC LAYER */}
      <BusinessUnderstandingCard onActivated={fetchData} />

      {/* 1. INTERACTIVE SEMANTIC RESOLVER SANDBOX */}
      <section className="p-6 rounded-3xl border border-surface-elevated bg-surface/50 space-y-4">
        <div className="flex items-center justify-between border-b border-surface-elevated pb-3">
          <div>
            <h3 className="text-base font-bold text-white font-sans flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-brand-cyan" />
              <span>Semantic Terminology Resolver Sandbox</span>
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Demonstrates how colloquial language resolves deterministically into canonical mathematical metrics and tenant data models.
            </p>
          </div>
        </div>

        <div className="flex flex-col sm:flex-row gap-2">
          <input
            type="text"
            placeholder="Type a business term (e.g. 'sales', 'turnover', 'margin', 'revenue', 'spending')..."
            value={testTerm}
            onChange={(e) => setTestTerm(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleResolveTest()}
            className="flex-1 rounded-xl bg-void border border-surface-highlight px-4 py-2.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-brand-cyan font-sans"
          />
          <button
            onClick={handleResolveTest}
            disabled={resolving || !testTerm.trim()}
            className="px-5 py-2.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 disabled:bg-surface-elevated text-white text-xs font-semibold shadow-md transition-all font-sans"
          >
            {resolving ? 'Resolving...' : 'Test Resolution'}
          </button>
        </div>

        {resolvedResult && (
          <div className="p-4 rounded-2xl bg-void/80 border border-surface-elevated space-y-2.5 text-xs animate-in fade-in duration-150">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {resolvedResult.is_ambiguous ? (
                  <span className="p-1 rounded bg-amber-500/20 text-amber-300 font-mono text-[10px] font-bold">
                    AMBIGUOUS
                  </span>
                ) : resolvedResult.availability_status === 'AVAILABLE' ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                ) : (
                  <span className="p-1 rounded bg-amber-500/20 text-amber-300 font-mono text-[10px] font-bold">
                    {resolvedResult.availability_status}
                  </span>
                )}
                <span className="font-semibold text-slate-200 font-sans">
                  Query: <code className="text-brand-cyan">"{resolvedResult.query}"</code>
                </span>
              </div>
              <span className="font-mono text-[11px] text-slate-400">
                Tool: {resolvedResult.analytics_tool || 'deterministic_analytics'}
              </span>
            </div>

            {resolvedResult.is_ambiguous ? (
              <div className="p-3 rounded-xl bg-amber-950/30 border border-amber-800/40 text-amber-200 space-y-1.5">
                <p className="font-semibold text-amber-100">{resolvedResult.clarification_prompt}</p>
                {resolvedResult.ambiguity_candidates && resolvedResult.ambiguity_candidates.length > 0 && (
                  <div className="flex gap-1.5 flex-wrap pt-1">
                    {resolvedResult.ambiguity_candidates.map((cand) => (
                      <span
                        key={cand}
                        className="px-2 py-0.5 rounded-md bg-amber-900/50 text-amber-200 font-mono text-[10px]"
                      >
                        {cand}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ) : resolvedResult.canonical_name || resolvedResult.canonical_kpi ? (
              <div className="space-y-1.5 font-mono text-[11px] text-slate-300 pt-1">
                <div className="flex justify-between">
                  <div>
                    <span className="text-slate-500">Canonical Metric: </span>
                    <span className="text-white font-bold">
                      {resolvedResult.display_name || resolvedResult.canonical_name}
                    </span>{' '}
                    ({resolvedResult.canonical_name || resolvedResult.canonical_kpi})
                  </div>
                  {resolvedResult.availability_status && (
                    <span
                      className={`text-[10px] px-2 py-0.5 rounded border font-semibold ${
                        resolvedResult.availability_status === 'AVAILABLE'
                          ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                          : 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                      }`}
                    >
                      {resolvedResult.availability_status}
                    </span>
                  )}
                </div>
                {resolvedResult.calculation_formula && (
                  <p>
                    <span className="text-slate-500">Formula Definition: </span>
                    <span className="text-emerald-400">{resolvedResult.calculation_formula}</span>
                  </p>
                )}
                {resolvedResult.unsupported_message && (
                  <p className="text-amber-300 font-sans">{resolvedResult.unsupported_message}</p>
                )}
              </div>
            ) : (
              <p className="text-amber-300 text-xs font-sans">
                {resolvedResult.unsupported_message || 'Could not resolve term to an approved metric.'}
              </p>
            )}
          </div>
        )}
      </section>

      {/* 2. CANONICAL KPI ONTOLOGY CATALOG */}
      <section className="p-6 rounded-3xl border border-surface-elevated bg-surface/50 space-y-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-surface-elevated pb-4">
          <div>
            <h3 className="text-base font-bold text-white font-sans flex items-center gap-2">
              <Layers className="w-4 h-4 text-brand-cyan" />
              <span>Canonical KPI Semantic Dictionary ({filteredKpis.length})</span>
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Governed formulas, synonyms, and database column bindings.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-2.5" />
              <input
                type="text"
                placeholder="Search KPIs or synonyms..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="rounded-xl bg-void border border-surface-elevated pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-brand-cyan font-sans"
              />
            </div>

            <select
              value={selectedDomain}
              onChange={(e) => setSelectedDomain(e.target.value)}
              className="rounded-xl bg-void border border-surface-elevated px-3 py-1.5 text-xs text-slate-200 focus:outline-none font-sans"
            >
              <option value="all">All Domains</option>
              <option value="commercial">Commercial</option>
              <option value="finance">Finance</option>
              <option value="inventory">Inventory</option>
            </select>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filteredKpis.map((kpi) => (
            <div
              key={kpi.canonical_name}
              className="p-4 rounded-2xl bg-void/60 border border-surface-elevated space-y-2.5 text-xs hover:border-surface-highlight transition-all"
            >
              <div className="flex items-center justify-between">
                <span className="font-bold text-white text-sm font-sans">{kpi.display_name}</span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-cyan-950/80 border border-brand-cyan/30 text-brand-cyan uppercase">
                  {kpi.business_domain}
                </span>
              </div>

              <p className="text-slate-300 text-xs font-sans leading-relaxed">{kpi.description}</p>

              <div className="p-2 rounded-xl bg-surface/70 border border-surface-elevated font-mono text-[11px] space-y-0.5">
                <div className="text-slate-400">
                  <span className="text-slate-500">Formula: </span>
                  <span className="text-emerald-400 font-semibold">{kpi.calculation_reference}</span>
                </div>
                <div className="text-slate-400">
                  <span className="text-slate-500">Target Field: </span>
                  <span className="text-slate-200">{kpi.metric_field} ({kpi.unit})</span>
                </div>
              </div>

              {kpi.synonyms && kpi.synonyms.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5 pt-1 text-[10px] font-mono">
                  <span className="text-slate-500">Synonyms:</span>
                  {kpi.synonyms.map((s, sidx) => (
                    <span key={sidx} className="px-1.5 py-0.5 rounded bg-surface border border-surface-elevated text-slate-300">
                      {s}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* 3. CORPORATE POLICIES & RAG DOCUMENTATION */}
      <section className="p-6 rounded-3xl border border-surface-elevated bg-surface/50 space-y-4">
        <div className="flex items-center justify-between border-b border-surface-elevated pb-3">
          <div>
            <h3 className="text-base font-bold text-white font-sans flex items-center gap-2">
              <FileText className="w-4 h-4 text-emerald-400" />
              <span>Business Policies & Context Documents ({documents.length})</span>
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Source documents chunked and indexed into vector RAG for agentic semantic reasoning.
            </p>
          </div>
        </div>

        {documents.length === 0 ? (
          <div className="p-8 rounded-2xl bg-void/60 border border-surface-elevated text-center space-y-3">
            <div className="w-10 h-10 rounded-xl bg-surface border border-surface-elevated flex items-center justify-center mx-auto text-emerald-400">
              <FileText className="w-5 h-5" />
            </div>
            <h4 className="font-bold text-white text-sm font-sans">
              Add business context to help NEXUS understand your definitions and rules.
            </h4>
            <p className="text-xs text-slate-400 max-w-sm mx-auto">
              Upload operational manuals, margin guidelines, or KPI definitions to enable grounded semantic reasoning.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {documents.map((doc) => (
              <div
                key={doc.id}
                className="p-4 rounded-2xl bg-void/60 border border-surface-elevated space-y-2 text-xs hover:border-surface-highlight transition-all"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono text-slate-500 uppercase">{doc.source}</span>
                  <span className="text-[10px] font-mono text-brand-cyan">{doc.chunk_count} Chunks</span>
                </div>
                <h4 className="font-bold text-white text-sm font-sans">{doc.title}</h4>
                <div className="text-[11px] font-mono text-slate-400 pt-1">
                  Version: {doc.version} • Indexed: {formatDate(doc.created_at)}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
};
