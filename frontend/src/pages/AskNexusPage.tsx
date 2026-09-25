import React, { useState } from 'react';
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
} from 'lucide-react';
import { analyzeBusinessQuery } from '../services/agent';
import { AgentResponse, EvidenceRecord } from '../types/api';
import { formatDuration } from '../utils/formatters';
import { ErrorState } from '../components/common/ErrorState';
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
  const [history, setHistory] = useState<Array<{ query: string; response: AgentResponse }>>([]);
  const [loading, setLoading] = useState(false);
  const [currentStage, setCurrentStage] = useState<StageId>('understand');
  const [stageMessage, setStageMessage] = useState<string>('Resolving natural language semantics to canonical metrics...');
  const [error, setError] = useState<string | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceRecord | null>(null);

  const suggestedQuestions = [
    'Why did margin fall this month?',
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
    setCurrentStage('understand');
    setStageMessage('Resolving canonical KPIs, date intervals, and domain ontology...');

    // Simulate clean safe progression for human-readable operations
    const t1 = setTimeout(() => {
      setCurrentStage('investigate');
      setStageMessage('Executing deterministic analytical queries and decomposing drivers...');
    }, 600);

    const t2 = setTimeout(() => {
      setCurrentStage('validate');
      setStageMessage('Cross-verifying row counts, cryptographic checksums, and business policies...');
    }, 1200);

    try {
      const res = await analyzeBusinessQuery({
        query: text,
        explanation_level: explanationLevel,
      });

      setCurrentStage('decide');
      setStageMessage('Structuring intelligence dossier with verifiable evidence...');

      setHistory((prev) => [{ query: text, response: res }, ...prev]);
      setQuery('');
    } catch (err: any) {
      setError(err?.message || 'Failed to process inquiry via NEXUS agent.');
    } finally {
      clearTimeout(t1);
      clearTimeout(t2);
      setLoading(false);
    }
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* 1. INTELLIGENCE CONSOLE HERO & PROMPT INPUT */}
      <section className="relative rounded-3xl p-6 sm:p-10 overflow-hidden bg-void-sub border border-surface-elevated shadow-2xl text-center space-y-6">
        <div className="absolute top-0 left-1/2 -translate-x-1/2 -mt-24 w-[500px] h-[300px] rounded-full bg-cyan-500/5 blur-3xl pointer-events-none" />

        <div className="relative z-10 max-w-2xl mx-auto space-y-2">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-950/80 border border-brand-cyan/40 text-brand-cyan text-xs font-mono font-medium">
            <Terminal className="w-3.5 h-3.5" />
            <span>NEXUS INTELLIGENCE CONSOLE</span>
          </div>

          <h1 className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight font-sans">
            What do you want to understand?
          </h1>

          <p className="text-xs sm:text-sm text-slate-400 font-sans">
            Inquire in natural business terminology. Orchestrates deterministic SQL analytics,
            semantic ontology mappings, and business context RAG with verifiable provenance.
          </p>
        </div>

        {/* Console Input Bar */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleAsk(query);
          }}
          className="relative z-10 max-w-3xl mx-auto space-y-3"
        >
          <div className="relative rounded-2xl bg-void border border-surface-highlight focus-within:border-brand-cyan focus-within:ring-1 focus-within:ring-brand-cyan transition-all shadow-xl">
            <textarea
              rows={2}
              placeholder="e.g. Why did gross margin decline, and which product categories drove the variance?"
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

            <div className="flex flex-wrap items-center justify-between gap-3 px-4 pb-3 pt-1 border-t border-surface-elevated/60 text-xs">
              <div className="flex items-center gap-2">
                <span className="text-slate-400 font-mono text-[11px]">Explanation Posture:</span>
                <select
                  value={explanationLevel}
                  onChange={(e) => setExplanationLevel(e.target.value as any)}
                  className="rounded-lg bg-surface border border-surface-elevated px-2.5 py-1 text-slate-200 text-xs focus:outline-none"
                >
                  <option value="manager">Manager (Strategic Briefing)</option>
                  <option value="analyst">Analyst (Detailed Breakdown)</option>
                  <option value="simple">Executive (Concise Summary)</option>
                </select>
              </div>

              <button
                type="submit"
                disabled={loading || !query.trim()}
                className="inline-flex items-center gap-2 px-5 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 disabled:bg-surface-elevated disabled:text-slate-600 text-white font-semibold text-xs shadow-md transition-all font-sans"
              >
                <Send className="w-3.5 h-3.5" />
                <span>Execute Analysis</span>
              </button>
            </div>
          </div>

          {/* Curated Suggested Strategic Inquiries */}
          <div className="flex flex-wrap items-center justify-center gap-2 pt-2 text-xs">
            <span className="text-slate-500 font-mono text-[11px]">Suggested Inquiries:</span>
            {suggestedQuestions.map((prompt) => (
              <button
                key={prompt}
                type="button"
                onClick={() => handleAsk(prompt)}
                className="px-2.5 py-1 rounded-lg bg-surface hover:bg-surface-elevated border border-surface-elevated text-slate-300 hover:text-brand-cyan text-[11px] transition-colors"
              >
                {prompt}
              </button>
            ))}
          </div>
        </form>
      </section>

      {/* 2. REASONING PROGRESSION STAGE (SAFE EXECUTION TELEMETRY) */}
      {loading && (
        <IntelligenceStage
          currentStage={currentStage}
          statusMessage={stageMessage}
          isExecuting={true}
        />
      )}

      {error && <ErrorState message={error} onRetry={() => handleAsk(query)} />}

      {/* 3. STRUCTURED INTELLIGENCE REPORT DOSSIERS */}
      <div className="space-y-6">
        {history.map((item, idx) => {
          const res = item.response;

          return (
            <article
              key={idx}
              className="rounded-3xl border border-surface-elevated bg-surface/50 p-6 sm:p-8 space-y-6 animate-in fade-in duration-150"
            >
              {/* Dossier Header: Original Inquiry & Metadata */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-surface-elevated pb-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono uppercase tracking-widest text-brand-cyan font-semibold">
                      INQUIRY DOSSIER
                    </span>
                    <span className="text-slate-600">•</span>
                    <span className="text-[11px] font-mono text-slate-400 capitalize">
                      {res.intent?.replace('_', ' ') || 'Strategic Analysis'}
                    </span>
                  </div>
                  <h3 className="text-base sm:text-lg font-bold text-white font-sans">
                    "{item.query}"
                  </h3>
                </div>

                <div className="flex items-center gap-2 shrink-0 text-xs font-mono text-slate-400">
                  <Clock className="w-3.5 h-3.5 text-slate-500" />
                  <span>{formatDuration(res.execution_metadata?.elapsed_ms)}</span>
                </div>
              </div>

              {/* Semantic Clarification Alert (if ambiguous) */}
              {res.needs_clarification && res.clarification_prompt && (
                <div className="p-4 rounded-2xl bg-amber-950/30 border border-amber-800/50 text-amber-200 text-xs flex items-start gap-3">
                  <HelpCircle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <span className="font-semibold block text-amber-300">
                      Ambiguity Detected — Clarification Required:
                    </span>
                    <p className="text-slate-300 font-sans leading-relaxed">
                      {res.clarification_prompt}
                    </p>
                  </div>
                </div>
              )}

              {/* 1. NEXUS Grounded Narrative Findings */}
              <div className="space-y-2">
                <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                  <FileText className="w-3.5 h-3.5 text-brand-cyan" />
                  <span>NEXUS Analytical Finding</span>
                </span>
                <div className="p-5 rounded-2xl bg-void/80 border border-surface-elevated text-xs sm:text-sm text-slate-200 leading-relaxed whitespace-pre-wrap font-sans">
                  {res.answer}
                </div>
              </div>

              {/* 2. Structured Provenance & Action Triggers */}
              <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-surface-elevated">
                <div className="flex flex-wrap items-center gap-2">
                  {res.evidence && res.evidence.length > 0 && (
                    <button
                      onClick={() => setSelectedEvidence(res.evidence[0])}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-surface-elevated hover:bg-surface-highlight border border-surface-highlight text-slate-200 text-xs font-medium transition-all"
                    >
                      <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                      <span>Inspect SQL Evidence ({res.evidence.length})</span>
                    </button>
                  )}

                  <button
                    onClick={() => onNavigate('/investigations')}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-surface-elevated hover:bg-surface-highlight border border-surface-highlight text-slate-200 text-xs font-medium transition-all"
                  >
                    <SearchCode className="w-3.5 h-3.5 text-brand-cyan" />
                    <span>Investigate Root Causes</span>
                  </button>

                  <button
                    onClick={() => onNavigate('/forecasts')}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-surface-elevated hover:bg-surface-highlight border border-surface-highlight text-slate-200 text-xs font-medium transition-all"
                  >
                    <TrendingUp className="w-3.5 h-3.5 text-violet-400" />
                    <span>Forecast Trend</span>
                  </button>
                </div>

                <span className="text-[11px] font-mono text-slate-500">
                  {res.tools_used?.length ?? res.execution_metadata?.tools_executed?.length ?? 0} Analytical Tools Evaluated
                </span>
              </div>

              {/* 3. Follow-Up Inquiries */}
              {res.follow_up_questions && res.follow_up_questions.length > 0 && (
                <div className="pt-3 border-t border-surface-elevated/60 space-y-2">
                  <span className="text-[10px] font-mono text-slate-400 uppercase tracking-wider block">
                    Recommended Follow-Up Inquiries:
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {res.follow_up_questions.map((fq, fidx) => (
                      <button
                        key={fidx}
                        onClick={() => handleAsk(fq)}
                        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl bg-void hover:bg-surface border border-surface-elevated text-slate-300 hover:text-brand-cyan text-xs transition-colors"
                      >
                        <span>{fq}</span>
                        <ArrowRight className="w-3 h-3 text-brand-cyan" />
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
          isOpen={Boolean(selectedEvidence)}
          onClose={() => setSelectedEvidence(null)}
          asModal
        />
      )}
    </div>
  );
};
