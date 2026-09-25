import React, { useState } from 'react';
import {
  SearchCode,
  ShieldCheck,
  CheckCircle2,
  XCircle,
  HelpCircle,
  AlertTriangle,
  TrendingUp,
  Layers,
  Sparkles,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { analyzeInvestigation } from '../services/investigation';
import { InvestigationResponse, EvidenceRecord } from '../types/api';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EvidencePanel } from '../components/common/EvidencePanel';

interface InvestigationsPageProps {
  onNavigate: (route: string) => void;
  onAskQuery: (query: string) => void;
}

export const InvestigationsPage: React.FC<InvestigationsPageProps> = ({
  onNavigate,
  onAskQuery,
}) => {
  const [query, setQuery] = useState('');
  const [response, setResponse] = useState<InvestigationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeEvidence, setActiveEvidence] = useState<EvidenceRecord | null>(null);
  const [expandedSteps, setExpandedSteps] = useState(false);

  const sampleQuestions = [
    'Why did revenue decline in recent months?',
    'Investigate gross margin variance between periods',
    'What drove changes in product unit volume?',
    'Analyze category mix impact on average order value',
  ];

  const handleRunInvestigation = async (diagnosticQuery: string) => {
    if (!diagnosticQuery.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await analyzeInvestigation({
        query: diagnosticQuery,
        explanation_level: 'manager',
      });
      setResponse(res);
      setQuery(diagnosticQuery);
    } catch (err: any) {
      setError(err?.message || 'Failed to execute diagnostic investigation.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* Header & Prompt Formulation */}
      <section className="rounded-3xl border border-slate-800 bg-slate-900/80 p-6 sm:p-8 space-y-4">
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-950/80 border border-cyan-800/80 text-cyan-400 text-xs font-mono font-medium">
              <SearchCode className="w-3.5 h-3.5" />
              <span>Phase 6 Diagnostic Engine</span>
            </div>
            <h2 className="text-2xl sm:text-3xl font-bold text-white tracking-tight">
              Diagnostic Business Investigations
            </h2>
            <p className="text-xs sm:text-sm text-slate-400 max-w-2xl">
              Answer <strong className="text-slate-300">"Why did this happen?"</strong> by decomposing
              variance across category contribution, price/volume/mix (PVM), and customer cohorts with strict causality safeguards.
            </p>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={() => onNavigate('/forecasts')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 text-xs font-medium transition-all"
            >
              <TrendingUp className="w-3.5 h-3.5 text-violet-400" />
              <span>Forecast Next</span>
            </button>
            <button
              onClick={() => onAskQuery(`Help me investigate business variance and root causes`)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-cyan-950/80 hover:bg-cyan-900/80 border border-cyan-800 text-cyan-300 text-xs font-medium transition-all"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Ask Analyst</span>
            </button>
          </div>
        </div>

        {/* Input Form */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleRunInvestigation(query);
          }}
          className="space-y-3 pt-2"
        >
          <div className="flex flex-col sm:flex-row gap-2">
            <input
              type="text"
              placeholder="e.g. Why did revenue decline in August?"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              disabled={loading}
              className="flex-1 rounded-xl bg-slate-950 border border-slate-700/80 px-4 py-3 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:opacity-60 font-sans"
            />
            <button
              type="submit"
              disabled={loading || !query.trim()}
              className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-xs font-semibold shadow-md shadow-cyan-600/25 transition-all"
            >
              <SearchCode className="w-4 h-4" />
              <span>Investigate</span>
            </button>
          </div>

          {/* Sample Prompts */}
          <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
            <span className="text-slate-400">Suggested Inquiries:</span>
            {sampleQuestions.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => handleRunInvestigation(q)}
                className="px-2.5 py-1 rounded-lg bg-slate-800/80 hover:bg-slate-700/80 border border-slate-700/80 text-slate-300 hover:text-cyan-300 text-[11px] transition-colors"
              >
                {q}
              </button>
            ))}
          </div>
        </form>
      </section>

      {/* Loading state with step progression */}
      {loading && (
        <LoadingState
          message="Running multi-step diagnostic investigation..."
          stepIndex={1}
          steps={[
            'Establishing empirical baseline and variance...',
            'Decomposing category and product contribution...',
            'Formulating and validating causal hypotheses...',
            'Auditing evidence gaps and causality caveats...',
          ]}
        />
      )}

      {error && <ErrorState message={error} onRetry={() => handleRunInvestigation(query)} />}

      {/* Investigation Results */}
      {response && !loading && (
        <div className="space-y-6 animate-in fade-in duration-200">
          {/* Executive Summary Takeaway */}
          <div className="rounded-3xl border border-cyan-800/40 bg-cyan-950/20 p-6 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono uppercase tracking-wider text-cyan-400 font-semibold flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5" />
                Diagnostic Takeaway
              </span>
              <span className="px-2.5 py-0.5 rounded-full bg-cyan-900/60 border border-cyan-700/60 text-cyan-200 text-xs font-mono">
                Archetype: {response.investigation_type}
              </span>
            </div>
            <p className="text-sm sm:text-base font-medium text-slate-100 leading-relaxed">
              {response.summary}
            </p>
          </div>

          {/* 1. Established Facts & Observations */}
          <section className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                <span>Established Empirical Facts (Observations)</span>
              </h3>
              <span className="text-xs font-mono text-slate-400">
                {response.observations?.length ?? 0} Measured Signals
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {response.observations?.map((obs) => (
                <div
                  key={obs.observation_id}
                  className="p-4 rounded-2xl bg-slate-950/60 border border-slate-800/80 space-y-2 text-xs"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-slate-200 capitalize">{obs.metric}</span>
                    <span
                      className={`font-mono px-2 py-0.5 rounded ${
                        obs.variance_pct < 0
                          ? 'bg-rose-950/80 text-rose-300 border border-rose-800/80'
                          : 'bg-emerald-950/80 text-emerald-300 border border-emerald-800/80'
                      }`}
                    >
                      {obs.variance_pct >= 0 ? '+' : ''}
                      {obs.variance_pct?.toFixed(1)}%
                    </span>
                  </div>
                  <p className="text-slate-300 leading-relaxed">{obs.finding}</p>
                  <div className="text-[11px] font-mono text-slate-400 pt-1">
                    Observed: {obs.observed_value?.toLocaleString()} • Baseline: {obs.baseline_value?.toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* 2. Tested Hypotheses Tournament */}
          <section className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
            <div className="border-b border-slate-800 pb-3">
              <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                <Layers className="w-4 h-4 text-cyan-400" />
                <span>Hypothesis Testing Results</span>
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Evaluation of candidate drivers against deterministic transactional data.
              </p>
            </div>

            <div className="space-y-3">
              {response.hypotheses?.map((hyp) => {
                let badgeClass = 'bg-slate-800 text-slate-300 border-slate-700';
                let Icon = HelpCircle;
                if (hyp.status === 'confirmed') {
                  badgeClass = 'bg-emerald-950/80 text-emerald-300 border-emerald-800';
                  Icon = CheckCircle2;
                } else if (hyp.status === 'rejected') {
                  badgeClass = 'bg-rose-950/80 text-rose-300 border-rose-800';
                  Icon = XCircle;
                }

                return (
                  <div
                    key={hyp.hypothesis_id}
                    className="p-4 rounded-2xl bg-slate-950/60 border border-slate-800/80 space-y-2 text-xs"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-slate-200">{hyp.statement}</span>
                      <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full border text-[11px] font-mono capitalize ${badgeClass}`}>
                        <Icon className="w-3.5 h-3.5" />
                        <span>{hyp.status}</span>
                      </span>
                    </div>
                    <p className="text-slate-300 leading-relaxed">{hyp.evidence_summary}</p>
                    <div className="text-[11px] font-mono text-slate-400 flex items-center gap-3 pt-1">
                      <span>Statistical Support: {(hyp.support_score * 100).toFixed(0)}%</span>
                      <span>•</span>
                      <span>Confidence: {(hyp.confidence * 100).toFixed(0)}%</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {/* 3. Audited Conclusions & Causality Safeguards */}
          <section className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
            <div className="border-b border-slate-800 pb-3">
              <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                <span>Audited Conclusions & Causality Safeguards</span>
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Conclusions are strictly bounded: correlation and statistical association do not establish absolute causation.
              </p>
            </div>

            <div className="space-y-3">
              {response.conclusions?.map((c) => (
                <div
                  key={c.conclusion_id}
                  className="p-4 rounded-2xl bg-slate-950/60 border border-slate-800/80 space-y-2 text-xs"
                >
                  <p className="text-slate-100 font-medium leading-relaxed">{c.statement}</p>
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <span className="px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300 text-[11px] font-mono">
                      Primary Driver: {c.primary_driver}
                    </span>
                    <span className="px-2 py-0.5 rounded bg-cyan-950/80 border border-cyan-800/80 text-cyan-300 text-[11px] font-mono">
                      Confidence: {c.confidence_rating}
                    </span>
                  </div>
                  {c.causality_caveat && (
                    <div className="p-2.5 rounded-xl bg-amber-950/20 border border-amber-800/30 text-amber-300/90 text-[11px] flex items-start gap-2 mt-2">
                      <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5 text-amber-400" />
                      <span>{c.causality_caveat}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* 4. Evidence Gaps (Honest Telemetry Boundaries) */}
          {response.evidence_gaps && response.evidence_gaps.length > 0 && (
            <div className="rounded-2xl border border-amber-900/30 bg-amber-950/10 p-5 space-y-2 text-xs">
              <span className="font-semibold text-amber-300 flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                Identified Evidence Gaps & Unmeasured Telemetry
              </span>
              <ul className="list-disc list-inside space-y-1 text-slate-300 text-[11px]">
                {response.evidence_gaps.map((gap) => (
                  <li key={gap.gap_id}>
                    <strong className="text-slate-200">{gap.area}: </strong>
                    {gap.description}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* 5. Investigation Sequence Steps */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
            <button
              onClick={() => setExpandedSteps(!expandedSteps)}
              className="w-full flex items-center justify-between text-xs font-semibold text-slate-300"
            >
              <span>Investigation Steps Trace ({response.investigation_steps?.length ?? 0} executed)</span>
              {expandedSteps ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>

            {expandedSteps && (
              <div className="mt-3 space-y-2 pt-2 border-t border-slate-800/60 text-xs">
                {response.investigation_steps?.map((step) => (
                  <div key={step.step_number} className="flex items-start gap-2.5 text-[11px] font-mono text-slate-300">
                    <span className="text-cyan-400 font-bold shrink-0">Step {step.step_number}:</span>
                    <div>
                      <span>{step.description}</span>
                      <span className="text-slate-400 block">Tool: {step.tool_invoked}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Evidence Inspector Trigger */}
          {response.evidence && response.evidence.length > 0 && (
            <div className="flex justify-end">
              <button
                onClick={() => setActiveEvidence(response.evidence[0])}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-medium transition-all"
              >
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                <span>Inspect Underlying SQL Evidence Record</span>
              </button>
            </div>
          )}
        </div>
      )}

      {/* Evidence Modal */}
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
