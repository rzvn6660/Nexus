import React, { useEffect, useState, useCallback } from 'react';
import {
  TrendingUp,
  SearchCode,
  ShieldCheck,
  ArrowRight,
  BarChart3,
  Layers,
  Activity,
  Package,
  Database,
  Sparkles,
  Radio,
  AlertTriangle,
  RefreshCw,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts';
import {
  getFinancialSummary,
  getRevenueTimeSeries,
  getProductRankings,
  getCategoryBreakdown,
  getInventoryOverview,
} from '../services/analytics';
import {
  SummaryResponse,
  TimeSeriesResponse,
  ProductRankingResponse,
  BreakdownResponse,
  InventoryOverviewResponse,
  EvidenceRecord,
} from '../types/api';
import {
  formatCurrency,
  formatNumber,
  formatPercent,
  getGlobalCurrencySymbol,
} from '../utils/formatters';
import { CardSkeleton } from '../components/common/LoadingState';
import { EvidencePanel } from '../components/common/EvidencePanel';
import { MetricStatement, MetricItem } from '../components/intelligence/MetricStatement';
import { SignalRow, SignalData } from '../components/intelligence/SignalRow';

interface OverviewPageProps {
  onNavigate: (route: string) => void;
  onAskQuery: (query: string) => void;
}

export const OverviewPage: React.FC<OverviewPageProps> = ({
  onNavigate,
  onAskQuery,
}) => {
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [revenueSeries, setRevenueSeries] = useState<TimeSeriesResponse | null>(null);
  const [topProducts, setTopProducts] = useState<ProductRankingResponse | null>(null);
  const [categoryBreakdown, setCategoryBreakdown] = useState<BreakdownResponse | null>(null);
  const [inventory, setInventory] = useState<InventoryOverviewResponse | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showErrorDetails, setShowErrorDetails] = useState(false);
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceRecord | null>(null);
  const [chartGranularity, setChartGranularity] = useState<'monthly' | 'weekly'>('monthly');

  const loadDashboardData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const results = await Promise.allSettled([
        getFinancialSummary(),
        getRevenueTimeSeries({ granularity: chartGranularity }),
        getProductRankings({ ranking_metric: 'revenue', limit: 5 }),
        getCategoryBreakdown({ metric: 'revenue' }),
        getInventoryOverview(),
      ]);

      const [sumRes, revRes, prodRes, catRes, invRes] = results;

      if (sumRes.status === 'fulfilled') {
        setSummary(sumRes.value);
      } else {
        setError(sumRes.reason?.message || 'Failed to load executive overview analytics.');
      }

      if (revRes.status === 'fulfilled') {
        setRevenueSeries(revRes.value);
      } else {
        setRevenueSeries(null);
      }

      if (prodRes.status === 'fulfilled') {
        setTopProducts(prodRes.value);
      } else {
        setTopProducts(null);
      }

      if (catRes.status === 'fulfilled') {
        setCategoryBreakdown(catRes.value);
      } else {
        setCategoryBreakdown(null);
      }

      if (invRes.status === 'fulfilled') {
        setInventory(invRes.value);
      } else {
        setInventory(null);
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load executive overview analytics.');
    } finally {
      setLoading(false);
    }
  }, [chartGranularity]);

  useEffect(() => {
    loadDashboardData();
  }, [loadDashboardData]);

  if (loading && !summary) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-24 rounded-2xl bg-surface/60 border border-surface-elevated" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <CardSkeleton rows={2} />
          <CardSkeleton rows={2} />
          <CardSkeleton rows={2} />
          <CardSkeleton rows={2} />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 h-80 rounded-2xl bg-surface/60 border border-surface-elevated" />
          <div className="h-80 rounded-2xl bg-surface/60 border border-surface-elevated" />
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
                Unable to Connect to Intelligence Engine
              </h2>
              <p className="text-xs sm:text-sm text-slate-300 font-sans leading-relaxed">
                {isConnectionError
                  ? 'The executive overview service could not retrieve transactional metrics from the backend database. This occurs when the transactional database service is offline or initial ledger ingestion has not completed.'
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
                Verify transactional CSV/XLSX ledgers or database schema ingestion status.
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
                Inspect deterministic formula schemas and semantic KPI calculation rules.
              </p>
            </button>
          </div>

          {/* Primary Action Row */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
            <button
              onClick={loadDashboardData}
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
  const invData = inventory?.data;

  // Resolve net sales and order counts safely from either net_sales/orders or net_revenue/orders_count
  const netSalesMetric = s?.net_sales || s?.net_revenue;
  const netSalesValue = Number(netSalesMetric?.value ?? 0);
  const ordersMetric = s?.orders || s?.orders_count;
  const ordersValue = Number(ordersMetric?.value ?? 0);

  // First-use empty workspace state: only empty if summary is missing or both orders and sales are 0
  const isWorkspaceEmpty = !summary || (ordersValue === 0 && netSalesValue === 0);
  if (isWorkspaceEmpty) {
    return (
      <div className="space-y-8 animate-in fade-in duration-200">
        <div className="rounded-3xl border border-surface-elevated bg-surface/60 p-8 sm:p-12 text-center max-w-2xl mx-auto space-y-6 my-8 shadow-obsidian">
          <div className="w-16 h-16 rounded-2xl bg-cyan-950/60 border border-cyan-500/30 flex items-center justify-center mx-auto text-cyan-400 shadow-cyan-subtle">
            <Database className="w-8 h-8" />
          </div>

          <div className="space-y-2">
            <h2 className="text-2xl font-bold text-white font-sans tracking-tight">
              Your Intelligence Workspace is Ready for Data
            </h2>
            <p className="text-sm text-slate-300 max-w-lg mx-auto leading-relaxed font-sans">
              Connect your transactional records to activate deterministic revenue telemetry, margin variance signals, and backtested predictive forecasts.
            </p>
          </div>

          {/* Supported Format Indicators */}
          <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
            <span className="text-[11px] font-mono text-slate-400 uppercase">Supported Ingestion:</span>
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

          {/* What Gets Activated Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-left pt-2 font-sans">
            <div className="p-3.5 rounded-xl bg-void/60 border border-surface-elevated/70 space-y-1">
              <span className="text-[10px] font-mono uppercase text-cyan-400 font-semibold block">01 / TELEMETRY</span>
              <p className="text-xs font-bold text-white">Headline KPIs & Margins</p>
              <p className="text-[11px] text-slate-400">Deterministic SQL net revenue, gross margins, and order volume.</p>
            </div>
            <div className="p-3.5 rounded-xl bg-void/60 border border-surface-elevated/70 space-y-1">
              <span className="text-[10px] font-mono uppercase text-emerald-400 font-semibold block">02 / DIAGNOSTICS</span>
              <p className="text-xs font-bold text-white">Automated Variance</p>
              <p className="text-[11px] text-slate-400">Root cause decomposition across category contribution and SKU mix.</p>
            </div>
            <div className="p-3.5 rounded-xl bg-void/60 border border-surface-elevated/70 space-y-1">
              <span className="text-[10px] font-mono uppercase text-violet-400 font-semibold block">03 / FORECASTING</span>
              <p className="text-xs font-bold text-white">Horizon Projections</p>
              <p className="text-[11px] text-slate-400">Backtested tournament time-series with prediction interval corridors.</p>
            </div>
          </div>

          {/* Call to Actions */}
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

  const netSalesPctChange =
    netSalesMetric?.percentage_change ??
    s?.comparison?.net_sales?.percentage_change ??
    s?.comparison?.net_revenue?.percentage_change;

  const ordersPctChange =
    ordersMetric?.percentage_change ??
    s?.comparison?.orders?.percentage_change ??
    s?.comparison?.orders_count?.percentage_change;

  const grossProfitPctChange =
    s?.gross_profit?.percentage_change ??
    s?.comparison?.gross_profit?.percentage_change;

  const marginPctChange =
    s?.gross_margin?.percentage_change ??
    s?.comparison?.gross_margin?.percentage_change ??
    s?.comparison?.gross_margin_pct?.percentage_change;

  const grossMarginVal =
    s?.gross_margin?.value !== undefined && s?.gross_margin?.value !== null
      ? Number(s.gross_margin.value)
      : s?.gross_margin_pct !== undefined && s?.gross_margin_pct !== null
      ? Number(s.gross_margin_pct)
      : null;

  const hasInventoryData = Boolean(invData && (invData.total_skus ?? 0) > 0);

  // Build executive business state metric items (Above the fold)
  const businessMetrics: MetricItem[] = [
    {
      label: 'NET REVENUE',
      value: formatCurrency(netSalesMetric?.value, true),
      change: netSalesPctChange !== null && netSalesPctChange !== undefined
        ? `${netSalesPctChange >= 0 ? '+' : ''}${formatPercent(netSalesPctChange)}`
        : undefined,
      changeType: (netSalesPctChange ?? 0) >= 0 ? 'positive' : 'negative',
      annotation: `${formatNumber(ordersValue)} completed orders`,
      onClick: () => onNavigate('/analytics'),
    },
    {
      label: 'GROSS MARGIN',
      value: grossMarginVal !== null ? `${grossMarginVal.toFixed(1)}%` : '—',
      change: marginPctChange !== null && marginPctChange !== undefined && grossMarginVal !== null
        ? `${marginPctChange >= 0 ? '+' : ''}${formatPercent(marginPctChange)}`
        : grossProfitPctChange !== null && grossProfitPctChange !== undefined && grossMarginVal !== null
        ? `${grossProfitPctChange >= 0 ? '+' : ''}${formatPercent(grossProfitPctChange)}`
        : undefined,
      changeType: (marginPctChange ?? grossProfitPctChange ?? 0) >= 0 ? 'positive' : 'negative',
      annotation: s?.gross_profit?.value !== null && s?.gross_profit?.value !== undefined
        ? `Profit: ${formatCurrency(s.gross_profit.value, true)}`
        : 'Incomplete cost data',
      onClick: () => onAskQuery('Why did gross margin change?'),
    },
    {
      label: 'COMMERCIAL ORDERS',
      value: formatNumber(ordersValue),
      change: ordersPctChange !== null && ordersPctChange !== undefined
        ? `${ordersPctChange >= 0 ? '+' : ''}${formatPercent(ordersPctChange)}`
        : undefined,
      changeType: (ordersPctChange ?? 0) >= 0 ? 'positive' : 'negative',
      annotation: s?.average_order_value?.value
        ? `AOV: ${formatCurrency(s.average_order_value.value, true)}`
        : 'Order volume',
      onClick: () => onNavigate('/analytics'),
    },
    {
      label: 'INVENTORY POSTURE',
      value: hasInventoryData
        ? ((invData?.out_of_stock_items_count ?? 0) === 0 ? 'Healthy' : 'Attention Required')
        : 'Not Ingested',
      changeType: hasInventoryData
        ? ((invData?.out_of_stock_items_count ?? 0) === 0 ? 'positive' : 'negative')
        : 'neutral',
      annotation: hasInventoryData
        ? `${invData?.low_stock_items_count ?? 0} low-stock SKUs flagged`
        : 'Connect inventory ledger',
      onClick: hasInventoryData
        ? () => onAskQuery('What is our inventory turnover ratio and stock health?')
        : () => onNavigate('/data'),
    },
  ];

  // Observed Briefing Signals ("What Changed") - strictly empirical, distinguished from AI speculation
  const signals: SignalData[] = [];

  if (grossMarginVal !== null && grossMarginVal !== undefined) {
    const isSalesExpanding = (netSalesPctChange ?? 0) >= 0;
    const volumeDesc = isSalesExpanding ? 'with sustained order volume' : 'amid volume contraction';

    signals.push({
      id: 'signal-margin',
      category: 'Margin Retention',
      severity: grossMarginVal < 25 ? 'warning' : 'positive',
      what: `Gross Margin registered at ${grossMarginVal.toFixed(1)}% ${volumeDesc}`,
      whyItMatters: isSalesExpanding
        ? 'Net sales volume expanded; monitor COGS and category mix shifts to maintain retention.'
        : 'Net sales volume contracted; evaluate pricing tiers and supplier cost structures to defend profit margins.',
      onInvestigate: () => onNavigate('/investigations'),
      onViewEvidence: () => setSelectedEvidence(summary?.evidence || null),
    });
  }

  if (categoryBreakdown?.data?.items?.length) {
    signals.push({
      id: 'signal-growth',
      category: 'Commercial Drivers',
      severity: 'positive',
      what: `Top category "${categoryBreakdown.data.items[0].dimension_value}" generated ${formatCurrency(categoryBreakdown.data.items[0].metric_value, true)}`,
      whyItMatters:
        'Category concentration accounts for a significant portion of quarterly volume; monitoring price elasticity is recommended.',
      onInvestigate: () => onNavigate('/investigations'),
      onViewEvidence: () => setSelectedEvidence(categoryBreakdown.evidence || null),
    });
  }

  if (hasInventoryData) {
    signals.push({
      id: 'signal-inventory',
      category: 'Stock Health',
      severity: (invData?.low_stock_items_count ?? 0) > 0 ? 'warning' : 'positive',
      what: `${invData?.low_stock_items_count ?? 0} SKUs flagged near minimum stock reorder threshold`,
      whyItMatters:
        'Prevents stockouts across fast-moving product tiers without committing excessive working capital.',
      onInvestigate: () => onAskQuery('Which products are at risk of stockout?'),
    });
  }

  const chartData = revenueSeries?.data?.points?.map((pt) => ({
    label: pt.period_label,
    value: pt.value,
  })) || [];

  return (
    <div className="space-y-6 sm:space-y-8 animate-in fade-in duration-200">
      {/* 1. COMPACT EXECUTIVE BRIEFING HEADER */}
      <section className="p-5 sm:p-6 rounded-2xl bg-surface/70 border border-surface-elevated shadow-obsidian flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="space-y-1 max-w-2xl">
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-500/30 text-[10px] font-sans font-semibold text-cyan-300">
              <Radio className="w-2.5 h-2.5 text-cyan-400 animate-pulse" />
              <span>EXECUTIVE BRIEFING</span>
            </span>
            <span className="text-[11px] text-slate-400 font-sans hidden sm:inline">
              • Deterministic Analytics Engine Online
            </span>
          </div>

          <h2 className="text-xl sm:text-2xl font-bold text-white font-sans tracking-tight">
            Commercial Performance & Variance Briefing
          </h2>

          <p className="text-xs text-slate-300 font-sans leading-relaxed">
            Real-time verified metrics, margin trajectory, and automated empirical variance signals.
          </p>
        </div>

        {/* Quick Action Triggers */}
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <button
            onClick={() => onNavigate('/investigations')}
            className="btn-secondary py-1.5 px-3 text-xs"
            title="Diagnose root causes in investigation engine"
          >
            <SearchCode className="w-3.5 h-3.5 text-cyan-400" />
            <span>Investigate</span>
          </button>

          <button
            onClick={() => onNavigate('/forecasts')}
            className="btn-secondary py-1.5 px-3 text-xs"
            title="Open predictive forecasting horizon"
          >
            <TrendingUp className="w-3.5 h-3.5 text-violet-400" />
            <span>Forecast</span>
          </button>

          <button
            onClick={() => onAskQuery('Provide an executive summary of our current commercial performance')}
            className="btn-primary py-1.5 px-3 text-xs shadow-cyan-subtle"
            title="Ask AI Intelligence Console"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>Ask NEXUS</span>
          </button>
        </div>
      </section>

      {/* 2. CORE BUSINESS KPIS (ABOVE THE FOLD) */}
      <section>
        <MetricStatement
          title="PRIMARY COMMERCIAL TELEMETRY"
          metrics={businessMetrics}
        />
      </section>

      {/* 3. VERIFIED VARIANCE SIGNALS (WHAT CHANGED) */}
      <section className="space-y-3">
        <div className="flex items-center justify-between border-b border-surface-elevated/80 pb-2.5">
          <div className="flex items-center gap-2">
            <h3 className="text-sm sm:text-base font-bold text-white font-sans flex items-center gap-2">
              <Activity className="w-4 h-4 text-cyan-400" />
              <span>Observed Variance Signals</span>
            </h3>
            <span className="px-2 py-0.5 rounded-full bg-surface-elevated text-slate-300 text-[10px] font-mono">
              {signals.length} Active
            </span>
          </div>

          <button
            onClick={() => onNavigate('/investigations')}
            className="text-xs text-cyan-400 hover:text-cyan-300 transition-colors flex items-center gap-1 font-sans font-medium"
          >
            <span>Run Custom Diagnostic</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>

        <div className="space-y-3">
          {signals.length > 0 ? (
            signals.map((sig) => (
              <SignalRow key={sig.id} signal={sig} />
            ))
          ) : (
            <div className="p-4 rounded-xl bg-surface/50 border border-surface-elevated text-xs text-slate-400 font-sans italic">
              No empirical variance alerts triggered for this period. Signals automatically activate upon catalog cost changes or unusual transaction variance.
            </div>
          )}
        </div>
      </section>

      {/* 4. COMMERCIAL REVENUE TRAJECTORY & CATEGORY DISTRIBUTION */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left 2 Cols: Revenue Trajectory */}
        <section className="lg:col-span-2 rounded-2xl bg-surface/70 border border-surface-elevated p-5 sm:p-6 space-y-4 shadow-obsidian">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-surface-elevated/80 pb-3">
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold text-white font-sans flex items-center gap-2">
                  <BarChart3 className="w-4 h-4 text-cyan-400" />
                  <span>Commercial Revenue Trajectory</span>
                </h3>
                <span className="px-2 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-500/30 text-[10px] font-mono text-cyan-300 uppercase">
                  Verified Data
                </span>
              </div>
              <p className="text-xs text-slate-400 font-sans mt-0.5">
                Deterministic net sales aggregated chronologically from transaction records.
              </p>
            </div>

            {/* Granularity & Forward Links */}
            <div className="flex items-center gap-2 text-xs">
              <button
                onClick={() => setChartGranularity(chartGranularity === 'monthly' ? 'weekly' : 'monthly')}
                className="btn-secondary py-1 px-2.5 text-xs font-mono"
              >
                {chartGranularity === 'monthly' ? 'Monthly View' : 'Weekly View'}
              </button>

              <button
                onClick={() => onNavigate('/investigations')}
                className="inline-flex items-center gap-1 py-1 px-2.5 rounded-lg bg-cyan-950/70 border border-cyan-500/30 text-cyan-300 hover:text-white text-xs font-medium transition-colors"
                title="Decompose revenue variance in diagnostic engine"
              >
                <SearchCode className="w-3 h-3" />
                <span>Investigate</span>
              </button>
            </div>
          </div>

          <div className="h-64 sm:h-72 w-full pt-2">
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
                  <defs>
                    <linearGradient id="revGradientObsidian" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#06B6D4" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#06B6D4" stopOpacity={0.0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1E293B" vertical={false} />
                  <XAxis dataKey="label" stroke="#64748B" fontSize={11} tickLine={false} axisLine={{ stroke: '#334155' }} />
                  <YAxis
                    stroke="#64748B"
                    fontSize={11}
                    tickLine={false}
                    axisLine={{ stroke: '#334155' }}
                    tickFormatter={(v) => `${getGlobalCurrencySymbol()}${(v / 1000).toFixed(0)}K`}
                  />
                  <Tooltip
                    content={({ active, payload, label }) => {
                      if (active && payload && payload.length) {
                        return (
                          <div className="rounded-xl border border-surface-highlight bg-void-sub p-3 shadow-obsidian text-xs font-sans">
                            <p className="text-slate-400 font-medium">{label}</p>
                            <p className="text-cyan-400 font-bold text-sm mt-0.5 font-mono">
                              {formatCurrency(payload[0].value as number)}
                            </p>
                            <span className="text-[10px] text-slate-500 block mt-1">Verified Transactional Net Sales</span>
                          </div>
                        );
                      }
                      return null;
                    }}
                  />
                  <Area type="monotone" dataKey="value" stroke="#06B6D4" strokeWidth={2.5} fill="url(#revGradientObsidian)" />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full w-full flex flex-col items-center justify-center text-center p-6 rounded-xl bg-void/40 border border-surface-elevated/60 text-slate-400">
                <BarChart3 className="w-8 h-8 text-slate-600 mb-2" />
                <p className="text-xs font-medium text-slate-300 font-sans">No chronological data points available</p>
                <p className="text-[11px] text-slate-500 font-sans mt-1">
                  Adjust granularity or ensure timestamp fields are mapped in ingested transactions.
                </p>
              </div>
            )}
          </div>

          <div className="flex items-center justify-between pt-3 border-t border-surface-elevated/70 text-xs text-slate-400 font-sans">
            <span>Aggregated from verified transactional database records</span>
            <button
              onClick={() => setSelectedEvidence(revenueSeries?.evidence || null)}
              className="text-cyan-400 hover:text-cyan-300 hover:underline inline-flex items-center gap-1.5 font-medium"
            >
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>Inspect Calculation Lineage</span>
            </button>
          </div>
        </section>

        {/* Right Col: Category Contribution Breakdown & Product Highlights */}
        <section className="rounded-2xl bg-surface/70 border border-surface-elevated p-5 sm:p-6 space-y-4 shadow-obsidian flex flex-col justify-between">
          <div className="space-y-1">
            <h3 className="text-base font-bold text-white font-sans flex items-center gap-2">
              <Layers className="w-4 h-4 text-emerald-400" />
              <span>Category Contribution</span>
            </h3>
            <p className="text-xs text-slate-400 font-sans">
              Share of net sales across merchandise domains.
            </p>
          </div>

          <div className="space-y-3 my-auto">
            {categoryBreakdown?.data?.items && categoryBreakdown.data.items.length > 0 ? (
              categoryBreakdown.data.items.slice(0, 4).map((cat, idx) => {
                const totalVal = categoryBreakdown.data.total_value || 1;
                const pct = cat.percentage_of_total !== undefined
                  ? cat.percentage_of_total.toFixed(1)
                  : ((cat.metric_value / totalVal) * 100).toFixed(1);

                return (
                  <div key={idx} className="space-y-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-semibold text-slate-200 capitalize font-sans">{cat.dimension_value}</span>
                      <span className="font-mono text-slate-300 font-medium">{formatCurrency(cat.metric_value, true)} ({pct}%)</span>
                    </div>
                    <div className="w-full h-1.5 rounded-full bg-void overflow-hidden">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-sky-400"
                        style={{ width: `${Math.min(100, Math.max(5, parseFloat(pct)))}%` }}
                      />
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="p-4 rounded-xl bg-void/40 border border-surface-elevated/60 text-center text-slate-400 text-xs font-sans">
                No category breakdown recorded for this dataset.
              </div>
            )}
          </div>

          {/* Top Product Highlight */}
          {topProducts?.data?.items && topProducts.data.items.length > 0 && (
            <div className="p-3.5 rounded-xl bg-void/60 border border-surface-elevated space-y-1 text-xs">
              <div className="flex items-center gap-1.5 text-slate-400 text-[10px] uppercase font-sans font-semibold">
                <Package className="w-3.5 h-3.5 text-cyan-400" />
                <span>Top Performing SKU</span>
              </div>
              <div className="font-semibold text-white font-sans truncate">
                {topProducts.data.items[0].product_name}
              </div>
              <div className="font-mono text-[11px] text-cyan-300">
                {formatCurrency(topProducts.data.items[0].metric_value, true)} ({formatNumber(topProducts.data.items[0].units_sold)} units)
              </div>
            </div>
          )}

          <div className="pt-3 border-t border-surface-elevated/70 flex items-center justify-between text-xs">
            <span className="text-slate-400 text-[11px] font-sans">Ranked Deterministically</span>
            <button
              onClick={() => onNavigate('/analytics')}
              className="text-cyan-400 hover:text-cyan-300 hover:underline flex items-center gap-1 font-sans text-xs font-medium"
            >
              <span>Full Analytics Table</span>
              <ArrowRight className="w-3 h-3" />
            </button>
          </div>
        </section>
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
