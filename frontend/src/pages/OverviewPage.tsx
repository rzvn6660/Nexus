import React, { useEffect, useState, useCallback } from 'react';
import {
  TrendingUp,
  TrendingDown,
  DollarSign,
  ShoppingCart,
  Users,
  Package,
  Layers,
  SearchCode,
  ArrowUpRight,
  ShieldCheck,
  AlertTriangle,
  Sparkles,
} from 'lucide-react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  BarChart,
  Bar,
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
} from '../utils/formatters';
import { CardSkeleton } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EvidencePanel } from '../components/common/EvidencePanel';

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
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <CardSkeleton />
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

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* 1. Header Banner & Executive Signals */}
      <section className="relative rounded-3xl p-6 sm:p-8 overflow-hidden bg-slate-900/80 border border-slate-800 shadow-xl">
        <div className="absolute top-0 right-0 -mr-16 -mt-16 w-64 h-64 rounded-full bg-cyan-500/10 blur-3xl pointer-events-none" />
        <div className="relative z-10 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-950/80 border border-cyan-800/80 text-cyan-400 text-xs font-mono font-medium mb-1">
              <Sparkles className="w-3.5 h-3.5" />
              <span>Commercial Telemetry • Live Analytics</span>
            </div>
            <h2 className="text-2xl sm:text-3xl font-bold text-white tracking-tight">
              Executive Business Overview
            </h2>
            <p className="text-xs sm:text-sm text-slate-400">
              Deterministic calculations derived from completed enterprise sales orders.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <button
              onClick={() => setSelectedEvidence(summary?.evidence || null)}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-medium transition-all"
            >
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              <span>Inspect Calculation Evidence</span>
            </button>

            <button
              onClick={() => onNavigate('/investigations')}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold shadow-md shadow-cyan-600/25 transition-all"
            >
              <SearchCode className="w-4 h-4" />
              <span>Launch Diagnostic Investigation</span>
            </button>
          </div>
        </div>
      </section>

      {/* 2. Top-Level KPI Grid (5 Core Business Metrics) */}
      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        {/* Net Revenue */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 space-y-3 relative group hover:border-slate-700 transition-all">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Net Revenue</span>
            <div className="p-2 rounded-xl bg-cyan-950/60 border border-cyan-800/40 text-cyan-400">
              <DollarSign className="w-4 h-4" />
            </div>
          </div>
          <div>
            <div className="text-2xl font-bold font-mono text-white">
              {formatCurrency(s?.net_revenue?.value, true)}
            </div>
            <div className="flex items-center gap-1.5 text-xs mt-1">
              {s?.net_revenue?.percentage_change !== null && s?.net_revenue?.percentage_change !== undefined ? (
                <>
                  {s.net_revenue.percentage_change >= 0 ? (
                    <span className="text-emerald-400 font-semibold flex items-center">
                      <TrendingUp className="w-3.5 h-3.5 mr-0.5" />
                      {formatPercent(s.net_revenue.percentage_change)}
                    </span>
                  ) : (
                    <span className="text-rose-400 font-semibold flex items-center">
                      <TrendingDown className="w-3.5 h-3.5 mr-0.5" />
                      {formatPercent(s.net_revenue.percentage_change)}
                    </span>
                  )}
                  <span className="text-slate-400 text-[11px]">vs prev period</span>
                </>
              ) : (
                <span className="text-slate-400 text-[11px]">Baseline period</span>
              )}
            </div>
          </div>
        </div>

        {/* Gross Profit & Margin */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 space-y-3 relative group hover:border-slate-700 transition-all">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Gross Profit</span>
            <div className="p-2 rounded-xl bg-emerald-950/60 border border-emerald-800/40 text-emerald-400">
              <TrendingUp className="w-4 h-4" />
            </div>
          </div>
          <div>
            <div className="text-2xl font-bold font-mono text-white">
              {formatCurrency(s?.gross_profit?.value, true)}
            </div>
            <div className="flex items-center gap-2 text-xs mt-1">
              <span className="px-1.5 py-0.5 rounded bg-emerald-950/80 border border-emerald-800/80 text-emerald-300 font-mono text-[11px]">
                {s?.gross_margin_pct ? `${s.gross_margin_pct.toFixed(1)}% Margin` : '—'}
              </span>
            </div>
          </div>
        </div>

        {/* Total Orders */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 space-y-3 relative group hover:border-slate-700 transition-all">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Total Orders</span>
            <div className="p-2 rounded-xl bg-violet-950/60 border border-violet-800/40 text-violet-400">
              <ShoppingCart className="w-4 h-4" />
            </div>
          </div>
          <div>
            <div className="text-2xl font-bold font-mono text-white">
              {formatNumber(s?.orders_count?.value)}
            </div>
            <div className="flex items-center gap-1.5 text-xs mt-1 text-slate-400">
              <span>{formatNumber(s?.units_sold?.value)} units sold</span>
            </div>
          </div>
        </div>

        {/* Average Order Value (AOV) */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 space-y-3 relative group hover:border-slate-700 transition-all">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Avg Order Value</span>
            <div className="p-2 rounded-xl bg-amber-950/60 border border-amber-800/40 text-amber-400">
              <ArrowUpRight className="w-4 h-4" />
            </div>
          </div>
          <div>
            <div className="text-2xl font-bold font-mono text-white">
              {formatCurrency(s?.average_order_value?.value)}
            </div>
            <div className="flex items-center gap-1.5 text-xs mt-1 text-slate-400">
              <span>Per customer basket</span>
            </div>
          </div>
        </div>

        {/* Active Customers */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 space-y-3 relative group hover:border-slate-700 transition-all">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Customers</span>
            <div className="p-2 rounded-xl bg-sky-950/60 border border-sky-800/40 text-sky-400">
              <Users className="w-4 h-4" />
            </div>
          </div>
          <div>
            <div className="text-2xl font-bold font-mono text-white">
              {formatNumber(s?.customers_count?.value)}
            </div>
            <div className="flex items-center gap-1.5 text-xs mt-1 text-slate-400">
              <span>Active buyers</span>
            </div>
          </div>
        </div>
      </section>

      {/* 3. Interactive Revenue Trend Chart */}
      <section className="rounded-3xl border border-slate-800 bg-slate-900/70 p-6 space-y-4">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-800 pb-4">
          <div>
            <h3 className="text-base font-semibold text-white flex items-center gap-2">
              <DollarSign className="w-4 h-4 text-cyan-400" />
              <span>Revenue Trend Over Time</span>
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Historical commercial performance with verified period aggregation.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <div className="inline-flex rounded-lg bg-slate-950 border border-slate-800 p-0.5 text-xs font-mono">
              <button
                onClick={() => setChartGranularity('monthly')}
                className={`px-3 py-1 rounded-md transition-all ${
                  chartGranularity === 'monthly'
                    ? 'bg-cyan-600 text-white font-medium shadow-sm'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Monthly
              </button>
              <button
                onClick={() => setChartGranularity('weekly')}
                className={`px-3 py-1 rounded-md transition-all ${
                  chartGranularity === 'weekly'
                    ? 'bg-cyan-600 text-white font-medium shadow-sm'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Weekly
              </button>
            </div>

            <button
              onClick={() => onNavigate('/forecasts')}
              className="inline-flex items-center gap-1 px-3 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 text-xs font-medium transition-all"
            >
              <span>Forecast</span>
              <ArrowUpRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Recharts Area Chart */}
        <div className="h-72 w-full pt-2">
          {revenueSeries?.data?.points && revenueSeries.data.points.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={revenueSeries.data.points}
                margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="revenueGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#0284c7" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#0284c7" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                <XAxis
                  dataKey="period_label"
                  stroke="#64748b"
                  fontSize={11}
                  tickLine={false}
                  axisLine={{ stroke: '#334155' }}
                />
                <YAxis
                  stroke="#64748b"
                  fontSize={11}
                  tickLine={false}
                  axisLine={{ stroke: '#334155' }}
                  tickFormatter={(val) => `₹${(val / 1000).toFixed(0)}K`}
                />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (active && payload && payload.length) {
                      const dataPoint = payload[0].payload;
                      return (
                        <div className="rounded-xl border border-slate-700 bg-slate-900 p-3 shadow-xl text-xs space-y-1">
                          <p className="font-semibold text-slate-200">{label}</p>
                          <p className="font-mono text-cyan-400 font-bold">
                            Revenue: {formatCurrency(dataPoint.value)}
                          </p>
                          {dataPoint.growth_rate !== null && dataPoint.growth_rate !== undefined && (
                            <p className="text-[11px] text-slate-400">
                              Growth: {formatPercent(dataPoint.growth_rate)}
                            </p>
                          )}
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke="#38bdf8"
                  strokeWidth={2.5}
                  fillOpacity={1}
                  fill="url(#revenueGradient)"
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-full flex items-center justify-center text-xs text-slate-400">
              No revenue time series data recorded for the selected frequency.
            </div>
          )}
        </div>
      </section>

      {/* 4. Performance Breakdown & Top Products Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Category Contribution Breakdown */}
        <section className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div>
              <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                <Layers className="w-4 h-4 text-cyan-400" />
                <span>Revenue by Category</span>
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">Contribution across merchandising groups</p>
            </div>
            <button
              onClick={() => onNavigate('/analytics')}
              className="text-xs text-cyan-400 hover:text-cyan-300 font-medium"
            >
              View All
            </button>
          </div>

          <div className="h-56 w-full">
            {categoryBreakdown?.data?.items && categoryBreakdown.data.items.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={categoryBreakdown.data.items.slice(0, 5)}
                  layout="vertical"
                  margin={{ top: 5, right: 20, left: 40, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                  <XAxis
                    type="number"
                    stroke="#64748b"
                    fontSize={10}
                    tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}K`}
                  />
                  <YAxis
                    type="category"
                    dataKey="dimension_value"
                    stroke="#94a3b8"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip
                    content={({ active, payload }) => {
                      if (active && payload && payload.length) {
                        const item = payload[0].payload;
                        return (
                          <div className="rounded-xl border border-slate-700 bg-slate-900 p-2.5 shadow-xl text-xs space-y-0.5">
                            <p className="font-semibold text-slate-200">{item.dimension_value}</p>
                            <p className="font-mono text-cyan-400">{formatCurrency(item.metric_value)}</p>
                            <p className="text-[11px] text-slate-400">
                              Share: {item.percentage_of_total?.toFixed(1)}%
                            </p>
                          </div>
                        );
                      }
                      return null;
                    }}
                  />
                  <Bar dataKey="metric_value" fill="#0284c7" radius={[0, 6, 6, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-xs text-slate-400">
                No category data available.
              </div>
            )}
          </div>
        </section>

        {/* Top Performing Products Leaderboard */}
        <section className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div>
              <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                <Package className="w-4 h-4 text-emerald-400" />
                <span>Top Revenue Products</span>
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">Ranked by gross sales volume</p>
            </div>
            <button
              onClick={() => onNavigate('/analytics')}
              className="text-xs text-cyan-400 hover:text-cyan-300 font-medium"
            >
              View Rankings
            </button>
          </div>

          <div className="space-y-2.5">
            {topProducts?.data?.items?.slice(0, 4).map((p) => (
              <div
                key={p.product_id}
                className="flex items-center justify-between p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 text-xs hover:border-slate-700 transition-colors"
              >
                <div className="min-w-0 pr-2">
                  <div className="flex items-center gap-2">
                    <span className="w-5 h-5 rounded-full bg-slate-800 text-slate-300 font-mono font-bold text-[11px] flex items-center justify-center shrink-0">
                      {p.rank}
                    </span>
                    <span className="font-semibold text-slate-200 truncate">{p.product_name}</span>
                  </div>
                  <span className="text-[11px] font-mono text-slate-400 ml-7 block truncate">
                    SKU: {p.sku} • {p.category}
                  </span>
                </div>

                <div className="text-right shrink-0">
                  <span className="font-mono font-semibold text-white block">
                    {formatCurrency(p.revenue, true)}
                  </span>
                  <span className="text-[11px] font-mono text-emerald-400">
                    {p.margin_pct ? `${p.margin_pct.toFixed(1)}% margin` : ''}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* 5. Inventory Summary & Business Signals */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Inventory Summary Card */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
              <Package className="w-4 h-4 text-cyan-400" />
              Inventory Health
            </span>
            <span className="px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 text-[10px] font-mono">
              {inventory?.data?.total_skus ?? 0} SKUs
            </span>
          </div>

          <div className="space-y-2 pt-1">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-400">Total Stock Value:</span>
              <span className="font-mono font-semibold text-slate-200">
                {formatCurrency(inventory?.data?.total_inventory_value, true)}
              </span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-400">Low Stock SKUs:</span>
              <span className="font-mono font-semibold text-amber-400">
                {inventory?.data?.low_stock_items_count ?? 0}
              </span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-400">Out of Stock:</span>
              <span className="font-mono font-semibold text-rose-400">
                {inventory?.data?.out_of_stock_items_count ?? 0}
              </span>
            </div>
          </div>
        </div>

        {/* Business Intelligence Signals */}
        <div className="md:col-span-2 rounded-2xl border border-slate-800 bg-slate-900/60 p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
              <AlertTriangle className="w-4 h-4 text-amber-400" />
              Observed Analytical Signals
            </span>
            <span className="text-[11px] font-mono text-slate-400">Verified Findings</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
            <div
              onClick={() => onAskQuery('Why did revenue change in recent periods?')}
              className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 hover:border-cyan-500/50 cursor-pointer transition-colors space-y-1"
            >
              <div className="flex items-center justify-between text-cyan-400 font-medium">
                <span>Revenue Variance</span>
                <ArrowUpRight className="w-3.5 h-3.5" />
              </div>
              <p className="text-slate-400 text-[11px] leading-relaxed">
                Investigate category and product drivers explaining recent revenue movements.
              </p>
            </div>

            <div
              onClick={() => onAskQuery('Forecast revenue for the next 3 months')}
              className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 hover:border-cyan-500/50 cursor-pointer transition-colors space-y-1"
            >
              <div className="flex items-center justify-between text-cyan-400 font-medium">
                <span>Forward Projections</span>
                <ArrowUpRight className="w-3.5 h-3.5" />
              </div>
              <p className="text-slate-400 text-[11px] leading-relaxed">
                Generate backtested time-series forecast with statistical prediction intervals.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 6. Evidence Modal Drawer */}
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
