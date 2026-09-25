import React, { useState, useEffect } from 'react';
import {
  TrendingUp,
  ShieldAlert,
  ShieldCheck,
  SearchCode,
  Sparkles,
  Info,
  AlertTriangle,
} from 'lucide-react';
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from 'recharts';
import { generateStructuredForecast } from '../services/forecast';
import { getRevenueTimeSeries } from '../services/analytics';
import { ForecastResponse, ForecastEvidence, TimeSeriesResponse } from '../types/api';
import { formatCurrency } from '../utils/formatters';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { StatusBadge } from '../components/common/StatusBadge';
import { EvidencePanel } from '../components/common/EvidencePanel';

interface ForecastsPageProps {
  onNavigate: (route: string) => void;
  onAskQuery: (query: string) => void;
}

export const ForecastsPage: React.FC<ForecastsPageProps> = ({
  onNavigate,
  onAskQuery,
}) => {
  const [metric, setMetric] = useState('revenue');
  const [horizon, setHorizon] = useState(3);
  const [frequency, setFrequency] = useState<'monthly' | 'weekly' | 'daily'>('monthly');
  const [policy, setPolicy] = useState<'validated_best' | 'baseline_only'>('validated_best');

  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [historySeries, setHistorySeries] = useState<TimeSeriesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeEvidence, setActiveEvidence] = useState<ForecastEvidence | null>(null);

  const handleGenerateForecast = async () => {
    setLoading(true);
    setError(null);
    try {
      const [fRes, hRes] = await Promise.all([
        generateStructuredForecast({
          target_metric: metric,
          forecast_horizon: horizon,
          frequency,
          model_policy: policy,
        }),
        getRevenueTimeSeries({ granularity: frequency }),
      ]);
      setForecast(fRes);
      setHistorySeries(hRes);
    } catch (err: any) {
      setError(err?.message || 'Failed to generate statistical forecast.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Generate initial forecast on page mount
    handleGenerateForecast();
  }, []);

  // Merge historical time-series with forecast points for continuous visualization
  const chartData: any[] = [];
  if (historySeries?.data?.points) {
    historySeries.data.points.slice(-8).forEach((pt) => {
      chartData.push({
        period: pt.period_label,
        historical: pt.value,
        forecast: null,
        lower_bound: null,
        upper_bound: null,
      });
    });
  }

  if (forecast?.predictions && forecast.status === 'completed') {
    // Connect the last historical point with the forecast start
    if (chartData.length > 0) {
      const lastHist = chartData[chartData.length - 1];
      lastHist.forecast = lastHist.historical;
      lastHist.lower_bound = lastHist.historical;
      lastHist.upper_bound = lastHist.historical;
    }

    forecast.predictions.forEach((p) => {
      chartData.push({
        period: p.period,
        historical: null,
        forecast: p.point_forecast,
        lower_bound: p.lower_bound,
        upper_bound: p.upper_bound,
      });
    });
  }

  const isInsufficient = forecast?.status === 'insufficient_data';

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* Header & Controls Panel */}
      <section className="rounded-3xl border border-slate-800 bg-slate-900/80 p-6 sm:p-8 space-y-5">
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-950/80 border border-cyan-800/80 text-cyan-400 text-xs font-mono font-medium">
              <TrendingUp className="w-3.5 h-3.5" />
              <span>Phase 7 Predictive Intelligence</span>
            </div>
            <h2 className="text-2xl sm:text-3xl font-bold text-white tracking-tight">
              Time-Series Predictive Forecasting
            </h2>
            <p className="text-xs sm:text-sm text-slate-400 max-w-2xl">
              Evaluate prospective horizons using expanding-window backtested statistical models
              with rigorous prediction intervals and parsimonious baseline selection.
            </p>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={() => onNavigate('/investigations')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 text-xs font-medium transition-all"
            >
              <SearchCode className="w-3.5 h-3.5 text-cyan-400" />
              <span>Investigate Drivers</span>
            </button>
            <button
              onClick={() => onAskQuery(`Explain the ${metric} forecast and its prediction intervals`)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-cyan-950/80 hover:bg-cyan-900/80 border border-cyan-800 text-cyan-300 text-xs font-medium transition-all"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Ask Analyst</span>
            </button>
          </div>
        </div>

        {/* Forecast Configuration Form */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 pt-2">
          {/* Target Metric */}
          <div className="space-y-1.5">
            <label className="text-xs font-mono text-slate-400">Target Metric</label>
            <select
              value={metric}
              onChange={(e) => setMetric(e.target.value)}
              className="w-full rounded-xl bg-slate-950 border border-slate-800 px-3 py-2 text-xs text-slate-200 focus:outline-none focus:ring-2 focus:ring-cyan-500 font-sans"
            >
              <option value="revenue">Net Revenue</option>
              <option value="units">Sales Units</option>
              <option value="orders">Total Orders</option>
              <option value="sales">Gross Sales</option>
            </select>
          </div>

          {/* Forecast Horizon */}
          <div className="space-y-1.5">
            <label className="text-xs font-mono text-slate-400">Horizon Periods (1–12)</label>
            <input
              type="number"
              min={1}
              max={12}
              value={horizon}
              onChange={(e) => setHorizon(Math.min(12, Math.max(1, parseInt(e.target.value) || 1)))}
              className="w-full rounded-xl bg-slate-950 border border-slate-800 px-3 py-2 text-xs text-slate-200 focus:outline-none focus:ring-2 focus:ring-cyan-500 font-mono"
            />
          </div>

          {/* Temporal Frequency */}
          <div className="space-y-1.5">
            <label className="text-xs font-mono text-slate-400">Frequency</label>
            <select
              value={frequency}
              onChange={(e) => setFrequency(e.target.value as any)}
              className="w-full rounded-xl bg-slate-950 border border-slate-800 px-3 py-2 text-xs text-slate-200 focus:outline-none focus:ring-2 focus:ring-cyan-500 font-sans"
            >
              <option value="monthly">Monthly (MS)</option>
              <option value="weekly">Weekly (W-MON)</option>
              <option value="daily">Daily (D)</option>
            </select>
          </div>

          {/* Model Selection Policy */}
          <div className="space-y-1.5">
            <label className="text-xs font-mono text-slate-400">Selection Policy</label>
            <select
              value={policy}
              onChange={(e) => setPolicy(e.target.value as any)}
              className="w-full rounded-xl bg-slate-950 border border-slate-800 px-3 py-2 text-xs text-slate-200 focus:outline-none focus:ring-2 focus:ring-cyan-500 font-sans"
            >
              <option value="validated_best">Validated Best (Backtest)</option>
              <option value="baseline_only">Baseline Only</option>
            </select>
          </div>

          {/* Submit Button */}
          <div className="flex items-end">
            <button
              onClick={handleGenerateForecast}
              disabled={loading}
              className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-800 text-white text-xs font-semibold shadow-md shadow-cyan-600/25 transition-all h-[38px]"
            >
              <TrendingUp className="w-4 h-4" />
              <span>Generate Forecast</span>
            </button>
          </div>
        </div>
      </section>

      {loading && (
        <LoadingState
          message="Running expanding-window backtests and fitting candidates..."
          stepIndex={1}
          steps={[
            'Validating time-series data quality gate...',
            'Executing out-of-sample backtests on candidate models...',
            'Enforcing parsimonious baseline selection rule...',
            'Generating prediction intervals and provenance...',
          ]}
        />
      )}

      {error && <ErrorState message={error} onRetry={handleGenerateForecast} />}

      {/* Insufficient Data State */}
      {isInsufficient && !loading && (
        <div className="rounded-3xl border border-sky-800/60 bg-sky-950/20 p-8 text-center space-y-4">
          <div className="w-12 h-12 rounded-2xl bg-sky-900/60 border border-sky-700/60 flex items-center justify-center text-sky-400 mx-auto">
            <ShieldAlert className="w-6 h-6" />
          </div>
          <div className="max-w-md mx-auto space-y-2">
            <h3 className="text-base font-bold text-sky-200">
              Insufficient Historical Data
            </h3>
            <p className="text-xs text-slate-300 leading-relaxed">
              {forecast?.limitations?.[0] ||
                'The selected series does not contain enough continuous historical observations to produce an evidence-backed forecast.'}
            </p>
          </div>
          <div className="pt-2">
            <StatusBadge status="INSUFFICIENT_DATA" />
          </div>
        </div>
      )}

      {/* Validated Forecast Results */}
      {forecast && forecast.status === 'completed' && !loading && (
        <div className="space-y-6 animate-in fade-in duration-200">
          {/* Executive Forecast Summary Row */}
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
            <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 space-y-1">
              <span className="text-[11px] font-mono uppercase text-slate-400">Selected Model</span>
              <p className="text-base font-bold text-cyan-400 capitalize">
                {forecast.model?.name?.replace('_', ' ')}
              </p>
              <span className="text-[10px] font-mono text-slate-400">
                v{forecast.model?.version} • {forecast.model?.is_baseline ? 'Baseline' : 'Statistical'}
              </span>
            </div>

            <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 space-y-1">
              <span className="text-[11px] font-mono uppercase text-slate-400">Backtest MAE</span>
              <p className="text-base font-bold text-white font-mono">
                {forecast.evaluation?.mae !== undefined ? forecast.evaluation.mae.toFixed(2) : '—'}
              </p>
              <span className="text-[10px] font-mono text-slate-400">Mean Absolute Error</span>
            </div>

            <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 space-y-1">
              <span className="text-[11px] font-mono uppercase text-slate-400">sMAPE Accuracy</span>
              <p className="text-base font-bold text-emerald-400 font-mono">
                {forecast.evaluation?.smape !== undefined
                  ? `${forecast.evaluation.smape.toFixed(1)}%`
                  : '—'}
              </p>
              <span className="text-[10px] font-mono text-slate-400">Bounded Percentage</span>
            </div>

            <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 space-y-1">
              <span className="text-[11px] font-mono uppercase text-slate-400">Data Quality</span>
              <div className="pt-1">
                <StatusBadge status={forecast.data_quality?.status || 'READY'} size="sm" />
              </div>
              <span className="text-[10px] font-mono text-slate-400 block pt-0.5">
                {forecast.data_quality?.observation_count} points evaluated
              </span>
            </div>
          </div>

          {/* Historical + Prospective Chart with Shaded Prediction Interval */}
          <section className="rounded-3xl border border-slate-800 bg-slate-900/70 p-6 space-y-4">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
              <div>
                <h3 className="text-base font-semibold text-white flex items-center gap-2">
                  <TrendingUp className="w-5 h-5 text-cyan-400" />
                  <span>Historical Observed + Prospective Forecast</span>
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Shaded envelope reflects statistical prediction interval derived from empirical residual variance.
                </p>
              </div>

              {forecast.evidence && (
                <button
                  onClick={() => setActiveEvidence(forecast.evidence)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-medium transition-all"
                >
                  <ShieldCheck className="w-4 h-4 text-emerald-400" />
                  <span>Model Provenance</span>
                </button>
              )}
            </div>

            <div className="h-80 w-full pt-2">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
                  <defs>
                    <linearGradient id="forecastIntervalGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#818cf8" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#818cf8" stopOpacity={0.05} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                  <XAxis
                    dataKey="period"
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
                    tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}K`}
                  />
                  <Tooltip
                    content={({ active, payload, label }) => {
                      if (active && payload && payload.length) {
                        const pt = payload[0].payload;
                        return (
                          <div className="rounded-xl border border-slate-700 bg-slate-900 p-3 shadow-xl text-xs space-y-1 font-mono">
                            <p className="font-semibold text-slate-200 font-sans">{label}</p>
                            {pt.historical !== null && (
                              <p className="text-cyan-400">
                                Historical: {formatCurrency(pt.historical)}
                              </p>
                            )}
                            {pt.forecast !== null && (
                              <p className="text-violet-400 font-bold">
                                Point Forecast: {formatCurrency(pt.forecast)}
                              </p>
                            )}
                            {pt.lower_bound !== null && pt.upper_bound !== null && (
                              <p className="text-slate-400 text-[11px]">
                                Interval: {formatCurrency(pt.lower_bound)} — {formatCurrency(pt.upper_bound)}
                              </p>
                            )}
                          </div>
                        );
                      }
                      return null;
                    }}
                  />
                  <Legend
                    verticalAlign="top"
                    align="right"
                    wrapperStyle={{ paddingBottom: '10px', fontSize: '11px' }}
                  />
                  {/* Historical Observed Line */}
                  <Line
                    type="monotone"
                    name="Historical Actual"
                    dataKey="historical"
                    stroke="#38bdf8"
                    strokeWidth={2.5}
                    dot={{ r: 3, fill: '#38bdf8' }}
                  />
                  {/* Prospective Prediction Envelope */}
                  <Area
                    type="monotone"
                    name="Upper Prediction Bound"
                    dataKey="upper_bound"
                    stroke="#818cf8"
                    strokeDasharray="3 3"
                    fill="url(#forecastIntervalGradient)"
                  />
                  {/* Point Forecast Line */}
                  <Line
                    type="monotone"
                    name="Point Forecast"
                    dataKey="forecast"
                    stroke="#a855f7"
                    strokeWidth={2.5}
                    strokeDasharray="4 4"
                    dot={{ r: 4, fill: '#a855f7' }}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </section>

          {/* Predictions Table with Prediction Intervals */}
          <section className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
            <h3 className="text-base font-semibold text-white">
              Numerical Forecast Points & Statistical Prediction Intervals
            </h3>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400 text-[11px]">
                    <th className="py-2.5 px-3">Horizon Period</th>
                    <th className="py-2.5 px-3 text-right">Point Forecast</th>
                    <th className="py-2.5 px-3 text-right">Lower Bound (95%)</th>
                    <th className="py-2.5 px-3 text-right">Upper Bound (95%)</th>
                    <th className="py-2.5 px-3 text-right">Estimated Band Spread</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {forecast.predictions?.map((p) => {
                    const spread = p.upper_bound - p.lower_bound;
                    return (
                      <tr key={p.period} className="hover:bg-slate-800/30 transition-colors">
                        <td className="py-3 px-3 font-semibold text-slate-200">{p.period}</td>
                        <td className="py-3 px-3 text-right text-violet-400 font-bold">
                          {formatCurrency(p.point_forecast)}
                        </td>
                        <td className="py-3 px-3 text-right text-slate-400">
                          {formatCurrency(p.lower_bound)}
                        </td>
                        <td className="py-3 px-3 text-right text-slate-400">
                          {formatCurrency(p.upper_bound)}
                        </td>
                        <td className="py-3 px-3 text-right text-slate-400">
                          ±{formatCurrency(spread / 2)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {/* Assumptions & Limitations Disclosures */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
            <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-2">
              <span className="font-semibold text-slate-200 flex items-center gap-1.5">
                <Info className="w-4 h-4 text-cyan-400" />
                Modeling Assumptions
              </span>
              <ul className="list-disc list-inside space-y-1 text-slate-400 leading-relaxed text-[11px]">
                {forecast.assumptions?.map((asm, i) => (
                  <li key={i}>{asm}</li>
                ))}
              </ul>
            </div>

            <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-2">
              <span className="font-semibold text-slate-200 flex items-center gap-1.5">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                Statistical Limitations
              </span>
              <ul className="list-disc list-inside space-y-1 text-slate-400 leading-relaxed text-[11px]">
                {forecast.limitations?.map((lim, i) => (
                  <li key={i}>{lim}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Model Provenance Evidence Modal */}
      {activeEvidence && (
        <EvidencePanel
          forecastEvidence={activeEvidence}
          isOpen={Boolean(activeEvidence)}
          onClose={() => setActiveEvidence(null)}
          asModal
        />
      )}
    </div>
  );
};
