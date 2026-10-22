import React, { useState, useEffect } from 'react';
import {
  SearchCode,
  ShieldCheck,
  AlertTriangle,
  TrendingUp,
  Sparkles,
  ChevronDown,
  ChevronUp,
  Layers,
  ArrowRight,
  RefreshCw,
  SlidersHorizontal,
  Calendar,
  X,
  Database,
  BookOpen,
  Info,
} from 'lucide-react';
import { analyzeInvestigation } from '../services/investigation';
import {
  InvestigationResponse,
  EvidenceRecord,
  InvestigationHypothesis,
} from '../types/api';
import { EvidencePanel } from '../components/common/EvidencePanel';
import { InvestigationPath } from '../components/intelligence/InvestigationPath';
import { IntelligenceStage, StageId } from '../components/intelligence/IntelligenceStage';

interface InvestigationsPageProps {
  onNavigate: (route: string) => void;
  onAskQuery: (query: string) => void;
}

export const InvestigationsPage: React.FC<InvestigationsPageProps> = ({
  onNavigate,
  onAskQuery,
}) => {
  const [query, setQuery] = useState('');
  const [explanationLevel, setExplanationLevel] = useState<'manager' | 'analyst' | 'technical' | 'simple'>('manager');
  const [referenceDate, setReferenceDate] = useState('');
  const [showFormSettings, setShowFormSettings] = useState(false);

  const [response, setResponse] = useState<InvestigationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorDetails, setErrorDetails] = useState<any>(null);
  const [lastAttemptedQuery, setLastAttemptedQuery] = useState('');

  const [activeEvidence, setActiveEvidence] = useState<EvidenceRecord | null>(null);
  const [selectedHypothesis, setSelectedHypothesis] = useState<InvestigationHypothesis | null>(null);
  const [expandedSteps, setExpandedSteps] = useState(false);
  const [expandedDiagnostics, setExpandedDiagnostics] = useState(false);

  // Live Analytical Progression Telemetry
  const [executionStage, setExecutionStage] = useState<StageId>('understand');
  const [stageStatusMessage, setStageStatusMessage] = useState('');

  useEffect(() => {
    if (!loading) {
      setExecutionStage('understand');
      return;
    }

    setExecutionStage('understand');
    setStageStatusMessage('Resolving inquiry semantics, time intervals & baseline benchmarks...');

    const t1 = setTimeout(() => {
      setExecutionStage('investigate');
      setStageStatusMessage('Decomposing category contribution, unit velocity & price-volume-mix factors...');
    }, 1200);

    const t2 = setTimeout(() => {
      setExecutionStage('validate');
      setStageStatusMessage('Auditing mathematical evidence & testing causal hypothesis tournament...');
    }, 2800);

    const t3 = setTimeout(() => {
      setExecutionStage('decide');
      setStageStatusMessage('Assembling audited conclusions, causality safeguards & proactive avenues...');
    }, 4500);

    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
    };
  }, [loading]);

  // Handle escape key to close modals
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (selectedHypothesis) setSelectedHypothesis(null);
        if (activeEvidence) setActiveEvidence(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedHypothesis, activeEvidence]);

  const sampleArchetypes = [
    {
      code: 'PVM',
      title: 'Price-Volume-Mix',
      query: 'Investigate price volume mix variance in revenue',
      description: 'Isolate whether revenue shifts stem from pure pricing, unit sales changes, or customer basket composition.',
      badgeColor: 'border-cyan-500/30 bg-cyan-950/70 text-cyan-400',
    },
    {
      code: 'GPM',
      title: 'Margin Dilution',
      query: 'Investigate gross margin variance between periods',
      description: 'Decompose supplier cost inflation, promotional discount erosion, and tier profitability.',
      badgeColor: 'border-emerald-500/30 bg-emerald-950/70 text-emerald-400',
    },
    {
      code: 'MIX',
      title: 'Category Shifts',
      query: 'Analyze category mix impact on average order value',
      description: 'Trace demand migration between product departments and measure cannibalization risks.',
      badgeColor: 'border-violet-500/30 bg-violet-950/70 text-violet-400',
    },
    {
      code: 'VOL',
      title: 'Unit Velocity',
      query: 'What drove changes in product unit volume?',
      description: 'Analyze transaction frequency and stockout-constrained demand bottlenecks across catalog tiers.',
      badgeColor: 'border-amber-500/30 bg-amber-950/70 text-amber-400',
    },
  ];

  const sampleQuestions = [
    'Why did revenue decline in recent months?',
    'Investigate gross margin variance between periods',
    'What drove changes in product unit volume?',
    'Analyze category mix impact on average order value',
  ];

  const handleRunInvestigation = async (
    diagnosticQuery: string,
    overrideLevel?: 'manager' | 'analyst' | 'technical' | 'simple'
  ) => {
    if (!diagnosticQuery.trim() || loading) return;
    setLoading(true);
    setError(null);
    setErrorDetails(null);
    setLastAttemptedQuery(diagnosticQuery);

    const targetLevel = overrideLevel || explanationLevel;

    try {
      const res = await analyzeInvestigation({
        query: diagnosticQuery,
        explanation_level: targetLevel,
        reference_date: referenceDate.trim() ? referenceDate.trim() : null,
      });
      setResponse(res);
      setQuery(diagnosticQuery);
    } catch (err: any) {
      const errorMessage = err?.message || 'Failed to execute diagnostic investigation.';
      setError(errorMessage);
      setErrorDetails({
        endpoint: '/api/v1/investigation/analyze',
        status: err?.status || 500,
        query: diagnosticQuery,
        explanation_level: targetLevel,
        reference_date: referenceDate.trim() || null,
        timestamp: new Date().toISOString(),
        rawMessage: errorMessage,
      });
    } finally {
      setLoading(false);
    }
  };

  const handleResetDiagnostic = () => {
    setResponse(null);
    setError(null);
    setErrorDetails(null);
    setSelectedHypothesis(null);
    setActiveEvidence(null);
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Executive Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-elevated pb-5">
        <div>
          <div className="inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-800/50 text-cyan-400 font-mono text-[11px] font-semibold mb-2">
            <SearchCode className="w-3.5 h-3.5" />
            <span>DIAGNOSTIC ROOT-CAUSE ENGINE</span>
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight font-sans">
            Diagnostic Business Investigations
          </h1>
          <p className="text-xs text-slate-400 mt-1 max-w-2xl font-sans">
            Answer &quot;Why did this happen?&quot; by decomposing variance across category contribution, price/volume/mix (PVM), and customer cohorts with strict causality safeguards.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {(response || error) && (
            <button
              onClick={handleResetDiagnostic}
              className="btn-secondary text-xs h-9 inline-flex items-center gap-1.5"
              title="Clear active results and start new diagnostic"
            >
              <RefreshCw className="w-3.5 h-3.5 text-slate-400" />
              <span>New Diagnostic</span>
            </button>
          )}

          <button
            onClick={() => onNavigate('/forecasts')}
            className="btn-secondary text-xs h-9 inline-flex items-center gap-1.5"
            title="Switch to prospective forecasting engine"
          >
            <TrendingUp className="w-3.5 h-3.5 text-violet-400" />
            <span>Forecast Horizon</span>
          </button>

          <button
            onClick={() => onAskQuery(query.trim() || 'Help me investigate business variance and root causes')}
            className="btn-secondary text-xs h-9 inline-flex items-center gap-1.5"
            title="Ask questions in continuous conversational console"
          >
            <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
            <span>Console Inquiry</span>
          </button>
        </div>
      </div>

      {/* Investigation Prompt Formulation Form */}
      <section className="rounded-2xl border border-surface-elevated bg-surface/75 shadow-obsidian p-5 sm:p-6 space-y-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleRunInvestigation(query);
          }}
          className="space-y-3"
        >
          <div className="flex flex-col sm:flex-row gap-2">
            <div className="relative flex-1">
              <input
                id="investigation-query-input"
                type="text"
                placeholder="e.g. Why did revenue decline in August? or Investigate margin dilution"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                disabled={loading}
                className="input-obsidian text-sm h-11 w-full pl-3 pr-8"
              />
              {query && !loading && (
                <button
                  type="button"
                  onClick={() => setQuery('')}
                  aria-label="Clear query input"
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors p-1"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setShowFormSettings(!showFormSettings)}
                className={`btn-secondary text-xs h-11 px-3 inline-flex items-center gap-1.5 ${
                  showFormSettings || referenceDate || explanationLevel !== 'manager'
                    ? 'border-cyan-500/50 text-cyan-300 bg-cyan-950/30'
                    : ''
                }`}
                title="Configure explanation depth and reference anchor date"
              >
                <SlidersHorizontal className="w-3.5 h-3.5 text-slate-400" />
                <span className="hidden sm:inline">Settings</span>
                {(referenceDate || explanationLevel !== 'manager') && (
                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                )}
              </button>

              <button
                type="submit"
                disabled={loading || !query.trim()}
                className="btn-primary text-xs h-11 px-5 whitespace-nowrap inline-flex items-center gap-2"
              >
                <SearchCode className="w-4 h-4" />
                <span>{loading ? 'Investigating...' : 'Launch Diagnostic'}</span>
              </button>
            </div>
          </div>

          {/* Collapsible Inquiry Configuration Parameters */}
          {showFormSettings && (
            <div className="p-4 rounded-xl bg-void/70 border border-surface-elevated grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs font-sans animate-in fade-in duration-150">
              <div className="space-y-1.5">
                <label htmlFor="explanation-level-select" className="text-slate-300 font-semibold block text-[11px] font-mono uppercase tracking-wider">
                  Audience Depth:
                </label>
                <select
                  id="explanation-level-select"
                  value={explanationLevel}
                  onChange={(e) => setExplanationLevel(e.target.value as any)}
                  className="input-obsidian text-xs h-9 w-full bg-surface"
                >
                  <option value="manager">Management Summary (Actionable drivers & business impact)</option>
                  <option value="analyst">Financial Analyst (Full variance bridge & percentage contributions)</option>
                  <option value="technical">Data Engineering (Query details, schema parameters & trace)</option>
                  <option value="simple">Executive Digest (High-level findings takeaway)</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label htmlFor="reference-date-input" className="text-slate-300 font-semibold block text-[11px] font-mono uppercase tracking-wider">
                  Anchor Reference Date (Optional):
                </label>
                <div className="relative">
                  <input
                    id="reference-date-input"
                    type="date"
                    value={referenceDate}
                    onChange={(e) => setReferenceDate(e.target.value)}
                    placeholder="YYYY-MM-DD"
                    className="input-obsidian text-xs h-9 w-full pl-8"
                  />
                  <Calendar className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
                  {referenceDate && (
                    <button
                      type="button"
                      onClick={() => setReferenceDate('')}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 p-0.5"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Quick Preset Diagnostic Inquiries */}
          <div className="flex flex-wrap items-center gap-2 text-xs pt-1">
            <span className="text-slate-500 font-mono text-[11px]">Recommended Diagnostic Queries:</span>
            {sampleQuestions.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => {
                  setQuery(q);
                  handleRunInvestigation(q);
                }}
                className="px-2.5 py-1 rounded-lg bg-void/80 hover:bg-surface-elevated/70 border border-surface-elevated hover:border-cyan-500/40 text-slate-300 hover:text-cyan-300 text-[11px] transition-colors font-sans"
              >
                {q}
              </button>
            ))}
          </div>
        </form>
      </section>

      {/* Genuine Execution Progression Telemetry */}
      {loading && (
        <IntelligenceStage
          currentStage={executionStage}
          statusMessage={stageStatusMessage}
          isExecuting={true}
        />
      )}

      {/* Honest Diagnostic Engine Notice (on Error / Database Offline) */}
      {error && !loading && (
        <div
          role="alert"
          className="rounded-2xl border border-rose-500/30 bg-rose-950/20 p-5 sm:p-6 space-y-4 animate-in fade-in duration-200"
        >
          <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
            <div className="flex items-start gap-3">
              <div className="p-2.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-400 shrink-0 mt-0.5">
                <AlertTriangle className="w-5 h-5" />
              </div>
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-semibold text-rose-200 font-sans">
                    Diagnostic Engine Notice: Telemetry Unreachable
                  </h3>
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase bg-rose-950/80 border border-rose-800 text-rose-300">
                    HTTP 500 / Database Offline
                  </span>
                </div>
                <p className="text-xs text-rose-300/90 leading-relaxed font-sans max-w-2xl">
                  The multi-step diagnostic investigation engine could not execute deterministic variance decomposition for{' '}
                  <strong className="text-white font-mono font-normal">&quot;{lastAttemptedQuery || query}&quot;</strong>.
                  This occurs when the underlying transactional database or line-item telemetry tables are offline.
                </p>
              </div>
            </div>

            <button
              onClick={() => handleRunInvestigation(lastAttemptedQuery || query)}
              disabled={loading}
              className="btn-secondary text-xs h-9 inline-flex items-center gap-1.5 shrink-0 border-rose-700/50 hover:bg-rose-900/30 text-rose-200 self-start"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              <span>Retry Diagnostic</span>
            </button>
          </div>

          {/* Operational Recovery Shortcuts */}
          <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-rose-900/30">
            <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400">
              Operational Diagnostics:
            </span>
            <button
              onClick={() => onNavigate('/data')}
              className="btn-secondary text-xs h-8 inline-flex items-center gap-1.5"
            >
              <Database className="w-3.5 h-3.5 text-cyan-400" />
              <span>Data Gateway (Verify Telemetry Ingestion)</span>
            </button>
            <button
              onClick={() => onNavigate('/knowledge')}
              className="btn-secondary text-xs h-8 inline-flex items-center gap-1.5"
            >
              <BookOpen className="w-3.5 h-3.5 text-emerald-400" />
              <span>KPI Dictionary (Verify Semantic Formulas)</span>
            </button>
          </div>

          {/* Expandable Technical Diagnostics Drawer */}
          <div className="pt-2 border-t border-rose-900/30">
            <button
              onClick={() => setExpandedDiagnostics(!expandedDiagnostics)}
              className="inline-flex items-center gap-1.5 text-[11px] font-mono text-rose-400/80 hover:text-rose-300 transition-colors"
            >
              {expandedDiagnostics ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              <span>{expandedDiagnostics ? 'Hide Technical Diagnostics' : 'Inspect Technical Diagnostics & Stack Telemetry'}</span>
            </button>

            {expandedDiagnostics && (
              <div className="mt-2.5 p-4 rounded-xl bg-void/90 border border-surface-elevated font-mono text-[11px] text-slate-300 space-y-2 overflow-x-auto">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[10px] text-slate-400 pb-2 border-b border-surface-elevated">
                  <div><span className="text-slate-500">API Endpoint:</span> POST /api/v1/investigation/analyze</div>
                  <div><span className="text-slate-500">HTTP Status:</span> 500 Internal Server Error</div>
                  <div><span className="text-slate-500">Explanation Depth:</span> {explanationLevel}</div>
                  <div><span className="text-slate-500">Timestamp:</span> {errorDetails?.timestamp || new Date().toISOString()}</div>
                </div>
                <div className="text-xs text-rose-300">
                  <strong>Error Details:</strong> {error}
                </div>
                <div className="p-2.5 rounded bg-surface/60 border border-surface-elevated text-[10px] text-slate-400">
                  <strong className="text-amber-400">Resolution Guidance:</strong> NEXUS enforces strict evidence-grounded truth rules without fabricating dummy data. When backend PostgreSQL services are offline, analytical queries halt safely rather than synthesizing hallucinatory metrics.
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Initial / Empty State: Supported Diagnostic Archetypes */}
      {!response && !loading && (
        <div className="space-y-6">
          <div className="rounded-2xl border border-surface-elevated bg-surface/75 shadow-obsidian p-6 sm:p-8 space-y-4">
            <div className="border-b border-surface-elevated pb-3">
              <span className="text-[10px] font-mono uppercase text-cyan-400 font-semibold tracking-wider flex items-center gap-1.5">
                <SearchCode className="w-3.5 h-3.5" />
                <span>DIAGNOSTIC FRAMEWORK TEMPLATES — Select a framework to formulate an empirical query</span>
              </span>
              <h2 className="text-base font-bold text-white font-sans mt-1">
                Root Cause & Variance Decomposition Methods
              </h2>
              <p className="text-xs text-slate-400 font-sans">
                Select an analytical framework or enter a custom question above. NEXUS constructs a hypothesis tree and evaluates causal boundaries against real transactional telemetry.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 font-sans text-xs">
              {sampleArchetypes.map((archetype) => (
                <div
                  key={archetype.code}
                  onClick={() => {
                    setQuery(archetype.query);
                    handleRunInvestigation(archetype.query);
                  }}
                  className="p-4 rounded-xl bg-void/60 border border-surface-elevated hover:border-cyan-500/50 cursor-pointer transition-all space-y-2 group"
                >
                  <div className={`w-8 h-8 rounded-lg border flex items-center justify-center text-xs font-mono font-bold group-hover:scale-105 transition-transform ${archetype.badgeColor}`}>
                    {archetype.code}
                  </div>
                  <h3 className="font-bold text-white group-hover:text-cyan-300 transition-colors">
                    {archetype.title}
                  </h3>
                  <p className="text-slate-400 text-[11px] leading-relaxed">
                    {archetype.description}
                  </p>
                  <div className="pt-1 text-[10px] font-mono text-cyan-400/80 group-hover:text-cyan-300 flex items-center gap-1">
                    <span>Execute Template</span>
                    <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Structured Diagnostic Results */}
      {response && !loading && (
        <div className="space-y-6 animate-in fade-in duration-200">
          {/* Executive Diagnostic Briefing Takeaway */}
          <div className="rounded-2xl border border-cyan-500/30 bg-cyan-950/20 shadow-obsidian p-6 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-mono uppercase tracking-wider text-cyan-400 font-semibold flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5" />
                <span>Executive Diagnostic Summary</span>
              </span>
              <div className="flex flex-wrap items-center gap-2">
                <span className="px-2.5 py-0.5 rounded-full bg-cyan-950/80 border border-cyan-700/60 text-cyan-300 text-xs font-mono">
                  Archetype: {response.investigation_type}
                </span>
                {response.stopped_reason && (
                  <span className="px-2.5 py-0.5 rounded-full bg-surface-elevated border border-surface-highlight text-slate-300 text-xs font-mono">
                    Halt: {response.stopped_reason.replace(/_/g, ' ')}
                  </span>
                )}
              </div>
            </div>
            <p className="text-sm sm:text-base font-medium text-slate-100 leading-relaxed font-sans">
              {response.summary}
            </p>
          </div>

          {/* SIGNATURE VISUAL DIAGNOSTIC PATH */}
          <InvestigationPath
            rootSymptom={query || response.summary}
            observations={response.observations || []}
            hypotheses={response.hypotheses || []}
            onSelectHypothesis={(hyp) => setSelectedHypothesis(hyp)}
          />

          {/* Audited Conclusions & Strict Causality Safeguards */}
          <section className="rounded-2xl border border-surface-elevated bg-surface/75 shadow-obsidian p-6 space-y-4">
            <div className="border-b border-surface-elevated pb-3">
              <h2 className="text-sm font-semibold text-white flex items-center gap-2 font-sans">
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                <span>Audited Conclusions & Causality Safeguards</span>
              </h2>
              <p className="text-xs text-slate-400 mt-0.5 font-sans">
                Conclusions are strictly bounded: correlation and statistical association do not establish absolute causation.
              </p>
            </div>

            <div className="space-y-3">
              {response.conclusions?.map((c) => {
                const conclusionId = c.conclusion_id || (c as any).id || 'CONC';
                const confidence = String(c.confidence_rating || (c as any).strength || 'medium').toLowerCase();
                const displayConfidence = String(c.confidence_rating || (c as any).strength || 'medium');
                const driver = c.primary_driver || (c as any).hypothesis_id || 'Measured Variance Factor';
                const caveat = c.causality_caveat || (c as any).causal_caveat;
                const sharePct = (c as any).contribution_share_pct;

                return (
                  <div
                    key={conclusionId}
                    className="p-4 rounded-xl bg-void/60 border border-surface-elevated space-y-2 text-xs"
                  >
                    <p className="text-slate-100 font-medium leading-relaxed font-sans text-sm">{c.statement}</p>
                    <div className="flex flex-wrap items-center gap-2 pt-1 font-mono text-[11px]">
                      <span className="px-2.5 py-1 rounded bg-surface border border-surface-elevated text-slate-300">
                        Primary Driver: <strong className="text-white">{driver}</strong>
                      </span>
                      {sharePct !== undefined && sharePct !== null && (
                        <span className="px-2.5 py-1 rounded bg-cyan-950/60 border border-cyan-700/60 text-cyan-300 font-bold">
                          Attributed Share: {typeof sharePct === 'number' ? `${sharePct.toFixed(1)}%` : String(sharePct)}
                        </span>
                      )}
                      <span
                        className={`px-2.5 py-1 rounded border font-semibold uppercase ${
                          confidence === 'high' || confidence === 'direct' || confidence === 'strong'
                            ? 'bg-emerald-950/60 border-emerald-500/40 text-emerald-300'
                            : confidence === 'medium' || confidence === 'moderate'
                            ? 'bg-cyan-950/60 border-cyan-500/40 text-cyan-300'
                            : 'bg-amber-950/60 border-amber-500/40 text-amber-300'
                        }`}
                      >
                        Confidence: {displayConfidence}
                      </span>
                    </div>

                    {caveat && (
                      <div className="p-3 rounded-lg bg-amber-950/20 border border-amber-800/30 text-amber-300 text-[11px] flex items-start gap-2 mt-2">
                        <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5 text-amber-400" />
                        <span>{caveat}</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>

          {/* Grounded Narrative Explanation (if returned by backend) */}
          {response.explanation && (
            <section className="rounded-2xl border border-surface-elevated bg-surface/75 shadow-obsidian p-6 space-y-3 font-sans">
              <div className="border-b border-surface-elevated pb-2.5 flex items-center justify-between">
                <h3 className="text-xs font-mono uppercase tracking-wider text-slate-300 font-semibold flex items-center gap-2">
                  <BookOpen className="w-3.5 h-3.5 text-cyan-400" />
                  <span>Grounded Diagnostic Narrative</span>
                </h3>
                <span className="text-[10px] font-mono text-slate-500">
                  Level: {explanationLevel.toUpperCase()}
                </span>
              </div>
              <div className="text-xs sm:text-sm text-slate-200 leading-relaxed space-y-3 whitespace-pre-line">
                {response.explanation}
              </div>
            </section>
          )}

          {/* Identified Evidence Gaps */}
          {response.evidence_gaps && response.evidence_gaps.length > 0 && (
            <div className="rounded-2xl border border-amber-900/30 bg-amber-950/10 shadow-obsidian p-5 space-y-2 text-xs">
              <span className="font-semibold text-amber-300 flex items-center gap-1.5 font-sans">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                <span>Identified Evidence Gaps & Unmeasured Telemetry</span>
              </span>
              <ul className="list-disc list-inside space-y-1 text-slate-300 text-[11px] font-sans">
                {response.evidence_gaps.map((gap, idx) => (
                  <li key={gap.gap_id || `gap-${idx}`}>
                    {gap.area && gap.area.trim() ? (
                      <strong className="text-slate-200">{gap.area}: </strong>
                    ) : null}
                    {gap.description}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Model Assumptions & Analytical Boundaries */}
          {((response.assumptions && response.assumptions.length > 0) || (response.limitations && response.limitations.length > 0)) && (
            <div className="p-4 rounded-xl bg-void/60 border border-surface-elevated space-y-2 text-xs font-sans">
              <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 flex items-center gap-1.5 font-semibold">
                <Info className="w-3.5 h-3.5 text-slate-400" />
                <span>Model Assumptions & Diagnostic Boundaries</span>
              </span>
              <ul className="list-disc list-inside text-slate-300 space-y-1 text-[11px]">
                {response.assumptions?.map((asm, aidx) => (
                  <li key={`asm-${aidx}`}>{asm}</li>
                ))}
                {response.limitations?.map((lim, lidx) => (
                  <li key={`lim-${lidx}`} className="text-amber-300/80">{lim}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Tool Step Execution Trace */}
          <div className="rounded-2xl border border-surface-elevated bg-surface/75 shadow-obsidian p-4">
            <button
              onClick={() => setExpandedSteps(!expandedSteps)}
              className="w-full flex items-center justify-between text-xs font-semibold text-slate-300 hover:text-white transition-colors"
            >
              <div className="flex items-center gap-2">
                <Layers className="w-4 h-4 text-cyan-400" />
                <span>Investigation Execution Trace ({response.investigation_steps?.length ?? 0} steps executed)</span>
              </div>
              {expandedSteps ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>

            {expandedSteps && (
              <div className="mt-3 space-y-2 pt-3 border-t border-surface-elevated text-xs">
                {response.investigation_steps?.map((step) => {
                  const stepNum = step.step_number || (step as any).step;
                  const toolName = step.tool_invoked || (step as any).tool;
                  const desc = step.description || (step as any).purpose;

                  return (
                    <div key={stepNum} className="flex items-start gap-2.5 text-[11px] font-mono text-slate-300 p-2 rounded bg-void/50 border border-surface-elevated">
                      <span className="text-cyan-400 font-bold shrink-0">Step {stepNum}:</span>
                      <div>
                        <span>{desc}</span>
                        <span className="text-slate-500 block text-[10px]">Tool: {toolName}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Proactive Follow-Up Inquiries */}
          {response.follow_up_questions && response.follow_up_questions.length > 0 && (
            <div className="rounded-2xl border border-surface-elevated bg-surface/75 shadow-obsidian p-5 space-y-2">
              <span className="text-[10px] font-mono text-slate-400 uppercase tracking-wider block font-semibold">
                RECOMMENDED PROACTIVE FOLLOW-UP INQUIRIES:
              </span>
              <div className="flex flex-wrap gap-2">
                {response.follow_up_questions.map((fq, fidx) => (
                  <button
                    key={fidx}
                    onClick={() => {
                      setQuery(fq);
                      handleRunInvestigation(fq);
                    }}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-void/70 hover:bg-surface-elevated/70 border border-surface-elevated hover:border-cyan-500/40 text-slate-300 hover:text-cyan-300 text-xs transition-colors font-sans"
                  >
                    <span>{fq}</span>
                    <ArrowRight className="w-3 h-3 text-cyan-400" />
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Provenance Inspection Trigger */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
            <span className="text-xs font-mono text-slate-500">
              {response.evidence?.length ?? 0} underlying SQL evidence records • {response.tools_used?.length ?? 0} analytical tools evaluated
            </span>

            {response.evidence && response.evidence.length > 0 && (
              <button
                onClick={() => setActiveEvidence(response.evidence[0])}
                className="btn-secondary text-xs h-9 inline-flex items-center gap-2"
              >
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                <span>Inspect Underlying SQL Evidence Record ({response.evidence.length})</span>
                <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
              </button>
            )}
          </div>
        </div>
      )}

      {/* Hypothesis Detail Inspector Modal */}
      {selectedHypothesis && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-void/80 backdrop-blur-sm animate-in fade-in duration-200"
          onClick={() => setSelectedHypothesis(null)}
        >
          <div
            className="w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-2xl border border-surface-elevated bg-surface p-6 space-y-4 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3 border-b border-surface-elevated pb-3">
              <div>
                <span className="text-[10px] font-mono uppercase tracking-wider text-cyan-400 font-semibold block">
                  HYPOTHESIS EVALUATION DOSSIER • {selectedHypothesis.hypothesis_id || (selectedHypothesis as any).id}
                </span>
                <h3 className="text-base font-bold text-white font-sans mt-0.5">
                  {selectedHypothesis.statement}
                </h3>
              </div>
              <button
                onClick={() => setSelectedHypothesis(null)}
                aria-label="Close hypothesis modal"
                className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-surface-elevated transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Evaluation Status & Evidence Strength */}
            <div className="flex flex-wrap items-center gap-2 font-mono text-xs">
              <span
                className={`px-2.5 py-1 rounded-full font-semibold uppercase border ${
                  selectedHypothesis.status === 'CONFIRMED' || selectedHypothesis.status === 'SUPPORTED'
                    ? 'bg-emerald-950/80 text-emerald-300 border-emerald-800'
                    : selectedHypothesis.status === 'PARTIALLY_SUPPORTED'
                    ? 'bg-cyan-950/80 text-cyan-300 border-cyan-800'
                    : selectedHypothesis.status === 'NOT_SUPPORTED' || selectedHypothesis.status === 'REJECTED'
                    ? 'bg-rose-950/80 text-rose-300 border-rose-800'
                    : 'bg-slate-800 text-slate-300 border-slate-700'
                }`}
              >
                Status: {selectedHypothesis.status}
              </span>

              {(selectedHypothesis as any).evidence_strength && (
                <span className="px-2.5 py-1 rounded-full bg-surface-elevated border border-surface-highlight text-slate-300">
                  Strength: {(selectedHypothesis as any).evidence_strength}
                </span>
              )}
            </div>

            {/* Confidence Justification */}
            {((selectedHypothesis as any).confidence_reason || selectedHypothesis.evidence_summary) && (
              <div className="p-3.5 rounded-xl bg-void/60 border border-surface-elevated space-y-1">
                <span className="text-[10px] font-mono uppercase text-slate-400 font-semibold block">
                  Evaluation Justification & Telemetry Finding:
                </span>
                <p className="text-xs text-slate-200 leading-relaxed font-sans">
                  {(selectedHypothesis as any).confidence_reason || selectedHypothesis.evidence_summary}
                </p>
              </div>
            )}

            {/* Supporting Evidence Items */}
            {selectedHypothesis.supporting_evidence && selectedHypothesis.supporting_evidence.length > 0 && (
              <div className="space-y-2">
                <span className="text-xs font-mono uppercase text-emerald-400 font-semibold block">
                  Supporting Empirical Evidence ({selectedHypothesis.supporting_evidence.length}):
                </span>
                <div className="space-y-1.5">
                  {selectedHypothesis.supporting_evidence.map((ev, idx) => (
                    <div key={idx} className="p-2.5 rounded-lg bg-surface-elevated/50 border border-emerald-900/40 text-xs font-sans space-y-1">
                      <div className="flex items-center justify-between font-mono text-[11px]">
                        <span className="text-emerald-300 font-semibold">{ev.metric || 'Measured Signal'}</span>
                        <span className="text-slate-400">Tool: {ev.tool_name || 'analytics'}</span>
                      </div>
                      <div className="text-slate-300 text-[11px]">
                        Value: <strong>{typeof ev.value === 'number' ? ev.value.toLocaleString() : String(ev.value)}</strong>
                        {ev.contribution_pct !== undefined && ev.contribution_pct !== null && (
                          <span className="ml-2 text-cyan-300 font-mono">({ev.contribution_pct}% contribution)</span>
                        )}
                      </div>
                      {ev.notes && <p className="text-slate-400 text-[10px]">{ev.notes}</p>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Contradicting Evidence Items */}
            {(selectedHypothesis as any).contradicting_evidence && (selectedHypothesis as any).contradicting_evidence.length > 0 && (
              <div className="space-y-2">
                <span className="text-xs font-mono uppercase text-rose-400 font-semibold block">
                  Contradicting Empirical Evidence ({(selectedHypothesis as any).contradicting_evidence.length}):
                </span>
                <div className="space-y-1.5">
                  {(selectedHypothesis as any).contradicting_evidence.map((ev: any, idx: number) => (
                    <div key={idx} className="p-2.5 rounded-lg bg-surface-elevated/50 border border-rose-900/40 text-xs font-sans space-y-1">
                      <div className="flex items-center justify-between font-mono text-[11px]">
                        <span className="text-rose-300 font-semibold">{ev.metric || 'Contradicting Signal'}</span>
                        <span className="text-slate-400">Tool: {ev.tool_name || 'analytics'}</span>
                      </div>
                      <div className="text-slate-300 text-[11px]">
                        Value: <strong>{String(ev.value)}</strong>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Modal Actions */}
            <div className="flex items-center justify-end gap-2 pt-3 border-t border-surface-elevated">
              {response?.evidence?.[0] && (
                <button
                  onClick={() => {
                    setActiveEvidence(response.evidence[0]);
                    setSelectedHypothesis(null);
                  }}
                  className="btn-secondary text-xs h-9 inline-flex items-center gap-1.5"
                >
                  <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Inspect Underlying SQL Record</span>
                </button>
              )}
              <button
                onClick={() => setSelectedHypothesis(null)}
                className="btn-primary text-xs h-9 px-4"
              >
                Close Dossier
              </button>
            </div>
          </div>
        </div>
      )}

      {/* SQL Evidence Modal */}
      {activeEvidence && (
        <EvidencePanel
          evidence={activeEvidence}
          ragEvidence={response?.rag_evidence}
          isOpen={Boolean(activeEvidence)}
          onClose={() => setActiveEvidence(null)}
          asModal
        />
      )}
    </div>
  );
};
