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
import { CardSkeleton } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EvidencePanel } from '../components/common/EvidencePanel';
import { IntelligenceHeader } from '../components/intelligence/IntelligenceHeader';

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
  const [customerSegments, setCustomerSegments] = useState<BreakdownResponse | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeEvidence, setActiveEvidence] = useState<EvidenceRecord | null>(null);

  const fetchAnalytics = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [sumRes, prodRes, custRes] = await Promise.all([
        getFinancialSummary({ granularity }),
        getProductRankings({ ranking_metric: selectedMetric, limit: 10 }),
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

  if (loading && !summary) {
    return <CardSkeleton rows={6} />;
  }

  if (error && !summary) {
    return <ErrorState message={error} onRetry={fetchAnalytics} />;
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

  const currentMetricValue =
    selectedMetric === 'revenue'
      ? formatCurrency(netSalesVal, true)
      : selectedMetric === 'profit'
      ? formatCurrency(grossProfitVal, true)
      : formatNumber(unitsSoldVal);

  const currentMetricChange =
    selectedMetric === 'revenue'
      ? netSalesChange
      : selectedMetric === 'profit'
      ? grossProfitChange
      : unitsSoldChange;

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* Header */}
      <IntelligenceHeader
        eyebrow="DETERMINISTIC ANALYTICS LAYER"
        title="Deterministic Business Analytics"
        subtitle="Mathematical business intelligence derived strictly from relational database tables. Zero LLM calculation hallucinations."
        icon={BarChart3}
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => onAskQuery(`Analyze the current ${selectedMetric} variance and drivers`)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-cyan-950/80 hover:bg-cyan-900 border border-brand-cyan/40 text-brand-cyan text-xs font-medium transition-all"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Ask Analyst</span>
            </button>
            {summary?.evidence && (
              <button
                onClick={() => setActiveEvidence(summary.evidence)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-surface hover:bg-surface-elevated border border-surface-elevated text-slate-200 text-xs font-medium transition-all"
              >
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                <span>Verify SQL Evidence</span>
              </button>
            )}
          </div>
        }
      />

      {/* 1. CONTINUOUS WORKFLOW ANCHOR: QUESTION -> METRIC -> RESULT -> INVESTIGATE / FORECAST */}
      <section className="p-6 rounded-3xl bg-surface/60 border border-surface-elevated space-y-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-elevated pb-4">
          <div className="space-y-1">
            <span className="text-[10px] font-mono uppercase tracking-widest text-brand-cyan font-semibold">
              ANALYTICAL INQUIRY TARGET
            </span>
            <div className="flex items-baseline gap-3">
              <h3 className="text-xl sm:text-2xl font-bold text-white font-sans capitalize">
                Net {selectedMetric}
              </h3>
              <span className="text-2xl sm:text-3xl font-extrabold font-mono text-brand-cyan">
                {currentMetricValue}
              </span>
              {currentMetricChange !== null && currentMetricChange !== undefined && (
                <span
                  className={`inline-flex items-center gap-1 text-xs font-mono font-semibold px-2 py-0.5 rounded ${
                    currentMetricChange >= 0
                      ? 'text-emerald-400 bg-emerald-950/70 border border-emerald-900/60'
                      : 'text-rose-400 bg-rose-950/70 border border-rose-900/60'
                  }`}
                >
                  {currentMetricChange >= 0 ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                  <span>{formatPercent(currentMetricChange)} vs prev</span>
                </span>
              )}
            </div>
          </div>

          {/* Workflow Action Triggers */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => onNavigate('/investigations')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-cyan-950/80 hover:bg-cyan-900 border border-brand-cyan/40 text-brand-cyan text-xs font-medium transition-all"
            >
              <SearchCode className="w-3.5 h-3.5" />
              <span>Why did this change? [Investigate]</span>
            </button>

            <button
              onClick={() => onNavigate('/forecasts')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-surface-elevated hover:bg-surface-highlight border border-surface-highlight text-violet-300 text-xs font-medium transition-all"
            >
              <TrendingUp className="w-3.5 h-3.5" />
              <span>What happens next? [Forecast]</span>
            </button>
          </div>
        </div>

        {/* Filter Controls */}
        <div className="flex flex-wrap items-center justify-between gap-3 text-xs font-mono">
          <div className="flex items-center gap-2">
            <span className="text-slate-400">Metric Target:</span>
            <div className="inline-flex rounded-lg bg-void border border-surface-elevated p-0.5">
              {(['revenue', 'profit', 'units'] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setSelectedMetric(m)}
                  className={`px-3 py-1 rounded-md transition-all capitalize ${
                    selectedMetric === m
                      ? 'bg-brand-cyan text-void font-bold shadow-sm'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-slate-400">Granularity:</span>
            <div className="inline-flex rounded-lg bg-void border border-surface-elevated p-0.5">
              {(['monthly', 'weekly'] as const).map((g) => (
                <button
                  key={g}
                  onClick={() => setGranularity(g)}
                  className={`px-3 py-1 rounded-md transition-all capitalize ${
                    granularity === g
                      ? 'bg-surface-elevated text-white font-semibold'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {g}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* 2. GRANULAR TIME SERIES CHART */}
      <section className="rounded-3xl border border-surface-elevated bg-surface/50 p-6 space-y-4">
        <div className="flex items-center justify-between border-b border-surface-elevated pb-3">
          <div>
            <h3 className="text-base font-bold text-white capitalize font-sans">
              {selectedMetric} Telemetry Progression ({granularity})
            </h3>
            <p className="text-xs text-slate-400 mt-0.5 font-sans">
              Aggregated from completed sales orders without sampling or approximation.
            </p>
          </div>

          {timeSeries?.evidence && (
            <button
              onClick={() => setActiveEvidence(timeSeries.evidence)}
              className="text-xs font-mono text-brand-cyan hover:underline flex items-center gap-1"
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
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                <XAxis dataKey="label" stroke="#64748b" fontSize={11} tickLine={false} axisLine={{ stroke: '#334155' }} />
                <YAxis
                  stroke="#64748b"
                  fontSize={11}
                  tickLine={false}
                  axisLine={{ stroke: '#334155' }}
                  tickFormatter={(v) => (selectedMetric === 'units' ? formatNumber(v) : `${getGlobalCurrencySymbol()}${(v / 1000).toFixed(0)}K`)}
                />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (active && payload && payload.length) {
                      return (
                        <div className="rounded-xl border border-surface-highlight bg-void-sub p-3 shadow-xl text-xs font-mono">
                          <p className="text-slate-400">{label}</p>
                          <p className="text-brand-cyan font-bold text-sm">
                            {selectedMetric === 'units'
                              ? `${formatNumber(payload[0].value as number)} units`
                              : formatCurrency(payload[0].value as number)}
                          </p>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Line type="monotone" dataKey="value" stroke="#00F2FE" strokeWidth={2.5} dot={{ fill: '#00F2FE', r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-full min-h-[16rem] flex flex-col items-center justify-center p-6 text-center rounded-2xl bg-void/40 border border-dashed border-surface-elevated space-y-2">
              <BarChart3 className="w-8 h-8 text-slate-500" />
              <p className="text-xs font-semibold text-slate-300">
                {selectedMetric === 'profit'
                  ? 'Profit Telemetry Unavailable: Line-Item & Product Cost Data Required'
                  : 'Telemetry Unavailable: Chronological Data Points Required'}
              </p>
              <p className="text-[11px] text-slate-400 max-w-sm">
                {selectedMetric === 'profit'
                  ? 'Calculating historical profit trends requires catalog product unit costs and transaction line items.'
                  : 'No chronological data points found for the active filter. Line-item or sales order timestamps are required.'}
              </p>
            </div>
          )}
        </div>
      </section>

      {/* 3. PRODUCT RANKINGS & SEGMENTS */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Top Products Table */}
        <section className="rounded-3xl border border-surface-elevated bg-surface/50 p-6 space-y-4">
          <div className="flex items-center justify-between border-b border-surface-elevated pb-3">
            <h3 className="text-base font-bold text-white font-sans flex items-center gap-2">
              <Package className="w-4 h-4 text-brand-cyan" />
              <span>Product Leaderboard (Top 10)</span>
            </h3>
            <span className="text-[11px] font-mono text-slate-400">Ranked by {selectedMetric}</span>
          </div>

          <div className="overflow-x-auto">
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
                      <tr className="border-b border-surface-elevated text-slate-400 font-mono">
                        <th className="pb-2">SKU / Product</th>
                        <th className="pb-2 text-right">Metric Value</th>
                        <th className="pb-2 text-right">Units</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-surface-elevated">
                      {productList.map((p: any, idx: number) => (
                        <tr key={idx} className="hover:bg-surface/60 transition-colors">
                          <td className="py-2.5 font-medium text-slate-200">
                            <div className="font-sans font-semibold">{p.product_name}</div>
                            <div className="font-mono text-[10px] text-slate-500">{p.sku} • {p.category}</div>
                          </td>
                          <td className="py-2.5 text-right font-mono font-semibold text-white">
                            {formatCurrency(p.metric_value, true)}
                          </td>
                          <td className="py-2.5 text-right font-mono text-slate-300">
                            {formatNumber(p.units_sold)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                );
              }
              return (
                <div className="py-8 px-4 text-center rounded-2xl bg-void/40 border border-dashed border-surface-elevated space-y-2">
                  <Package className="w-8 h-8 text-slate-500 mx-auto" />
                  <p className="text-xs font-semibold text-slate-300">No Product-Level Telemetry Available</p>
                  <p className="text-[11px] text-slate-400 max-w-sm mx-auto">
                    Product rankings require product catalog items and order line items (SaleItem). Upload product catalog data to unlock SKU-level performance insights.
                  </p>
                </div>
              );
            })()}
          </div>
        </section>

        {/* Customer Cohort Segments */}
        <section className="rounded-3xl border border-surface-elevated bg-surface/50 p-6 space-y-4">
          <div className="flex items-center justify-between border-b border-surface-elevated pb-3">
            <h3 className="text-base font-bold text-white font-sans flex items-center gap-2">
              <Users className="w-4 h-4 text-emerald-400" />
              <span>Customer Segmentation Analysis</span>
            </h3>
            <span className="text-[11px] font-mono text-slate-400">Behavioral cohorts</span>
          </div>

          <div className="space-y-3">
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
                  <div key={idx} className="p-3.5 rounded-2xl bg-void/60 border border-surface-elevated space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-semibold text-slate-200 font-sans capitalize">{dimName}</span>
                      <span className="font-mono font-bold text-brand-cyan">{formatCurrency(Number(val), true)}</span>
                    </div>
                    <div className="flex items-center justify-between text-[11px] font-mono text-slate-400">
                      <span>{formatNumber(orders)} orders</span>
                      <span>Share: {typeof share === 'number' ? share.toFixed(1) : share}%</span>
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="py-8 px-4 text-center rounded-2xl bg-void/40 border border-dashed border-surface-elevated space-y-2">
                <Users className="w-8 h-8 text-slate-500 mx-auto" />
                <p className="text-xs font-semibold text-slate-300">No Customer Segments Available</p>
                <p className="text-[11px] text-slate-400 max-w-sm mx-auto">
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
