import React, { useState, useEffect, useCallback } from 'react';
import {
  BarChart3,
  Package,
  Users,
  ShieldCheck,
  SearchCode,
  TrendingUp,
  TrendingDown,
  Sparkles,
  ArrowRight,
  ArrowUpRight,
  Database,
  AlertTriangle,
  RefreshCw,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts';
import {
  getFinancialSummary,
  getRevenueTimeSeries,
  getProfitTimeSeries,
  getSalesTimeSeries,
  getProductRankings,
  getCustomerSegments,
} from '../services/analytics';
import {
  SummaryResponse,
  TimeSeriesResponse,
  ProductRankingResponse,
  BreakdownResponse,
  EvidenceRecord,
} from '../types/api';
import {
  formatCurrency,
  formatNumber,
  formatPercent,
  getGlobalCurrencySymbol,
} from '../utils/formatters';
import { EvidencePanel } from '../components/common/EvidencePanel';

interface AnalyticsPageProps {
  onNavigate: (route: string) => void;
  onAskQuery: (query: string) => void;
}

export const AnalyticsPage: React.FC<AnalyticsPageProps> = ({
  onNavigate,
  onAskQuery,
}) => {
  const [selectedMetric, setSelectedMetric] = useState<'revenue' | 'profit' | 'units'>('revenue');
  const [granularity, setGranularity] = useState<'monthly' | 'weekly'>('monthly');

  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [timeSeries, setTimeSeries] = useState<TimeSeriesResponse | null>(null);
  const [products, setProducts] = useState<ProductRankingResponse | null>(null);
  const [customerSegments, setCustomerSegments] = useState<BreakdownResponse | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showErrorDetails, setShowErrorDetails] = useState(false);
  const [activeEvidence, setActiveEvidence] = useState<EvidenceRecord | null>(null);

  const fetchAnalytics = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const timeSeriesPromise =
        selectedMetric === 'profit'
          ? getProfitTimeSeries({ granularity })
          : selectedMetric === 'units'
          ? getSalesTimeSeries({ granularity })
          : getRevenueTimeSeries({ granularity });

      const results = await Promise.allSettled([
        getFinancialSummary({ granularity }),
        getProductRankings({ ranking_metric: selectedMetric, limit: 10 }),
        getCustomerSegments(),
        timeSeriesPromise,
      ]);

      const [sumRes, prodRes, custRes, tsRes] = results;

      if (sumRes.status === 'fulfilled') {
        setSummary(sumRes.value);
      } else {
        setError(sumRes.reason?.message || 'Failed to fetch deterministic financial summary.');
      }

      if (prodRes.status === 'fulfilled') {
        setProducts(prodRes.value);
      } else {
        setProducts(null);
      }

      if (custRes.status === 'fulfilled') {
        setCustomerSegments(custRes.value);
      } else {
        setCustomerSegments(null);
      }

      if (tsRes.status === 'fulfilled') {
        setTimeSeries(tsRes.value);
      } else {
        setTimeSeries(null);
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to fetch deterministic analytics telemetry.');
    } finally {
      setLoading(false);
    }
  }, [selectedMetric, granularity]);

  useEffect(() => {
    fetchAnalytics();
  }, [fetchAnalytics]);

  if (loading && !summary) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-24 rounded-2xl bg-surface/60 border border-surface-elevated" />
        <div className="h-32 rounded-2xl bg-surface/60 border border-surface-elevated" />
        <div className="h-80 rounded-2xl bg-surface/60 border border-surface-elevated" />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="h-72 rounded-2xl bg-surface/60 border border-surface-elevated" />
          <div className="h-72 rounded-2xl bg-surface/60 border border-surface-elevated" />
        </div>
      </div>
    );
  }

  if (error && !summary) {
    const isConnectionError =
      error.includes('500') ||
      error.includes('Failed to fetch') ||
      error.includes('NetworkError') ||
      error.includes('network');

    return (
      <div className="space-y-6 animate-in fade-in duration-200 max-w-3xl mx-auto py-6">
        <div className="rounded-3xl border border-surface-elevated bg-surface/70 p-6 sm:p-10 shadow-obsidian space-y-6">
          <div className="flex items-start gap-4">
            <div className="w-12 h-12 rounded-2xl bg-rose-950/60 border border-rose-500/30 flex items-center justify-center text-rose-400 shrink-0 shadow-sm">
              <Database className="w-6 h-6" />
            </div>
            <div className="space-y-1.5 flex-1 min-w-0">
              <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-rose-950/60 border border-rose-500/30 text-[10px] font-mono text-rose-300 uppercase">
                <AlertTriangle className="w-3 h-3 text-rose-400" />
                <span>Analytics Engine Notice</span>
              </div>
              <h2 className="text-xl sm:text-2xl font-bold text-white font-sans tracking-tight">
                Unable to Connect to Financial Telemetry
              </h2>
              <p className="text-xs sm:text-sm text-slate-300 font-sans leading-relaxed">
                {isConnectionError
                  ? 'The deterministic analytics service could not retrieve transactional ledger records from the backend database. This occurs when the transactional database service is offline or sales ledgers have not yet been ingested.'
                  : error}
              </p>
            </div>
          </div>

          {/* Actionable Recovery Options */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2 border-t border-surface-elevated/80 font-sans">
            <button
              onClick={() => onNavigate('/data')}
              className="p-4 rounded-xl bg-void/70 hover:bg-surface-elevated/60 border border-surface-elevated hover:border-cyan-500/40 text-left transition-all group"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-white group-hover:text-cyan-300 transition-colors">
                  Open Data Gateway
                </span>
                <ArrowRight className="w-3.5 h-3.5 text-slate-500 group-hover:text-cyan-400 transition-colors" />
              </div>
              <p className="text-[11px] text-slate-400 mt-1">
                Upload and verify sales orders, product SKUs, and customer records.
              </p>
            </button>

            <button
              onClick={() => onNavigate('/knowledge')}
              className="p-4 rounded-xl bg-void/70 hover:bg-surface-elevated/60 border border-surface-elevated hover:border-cyan-500/40 text-left transition-all group"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-white group-hover:text-cyan-300 transition-colors">
                  Review Metric Definitions
                </span>
                <ArrowRight className="w-3.5 h-3.5 text-slate-500 group-hover:text-cyan-400 transition-colors" />
              </div>
              <p className="text-[11px] text-slate-400 mt-1">
                Inspect mathematical formulas and deterministic calculation schemas.
              </p>
            </button>
          </div>

          {/* Primary Action Row */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
            <button
              onClick={fetchAnalytics}
              className="btn-primary py-2 px-4 text-xs shadow-cyan-subtle inline-flex items-center gap-2"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Retry Telemetry Sync</span>
            </button>

            <button
              onClick={() => setShowErrorDetails(!showErrorDetails)}
              className="text-xs font-mono text-slate-400 hover:text-slate-200 inline-flex items-center gap-1.5 transition-colors"
            >
              <span>Technical Diagnostics</span>
              {showErrorDetails ? (
                <ChevronUp className="w-3.5 h-3.5" />
              ) : (
                <ChevronDown className="w-3.5 h-3.5" />
              )}
            </button>
          </div>

          {/* Technical Diagnostics Drawer */}
          {showErrorDetails && (
            <div className="p-3.5 rounded-xl bg-void border border-surface-elevated font-mono text-xs text-slate-400 space-y-1.5">
              <div className="text-slate-300 text-[11px] font-semibold">// Error Diagnostic Information</div>
              <div className="text-rose-400 break-all">{error}</div>
              <div className="text-slate-500 text-[11px]">Target: /api/v1/analytics/summary</div>
            </div>
          )}
        </div>
      </div>
    );
  }

  const s = summary?.data;

  const netSalesVal = s?.net_sales?.value ?? s?.net_revenue?.value;
  const netSalesChange =
    s?.net_sales?.percentage_change ??
    s?.net_revenue?.percentage_change ??
    s?.comparison?.net_sales?.percentage_change;

  const grossProfitVal = s?.gross_profit?.value;
  const grossProfitChange =
    s?.gross_profit?.percentage_change ??
    s?.comparison?.gross_profit?.percentage_change;

  const unitsSoldVal = s?.units_sold?.value ?? s?.orders?.value ?? s?.orders_count?.value ?? 0;
  const unitsSoldChange =
    s?.units_sold?.percentage_change ??
    s?.comparison?.units_sold?.percentage_change ??
    s?.orders?.percentage_change;

  // First-use empty workspace check
  const isWorkspaceEmpty = !summary || (Number(netSalesVal ?? 0) === 0 && Number(unitsSoldVal ?? 0) === 0);
  if (isWorkspaceEmpty) {
    return (
      <div className="space-y-8 animate-in fade-in duration-200">
        <div className="rounded-3xl border border-surface-elevated bg-surface/60 p-8 sm:p-12 text-center max-w-2xl mx-auto space-y-6 my-8 shadow-obsidian">
          <div className="w-16 h-16 rounded-2xl bg-cyan-950/60 border border-cyan-500/30 flex items-center justify-center mx-auto text-cyan-400 shadow-cyan-subtle">
            <BarChart3 className="w-8 h-8" />
          </div>

          <div className="space-y-2">
            <h2 className="text-2xl font-bold text-white font-sans tracking-tight">
              Your Financial Telemetry Workspace is Ready for Data
            </h2>
            <p className="text-sm text-slate-300 max-w-lg mx-auto leading-relaxed font-sans">
              Connect transactional sales ledgers, customer records, and product catalog data to activate continuous time-series analytics, SKU rankings, and customer cohort decomposition.
            </p>
          </div>

          {/* Supported Format Indicators */}
          <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
            <span className="text-[11px] font-mono text-slate-400 uppercase">Supported Formats:</span>
            <span className="px-2.5 py-1 rounded-lg bg-surface border border-surface-elevated text-xs font-mono text-cyan-300">
              CSV Files
            </span>
            <span className="px-2.5 py-1 rounded-lg bg-surface border border-surface-elevated text-xs font-mono text-cyan-300">
              Excel (.xlsx, .xls)
            </span>
            <span className="px-2.5 py-1 rounded-lg bg-surface border border-surface-elevated text-xs font-mono text-cyan-300">
              PostgreSQL Relational
            </span>
          </div>

          {/* Feature Activation Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-left pt-2 font-sans">
            <div className="p-3.5 rounded-xl bg-void/60 border border-surface-elevated/70 space-y-1">
              <span className="text-[10px] font-mono uppercase text-cyan-400 font-semibold block">01 / TIME-SERIES</span>
              <p className="text-xs font-bold text-white">Continuous Progression</p>
              <p className="text-[11px] text-slate-400">Track net revenue, gross profits, and order volumes over monthly or weekly intervals.</p>
            </div>
            <div className="p-3.5 rounded-xl bg-void/60 border border-surface-elevated/70 space-y-1">
              <span className="text-[10px] font-mono uppercase text-emerald-400 font-semibold block">02 / LEADERBOARD</span>
              <p className="text-xs font-bold text-white">Product Performance</p>
              <p className="text-[11px] text-slate-400">Rank product SKUs by net revenue contribution, unit sales volume, or gross margin retention.</p>
            </div>
            <div className="p-3.5 rounded-xl bg-void/60 border border-surface-elevated/70 space-y-1">
              <span className="text-[10px] font-mono uppercase text-violet-400 font-semibold block">03 / SEGMENTS</span>
              <p className="text-xs font-bold text-white">Customer Cohorts</p>
              <p className="text-[11px] text-slate-400">Decompose buyer concentrations, repeat transaction frequencies, and demographic tiers.</p>
            </div>
          </div>

          {/* Action Row */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-3">
            <button
              onClick={() => onNavigate('/data')}
              className="btn-primary px-6 py-2.5 text-xs shadow-cyan-glow w-full sm:w-auto"
            >
              <span>Connect Transactional Data in Gateway</span>
              <ArrowRight className="w-4 h-4" />
            </button>
            <button
              onClick={() => onNavigate('/knowledge')}
              className="btn-secondary px-4 py-2.5 text-xs w-full sm:w-auto"
            >
              <span>Review Semantic KPI Dictionary</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  const getMetricDisplayTitle = (metric: 'revenue' | 'profit' | 'units') => {
    switch (metric) {
      case 'revenue':
        return 'Net Revenue';
      case 'profit':
        return 'Gross Profit';
      case 'units':
        return 'Commercial Units Sold';
    }
  };

  const currentMetricValue =
    selectedMetric === 'revenue'
      ? formatCurrency(netSalesVal, true)
      : selectedMetric === 'profit'
      ? (grossProfitVal !== undefined && grossProfitVal !== null ? formatCurrency(grossProfitVal, true) : '—')
      : `${formatNumber(unitsSoldVal)} units`;

  const currentMetricChange =
    selectedMetric === 'revenue'
      ? netSalesChange
      : selectedMetric === 'profit'
      ? grossProfitChange
      : unitsSoldChange;

  const comparisonPeriodLabel = granularity === 'monthly' ? 'vs prior month' : 'vs prior week';

  const formatYAxisTick = (v: number) => {
    if (selectedMetric === 'units') {
      if (v >= 1000000) return `${(v / 1000000).toFixed(1)}M`;
      if (v >= 1000) return `${(v / 1000).toFixed(0)}K`;
      return formatNumber(v);
    }
    const symbol = getGlobalCurrencySymbol();
    if (Math.abs(v) >= 1000000) return `${symbol}${(v / 1000000).toFixed(1)}M`;
    if (Math.abs(v) >= 1000) return `${symbol}${(v / 1000).toFixed(0)}K`;
    return `${symbol}${v}`;
  };

  return (
    <div className="space-y-6 sm:space-y-8 animate-in fade-in duration-200">
      {/* 1. COMPACT PAGE HEADER */}
      <section className="p-5 sm:p-6 rounded-2xl bg-surface/70 border border-surface-elevated shadow-obsidian flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="space-y-1 max-w-2xl">
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-500/30 text-[10px] font-sans font-semibold text-cyan-300">
              <BarChart3 className="w-2.5 h-2.5 text-cyan-400" />
              <span>DETERMINISTIC ANALYTICS LAYER</span>
            </span>
            <span className="text-[11px] text-slate-400 font-sans hidden sm:inline">
              • Relational SQL Telemetry
            </span>
          </div>

          <h2 className="text-xl sm:text-2xl font-bold text-white font-sans tracking-tight">
            Deterministic Financial Telemetry
          </h2>

          <p className="text-xs text-slate-300 font-sans leading-relaxed">
            Mathematical business metrics calculated directly from database records without estimation.
          </p>
        </div>

        {/* Action Triggers */}
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <button
            onClick={() => onAskQuery(`Analyze the current ${selectedMetric} variance and drivers`)}
            className="btn-primary py-1.5 px-3 text-xs shadow-cyan-subtle"
            title="Ask AI Intelligence Console about this metric"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>Ask Analyst</span>
          </button>

          {summary?.evidence && (
            <button
              onClick={() => setActiveEvidence(summary.evidence)}
              className="btn-secondary py-1.5 px-3 text-xs"
              title="Inspect calculation lineage and verification parameters"
            >
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>Verify SQL Evidence</span>
            </button>
          )}
        </div>
      </section>

      {/* 2. ANALYTICAL TARGET BANNER & WORKFLOW CONTROLS */}
      <section className="p-5 sm:p-6 rounded-2xl bg-surface/70 border border-surface-elevated shadow-obsidian space-y-5">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-elevated/80 pb-4">
          <div className="space-y-1">
            <span className="text-[10px] font-sans uppercase tracking-wider text-cyan-400 font-semibold">
              ACTIVE EXPLORATION TARGET
            </span>
            <div className="flex flex-wrap items-baseline gap-3">
              <h3 className="text-xl sm:text-2xl font-bold text-white font-sans">
                {getMetricDisplayTitle(selectedMetric)}
              </h3>
              <span className="text-2xl sm:text-3xl font-extrabold font-sans text-cyan-300 tracking-tight">
                {currentMetricValue}
              </span>
              {currentMetricChange !== null && currentMetricChange !== undefined && (
                <span
                  className={`inline-flex items-center gap-1 text-xs font-mono font-semibold px-2 py-0.5 rounded-full border ${
                    currentMetricChange >= 0
                      ? 'text-emerald-300 bg-emerald-950/60 border-emerald-800/80'
                      : 'text-rose-300 bg-rose-950/60 border-rose-800/80'
                  }`}
                >
                  {currentMetricChange >= 0 ? <TrendingUp className="w-3 h-3 text-emerald-400" /> : <TrendingDown className="w-3 h-3 text-rose-400" />}
                  <span>{formatPercent(currentMetricChange)} {comparisonPeriodLabel}</span>
                </span>
              )}
            </div>
          </div>

          {/* Connected Workflow Action Triggers */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => onNavigate('/investigations')}
              className="btn-secondary py-1.5 px-3 text-xs group"
              title="Decompose variance drivers in diagnostic root-cause engine"
            >
              <SearchCode className="w-3.5 h-3.5 text-cyan-400 group-hover:scale-105 transition-transform" />
              <span>Decompose Drivers</span>
            </button>

            <button
              onClick={() => onNavigate('/forecasts')}
              className="btn-secondary py-1.5 px-3 text-xs group"
              title="Project next periods in forecasting engine"
            >
              <TrendingUp className="w-3.5 h-3.5 text-violet-400 group-hover:scale-105 transition-transform" />
              <span>Project Horizon</span>
            </button>
          </div>
        </div>

        {/* Filter Controls (Metric & Granularity) */}
        <div className="flex flex-wrap items-center justify-between gap-4 text-xs font-sans">
          <div className="flex items-center gap-2.5">
            <span className="text-slate-400 font-medium">Metric Target:</span>
            <div className="inline-flex rounded-xl bg-void border border-surface-elevated p-1">
              {(['revenue', 'profit', 'units'] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setSelectedMetric(m)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all capitalize ${
                    selectedMetric === m
                      ? 'bg-cyan-500 text-slate-950 font-bold shadow-cyan-subtle'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  {m === 'units' ? 'Unit Sales' : m}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <span className="text-slate-400 font-medium">Granularity:</span>
            <div className="inline-flex rounded-xl bg-void border border-surface-elevated p-1">
              {(['monthly', 'weekly'] as const).map((g) => (
                <button
                  key={g}
                  onClick={() => setGranularity(g)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all capitalize ${
                    granularity === g
                      ? 'bg-surface-elevated text-white border border-white/10'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  {g} View
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* 3. TIME SERIES CHART SECTION */}
      <section className="rounded-2xl border border-surface-elevated bg-surface/70 p-5 sm:p-6 space-y-4 shadow-obsidian">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-surface-elevated/80 pb-3">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-bold text-white font-sans">
                {getMetricDisplayTitle(selectedMetric)} Telemetry Progression ({granularity})
              </h3>
              <span className="px-2 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-500/30 text-[10px] font-mono text-cyan-300 uppercase">
                Continuous Series
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5 font-sans">
              Aggregated from completed sales orders without sampling or approximation.
            </p>
          </div>

          {timeSeries?.evidence && (
            <button
              onClick={() => setActiveEvidence(timeSeries.evidence)}
              className="text-xs text-cyan-400 hover:text-cyan-300 hover:underline flex items-center gap-1.5 font-medium font-sans self-start sm:self-auto"
            >
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>Inspect Time-Series SQL</span>
            </button>
          )}
        </div>

        <div className="h-72 w-full pt-2">
          {timeSeries?.data?.points && timeSeries.data.points.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={timeSeries.data.points.map((pt) => ({ label: pt.period_label, value: pt.value }))}
                margin={{ top: 10, right: 20, left: 10, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#1E293B" vertical={false} />
                <XAxis dataKey="label" stroke="#64748B" fontSize={11} tickLine={false} axisLine={{ stroke: '#334155' }} />
                <YAxis
                  stroke="#64748B"
                  fontSize={11}
                  tickLine={false}
                  axisLine={{ stroke: '#334155' }}
                  tickFormatter={formatYAxisTick}
                />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (active && payload && payload.length) {
                      return (
                        <div className="rounded-xl border border-surface-highlight bg-void-sub p-3 shadow-obsidian text-xs font-sans">
                          <p className="text-slate-400 font-medium">{label}</p>
                          <p className="text-cyan-400 font-bold text-sm mt-0.5 font-mono">
                            {selectedMetric === 'units'
                              ? `${formatNumber(payload[0].value as number)} units`
                              : formatCurrency(payload[0].value as number)}
                          </p>
                          <span className="text-[10px] text-slate-500 block mt-1">Verified Database Telemetry</span>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="#06B6D4"
                  strokeWidth={2.5}
                  dot={{ fill: '#06B6D4', r: 3.5, strokeWidth: 1, stroke: '#070A12' }}
                  activeDot={{ r: 5, fill: '#22D3EE', strokeWidth: 2, stroke: '#070A12' }}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-full min-h-[16rem] flex flex-col items-center justify-center p-6 text-center rounded-2xl bg-void/40 border border-dashed border-surface-elevated space-y-2">
              <BarChart3 className="w-8 h-8 text-slate-500" />
              <p className="text-xs font-semibold text-slate-200 font-sans">
                {selectedMetric === 'profit'
                  ? 'Profit Telemetry Unavailable: Product Unit Costs Required'
                  : 'Telemetry Unavailable: Chronological Data Points Required'}
              </p>
              <p className="text-[11px] text-slate-400 max-w-sm font-sans leading-relaxed">
                {selectedMetric === 'profit'
                  ? 'Calculating historical profit trends requires product catalog costs (COGS) mapped to order line items.'
                  : 'No chronological data points found for this period filter.'}
              </p>
            </div>
          )}
        </div>
      </section>

      {/* 4. PRODUCT LEADERBOARD & CUSTOMER SEGMENTS */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Top Products Leaderboard Table */}
        <section className="rounded-2xl border border-surface-elevated bg-surface/70 p-5 sm:p-6 space-y-4 shadow-obsidian flex flex-col justify-between">
          <div className="flex items-center justify-between border-b border-surface-elevated/80 pb-3">
            <h3 className="text-base font-bold text-white font-sans flex items-center gap-2">
              <Package className="w-4 h-4 text-cyan-400" />
              <span>Product Leaderboard (Top 10)</span>
            </h3>
            <span className="text-[11px] font-sans text-slate-400">
              Ranked by {getMetricDisplayTitle(selectedMetric)}
            </span>
          </div>

          <div className="overflow-x-auto flex-1">
            {(() => {
              const productList = Array.isArray(products?.data)
                ? products.data
                : Array.isArray((products?.data as any)?.items)
                ? (products?.data as any).items
                : [];
              if (productList.length > 0) {
                return (
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-surface-elevated/80 text-slate-400 font-sans text-[11px]">
                        <th className="pb-2.5 font-semibold">SKU / Product</th>
                        <th className="pb-2.5 text-right font-semibold">
                          {selectedMetric === 'revenue' ? 'Net Revenue' : selectedMetric === 'profit' ? 'Gross Profit' : 'Units Sold'}
                        </th>
                        <th className="pb-2.5 text-right font-semibold">
                          {selectedMetric === 'units' ? 'Net Revenue' : selectedMetric === 'profit' ? 'Gross Margin' : 'Units Sold'}
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-surface-elevated/60">
                      {productList.map((p: any, idx: number) => (
                        <tr
                          key={idx}
                          onClick={() => onAskQuery(`Analyze performance and margin drivers for SKU ${p.sku} (${p.product_name})`)}
                          className="hover:bg-surface-elevated/50 transition-colors cursor-pointer group"
                          title="Click to query NEXUS intelligence regarding this product"
                        >
                          <td className="py-2.5 font-medium text-slate-200">
                            <div className="font-sans font-semibold text-slate-100 group-hover:text-cyan-300 transition-colors flex items-center gap-1.5">
                              <span>{p.product_name}</span>
                              <ArrowUpRight className="w-3 h-3 text-slate-500 opacity-0 group-hover:opacity-100 group-hover:text-cyan-400 transition-all shrink-0" />
                            </div>
                            <div className="font-mono text-[10px] text-slate-400">{p.sku} • {p.category}</div>
                          </td>
                          <td className="py-2.5 text-right font-mono font-semibold text-white">
                            {selectedMetric === 'units'
                              ? formatNumber(p.metric_value ?? p.units_sold)
                              : formatCurrency(p.metric_value ?? (selectedMetric === 'profit' ? p.gross_profit : p.revenue), true)}
                          </td>
                          <td className="py-2.5 text-right font-mono text-slate-300">
                            {selectedMetric === 'units'
                              ? formatCurrency(p.revenue, true)
                              : selectedMetric === 'profit'
                              ? (p.margin_pct !== undefined && p.margin_pct !== null ? `${p.margin_pct.toFixed(1)}%` : formatNumber(p.units_sold))
                              : formatNumber(p.units_sold)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                );
              }
              return (
                <div className="py-12 px-4 text-center rounded-xl bg-void/40 border border-dashed border-surface-elevated space-y-2">
                  <Package className="w-8 h-8 text-slate-500 mx-auto" />
                  <p className="text-xs font-semibold text-slate-300 font-sans">No Product-Level Telemetry Available</p>
                  <p className="text-[11px] text-slate-400 max-w-sm mx-auto font-sans leading-relaxed">
                    Product rankings require product catalog items and order line items. Ingest catalog records via Data Gateway to unlock SKU-level insights.
                  </p>
                </div>
              );
            })()}
          </div>
        </section>

        {/* Customer Cohort Segments */}
        <section className="rounded-2xl border border-surface-elevated bg-surface/70 p-5 sm:p-6 space-y-4 shadow-obsidian flex flex-col justify-between">
          <div className="flex items-center justify-between border-b border-surface-elevated/80 pb-3">
            <h3 className="text-base font-bold text-white font-sans flex items-center gap-2">
              <Users className="w-4 h-4 text-emerald-400" />
              <span>Customer Segmentation Analysis</span>
            </h3>
            <span className="text-[11px] font-sans text-slate-400">Behavioral cohorts</span>
          </div>

          <div className="space-y-3 flex-1">
            {customerSegments?.data?.items && customerSegments.data.items.length > 0 ? (
              customerSegments.data.items.map((seg, idx) => {
                const dimName = seg.dimension_value || seg.label || seg.key || 'Unknown';
                const val = seg.metric_value !== undefined && seg.metric_value !== null
                  ? seg.metric_value
                  : seg.value !== undefined && seg.value !== null
                  ? seg.value
                  : 0;
                const orders = seg.order_count ?? seg.count ?? 0;
                const share = seg.percentage_of_total ?? 0;
                return (
                  <div
                    key={idx}
                    onClick={() => onAskQuery(`Break down customer retention and order frequency for segment ${dimName}`)}
                    className="p-3.5 rounded-xl bg-void/60 border border-surface-elevated space-y-1.5 hover:border-cyan-500/30 hover:bg-surface-elevated/40 transition-all cursor-pointer group"
                    title="Click to analyze this customer segment in Ask NEXUS"
                  >
                    <div className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-1.5">
                        <span className="font-semibold text-slate-200 font-sans capitalize group-hover:text-cyan-300 transition-colors">{dimName}</span>
                        <ArrowUpRight className="w-3 h-3 text-slate-500 opacity-0 group-hover:opacity-100 group-hover:text-cyan-400 transition-all shrink-0" />
                      </div>
                      <span className="font-mono font-bold text-cyan-300">{formatCurrency(Number(val), true)}</span>
                    </div>
                    <div className="flex items-center justify-between text-[11px] font-sans text-slate-400">
                      <span>{formatNumber(orders)} orders</span>
                      <span className="font-mono">Share: {typeof share === 'number' ? share.toFixed(1) : share}%</span>
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="py-12 px-4 text-center rounded-xl bg-void/40 border border-dashed border-surface-elevated space-y-2">
                <Users className="w-8 h-8 text-slate-500 mx-auto" />
                <p className="text-xs font-semibold text-slate-300 font-sans">No Customer Segments Available</p>
                <p className="text-[11px] text-slate-400 max-w-sm mx-auto font-sans leading-relaxed">
                  Customer cohort segmentation requires customer records linked to sales orders.
                </p>
              </div>
            )}
          </div>
        </section>
      </div>

      {/* Evidence Modal */}
      {activeEvidence && (
        <EvidencePanel
          evidence={activeEvidence}
          isOpen={Boolean(activeEvidence)}
          onClose={() => setActiveEvidence(null)}
          asModal
        />
      )}
    </div>
  );
};
