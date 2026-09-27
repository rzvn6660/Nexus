import React, { useState } from 'react';
import {
  SearchCode,
  ShieldCheck,
  AlertTriangle,
  TrendingUp,
  Sparkles,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { analyzeInvestigation } from '../services/investigation';
import { InvestigationResponse, EvidenceRecord } from '../types/api';
import { ErrorState } from '../components/common/ErrorState';
import { EvidencePanel } from '../components/common/EvidencePanel';
import { InvestigationPath } from '../components/intelligence/InvestigationPath';
import { IntelligenceStage } from '../components/intelligence/IntelligenceStage';
import { IntelligenceHeader } from '../components/intelligence/IntelligenceHeader';

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
  const [stageIndex, setStageIndex] = useState<'understand' | 'investigate' | 'validate' | 'decide'>('understand');
  const [stageMsg, setStageMsg] = useState('Formulating diagnostic hypothesis tree...');
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
    setStageIndex('understand');
    setStageMsg('Establishing empirical baseline and identifying primary variance...');

    const t1 = setTimeout(() => {
      setStageIndex('investigate');
      setStageMsg('Decomposing category contribution, price/volume/mix, and customer cohorts...');
    }, 700);

    const t2 = setTimeout(() => {
      setStageIndex('validate');
      setStageMsg('Evaluating statistical significance and applying causality safeguards...');
    }, 1400);

    try {
      const res = await analyzeInvestigation({
        query: diagnosticQuery,
        explanation_level: 'manager',
      });
      setResponse(res);
      setQuery(diagnosticQuery);
      setStageIndex('decide');
      setStageMsg('Investigation complete. Findings, hypotheses, and evidence bounded.');
    } catch (err: any) {
      setError(err?.message || 'Failed to execute diagnostic investigation.');
    } finally {
      clearTimeout(t1);
      clearTimeout(t2);
      setLoading(false);
    }
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* Header */}
      <IntelligenceHeader
        eyebrow="DIAGNOSTIC ROOT-CAUSE ENGINE"
        title="Diagnostic Business Investigations"
        subtitle='Answer "Why did this happen?" by decomposing variance across category contribution, price/volume/mix (PVM), and customer cohorts with strict causality safeguards.'
        icon={SearchCode}
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => onNavigate('/forecasts')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-surface hover:bg-surface-elevated border border-surface-elevated text-slate-300 text-xs font-medium transition-all"
            >
              <TrendingUp className="w-3.5 h-3.5 text-violet-400" />
              <span>Forecast Horizon</span>
            </button>
            <button
              onClick={() => onAskQuery(`Help me investigate business variance and root causes`)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-cyan-950/80 hover:bg-cyan-900 border border-brand-cyan/40 text-brand-cyan text-xs font-medium transition-all"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Console Inquiry</span>
            </button>
          </div>
        }
      />

      {/* Investigation Prompt Formulation Form */}
      <section className="p-6 rounded-3xl bg-surface/50 border border-surface-elevated space-y-3">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleRunInvestigation(query);
          }}
          className="space-y-3"
        >
          <div className="flex flex-col sm:flex-row gap-2">
            <input
              type="text"
              placeholder="e.g. Why did revenue decline in August?"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              disabled={loading}
              className="flex-1 rounded-xl bg-void border border-surface-highlight px-4 py-3 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-brand-cyan disabled:opacity-60 font-sans"
            />
            <button
              type="submit"
              disabled={loading || !query.trim()}
              className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl bg-cyan-600 hover:bg-cyan-500 disabled:bg-surface-elevated disabled:text-slate-600 text-white font-semibold text-xs shadow-md transition-all font-sans"
            >
              <SearchCode className="w-4 h-4" />
              <span>Launch Diagnostic</span>
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-slate-500 font-mono text-[11px]">Recommended Diagnostic Queries:</span>
            {sampleQuestions.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => handleRunInvestigation(q)}
                className="px-2.5 py-1 rounded-lg bg-surface hover:bg-surface-elevated border border-surface-elevated text-slate-300 hover:text-brand-cyan text-[11px] transition-colors"
              >
                {q}
              </button>
            ))}
          </div>
        </form>
      </section>

      {/* Execution Stages Telemetry */}
      {loading && (
        <IntelligenceStage
          currentStage={stageIndex}
          statusMessage={stageMsg}
          isExecuting={true}
        />
      )}

      {error && <ErrorState message={error} onRetry={() => handleRunInvestigation(query)} />}

      {/* Empty State / Initial Prompt */}
      {!response && !loading && !error && (
        <div className="rounded-3xl border border-surface-elevated bg-surface/30 p-8 sm:p-12 text-center max-w-xl mx-auto space-y-4">
          <div className="w-12 h-12 rounded-2xl bg-void border border-surface-elevated flex items-center justify-center mx-auto text-brand-cyan">
            <SearchCode className="w-6 h-6" />
          </div>
          <div className="space-y-1">
            <h3 className="text-base font-bold text-white font-sans">
              Ask NEXUS a business question to begin an investigation.
            </h3>
            <p className="text-xs text-slate-400 max-w-md mx-auto leading-relaxed">
              Formulate a question about metric changes, margin variances, or channel shifts above, or select one of the recommended diagnostic queries.
            </p>
          </div>
        </div>
      )}

      {/* Structured Diagnostic Results */}
      {response && !loading && (
        <div className="space-y-6 animate-in fade-in duration-200">
          {/* Executive Diagnostic Briefing Takeaway */}
          <div className="rounded-3xl border border-cyan-800/40 bg-cyan-950/20 p-6 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono uppercase tracking-wider text-brand-cyan font-semibold flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5" />
                <span>Executive Diagnostic Summary</span>
              </span>
              <span className="px-2.5 py-0.5 rounded-full bg-cyan-900/60 border border-cyan-700/60 text-brand-cyan text-xs font-mono">
                Archetype: {response.investigation_type}
              </span>
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
          />

          {/* 3. Audited Conclusions & Strict Causality Safeguards */}
          <section className="rounded-3xl border border-surface-elevated bg-surface/50 p-6 space-y-4">
            <div className="border-b border-surface-elevated pb-3">
              <h3 className="text-sm font-semibold text-white flex items-center gap-2 font-sans">
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
                  className="p-4 rounded-2xl bg-void/60 border border-surface-elevated space-y-2 text-xs"
                >
                  <p className="text-slate-100 font-medium leading-relaxed font-sans">{c.statement}</p>
                  <div className="flex flex-wrap items-center gap-2 pt-1 font-mono">
                    <span className="px-2 py-0.5 rounded bg-surface border border-surface-elevated text-slate-300 text-[11px]">
                      Primary Driver: {c.primary_driver}
                    </span>
                    <span className="px-2 py-0.5 rounded bg-cyan-950/80 border border-brand-cyan/30 text-brand-cyan text-[11px]">
                      Confidence: {c.confidence_rating}
                    </span>
                  </div>

                  {c.causality_caveat && (
                    <div className="p-3 rounded-xl bg-amber-950/20 border border-amber-800/30 text-amber-300 text-[11px] flex items-start gap-2 mt-2">
                      <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5 text-amber-400" />
                      <span>{c.causality_caveat}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* 4. Identified Evidence Gaps */}
          {response.evidence_gaps && response.evidence_gaps.length > 0 && (
            <div className="rounded-2xl border border-amber-900/30 bg-amber-950/10 p-5 space-y-2 text-xs">
              <span className="font-semibold text-amber-300 flex items-center gap-1.5 font-sans">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                <span>Identified Evidence Gaps & Unmeasured Telemetry</span>
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

          {/* 5. Tool Step Execution Trace */}
          <div className="rounded-2xl border border-surface-elevated bg-surface/30 p-4">
            <button
              onClick={() => setExpandedSteps(!expandedSteps)}
              className="w-full flex items-center justify-between text-xs font-semibold text-slate-300"
            >
              <span>Investigation Steps Trace ({response.investigation_steps?.length ?? 0} executed)</span>
              {expandedSteps ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>

            {expandedSteps && (
              <div className="mt-3 space-y-2 pt-2 border-t border-surface-elevated text-xs">
                {response.investigation_steps?.map((step) => (
                  <div key={step.step_number} className="flex items-start gap-2.5 text-[11px] font-mono text-slate-300">
                    <span className="text-brand-cyan font-bold shrink-0">Step {step.step_number}:</span>
                    <div>
                      <span>{step.description}</span>
                      <span className="text-slate-500 block">Tool: {step.tool_invoked}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Provenance Inspection Trigger */}
          {response.evidence && response.evidence.length > 0 && (
            <div className="flex justify-end">
              <button
                onClick={() => setActiveEvidence(response.evidence[0])}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-surface hover:bg-surface-elevated border border-surface-elevated text-slate-200 text-xs font-medium transition-all"
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
