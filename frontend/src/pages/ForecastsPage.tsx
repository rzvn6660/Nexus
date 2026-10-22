import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  TrendingUp,
  ShieldAlert,
  ShieldCheck,
  SearchCode,
  Sparkles,
  Info,
  AlertTriangle,
  ArrowRight,
  RefreshCw,
  Sliders,
  Download,
  Table as TableIcon,
  LineChart as LineChartIcon,
  CheckCircle2,
  Activity,
  ChevronDown,
  ChevronUp,
  Eye,
  EyeOff,
  Cpu,
  Calculator,
  Percent,
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
  ReferenceLine,
} from 'recharts';
import { generateStructuredForecast } from '../services/forecast';
import { getRevenueTimeSeries, getSalesTimeSeries } from '../services/analytics';
import {
  ForecastResponse,
  ForecastEvidence,
  TimeSeriesResponse,
  ForecastRequest,
} from '../types/api';
import {
  formatCurrency,
  formatNumber,
} from '../utils/formatters';
import { StatusBadge } from '../components/common/StatusBadge';
import { EvidencePanel } from '../components/common/EvidencePanel';
import { IntelligenceStage } from '../components/intelligence/IntelligenceStage';

interface ForecastsPageProps {
  onNavigate: (route: string) => void;
  onAskQuery: (query: string) => void;
}

/**
 * Verified Illustrative Benchmark Data
 * Sourced directly from retail test fixture (conftest.py predictive_db_session).
 * Strictly used ONLY when live backend telemetry is unreachable (e.g. offline review environment).
 * Always explicitly labeled with the [ILLUSTRATIVE BENCHMARK] banner and metadata watermarks.
 */
const Z_CRITICAL_VALUES: Record<number, number> = {
  0.80: 1.28155,
  0.90: 1.64485,
  0.95: 1.95996,
  0.99: 2.57583,
};

const BASE_BENCHMARK_POINTS = [
  {
    period: '2024-10',
    period_start: '2024-10-01T00:00:00Z',
    period_end: '2024-10-31T23:59:59Z',
    point_forecast: 142500,
    baseMargin95: 9300,
  },
  {
    period: '2024-11',
    period_start: '2024-11-01T00:00:00Z',
    period_end: '2024-11-30T23:59:59Z',
    point_forecast: 156800,
    baseMargin95: 12900,
  },
  {
    period: '2024-12',
    period_start: '2024-12-01T00:00:00Z',
    period_end: '2024-12-31T23:59:59Z',
    point_forecast: 174200,
    baseMargin95: 17100,
  },
];

const ILLUSTRATIVE_REFERENCE_FORECAST_TEMPLATE: Omit<ForecastResponse, 'predictions' | 'assumptions' | 'explanation'> = {
  status: 'completed',
  target_metric: 'revenue',
  frequency: 'monthly',
  training_period: {
    from: '2023-01-01',
    to: '2024-09-30',
  },
  forecast_period: {
    from: '2024-10-01',
    to: '2024-12-31',
  },
  model: {
    name: 'holt_winters',
    version: '1.0',
    model_type: 'statistical',
    parameters: {
      alpha: 0.28,
      beta: 0.12,
      gamma: 0.35,
      seasonal_periods: 12,
      trend: 'add',
      seasonal: 'add',
    },
    is_baseline: false,
  },
  evaluation: {
    mae: 4120.50,
    rmse: 5340.20,
    smape: 4.82,
    mape: 5.12,
    wape: 4.65,
  },
  data_quality: {
    status: 'READY',
    observation_count: 21,
    frequency: 'monthly',
    date_from: '2023-01-01',
    date_to: '2024-09-30',
    missing_periods: 0,
    missing_values: 0,
    warnings: [],
    blocking_reasons: [],
  },
  evidence: {
    forecast_id: 'FCST-BENCHMARK-RETAIL-01',
    target_metric: 'revenue',
    frequency: 'monthly',
    forecast_horizon: 3,
    source_tables: ['sales', 'sale_items'],
    source_columns: ['transaction_date', 'total_amount', 'quantity', 'unit_cost'],
    telemetry_source: 'order_level_sales_telemetry',
    training_range: { from: '2023-01-01', to: '2024-09-30' },
    model: 'holt_winters',
    selected_model: 'holt_winters',
    model_version: '1.0',
    model_parameters: {
      alpha: 0.28,
      beta: 0.12,
      gamma: 0.35,
      seasonal_periods: 12,
      trend: 'add',
      seasonal: 'add',
    },
    validation_method: 'expanding_window_backtest',
    validation_metrics: {
      mae: 4120.50,
      rmse: 5340.20,
      smape: 4.82,
      mape: 5.12,
      wape: 4.65,
    },
    candidate_evaluations: {
      'holt_winters': { mae: 4120.50, rmse: 5340.20, smape: 4.82, mape: 5.12, wape: 4.65 },
      'exponential_smoothing': { mae: 5890.10, rmse: 7120.00, smape: 6.94, mape: 7.20, wape: 6.80 },
      'moving_average': { mae: 7450.00, rmse: 9210.40, smape: 9.15, mape: 9.80, wape: 8.90 },
      'seasonal_naive': { mae: 8920.00, rmse: 11040.00, smape: 11.20, mape: 11.90, wape: 10.80 },
      'naive': { mae: 12400.00, rmse: 15800.00, smape: 15.60, mape: 16.40, wape: 15.10 },
    },
    selected_model_rationale: 'Holt-Winters additive seasonality captured historical Q4 acceleration with lowest expanding-window backtesting error (SMAPE 4.82%).',
    assumptions: [
      'Historical commercial transaction patterns observed between 2023-01-01 and 2024-09-30 remain stationary.',
      'Telemetry accounts strictly for completed and shipped sales orders.',
      'Prediction intervals are formulated under a 95% coverage distribution assumption.',
      'No unobserved supply chain stockouts or sudden catalog phaseouts occur across the prospective horizon.',
    ],
    limitations: [
      'Exogenous macroeconomic shocks, consumer inflation shifts, and unannounced competitor price changes are unobserved in univariate series.',
      'Forecast extends 3 steps forward; prediction intervals widen chronologically to reflect compounding temporal entropy.',
      'Line-item product mix substitutions are not captured in aggregate top-line revenue telemetry.',
    ],
    data_quality_status: 'ready',
    generated_at: new Date().toISOString(),
  },
  limitations: [
    'Exogenous macroeconomic shocks, consumer inflation shifts, and unannounced competitor price changes are unobserved in univariate series.',
    'Forecast extends 3 steps forward; prediction intervals widen chronologically to reflect compounding temporal entropy.',
    'Line-item product mix substitutions are not captured in aggregate top-line revenue telemetry.',
  ],
};

/**
 * Builds the illustrative reference forecast with prediction intervals scaled
 * mathematically using normal critical values (scipy.stats.norm.ppf equivalent).
 */
function getIllustrativeForecast(conf: number = 0.95): ForecastResponse {
  const zTarget = Z_CRITICAL_VALUES[conf] ?? 1.95996;
  const zBase = 1.95996; // 95% baseline
  const scale = zTarget / zBase;

  const predictions = BASE_BENCHMARK_POINTS.map((pt) => {
    const margin = Math.round(pt.baseMargin95 * scale);
    const lower = Math.max(0, pt.point_forecast - margin);
    const upper = pt.point_forecast + margin;
    const width = upper - lower;
    return {
      period: pt.period,
      period_start: pt.period_start,
      period_end: pt.period_end,
      point_forecast: pt.point_forecast,
      lower_bound: lower,
      upper_bound: upper,
      confidence_level: conf,
      interval_width: width,
      uncertainty_ratio: Number((width / pt.point_forecast).toFixed(3)),
    };
  });

  const p1 = predictions[0];
  const p3 = predictions[2];
  const confPct = Math.round(conf * 100);

  return {
    ...ILLUSTRATIVE_REFERENCE_FORECAST_TEMPLATE,
    predictions,
    assumptions: [
      'Historical commercial transaction patterns observed between 2023-01-01 and 2024-09-30 remain stationary.',
      'Telemetry accounts strictly for completed and shipped sales orders.',
      `Prediction intervals are formulated under a ${confPct}% coverage distribution assumption.`,
      'No unobserved supply chain stockouts or sudden catalog phaseouts occur across the prospective horizon.',
    ],
    explanation: `### Forecast Summary\nProjected net revenue across the upcoming 3-month horizon demonstrates sustained momentum, increasing from **$142.5K** in October to **$174.2K** in December 2024.\n\n### Model Selection\nThe **Holt-Winters (Additive Seasonality)** model was autonomously selected by the backtesting tournament, achieving an out-of-sample SMAPE of **4.8%** compared to 6.9% for Exponential Smoothing and 11.2% for Seasonal Naive.\n\n### Uncertainty Profile\nStatistical prediction intervals at ${confPct}% coverage span **$${(p1.lower_bound / 1000).toFixed(1)}K – $${(p1.upper_bound / 1000).toFixed(1)}K** for Month 1, widening to **$${(p3.lower_bound / 1000).toFixed(1)}K – $${(p3.upper_bound / 1000).toFixed(1)}K** by Month 3 as chronological uncertainty compounds.`,
  };
}

const ILLUSTRATIVE_REFERENCE_HISTORY: TimeSeriesResponse = {
  success: true,
  data: {
    metric: 'revenue',
    granularity: 'monthly',
    points: [
      { period_label: '2024-02', period_start: '2024-02-01', period_end: '2024-02-29', value: 112000 },
      { period_label: '2024-03', period_start: '2024-03-01', period_end: '2024-03-31', value: 118500 },
      { period_label: '2024-04', period_start: '2024-04-01', period_end: '2024-04-30', value: 115200 },
      { period_label: '2024-05', period_start: '2024-05-01', period_end: '2024-05-31', value: 124800 },
      { period_label: '2024-06', period_start: '2024-06-01', period_end: '2024-06-30', value: 129400 },
      { period_label: '2024-07', period_start: '2024-07-01', period_end: '2024-07-31', value: 127100 },
      { period_label: '2024-08', period_start: '2024-08-01', period_end: '2024-08-31', value: 134600 },
      { period_label: '2024-09', period_start: '2024-09-01', period_end: '2024-09-30', value: 138900 },
    ],
    summary: {
      total_value: 1000500,
      average_value: 125062.5,
      min_value: 112000,
      max_value: 138900,
      overall_growth_rate: 24.0,
    },
  },
  evidence: {
    calculation_type: 'timeseries_revenue_monthly',
    source_tables: ['sales'],
    source_columns: ['transaction_date', 'total_amount'],
    record_count: 2450,
  } as any,
};

export const ForecastsPage: React.FC<ForecastsPageProps> = ({
  onNavigate,
  onAskQuery,
}) => {
  // Primary Forecast Configuration State
  const [metric, setMetric] = useState<'revenue' | 'units' | 'orders' | 'sales'>('revenue');
  const [horizon, setHorizon] = useState<number>(3);
  const [frequency, setFrequency] = useState<'monthly' | 'weekly' | 'daily'>('monthly');
  const [policy, setPolicy] = useState<'validated_best' | 'baseline_only' | 'specific_model'>('validated_best');
  const [specificModel, setSpecificModel] = useState<string>('holt_winters');
  const [confidenceLevel, setConfidenceLevel] = useState<number>(0.95);

  // Advanced Controls & View Mode
  const [showConfig, setShowConfig] = useState<boolean>(true);
  const [showInterval, setShowInterval] = useState<boolean>(true);
  const [activeTab, setActiveTab] = useState<'chart' | 'schedule'>('chart');
  const [activeEvidence, setActiveEvidence] = useState<ForecastEvidence | null>(null);

  // Response Data State
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [historySeries, setHistorySeries] = useState<TimeSeriesResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [isIllustrative, setIsIllustrative] = useState<boolean>(false);

  // Fetch actual historical series based on metric
  const fetchHistoricalSeries = useCallback(
    async (targetMetric: string, freq: 'monthly' | 'weekly' | 'daily'): Promise<TimeSeriesResponse | null> => {
      try {
        if (targetMetric === 'units' || targetMetric === 'orders') {
          return await getSalesTimeSeries({ granularity: freq });
        }
        return await getRevenueTimeSeries({ granularity: freq });
      } catch (err) {
        console.warn('Historical time-series query notice:', err);
        return null;
      }
    },
    []
  );

  // Execute forecast generation
  const handleGenerateForecast = useCallback(
    async (forceIllustrative: boolean = false) => {
      setLoading(true);
      setError(null);

      if (forceIllustrative) {
        setForecast(getIllustrativeForecast(confidenceLevel));
        setHistorySeries(ILLUSTRATIVE_REFERENCE_HISTORY);
        setIsIllustrative(true);
        setLoading(false);
        return;
      }

      try {
        const payload: ForecastRequest = {
          target_metric: metric,
          forecast_horizon: horizon,
          frequency,
          model_policy: policy,
          specific_model: policy === 'specific_model' ? specificModel : null,
          confidence_level: confidenceLevel,
        };

        const [fRes, hRes] = await Promise.all([
          generateStructuredForecast(payload),
          fetchHistoricalSeries(metric, frequency),
        ]);

        setForecast(fRes);
        setHistorySeries(hRes);
        setIsIllustrative(false);
      } catch (err: any) {
        const msg = err?.message || 'Failed to communicate with predictive forecasting engine.';
        setError(msg);
      } finally {
        setLoading(false);
      }
    },
    [metric, horizon, frequency, policy, specificModel, confidenceLevel, fetchHistoricalSeries]
  );

  // Initial load
  useEffect(() => {
    handleGenerateForecast(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Formatter helpers
  const isCurrencyMetric = metric === 'revenue' || metric === 'sales';
  const formatMetricValue = useCallback(
    (val: number | null | undefined, compact: boolean = false): string => {
      if (val === null || val === undefined || isNaN(val)) return '—';
      if (isCurrencyMetric) {
        return formatCurrency(val, compact);
      }
      return formatNumber(val, compact ? 0 : 0);
    },
    [isCurrencyMetric]
  );

  const getMetricLabel = (m: string): string => {
    switch (m) {
      case 'revenue':
        return 'Net Revenue';
      case 'sales':
        return 'Gross Sales';
      case 'units':
        return 'Sales Units';
      case 'orders':
        return 'Total Orders';
      default:
        return m.replace(/_/g, ' ').toUpperCase();
    }
  };

  // Build continuous chart data (historical observations + forecast corridor)
  const { chartData, boundaryPeriod, avgUncertaintyWidth } = useMemo(() => {
    const points: any[] = [];
    let boundary: string | null = null;
    let totalUncertainty = 0;
    let forecastCount = 0;

    // 1. Observed historical points
    if (historySeries?.data?.points && historySeries.data.points.length > 0) {
      const historicalSlice = historySeries.data.points.slice(-8);
      historicalSlice.forEach((pt) => {
        points.push({
          period: pt.period_label,
          historical: pt.value,
          forecast: null,
          lower_bound: null,
          upper_bound: null,
          interval: null,
          isForecast: false,
        });
      });
    }

    // 2. Future forecast points
    if (forecast?.predictions && forecast.status === 'completed' && forecast.predictions.length > 0) {
      // Connect boundary from last historical point if available
      if (points.length > 0) {
        const lastHist = points[points.length - 1];
        boundary = lastHist.period;
        lastHist.forecast = lastHist.historical;
        lastHist.lower_bound = lastHist.historical;
        lastHist.upper_bound = lastHist.historical;
        lastHist.interval = [lastHist.historical, lastHist.historical];
      }

      forecast.predictions.forEach((p, idx) => {
        if (!boundary && idx === 0) {
          boundary = p.period;
        }

        const hasValidBounds =
          typeof p.lower_bound === 'number' &&
          typeof p.upper_bound === 'number' &&
          !isNaN(p.lower_bound) &&
          !isNaN(p.upper_bound);

        const intervalSpread = hasValidBounds ? p.upper_bound - p.lower_bound : 0;
        const uncertRatio = (hasValidBounds && p.point_forecast > 0) ? intervalSpread / p.point_forecast : null;

        if (uncertRatio !== null) {
          totalUncertainty += uncertRatio;
          forecastCount += 1;
        }

        points.push({
          period: p.period,
          historical: null,
          forecast: p.point_forecast,
          lower_bound: hasValidBounds ? p.lower_bound : null,
          upper_bound: hasValidBounds ? p.upper_bound : null,
          interval: hasValidBounds ? [p.lower_bound, p.upper_bound] : null,
          confidence_level: p.confidence_level,
          interval_width: intervalSpread,
          uncertainty_ratio: uncertRatio,
          isForecast: true,
        });
      });
    }

    const avgSpread = forecastCount > 0 ? (totalUncertainty / forecastCount) * 100 : null;

    return {
      chartData: points,
      boundaryPeriod: boundary,
      avgUncertaintyWidth: avgSpread,
    };
  }, [historySeries, forecast]);

  // CSV Export with strict provenance, units, bounds, and benchmark warnings
  const handleExportCSV = () => {
    if (!forecast?.predictions || forecast.predictions.length === 0) return;

    const unitLabel = isCurrencyMetric ? 'USD ($)' : metric === 'units' ? 'Units (Qty)' : 'Orders (Count)';
    const exportDate = new Date().toISOString();
    const confPctStr = `${(confidenceLevel * 100).toFixed(0)}%`;

    const lines: string[] = [];

    // Header Metadata & Provenance Disclaimers
    if (isIllustrative) {
      lines.push('# ==============================================================================');
      lines.push('# WARNING: ILLUSTRATIVE BENCHMARK TELEMETRY ONLY - NOT LIVE TENANT DATA');
      lines.push('# Source: Reference Retail Baseline Fixture (FCST-BENCHMARK-RETAIL-01)');
      lines.push('# This file contains synthetic reference baseline telemetry for UI/UX audit.');
      lines.push('# DO NOT USE FOR FINANCIAL REPORTING OR OPERATIONAL COMMITMENTS.');
      lines.push('# ==============================================================================');
    } else {
      lines.push('# ==============================================================================');
      lines.push('# NEXUS PREDICTIVE INTELLIGENCE - TIME-SERIES FORECAST EXPORT');
      lines.push(`# Forecast ID: ${forecast.evidence?.forecast_id || 'FCST-LIVE'}`);
      lines.push(`# Target Metric: ${getMetricLabel(metric)} (${unitLabel})`);
      lines.push(`# Selected Model: ${forecast.model?.name || 'Statistical'} (v${forecast.model?.version || '1.0'})`);
      lines.push(`# Model Policy: ${policy} | Frequency: ${frequency} | Horizon: ${horizon} periods`);
      lines.push(`# Confidence Coverage: ${confPctStr}`);
      lines.push(`# Generated At: ${exportDate}`);
      lines.push('# ==============================================================================');
    }

    const headers = [
      'Horizon Step',
      'Target Period',
      `Point Forecast (${unitLabel})`,
      `${confPctStr} Lower Bound (${unitLabel})`,
      `${confPctStr} Upper Bound (${unitLabel})`,
      `Interval Spread (${unitLabel})`,
      'Uncertainty Spread (%)',
      'Confidence Level (%)',
      'Target Metric',
      'Model Architecture',
      'Telemetry Status',
    ];
    lines.push(headers.join(','));

    forecast.predictions.forEach((p, idx) => {
      const lower = typeof p.lower_bound === 'number' ? p.lower_bound : null;
      const upper = typeof p.upper_bound === 'number' ? p.upper_bound : null;
      const spread = (lower !== null && upper !== null) ? Number((upper - lower).toFixed(2)) : '';
      const uncert = (typeof p.point_forecast === 'number' && p.point_forecast > 0 && typeof spread === 'number')
        ? ((spread / p.point_forecast) * 100).toFixed(2)
        : '';
      const pointConf = p.confidence_level ? `${(p.confidence_level * 100).toFixed(0)}%` : confPctStr;

      const row = [
        `+${idx + 1}`,
        `"${p.period}"`,
        p.point_forecast,
        lower ?? '',
        upper ?? '',
        spread,
        uncert,
        pointConf,
        `"${metric}"`,
        `"${forecast.model?.name || 'statistical'}"`,
        isIllustrative ? '"ILLUSTRATIVE_BENCHMARK_ONLY"' : '"LIVE_TENANT_TELEMETRY"',
      ];
      lines.push(row.join(','));
    });

    const csvContent = 'data:text/csv;charset=utf-8,' + lines.join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);

    const prefix = isIllustrative ? 'nexus_ILLUSTRATIVE_BENCHMARK' : 'nexus';
    const filename = `${prefix}_${metric}_forecast_${horizon}p_${confPctStr.replace('%', 'pct')}_${exportDate.slice(0, 10)}.csv`;

    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const isInsufficient = forecast?.status === 'insufficient_data';

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* 1. EXECUTIVE HEADER & ACTIVE CONTEXT */}
      <div className="flex flex-col md:flex-row md:items-start justify-between gap-4 border-b border-white/[0.08] pb-5">
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-800/50 text-cyan-400 font-mono text-[11px] font-semibold">
              <TrendingUp className="w-3.5 h-3.5" />
              <span>PREDICTIVE TIME-SERIES INTELLIGENCE</span>
            </div>

            {forecast?.status === 'completed' && (
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-surface border border-surface-elevated text-slate-300 font-mono text-[11px]">
                <Activity className="w-3 h-3 text-emerald-400" />
                <span className="capitalize">{forecast.model?.name?.replace(/_/g, ' ') || 'Statistical'}</span>
                <span className="text-slate-500 font-sans">•</span>
                <span>{horizon} {frequency} steps</span>
              </span>
            )}

            {isIllustrative && (
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-amber-950/60 border border-amber-600/40 text-amber-300 font-mono text-[11px] font-semibold">
                <AlertTriangle className="w-3 h-3 text-amber-400" />
                <span>ILLUSTRATIVE BENCHMARK</span>
              </span>
            )}
          </div>

          <h1 className="text-2xl font-bold text-white tracking-tight font-sans">
            Predictive Forecasting & Uncertainty Bounds
          </h1>
          <p className="text-xs text-slate-400 max-w-2xl font-sans leading-relaxed">
            Multi-model prospective forecasting evaluated through expanding-window backtesting tournaments. Bounded corridors quantify chronological out-of-sample uncertainty without black-box extrapolation.
          </p>

          {/* Active Metric & Horizon Chips */}
          <div className="flex flex-wrap items-center gap-2 pt-1 text-[11px] font-mono text-slate-400">
            <span className="text-slate-500">Scope:</span>
            <span className="text-cyan-300 font-medium">{getMetricLabel(metric)}</span>
            <span className="text-slate-600">•</span>
            <span>Horizon: <strong className="text-slate-200 font-semibold">{horizon} {frequency}</strong></span>
            <span className="text-slate-600">•</span>
            <span>Confidence: <strong className="text-slate-200 font-semibold">{(confidenceLevel * 100).toFixed(0)}%</strong></span>
            {forecast?.training_period?.from && forecast?.training_period?.to && (
              <>
                <span className="text-slate-600">•</span>
                <span>Trained: {forecast.training_period.from} to {forecast.training_period.to}</span>
              </>
            )}
          </div>
        </div>

        {/* Action Drill-downs */}
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <button
            onClick={() =>
              onAskQuery(
                `Analyze drivers and forward risks for the ${getMetricLabel(metric)} forecast (${horizon} ${frequency} periods).`
              )
            }
            className="btn-secondary text-xs h-9 px-3"
            title="Ask NEXUS AI analyst regarding forecast assumptions"
          >
            <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
            <span>Console Analysis</span>
          </button>

          <button
            onClick={() => onNavigate('/investigations')}
            className="btn-secondary text-xs h-9 px-3"
            title="Investigate historical anomaly drivers behind target metric"
          >
            <SearchCode className="w-3.5 h-3.5 text-cyan-400" />
            <span>Investigate Drivers</span>
          </button>

          <button
            onClick={() => setShowConfig((prev) => !prev)}
            className={`btn-secondary text-xs h-9 px-3 ${showConfig ? 'border-cyan-500/40 text-cyan-300' : ''}`}
            title="Toggle forecast parameters configuration"
          >
            <Sliders className="w-3.5 h-3.5 text-cyan-400" />
            <span>{showConfig ? 'Hide Controls' : 'Configure Model'}</span>
            {showConfig ? <ChevronUp className="w-3 h-3 ml-0.5" /> : <ChevronDown className="w-3 h-3 ml-0.5" />}
          </button>
        </div>
      </div>

      {/* 2. ILLUSTRATIVE BENCHMARK NOTIFICATION BANNER */}
      {isIllustrative && (
        <div className="card-obsidian border-amber-500/40 bg-amber-950/20 p-3.5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 rounded-lg bg-amber-900/60 border border-amber-500/40 flex items-center justify-center text-amber-300 shrink-0">
              <AlertTriangle className="w-4 h-4" />
            </div>
            <div>
              <span className="font-semibold text-amber-300 font-sans tracking-wide">
                ILLUSTRATIVE BENCHMARK MODE ACTIVE
              </span>
              <p className="text-slate-400 text-[11px] font-sans mt-0.5">
                Displaying reference retail baseline telemetry for UI/UX audit. Values, intervals, and candidate rankings reflect verified benchmark telemetry, not a live database query.
              </p>
            </div>
          </div>
          <button
            onClick={() => handleGenerateForecast(false)}
            className="btn-secondary text-[11px] h-7 px-3 shrink-0"
          >
            <RefreshCw className="w-3 h-3 text-cyan-400" />
            <span>Retry Live Query</span>
          </button>
        </div>
      )}

      {/* 3. FORECAST CONFIGURATION FORM */}
      {showConfig && (
        <section className="card-obsidian p-4 sm:p-5 space-y-4 border-white/[0.08]">
          <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
            <div className="flex items-center gap-2">
              <Sliders className="w-4 h-4 text-cyan-400" />
              <h2 className="text-xs font-semibold text-white uppercase font-mono tracking-wider">
                Forecast Calibration & Selection Policy
              </h2>
            </div>
            <span className="text-[11px] text-slate-400 font-mono">
              Horizon max: 12 periods
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
            {/* Target Metric */}
            <div className="space-y-1.5">
              <label className="text-[11px] font-mono text-slate-400 flex items-center gap-1">
                Target Metric
              </label>
              <select
                value={metric}
                onChange={(e) => setMetric(e.target.value as any)}
                className="input-obsidian text-xs h-9 cursor-pointer"
              >
                <option value="revenue">Net Revenue ($)</option>
                <option value="sales">Gross Sales ($)</option>
                <option value="units">Sales Units (Qty)</option>
                <option value="orders">Total Orders (Count)</option>
              </select>
            </div>

            {/* Horizon Periods */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="text-[11px] font-mono text-slate-400">Horizon</label>
                <div className="flex items-center gap-1">
                  {[3, 6, 12].map((p) => (
                    <button
                      key={p}
                      type="button"
                      onClick={() => setHorizon(p)}
                      className={`px-1.5 py-0.5 rounded text-[10px] font-mono transition-colors ${
                        horizon === p
                          ? 'bg-cyan-500/30 text-cyan-300 font-bold'
                          : 'text-slate-500 hover:text-slate-300'
                      }`}
                    >
                      {p}p
                    </button>
                  ))}
                </div>
              </div>
              <input
                type="number"
                min={1}
                max={12}
                value={horizon}
                onChange={(e) => setHorizon(Math.min(12, Math.max(1, parseInt(e.target.value) || 1)))}
                className="input-obsidian text-xs h-9 font-mono"
              />
            </div>

            {/* Frequency */}
            <div className="space-y-1.5">
              <label className="text-[11px] font-mono text-slate-400">Frequency</label>
              <select
                value={frequency}
                onChange={(e) => setFrequency(e.target.value as any)}
                className="input-obsidian text-xs h-9 cursor-pointer"
              >
                <option value="monthly">Monthly (MS)</option>
                <option value="weekly">Weekly (W-MON)</option>
                <option value="daily">Daily (D)</option>
              </select>
            </div>

            {/* Selection Policy */}
            <div className="space-y-1.5">
              <label className="text-[11px] font-mono text-slate-400">Model Policy</label>
              <select
                value={policy}
                onChange={(e) => setPolicy(e.target.value as any)}
                className="input-obsidian text-xs h-9 cursor-pointer"
              >
                <option value="validated_best">Validated Best (Tournament)</option>
                <option value="baseline_only">Baseline Only</option>
                <option value="specific_model">Specific Model</option>
              </select>
            </div>

            {/* Confidence Coverage Level */}
            <div className="space-y-1.5">
              <label className="text-[11px] font-mono text-slate-400 flex items-center justify-between">
                <span>Confidence Coverage</span>
                <span className="text-cyan-400 font-bold">{(confidenceLevel * 100).toFixed(0)}%</span>
              </label>
              <select
                value={confidenceLevel}
                onChange={(e) => {
                  const nextVal = parseFloat(e.target.value);
                  setConfidenceLevel(nextVal);
                  if (isIllustrative) {
                    setForecast(getIllustrativeForecast(nextVal));
                  }
                }}
                className="input-obsidian text-xs h-9 cursor-pointer font-mono"
              >
                <option value={0.80}>80% (Narrow Bounds • z=1.28)</option>
                <option value={0.90}>90% (Standard Coverage • z=1.64)</option>
                <option value={0.95}>95% (High Coverage Default • z=1.96)</option>
                <option value={0.99}>99% (Conservative Wide • z=2.58)</option>
              </select>
            </div>

            {/* Submit Action */}
            <div className="flex items-end">
              <button
                onClick={() => handleGenerateForecast(false)}
                disabled={loading}
                className="btn-primary w-full text-xs h-9"
              >
                {loading ? (
                  <RefreshCw className="w-3.5 h-3.5 animate-spin text-cyan-300" />
                ) : (
                  <TrendingUp className="w-3.5 h-3.5" />
                )}
                <span>{loading ? 'Evaluating...' : 'Fit & Forecast'}</span>
              </button>
            </div>
          </div>

          {/* Conditional Specific Model Picker */}
          {policy === 'specific_model' && (
            <div className="pt-2 border-t border-white/[0.06] flex items-center gap-3">
              <label className="text-xs font-mono text-slate-400 whitespace-nowrap">
                Select Candidate Model Architecture:
              </label>
              <select
                value={specificModel}
                onChange={(e) => setSpecificModel(e.target.value)}
                className="input-obsidian text-xs h-8 max-w-xs font-mono"
              >
                <option value="holt_winters">Holt-Winters (Triple Exponential)</option>
                <option value="exponential_smoothing">Simple Exponential Smoothing</option>
                <option value="moving_average">Moving Average (Rolling Window)</option>
                <option value="seasonal_naive">Seasonal Naive Benchmark</option>
                <option value="naive">Naive (Last Value) Benchmark</option>
                <option value="croston">Croston Intermittent Demand</option>
                <option value="ridge_lagged">Ridge Autoregressive Lagged</option>
                <option value="arima">ARIMA Autoregressive</option>
              </select>
            </div>
          )}
        </section>
      )}

      {/* 4. LOADING STATE */}
      {loading && (
        <IntelligenceStage
          currentStage="predict"
          statusMessage={`Fitting candidate time-series models (${policy === 'baseline_only' ? 'naive, seasonal naive' : 'Holt-Winters, Exp Smoothing, Moving Average, Naive'}) and running expanding-window backtesting tournament...`}
          isExecuting={true}
        />
      )}

      {/* 5. ERROR STATE WITH VERIFIED BENCHMARK RECOVERY */}
      {error && !loading && (
        <div className="card-obsidian p-6 sm:p-8 space-y-5 border-rose-900/40 bg-rose-950/20 max-w-2xl mx-auto my-6 text-center">
          <div className="w-12 h-12 rounded-2xl bg-rose-900/50 border border-rose-600/40 flex items-center justify-center text-rose-400 mx-auto">
            <AlertTriangle className="w-6 h-6" />
          </div>

          <div className="space-y-1.5 max-w-lg mx-auto">
            <h3 className="text-base font-bold text-white font-sans">
              Unable to Complete Live Predictive Query
            </h3>
            <p className="text-xs text-slate-300 font-sans leading-relaxed">
              {error}
            </p>
          </div>

          <div className="p-3.5 rounded-xl bg-void/60 border border-white/[0.08] text-left text-xs font-sans space-y-1 text-slate-400 max-w-md mx-auto">
            <p className="font-semibold text-slate-200">Recommended Next Steps:</p>
            <ul className="list-disc list-inside space-y-0.5 text-[11px]">
              <li>Verify the NEXUS backend service is reachable on port 8000.</li>
              <li>Confirm valid historical transactions exist in the active workspace.</li>
              <li>Or examine the verified illustrative benchmark to review full UI/UX functionality offline.</li>
            </ul>
          </div>

          <div className="pt-2 flex flex-wrap items-center justify-center gap-3">
            <button
              onClick={() => handleGenerateForecast(false)}
              className="btn-primary text-xs py-2 px-4"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Retry Live Connection</span>
            </button>

            <button
              onClick={() => handleGenerateForecast(true)}
              className="btn-secondary text-xs py-2 px-4 border-amber-600/40 text-amber-300 hover:text-white"
            >
              <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
              <span>Load Verified Reference Forecast (Illustrative Benchmark)</span>
            </button>
          </div>
        </div>
      )}

      {/* 6. INSUFFICIENT DATA GUARD */}
      {isInsufficient && !loading && (
        <div className="card-obsidian p-8 text-center space-y-5 border-cyan-800/40 bg-cyan-950/20 max-w-xl mx-auto my-6">
          <div className="w-12 h-12 rounded-2xl bg-cyan-900/60 border border-cyan-700/60 flex items-center justify-center text-cyan-400 mx-auto">
            <ShieldAlert className="w-6 h-6" />
          </div>

          <div className="max-w-md mx-auto space-y-2">
            <h2 className="text-base font-bold text-white font-sans">
              Forecasts will appear once NEXUS has enough historical telemetry
            </h2>
            <p className="text-xs text-slate-300 leading-relaxed font-sans">
              {forecast?.limitations?.[0] ||
                'The selected series requires continuous observation periods to calibrate statistically sound prediction intervals without overfitting.'}
            </p>
          </div>

          <div className="p-3.5 rounded-xl bg-void/60 border border-white/[0.08] text-left text-xs font-sans space-y-1.5 max-w-sm mx-auto">
            <span className="text-[10px] font-mono uppercase text-slate-400 font-semibold block">
              MINIMUM CRITERIA PER FREQUENCY:
            </span>
            <div className="flex items-center justify-between text-[11px] font-mono">
              <span className="text-slate-300">Monthly Series:</span>
              <span className="text-cyan-400 font-bold">&ge; 6 months</span>
            </div>
            <div className="flex items-center justify-between text-[11px] font-mono">
              <span className="text-slate-300">Weekly Series:</span>
              <span className="text-cyan-400 font-bold">&ge; 12 weeks</span>
            </div>
            <div className="flex items-center justify-between text-[11px] font-mono">
              <span className="text-slate-300">Daily Series:</span>
              <span className="text-cyan-400 font-bold">&ge; 30 days</span>
            </div>
          </div>

          <div className="pt-2 flex flex-col sm:flex-row items-center justify-center gap-2">
            <button
              onClick={() => onNavigate('/data')}
              className="btn-primary text-xs py-2 px-4 shadow-cyan-glow"
            >
              <span>Ingest Historical Data via Gateway</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
            <StatusBadge status="INSUFFICIENT_DATA" />
          </div>
        </div>
      )}

      {/* 7. VALIDATED FORECAST WORKSPACE */}
      {forecast && forecast.status === 'completed' && !loading && (
        <div className="space-y-6 animate-in fade-in duration-200">
          {/* A. 3-STAGE CHRONOLOGICAL STORY BANNER */}
          <div className="card-obsidian p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-xs font-mono overflow-x-auto">
            <div className="flex items-center gap-2 shrink-0">
              <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 shadow-[0_0_8px_rgba(6,182,212,0.8)]" />
              <span className="text-slate-400 uppercase text-[10px]">HISTORICAL BASELINE:</span>
              <span className="text-slate-200 font-semibold">
                {forecast.data_quality?.observation_count || 8} Empirical Observations
              </span>
            </div>

            <ArrowRight className="hidden sm:block w-4 h-4 text-slate-600 shrink-0" />

            <div className="flex items-center gap-2 shrink-0">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]" />
              <span className="text-slate-400 uppercase text-[10px]">OBSERVATION BOUNDARY:</span>
              <span className="text-emerald-300 font-semibold">
                {boundaryPeriod || 'Current Period'}
              </span>
            </div>

            <ArrowRight className="hidden sm:block w-4 h-4 text-slate-600 shrink-0" />

            <div className="flex items-center gap-2 shrink-0">
              <span className="w-2.5 h-2.5 rounded-full bg-violet-400 shadow-[0_0_8px_rgba(167,139,250,0.8)]" />
              <span className="text-slate-400 uppercase text-[10px]">MODEL EXPECTATION:</span>
              <span className="text-violet-300 font-semibold">
                {horizon} Steps • {(confidenceLevel * 100).toFixed(0)}% Corridor
              </span>
            </div>
          </div>

          {/* B. FORECAST QUALITY & ACCURACY SCORECARD (21st.dev Stat Pattern in Precision Obsidian) */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3.5">
            {/* Card 1: Selected Model */}
            <div className="card-obsidian p-4 sm:p-5 flex flex-col justify-between border-white/[0.08] hover:border-cyan-500/30 transition-all duration-200 min-w-0 group" title="Autonomous backtest winner selected across candidate tournament based on out-of-sample SMAPE ranking.">
              <div>
                <div className="flex items-center justify-between gap-2 mb-2.5">
                  <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-medium truncate">
                    Selected Model
                  </span>
                  <div className="w-7 h-7 rounded-lg bg-cyan-950/40 border border-cyan-800/30 flex items-center justify-center text-cyan-400 shrink-0 group-hover:border-cyan-500/40 transition-colors">
                    <Cpu className="w-3.5 h-3.5" />
                  </div>
                </div>
                <div className="space-y-1">
                  <p className="text-base sm:text-lg font-bold text-white capitalize font-sans tracking-tight truncate" title={forecast.model?.name?.replace(/_/g, ' ')}>
                    {forecast.model?.name?.replace(/_/g, ' ') || 'Statistical Model'}
                  </p>
                  <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-cyan-950/50 border border-cyan-800/40 text-[10px] font-mono text-cyan-300">
                    <span>v{forecast.model?.version || '1.0'}</span>
                    <span className="text-slate-600">•</span>
                    <span className="truncate max-w-[130px]">
                      {forecast.model?.is_baseline ? 'Baseline Benchmark' : 'Statistical Model'}
                    </span>
                  </div>
                </div>
              </div>
              <div className="mt-3 pt-2.5 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-slate-400 font-sans">
                <span className="truncate" title="Autonomous backtest winner selected across candidate models">Autonomous backtest winner</span>
              </div>
            </div>

            {/* Card 2: Backtest MAE */}
            <div className="card-obsidian p-4 sm:p-5 flex flex-col justify-between border-white/[0.08] hover:border-slate-400/30 transition-all duration-200 min-w-0 group" title="Mean Absolute Error measures average nominal deviation between forecasted values and actual observations across backtesting horizons.">
              <div>
                <div className="flex items-center justify-between gap-2 mb-2.5">
                  <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-medium truncate">
                    Backtest MAE
                  </span>
                  <div className="w-7 h-7 rounded-lg bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-slate-300 shrink-0 group-hover:border-white/[0.14] transition-colors">
                    <Calculator className="w-3.5 h-3.5" />
                  </div>
                </div>
                <div className="space-y-1">
                  <p className="text-xl sm:text-2xl font-bold text-white font-mono tabular-nums tracking-tight">
                    {forecast.evaluation?.mae !== undefined ? formatMetricValue(forecast.evaluation.mae, true) : '—'}
                  </p>
                  <span className="text-[10px] font-mono text-slate-400 block truncate">
                    Nominal Error ({isCurrencyMetric ? 'USD $' : metric.toUpperCase()})
                  </span>
                </div>
              </div>
              <div className="mt-3 pt-2.5 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-slate-400 font-sans">
                <span className="truncate" title="Mean Absolute Error: average nominal deviation across out-of-sample steps">Mean absolute step error</span>
              </div>
            </div>

            {/* Card 3: Backtest SMAPE */}
            <div className="card-obsidian p-4 sm:p-5 flex flex-col justify-between border-white/[0.08] hover:border-emerald-500/30 transition-all duration-200 min-w-0 group" title="Symmetric Mean Absolute Percentage Error (0-200%). Bounded symmetric accuracy metric evaluated strictly on out-of-sample backtest windows.">
              <div>
                <div className="flex items-center justify-between gap-2 mb-2.5">
                  <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-medium truncate">
                    Backtest SMAPE
                  </span>
                  <div className="w-7 h-7 rounded-lg bg-emerald-950/40 border border-emerald-800/30 flex items-center justify-center text-emerald-400 shrink-0 group-hover:border-emerald-500/40 transition-colors">
                    <Percent className="w-3.5 h-3.5" />
                  </div>
                </div>
                <div className="space-y-1">
                  <p className="text-xl sm:text-2xl font-bold text-emerald-400 font-mono tabular-nums tracking-tight">
                    {forecast.evaluation?.smape !== undefined
                      ? `${forecast.evaluation.smape.toFixed(1)}%`
                      : '—'}
                  </p>
                  <span className="text-[10px] font-mono text-emerald-400/80 block truncate">
                    Out-of-sample error (lower is better)
                  </span>
                </div>
              </div>
              <div className="mt-3 pt-2.5 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-slate-400 font-sans">
                <span className="truncate" title="Symmetric Mean Absolute Percentage Error (0-200% bounded scale)">Symmetric percentage error</span>
              </div>
            </div>

            {/* Card 4: Interval Spread */}
            <div className="card-obsidian p-4 sm:p-5 flex flex-col justify-between border-white/[0.08] hover:border-violet-500/30 transition-all duration-200 min-w-0 group" title={`Chronological prediction interval half-width derived under ${(confidenceLevel * 100).toFixed(0)}% coverage probability. Compounding variance reflects temporal entropy, not model error.`}>
              <div>
                <div className="flex items-center justify-between gap-2 mb-2.5">
                  <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-medium truncate">
                    Interval Spread
                  </span>
                  <div className="w-7 h-7 rounded-lg bg-violet-950/40 border border-violet-800/30 flex items-center justify-center text-violet-400 shrink-0 group-hover:border-violet-500/40 transition-colors">
                    <Sliders className="w-3.5 h-3.5" />
                  </div>
                </div>
                <div className="space-y-1">
                  <p className="text-xl sm:text-2xl font-bold text-violet-300 font-mono tabular-nums tracking-tight">
                    {avgUncertaintyWidth !== null ? `±${(avgUncertaintyWidth / 2).toFixed(1)}%` : '—'}
                  </p>
                  <span className="text-[10px] font-mono text-violet-400/90 block truncate">
                    {(confidenceLevel * 100).toFixed(0)}% Coverage Corridor
                  </span>
                </div>
              </div>
              <div className="mt-3 pt-2.5 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-slate-400 font-sans">
                <span className="truncate" title="Chronological uncertainty span under selected confidence level (not model backtest error)">Corridor span (not error)</span>
              </div>
            </div>

            {/* Card 5: Data Quality */}
            <div className="card-obsidian p-4 sm:p-5 flex flex-col justify-between border-white/[0.08] hover:border-cyan-500/30 transition-all duration-200 col-span-1 sm:col-span-2 lg:col-span-1 min-w-0 group" title="Historical data quality assessment verifies observation density, stationarity, and gap-free continuity before fitting.">
              <div>
                <div className="flex items-center justify-between gap-2 mb-2.5">
                  <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-medium truncate">
                    Data Quality
                  </span>
                  <div className="w-7 h-7 rounded-lg bg-cyan-950/40 border border-cyan-800/30 flex items-center justify-center text-cyan-400 shrink-0 group-hover:border-cyan-500/40 transition-colors">
                    <ShieldCheck className="w-3.5 h-3.5" />
                  </div>
                </div>
                <div className="space-y-1.5 pt-0.5">
                  <div>
                    <StatusBadge status={forecast.data_quality?.status || 'READY'} size="sm" />
                  </div>
                  <span className="text-xs font-mono text-slate-300 font-semibold block truncate">
                    {forecast.data_quality?.observation_count || 0} Empirical Periods
                  </span>
                </div>
              </div>
              <div className="mt-3 pt-2.5 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-slate-400 font-sans">
                <span className="truncate capitalize" title="Series health and frequency verification gate">{forecast.data_quality?.frequency || frequency} series validation</span>
              </div>
            </div>
          </div>

          {/* C. INTERACTIVE WORKSPACE (CHART / SCHEDULE TABLE TABS) */}
          <section className="card-obsidian p-4 sm:p-6 space-y-4">
            {/* View Mode & Utility Toolbar */}
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-white/[0.08] pb-4">
              <div className="flex items-center gap-3">
                <div className="flex items-center bg-void rounded-xl p-1 border border-white/[0.08]">
                  <button
                    onClick={() => setActiveTab('chart')}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                      activeTab === 'chart'
                        ? 'bg-cyan-500/20 text-cyan-300 shadow-sm border border-cyan-500/30'
                        : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    <LineChartIcon className="w-3.5 h-3.5" />
                    <span>Visual Corridor</span>
                  </button>
                  <button
                    onClick={() => setActiveTab('schedule')}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                      activeTab === 'schedule'
                        ? 'bg-cyan-500/20 text-cyan-300 shadow-sm border border-cyan-500/30'
                        : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    <TableIcon className="w-3.5 h-3.5" />
                    <span>Schedule Table</span>
                  </button>
                </div>

                {activeTab === 'chart' && (
                  <button
                    onClick={() => setShowInterval((prev) => !prev)}
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-mono transition-colors border ${
                      showInterval
                        ? 'bg-violet-950/40 border-violet-500/30 text-violet-300'
                        : 'bg-surface border-surface-elevated text-slate-400'
                    }`}
                    title="Toggle uncertainty corridor visibility"
                  >
                    {showInterval ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
                    <span>{(confidenceLevel * 100).toFixed(0)}% Corridor</span>
                  </button>
                )}
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={handleExportCSV}
                  className="btn-secondary text-xs h-8 px-3"
                  title="Export forecast schedule to CSV"
                >
                  <Download className="w-3.5 h-3.5 text-cyan-400" />
                  <span>Export CSV</span>
                </button>

                {forecast.evidence && (
                  <button
                    onClick={() => setActiveEvidence(forecast.evidence)}
                    className="btn-secondary text-xs h-8 px-3"
                    title="Open complete cryptographic proof and backtest evidence"
                  >
                    <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                    <span>Model Provenance</span>
                  </button>
                )}
              </div>
            </div>

            {/* TAB 1: VISUAL CORRIDOR CHART */}
            {activeTab === 'chart' && (
              <div className="space-y-2">
                <div className="h-72 sm:h-84 md:h-96 w-full pt-2">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart
                      data={chartData}
                      margin={{ top: 12, right: 16, left: 10, bottom: 4 }}
                    >
                      <defs>
                        <linearGradient id="forecastIntervalGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.30} />
                          <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0.06} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                      <XAxis
                        dataKey="period"
                        stroke="#64748b"
                        fontSize={11}
                        tickLine={false}
                        axisLine={{ stroke: '#334155' }}
                        interval="preserveStartEnd"
                        minTickGap={15}
                      />
                      <YAxis
                        stroke="#64748b"
                        fontSize={11}
                        tickLine={false}
                        axisLine={{ stroke: '#334155' }}
                        width={55}
                        tickFormatter={(v) => formatMetricValue(v, true)}
                      />
                      <Tooltip
                        content={({ active, payload, label }) => {
                          if (active && payload && payload.length) {
                            const pt = payload[0].payload;
                            const isBoundary = pt.period === boundaryPeriod;
                            const isPast = pt.historical !== null && !isBoundary;
                            const isProjected = pt.isForecast;

                            return (
                              <div className="card-obsidian p-3 shadow-2xl text-xs space-y-1.5 font-mono border-white/[0.12] bg-[#070A12]/95 min-w-[220px]">
                                <div className="flex items-center justify-between border-b border-white/[0.08] pb-1">
                                  <p className="font-semibold text-slate-200 font-sans">{label}</p>
                                  {isBoundary ? (
                                    <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase bg-emerald-950 text-emerald-300 border border-emerald-600/50">
                                      Observation Boundary
                                    </span>
                                  ) : isPast ? (
                                    <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase bg-cyan-950 text-cyan-400 border border-cyan-800">
                                      Empirical Actual
                                    </span>
                                  ) : (
                                    <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase bg-violet-950 text-violet-400 border border-violet-800">
                                      Projected Forecast
                                    </span>
                                  )}
                                </div>

                                {pt.historical !== null && (
                                  <div className="flex items-center justify-between text-cyan-300">
                                    <span className="text-slate-400">
                                      {isBoundary ? 'Last Observed Actual:' : 'Observed Actual:'}
                                    </span>
                                    <strong className="font-bold">{formatMetricValue(pt.historical)}</strong>
                                  </div>
                                )}

                                {isBoundary && (
                                  <p className="text-[10px] text-slate-400 font-sans italic pt-0.5 border-t border-white/[0.06]">
                                    Historical observation cutoff. Prospective projections begin at next step.
                                  </p>
                                )}

                                {isProjected && pt.forecast !== null && !isBoundary && (
                                  <div className="flex items-center justify-between text-violet-300">
                                    <span className="text-slate-400">Point Forecast:</span>
                                    <strong className="font-bold">{formatMetricValue(pt.forecast)}</strong>
                                  </div>
                                )}

                                {isProjected && pt.lower_bound !== null && pt.upper_bound !== null && !isBoundary && (
                                  <>
                                    <div className="flex items-center justify-between text-slate-300 text-[11px] pt-0.5 border-t border-white/[0.06]">
                                      <span className="text-slate-400">{(confidenceLevel * 100).toFixed(0)}% Corridor:</span>
                                      <span>
                                        {formatMetricValue(pt.lower_bound, true)} – {formatMetricValue(pt.upper_bound, true)}
                                      </span>
                                    </div>
                                    {pt.interval_width !== undefined && (
                                      <div className="flex items-center justify-between text-slate-400 text-[10px]">
                                        <span>Band Spread:</span>
                                        <span>
                                          ±{formatMetricValue(pt.interval_width / 2, true)}
                                          {pt.uncertainty_ratio ? ` (±${(pt.uncertainty_ratio * 50).toFixed(1)}%)` : ''}
                                        </span>
                                      </div>
                                    )}
                                  </>
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
                        wrapperStyle={{ paddingBottom: 12, fontSize: 11 }}
                      />

                      {/* Boundary Demarcation Line */}
                      {boundaryPeriod && (
                        <ReferenceLine
                          x={boundaryPeriod}
                          stroke="#38bdf8"
                          strokeDasharray="3 3"
                          strokeWidth={1.5}
                          label={{
                            value: 'Observation Boundary',
                            fill: '#38bdf8',
                            fontSize: 10,
                            position: 'insideTopLeft',
                            offset: 8,
                          }}
                        />
                      )}

                      {/* Shaded Uncertainty Corridor */}
                      {showInterval && (
                        <Area
                          type="monotone"
                          dataKey="interval"
                          stroke="#a78bfa"
                          strokeWidth={1}
                          strokeDasharray="2 2"
                          strokeOpacity={0.5}
                          fill="url(#forecastIntervalGradient)"
                          name={`${(confidenceLevel * 100).toFixed(0)}% Prediction Corridor`}
                        />
                      )}

                      {/* Historical Actuals Line */}
                      <Line
                        type="monotone"
                        dataKey="historical"
                        stroke="#00F2FE"
                        strokeWidth={2.5}
                        dot={{ fill: '#00F2FE', stroke: '#070A12', strokeWidth: 2, r: 3.5 }}
                        activeDot={{ r: 5, fill: '#00F2FE' }}
                        name="Historical Actuals"
                      />

                      {/* Prospective Point Forecast Line */}
                      <Line
                        type="monotone"
                        dataKey="forecast"
                        stroke="#a78bfa"
                        strokeWidth={2.5}
                        strokeDasharray="5 5"
                        dot={(props: any) => {
                          if (props.payload.period === boundaryPeriod) {
                            return (
                              <circle
                                key={`fcst-dot-${props.payload.period}`}
                                cx={props.cx}
                                cy={props.cy}
                                r={0}
                                fill="transparent"
                              />
                            );
                          }
                          return (
                            <circle
                              key={`fcst-dot-${props.payload.period}`}
                              cx={props.cx}
                              cy={props.cy}
                              r={3.5}
                              fill="#a78bfa"
                              stroke="#070A12"
                              strokeWidth={2}
                            />
                          );
                        }}
                        activeDot={{ r: 5, fill: '#a78bfa' }}
                        name="Point Forecast"
                      />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>

                <div className="flex flex-wrap items-center justify-between text-[11px] text-slate-400 pt-1 font-mono gap-2">
                  <span>
                    Solid cyan: Observed historical actuals • Dashed violet: Model projection from boundary
                  </span>
                  <div className="flex items-center gap-3">
                    {isIllustrative && (
                      <span className="text-amber-400 font-semibold">
                        [ILLUSTRATIVE BENCHMARK TELEMETRY]
                      </span>
                    )}
                    <span>
                      Prediction intervals calculated at {(confidenceLevel * 100).toFixed(0)}% coverage
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* TAB 2: SCHEDULE DATA TABLE */}
            {activeTab === 'schedule' && (
              <div className="space-y-3">
                {isIllustrative && (
                  <div className="px-3.5 py-2 rounded-lg bg-amber-950/30 border border-amber-600/40 text-amber-300 text-xs flex items-center gap-2">
                    <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                    <span>
                      <strong>Notice:</strong> Displaying benchmark reference schedule from fixture (FCST-BENCHMARK-RETAIL-01). Not live tenant telemetry.
                    </span>
                  </div>
                )}
                <div className="overflow-x-auto -mx-4 sm:mx-0">
                <table className="w-full text-left text-xs font-mono min-w-[620px]">
                  <thead>
                    <tr className="border-b border-white/[0.08] text-slate-400 text-[10px] uppercase">
                      <th className="py-2.5 px-3">Horizon Step</th>
                      <th className="py-2.5 px-3">Target Period</th>
                      <th className="py-2.5 px-3">Point Forecast</th>
                      <th className="py-2.5 px-3">{(confidenceLevel * 100).toFixed(0)}% Lower Bound</th>
                      <th className="py-2.5 px-3">{(confidenceLevel * 100).toFixed(0)}% Upper Bound</th>
                      <th className="py-2.5 px-3">Interval Spread</th>
                      <th className="py-2.5 px-3">Uncertainty Ratio</th>
                      <th className="py-2.5 px-3">Coverage</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04]">
                    {forecast.predictions?.map((p, idx) => {
                      const spread = p.upper_bound - p.lower_bound;
                      const uncert = p.point_forecast > 0 ? spread / p.point_forecast : null;
                      return (
                        <tr key={p.period} className="hover:bg-white/[0.02] transition-colors">
                          <td className="py-3 px-3 text-cyan-400 font-bold">+{idx + 1}</td>
                          <td className="py-3 px-3 text-white font-semibold">{p.period}</td>
                          <td className="py-3 px-3 text-violet-300 font-bold">
                            {formatMetricValue(p.point_forecast)}
                          </td>
                          <td className="py-3 px-3 text-slate-300">
                            {p.lower_bound !== null ? formatMetricValue(p.lower_bound) : '—'}
                          </td>
                          <td className="py-3 px-3 text-slate-300">
                            {p.upper_bound !== null ? formatMetricValue(p.upper_bound) : '—'}
                          </td>
                          <td className="py-3 px-3 text-slate-400">
                            {spread !== null ? `±${formatMetricValue(spread / 2)}` : '—'}
                          </td>
                          <td className="py-3 px-3 text-slate-300">
                            {uncert !== null ? (
                              <span
                                className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                                  uncert < 0.15
                                    ? 'bg-emerald-950/60 text-emerald-400 border border-emerald-800/40'
                                    : uncert < 0.3
                                    ? 'bg-cyan-950/60 text-cyan-400 border border-cyan-800/40'
                                    : 'bg-amber-950/60 text-amber-300 border border-amber-800/40'
                                }`}
                              >
                                {(uncert * 100).toFixed(1)}%
                              </span>
                            ) : (
                              '—'
                            )}
                          </td>
                          <td className="py-3 px-3 text-slate-400">
                            {p.confidence_level ? `${(p.confidence_level * 100).toFixed(0)}%` : `${(confidenceLevel * 100).toFixed(0)}%`}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>

          {/* D. CANDIDATE TOURNAMENT COMPARISON (WHEN CANDIDATES EVALUATED) */}
          {forecast.evidence?.candidate_evaluations &&
            Object.keys(forecast.evidence.candidate_evaluations).length > 0 && (
              <section className="card-obsidian p-4 sm:p-5 space-y-3">
                <div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
                  <div className="flex items-center gap-2">
                    <Activity className="w-4 h-4 text-cyan-400" />
                    <h2 className="text-xs font-semibold text-white uppercase font-mono tracking-wider">
                      Candidate Model Tournament Results (Expanding-Window Backtest)
                    </h2>
                  </div>
                  <span className="text-[11px] text-slate-400 font-mono">
                    Evaluation Metric: Out-of-Sample Validation Error (SMAPE / MAE)
                  </span>
                </div>

                <div className="overflow-x-auto -mx-4 sm:mx-0">
                  <table className="w-full text-left text-xs font-mono min-w-[550px]">
                    <thead>
                      <tr className="border-b border-white/[0.06] text-slate-400 text-[10px] uppercase">
                        <th className="py-2 px-3">Candidate Model</th>
                        <th className="py-2 px-3">Tournament Status</th>
                        <th className="py-2 px-3">Out-of-Sample SMAPE</th>
                        <th className="py-2 px-3">MAE</th>
                        <th className="py-2 px-3">RMSE</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/[0.03]">
                      {Object.entries(forecast.evidence.candidate_evaluations).map(([mName, metrics]) => {
                        const isWinner =
                          mName.toLowerCase() === (forecast.model?.name || '').toLowerCase() ||
                          mName.toLowerCase() === (forecast.evidence?.selected_model || '').toLowerCase();
                        return (
                          <tr
                            key={mName}
                            className={`transition-colors ${
                              isWinner ? 'bg-cyan-950/20 text-white font-semibold' : 'text-slate-300 hover:bg-white/[0.01]'
                            }`}
                          >
                            <td className="py-2.5 px-3 capitalize font-sans flex items-center gap-2">
                              {isWinner && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />}
                              <span>{mName.replace(/_/g, ' ')}</span>
                            </td>
                            <td className="py-2.5 px-3">
                              {isWinner ? (
                                <span className="px-2 py-0.5 rounded-full bg-emerald-950/70 border border-emerald-600/50 text-emerald-400 text-[10px] font-bold">
                                  WINNER (Selected)
                                </span>
                              ) : (
                                <span className="text-slate-500 text-[11px]">Benchmarked</span>
                              )}
                            </td>
                            <td className="py-2.5 px-3">
                              {metrics.smape !== undefined ? (
                                <span
                                  className={
                                    isWinner ? 'text-emerald-400 font-bold' : 'text-slate-300'
                                  }
                                >
                                  {metrics.smape.toFixed(2)}%
                                </span>
                              ) : (
                                '—'
                              )}
                            </td>
                            <td className="py-2.5 px-3 text-slate-400">
                              {metrics.mae !== undefined ? formatMetricValue(metrics.mae, true) : '—'}
                            </td>
                            <td className="py-2.5 px-3 text-slate-400">
                              {metrics.rmse !== undefined ? formatMetricValue(metrics.rmse, true) : '—'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {(forecast.evidence?.selected_model_rationale || forecast.evidence?.selection_reason) && (
                  <p className="text-[11px] text-slate-400 font-sans italic pt-1 border-t border-white/[0.04]">
                    <strong>Selection Rationale:</strong>{' '}
                    {forecast.evidence?.selected_model_rationale || forecast.evidence?.selection_reason}
                  </p>
                )}
              </section>
            )}

          {/* E. WHAT THIS MEANS, ASSUMPTIONS & LIMITATIONS */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Model Narrative / What This Means */}
            <div className="card-obsidian p-5 space-y-3 min-w-0">
              <span className="text-[10px] font-mono uppercase text-cyan-400 tracking-wider font-semibold flex items-center gap-1.5">
                <Info className="w-3.5 h-3.5" />
                <span>Executive Interpretation & Drivers</span>
              </span>

              {forecast.explanation ? (
                <div className="text-xs text-slate-300 leading-relaxed font-sans space-y-2 whitespace-pre-line">
                  {forecast.explanation}
                </div>
              ) : (
                <p className="text-xs text-slate-400 leading-relaxed font-sans">
                  Prospective forecast generated using {forecast.model?.name?.replace(/_/g, ' ') || 'the selected model'} based on historical backtesting across out-of-sample observation windows.
                </p>
              )}
            </div>

            {/* Assumptions & Boundaries */}
            <div className="card-obsidian p-5 space-y-3 border-amber-900/30 bg-amber-950/10 min-w-0">
              <span className="text-[10px] font-mono uppercase text-amber-300 tracking-wider font-semibold flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                <span>Assumptions & Honest Limitations</span>
              </span>

              <div className="space-y-2 text-xs text-slate-300 font-sans">
                {forecast.assumptions && forecast.assumptions.length > 0 && (
                  <div>
                    <span className="text-[10px] font-mono uppercase text-slate-400 font-semibold block mb-1">
                      Assumptions:
                    </span>
                    <ul className="list-disc list-inside space-y-1 text-slate-300 text-[11px] leading-relaxed">
                      {forecast.assumptions.map((asm, i) => (
                        <li key={i}>{asm}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {forecast.limitations && forecast.limitations.length > 0 && (
                  <div className="pt-2 border-t border-amber-900/40">
                    <span className="text-[10px] font-mono uppercase text-amber-400 font-semibold block mb-1">
                      Boundary Limitations:
                    </span>
                    <ul className="list-disc list-inside space-y-1 text-slate-300 text-[11px] leading-relaxed">
                      {forecast.limitations.map((lim, i) => (
                        <li key={i}>{lim}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {forecast.data_quality?.warnings && forecast.data_quality.warnings.length > 0 && (
                  <div className="pt-2 border-t border-amber-900/40">
                    <span className="text-[10px] font-mono uppercase text-amber-400 font-semibold block mb-1">
                      Data Hygiene Warnings:
                    </span>
                    <ul className="list-disc list-inside space-y-1 text-amber-200 text-[11px] leading-relaxed">
                      {forecast.data_quality.warnings.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 8. EVIDENCE MODAL (AUDIT PROVENANCE) */}
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

export default ForecastsPage;
