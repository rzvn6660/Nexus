import React, { useState, useEffect, useCallback } from 'react';
import {
  History,
  FileText,
  Download,
  CheckCircle2,
  Filter,
  UserCheck,
} from 'lucide-react';
import {
  listHistoricalAnalyses,
  getAnalysisDetail,
  listDecisionRecords,
  reviewDecisionRecord,
  exportAnalysisReport,
} from '../services/history';
import {
  AnalysisRunItem,
  AnalysisRunDetail,
  DecisionRecordItem,
  DecisionReviewRequest,
} from '../types/api';
import { formatDate, formatDuration } from '../utils/formatters';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { DecisionCard } from '../components/intelligence/DecisionCard';
import { IntelligenceHeader } from '../components/intelligence/IntelligenceHeader';

export const HistoryPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'decisions' | 'analyses'>('decisions');

  // Decision state
  const [decisions, setDecisions] = useState<DecisionRecordItem[]>([]);
  const [decisionFilter, setDecisionFilter] = useState<string>('all');
  const [loadingDecisions, setLoadingDecisions] = useState(true);

  // Analysis state
  const [analyses, setAnalyses] = useState<AnalysisRunItem[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [runDetail, setRunDetail] = useState<AnalysisRunDetail | null>(null);
  const [loadingAnalyses, setLoadingAnalyses] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [downloadingReport, setDownloadingReport] = useState(false);

  // Load Decisions
  const fetchDecisions = useCallback(async () => {
    setLoadingDecisions(true);
    try {
      const data = await listDecisionRecords({
        status: decisionFilter === 'all' ? undefined : decisionFilter,
      });
      setDecisions(data);
    } catch (err: any) {
      setError(err?.message || 'Failed to load decision records.');
    } finally {
      setLoadingDecisions(false);
    }
  }, [decisionFilter]);

  // Load Analyses
  const fetchAnalyses = useCallback(async () => {
    setLoadingAnalyses(true);
    try {
      const data = await listHistoricalAnalyses({ limit: 50 });
      setAnalyses(data);
      if (data.length > 0 && !selectedRunId) {
        setSelectedRunId(data[0].id);
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load historical analyses.');
    } finally {
      setLoadingAnalyses(false);
    }
  }, [selectedRunId]);

  // Load specific detail
  useEffect(() => {
    if (selectedRunId) {
      setLoadingDetail(true);
      getAnalysisDetail(selectedRunId)
        .then((detail) => setRunDetail(detail))
        .catch((err) => console.error('Failed to load analysis detail:', err))
        .finally(() => setLoadingDetail(false));
    }
  }, [selectedRunId]);

  useEffect(() => {
    if (activeTab === 'decisions') {
      fetchDecisions();
    } else {
      fetchAnalyses();
    }
  }, [activeTab, fetchDecisions, fetchAnalyses]);

  const handleReviewDecision = async (
    decisionId: number,
    review: DecisionReviewRequest
  ) => {
    await reviewDecisionRecord(decisionId, review);
    await fetchDecisions();
  };

  const handleExportMarkdown = async () => {
    if (!selectedRunId) return;
    setDownloadingReport(true);
    try {
      const report = await exportAnalysisReport(selectedRunId, 'markdown');
      const blob = new Blob([report.content], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `NEXUS-Intelligence-Report-${report.analysis_id}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to export report:', err);
    } finally {
      setDownloadingReport(false);
    }
  };

  const pendingCount = decisions.filter((d) => d.status === 'PENDING').length;

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* Header */}
      <IntelligenceHeader
        eyebrow="HUMAN-IN-THE-LOOP GOVERNANCE"
        title="Analysis History & Decision Review Gate"
        subtitle="Verifiable audit trail of agent executions, deterministic calculations, and human approval checkpoints."
        icon={History}
      />

      {/* Tabs */}
      <div className="flex items-center justify-between border-b border-surface-elevated pb-3">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setActiveTab('decisions')}
            className={`px-4 py-2 rounded-xl text-xs font-semibold transition-all flex items-center gap-2 ${
              activeTab === 'decisions'
                ? 'bg-cyan-950/80 text-brand-cyan border border-brand-cyan/40 shadow-sm'
                : 'text-slate-400 hover:text-slate-200 hover:bg-surface'
            }`}
          >
            <UserCheck className="w-4 h-4" />
            <span>Decision Review Gate</span>
            {pendingCount > 0 && (
              <span className="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/40 text-[10px] font-mono">
                {pendingCount} Pending
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('analyses')}
            className={`px-4 py-2 rounded-xl text-xs font-semibold transition-all flex items-center gap-2 ${
              activeTab === 'analyses'
                ? 'bg-cyan-950/80 text-brand-cyan border border-brand-cyan/40 shadow-sm'
                : 'text-slate-400 hover:text-slate-200 hover:bg-surface'
            }`}
          >
            <FileText className="w-4 h-4" />
            <span>Persisted Analyses Log ({analyses.length})</span>
          </button>
        </div>

        {activeTab === 'decisions' && (
          <div className="flex items-center gap-2 text-xs font-mono">
            <Filter className="w-3.5 h-3.5 text-slate-500" />
            <select
              value={decisionFilter}
              onChange={(e) => setDecisionFilter(e.target.value)}
              className="rounded-lg bg-surface border border-surface-elevated px-2.5 py-1 text-slate-300 text-xs focus:outline-none"
            >
              <option value="all">All Postures</option>
              <option value="PENDING">Pending Only</option>
              <option value="APPROVED">Approved</option>
              <option value="REJECTED">Rejected</option>
              <option value="MODIFIED">Modified</option>
            </select>
          </div>
        )}
      </div>

      {error && <ErrorState message={error} onRetry={() => activeTab === 'decisions' ? fetchDecisions() : fetchAnalyses()} />}

      {/* View 1: Decision Review Gate */}
      {activeTab === 'decisions' && (
        <div className="space-y-4">
          {loadingDecisions ? (
            <LoadingState message="Fetching pending human decisions from database..." />
          ) : decisions.length === 0 ? (
            <div className="p-12 text-center rounded-3xl bg-surface/40 border border-surface-elevated space-y-2">
              <CheckCircle2 className="w-8 h-8 text-emerald-400 mx-auto" />
              <h4 className="text-sm font-bold text-white font-sans">No Decisions Matching Filter</h4>
              <p className="text-xs text-slate-400">All agent recommendations have been processed or no entries found.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {decisions.map((decision) => (
                <DecisionCard
                  key={decision.id}
                  decision={decision}
                  onReview={handleReviewDecision}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* View 2: Persisted Analyses Explorer */}
      {activeTab === 'analyses' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Analysis History List */}
          <div className="space-y-2 lg:col-span-1 max-h-[700px] overflow-y-auto pr-1">
            {loadingAnalyses ? (
              <LoadingState message="Loading historical run ledger..." />
            ) : analyses.length === 0 ? (
              <div className="p-8 text-center rounded-2xl bg-surface/40 border border-surface-elevated text-xs text-slate-400">
                No analyses recorded in database yet.
              </div>
            ) : (
              analyses.map((run) => {
                const isSelected = selectedRunId === run.id;
                return (
                  <div
                    key={run.id}
                    onClick={() => setSelectedRunId(run.id)}
                    className={`p-3.5 rounded-xl border transition-all cursor-pointer space-y-1.5 ${
                      isSelected
                        ? 'bg-cyan-950/70 border-brand-cyan/60 text-white shadow-sm'
                        : 'bg-surface/50 border-surface-elevated text-slate-300 hover:bg-surface'
                    }`}
                  >
                    <div className="flex items-center justify-between text-[11px] font-mono">
                      <span className="text-brand-cyan font-bold truncate">#{run.id} • {run.intent || 'analysis'}</span>
                      <span className="text-slate-400">{formatDate(run.created_at)}</span>
                    </div>

                    <p className="text-xs font-semibold text-slate-200 line-clamp-2 font-sans">
                      {run.query}
                    </p>

                    <div className="flex items-center justify-between text-[10px] font-mono text-slate-400 pt-0.5">
                      <span>{run.explanation_level}</span>
                      <span>{formatDuration(run.execution_time_ms)}</span>
                    </div>

                    {/* Phase 19: Semantic + Dataset snapshot badges */}
                    {(run.semantic_version != null || run.dataset_id) && (
                      <div className="flex items-center gap-2 pt-0.5 flex-wrap">
                        {run.semantic_version != null && (
                          <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-violet-950/60 border border-violet-700/40 text-[9px] font-mono text-violet-300">
                            SEM v{run.semantic_version}
                          </span>
                        )}
                        {run.dataset_id && (
                          <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-teal-950/60 border border-teal-700/40 text-[9px] font-mono text-teal-300">
                            DS:{run.dataset_id.slice(0, 8)}
                          </span>
                        )}
                        {run.dataset_date_coverage?.start && (
                          <span className="text-[9px] font-mono text-slate-500">
                            {run.dataset_date_coverage.start} &rarr; {run.dataset_date_coverage.end}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>

          {/* Selected Run Inspection Canvas */}
          <div className="lg:col-span-2 rounded-3xl bg-surface/60 border border-surface-elevated p-6 space-y-5">
            {loadingDetail ? (
              <LoadingState message="Loading complete analysis run payload..." />
            ) : runDetail ? (
              <div className="space-y-5 animate-in fade-in duration-150">
                {/* Header & Export Action */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-surface-elevated pb-4">
                  <div>
                    <span className="text-[10px] font-mono uppercase text-brand-cyan tracking-wider font-semibold">
                      Historical Execution #{runDetail.id}
                    </span>
                    <h3 className="text-base font-bold text-white font-sans mt-0.5">
                      {runDetail.query}
                    </h3>
                  </div>

                  <button
                    onClick={handleExportMarkdown}
                    disabled={downloadingReport}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-surface-elevated hover:bg-surface-highlight border border-surface-highlight text-xs font-semibold text-white transition-all self-start shrink-0"
                  >
                    <Download className="w-3.5 h-3.5 text-brand-cyan" />
                    <span>{downloadingReport ? 'Generating...' : 'Export Dossier (MD)'}</span>
                  </button>
                </div>

                {/* Analytical Answer */}
                <div className="space-y-2">
                  <span className="text-[11px] font-mono uppercase text-slate-400 tracking-wider">
                    Grounded Analytical Narrative
                  </span>
                  <div className="p-4 rounded-2xl bg-void/80 border border-surface-elevated text-xs sm:text-sm text-slate-200 leading-relaxed whitespace-pre-wrap font-sans">
                    {runDetail.answer}
                  </div>
                </div>

                {/* Telemetry & Metadata */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
                  <div className="p-2.5 rounded-xl bg-surface border border-surface-elevated">
                    <span className="text-[10px] text-slate-400 block">INTENT</span>
                    <span className="text-brand-cyan font-semibold">{runDetail.intent || 'analysis'}</span>
                  </div>
                  <div className="p-2.5 rounded-xl bg-surface border border-surface-elevated">
                    <span className="text-[10px] text-slate-400 block">EXECUTION TIME</span>
                    <span className="text-slate-200 font-semibold">{formatDuration(runDetail.execution_time_ms)}</span>
                  </div>
                  <div className="p-2.5 rounded-xl bg-surface border border-surface-elevated">
                    <span className="text-[10px] text-slate-400 block">TOOLS INVOKED</span>
                    <span className="text-slate-200 font-semibold">{runDetail.tools_used?.length ?? 0} Tools</span>
                  </div>
                  <div className="p-2.5 rounded-xl bg-surface border border-surface-elevated">
                    <span className="text-[10px] text-slate-400 block">EVIDENCE COUNT</span>
                    <span className="text-emerald-400 font-semibold">{runDetail.evidence_records?.length ?? 0} Records</span>
                  </div>
                </div>

                {/* Phase 19: Semantic + Dataset Provenance Block */}
                {(runDetail.semantic_version != null || runDetail.dataset_id) && (
                  <div className="rounded-2xl bg-void/60 border border-surface-elevated p-4 space-y-3">
                    <span className="text-[10px] font-mono uppercase text-slate-400 tracking-wider block">Run Provenance</span>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs font-mono">
                      {runDetail.semantic_version != null && (
                        <div className="space-y-0.5">
                          <span className="text-[10px] text-slate-500 block">SEMANTIC MODEL</span>
                          <span className="text-violet-300 font-semibold">Version {runDetail.semantic_version}</span>
                          {runDetail.semantic_revision_id && (
                            <span className="text-[9px] text-slate-500 block truncate">{runDetail.semantic_revision_id}</span>
                          )}
                        </div>
                      )}
                      {runDetail.dataset_id && (
                        <div className="space-y-0.5">
                          <span className="text-[10px] text-slate-500 block">DATASET AT RUN TIME</span>
                          <span className="text-teal-300 font-semibold truncate block">{runDetail.dataset_id.slice(0, 16)}&hellip;</span>
                          {runDetail.dataset_date_coverage?.start && (
                            <span className="text-[9px] text-slate-500 block">
                              {runDetail.dataset_date_coverage.start} &rarr; {runDetail.dataset_date_coverage.end}
                              {runDetail.dataset_date_coverage.days ? ` (${runDetail.dataset_date_coverage.days}d)` : ''}
                            </span>
                          )}
                        </div>
                      )}
                      {runDetail.dataset_content_hash && (
                        <div className="col-span-full space-y-0.5">
                          <span className="text-[10px] text-slate-500 block">DATASET FINGERPRINT (SHA-256)</span>
                          <span className="text-[9px] text-slate-400 font-mono truncate block">{runDetail.dataset_content_hash}</span>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Attached Decisions */}
                {runDetail.decisions && runDetail.decisions.length > 0 && (
                  <div className="space-y-2 pt-2 border-t border-surface-elevated">
                    <span className="text-[11px] font-mono uppercase text-slate-400 tracking-wider">
                      Attached Decision Checkpoints ({runDetail.decisions.length})
                    </span>
                    <div className="space-y-2">
                      {runDetail.decisions.map((dec) => (
                        <DecisionCard
                          key={dec.id}
                          decision={dec}
                          onReview={handleReviewDecision}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="p-12 text-center text-xs text-slate-400">
                Select an analytical execution from the ledger to inspect its detailed evidence trace.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
