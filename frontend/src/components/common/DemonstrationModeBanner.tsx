import React from 'react';
import { Sparkles, ShieldAlert, ArrowRight } from 'lucide-react';

interface DemonstrationModeBannerProps {
  reasonCode?: string | null;
  explanation?: string | null;
  isActionable?: boolean;
  className?: string;
  onInspectData?: () => void;
}

export const DemonstrationModeBanner: React.FC<DemonstrationModeBannerProps> = ({
  reasonCode,
  explanation,
  isActionable = false,
  className = '',
  onInspectData,
}) => {
  const rawBizName = typeof window !== 'undefined' ? localStorage.getItem('nexus_business_name') || '' : '';
  const bizId = (typeof window !== 'undefined' ? localStorage.getItem('nexus_business_id') || '' : '').toLowerCase();
  const bizName = rawBizName.toLowerCase();
  const isSandbox = bizId.includes('sandbox') || bizName.includes('sandbox') || reasonCode === 'DEMO_SYNTHETIC';
  const isDemoOrSandbox = isSandbox || bizId.includes('demo') || bizName.includes('demo') || reasonCode === 'DEMO_SYNTHETIC';

  const isInFlight = reasonCode === 'INCOMPLETE_IN_FLIGHT_JOBS';

  // Only render if demo/sandbox business, in-flight jobs, or non-actionable diagnostic mode
  if (!isDemoOrSandbox && !isInFlight && isActionable) {
    return null;
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className={`rounded-xl border p-4 shadow-xs transition-all ${
        isInFlight
          ? 'bg-amber-50 dark:bg-amber-950/40 border-amber-300 dark:border-amber-800 text-amber-900 dark:text-amber-200'
          : 'bg-indigo-50/70 dark:bg-indigo-950/30 border-indigo-200 dark:border-indigo-800 text-slate-800 dark:text-slate-200'
      } ${className}`}
    >
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-start gap-3">
          <div
            className={`p-2 rounded-lg shrink-0 mt-0.5 ${
              isInFlight
                ? 'bg-amber-100 dark:bg-amber-900/60 text-amber-600 dark:text-amber-400'
                : 'bg-indigo-100 dark:bg-indigo-900/60 text-indigo-600 dark:text-indigo-400'
            }`}
          >
            {isInFlight ? <ShieldAlert className="w-4 h-4" /> : <Sparkles className="w-4 h-4" />}
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-bold uppercase tracking-wider font-mono">
                {isInFlight
                  ? 'In-Flight Ingestion Telemetry'
                  : isSandbox
                  ? 'Controlled Sandbox Merchant Active'
                  : 'Demonstration Workspace Active'}
              </span>
              <span
                className={`px-2 py-0.5 text-[10px] font-mono font-semibold rounded-full border ${
                  isInFlight
                    ? 'bg-amber-200/50 dark:bg-amber-900/40 border-amber-400 dark:border-amber-700 text-amber-900 dark:text-amber-300'
                    : isSandbox
                    ? 'bg-emerald-200/50 dark:bg-emerald-900/40 border-emerald-300 dark:border-emerald-700 text-emerald-900 dark:text-emerald-300'
                    : 'bg-indigo-200/50 dark:bg-indigo-900/40 border-indigo-300 dark:border-indigo-700 text-indigo-900 dark:text-indigo-300'
                }`}
              >
                {reasonCode || (isSandbox ? 'SANDBOX_VALIDATION' : 'DIAGNOSTIC_ONLY')}
              </span>
            </div>
            <p className="text-xs text-slate-600 dark:text-slate-300 mt-1 leading-relaxed">
              {explanation ||
                (isInFlight
                  ? 'Background connector extraction is in-flight. Metric totals reflect verified historical intervals; pending ledger synchronizations are isolated until audit confirmation.'
                  : isSandbox
                  ? `${rawBizName || 'Northstar Fashion & Retail — NEXUS Sandbox'} operates under controlled synthetic validation. Customer cadences, 12-month histories, and seasonal sales curves are deterministically generated.`
                  : `Operating in demonstration workspace${rawBizName ? ` (${rawBizName})` : ''}. Metric totals and models reflect deterministic test datasets without external billing impact.`)}
            </p>
            {isSandbox && !explanation && (
              <div className="mt-2 grid grid-cols-1 md:grid-cols-3 gap-2 text-[11px] font-mono border-t border-indigo-200/60 dark:border-indigo-800/60 pt-2">
                <div className="flex items-start gap-1 text-slate-700 dark:text-slate-300">
                  <span className="font-bold text-amber-600 dark:text-amber-400">SYNTHETIC:</span>
                  <span>Customers, 12-mo history, seasonal spikes, unit costs (estimated margin).</span>
                </div>
                <div className="flex items-start gap-1 text-slate-700 dark:text-slate-300">
                  <span className="font-bold text-emerald-600 dark:text-emerald-400">VERIFIED:</span>
                  <span>Order invariants, schema mapping, atomic rollback, tenant isolation.</span>
                </div>
                <div className="flex items-start gap-1 text-slate-700 dark:text-slate-300">
                  <span className="font-bold text-rose-600 dark:text-rose-400">UNAVAILABLE:</span>
                  <span>Legal merchant consent, live bank settlement, signed period close.</span>
                </div>
              </div>
            )}
          </div>
        </div>

        {onInspectData && (
          <button
            onClick={onInspectData}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-surface-border bg-surface hover:bg-surface-elevated text-slate-700 dark:text-slate-300 transition-colors shrink-0 self-start sm:self-center"
          >
            <span>Data Provenance</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    </div>
  );
};
