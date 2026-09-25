import React, { useState, useEffect, useCallback } from 'react';
import {
  Database,
  Table as TableIcon,
  ShieldCheck,
  ChevronRight,
} from 'lucide-react';
import { getDataHealth, listTables, profileDataset, auditQuality } from '../services/data';
import { DataHealthResponse, TableSummary, DatasetProfile, QualityReport } from '../types/api';
import { formatNumber } from '../utils/formatters';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { StatusBadge } from '../components/common/StatusBadge';

export const DataPage: React.FC = () => {
  const [health, setHealth] = useState<DataHealthResponse | null>(null);
  const [tables, setTables] = useState<TableSummary[]>([]);
  const [selectedTable, setSelectedTable] = useState<string>('sales');
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [quality, setQuality] = useState<QualityReport | null>(null);

  const [loading, setLoading] = useState(true);
  const [tableLoading, setTableLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchInitialData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [hRes, tRes] = await Promise.all([getDataHealth(), listTables()]);
      setHealth(hRes);
      setTables(tRes);
      if (tRes.length > 0) {
        setSelectedTable(tRes[0].table_name);
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to query data layer metadata.');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchTableDetails = useCallback(async (tableName: string) => {
    setTableLoading(true);
    try {
      const [pRes, qRes] = await Promise.all([
        profileDataset(tableName),
        auditQuality(tableName),
      ]);
      setProfile(pRes);
      setQuality(qRes);
    } catch (err: any) {
      console.warn(`Could not load detailed audit for ${tableName}:`, err);
    } finally {
      setTableLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchInitialData();
  }, [fetchInitialData]);

  useEffect(() => {
    if (selectedTable) {
      fetchTableDetails(selectedTable);
    }
  }, [selectedTable, fetchTableDetails]);

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* Header Banner */}
      <section className="rounded-3xl border border-slate-800 bg-slate-900/80 p-6 sm:p-8 space-y-3">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-950/80 border border-cyan-800/80 text-cyan-400 text-xs font-mono font-medium">
          <Database className="w-3.5 h-3.5" />
          <span>Data Layer Architecture</span>
        </div>
        <h2 className="text-2xl sm:text-3xl font-bold text-white tracking-tight">
          Dataset Health, Schema & Quality Catalog
        </h2>
        <p className="text-xs sm:text-sm text-slate-400 max-w-2xl">
          Inspection of relational database tables, record cardinality, distribution profiles,
          and automated business rule verification scorecards.
        </p>
      </section>

      {loading && <LoadingState message="Loading database schema and quality metrics..." />}
      {error && <ErrorState message={error} onRetry={fetchInitialData} />}

      {/* Dataset Health Overview Stats */}
      {health && (
        <section className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 space-y-2">
            <span className="text-xs font-mono uppercase text-slate-400">Total Registered Records</span>
            <p className="text-2xl font-bold font-mono text-cyan-400">
              {formatNumber(health.total_records)}
            </p>
            <span className="text-[11px] text-slate-400 block">Across all domain models</span>
          </div>

          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 space-y-2">
            <span className="text-xs font-mono uppercase text-slate-400">Database Tables</span>
            <p className="text-2xl font-bold font-mono text-white">
              {health.tables?.length ?? 0} Tables
            </p>
            <span className="text-[11px] text-slate-400 block">PostgreSQL 16 relational storage</span>
          </div>

          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 space-y-2">
            <span className="text-xs font-mono uppercase text-slate-400">Data Layer Status</span>
            <div className="pt-1">
              <StatusBadge status={health.status === 'ready' ? 'READY' : 'DEGRADED'} />
            </div>
            <span className="text-[11px] text-slate-400 block pt-1">Automated profiling active</span>
          </div>
        </section>
      )}

      {/* Table Catalog & Selected Profile Detail */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Table Directory */}
        <section className="rounded-3xl border border-slate-800 bg-slate-900/60 p-5 space-y-3">
          <h3 className="text-sm font-semibold text-white px-2 flex items-center gap-2">
            <TableIcon className="w-4 h-4 text-cyan-400" />
            <span>Database Tables</span>
          </h3>

          <div className="space-y-1.5">
            {tables.map((t) => (
              <button
                key={t.table_name}
                onClick={() => setSelectedTable(t.table_name)}
                className={`w-full flex items-center justify-between p-3 rounded-2xl text-xs transition-all text-left ${
                  selectedTable === t.table_name
                    ? 'bg-cyan-950/80 border border-cyan-800/80 text-cyan-300 font-semibold shadow-sm'
                    : 'bg-slate-950/40 border border-slate-800/80 text-slate-300 hover:bg-slate-800'
                }`}
              >
                <div>
                  <span className="font-mono font-bold block">{t.table_name}</span>
                  <span className="text-[11px] text-slate-400 font-mono">
                    {formatNumber(t.row_count)} rows • {t.column_count} columns
                  </span>
                </div>
                <ChevronRight className="w-4 h-4 text-slate-400" />
              </button>
            ))}
          </div>
        </section>

        {/* Right: Table Detailed Profile & Quality Scorecard */}
        <div className="lg:col-span-2 space-y-6">
          {tableLoading ? (
            <LoadingState message={`Profiling table ${selectedTable}...`} />
          ) : (
            <>
              {/* Quality Audit Scorecard */}
              {quality && (
                <section className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
                  <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                    <div>
                      <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                        <ShieldCheck className="w-4 h-4 text-emerald-400" />
                        <span>Quality Scorecard: {quality.dataset}</span>
                      </h3>
                      <p className="text-xs text-slate-400 mt-0.5">
                        Deterministic referential and boundary rule verification.
                      </p>
                    </div>

                    <StatusBadge status={quality.overall_status.toUpperCase()} />
                  </div>

                  <div className="space-y-2">
                    {quality.rule_results?.map((r) => (
                      <div
                        key={r.rule_id}
                        className="flex items-start justify-between p-3 rounded-xl bg-slate-950/60 border border-slate-800 text-xs gap-3"
                      >
                        <div className="space-y-0.5">
                          <span className="font-semibold text-slate-200">{r.rule_name}</span>
                          <p className="text-slate-400 text-[11px]">{r.message}</p>
                        </div>
                        <span
                          className={`font-mono px-2 py-0.5 rounded text-[10px] uppercase shrink-0 ${
                            r.status === 'passed'
                              ? 'bg-emerald-950/80 text-emerald-300 border border-emerald-800/80'
                              : 'bg-rose-950/80 text-rose-300 border border-rose-800/80'
                          }`}
                        >
                          {r.status}
                        </span>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Column Profiling Breakdown */}
              {profile?.columns && (
                <section className="rounded-3xl border border-slate-800 bg-slate-900/60 p-6 space-y-4">
                  <h3 className="text-sm font-semibold text-white">
                    Column Attribute Profile ({Object.keys(profile.columns).length} columns)
                  </h3>

                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs font-mono">
                      <thead>
                        <tr className="border-b border-slate-800 text-slate-400 text-[11px]">
                          <th className="py-2.5 px-3">Column Name</th>
                          <th className="py-2.5 px-3">Data Type</th>
                          <th className="py-2.5 px-3 text-right">Null Count</th>
                          <th className="py-2.5 px-3 text-right">Null %</th>
                          <th className="py-2.5 px-3 text-right">Distinct Count</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/60">
                        {Object.values(profile.columns).map((c) => (
                          <tr key={c.column_name} className="hover:bg-slate-800/30 transition-colors">
                            <td className="py-2.5 px-3 font-semibold text-slate-200">{c.column_name}</td>
                            <td className="py-2.5 px-3 text-cyan-400">{c.data_type}</td>
                            <td className="py-2.5 px-3 text-right text-slate-300">{formatNumber(c.null_count)}</td>
                            <td className="py-2.5 px-3 text-right text-slate-400">{c.null_percentage.toFixed(1)}%</td>
                            <td className="py-2.5 px-3 text-right text-emerald-400">{formatNumber(c.distinct_count)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
