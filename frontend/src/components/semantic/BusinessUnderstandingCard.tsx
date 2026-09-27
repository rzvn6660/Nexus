import React, { useState, useEffect, useCallback } from 'react';
import {
  Brain,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Database,
  Calendar,
  Layers,
  ShieldAlert,
} from 'lucide-react';
import {
  getBusinessUnderstanding,
  activateBusinessUnderstanding,
} from '../../services/semantic';
import { BusinessUnderstandingResponse } from '../../types/api';

interface BusinessUnderstandingCardProps {
  businessId?: string;
  onActivated?: () => void;
}

export const BusinessUnderstandingCard: React.FC<BusinessUnderstandingCardProps> = ({
  businessId,
  onActivated,
}) => {
  const [data, setData] = useState<BusinessUnderstandingResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [activating, setActivating] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchUnderstanding = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getBusinessUnderstanding(businessId);
      setData(res);
    } catch (err: any) {
      setError(err?.message || 'Failed to load business understanding.');
    } finally {
      setLoading(false);
    }
  }, [businessId]);

  useEffect(() => {
    fetchUnderstanding();
  }, [fetchUnderstanding]);

  const handleActivate = async () => {
    setActivating(true);
    try {
      const res = await activateBusinessUnderstanding({ force_refresh: true }, businessId);
      setData(res.understanding);
      if (onActivated) onActivated();
    } catch (err: any) {
      setError(err?.message || 'Failed to refresh semantic understanding.');
    } finally {
      setActivating(false);
    }
  };

  if (loading && !data) {
    return (
      <div className="glass-panel rounded-2xl p-6 border border-surface-elevated animate-pulse flex items-center justify-between">
        <div className="space-y-2">
          <div className="h-4 w-48 bg-slate-800 rounded"></div>
          <div className="h-3 w-64 bg-slate-800/60 rounded"></div>
        </div>
        <RefreshCw className="w-5 h-5 text-slate-600 animate-spin" />
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="glass-panel rounded-2xl p-6 border border-rose-900/40 bg-rose-950/20 text-rose-300 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 text-rose-400" />
          <div>
            <p className="font-semibold text-rose-200">Unable to load Business Understanding</p>
            <p className="text-xs text-rose-400/80">{error}</p>
          </div>
        </div>
        <button
          onClick={fetchUnderstanding}
          className="px-3 py-1.5 rounded-lg bg-rose-900/60 hover:bg-rose-800 text-xs font-semibold text-white transition-all"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  const isReview = data.status === 'REQUIRES_REVIEW' || data.has_conflicts;
  const isReady = data.status === 'ACTIVE';

  return (
    <div className="glass-panel rounded-3xl p-6 sm:p-7 border border-surface-elevated bg-surface/50 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-surface-elevated pb-5">
        <div className="flex items-start gap-3.5">
          <div className="p-2.5 rounded-2xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 shrink-0">
            <Brain className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-lg font-bold text-white tracking-tight">
                Business Understanding & Semantic Layer
              </h3>
              <span
                className={`text-[11px] font-mono px-2.5 py-0.5 rounded-full border uppercase font-semibold ${
                  isReview
                    ? 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                    : isReady
                    ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                    : 'bg-slate-800 border-slate-700 text-slate-400'
                }`}
              >
                {data.status} • Revision v{data.version}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Deterministic semantic intelligence mapping your uploaded datasets to governed entities, metric availability, and formulas.
            </p>
          </div>
        </div>

        <button
          onClick={handleActivate}
          disabled={activating}
          className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-medium transition-all shadow-sm disabled:opacity-50 shrink-0 self-start sm:self-center"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${activating ? 'animate-spin' : ''}`} />
          <span>{activating ? 'Rebuilding Understanding...' : 'Refresh Semantic Model'}</span>
        </button>
      </div>

      {/* Conflicts Alert Banner */}
      {isReview && data.conflicts && data.conflicts.length > 0 && (
        <div className="p-4 rounded-2xl bg-amber-950/40 border border-amber-800/60 text-xs text-amber-200 flex items-start gap-3">
          <ShieldAlert className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="font-semibold text-amber-100">
              Semantic Revision Notice — Requires Operator Review
            </p>
            {data.conflicts.map((c, idx) => (
              <p key={idx} className="text-amber-300/80">
                • {c.message || JSON.stringify(c)}
              </p>
            ))}
          </div>
        </div>
      )}

      {/* Grid: Entities & Data Coverage */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        {/* Discovered Entities */}
        <div className="p-4 rounded-2xl bg-void/60 border border-surface-elevated space-y-3">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="font-semibold text-slate-300 flex items-center gap-1.5">
              <Database className="w-4 h-4 text-cyan-400" /> Discovered Entities
            </span>
            <span className="font-mono text-[11px]">{Object.keys(data.entities).length} Active</span>
          </div>
          <div className="space-y-2 text-xs">
            {['Sale', 'Customer', 'Product', 'Inventory', 'Expense', 'SaleItem'].map((ent) => {
              const info = data.entities[ent];
              return (
                <div
                  key={ent}
                  className="flex items-center justify-between p-2 rounded-xl bg-surface/40 border border-surface-highlight/30"
                >
                  <div className="flex items-center gap-2">
                    {info ? (
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                    ) : (
                      <div className="w-3.5 h-3.5 rounded-full border border-slate-700" />
                    )}
                    <span className={info ? 'text-slate-200 font-medium' : 'text-slate-500'}>
                      {ent}
                    </span>
                  </div>
                  <span className="font-mono text-[11px] text-slate-400">
                    {info ? `${info.record_count.toLocaleString()} rows` : 'None'}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Date & Temporal Coverage */}
        <div className="p-4 rounded-2xl bg-void/60 border border-surface-elevated space-y-3">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="font-semibold text-slate-300 flex items-center gap-1.5">
              <Calendar className="w-4 h-4 text-cyan-400" /> Temporal Coverage
            </span>
            <span className="font-mono text-[11px]">Sales Horizon</span>
          </div>
          <div className="p-3.5 rounded-xl bg-surface/40 border border-surface-highlight/30 space-y-2 text-xs">
            <div className="flex justify-between">
              <span className="text-slate-400">Earliest Transaction:</span>
              <span className="font-mono text-slate-200">
                {data.summary.sales_date_start || 'No records'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Latest Transaction:</span>
              <span className="font-mono text-slate-200">
                {data.summary.sales_date_end || 'No records'}
              </span>
            </div>
            <div className="flex justify-between pt-1 border-t border-surface-highlight/30">
              <span className="text-slate-400">Total Transactions:</span>
              <span className="font-mono text-emerald-400 font-bold">
                {data.summary.sales_count.toLocaleString()}
              </span>
            </div>
          </div>

          {/* Slicing Dimensions */}
          <div className="pt-2">
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">
              Slicing Dimensions
            </span>
            <div className="flex flex-wrap gap-1.5">
              {Object.keys(data.dimensions).map((dimKey) => (
                <span
                  key={dimKey}
                  className="px-2 py-0.5 rounded-lg bg-slate-800/80 border border-slate-700 text-slate-300 text-[11px] font-mono"
                >
                  {dimKey}
                </span>
              ))}
            </div>
          </div>
        </div>

        {/* Governed Metric Availability */}
        <div className="p-4 rounded-2xl bg-void/60 border border-surface-elevated space-y-3">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="font-semibold text-slate-300 flex items-center gap-1.5">
              <Layers className="w-4 h-4 text-cyan-400" /> Metric Availability
            </span>
            <span className="font-mono text-[11px]">
              {Object.values(data.metrics).filter((m) => m.status === 'AVAILABLE').length}/
              {Object.keys(data.metrics).length} Ready
            </span>
          </div>

          <div className="space-y-1.5 max-h-56 overflow-y-auto pr-1 text-xs">
            {Object.values(data.metrics).map((m) => {
              const isAvail = m.status === 'AVAILABLE';
              const isCost = m.status === 'REQUIRES_COST_DATA';
              const isHistory = m.status === 'INSUFFICIENT_HISTORY';

              return (
                <div
                  key={m.canonical_name}
                  className="p-2 rounded-xl bg-surface/40 border border-surface-highlight/20 flex items-center justify-between gap-2"
                >
                  <div className="truncate">
                    <span className="font-medium text-slate-200 block truncate">
                      {m.display_name}
                    </span>
                    <span className="font-mono text-[10px] text-slate-500 truncate block">
                      {m.calculation_formula}
                    </span>
                  </div>

                  <span
                    className={`text-[10px] font-mono px-2 py-0.5 rounded-md border font-semibold shrink-0 ${
                      isAvail
                        ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                        : isCost
                        ? 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                        : isHistory
                        ? 'bg-blue-500/10 border-blue-500/30 text-blue-300'
                        : 'bg-slate-800 border-slate-700 text-slate-400'
                    }`}
                  >
                    {isAvail ? 'AVAILABLE' : isCost ? 'NEEDS COST' : isHistory ? '< 90 DAYS' : 'UNAVAILABLE'}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Warnings & Diagnostic Guidance */}
      {data.summary.warnings && data.summary.warnings.length > 0 && (
        <div className="p-3.5 rounded-2xl bg-slate-900/60 border border-amber-900/30 space-y-1 text-xs">
          <span className="text-[11px] font-semibold text-amber-400 flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5" /> Semantic Audit Warnings:
          </span>
          <ul className="list-disc pl-5 space-y-0.5 text-slate-300 text-[11px]">
            {data.summary.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};
