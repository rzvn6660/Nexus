import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Database,
  Table as TableIcon,
  AlertTriangle,
  CheckCircle2,
  UploadCloud,
  FileSpreadsheet,
  ArrowRight,
  Eye,
  FileCheck,
} from 'lucide-react';
import { getDataHealth, listTables, profileDataset, auditQuality } from '../services/data';
import {
  uploadGatewayDataset,
  listGatewayDatasets,
  previewGatewayDataset,
  ingestGatewayDataset,
  GatewayDatasetDetail,
  GatewayPreviewResponse,
} from '../services/gateway';
import { DataHealthResponse, TableSummary, DatasetProfile, QualityReport } from '../types/api';
import { formatNumber } from '../utils/formatters';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { StatusBadge } from '../components/common/StatusBadge';
import { IntelligenceHeader } from '../components/intelligence/IntelligenceHeader';
import { ErrorBoundary } from '../components/common/ErrorBoundary';

export const DataPage: React.FC = () => {
  const [health, setHealth] = useState<DataHealthResponse | null>(null);
  const [tables, setTables] = useState<TableSummary[]>([]);
  const [selectedTable, setSelectedTable] = useState<string>('');
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [quality, setQuality] = useState<QualityReport | null>(null);

  // Data Gateway Ingestion States
  const [gatewayDatasets, setGatewayDatasets] = useState<GatewayDatasetDetail[]>([]);
  const [selectedGatewayDataset, setSelectedGatewayDataset] = useState<GatewayDatasetDetail | null>(null);
  const [gatewayPreview, setGatewayPreview] = useState<GatewayPreviewResponse | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [ingesting, setIngesting] = useState(false);
  const [ingestSuccess, setIngestSuccess] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [loading, setLoading] = useState(true);
  const [tableLoading, setTableLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorDetails, setErrorDetails] = useState<any>(null);

  const fetchTableDetails = useCallback(async (tableName: string) => {
    if (!tableName) return;
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

  const fetchInitialData = useCallback(async () => {
    setLoading(true);
    setError(null);
    setErrorDetails(null);
    try {
      const [hRes, tRes, gRes] = await Promise.all([
        getDataHealth(),
        listTables(),
        listGatewayDatasets().catch(() => []),
      ]);
      setHealth(hRes);
      setTables(tRes);
      setGatewayDatasets(gRes);
      if (tRes.length > 0) {
        setSelectedTable((prev) => prev || tRes[0].table_name);
      }
      if (gRes.length > 0) {
        setSelectedGatewayDataset(gRes[0]);
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to query data layer metadata.');
      setErrorDetails(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchInitialData();
  }, [fetchInitialData]);

  useEffect(() => {
    let active = true;
    if (selectedTable) {
      setTableLoading(true);
      Promise.all([
        profileDataset(selectedTable),
        auditQuality(selectedTable),
      ])
        .then(([pRes, qRes]) => {
          if (active) {
            setProfile(pRes);
            setQuality(qRes);
          }
        })
        .catch((err) => {
          if (active) {
            console.warn(`Could not load detailed audit for ${selectedTable}:`, err);
          }
        })
        .finally(() => {
          if (active) {
            setTableLoading(false);
          }
        });
    }
    return () => {
      active = false;
    };
  }, [selectedTable]);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setUploadError(null);
    setIngestSuccess(null);

    try {
      const uploaded = await uploadGatewayDataset(file);
      setSelectedGatewayDataset(uploaded);
      setGatewayDatasets((prev) => [uploaded, ...prev]);
      // Also fetch preview automatically if ID exists
      const dId = uploaded.dataset_id || uploaded.id;
      if (dId) {
        const prev = await previewGatewayDataset(dId);
        setGatewayPreview(prev);
      }
    } catch (err: any) {
      setUploadError(err?.data?.detail || err?.message || 'Failed to process file through Data Gateway.');
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handlePreviewDataset = async (datasetId?: string) => {
    if (!datasetId) return;
    try {
      const prev = await previewGatewayDataset(datasetId);
      setGatewayPreview(prev);
    } catch (err: any) {
      console.warn('Could not load dataset preview:', err);
    }
  };

  const handleIngestDataset = async () => {
    if (!selectedGatewayDataset) return;
    const dId = selectedGatewayDataset.dataset_id || selectedGatewayDataset.id;
    if (!dId) return;

    setIngesting(true);
    setUploadError(null);
    setIngestSuccess(null);

    const targetEntity =
      selectedGatewayDataset.target_entity ||
      selectedGatewayDataset.mapping_proposal?.target_entity ||
      'Sale';

    try {
      const res = await ingestGatewayDataset(dId, targetEntity);
      const entityName = res.target_entity || res.entity || targetEntity;
      setIngestSuccess(`Successfully ingested ${res.records_persisted} records into ${entityName} model.`);
      // Refresh database tables
      fetchInitialData();
    } catch (err: any) {
      setUploadError(err?.data?.detail || err?.message || 'Failed to ingest records into core model.');
    } finally {
      setIngesting(false);
    }
  };

  // Determine posture status safely
  const failedCount = quality?.failed_rules ?? quality?.checks_failed ?? 0;
  const currentPosture: 'READY' | 'READY_WITH_WARNINGS' | 'INSUFFICIENT_DATA' | 'INVALID' =
    health?.status === 'ready'
      ? failedCount > 0
        ? 'READY_WITH_WARNINGS'
        : 'READY'
      : 'INVALID';

  return (
    <ErrorBoundary fallbackTitle="Data Layer Diagnostics" onReset={fetchInitialData}>
      <div className="space-y-8 animate-in fade-in duration-200">
      {/* Header */}
      <IntelligenceHeader
        eyebrow="DATA TELEMETRY & HEALTH"
        title="Production Data Gateway & Schema Catalog"
        subtitle="Ingest raw CSV/XLSX spreadsheets, evaluate deterministic data quality, verify schema entity mappings, and monitor live PostgreSQL tables."
        icon={Database}
      />

      {loading && <LoadingState message="Loading database schema and quality metrics..." />}
      {error && <ErrorState message={error} technicalDetails={errorDetails} onRetry={fetchInitialData} />}

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
          <span className="text-[11px] text-slate-400 block">PostgreSQL relational storage</span>
        </div>

        {/* Quality Rules */}
        <div className="rounded-2xl border border-surface-elevated bg-surface/60 p-5 space-y-1">
          <span className="text-[10px] font-mono uppercase text-slate-400">QUALITY SCORECARD</span>
          <p className="text-2xl font-bold font-mono text-emerald-400">
            {quality ? `${quality.checks_passed ?? quality.passed_rules ?? 0}/${quality.checks_executed ?? quality.total_rules ?? 0} Passed` : 'Auditing...'}
          </p>
          <span className="text-[11px] text-slate-400 block">Automated rule checks</span>
        </div>
      </section>

      {/* 2. PRODUCTION DATA GATEWAY INGESTION SECTION */}
      <section className="rounded-3xl border border-cyan-800/40 bg-surface/50 p-6 space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-surface-elevated pb-4">
          <div className="space-y-1">
            <div className="inline-flex items-center gap-2 text-xs font-mono text-brand-cyan font-semibold">
              <UploadCloud className="w-4 h-4" />
              <span>NEXUS DATA GATEWAY ({gatewayDatasets.length} DATASETS)</span>
            </div>
            <h3 className="text-base font-bold text-white font-sans">
              Connect Spreadsheets & Commercial Datasets
            </h3>
            <p className="text-xs text-slate-400">
              Upload CSV or Excel files. NEXUS profiles types, audits quality, maps entities, and readies data for autonomous intelligence.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileUpload}
              accept=".csv,.xlsx"
              className="hidden"
              id="gateway-file-upload"
            />
            <label
              htmlFor="gateway-file-upload"
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-cyan-400 to-sky-400 hover:from-cyan-300 hover:to-sky-300 text-slate-950 font-semibold text-xs tracking-tight transition-all shadow-[0_0_20px_rgba(0,242,254,0.25)] cursor-pointer"
            >
              <FileSpreadsheet className="w-4 h-4" />
              <span>{uploading ? 'Processing File...' : 'Upload CSV / XLSX'}</span>
            </label>
          </div>
        </div>

        {uploadError && (
          <div className="p-3.5 rounded-xl bg-rose-950/60 border border-rose-500/30 flex items-center gap-3 text-xs text-rose-300">
            <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{uploadError}</span>
          </div>
        )}

        {ingestSuccess && (
          <div className="p-3.5 rounded-xl bg-emerald-950/60 border border-emerald-500/30 flex items-center gap-3 text-xs text-emerald-300">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{ingestSuccess}</span>
          </div>
        )}

        {/* Selected / Latest Ingested Dataset Summary */}
        {selectedGatewayDataset ? (
          <div className="rounded-2xl border border-surface-elevated bg-void/80 p-5 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-surface-elevated pb-3 text-xs">
              <div className="flex items-center gap-2">
                <FileCheck className="w-4 h-4 text-brand-cyan" />
                <span className="font-bold text-white font-mono">
                  {selectedGatewayDataset.original_filename || selectedGatewayDataset.filename || 'dataset.csv'}
                </span>
                <span className="px-2 py-0.5 rounded bg-surface border border-surface-elevated font-mono text-[10px] text-slate-400">
                  {selectedGatewayDataset.file_size_bytes
                    ? `${(selectedGatewayDataset.file_size_bytes / 1024).toFixed(1)} KB`
                    : 'Tabular file'}
                </span>
              </div>
              <div className="flex items-center gap-3 font-mono text-[11px]">
                <span className="text-slate-400">
                  Readiness: <strong className="text-brand-cyan">{selectedGatewayDataset.readiness_score ?? 70}%</strong>
                </span>
                <span className="text-slate-400">
                  Quality: <strong className="text-emerald-400">{selectedGatewayDataset.quality_score ?? 100}/100</strong>
                </span>
                <span className="text-slate-400">
                  Rows: <strong className="text-white">{selectedGatewayDataset.row_count ?? 0}</strong>
                </span>
              </div>
            </div>

            {/* Entity Mapping & Readiness Verification */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs font-mono">
              <div className="space-y-1">
                <span className="text-slate-500 text-[10px] uppercase">TARGET ENTITY</span>
                <div className="text-white font-bold">
                  {selectedGatewayDataset.target_entity ||
                    selectedGatewayDataset.mapping_proposal?.target_entity ||
                    'Core Model'}
                </div>
                <span className="text-[10px] text-slate-400 block">Unified Core Model Target</span>
              </div>
              <div className="space-y-1">
                <span className="text-slate-500 text-[10px] uppercase">READINESS POSTURE</span>
                <div className="text-brand-cyan font-bold">{selectedGatewayDataset.readiness_status || 'READY'}</div>
                <span className="text-[10px] text-slate-400 block">
                  {selectedGatewayDataset.readiness_reasons?.[0] || 'Validated for autonomous analysis'}
                </span>
              </div>
              <div className="flex items-center justify-start sm:justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => handlePreviewDataset(selectedGatewayDataset.dataset_id || selectedGatewayDataset.id)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-surface hover:bg-surface-elevated border border-surface-elevated text-slate-300 text-xs font-medium"
                >
                  <Eye className="w-3.5 h-3.5 text-brand-cyan" />
                  <span>Preview Rows</span>
                </button>
                <button
                  type="button"
                  disabled={ingesting || (selectedGatewayDataset.readiness_score ?? 70) < 70}
                  onClick={handleIngestDataset}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:bg-surface-elevated disabled:text-slate-500 text-white text-xs font-semibold shadow-md transition-all"
                >
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>{ingesting ? 'Ingesting...' : 'Ingest to Core'}</span>
                </button>
              </div>
            </div>

            {/* Schema Mappings Badges */}
            {(() => {
              const rawMappings: any[] = Array.isArray(selectedGatewayDataset.schema_mappings)
                ? selectedGatewayDataset.schema_mappings
                : selectedGatewayDataset.mapping_proposal?.field_mappings
                ? Object.entries(selectedGatewayDataset.mapping_proposal.field_mappings).map(([src, tgt]: any) => ({
                    source_column: src,
                    mapped_field: typeof tgt === 'object' ? tgt.target_field || tgt.mapped_field || JSON.stringify(tgt) : String(tgt),
                  }))
                : [];

              return (
                <div className="pt-2 border-t border-surface-elevated/60 space-y-1.5">
                  <span className="text-[10px] font-mono text-slate-500 uppercase">
                    MAPPED SCHEMA COLUMNS ({rawMappings.length}):
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {rawMappings.length > 0 ? (
                      rawMappings.map((m, idx) => (
                        <span
                          key={idx}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-surface border border-surface-elevated text-[11px] font-mono text-slate-300"
                        >
                          <span>{m.source_column || m.source || 'Column'}</span>
                          <ArrowRight className="w-3 h-3 text-cyan-400" />
                          <span className="text-emerald-400 font-semibold">{m.mapped_field || m.target || 'Field'}</span>
                        </span>
                      ))
                    ) : (
                      <span className="text-xs text-slate-500 font-mono">No direct column mappings required.</span>
                    )}
                  </div>
                </div>
              );
            })()}

            {/* Data Preview Table (if loaded) */}
            {gatewayPreview && gatewayPreview.dataset_id === (selectedGatewayDataset.dataset_id || selectedGatewayDataset.id) && (
              <div className="pt-3 border-t border-surface-elevated space-y-2">
                <div className="flex items-center justify-between text-xs font-mono text-slate-400">
                  <span>Sanitized Sample Rows ({gatewayPreview.sample_rows.length} rows previewed)</span>
                  <button
                    onClick={() => setGatewayPreview(null)}
                    className="text-slate-500 hover:text-slate-300 text-[11px]"
                  >
                    Close Preview
                  </button>
                </div>
                <div className="overflow-x-auto rounded-xl border border-surface-elevated max-h-56">
                  <table className="w-full text-left font-mono text-[11px]">
                    <thead className="bg-surface/80 text-slate-400 border-b border-surface-elevated">
                      <tr>
                        {gatewayPreview.columns.map((c) => (
                          <th key={c} className="p-2.5 whitespace-nowrap">
                            <div>{c}</div>
                            <div className="text-[9px] text-cyan-400 font-normal">
                              {gatewayPreview.inferred_types[c]}
                            </div>
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-surface-elevated text-slate-300">
                      {gatewayPreview.sample_rows.map((row, rIdx) => (
                        <tr key={rIdx} className="hover:bg-surface/40">
                          {gatewayPreview.columns.map((c) => (
                            <td key={c} className="p-2.5 whitespace-nowrap">
                              {row[c] !== null && row[c] !== undefined ? String(row[c]) : '—'}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="p-6 rounded-2xl bg-void/50 border border-surface-elevated text-center space-y-2">
            <p className="text-xs text-slate-400">
              No dataset currently uploaded through Data Gateway. Click 'Upload CSV / XLSX' above to ingest commercial records.
            </p>
          </div>
        )}
      </section>

      {/* 3. TABLE DIRECTORY & SCHEMA PROFILES */}
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
                  onClick={() => {
                    if (selectedTable === t.table_name) {
                      fetchTableDetails(t.table_name);
                    } else {
                      setSelectedTable(t.table_name);
                    }
                  }}
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
                <div className="text-right">
                  <span className="text-[10px] font-mono uppercase text-slate-500 block">
                    CARDINALITY
                  </span>
                  <span className="text-sm font-bold font-mono text-brand-cyan">
                    {formatNumber(profile?.row_count ?? (profile as any)?.total_rows ?? 0)} records
                  </span>
                </div>
              </div>

              {/* Column Schema Profile Table */}
              <div className="space-y-3">
                <span className="text-xs font-mono uppercase text-slate-400 tracking-wider font-semibold block">
                  Column Schema & Type Telemetry
                </span>
                <div className="overflow-x-auto rounded-xl border border-surface-elevated">
                  <table className="w-full text-left font-mono text-xs">
                    <thead className="bg-surface text-slate-400 border-b border-surface-elevated">
                      <tr>
                        <th className="p-3">Column</th>
                        <th className="p-3">Data Type</th>
                        <th className="p-3">Null %</th>
                        <th className="p-3">Distinct Values</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-surface-elevated text-slate-300">
                      {Object.values(profile?.columns || {}).map((c) => (
                        <tr key={c.column_name} className="hover:bg-surface/60">
                          <td className="p-3 font-semibold text-white">{c.column_name}</td>
                          <td className="p-3 text-brand-cyan">{c.data_type || (c as any).inferred_type || '—'}</td>
                          <td className="p-3">
                            <span
                              className={
                                c.null_percentage > 5
                                  ? 'text-amber-400 font-bold'
                                  : 'text-slate-400'
                              }
                            >
                              {c.null_percentage.toFixed(1)}%
                            </span>
                          </td>
                          <td className="p-3 text-slate-400">{formatNumber(c.distinct_count ?? (c as any).unique_count ?? 0)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Quality Audit Scorecard for Selected Table */}
              {quality && (
                <div className="space-y-3 pt-2">
                  <span className="text-xs font-mono uppercase text-slate-400 tracking-wider font-semibold block">
                    Automated Quality Constraints ({quality.passed_rules ?? quality.checks_passed ?? 0}/
                    {quality.total_rules ?? quality.checks_executed ?? 0} Passed)
                  </span>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
                    {(quality.rule_results || quality.checks || []).map((r: any, idx: number) => {
                      const isPassed = r.passed === true || r.status === 'passed' || r.status === 'PASSED';
                      const ruleName = r.rule_name || r.check_name || r.rule_description || `Constraint #${idx + 1}`;
                      const statusLabel = r.status ? String(r.status).toUpperCase() : isPassed ? 'PASSED' : 'FAILED';
                      return (
                        <div
                          key={idx}
                          className={`p-3 rounded-xl border flex items-center justify-between ${
                            isPassed
                              ? 'bg-emerald-950/20 border-emerald-800/40 text-emerald-300'
                              : 'bg-rose-950/20 border-rose-800/40 text-rose-300'
                          }`}
                        >
                          <div className="flex items-center gap-2 truncate">
                            {isPassed ? (
                              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                            ) : (
                              <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
                            )}
                            <span className="truncate font-sans">{ruleName}</span>
                          </div>
                          <span className="font-mono text-[10px] uppercase font-bold shrink-0">
                            {statusLabel}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  </ErrorBoundary>
);
};
