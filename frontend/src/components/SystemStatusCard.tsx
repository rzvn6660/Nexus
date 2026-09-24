import React from 'react';
import { HealthResponse } from '../types/api';
import { RefreshCw, Database, Server, CheckCircle2, AlertTriangle, Clock } from 'lucide-react';

interface SystemStatusCardProps {
  health: HealthResponse | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}

export const SystemStatusCard: React.FC<SystemStatusCardProps> = ({
  health,
  loading,
  error,
  onRefresh,
}) => {
  return (
    <div className="glass-panel rounded-2xl p-6 relative overflow-hidden">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">
            <Server className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-white">System Runtime & Diagnostics</h3>
            <p className="text-xs text-slate-400">Live health telemetry from FastAPI backend</p>
          </div>
        </div>

        <button
          onClick={onRefresh}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-300 hover:text-white bg-slate-800/80 hover:bg-slate-700/80 border border-slate-700 rounded-lg transition-all disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
        </button>
      </div>

      {error ? (
        <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold text-rose-200">Unable to reach NEXUS backend API</p>
            <p className="mt-1 text-rose-300/80">{error}</p>
            <p className="mt-2 text-slate-400 font-mono">
              Expected at: http://localhost:8000/api/health
            </p>
          </div>
        </div>
      ) : health ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800">
            <span className="text-xs text-slate-400 block mb-1">Service Status</span>
            <div className="flex items-center gap-1.5">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span className="text-sm font-semibold capitalize text-emerald-400">
                {health.status}
              </span>
            </div>
            <span className="text-[11px] font-mono text-slate-400 mt-1 block">
              id: {health.service}
            </span>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800">
            <span className="text-xs text-slate-400 block mb-1">Database Engine</span>
            <div className="flex items-center gap-1.5">
              <Database
                className={`w-4 h-4 ${
                  health.database?.status === 'connected' ? 'text-cyan-400' : 'text-amber-400'
                }`}
              />
              <span
                className={`text-sm font-semibold capitalize ${
                  health.database?.status === 'connected' ? 'text-cyan-400' : 'text-amber-400'
                }`}
              >
                {health.database?.status || 'unconfigured'}
              </span>
            </div>
            <span className="text-[11px] font-mono text-slate-400 mt-1 block">
              {health.database?.latency_ms ? `${health.database.latency_ms}ms latency` : 'standby'}
            </span>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800">
            <span className="text-xs text-slate-400 block mb-1">Environment</span>
            <div className="text-sm font-semibold text-slate-200 capitalize">
              {health.environment}
            </div>
            <span className="text-[11px] font-mono text-slate-400 mt-1 block">
              version: v{health.version}
            </span>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800">
            <span className="text-xs text-slate-400 block mb-1">Last Telemetry</span>
            <div className="flex items-center gap-1 text-sm font-medium text-slate-300">
              <Clock className="w-3.5 h-3.5 text-slate-400" />
              <span>{new Date(health.timestamp).toLocaleTimeString()}</span>
            </div>
            <span className="text-[11px] font-mono text-slate-400 mt-1 block truncate">
              UTC ISO-8601
            </span>
          </div>
        </div>
      ) : (
        <div className="h-24 flex items-center justify-center text-xs text-slate-400">
          Probing health endpoint...
        </div>
      )}
    </div>
  );
};
