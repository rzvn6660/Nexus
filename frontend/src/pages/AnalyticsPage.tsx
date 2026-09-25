import React, { useState, useEffect, useCallback } from 'react';
import {
  BarChart3,
  DollarSign,
  Package,
  Layers,
  Users,
  ShieldCheck,
  SearchCode,
  ArrowUpRight,
  Sparkles,
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
  getCategoryBreakdown,
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
} from '../utils/formatters';
import { CardSkeleton } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
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
  const [granularity, setGranularity] = useState<'monthly' | 'weekly' | 'daily'>('monthly');

  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [timeSeries, setTimeSeries] = useState<TimeSeriesResponse | null>(null);
  const [products, setProducts] = useState<ProductRankingResponse | null>(null);
  const [categories, setCategories] = useState<BreakdownResponse | null>(null);
  const [customerSegments, setCustomerSegments] = useState<BreakdownResponse | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeEvidence, setActiveEvidence] = useState<EvidenceRecord | null>(null);

  const fetchAnalytics = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [sumRes, prodRes, catRes, custRes] = await Promise.all([
        getFinancialSummary({ granularity }),
        getProductRankings({ ranking_metric: selectedMetric, limit: 10 }),
        getCategoryBreakdown({ metric: selectedMetric }),
        getCustomerSegments(),
      ]);

      let tsRes: TimeSeriesResponse;
      if (selectedMetric === 'profit') {
        tsRes = await getProfitTimeSeries({ granularity });
      } else if (selectedMetric === 'units') {
        tsRes = await getSalesTimeSeries({ granularity });
      } else {
        tsRes = await getRevenueTimeSeries({ granularity });
      }

      setSummary(sumRes);
      setTimeSeries(tsRes);
      setProducts(prodRes);
      setCategories(catRes);
      setCustomerSegments(custRes);
    } catch (err: any) {
      setError(err?.message || 'Failed to fetch deterministic analytics telemetry.');
    } finally {
      setLoading(false);
    }
  }, [selectedMetric, granularity]);

  useEffect(() => {
    fetchAnalytics();
  }, [fetchAnalytics]);

  const s = summary?.data;

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* Header & Controls Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <h2 className="text-xl sm:text-2xl font-bold text-white flex items-center gap-2">
            <BarChart3 className="w-6 h-6 text-cyan-400" />
            <span>Deterministic Business Analytics</span>
          </h2>
          <p className="text-xs sm:text-sm text-slate-400 mt-0.5">
            Audit-grade calculations verified by formal statistical and financial definitions.
          </p>
        </div>

        {/* Filter controls */}
        <div className="flex flex-wrap items-center gap-2 sm:gap-3">
          {/* Metric Selector */}
          <div className="inline-flex rounded-xl bg-slate-900 border border-slate-800 p-1 text-xs font-mono">
            <button
              onClick={() => setSelectedMetric('revenue')}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                selectedMetric === 'revenue'
                  ? 'bg-cyan-600 text-white font-medium shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Revenue
            </button>
            <button
              onClick={() => setSelectedMetric('profit')}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                selectedMetric === 'profit'
                  ? 'bg-cyan-600 text-white font-medium shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Profit
            </button>
            <button
              onClick={() => setSelectedMetric('units')}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                selectedMetric === 'units'
                  ? 'bg-cyan-600 text-white font-medium shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Units
            </button>
          </div>

          {/* Granularity Selector */}
          <div className="inline-flex rounded-xl bg-slate-900 border border-slate-800 p-1 text-xs font-mono">
            <button
              onClick={() => setGranularity('monthly')}
              className={`px-2.5 py-1.5 rounded-lg transition-all ${
                granularity === 'monthly'
                  ? 'bg-slate-800 text-cyan-300 font-semibold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Monthly
            </button>
            <button
              onClick={() => setGranularity('weekly')}
              className={`px-2.5 py-1.5 rounded-lg transition-all ${
                granularity === 'weekly'
                  ? 'bg-slate-800 text-cyan-300 font-semibold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Weekly
            </button>
          </div>

          {/* Evidence Inspector Button */}
          {summary?.evidence && (
            <button
              onClick={() => setActiveEvidence(summary.evidence)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-medium transition-all"
            >
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              <span>Evidence</span>
            </button>
          )}
        </div>
      </div>

      {loading && !summary && <CardSkeleton rows={6} />}
      {error && !summary && <ErrorState message={error} onRetry={fetchAnalytics} />}

      {/* Main Dynamic Time Series Chart */}
      <section className="rounded-3xl border border-slate-800 bg-slate-900/70 p-6 space-y-4">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div>
            <h3 className="text-base font-semibold text-white capitalize">
              {selectedMetric} Telemetry ({granularity})
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Verified metric points computed across completed retail ledger transactions.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => onNavigate('/investigations')}
              className="inline-flex items-center gap-1 px-3 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-cyan-400 border border-slate-700 text-xs font-medium"
            >
              <SearchCode className="w-3.5 h-3.5" />
              <span>Investigate Drivers</span>
            </button>
            <button
              onClick={() => onNavigate('/forecasts')}
              className="inline-flex items-center gap-1 px-3 py-1 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-medium"
            >
              <span>Forecast Trend</span>
              <ArrowUpRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <div className="h-72 w-full pt-2">
          {timeSeries?.data?.points && timeSeries.data.points.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={timeSeries.data.points}
                margin={{ top: 10, right: 20, left: 10, bottom: 0 }}
              >
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
                  tickFormatter={(val) =>
                    selectedMetric === 'units'
                      ? formatNumber(val)
                      : `₹${(val / 1000).toFixed(0)}K`
                  }
                />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (active && payload && payload.length) {
                      const pt = payload[0].payload;
                      return (
                        <div className="rounded-xl border border-slate-700 bg-slate-900 p-3 shadow-xl text-xs space-y-1">
                          <p className="font-semibold text-slate-200">{label}</p>
                          <p className="font-mono text-cyan-400 font-bold">
                            {selectedMetric.toUpperCase()}:{' '}
                            {selectedMetric === 'units'
                              ? formatNumber(pt.value)
                              : formatCurrency(pt.value)}
                          </p>
                          {pt.growth_rate !== null && pt.growth_rate !== undefined && (
                            <p className="text-[11px] text-slate-400">
                              Period Growth: {formatPercent(pt.growth_rate)}
                            </p>
                          )}
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="#0284c7"
                  strokeWidth={2.5}
                  dot={{ r: 3, fill: '#38bdf8' }}
                  activeDot={{ r: 5 }}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-full flex items-center justify-center text-xs text-slate-400">
              No time series data available for the chosen parameters.
            </div>
          )}
        </div>
      </section>

      {/* Financial Statement Summary (12 Canonical Business Metrics) */}
      <section className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div>
            <h3 className="text-base font-semibold text-white flex items-center gap-2">
              <DollarSign className="w-5 h-5 text-cyan-400" />
              <span>Full Financial Performance Statement</span>
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              12 reconciled canonical metrics computed with deterministic SQL ledger aggregations.
            </p>
          </div>
          <button
            onClick={() => setActiveEvidence(summary?.evidence || null)}
            className="text-xs text-cyan-400 hover:text-cyan-300 font-medium font-mono"
          >
            Audit Formula
          </button>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 text-xs">
          <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800/80">
            <span className="text-slate-400 block text-[11px]">Gross Revenue</span>
            <span className="font-mono font-semibold text-white text-base block mt-1">
              {formatCurrency(s?.gross_revenue?.value)}
            </span>
          </div>
          <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800/80">
            <span className="text-slate-400 block text-[11px]">Discounts Applied</span>
            <span className="font-mono font-semibold text-amber-400 text-base block mt-1">
              {formatCurrency(s?.discounts?.value)}
            </span>
          </div>
          <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800/80">
            <span className="text-slate-400 block text-[11px]">Returns & Refunds</span>
            <span className="font-mono font-semibold text-rose-400 text-base block mt-1">
              {formatCurrency(s?.returns?.value)}
            </span>
          </div>
          <div className="p-3.5 rounded-xl bg-cyan-950/20 border border-cyan-800/40">
            <span className="text-cyan-300 block text-[11px]">Net Revenue</span>
            <span className="font-mono font-bold text-cyan-400 text-base block mt-1">
              {formatCurrency(s?.net_revenue?.value)}
            </span>
          </div>
          <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800/80">
            <span className="text-slate-400 block text-[11px]">Cost of Goods Sold (COGS)</span>
            <span className="font-mono font-semibold text-slate-300 text-base block mt-1">
              {formatCurrency(s?.cogs?.value)}
            </span>
          </div>
          <div className="p-3.5 rounded-xl bg-emerald-950/20 border border-emerald-800/40">
            <span className="text-emerald-300 block text-[11px]">Gross Profit</span>
            <span className="font-mono font-bold text-emerald-400 text-base block mt-1">
              {formatCurrency(s?.gross_profit?.value)}
            </span>
          </div>
          <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800/80">
            <span className="text-slate-400 block text-[11px]">Gross Margin</span>
            <span className="font-mono font-semibold text-emerald-400 text-base block mt-1">
              {s?.gross_margin_pct ? `${s.gross_margin_pct.toFixed(1)}%` : '—'}
            </span>
          </div>
          <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800/80">
            <span className="text-slate-400 block text-[11px]">Operating Expenses</span>
            <span className="font-mono font-semibold text-slate-300 text-base block mt-1">
              {formatCurrency(s?.operating_expenses?.value)}
            </span>
          </div>
          <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800/80">
            <span className="text-slate-400 block text-[11px]">Operating Profit</span>
            <span className="font-mono font-semibold text-white text-base block mt-1">
              {formatCurrency(s?.operating_profit?.value)}
            </span>
          </div>
          <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800/80">
            <span className="text-slate-400 block text-[11px]">Operating Margin</span>
            <span className="font-mono font-semibold text-white text-base block mt-1">
              {s?.operating_margin_pct ? `${s.operating_margin_pct.toFixed(1)}%` : '—'}
            </span>
          </div>
          <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800/80">
            <span className="text-slate-400 block text-[11px]">Order Volume</span>
            <span className="font-mono font-semibold text-white text-base block mt-1">
              {formatNumber(s?.orders_count?.value)}
            </span>
          </div>
          <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800/80">
            <span className="text-slate-400 block text-[11px]">Average Order Value (AOV)</span>
            <span className="font-mono font-semibold text-white text-base block mt-1">
              {formatCurrency(s?.average_order_value?.value)}
            </span>
          </div>
        </div>
      </section>

      {/* Product Rankings Leaderboard */}
      <section className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div>
            <h3 className="text-base font-semibold text-white flex items-center gap-2">
              <Package className="w-5 h-5 text-emerald-400" />
              <span>Product Performance Rankings</span>
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Ranked dynamically by {selectedMetric.toUpperCase()}.
            </p>
          </div>
          <span className="text-xs font-mono text-slate-400">
            Evaluated {products?.data?.total_products_evaluated ?? 0} Products
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400 font-mono text-[11px]">
                <th className="py-2.5 px-3">Rank</th>
                <th className="py-2.5 px-3">Product Name</th>
                <th className="py-2.5 px-3">SKU</th>
                <th className="py-2.5 px-3">Category</th>
                <th className="py-2.5 px-3 text-right">Units Sold</th>
                <th className="py-2.5 px-3 text-right">Revenue</th>
                <th className="py-2.5 px-3 text-right">Gross Profit</th>
                <th className="py-2.5 px-3 text-right">Margin %</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono">
              {products?.data?.items?.map((p) => (
                <tr key={p.product_id} className="hover:bg-slate-800/40 transition-colors">
                  <td className="py-3 px-3 font-bold text-slate-300">#{p.rank}</td>
                  <td className="py-3 px-3 font-sans font-medium text-white">{p.product_name}</td>
                  <td className="py-3 px-3 text-slate-400">{p.sku}</td>
                  <td className="py-3 px-3 text-slate-400 font-sans">{p.category}</td>
                  <td className="py-3 px-3 text-right text-slate-300">{formatNumber(p.units_sold)}</td>
                  <td className="py-3 px-3 text-right text-cyan-400 font-semibold">{formatCurrency(p.revenue)}</td>
                  <td className="py-3 px-3 text-right text-emerald-400">{formatCurrency(p.gross_profit)}</td>
                  <td className="py-3 px-3 text-right text-slate-300">
                    {p.margin_pct ? `${p.margin_pct.toFixed(1)}%` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Category Breakdown & Customer Segments Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Categories */}
        <section className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <Layers className="w-4 h-4 text-cyan-400" />
              <span>Category Revenue Contribution</span>
            </h3>
            <span className="text-xs font-mono text-slate-400">
              {categories?.data?.items?.length ?? 0} Categories
            </span>
          </div>

          <div className="space-y-2">
            {categories?.data?.items?.map((cat) => (
              <div
                key={cat.dimension_value}
                className="flex items-center justify-between p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 text-xs"
              >
                <div>
                  <span className="font-semibold text-slate-200">{cat.dimension_value}</span>
                  <span className="text-[11px] text-slate-400 block">
                    Share: {cat.percentage_of_total?.toFixed(1)}% of total
                  </span>
                </div>
                <span className="font-mono font-bold text-cyan-400">
                  {formatCurrency(cat.metric_value)}
                </span>
              </div>
            ))}
          </div>
        </section>

        {/* Customer Segments */}
        <section className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <Users className="w-4 h-4 text-emerald-400" />
              <span>Customer Segment Distribution</span>
            </h3>
            <span className="text-xs font-mono text-slate-400">
              {customerSegments?.data?.items?.length ?? 0} Segments
            </span>
          </div>

          <div className="space-y-2">
            {customerSegments?.data?.items?.map((seg) => (
              <div
                key={seg.dimension_value}
                className="flex items-center justify-between p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 text-xs"
              >
                <div>
                  <span className="font-semibold text-slate-200 capitalize">{seg.dimension_value}</span>
                  <span className="text-[11px] text-slate-400 block">
                    {seg.order_count ?? 0} orders recorded
                  </span>
                </div>
                <span className="font-mono font-bold text-emerald-400">
                  {formatCurrency(seg.metric_value)}
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* Direct AI Inquiry Trigger */}
      <section className="rounded-2xl border border-cyan-800/40 bg-cyan-950/20 p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h4 className="text-sm font-semibold text-white flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-cyan-400" />
            <span>Deepen Analysis with NEXUS Intelligence</span>
          </h4>
          <p className="text-xs text-slate-300 mt-0.5">
            Query underlying causal drivers or forward-looking projections for {selectedMetric.toUpperCase()}.
          </p>
        </div>
        <button
          onClick={() => onAskQuery(`Analyze what is driving our ${selectedMetric} performance and variance`)}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold shadow-md shadow-cyan-600/25 transition-all shrink-0"
        >
          <span>Ask AI Analyst</span>
          <ArrowUpRight className="w-4 h-4" />
        </button>
      </section>

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
