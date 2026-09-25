import React, { useState, useEffect, useCallback } from 'react';
import {
  Database,
  Table as TableIcon,
  AlertTriangle,
  CheckCircle2,
} from 'lucide-react';
import { getDataHealth, listTables, profileDataset, auditQuality } from '../services/data';
import { DataHealthResponse, TableSummary, DatasetProfile, QualityReport } from '../types/api';
import { formatNumber } from '../utils/formatters';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { StatusBadge } from '../components/common/StatusBadge';
import { IntelligenceHeader } from '../components/intelligence/IntelligenceHeader';

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

  // Determine posture status
  const currentPosture: 'READY' | 'READY_WITH_WARNINGS' | 'INSUFFICIENT_DATA' | 'INVALID' =
    health?.status === 'ready'
      ? (quality?.failed_rules ?? 0) > 0
        ? 'READY_WITH_WARNINGS'
        : 'READY'
      : 'INVALID';

  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* Header */}
      <IntelligenceHeader
        eyebrow="DATA TELEMETRY & HEALTH"
        title="Dataset Health, Schema & Quality Catalog"
        subtitle="NEXUS knows what it knows. Verifies schema integrity, record cardinality, and automated data quality scorecards before any analytical query executes."
        icon={Database}
      />

      {loading && <LoadingState message="Loading database schema and quality metrics..." />}
      {error && <ErrorState message={error} onRetry={fetchInitialData} />}

      {/* 1. "NEXUS KNOWS WHAT IT KNOWS" STATUS MATRIX */}
      <section className="grid grid-cols-1 sm:grid-cols-4 gap-4">
        {/* Current Posture Card */}
        <div className="rounded-2xl border border-surface-elevated bg-surface/60 p-5 space-y-2">
          <span className="text-[10px] font-mono uppercase text-slate-400">DATA LAYER POSTURE</span>
          <div className="pt-1">
            <StatusBadge status={currentPosture} size="md" />
          </div>
          <span className="text-[11px] text-slate-400 block pt-1">
            {currentPosture === 'READY'
              ? 'All integrity constraints and foreign keys verified.'
              : 'Active warnings present in non-critical columns.'}
          </span>
        </div>

        {/* Total Records */}
        <div className="rounded-2xl border border-surface-elevated bg-surface/60 p-5 space-y-1">
          <span className="text-[10px] font-mono uppercase text-slate-400">TOTAL DATA COVERAGE</span>
          <p className="text-2xl font-bold font-mono text-brand-cyan">
            {formatNumber(health?.total_records ?? 0)}
          </p>
          <span className="text-[11px] text-slate-400 block">Relational enterprise records</span>
        </div>

        {/* Database Tables */}
        <div className="rounded-2xl border border-surface-elevated bg-surface/60 p-5 space-y-1">
          <span className="text-[10px] font-mono uppercase text-slate-400">ACTIVE SOURCE TABLES</span>
          <p className="text-2xl font-bold font-mono text-white">
            {health?.tables?.length ?? 0} Tables
          </p>
          <span className="text-[11px] text-slate-400 block">PostgreSQL 16 relational storage</span>
        </div>

        {/* Quality Rules */}
        <div className="rounded-2xl border border-surface-elevated bg-surface/60 p-5 space-y-1">
          <span className="text-[10px] font-mono uppercase text-slate-400">QUALITY SCORECARD</span>
          <p className="text-2xl font-bold font-mono text-emerald-400">
            {quality ? `${quality.passed_rules}/${quality.total_rules} Passed` : 'Auditing...'}
          </p>
          <span className="text-[11px] text-slate-400 block">Automated rule checks</span>
        </div>
      </section>

      {/* 2. TABLE DIRECTORY & SCHEMA PROFILES */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Table Directory */}
        <div className="rounded-3xl border border-surface-elevated bg-surface/50 p-5 space-y-3">
          <span className="text-xs font-mono uppercase text-slate-400 tracking-wider font-semibold block px-1">
            Database Catalog ({tables.length})
          </span>

          <div className="space-y-1.5">
            {tables.map((t) => {
              const isSelected = selectedTable === t.table_name;
              return (
                <button
                  key={t.table_name}
                  onClick={() => setSelectedTable(t.table_name)}
                  className={`w-full text-left p-3 rounded-xl border transition-all flex items-center justify-between text-xs ${
                    isSelected
                      ? 'bg-cyan-950/70 border-brand-cyan/60 text-white font-semibold'
                      : 'bg-surface/50 border-surface-elevated text-slate-300 hover:bg-surface'
                  }`}
                >
                  <div className="flex items-center gap-2.5 truncate">
                    <TableIcon className={`w-4 h-4 ${isSelected ? 'text-brand-cyan' : 'text-slate-500'}`} />
                    <span className="truncate">{t.table_name}</span>
                  </div>
                  <span className="font-mono text-[11px] text-slate-400">
                    {formatNumber(t.row_count)} rows
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Selected Table Inspection & Profile */}
        <div className="lg:col-span-2 rounded-3xl border border-surface-elevated bg-surface/50 p-6 space-y-5">
          {tableLoading ? (
            <LoadingState message={`Profiling table ${selectedTable}...`} />
          ) : (
            <>
              <div className="flex items-center justify-between border-b border-surface-elevated pb-4">
                <div>
                  <span className="text-[10px] font-mono uppercase text-brand-cyan tracking-wider font-semibold">
                    Table Profile
                  </span>
                  <h3 className="text-lg font-bold text-white font-mono mt-0.5">
                    {selectedTable}
                  </h3>
                </div>

                <div className="text-xs font-mono text-slate-400">
                  <span>{formatNumber(profile?.row_count ?? 0)} records • {profile?.column_count ?? (profile?.columns ? Object.keys(profile.columns).length : 0)} columns</span>
                </div>
              </div>

              {/* Column Schema Grid */}
              <div className="space-y-2">
                <span className="text-xs font-semibold text-slate-300 font-sans block">
                  Column Definitions & Nullability
                </span>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-surface-elevated text-slate-400 font-mono">
                        <th className="pb-2">Column Name</th>
                        <th className="pb-2">Type</th>
                        <th className="pb-2">Null Count</th>
                        <th className="pb-2 text-right">Distinct Values</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-surface-elevated font-mono">
                      {profile?.columns && Object.values(profile.columns).map((col, idx) => (
                        <tr key={idx} className="hover:bg-surface/60 transition-colors">
                          <td className="py-2 text-slate-200 font-semibold">{col.column_name}</td>
                          <td className="py-2 text-brand-cyan text-[11px]">{col.data_type}</td>
                          <td className="py-2 text-slate-400">{col.null_count} ({col.null_percentage}%)</td>
                          <td className="py-2 text-right text-slate-300">{col.distinct_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Quality Audit Scorecard for Selected Table */}
              {quality && (
                <div className="space-y-3 pt-3 border-t border-surface-elevated">
                  <span className="text-xs font-semibold text-slate-300 font-sans block">
                    Automated Quality Rules Execution
                  </span>

                  <div className="space-y-2">
                    {quality.rule_results?.map((rule, idx) => (
                      <div
                        key={idx}
                        className="p-3 rounded-xl bg-void/60 border border-surface-elevated flex items-center justify-between text-xs"
                      >
                        <div className="flex items-center gap-2">
                          {rule.status === 'passed' ? (
                            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                          ) : (
                            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
                          )}
                          <span className="font-semibold text-slate-200 font-sans">{rule.rule_name}</span>
                        </div>
                        <span className="font-mono text-slate-400 text-[11px]">{rule.message}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
