import React, { useState } from 'react';
import {
  Sparkles,
  Send,
  ShieldCheck,
  SearchCode,
  TrendingUp,
  HelpCircle,
  Clock,
  ArrowRight,
} from 'lucide-react';
import { analyzeBusinessQuery } from '../services/agent';
import { AgentResponse, EvidenceRecord } from '../types/api';
import { formatDuration } from '../utils/formatters';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EvidencePanel } from '../components/common/EvidencePanel';

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
  const [error, setError] = useState<string | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceRecord | null>(null);

  const promptSuggestions = [
    'How did revenue perform this month?',
    'Why did gross margin decline in August?',
    'Which products are generating the highest profit?',
    'Forecast revenue for the next 3 months',
    'What is our current inventory turnover ratio and stock health?',
  ];

  const handleAsk = async (text: string) => {
    if (!text.trim() || loading) return;
    setLoading(true);
    setError(null);
    try {
      const res = await analyzeBusinessQuery({
        query: text,
        explanation_level: explanationLevel,
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
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* Header Workspace Section */}
      <section className="rounded-3xl border border-slate-800 bg-slate-900/80 p-6 sm:p-8 space-y-4">
        <div className="space-y-1">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-950/80 border border-cyan-800/80 text-cyan-400 text-xs font-mono font-medium">
            <Sparkles className="w-3.5 h-3.5" />
            <span>Agentic Business Intelligence Workspace</span>
          </div>
          <h2 className="text-2xl sm:text-3xl font-bold text-white tracking-tight">
            Ask NEXUS Intelligence
          </h2>
          <p className="text-xs sm:text-sm text-slate-400 max-w-2xl">
            Inquire in natural business terminology. Orchestrates deterministic SQL analytics,
            semantic ontology mappings, and business context RAG with verifiable provenance.
          </p>
        </div>

        {/* Query Input Box */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleAsk(query);
          }}
          className="space-y-3 pt-2"
        >
          <div className="relative">
            <textarea
              rows={3}
              placeholder="Ask a strategic business question (e.g. 'How did revenue perform this month, and what drove category changes?')..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              disabled={loading}
              className="w-full rounded-2xl bg-slate-950 border border-slate-700/80 p-4 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:opacity-60 resize-none font-sans"
            />

            <div className="flex flex-wrap items-center justify-between gap-2 pt-2 px-1">
              <div className="flex items-center gap-2 text-xs">
                <span className="text-slate-400">Explanation Depth:</span>
                <select
                  value={explanationLevel}
                  onChange={(e) => setExplanationLevel(e.target.value as any)}
                  className="rounded-lg bg-slate-900 border border-slate-700 px-2.5 py-1 text-xs text-slate-200 focus:outline-none"
                >
                  <option value="manager">Manager (Strategic)</option>
                  <option value="analyst">Analyst (Detailed)</option>
                  <option value="simple">Executive (Concise)</option>
                </select>
              </div>

              <button
                type="submit"
                disabled={loading || !query.trim()}
                className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-xs font-semibold shadow-md shadow-cyan-600/25 transition-all"
              >
                <Send className="w-4 h-4" />
                <span>Submit Query</span>
              </button>
            </div>
          </div>

          {/* Quick Prompts */}
          <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
            <span className="text-slate-400">Suggested Inquiries:</span>
            {promptSuggestions.map((prompt) => (
              <button
                key={prompt}
                type="button"
                onClick={() => handleAsk(prompt)}
                className="px-2.5 py-1 rounded-lg bg-slate-800/80 hover:bg-slate-700 border border-slate-700/80 text-slate-300 hover:text-cyan-300 text-[11px] transition-colors"
              >
                {prompt}
              </button>
            ))}
          </div>
        </form>
      </section>

      {loading && (
        <LoadingState
          message="Reasoning across semantic ontology and running analytics..."
          stepIndex={1}
          steps={[
            'Interpreting query semantics and temporal intervals...',
            'Executing deterministic analytics tools...',
            'Retrieving relevant business policies & documentation...',
            'Constructing verifiable evidence and response...',
          ]}
        />
      )}

      {error && <ErrorState message={error} onRetry={() => handleAsk(query)} />}

      {/* Answer Stream History */}
      <div className="space-y-6">
        {history.map((item, idx) => {
          const res = item.response;
          return (
            <article
              key={idx}
              className="rounded-3xl border border-slate-800 bg-slate-900/70 p-6 sm:p-8 space-y-6 animate-in fade-in duration-150"
            >
              {/* User Inquiry Header */}
              <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-xl bg-slate-800 flex items-center justify-center text-slate-300 font-mono font-bold text-xs">
                    Q
                  </div>
                  <h3 className="text-base font-semibold text-white">{item.query}</h3>
                </div>

                <div className="flex items-center gap-2">
                  <span className="px-2.5 py-0.5 rounded-full bg-cyan-950/80 border border-cyan-800/60 text-cyan-300 text-xs font-mono capitalize">
                    {res.intent?.replace('_', ' ') || 'Analysis'}
                  </span>
                  <span className="text-[11px] font-mono text-slate-400 flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {formatDuration(res.execution_metadata?.elapsed_ms)}
                  </span>
                </div>
              </div>

              {/* Clarification Alert (if query was ambiguous) */}
              {res.needs_clarification && res.clarification_prompt && (
                <div className="p-4 rounded-2xl bg-amber-950/30 border border-amber-800/50 text-amber-200 text-xs flex items-start gap-2.5">
                  <HelpCircle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-semibold block mb-0.5">Semantic Clarification Required:</span>
                    <span>{res.clarification_prompt}</span>
                  </div>
                </div>
              )}

              {/* Primary Grounded Narrative Answer */}
              <div className="space-y-3">
                <div className="prose prose-invert max-w-none text-slate-200 text-sm leading-relaxed whitespace-pre-wrap font-sans">
                  {res.answer}
                </div>
              </div>

              {/* Action Buttons for Next-Stage Intelligence */}
              <div className="flex flex-wrap items-center gap-2.5 pt-2 border-t border-slate-800/80">
                {res.evidence && res.evidence.length > 0 && (
                  <button
                    onClick={() => setSelectedEvidence(res.evidence[0])}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-medium transition-all"
                  >
                    <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                    <span>View Evidence ({res.evidence.length})</span>
                  </button>
                )}

                <button
                  onClick={() => onNavigate('/investigations')}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-medium transition-all"
                >
                  <SearchCode className="w-3.5 h-3.5 text-cyan-400" />
                  <span>Investigate Drivers</span>
                </button>

                <button
                  onClick={() => onNavigate('/forecasts')}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-medium transition-all"
                >
                  <TrendingUp className="w-3.5 h-3.5 text-violet-400" />
                  <span>Forecast Horizon</span>
                </button>
              </div>

              {/* Follow-Up Inquiries */}
              {res.follow_up_questions && res.follow_up_questions.length > 0 && (
                <div className="pt-3 border-t border-slate-800/60 space-y-2">
                  <span className="text-xs font-mono text-slate-400 uppercase tracking-wider block">
                    Recommended Follow-Up Inquiries:
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {res.follow_up_questions.map((fq, fidx) => (
                      <button
                        key={fidx}
                        onClick={() => handleAsk(fq)}
                        className="inline-flex items-center gap-1 px-3 py-1 rounded-lg bg-slate-950/80 hover:bg-slate-800 border border-slate-800 text-slate-300 hover:text-cyan-300 text-xs transition-colors"
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

      {/* Evidence Modal */}
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
