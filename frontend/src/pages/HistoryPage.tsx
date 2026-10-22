import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  History,
  FileText,
  Download,
  CheckCircle2,
  UserCheck,
  ShieldCheck,
  Terminal,
  Search,
  X,
  AlertTriangle,
  RefreshCw,
  Layers,
  ShieldAlert,
  LogIn,
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
import { ErrorBoundary } from '../components/common/ErrorBoundary';
import { DecisionCard } from '../components/intelligence/DecisionCard';

interface HistoryPageProps {
  onNavigate?: (route: string) => void;
}

export const HistoryPage: React.FC<HistoryPageProps> = ({ onNavigate }) => {
  const [activeTab, setActiveTab] = useState<'decisions' | 'analyses'>('decisions');

  // Decision state
  const [decisions, setDecisions] = useState<DecisionRecordItem[]>([]);
  const [decisionFilter, setDecisionFilter] = useState<string>('all');
  const [decisionSearch, setDecisionSearch] = useState<string>('');
  const [decisionSort, setDecisionSort] = useState<'newest' | 'oldest'>('newest');
  const [loadingDecisions, setLoadingDecisions] = useState(true);

  // Analysis state
  const [analyses, setAnalyses] = useState<AnalysisRunItem[]>([]);
  const [analysisSearch, setAnalysisSearch] = useState<string>('');
  const [analysisStatusFilter, setAnalysisStatusFilter] = useState<string>('all');
  const [analysisIntentFilter, setAnalysisIntentFilter] = useState<string>('all');
  const [analysisSort, setAnalysisSort] = useState<'newest' | 'oldest'>('newest');
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [runDetail, setRunDetail] = useState<AnalysisRunDetail | null>(null);
  const [loadingAnalyses, setLoadingAnalyses] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // General & export state
  const [error, setError] = useState<string | null>(null);
  const [authRequired, setAuthRequired] = useState(false);
  const [downloadingReport, setDownloadingReport] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Load Decisions with resilient error handling
  const fetchDecisions = useCallback(async () => {
    setLoadingDecisions(true);
    try {
      const data = await listDecisionRecords({
        status: decisionFilter === 'all' ? undefined : decisionFilter,
      });
      setDecisions(data || []);
      setError(null);
      setAuthRequired(false);
    } catch (err: any) {
      console.warn('Failed to load decision records:', err);
      const isAuth = err?.status === 401 || err?.message?.toLowerCase().includes('token') || err?.message?.toLowerCase().includes('auth');
      if (isAuth) {
        setAuthRequired(true);
      } else {
        setError(err?.message || 'Failed to load decision records from database.');
      }
      setDecisions([]);
    } finally {
      setLoadingDecisions(false);
    }
  }, [decisionFilter]);

  // Load Analyses with resilient error handling
  const fetchAnalyses = useCallback(async () => {
    setLoadingAnalyses(true);
    try {
      const data = await listHistoricalAnalyses({ limit: 100 });
      setAnalyses(data || []);
      setError(null);
      setAuthRequired(false);
      if (data && data.length > 0) {
        setSelectedRunId((prev) => (prev ? prev : data[0].id));
      }
    } catch (err: any) {
      console.warn('Failed to load historical analyses:', err);
      const isAuth = err?.status === 401 || err?.message?.toLowerCase().includes('token') || err?.message?.toLowerCase().includes('auth');
      if (isAuth) {
        setAuthRequired(true);
      } else {
        setError(err?.message || 'Failed to load historical analysis runs from database.');
      }
      setAnalyses([]);
    } finally {
      setLoadingAnalyses(false);
    }
  }, []);

  // Fetch detailed run record
  useEffect(() => {
    if (selectedRunId) {
      setLoadingDetail(true);
      getAnalysisDetail(selectedRunId)
        .then((detail) => setRunDetail(detail))
        .catch((err) => {
          console.warn('Failed to load analysis detail:', err);
          // If detailed call fails, construct a graceful fallback detail using the run summary
          const fallbackRun = analyses.find((r) => r.id === selectedRunId);
          if (fallbackRun) {
            setRunDetail({
              ...fallbackRun,
              answer: 'Historical analysis detail payload unavailable. Please verify workspace connectivity.',
              tools_used: [],
              calculations: [],
              assumptions: [],
              limitations: [],
              evidence_records: [],
              rag_citations: [],
              decisions: [],
            });
          }
        })
        .finally(() => setLoadingDetail(false));
    }
  }, [selectedRunId, analyses]);

  // Unified refresh
  const handleRefreshAll = useCallback(async () => {
    setIsRefreshing(true);
    if (activeTab === 'decisions') {
      await fetchDecisions();
    } else {
      await fetchAnalyses();
    }
    setIsRefreshing(false);
  }, [activeTab, fetchDecisions, fetchAnalyses]);

  useEffect(() => {
    if (activeTab === 'decisions') {
      fetchDecisions();
    } else {
      fetchAnalyses();
    }
  }, [activeTab, fetchDecisions, fetchAnalyses]);

  // Decision review action
  const handleReviewDecision = async (
    decisionId: number,
    review: DecisionReviewRequest
  ) => {
    try {
      await reviewDecisionRecord(decisionId, review);
      await fetchDecisions();
    } catch (err: any) {
      console.error('Failed to commit review:', err);
      setError(err?.message || 'Failed to commit decision review.');
    }
  };

  // Inspect source analysis linked to a decision
  const handleInspectSourceAnalysis = useCallback((analysisId: number) => {
    setSelectedRunId(analysisId);
    setActiveTab('analyses');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, []);

  // Export report action
  const handleExportMarkdown = async () => {
    if (!selectedRunId) return;
    setDownloadingReport(true);
    try {
      const report = await exportAnalysisReport(selectedRunId, 'markdown');
      const blob = new Blob([report.content], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `NEXUS-Intelligence-Report-${report.analysis_id || selectedRunId}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err: any) {
      console.error('Failed to export report:', err);
      setError(err?.message || 'Failed to export analytical dossier.');
    } finally {
      setDownloadingReport(false);
    }
  };

  // Filtered decisions calculation
  const filteredDecisions = useMemo(() => {
    let list = [...decisions];
    if (decisionSearch.trim()) {
      const q = decisionSearch.toLowerCase();
      list = list.filter(
        (d) =>
          d.recommendation_text.toLowerCase().includes(q) ||
          d.reviewer_notes?.toLowerCase().includes(q) ||
          d.reviewed_by?.toLowerCase().includes(q) ||
          String(d.id).includes(q) ||
          (d.analysis_id && String(d.analysis_id).includes(q))
      );
    }
    if (decisionSort === 'oldest') {
      list.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
    } else {
      list.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    }
    return list;
  }, [decisions, decisionSearch, decisionSort]);

  // Decision counts by status
  const pendingCount = useMemo(() => decisions.filter((d) => d.status.toUpperCase() === 'PENDING').length, [decisions]);
  const approvedCount = useMemo(() => decisions.filter((d) => d.status.toUpperCase() === 'APPROVED').length, [decisions]);
  const rejectedCount = useMemo(() => decisions.filter((d) => d.status.toUpperCase() === 'REJECTED').length, [decisions]);
  const modifiedCount = useMemo(() => decisions.filter((d) => d.status.toUpperCase() === 'MODIFIED').length, [decisions]);
  const deferredCount = useMemo(() => decisions.filter((d) => d.status.toUpperCase() === 'DEFERRED').length, [decisions]);

  // Unique intents available in analyses
  const availableIntents = useMemo(() => {
    const intents = new Set<string>();
    analyses.forEach((a) => {
      if (a.intent) intents.add(a.intent.toLowerCase());
    });
    return Array.from(intents);
  }, [analyses]);

  // Filtered analyses calculation
  const filteredAnalyses = useMemo(() => {
    let list = [...analyses];
    if (analysisStatusFilter !== 'all') {
      list = list.filter((a) => a.status.toUpperCase() === analysisStatusFilter.toUpperCase());
    }
    if (analysisIntentFilter !== 'all') {
      list = list.filter((a) => (a.intent || '').toLowerCase() === analysisIntentFilter.toLowerCase());
    }
    if (analysisSearch.trim()) {
      const q = analysisSearch.toLowerCase();
      list = list.filter(
        (a) =>
          a.query.toLowerCase().includes(q) ||
          (a.intent && a.intent.toLowerCase().includes(q)) ||
          a.request_id.toLowerCase().includes(q) ||
          String(a.id).includes(q)
      );
    }
    if (analysisSort === 'oldest') {
      list.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
    } else {
      list.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    }
    return list;
  }, [analyses, analysisStatusFilter, analysisIntentFilter, analysisSearch, analysisSort]);

  // Counts for analyses
  const completedAnalysesCount = useMemo(
    () => analyses.filter((a) => ['SUCCESS', 'COMPLETED'].includes(a.status.toUpperCase())).length,
    [analyses]
  );
  const runningAnalysesCount = useMemo(
    () => analyses.filter((a) => ['RUNNING', 'IN_PROGRESS', 'PENDING'].includes(a.status.toUpperCase())).length,
    [analyses]
  );
  const failedAnalysesCount = useMemo(
    () => analyses.filter((a) => ['FAILED', 'ERROR'].includes(a.status.toUpperCase())).length,
    [analyses]
  );

  return (
    <ErrorBoundary>
      <div className="space-y-6 animate-in fade-in duration-200">
        {/* Executive Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-white/[0.08] pb-5">
          <div>
            <div className="flex flex-wrap items-center gap-2 mb-2">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-800/50 text-cyan-400 font-mono text-[11px] font-semibold">
                <History className="w-3.5 h-3.5" />
                <span>HUMAN-IN-THE-LOOP GOVERNANCE</span>
              </span>
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-surface border border-white/[0.08] text-slate-400 font-mono text-[10px]">
                <ShieldCheck className="w-3 h-3 text-emerald-400" />
                <span>Deterministic Audit Ledger</span>
              </span>
            </div>

            <h1 className="text-2xl sm:text-3xl font-bold text-white tracking-tight font-sans">
              Analysis History &amp; Decision Review Gate
            </h1>
            <p className="text-xs sm:text-sm text-slate-400 mt-1 max-w-2xl font-sans leading-relaxed">
              Verifiable audit trail of agent executions, deterministic calculations, and human approval checkpoints.
            </p>
          </div>

          {/* Action Buttons & Tabs */}
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
            <button
              onClick={handleRefreshAll}
              disabled={isRefreshing || loadingDecisions || loadingAnalyses}
              className="btn-secondary text-xs h-9 px-3 self-start sm:self-auto inline-flex items-center gap-1.5"
              title="Refresh ledger records from database"
            >
              <RefreshCw className={`w-3.5 h-3.5 text-cyan-400 ${isRefreshing ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline">Refresh Ledger</span>
            </button>

            {/* Tab Controls */}
            <div className="flex items-center gap-1 bg-void p-1 rounded-xl border border-white/[0.08]">
              <button
                type="button"
                onClick={() => setActiveTab('decisions')}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center gap-2 ${
                  activeTab === 'decisions'
                    ? 'bg-cyan-950/90 text-cyan-300 border border-cyan-500/40 shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                <UserCheck className="w-4 h-4" />
                <span>Decision Review Gate</span>
                {pendingCount > 0 ? (
                  <span className="px-1.5 py-0.2 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/40 text-[10px] font-mono animate-pulse">
                    {pendingCount}
                  </span>
                ) : (
                  <span className="px-1.5 py-0.2 rounded-full bg-surface border border-white/[0.08] text-slate-400 text-[10px] font-mono">
                    {decisions.length}
                  </span>
                )}
              </button>

              <button
                type="button"
                onClick={() => setActiveTab('analyses')}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center gap-2 ${
                  activeTab === 'analyses'
                    ? 'bg-cyan-950/90 text-cyan-300 border border-cyan-500/40 shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                <FileText className="w-4 h-4" />
                <span>Persisted Analyses Log</span>
                <span className="px-1.5 py-0.2 rounded-full bg-surface border border-white/[0.08] text-slate-400 text-[10px] font-mono">
                  {analyses.length}
                </span>
              </button>
            </div>
          </div>
        </div>

        {/* 21st.dev Precision Obsidian Metric Scorecard */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Card 1: Persisted Runs */}
          <div className="p-4 rounded-xl bg-void/60 border border-white/[0.08] flex flex-col justify-between space-y-3">
            <div className="flex items-center justify-between text-slate-400">
              <span className="text-[10px] font-mono tracking-wider uppercase font-semibold text-slate-400">
                PERSISTED RUNS
              </span>
              <div className="w-7 h-7 rounded-lg bg-cyan-950/60 border border-cyan-800/40 flex items-center justify-center text-cyan-400">
                <FileText className="w-3.5 h-3.5" />
              </div>
            </div>
            <div>
              <div className="text-2xl font-bold font-mono tracking-tight text-white">
                {analyses.length}
              </div>
              <div className="text-[11px] text-slate-400 mt-0.5 font-sans">
                {availableIntents.length > 0
                  ? `${availableIntents.length} Intent Categories Recorded`
                  : 'Historical Agent Ledger'}
              </div>
            </div>
            <div className="pt-2 border-t border-white/[0.04] text-[10px] font-mono text-cyan-400/80">
              Deterministic Query Log
            </div>
          </div>

          {/* Card 2: Decision Checkpoints */}
          <div className="p-4 rounded-xl bg-void/60 border border-white/[0.08] flex flex-col justify-between space-y-3">
            <div className="flex items-center justify-between text-slate-400">
              <span className="text-[10px] font-mono tracking-wider uppercase font-semibold text-slate-400">
                HUMAN REVIEW GATE
              </span>
              <div className="w-7 h-7 rounded-lg bg-emerald-950/60 border border-emerald-800/40 flex items-center justify-center text-emerald-400">
                <UserCheck className="w-3.5 h-3.5" />
              </div>
            </div>
            <div>
              <div className="text-2xl font-bold font-mono tracking-tight text-white flex items-baseline gap-2">
                <span>{decisions.length}</span>
                {pendingCount > 0 && (
                  <span className="text-xs font-sans text-amber-400 font-semibold px-2 py-0.5 rounded-full bg-amber-950/60 border border-amber-700/50">
                    {pendingCount} Pending
                  </span>
                )}
              </div>
              <div className="text-[11px] text-slate-400 mt-0.5 font-sans">
                {pendingCount === 0 && decisions.length > 0
                  ? 'All Recommendations Evaluated'
                  : 'Tracked Business Postures'}
              </div>
            </div>
            <div className="pt-2 border-t border-white/[0.04] text-[10px] font-mono text-emerald-400/80">
              {pendingCount > 0 ? 'Requires Executive Signoff' : 'Zero Unresolved Action Items'}
            </div>
          </div>

          {/* Card 3: Execution Reliability */}
          <div className="p-4 rounded-xl bg-void/60 border border-white/[0.08] flex flex-col justify-between space-y-3">
            <div className="flex items-center justify-between text-slate-400">
              <span className="text-[10px] font-mono tracking-wider uppercase font-semibold text-slate-400">
                EXECUTION RELIABILITY
              </span>
              <div className="w-7 h-7 rounded-lg bg-cyan-950/60 border border-cyan-800/40 flex items-center justify-center text-cyan-400">
                <ShieldCheck className="w-3.5 h-3.5" />
              </div>
            </div>
            <div>
              <div className="text-2xl font-bold font-mono tracking-tight text-white">
                {analyses.length > 0
                  ? `${Math.round((completedAnalysesCount / analyses.length) * 100)}%`
                  : '100%'}
              </div>
              <div className="text-[11px] text-slate-400 mt-0.5 font-sans">
                {completedAnalysesCount} Completed / {failedAnalysesCount} Failed
              </div>
            </div>
            <div className="pt-2 border-t border-white/[0.04] text-[10px] font-mono text-slate-400">
              Zero LLM Math Hallucinations
            </div>
          </div>

          {/* Card 4: Audit Immutability */}
          <div className="p-4 rounded-xl bg-void/60 border border-white/[0.08] flex flex-col justify-between space-y-3">
            <div className="flex items-center justify-between text-slate-400">
              <span className="text-[10px] font-mono tracking-wider uppercase font-semibold text-slate-400">
                AUDIT IMMUTABILITY
              </span>
              <div className="w-7 h-7 rounded-lg bg-violet-950/60 border border-violet-800/40 flex items-center justify-center text-violet-400">
                <Layers className="w-3.5 h-3.5" />
              </div>
            </div>
            <div>
              <div className="text-2xl font-bold font-mono tracking-tight text-violet-300">
                Phase 19
              </div>
              <div className="text-[11px] text-slate-400 mt-0.5 font-sans">
                Immutable Dataset &amp; SEM Pinning
              </div>
            </div>
            <div className="pt-2 border-t border-white/[0.04] text-[10px] font-mono text-violet-400/80">
              SHA-256 Fingerprint Grounded
            </div>
          </div>
        </div>

        {/* Dignified Auth / Workspace Notice when session is unauthenticated */}
        {authRequired && (
          <div className="p-4 sm:p-5 rounded-2xl bg-amber-950/20 border border-amber-600/40 text-amber-200 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="flex items-start gap-3">
              <ShieldAlert className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <h3 className="font-semibold text-white text-sm font-sans">
                  Workspace Authentication Required for Historical Records
                </h3>
                <p className="text-xs text-amber-200/80 font-sans leading-relaxed max-w-2xl">
                  Historical analytical runs, evidence records, and human decision checkpoints are strictly isolated per tenant organization. Please sign in to authenticate your workspace ledger.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 self-start sm:self-auto shrink-0">
              <button
                type="button"
                onClick={() => {
                  if (onNavigate) {
                    onNavigate('/login');
                  } else {
                    window.location.href = '/login';
                  }
                }}
                className="btn-primary text-xs h-8 px-3 inline-flex items-center gap-1.5"
              >
                <LogIn className="w-3.5 h-3.5" />
                <span>Sign In to Workspace</span>
              </button>
              <button
                type="button"
                onClick={handleRefreshAll}
                className="btn-secondary text-xs h-8 px-3 inline-flex items-center gap-1.5"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span>Retry</span>
              </button>
            </div>
          </div>
        )}

        {/* General Error Banner */}
        {error && !authRequired && (
          <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-600/40 text-rose-200 flex items-center justify-between gap-3 text-xs">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
              <span>{error}</span>
            </div>
            <button
              onClick={() => {
                setError(null);
                handleRefreshAll();
              }}
              className="px-2.5 py-1 rounded bg-rose-900/60 hover:bg-rose-800 text-white font-mono text-[11px] transition-colors"
            >
              Retry
            </button>
          </div>
        )}

        {/* ======================================================== */}
        {/* VIEW 1: DECISION REVIEW GATE */}
        {/* ======================================================== */}
        {activeTab === 'decisions' && (
          <div className="space-y-4">
            {/* Toolbar: Search, Posture Filters, and Sort */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 p-3 rounded-xl bg-void/60 border border-white/[0.08]">
              {/* Search Box */}
              <div className="relative flex-1 max-w-md">
                <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  placeholder="Search recommendations, reviewers, or notes..."
                  value={decisionSearch}
                  onChange={(e) => setDecisionSearch(e.target.value)}
                  className="input-obsidian pl-8 pr-8 text-xs h-8 font-sans w-full"
                />
                {decisionSearch && (
                  <button
                    onClick={() => setDecisionSearch('')}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white"
                  >
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>

              {/* Status Filter Pills & Sort Dropdown */}
              <div className="flex flex-wrap items-center gap-2">
                <div className="inline-flex rounded-lg bg-surface border border-white/[0.08] p-0.5 text-xs font-mono">
                  <button
                    type="button"
                    onClick={() => setDecisionFilter('all')}
                    className={`px-2.5 py-1 rounded-md transition-all ${
                      decisionFilter === 'all'
                        ? 'bg-cyan-950/80 text-cyan-300 font-semibold'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    All ({decisions.length})
                  </button>
                  <button
                    type="button"
                    onClick={() => setDecisionFilter('PENDING')}
                    className={`px-2.5 py-1 rounded-md transition-all ${
                      decisionFilter === 'PENDING'
                        ? 'bg-amber-950/80 text-amber-300 font-semibold'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    Pending ({pendingCount})
                  </button>
                  <button
                    type="button"
                    onClick={() => setDecisionFilter('APPROVED')}
                    className={`px-2.5 py-1 rounded-md transition-all ${
                      decisionFilter === 'APPROVED'
                        ? 'bg-emerald-950/80 text-emerald-300 font-semibold'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    Approved ({approvedCount})
                  </button>
                  <button
                    type="button"
                    onClick={() => setDecisionFilter('REJECTED')}
                    className={`px-2.5 py-1 rounded-md transition-all ${
                      decisionFilter === 'REJECTED'
                        ? 'bg-rose-950/80 text-rose-300 font-semibold'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    Rejected ({rejectedCount})
                  </button>
                  <button
                    type="button"
                    onClick={() => setDecisionFilter('MODIFIED')}
                    className={`px-2.5 py-1 rounded-md transition-all ${
                      decisionFilter === 'MODIFIED'
                        ? 'bg-sky-950/80 text-sky-300 font-semibold'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    Modified ({modifiedCount})
                  </button>
                  {deferredCount > 0 && (
                    <button
                      type="button"
                      onClick={() => setDecisionFilter('DEFERRED')}
                      className={`px-2.5 py-1 rounded-md transition-all ${
                        decisionFilter === 'DEFERRED'
                          ? 'bg-slate-800 text-slate-200 font-semibold'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      Deferred ({deferredCount})
                    </button>
                  )}
                </div>

                {/* Sort Toggle */}
                <select
                  value={decisionSort}
                  onChange={(e) => setDecisionSort(e.target.value as any)}
                  className="input-obsidian text-xs h-8 w-28 font-mono"
                >
                  <option value="newest">Newest First</option>
                  <option value="oldest">Oldest First</option>
                </select>
              </div>
            </div>

            {/* Decisions List Content */}
            {loadingDecisions ? (
              <LoadingState message="Fetching human decision audit ledger..." />
            ) : filteredDecisions.length === 0 ? (
              <div className="card-obsidian p-10 text-center space-y-3">
                <CheckCircle2 className="w-9 h-9 text-emerald-400 mx-auto" />
                <div className="space-y-1">
                  <h3 className="text-sm font-bold text-white font-sans">
                    {decisionSearch || decisionFilter !== 'all'
                      ? 'No Decisions Matching Filter Criteria'
                      : 'No Human Decisions Pending'}
                  </h3>
                  <p className="text-xs text-slate-400 font-sans max-w-md mx-auto leading-relaxed">
                    {decisionSearch || decisionFilter !== 'all'
                      ? 'Try resetting the search query or changing the posture filter above.'
                      : 'All agent-generated recommendations have been audited or no decision checkpoints have been registered yet.'}
                  </p>
                </div>
                {(decisionSearch || decisionFilter !== 'all') && (
                  <button
                    onClick={() => {
                      setDecisionSearch('');
                      setDecisionFilter('all');
                    }}
                    className="btn-secondary text-xs h-8 px-3 inline-flex items-center gap-1.5"
                  >
                    <span>Reset Decision Filters</span>
                  </button>
                )}
              </div>
            ) : (
              <div className="space-y-3">
                {filteredDecisions.map((decision) => (
                  <DecisionCard
                    key={decision.id}
                    decision={decision}
                    onReview={handleReviewDecision}
                    onInspectAnalysis={handleInspectSourceAnalysis}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* ======================================================== */}
        {/* VIEW 2: PERSISTED ANALYSES EXPLORER */}
        {/* ======================================================== */}
        {activeTab === 'analyses' && (
          <div className="space-y-4">
            {/* Toolbar: Search, Status, Intent Filter, Sort */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 p-3 rounded-xl bg-void/60 border border-white/[0.08]">
              {/* Search Box */}
              <div className="relative flex-1 max-w-md">
                <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  placeholder="Filter analyses by query, intent, or request ID..."
                  value={analysisSearch}
                  onChange={(e) => setAnalysisSearch(e.target.value)}
                  className="input-obsidian pl-8 pr-8 text-xs h-8 font-sans w-full"
                />
                {analysisSearch && (
                  <button
                    onClick={() => setAnalysisSearch('')}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white"
                  >
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>

              {/* Status Filters, Intent Dropdown & Sort */}
              <div className="flex flex-wrap items-center gap-2">
                <div className="inline-flex rounded-lg bg-surface border border-white/[0.08] p-0.5 text-xs font-mono">
                  <button
                    type="button"
                    onClick={() => setAnalysisStatusFilter('all')}
                    className={`px-2.5 py-1 rounded-md transition-all ${
                      analysisStatusFilter === 'all'
                        ? 'bg-cyan-950/80 text-cyan-300 font-semibold'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    All ({analyses.length})
                  </button>
                  <button
                    type="button"
                    onClick={() => setAnalysisStatusFilter('COMPLETED')}
                    className={`px-2.5 py-1 rounded-md transition-all ${
                      analysisStatusFilter === 'COMPLETED'
                        ? 'bg-emerald-950/80 text-emerald-300 font-semibold'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    Completed ({completedAnalysesCount})
                  </button>
                  {runningAnalysesCount > 0 && (
                    <button
                      type="button"
                      onClick={() => setAnalysisStatusFilter('RUNNING')}
                      className={`px-2.5 py-1 rounded-md transition-all ${
                        analysisStatusFilter === 'RUNNING'
                          ? 'bg-cyan-950/80 text-cyan-300 font-semibold'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      Running ({runningAnalysesCount})
                    </button>
                  )}
                  {failedAnalysesCount > 0 && (
                    <button
                      type="button"
                      onClick={() => setAnalysisStatusFilter('FAILED')}
                      className={`px-2.5 py-1 rounded-md transition-all ${
                        analysisStatusFilter === 'FAILED'
                          ? 'bg-rose-950/80 text-rose-300 font-semibold'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      Failed ({failedAnalysesCount})
                    </button>
                  )}
                </div>

                {/* Intent Dropdown */}
                {availableIntents.length > 0 && (
                  <select
                    value={analysisIntentFilter}
                    onChange={(e) => setAnalysisIntentFilter(e.target.value)}
                    className="input-obsidian text-xs h-8 w-32 font-mono capitalize"
                  >
                    <option value="all">All Intents</option>
                    {availableIntents.map((i) => (
                      <option key={i} value={i}>
                        {i}
                      </option>
                    ))}
                  </select>
                )}

                {/* Sort Toggle */}
                <select
                  value={analysisSort}
                  onChange={(e) => setAnalysisSort(e.target.value as any)}
                  className="input-obsidian text-xs h-8 w-28 font-mono"
                >
                  <option value="newest">Newest First</option>
                  <option value="oldest">Oldest First</option>
                </select>
              </div>
            </div>

            {/* Dual-Pane Layout: Ledger List (Left) + Detail Inspection Canvas (Right) */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              {/* Left Pane: Analysis History List */}
              <div className="lg:col-span-5 space-y-2.5 max-h-[720px] overflow-y-auto pr-1">
                {loadingAnalyses ? (
                  <LoadingState message="Loading historical analytical ledger..." />
                ) : filteredAnalyses.length === 0 ? (
                  <div className="card-obsidian p-8 text-center space-y-2 text-xs text-slate-400">
                    <Terminal className="w-7 h-7 text-slate-600 mx-auto" />
                    <p className="font-semibold text-slate-300">No matching historical analyses found.</p>
                    <p className="text-[11px] leading-relaxed">
                      {analysisSearch || analysisStatusFilter !== 'all' || analysisIntentFilter !== 'all'
                        ? 'Try loosening your filter or search query.'
                        : 'Run an analytical query in Ask NEXUS or Investigations to generate your first audit record.'}
                    </p>
                  </div>
                ) : (
                  filteredAnalyses.map((run) => {
                    const isSelected = selectedRunId === run.id;
                    const isSuccess = ['SUCCESS', 'COMPLETED'].includes(run.status.toUpperCase());
                    const isFailed = ['FAILED', 'ERROR'].includes(run.status.toUpperCase());

                    return (
                      <div
                        key={run.id}
                        onClick={() => setSelectedRunId(run.id)}
                        className={`p-4 rounded-xl border transition-all cursor-pointer space-y-2 relative ${
                          isSelected
                            ? 'bg-cyan-950/40 border-cyan-500/60 shadow-[0_0_20px_-4px_rgba(6,182,212,0.2)]'
                            : 'bg-void/60 border-white/[0.08] hover:bg-void/90 hover:border-white/[0.16]'
                        }`}
                      >
                        {/* Top Row: Run ID, Intent & Timestamp */}
                        <div className="flex items-center justify-between text-[11px] font-mono">
                          <div className="flex items-center gap-1.5 truncate">
                            <span className="text-cyan-400 font-bold">#{run.id}</span>
                            <span className="text-slate-500">•</span>
                            <span className="text-slate-300 font-semibold capitalize truncate">
                              {run.intent || 'analysis'}
                            </span>
                          </div>

                          <div className="flex items-center gap-2 shrink-0">
                            {isSuccess && (
                              <span className="px-1.5 py-0.5 rounded bg-emerald-950/70 border border-emerald-600/40 text-[9px] font-mono text-emerald-300 font-semibold uppercase">
                                COMPLETED
                              </span>
                            )}
                            {isFailed && (
                              <span className="px-1.5 py-0.5 rounded bg-rose-950/70 border border-rose-600/40 text-[9px] font-mono text-rose-300 font-semibold uppercase">
                                FAILED
                              </span>
                            )}
                            {!isSuccess && !isFailed && (
                              <span className="px-1.5 py-0.5 rounded bg-cyan-950/70 border border-cyan-600/40 text-[9px] font-mono text-cyan-300 font-semibold uppercase animate-pulse">
                                {run.status}
                              </span>
                            )}
                            <span className="text-slate-400 text-[10px]">{formatDate(run.created_at)}</span>
                          </div>
                        </div>

                        {/* Executive Query Text */}
                        <p className="text-xs sm:text-sm font-semibold text-white font-sans line-clamp-2 leading-snug">
                          {run.query}
                        </p>

                        {/* Telemetry Bar */}
                        <div className="flex items-center justify-between text-[10px] font-mono text-slate-400 pt-1 border-t border-white/[0.04]">
                          <span className="capitalize">{run.explanation_level || 'Executive'}</span>
                          <span className="text-cyan-400">{formatDuration(run.execution_time_ms)}</span>
                        </div>

                        {/* Phase 19 Semantic & Dataset Snapshot Badges */}
                        {(run.semantic_version != null || run.dataset_id) && (
                          <div className="flex items-center gap-1.5 pt-0.5 flex-wrap">
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

              {/* Right Pane: Selected Run Deep Inspection Canvas */}
              <div className="lg:col-span-7 card-obsidian p-5 sm:p-6 space-y-5">
                {loadingDetail ? (
                  <LoadingState message="Loading complete analytical run payload..." />
                ) : runDetail ? (
                  <div className="space-y-5 animate-in fade-in duration-150">
                    {/* Header & Export Action */}
                    <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 border-b border-white/[0.08] pb-4">
                      <div className="space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-[10px] font-mono uppercase text-cyan-400 tracking-wider font-semibold">
                            HISTORICAL EXECUTION #{runDetail.id}
                          </span>
                          <span className="text-[10px] font-mono text-slate-500">
                            REQ:{runDetail.request_id ? runDetail.request_id.slice(0, 10) : '—'}
                          </span>
                        </div>
                        <h2 className="text-base sm:text-lg font-bold text-white font-sans">
                          {runDetail.query}
                        </h2>
                      </div>

                      <button
                        onClick={handleExportMarkdown}
                        disabled={downloadingReport}
                        className="btn-secondary text-xs h-8 px-3 shrink-0 self-start sm:self-auto inline-flex items-center gap-1.5"
                        title="Download audit-ready Markdown dossier"
                      >
                        <Download className="w-3.5 h-3.5 text-cyan-400" />
                        <span>{downloadingReport ? 'Generating...' : 'Export Dossier (MD)'}</span>
                      </button>
                    </div>

                    {/* Telemetry Ribbon */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
                      <div className="p-2.5 rounded-lg bg-void/80 border border-white/[0.06]">
                        <span className="text-[10px] text-slate-500 block uppercase font-semibold">INTENT</span>
                        <span className="text-white font-semibold truncate block capitalize mt-0.5">
                          {runDetail.intent || 'analysis'}
                        </span>
                      </div>
                      <div className="p-2.5 rounded-lg bg-void/80 border border-white/[0.06]">
                        <span className="text-[10px] text-slate-500 block uppercase font-semibold">POSTURE</span>
                        <span className="text-white font-semibold capitalize block mt-0.5">
                          {runDetail.explanation_level || 'Executive'}
                        </span>
                      </div>
                      <div className="p-2.5 rounded-lg bg-void/80 border border-white/[0.06]">
                        <span className="text-[10px] text-slate-500 block uppercase font-semibold">LATENCY</span>
                        <span className="text-cyan-400 font-semibold block mt-0.5">
                          {formatDuration(runDetail.execution_time_ms)}
                        </span>
                      </div>
                      <div className="p-2.5 rounded-lg bg-void/80 border border-white/[0.06]">
                        <span className="text-[10px] text-slate-500 block uppercase font-semibold">TOOLS INVOKED</span>
                        <span className="text-white font-semibold block mt-0.5">
                          {runDetail.tools_used?.length ?? 0}
                        </span>
                      </div>
                    </div>

                    {/* Grounded Analytical Answer */}
                    <div className="space-y-2">
                      <span className="text-[10px] font-mono uppercase text-slate-400 tracking-wider font-semibold">
                        GROUNDED ANALYTICAL NARRATIVE
                      </span>
                      <div className="p-4 rounded-xl bg-void/90 border border-white/[0.08] text-xs sm:text-sm text-slate-200 leading-relaxed whitespace-pre-wrap font-sans">
                        {runDetail.answer}
                      </div>
                    </div>

                    {/* Computational Tools Invoked */}
                    {runDetail.tools_used && runDetail.tools_used.length > 0 && (
                      <div className="space-y-2">
                        <span className="text-[10px] font-mono uppercase text-slate-400 tracking-wider font-semibold">
                          DETERMINISTIC TOOLS EXECUTED ({runDetail.tools_used.length})
                        </span>
                        <div className="flex flex-wrap gap-1.5">
                          {runDetail.tools_used.map((tool) => (
                            <span
                              key={tool}
                              className="px-2.5 py-1 rounded-lg bg-void/80 border border-white/[0.08] text-cyan-300 font-mono text-[11px]"
                            >
                              {tool}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Calculations / Formulas */}
                    {runDetail.calculations && runDetail.calculations.length > 0 && (
                      <div className="space-y-2">
                        <span className="text-[10px] font-mono uppercase text-slate-400 tracking-wider font-semibold">
                          DETERMINISTIC FORMULAS &amp; INTERMEDIATE VALUES
                        </span>
                        <div className="space-y-1.5 font-mono text-[11px]">
                          {runDetail.calculations.map((calc, idx) => (
                            <div
                              key={idx}
                              className="p-2.5 rounded-lg bg-void/80 border border-white/[0.06] text-slate-300"
                            >
                              <div className="text-emerald-400 font-semibold">{calc.formula || calc.calculation || 'Calculation'}</div>
                              {calc.result != null && (
                                <div className="text-slate-400 text-[10px] mt-0.5">Result: {calc.result}</div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Provenance & Evidence Records */}
                    {runDetail.evidence_records && runDetail.evidence_records.length > 0 && (
                      <div className="space-y-2 pt-2 border-t border-white/[0.06]">
                        <span className="text-[10px] font-mono uppercase text-slate-400 tracking-wider font-semibold flex items-center gap-1.5">
                          <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                          <span>GROUNDED EVIDENCE PROOFS ({runDetail.evidence_records.length})</span>
                        </span>
                        <div className="space-y-2 font-mono text-[11px]">
                          {runDetail.evidence_records.map((ev, idx) => (
                            <div
                              key={idx}
                              className="p-3 rounded-lg bg-void/80 border border-white/[0.06] space-y-1"
                            >
                              <div className="flex items-center justify-between text-white font-semibold">
                                <span>{ev.metric || `Evidence #${idx + 1}`}</span>
                                <span className="text-emerald-400 text-[10px]">{ev.source_tables ? ev.source_tables.join(', ') : 'Grounded'}</span>
                              </div>
                              {ev.calculation && (
                                <div className="text-slate-400 text-[10px]">Method: {ev.calculation}</div>
                              )}
                              {ev.assumptions && ev.assumptions.length > 0 && (
                                <div className="text-slate-500 text-[10px]">
                                  Assumptions: {ev.assumptions.join('; ')}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* RAG Citations */}
                    {runDetail.rag_citations && runDetail.rag_citations.length > 0 && (
                      <div className="space-y-2 pt-2 border-t border-white/[0.06]">
                        <span className="text-[10px] font-mono uppercase text-slate-400 tracking-wider font-semibold">
                          ORGANIZATIONAL CONTEXT GROUNDING ({runDetail.rag_citations.length})
                        </span>
                        <div className="space-y-2 font-sans text-xs">
                          {runDetail.rag_citations.map((cite, idx) => (
                            <div
                              key={idx}
                              className="p-3 rounded-lg bg-void/80 border border-white/[0.06] space-y-1 text-slate-300"
                            >
                              <div className="font-semibold text-cyan-300 text-[11px]">
                                {cite.document_name || 'Document'} {cite.title ? `• ${cite.title}` : ''}
                              </div>
                              {cite.content_snippet && (
                                <p className="italic text-slate-400 text-xs">
                                  &ldquo;{cite.content_snippet}&rdquo;
                                </p>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Assumptions & Limitations */}
                    {((runDetail.assumptions && runDetail.assumptions.length > 0) ||
                      (runDetail.limitations && runDetail.limitations.length > 0)) && (
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2 border-t border-white/[0.06] text-xs font-sans">
                        {runDetail.assumptions && runDetail.assumptions.length > 0 && (
                          <div className="p-3 rounded-lg bg-void/70 border border-white/[0.06] space-y-1">
                            <span className="text-[10px] font-mono uppercase text-slate-400 font-semibold block">
                              EXPLICIT ASSUMPTIONS
                            </span>
                            <ul className="list-disc list-inside text-slate-300 text-xs space-y-0.5">
                              {runDetail.assumptions.map((item, idx) => (
                                <li key={idx}>{item}</li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {runDetail.limitations && runDetail.limitations.length > 0 && (
                          <div className="p-3 rounded-lg bg-void/70 border border-white/[0.06] space-y-1">
                            <span className="text-[10px] font-mono uppercase text-amber-400 font-semibold block">
                              BOUNDARY LIMITATIONS
                            </span>
                            <ul className="list-disc list-inside text-slate-300 text-xs space-y-0.5">
                              {runDetail.limitations.map((item, idx) => (
                                <li key={idx}>{item}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Linked Human Decisions */}
                    {runDetail.decisions && runDetail.decisions.length > 0 && (
                      <div className="space-y-2 pt-2 border-t border-white/[0.06]">
                        <span className="text-[10px] font-mono uppercase text-slate-400 tracking-wider font-semibold">
                          LINKED HUMAN REVIEW DECISIONS ({runDetail.decisions.length})
                        </span>
                        <div className="space-y-2">
                          {runDetail.decisions.map((d) => (
                            <div
                              key={d.id}
                              className="p-3 rounded-lg bg-void/80 border border-white/[0.06] flex items-center justify-between gap-3 text-xs"
                            >
                              <div className="space-y-0.5">
                                <span className="text-white font-medium">{d.recommendation_text}</span>
                                <span className="text-[10px] font-mono text-slate-500 block">
                                  Checkpoint #{d.id}
                                </span>
                              </div>
                              <span className="px-2 py-0.5 rounded-full bg-surface border border-white/[0.08] text-[10px] font-mono uppercase text-slate-300 shrink-0">
                                {d.status}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Footer execution metadata */}
                    <div className="pt-3 border-t border-white/[0.06] flex flex-wrap items-center justify-between gap-2 text-[10px] font-mono text-slate-500">
                      <span>Executed at {formatDate(runDetail.created_at)}</span>
                      <span>Execution ID: {runDetail.id} • Status: {runDetail.status}</span>
                    </div>
                  </div>
                ) : (
                  <div className="p-12 text-center text-xs text-slate-400 space-y-2">
                    <Terminal className="w-8 h-8 text-slate-600 mx-auto" />
                    <p>Select an analysis run from the ledger to inspect full execution details.</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </ErrorBoundary>
  );
};

export default HistoryPage;

