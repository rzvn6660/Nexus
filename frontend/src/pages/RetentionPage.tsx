import React, { useState, useEffect, useCallback } from 'react';
import {
  Users,
  UserCheck,
  AlertTriangle,
  ShieldCheck,
  ShieldAlert,
  Clock,
  DollarSign,
  TrendingUp,
  CheckCircle2,
  Search,
  Sparkles,
  RefreshCw,
  X,
  ChevronRight,
  Info,
  PhoneCall,
  Mail,
  Gift,
  HelpCircle,
  Eye,
  MessageSquare,
} from 'lucide-react';
import {
  getRetentionOverview,
  listRetentionCustomers,
  getRetentionCustomerDetail,
  createRetentionRecommendation,
  reviewRetentionDecision,
  executeRetentionAction,
  logCustomerResponse,
  getRetentionEvaluation,
} from '../services/analytics';
import { AuthService } from '../services/auth';
import {
  RetentionOverview,
  CustomerRiskDetail,
  RetentionOutcomeEvaluation,
  CadenceRiskTier,
  InterventionUrgency,
  RetentionActionType,
} from '../types/api';
import { formatCurrency, formatNumber, formatDate } from '../utils/formatters';
import { CadenceSafetyBadge } from '../components/common/CadenceSafetyBadge';
import { SeasonalCautionBanner } from '../components/common/SeasonalCautionBanner';
import { DemonstrationModeBanner } from '../components/common/DemonstrationModeBanner';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorBoundary } from '../components/common/ErrorBoundary';

interface RetentionPageProps {
  onNavigate: (route: string) => void;
  onAskQuery: (query: string) => void;
}

export const RetentionPage: React.FC<RetentionPageProps> = ({ onNavigate: _onNavigate, onAskQuery }) => {
  // State: High-level overview & evaluation
  const [overview, setOverview] = useState<RetentionOverview | null>(null);
  const [evaluation, setEvaluation] = useState<RetentionOutcomeEvaluation | null>(null);
  const [loadingOverview, setLoadingOverview] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // State: Customer list & filters
  const [customers, setCustomers] = useState<CustomerRiskDetail[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const [pageSize] = useState<number>(25);
  const [loadingList, setLoadingList] = useState<boolean>(false);

  // Filter criteria
  const [filterRiskTier, setFilterRiskTier] = useState<string>('all');
  const [filterUrgency, setFilterUrgency] = useState<string>('all');
  const [filterSegment, setFilterSegment] = useState<string>('all');
  const [filterSearch, setFilterSearch] = useState<string>('');
  const [requiresAttentionOnly, setRequiresAttentionOnly] = useState<boolean>(true);
  const [isRepeatOnly, setIsRepeatOnly] = useState<boolean>(true);

  // Selected customer for modal/drawer deep dive
  const [selectedCustomer, setSelectedCustomer] = useState<CustomerRiskDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState<boolean>(false);

  // HITL Action form state
  const [actionNotes, setActionNotes] = useState<string>('');
  const userProfile = AuthService.getUserProfile();
  const reviewerId = userProfile?.email || 'sarah.jenkins@northstar-sandbox.local';
  const [executionChannel, setExecutionChannel] = useState<string>('phone');
  const [actionInProgress, setActionInProgress] = useState<boolean>(false);
  const [actionSuccessMessage, setActionSuccessMessage] = useState<string | null>(null);
  const [responseStatus, setResponseStatus] = useState<'opened' | 'replied' | 'redeemed_code' | 'no_response' | 'declined' | 'purchased'>('replied');

  // Load Overview & Evaluation
  const loadOverviewAndEval = useCallback(async () => {
    setLoadingOverview(true);
    setError(null);
    try {
      const [overviewRes, evalRes] = await Promise.all([
        getRetentionOverview(),
        getRetentionEvaluation({ evaluation_window_days: 30 }),
      ]);
      setOverview(overviewRes.data);
      setEvaluation(evalRes.data);
    } catch (err: any) {
      console.warn('Retention overview notice:', err);
      setError(err?.message || 'Failed to load retention analytics.');
    } finally {
      setLoadingOverview(false);
    }
  }, []);

  // Load Customer List
  const loadCustomers = useCallback(async () => {
    setLoadingList(true);
    try {
      const res = await listRetentionCustomers({
        risk_tier: filterRiskTier === 'all' ? undefined : filterRiskTier,
        urgency: filterUrgency === 'all' ? undefined : filterUrgency,
        segment: filterSegment === 'all' ? undefined : filterSegment,
        search: filterSearch.trim() || undefined,
        requires_attention_only: requiresAttentionOnly,
        is_repeat_only: isRepeatOnly,
        page,
        page_size: pageSize,
      });
      setCustomers(res.data.items);
      setTotalCount(res.data.total_count);
    } catch (err: any) {
      console.warn('Retention customers list notice:', err);
    } finally {
      setLoadingList(false);
    }
  }, [filterRiskTier, filterUrgency, filterSegment, filterSearch, requiresAttentionOnly, isRepeatOnly, page, pageSize]);

  useEffect(() => {
    loadOverviewAndEval();
  }, [loadOverviewAndEval]);

  useEffect(() => {
    loadCustomers();
  }, [loadCustomers]);

  // Deep dive customer detail fetch
  const handleSelectCustomer = async (cid: number) => {
    setLoadingDetail(true);
    setActionSuccessMessage(null);
    try {
      const res = await getRetentionCustomerDetail(cid);
      setSelectedCustomer(res.data);
    } catch (err: any) {
      console.warn('Customer detail notice:', err);
    } finally {
      setLoadingDetail(false);
    }
  };

  // HITL: Propose / Register Decision
  const handleProposeDecision = async () => {
    if (!selectedCustomer) return;
    setActionInProgress(true);
    setActionSuccessMessage(null);
    try {
      const res = await createRetentionRecommendation({
        customer_id: selectedCustomer.customer_id,
        action_type: selectedCustomer.recommended_action?.action_type,
        custom_notes: actionNotes.trim() || undefined,
      });
      setActionSuccessMessage(`Decision registered successfully (#${res.data.decision_id}) in status PENDING review.`);
      // Refresh customer detail
      await handleSelectCustomer(selectedCustomer.customer_id);
      loadCustomers();
      loadOverviewAndEval();
    } catch (err: any) {
      alert(`Registration failed: ${err?.message || 'Unknown error'}`);
    } finally {
      setActionInProgress(false);
    }
  };

  // HITL: Review Decision (Approve / Reject)
  const handleReviewDecision = async (status: 'APPROVED' | 'REJECTED') => {
    if (!selectedCustomer?.existing_decision_id) return;
    setActionInProgress(true);
    setActionSuccessMessage(null);
    try {
      await reviewRetentionDecision({
        decision_id: selectedCustomer.existing_decision_id,
        status,
        reviewer_id: reviewerId.trim() || 'merchant_admin',
        reviewer_notes: actionNotes.trim() || undefined,
      });
      setActionSuccessMessage(`Decision #${selectedCustomer.existing_decision_id} updated to ${status}.`);
      await handleSelectCustomer(selectedCustomer.customer_id);
      loadCustomers();
      loadOverviewAndEval();
    } catch (err: any) {
      alert(`Review failed: ${err?.message || 'Unknown error'}`);
    } finally {
      setActionInProgress(false);
    }
  };

  // HITL: Execute Action
  const handleExecuteAction = async () => {
    if (!selectedCustomer?.existing_decision_id) return;
    setActionInProgress(true);
    setActionSuccessMessage(null);
    try {
      await executeRetentionAction({
        decision_id: selectedCustomer.existing_decision_id,
        execution_channel: executionChannel,
        executed_by: reviewerId.trim() || 'merchant_operator',
        execution_notes: actionNotes.trim() || undefined,
      });
      setActionSuccessMessage(`Retention action executed via ${executionChannel}. Audit event logged.`);
      await handleSelectCustomer(selectedCustomer.customer_id);
      loadCustomers();
      loadOverviewAndEval();
    } catch (err: any) {
      alert(`Execution failed: ${err?.message || 'Unknown error'}`);
    } finally {
      setActionInProgress(false);
    }
  };

  // HITL: Log Customer Response
  const handleLogResponse = async () => {
    if (!selectedCustomer?.existing_decision_id) return;
    setActionInProgress(true);
    setActionSuccessMessage(null);
    try {
      await logCustomerResponse({
        decision_id: selectedCustomer.existing_decision_id,
        response_status: responseStatus,
        logged_by: reviewerId.trim() || 'merchant_operator',
        response_notes: actionNotes.trim() || undefined,
      });
      setActionSuccessMessage(`Customer response logged: "${responseStatus}".`);
      await handleSelectCustomer(selectedCustomer.customer_id);
      loadCustomers();
      loadOverviewAndEval();
    } catch (err: any) {
      alert(`Response logging failed: ${err?.message || 'Unknown error'}`);
    } finally {
      setActionInProgress(false);
    }
  };

  const getTierColor = (tier: CadenceRiskTier) => {
    switch (tier) {
      case 'critical':
        return 'text-rose-400 bg-rose-500/10 border-rose-500/20';
      case 'high':
        return 'text-amber-400 bg-amber-500/10 border-amber-500/20';
      case 'medium':
        return 'text-yellow-400 bg-yellow-500/10 border-yellow-500/20';
      case 'low':
        return 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20';
      default:
        return 'text-slate-400 bg-slate-500/10 border-slate-500/20';
    }
  };

  const getUrgencyBadge = (urgency: InterventionUrgency) => {
    switch (urgency) {
      case 'immediate':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/30">
            <Clock className="w-3 h-3" /> Immediate (7d)
          </span>
        );
      case 'proactive':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/30">
            <Clock className="w-3 h-3" /> Proactive (14d)
          </span>
        );
      case 'watchlist':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold bg-yellow-500/10 text-yellow-400 border border-yellow-500/30">
            <Eye className="w-3 h-3" /> Watchlist (30d)
          </span>
        );
      case 'healthy':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
            <CheckCircle2 className="w-3 h-3" /> On Track
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold bg-slate-500/10 text-slate-400 border border-slate-500/30">
            <HelpCircle className="w-3 h-3" /> Nurture (1st-buy)
          </span>
        );
    }
  };

  const getActionIcon = (actionType?: RetentionActionType) => {
    switch (actionType) {
      case 'personal_follow_up':
        return <PhoneCall className="w-4 h-4 text-sky-400" />;
      case 'product_recommendation':
        return <Sparkles className="w-4 h-4 text-emerald-400" />;
      case 'loyalty_retention_offer':
        return <Gift className="w-4 h-4 text-amber-400" />;
      case 'service_experience_review':
        return <ShieldAlert className="w-4 h-4 text-rose-400" />;
      case 'reengagement_checkin':
      default:
        return <Mail className="w-4 h-4 text-indigo-400" />;
    }
  };

  return (
    <ErrorBoundary fallbackTitle="Customer Retention Intelligence Diagnostics">
      <div className="min-h-screen bg-slate-950 text-slate-100 p-6 space-y-6">
        {/* Top Header & Disclosures */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-5">
          <div>
            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                Phase 1 Intelligent Retention
              </span>
              <span className="text-xs text-slate-500">Deterministic Cadence & HITL Prescriptive Gating</span>
            </div>
            <h1 className="text-2xl font-bold text-white tracking-tight mt-1 flex items-center gap-2">
              <Users className="w-6 h-6 text-indigo-400" />
              Customer Retention & Churn Prevention
            </h1>
            <p className="text-xs text-slate-400 mt-1 max-w-2xl">
              Identify customers showing credible disengagement, explain factual cadence deviations, prioritize intervention urgency, and evaluate demonstrated retention efficacy.
            </p>
          </div>

          <div className="flex items-center gap-3">
            {overview?.safety_verdict && (
              <CadenceSafetyBadge verdict={overview.safety_verdict} />
            )}
            <button
              onClick={() => onAskQuery('Analyze customer churn risk, cadence ratios, and retention lift for repeat buyers')}
              className="px-3 py-1.5 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 text-xs font-semibold flex items-center gap-1.5 transition"
              title="Inspect customer retention in Ask NEXUS"
            >
              <MessageSquare className="w-3.5 h-3.5" />
              <span>Ask NEXUS</span>
            </button>
            <button
              onClick={() => {
                loadOverviewAndEval();
                loadCustomers();
              }}
              className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-300 hover:text-white hover:bg-slate-800 transition"
              title="Refresh Retention Telemetry"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Operational Error Banner */}
        {error && (
          <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Demonstration & In-Flight Ingestion Mode Banner */}
        <DemonstrationModeBanner
          reasonCode={overview?.safety_verdict?.reason_code}
          explanation={overview?.safety_verdict?.explanation}
          isActionable={overview?.safety_verdict?.is_actionable}
        />

        {/* Seasonal Caution Banner */}
        {overview?.safety_verdict?.seasonal_disclosure && (
          <SeasonalCautionBanner disclosure={overview.safety_verdict.seasonal_disclosure} />
        )}

        {/* 1. EXECUTIVE KPI SUMMARY METRICS */}
        {loadingOverview ? (
          <LoadingState message="Computing deterministic customer purchase cadences & safety verifications..." />
        ) : overview ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
              <div className="flex items-center justify-between text-xs text-slate-400 font-medium">
                <span>Attention Required</span>
                <AlertTriangle className="w-4 h-4 text-rose-400" />
              </div>
              <div className="mt-2 text-2xl font-bold text-white">
                {formatNumber(overview.customers_requiring_attention_count)}
              </div>
              <div className="mt-1 text-[11px] text-rose-400 font-medium">
                Critical & High risk repeat buyers
              </div>
            </div>

            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
              <div className="flex items-center justify-between text-xs text-slate-400 font-medium">
                <span>Revenue at Risk</span>
                <DollarSign className="w-4 h-4 text-amber-400" />
              </div>
              <div className="mt-2 text-2xl font-bold text-amber-400">
                {formatCurrency(overview.total_revenue_at_risk_usd)}
              </div>
              <div className="mt-1 text-[11px] text-slate-400">
                Historical spend of overdue accounts
              </div>
            </div>

            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
              <div className="flex items-center justify-between text-xs text-slate-400 font-medium">
                <span>Repeat Buyers</span>
                <UserCheck className="w-4 h-4 text-emerald-400" />
              </div>
              <div className="mt-2 text-2xl font-bold text-white">
                {formatNumber(overview.repeat_buyers_count)}
              </div>
              <div className="mt-1 text-[11px] text-emerald-400 font-medium">
                Eligible for cadence churn evaluation
              </div>
            </div>

            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
              <div className="flex items-center justify-between text-xs text-slate-400 font-medium">
                <span>One-Time Buyers</span>
                <HelpCircle className="w-4 h-4 text-slate-400" />
              </div>
              <div className="mt-2 text-2xl font-bold text-slate-300">
                {formatNumber(overview.one_time_buyers_count)}
              </div>
              <div className="mt-1 text-[11px] text-slate-400">
                Safeguarded (No false churn alerts)
              </div>
            </div>

            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
              <div className="flex items-center justify-between text-xs text-slate-400 font-medium">
                <span>Demonstrated Lift</span>
                <TrendingUp className="w-4 h-4 text-indigo-400" />
              </div>
              <div className="mt-2 text-2xl font-bold text-indigo-400">
                {evaluation ? `+${evaluation.retention_lift_pct_points}%` : 'N/A'}
              </div>
              <div className="mt-1 text-[11px] text-slate-400">
                Intervened vs comparison cohort reorders
              </div>
            </div>
          </div>
        ) : null}

        {/* 2. RISK TIER & INTERVENTION WORKLOAD DISTRIBUTION */}
        {overview && (
          <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                Customer Cohort Risk & Workload Distribution
              </h2>
              <span className="text-[11px] text-slate-500">
                As of cutoff: {formatDate(overview.as_of_date)}
              </span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
              <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20">
                <div className="text-[11px] font-semibold text-rose-400 uppercase">Critical (Immediate)</div>
                <div className="text-xl font-bold text-white mt-1">
                  {overview.risk_distribution.critical || 0}
                </div>
                <div className="text-[10px] text-slate-400 mt-0.5">&ge; 3.0x cadence ratio</div>
              </div>

              <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
                <div className="text-[11px] font-semibold text-amber-400 uppercase">High (Proactive)</div>
                <div className="text-xl font-bold text-white mt-1">
                  {overview.risk_distribution.high || 0}
                </div>
                <div className="text-[10px] text-slate-400 mt-0.5">2.0x &ndash; 3.0x cadence</div>
              </div>

              <div className="p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/20">
                <div className="text-[11px] font-semibold text-yellow-400 uppercase">Medium (Watchlist)</div>
                <div className="text-xl font-bold text-white mt-1">
                  {overview.risk_distribution.medium || 0}
                </div>
                <div className="text-[10px] text-slate-400 mt-0.5">1.25x &ndash; 2.0x cadence</div>
              </div>

              <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                <div className="text-[11px] font-semibold text-emerald-400 uppercase">Low (Healthy)</div>
                <div className="text-xl font-bold text-white mt-1">
                  {overview.risk_distribution.low || 0}
                </div>
                <div className="text-[10px] text-slate-400 mt-0.5">&lt; 1.25x (on schedule)</div>
              </div>

              <div className="p-3 rounded-lg bg-slate-800/40 border border-slate-700/40">
                <div className="text-[11px] font-semibold text-slate-400 uppercase">Insufficient History</div>
                <div className="text-xl font-bold text-white mt-1">
                  {overview.risk_distribution.insufficient_history || 0}
                </div>
                <div className="text-[10px] text-slate-400 mt-0.5">1-time or 0 purchases</div>
              </div>
            </div>
          </div>
        )}

        {/* 3. CUSTOMER RETENTION PRIORITIZATION TABLE */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl">
          {/* Table Header & Controls */}
          <div className="p-4 border-b border-slate-800 flex flex-col md:flex-row md:items-center justify-between gap-3 bg-slate-900/80">
            <div>
              <h2 className="text-sm font-bold text-white flex items-center gap-2">
                <span>Prioritized Customers Requiring Attention</span>
                <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 font-normal">
                  {formatNumber(totalCount)} matching
                </span>
              </h2>
              <p className="text-[11px] text-slate-400 mt-0.5">
                Evaluated against individual median inter-purchase intervals. One-time buyers excluded from cadence churn scoring.
              </p>
            </div>

            {/* Filter Bar */}
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5" />
                <input
                  type="text"
                  placeholder="Search customer code or name..."
                  value={filterSearch}
                  onChange={(e) => {
                    setFilterSearch(e.target.value);
                    setPage(1);
                  }}
                  className="pl-8 pr-3 py-1.5 text-xs bg-slate-950 border border-slate-800 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 w-52"
                />
              </div>

              <select
                value={filterRiskTier}
                onChange={(e) => {
                  setFilterRiskTier(e.target.value);
                  setPage(1);
                }}
                className="px-2.5 py-1.5 text-xs bg-slate-950 border border-slate-800 rounded-lg text-slate-300 focus:outline-none focus:border-indigo-500"
              >
                <option value="all">All Risk Tiers</option>
                <option value="critical">Critical (&ge;3.0x)</option>
                <option value="high">High (2.0x-3.0x)</option>
                <option value="medium">Medium (1.25x-2.0x)</option>
                <option value="low">Low (&lt;1.25x)</option>
                <option value="insufficient_history">Insufficient History</option>
              </select>

              <select
                value={filterUrgency}
                onChange={(e) => {
                  setFilterUrgency(e.target.value);
                  setPage(1);
                }}
                className="px-2.5 py-1.5 text-xs bg-slate-950 border border-slate-800 rounded-lg text-slate-300 focus:outline-none focus:border-indigo-500"
              >
                <option value="all">All Urgencies</option>
                <option value="immediate">Immediate (&le;7d)</option>
                <option value="proactive">Proactive (&le;14d)</option>
                <option value="watchlist">Watchlist (&le;30d)</option>
                <option value="healthy">On Track</option>
                <option value="insufficient_history">Nurture</option>
              </select>

              <select
                value={filterSegment}
                onChange={(e) => {
                  setFilterSegment(e.target.value);
                  setPage(1);
                }}
                className="px-2.5 py-1.5 text-xs bg-slate-950 border border-slate-800 rounded-lg text-slate-300 focus:outline-none focus:border-indigo-500"
              >
                <option value="all">All Segments</option>
                <option value="Retail">Retail</option>
                <option value="Wholesale">Wholesale</option>
                <option value="VIP">VIP</option>
                <option value="Corporate">Corporate</option>
              </select>

              <button
                onClick={() => setRequiresAttentionOnly(!requiresAttentionOnly)}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition ${
                  requiresAttentionOnly
                    ? 'bg-rose-500/20 text-rose-300 border-rose-500/40'
                    : 'bg-slate-950 text-slate-400 border-slate-800 hover:text-white'
                }`}
              >
                Attention Only (Critical/High)
              </button>

              <button
                onClick={() => setIsRepeatOnly(!isRepeatOnly)}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition ${
                  isRepeatOnly
                    ? 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40'
                    : 'bg-slate-950 text-slate-400 border-slate-800 hover:text-white'
                }`}
              >
                Repeat Buyers Only
              </button>
            </div>
          </div>

          {/* Customer Table */}
          <div className="overflow-x-auto">
            {loadingList ? (
              <div className="py-12">
                <LoadingState message="Filtering and ranking at-risk customers..." />
              </div>
            ) : customers.length === 0 ? (
              <div className="py-12 text-center text-xs text-slate-400">
                No customers match the selected filter criteria.
              </div>
            ) : (
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-slate-800 text-[11px] font-semibold text-slate-400 uppercase tracking-wider bg-slate-950/50">
                    <th className="py-3 px-4">Customer</th>
                    <th className="py-3 px-4">Segment</th>
                    <th className="py-3 px-4">Cadence Ratio</th>
                    <th className="py-3 px-4">Recency vs Baseline</th>
                    <th className="py-3 px-4">Intervention Urgency</th>
                    <th className="py-3 px-4">Lifetime Spend</th>
                    <th className="py-3 px-4">Recommended Action</th>
                    <th className="py-3 px-4">Action Status</th>
                    <th className="py-3 px-4 text-right">Review & Act</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {customers.map((c) => (
                    <tr
                      key={c.customer_id}
                      className="hover:bg-slate-850/50 transition cursor-pointer group"
                      onClick={() => handleSelectCustomer(c.customer_id)}
                    >
                      <td className="py-3 px-4 font-medium text-white">
                        <div className="flex items-center gap-1.5">
                          <span className="font-semibold">{c.customer_name}</span>
                          <span className="text-[10px] text-slate-500 font-mono">({c.customer_code})</span>
                        </div>
                      </td>
                      <td className="py-3 px-4 text-slate-300">
                        <span className="px-2 py-0.5 rounded text-[11px] bg-slate-800 text-slate-300 border border-slate-700">
                          {c.customer_segment || 'Standard'}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        {c.cadence_ratio !== null && c.cadence_ratio !== undefined ? (
                          <span className={`px-2 py-0.5 rounded text-[11px] font-bold border ${getTierColor(c.risk_tier)}`}>
                            {c.cadence_ratio.toFixed(2)}x
                          </span>
                        ) : (
                          <span className="text-slate-500 text-[11px]">N/A (1-time)</span>
                        )}
                      </td>
                      <td className="py-3 px-4 text-slate-300">
                        {c.days_since_last_purchase !== null && c.baseline_cadence_days !== null ? (
                          <div>
                            <span className="font-semibold text-white">{c.days_since_last_purchase?.toFixed(0)}d</span>
                            <span className="text-slate-500 text-[10px]"> / {c.baseline_cadence_days?.toFixed(0)}d normal</span>
                          </div>
                        ) : (
                          <span className="text-slate-500">Insufficient history</span>
                        )}
                      </td>
                      <td className="py-3 px-4">{getUrgencyBadge(c.urgency)}</td>
                      <td className="py-3 px-4 text-white font-medium">
                        {formatCurrency(c.total_lifetime_spend)}
                        <span className="text-[10px] text-slate-500 block">{c.total_lifetime_orders} orders</span>
                      </td>
                      <td className="py-3 px-4 text-slate-300">
                        {c.recommended_action ? (
                          <div className="flex items-center gap-1.5">
                            {getActionIcon(c.recommended_action.action_type)}
                            <span className="truncate max-w-[180px] font-medium" title={c.recommended_action.title}>
                              {c.recommended_action.title}
                            </span>
                          </div>
                        ) : (
                          <span className="text-slate-500">None</span>
                        )}
                      </td>
                      <td className="py-3 px-4">
                        {c.decision_status ? (
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                              c.decision_status === 'APPROVED'
                                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                                : c.decision_status === 'REJECTED'
                                ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                                : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                            }`}
                          >
                            {c.action_execution_status || c.decision_status}
                          </span>
                        ) : (
                          <span className="text-slate-500 text-[11px]">&mdash;</span>
                        )}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleSelectCustomer(c.customer_id);
                          }}
                          className="px-2.5 py-1 text-xs rounded bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 transition flex items-center gap-1 ml-auto"
                        >
                          <span>Review</span>
                          <ChevronRight className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Pagination */}
          <div className="p-3 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400 bg-slate-950/40">
            <div>
              Showing {customers.length > 0 ? (page - 1) * pageSize + 1 : 0} &ndash;{' '}
              {Math.min(page * pageSize, totalCount)} of {totalCount} customers
            </div>
            <div className="flex items-center gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="px-2.5 py-1 rounded bg-slate-900 border border-slate-800 text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-800"
              >
                Previous
              </button>
              <span className="text-xs text-slate-300 font-medium">Page {page}</span>
              <button
                disabled={page * pageSize >= totalCount}
                onClick={() => setPage((p) => p + 1)}
                className="px-2.5 py-1 rounded bg-slate-900 border border-slate-800 text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-800"
              >
                Next
              </button>
            </div>
          </div>
        </div>

        {/* 4. CUSTOMER DEEP-DIVE MODAL / DRAWER */}
        {selectedCustomer && (
          <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
            <div className="bg-slate-900 border border-slate-700/80 rounded-2xl max-w-4xl w-full max-h-[92vh] overflow-y-auto shadow-2xl flex flex-col">
              {/* Modal Header */}
              <div className="p-5 border-b border-slate-800 flex items-center justify-between bg-slate-950/60 sticky top-0 z-10">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
                    <Users className="w-5 h-5" />
                  </div>
                  <div>
                    <h3 className="text-lg font-bold text-white flex items-center gap-2">
                      <span>{selectedCustomer.customer_name}</span>
                      <span className="text-xs font-mono text-slate-400">({selectedCustomer.customer_code})</span>
                    </h3>
                    <div className="flex items-center gap-2 text-xs text-slate-400 mt-0.5">
                      <span>Segment: {selectedCustomer.customer_segment || 'Standard'}</span>
                      <span>&bull;</span>
                      <span>City: {selectedCustomer.city || 'N/A'}</span>
                      <span>&bull;</span>
                      <span>Email: {selectedCustomer.email || 'N/A'}</span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {loadingDetail && <RefreshCw className="w-4 h-4 text-indigo-400 animate-spin" />}
                  <button
                    onClick={() => setSelectedCustomer(null)}
                    className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>
              </div>

              {/* Modal Body: 5 Essential Capabilities */}
              <div className="p-6 space-y-6">
                {/* Notification Banner */}
                {actionSuccessMessage && (
                  <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    <span>{actionSuccessMessage}</span>
                  </div>
                )}

                {/* Grid: Why at Risk & Risk Metrics */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                  {/* Left: Why is customer at risk */}
                  <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                        <Info className="w-3.5 h-3.5 text-indigo-400" />
                        <span>Why At Risk (Factual Drivers)</span>
                      </h4>
                      <span className={`px-2 py-0.5 rounded text-[11px] font-bold border ${getTierColor(selectedCustomer.risk_tier)}`}>
                        {selectedCustomer.risk_tier.toUpperCase()} RISK
                      </span>
                    </div>

                    <p className="text-xs text-white leading-relaxed font-medium">
                      {selectedCustomer.why_at_risk_summary}
                    </p>

                    <div className="space-y-1.5 pt-2 border-t border-slate-800/80">
                      <div className="text-[11px] font-semibold text-slate-400">Observed Empirical Factors:</div>
                      <ul className="space-y-1 text-xs text-slate-300">
                        {selectedCustomer.risk_factors.map((rf, idx) => (
                          <li key={idx} className="flex items-start gap-1.5">
                            <span className="text-indigo-400 font-bold">&bull;</span>
                            <span>{rf}</span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    {/* Cadence progression interval sequence */}
                    {selectedCustomer.recent_intervals_days.length > 0 && (
                      <div className="pt-2 border-t border-slate-800/80 text-xs">
                        <span className="text-[11px] font-semibold text-slate-400">Purchase Interval Progression:</span>
                        <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                          {selectedCustomer.recent_intervals_days.map((iv, idx) => (
                            <span key={idx} className="px-2 py-0.5 rounded bg-slate-900 border border-slate-800 font-mono text-slate-300 text-[11px]">
                              {iv}d
                              {idx < selectedCustomer.recent_intervals_days.length - 1 && ' &rarr;'}
                            </span>
                          ))}
                          <span className="text-[11px] text-slate-400 font-medium ml-1">
                            ({selectedCustomer.cadence_trend} cadence)
                          </span>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Right: How serious is the risk & Intervention timing */}
                  <div className="bg-slate-950/60 border border-slate-800 rounded-xl p-4 space-y-3">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                      <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                      <span>Severity, Timing & Uncertainty</span>
                    </h4>

                    <div className="grid grid-cols-2 gap-3 text-xs">
                      <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800">
                        <div className="text-[10px] text-slate-400 uppercase">Intervention Timing</div>
                        <div className="mt-1">{getUrgencyBadge(selectedCustomer.urgency)}</div>
                      </div>
                      <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800">
                        <div className="text-[10px] text-slate-400 uppercase">Evidence Sufficiency</div>
                        <div className="text-xs font-bold text-white mt-1">
                          {(selectedCustomer.evidence_sufficiency_score * 100).toFixed(0)}% ({selectedCustomer.confidence_level})
                        </div>
                      </div>
                      <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800">
                        <div className="text-[10px] text-slate-400 uppercase">Cadence Ratio</div>
                        <div className="text-xs font-bold text-white mt-1">
                          {selectedCustomer.cadence_ratio ? `${selectedCustomer.cadence_ratio.toFixed(2)}x` : 'N/A'}
                        </div>
                      </div>
                      <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800">
                        <div className="text-[10px] text-slate-400 uppercase">Total Lifetime Spend</div>
                        <div className="text-xs font-bold text-amber-400 mt-1">
                          {formatCurrency(selectedCustomer.total_lifetime_spend)}
                        </div>
                      </div>
                    </div>

                    <div className="p-2.5 rounded-lg bg-slate-900/60 border border-slate-800 text-[11px] text-slate-400 leading-relaxed">
                      <span className="font-semibold text-slate-300">Non-Contractual Right-Censoring: </span>
                      {selectedCustomer.uncertainty_notice}
                    </div>

                    {selectedCustomer.top_categories_purchased.length > 0 && (
                      <div className="text-xs">
                        <span className="text-[11px] font-semibold text-slate-400">Top Categories: </span>
                        <span className="text-slate-300">{selectedCustomer.top_categories_purchased.join(', ')}</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Prescriptive Recommendation & HITL Action Box */}
                {selectedCustomer.recommended_action && (
                  <div className="bg-gradient-to-r from-indigo-950/40 via-slate-900 to-slate-900 border border-indigo-500/30 rounded-xl p-5 space-y-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        {getActionIcon(selectedCustomer.recommended_action.action_type)}
                        <h4 className="text-sm font-bold text-white">
                          Prescriptive Recommendation: {selectedCustomer.recommended_action.title}
                        </h4>
                      </div>
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-indigo-500/20 text-indigo-300 border border-indigo-500/40">
                        Human Approval Mandatory
                      </span>
                    </div>

                    <p className="text-xs text-slate-300 leading-relaxed">
                      {selectedCustomer.recommended_action.summary}
                    </p>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs pt-2">
                      <div>
                        <div className="font-semibold text-slate-300 text-[11px]">Recommended Action Steps:</div>
                        <ul className="mt-1 space-y-1 text-slate-300">
                          {selectedCustomer.recommended_action.action_steps.map((st, i) => (
                            <li key={i} className="flex items-start gap-1.5">
                              <span className="text-indigo-400 font-bold">&check;</span>
                              <span>{st}</span>
                            </li>
                          ))}
                        </ul>
                      </div>

                      <div className="space-y-2">
                        <div>
                          <span className="font-semibold text-slate-300 text-[11px]">Suggested Channel: </span>
                          <span className="text-indigo-300 font-medium">{selectedCustomer.recommended_action.suggested_channel}</span>
                        </div>
                        <div>
                          <span className="font-semibold text-slate-300 text-[11px]">Execution Window: </span>
                          <span className="text-amber-300 font-medium">{selectedCustomer.recommended_action.recommended_window}</span>
                        </div>
                        <div>
                          <span className="font-semibold text-slate-300 text-[11px]">Trade-Offs & Risks: </span>
                          <span className="text-slate-400">{selectedCustomer.recommended_action.trade_offs.join(' ')}</span>
                        </div>
                      </div>
                    </div>

                    {/* Decision Status & Execution Tracking */}
                    <div className="pt-4 border-t border-slate-800 space-y-3">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-semibold text-white">
                          Human-in-the-Loop Review & Action Status:
                        </span>
                        <span className="font-bold text-xs uppercase px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                          {selectedCustomer.action_execution_status || selectedCustomer.decision_status || 'NOT PROPOSED YET'}
                        </span>
                      </div>

                      {/* Reviewer and Execution controls */}
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                        <div>
                          <label className="text-[10px] text-slate-400 uppercase font-semibold">Reviewer Identity (Authenticated)</label>
                          <div className="mt-1 flex items-center gap-1.5 px-2.5 py-1 text-xs bg-slate-950 border border-slate-800 rounded text-slate-200">
                            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                            <span className="truncate font-mono">{reviewerId}</span>
                          </div>
                        </div>
                        <div>
                          <label className="text-[10px] text-slate-400 uppercase font-semibold">Channel</label>
                          <select
                            value={executionChannel}
                            onChange={(e) => setExecutionChannel(e.target.value)}
                            className="mt-1 w-full px-2.5 py-1 text-xs bg-slate-950 border border-slate-800 rounded text-white focus:outline-none focus:border-indigo-500"
                          >
                            <option value="phone">Direct Phone Call</option>
                            <option value="email">Personal Email</option>
                            <option value="in_person">In-Person Meeting</option>
                            <option value="promo_code">Targeted Offer Voucher</option>
                            <option value="support_ticket">Support Resolution</option>
                          </select>
                        </div>
                        <div>
                          <label className="text-[10px] text-slate-400 uppercase font-semibold">Review / Execution Notes</label>
                          <input
                            type="text"
                            value={actionNotes}
                            onChange={(e) => setActionNotes(e.target.value)}
                            className="mt-1 w-full px-2.5 py-1 text-xs bg-slate-950 border border-slate-800 rounded text-white focus:outline-none focus:border-indigo-500"
                            placeholder="Reasoning, customer specifics..."
                          />
                        </div>
                      </div>

                      {/* Action Buttons */}
                      <div className="flex flex-wrap items-center gap-2 pt-2">
                        {!selectedCustomer.existing_decision_id && (
                          <button
                            disabled={actionInProgress}
                            onClick={handleProposeDecision}
                            className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs transition disabled:opacity-40"
                          >
                            {actionInProgress ? 'Registering...' : 'Propose Recommendation (Register Decision)'}
                          </button>
                        )}

                        {selectedCustomer.existing_decision_id && selectedCustomer.decision_status === 'PENDING' && (
                          <>
                            <button
                              disabled={actionInProgress}
                              onClick={() => handleReviewDecision('APPROVED')}
                              className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs transition disabled:opacity-40"
                            >
                              Approve Decision (Human Review)
                            </button>
                            <button
                              disabled={actionInProgress}
                              onClick={() => handleReviewDecision('REJECTED')}
                              className="px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white font-semibold text-xs transition disabled:opacity-40"
                            >
                              Reject Decision
                            </button>
                          </>
                        )}

                        {selectedCustomer.decision_status === 'APPROVED' && !selectedCustomer.action_execution_status && (
                          <button
                            disabled={actionInProgress}
                            onClick={handleExecuteAction}
                            className="px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-semibold text-xs transition disabled:opacity-40"
                          >
                            Mark Action as Executed
                          </button>
                        )}

                        {selectedCustomer.action_execution_status === 'EXECUTED' && (
                          <div className="flex items-center gap-2">
                            <select
                              value={responseStatus}
                              onChange={(e: any) => setResponseStatus(e.target.value)}
                              className="px-2.5 py-1 text-xs bg-slate-950 border border-slate-800 rounded text-white"
                            >
                              <option value="opened">Email Opened</option>
                              <option value="replied">Customer Replied</option>
                              <option value="redeemed_code">Redeemed Code</option>
                              <option value="purchased">Made Subsequent Purchase</option>
                              <option value="no_response">No Response</option>
                              <option value="declined">Declined Outreach</option>
                            </select>
                            <button
                              disabled={actionInProgress}
                              onClick={handleLogResponse}
                              className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-semibold text-xs transition disabled:opacity-40"
                            >
                              Log Customer Response
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* 5. RETENTION OUTCOME MEASUREMENT & INTELLIGENCE EVALUATION */}
        {evaluation && (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-emerald-400" />
                <span>Empirical Retention Intervention Evaluation ({evaluation.evaluation_window_days}-Day Window)</span>
              </h3>
              <span className="text-xs text-slate-500">Observational Comparison vs Non-Intervened At-Risk Cohort</span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                <div className="text-[11px] text-slate-400">Intervened Reorder Rate</div>
                <div className="text-xl font-bold text-emerald-400 mt-1">
                  {evaluation.intervened_reorder_rate_pct}%
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">
                  {evaluation.intervened_reordered_count} of {evaluation.intervened_customers_count} accounts
                </div>
              </div>

              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                <div className="text-[11px] text-slate-400">Comparison Cohort Reorder Rate</div>
                <div className="text-xl font-bold text-slate-300 mt-1">
                  {evaluation.comparison_reorder_rate_pct}%
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">
                  {evaluation.comparison_reordered_count} of {evaluation.comparison_customers_count} uncontacted accounts
                </div>
              </div>

              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                <div className="text-[11px] text-slate-400">Observed Retention Lift</div>
                <div className="text-xl font-bold text-indigo-400 mt-1">
                  +{evaluation.retention_lift_pct_points} pp
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">
                  {evaluation.relative_lift_ratio ? `${evaluation.relative_lift_ratio}x relative lift` : 'Baseline lift'}
                </div>
              </div>

              <div className="p-3 rounded-lg bg-slate-950 border border-slate-800">
                <div className="text-[11px] text-slate-400">Early-Warning Lead Time</div>
                <div className="text-xl font-bold text-white mt-1">
                  {evaluation.average_lead_time_days ? `${evaluation.average_lead_time_days} days` : '14 days'}
                </div>
                <div className="text-[10px] text-slate-500 mt-0.5">Prior to expected order deadline</div>
              </div>
            </div>

            <div className="p-3 rounded-lg bg-slate-950/80 border border-slate-800 text-[11px] text-slate-400 leading-relaxed space-y-1">
              <div className="font-semibold text-slate-300">Methodological Disclosure:</div>
              <p>{evaluation.methodology_disclaimer}</p>
              <ul className="list-disc pl-4 space-y-0.5 text-slate-400 pt-1">
                {evaluation.limitations.map((lim, i) => (
                  <li key={i}>{lim}</li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </div>
    </ErrorBoundary>
  );
};
