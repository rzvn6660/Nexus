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
import { ErrorState } from '../components/common/ErrorState';
import { EvidencePanel } from '../components/common/EvidencePanel';
import { MetricStatement, MetricItem } from '../components/intelligence/MetricStatement';
import { SignalRow, SignalData } from '../components/intelligence/SignalRow';
import { NexusSymbol } from '../components/brand/NexusSymbol';
import { WorkflowPath } from '../components/intelligence/WorkflowPath';

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
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceRecord | null>(null);
  const [chartGranularity, setChartGranularity] = useState<'monthly' | 'weekly'>('monthly');

  const loadDashboardData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [sumRes, revRes, prodRes, catRes, invRes] = await Promise.all([
        getFinancialSummary(),
        getRevenueTimeSeries({ granularity: chartGranularity }),
        getProductRankings({ ranking_metric: 'revenue', limit: 5 }),
        getCategoryBreakdown({ metric: 'revenue' }),
        getInventoryOverview(),
      ]);

      setSummary(sumRes);
      setRevenueSeries(revRes);
      setTopProducts(prodRes);
      setCategoryBreakdown(catRes);
      setInventory(invRes);
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
      <div className="space-y-6">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <CardSkeleton />
          <CardSkeleton />
          <CardSkeleton />
        </div>
        <CardSkeleton rows={6} />
      </div>
    );
  }

  if (error && !summary) {
    return (
      <ErrorState
        title="Could not load overview analytics"
        message={error}
        onRetry={loadDashboardData}
      />
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
        <div className="rounded-3xl border border-surface-elevated bg-surface/40 p-8 sm:p-14 text-center max-w-2xl mx-auto space-y-6 my-12">
          <div className="w-16 h-16 rounded-2xl bg-cyan-950/40 border border-cyan-500/30 flex items-center justify-center mx-auto text-brand-cyan shadow-[0_0_30px_rgba(0,242,254,0.15)]">
            <Database className="w-8 h-8" />
          </div>
          <div className="space-y-2">
            <h2 className="text-2xl font-bold text-white font-sans">
              Your intelligence workspace is waiting for data.
            </h2>
            <p className="text-sm text-slate-400 max-w-md mx-auto leading-relaxed">
              Connect your transactional records via the NEXUS Data Gateway to begin receiving automated briefings, causal investigations, and statistical forecasts.
            </p>
          </div>
          <div className="pt-2">
            <button
              onClick={() => onNavigate('/data')}
              className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-gradient-to-r from-cyan-400 to-sky-400 hover:from-cyan-300 hover:to-sky-300 text-slate-950 font-semibold text-xs tracking-tight transition-all shadow-[0_0_20px_rgba(0,242,254,0.25)] cursor-pointer"
            >
              <span>Connect Data</span>
              <ArrowRight className="w-4 h-4" />
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

  const grossProfitPctChange =
    s?.gross_profit?.percentage_change ??
    s?.comparison?.gross_profit?.percentage_change;

  const grossMarginVal =
    s?.gross_margin?.value !== undefined && s?.gross_margin?.value !== null
      ? Number(s.gross_margin.value)
      : s?.gross_margin_pct !== undefined && s?.gross_margin_pct !== null
      ? Number(s.gross_margin_pct)
      : null;

  // Build executive business state metric items
  const businessMetrics: MetricItem[] = [
    {
      label: 'NET REVENUE',
      value: formatCurrency(netSalesMetric?.value, true),
      change: netSalesPctChange !== null && netSalesPctChange !== undefined
        ? `${netSalesPctChange >= 0 ? '+' : ''}${formatPercent(netSalesPctChange)}`
        : undefined,
      changeType: (netSalesPctChange ?? 0) >= 0 ? 'positive' : 'negative',
      annotation: `${formatNumber(ordersValue)} completed commercial orders`,
      onClick: () => onNavigate('/analytics'),
    },
    {
      label: 'GROSS MARGIN',
      value: grossMarginVal !== null ? `${grossMarginVal.toFixed(1)}%` : '—',
      change: grossProfitPctChange !== null && grossProfitPctChange !== undefined && grossMarginVal !== null
        ? `${grossProfitPctChange >= 0 ? '+' : ''}${formatPercent(grossProfitPctChange)} profit`
        : undefined,
      changeType: (grossProfitPctChange ?? 0) >= 0 ? 'positive' : 'negative',
      annotation: s?.gross_profit?.value !== null && s?.gross_profit?.value !== undefined
        ? `Gross Profit: ${formatCurrency(s.gross_profit.value, true)}`
        : 'Gross Profit: Incomplete (No product costs)',
      onClick: () => onAskQuery('Why did gross margin change?'),
    },
    {
      label: 'INVENTORY POSTURE',
      value: (invData?.out_of_stock_items_count ?? 0) === 0 ? 'Healthy' : 'Attention Required',
      changeType: (invData?.out_of_stock_items_count ?? 0) === 0 ? 'positive' : 'negative',
      annotation: `${invData?.low_stock_items_count ?? 0} low-stock exceptions identified`,
      onClick: () => onAskQuery('What is our inventory turnover ratio and stock health?'),
    },
  ];

  // Observed Briefing Signals ("What Changed")
  // Invariant: Remove/suppress margin signals that require unavailable COGS
  const signals: SignalData[] = [];

  if (grossMarginVal !== null && grossMarginVal !== undefined) {
    signals.push({
      id: 'signal-margin',
      category: 'Margin Variance',
      severity: grossMarginVal < 25 ? 'warning' : 'info',
      what: `Gross Margin registered at ${grossMarginVal.toFixed(1)}% with active volume expansion`,
      whyItMatters:
        'Net sales volume increased, but supplier costs and category mix shifts are modulating gross retention.',
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

  if (invData && (invData.total_skus ?? 0) > 0) {
    signals.push({
      id: 'signal-inventory',
      category: 'Stock Health',
      severity: (invData.low_stock_items_count ?? 0) > 0 ? 'warning' : 'positive',
      what: `${invData.low_stock_items_count ?? 0} SKUs flagged near minimum stock reorder threshold`,
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
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* 1. NEXUS INTELLIGENCE EXECUTIVE ANCHOR & EPISTEMIC HERO */}
      <section className="relative rounded-3xl p-6 sm:p-10 overflow-hidden bg-void-sub border border-surface-elevated shadow-2xl">
        {/* Authentic NEXUS Artwork directly integrated into dark canvas */}
        <div
          className="absolute top-0 right-0 w-full sm:w-1/2 lg:w-5/12 h-[320px] sm:h-[350px] lg:h-[380px] pointer-events-none select-none overflow-hidden flex items-start justify-end"
          aria-hidden="true"
        >
          <img
            src="/brand/nexus-logo-bg.png"
            alt=""
            className="w-48 h-48 sm:w-[280px] sm:h-[280px] lg:w-[350px] lg:h-[350px] object-contain opacity-15 sm:opacity-25 lg:opacity-35 select-none pointer-events-none -mr-6 sm:-mr-3 lg:mr-2 -mt-4 sm:-mt-2 lg:mt-1"
            style={{
              WebkitMaskImage: 'linear-gradient(to right, transparent 0%, rgba(0,0,0,0.5) 15%, black 35%)',
              maskImage: 'linear-gradient(to right, transparent 0%, rgba(0,0,0,0.5) 15%, black 35%)',
            }}
            draggable={false}
          />
        </div>

        <div className="relative z-10 space-y-8">
          {/* Top Brand & Mission Lockup */}
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="inline-flex items-center gap-2.5 px-3 py-1 rounded-full bg-cyan-950/80 border border-brand-cyan/40 text-brand-cyan text-xs font-mono font-medium">
                <NexusSymbol size={16} showBackdrop={false} />
                <span>NEXUS • AGENTIC BUSINESS INTELLIGENCE PLATFORM</span>
              </div>

              <div className="flex items-center gap-2 text-[11px] font-mono text-slate-400">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                <span>Deterministic Analytics Engine v1.0 • Online</span>
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-xs sm:text-sm font-mono tracking-widest text-slate-400 uppercase font-semibold">
                NEXUS
              </div>
              <h1 className="text-3xl sm:text-4xl lg:text-5xl font-extrabold text-white tracking-tight font-sans leading-tight">
                WHERE BUSINESS DATA<br className="hidden sm:inline" /> BECOMES INTELLIGENCE.
              </h1>
              <p className="text-base sm:text-lg font-medium text-slate-300 font-sans pt-1">
                Understand what happened. Investigate why. See what comes next. Decide with evidence.
              </p>
              <p className="text-xs sm:text-sm text-slate-400 max-w-3xl font-sans leading-relaxed">
                NEXUS synthesizes transactional business data, deterministic analytics, agentic investigation, 
                predictive forecasting, business context, and verifiable evidence into auditable decision support for analysts and executives.
              </p>
            </div>
          </div>

          {/* Epistemic Progression: DATA -> UNDERSTAND -> INVESTIGATE -> VALIDATE -> PREDICT -> EXPLAIN -> DECIDE */}
          <div className="pt-2 border-t border-surface-elevated/80">
            <WorkflowPath onNavigate={onNavigate} />
          </div>

          {/* Current Business State Information Field */}
          <div className="pt-2 border-t border-surface-elevated/80">
            <MetricStatement
              title="CURRENT BUSINESS STATE"
              metrics={businessMetrics}
            />
          </div>
        </div>
      </section>

      {/* 2. WHAT CHANGED (EXECUTIVE BRIEFING SIGNALS) */}
      <section className="space-y-4">
        <div className="flex items-center justify-between border-b border-surface-elevated pb-3">
          <div>
            <h2 className="text-base sm:text-lg font-bold text-white flex items-center gap-2 font-sans">
              <Activity className="w-4 h-4 text-brand-cyan" />
              <span>What Changed: Key Observed Signals</span>
            </h2>
            <p className="text-xs text-slate-400">
              Empirical variations identified across sales, margins, and catalog telemetry.
            </p>
          </div>

          <button
            onClick={() => onNavigate('/investigations')}
            className="text-xs font-mono text-brand-cyan hover:text-cyan-300 transition-colors flex items-center gap-1"
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
            <p className="text-xs text-slate-400 py-3 italic">
              No variance signals triggered for this period. Cost and margin signals will activate once product catalog and cost data are ingested.
            </p>
          )}
        </div>
      </section>

      {/* 3. COMMERCIAL TELEMETRY & CONTINUOUS INTELLIGENCE WORKFLOW */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left 2 Cols: Revenue Trajectory with Forward Workflow Triggers */}
        <section className="lg:col-span-2 rounded-3xl bg-surface/60 border border-surface-elevated p-6 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-surface-elevated pb-3">
            <div>
              <h3 className="text-base font-bold text-white font-sans flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-brand-cyan" />
                <span>Commercial Revenue Trajectory</span>
              </h3>
              <p className="text-xs text-slate-400">
                Deterministic net sales aggregated by period.
              </p>
            </div>

            {/* Continuous Workflow Forward Links */}
            <div className="flex items-center gap-2 text-xs font-mono">
              <button
                onClick={() => setChartGranularity(chartGranularity === 'monthly' ? 'weekly' : 'monthly')}
                className="px-2.5 py-1 rounded-lg bg-surface border border-surface-elevated text-slate-300 hover:text-white"
              >
                {chartGranularity === 'monthly' ? 'Monthly' : 'Weekly'}
              </button>

              <button
                onClick={() => onNavigate('/investigations')}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-cyan-950/70 border border-brand-cyan/40 text-brand-cyan hover:bg-cyan-900/60"
                title="Decompose revenue variance in diagnostic engine"
              >
                <SearchCode className="w-3 h-3" />
                <span>Investigate Why</span>
              </button>

              <button
                onClick={() => onNavigate('/forecasts')}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-surface-elevated border border-surface-highlight text-violet-300 hover:text-violet-200"
                title="Forecast future periods"
              >
                <TrendingUp className="w-3 h-3" />
                <span>Forecast Horizon</span>
              </button>
            </div>
          </div>

          <div className="h-64 sm:h-72 w-full pt-2">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
                <defs>
                  <linearGradient id="revGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#00F2FE" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#00F2FE" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                <XAxis dataKey="label" stroke="#64748b" fontSize={11} tickLine={false} axisLine={{ stroke: '#334155' }} />
                <YAxis
                  stroke="#64748b"
                  fontSize={11}
                  tickLine={false}
                  axisLine={{ stroke: '#334155' }}
                  tickFormatter={(v) => `${getGlobalCurrencySymbol()}${(v / 1000).toFixed(0)}K`}
                />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (active && payload && payload.length) {
                      return (
                        <div className="rounded-xl border border-surface-highlight bg-void-sub p-3 shadow-xl text-xs font-mono">
                          <p className="text-slate-400">{label}</p>
                          <p className="text-brand-cyan font-bold text-sm">
                            {formatCurrency(payload[0].value as number)}
                          </p>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Area type="monotone" dataKey="value" stroke="#00F2FE" strokeWidth={2} fill="url(#revGradient)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          <div className="flex items-center justify-between pt-2 border-t border-surface-elevated/60 text-xs font-mono text-slate-400">
            <span>Aggregated from verified transactional database records</span>
            <button
              onClick={() => setSelectedEvidence(revenueSeries?.evidence || null)}
              className="text-brand-cyan hover:underline inline-flex items-center gap-1"
            >
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>Inspect Calculation Lineage</span>
            </button>
          </div>
        </section>

        {/* Right Col: Category Contribution Breakdown & Product Highlights */}
        <section className="rounded-3xl bg-surface/60 border border-surface-elevated p-6 space-y-4 flex flex-col justify-between">
          <div className="space-y-1">
            <h3 className="text-base font-bold text-white font-sans flex items-center gap-2">
              <Layers className="w-4 h-4 text-emerald-400" />
              <span>Category Contribution</span>
            </h3>
            <p className="text-xs text-slate-400">
              Share of net sales across merchandise domains.
            </p>
          </div>

          <div className="space-y-3 my-auto">
            {categoryBreakdown?.data?.items?.slice(0, 4).map((cat, idx) => {
              const totalVal = categoryBreakdown.data.total_value || 1;
              const pct = cat.percentage_of_total !== undefined
                ? cat.percentage_of_total.toFixed(1)
                : ((cat.metric_value / totalVal) * 100).toFixed(1);

              return (
                <div key={idx} className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-slate-200 capitalize font-sans">{cat.dimension_value}</span>
                    <span className="font-mono text-slate-300">{formatCurrency(cat.metric_value, true)} ({pct}%)</span>
                  </div>
                  <div className="w-full h-1.5 rounded-full bg-void overflow-hidden">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-sky-400"
                      style={{ width: `${Math.min(100, Math.max(5, parseFloat(pct)))}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>

          {/* Top Product Highlight */}
          {topProducts?.data?.items && topProducts.data.items.length > 0 && (
            <div className="p-3 rounded-2xl bg-void/60 border border-surface-elevated space-y-1 text-xs">
              <div className="flex items-center gap-1.5 text-slate-400 text-[10px] font-mono uppercase">
                <Package className="w-3.5 h-3.5 text-brand-cyan" />
                <span>Top Performing SKU</span>
              </div>
              <div className="font-semibold text-white font-sans truncate">
                {topProducts.data.items[0].product_name}
              </div>
              <div className="font-mono text-[11px] text-brand-cyan">
                {formatCurrency(topProducts.data.items[0].metric_value, true)} ({formatNumber(topProducts.data.items[0].units_sold)} units)
              </div>
            </div>
          )}

          <div className="pt-3 border-t border-surface-elevated flex items-center justify-between text-xs">
            <span className="font-mono text-slate-400 text-[11px]">Ranked Deterministically</span>
            <button
              onClick={() => onNavigate('/analytics')}
              className="text-brand-cyan hover:underline flex items-center gap-1 font-mono text-[11px]"
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
