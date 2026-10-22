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
  RefreshCw,
  Search,
  X,
  Layers,
  ShieldCheck,
  Clock,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  Activity,
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
import { StatusBadge } from '../components/common/StatusBadge';
import { ErrorBoundary } from '../components/common/ErrorBoundary';

const CANONICAL_MODELS = [
  { name: 'sales', entity: 'Sale', description: 'Commercial transactions, revenue ledger & gross margins' },
  { name: 'customers', entity: 'Customer', description: 'Client identities, accounts & lifetime retention value' },
  { name: 'products', entity: 'Product', description: 'SKU catalog, pricing, categories & inventory units' },
  { name: 'sale_items', entity: 'SaleItem', description: 'Itemized transaction records & quantity metrics' },
  { name: 'inventory', entity: 'Inventory', description: 'Warehouse stock levels, locations & reorder thresholds' },
  { name: 'expenses', entity: 'Expense', description: 'Operational overhead, supplier disbursements & COGS' },
];

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
  const [previewLoading, setPreviewLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadStep, setUploadStep] = useState<string>('');
  const [isDragging, setIsDragging] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [ingesting, setIngesting] = useState(false);
  const [ingestSuccess, setIngestSuccess] = useState<string | null>(null);
  const [tableSearch, setTableSearch] = useState('');
  const [showTechnicalDiagnostics, setShowTechnicalDiagnostics] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [loading, setLoading] = useState(true);
  const [tableLoading, setTableLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorDetails, setErrorDetails] = useState<any>(null);
  const [dbConnected, setDbConnected] = useState<boolean>(true);

  const fetchTableDetails = useCallback(async (tableName: string) => {
    if (!tableName) return;
    setTableLoading(true);
    try {
      const [pRes, qRes] = await Promise.all([
        profileDataset(tableName).catch((err) => {
          console.warn(`Profile failed for ${tableName}:`, err);
          return null;
        }),
        auditQuality(tableName).catch((err) => {
          console.warn(`Quality audit failed for ${tableName}:`, err);
          return null;
        }),
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

    let hasDbError = false;
    let fetchedTables: TableSummary[] = [];

    try {
      // Execute health check with resilient error capture
      const healthPromise = getDataHealth().catch((err) => {
        hasDbError = true;
        console.warn('getDataHealth unavailable:', err);
        return null;
      });

      // Execute tables query
      const tablesPromise = listTables().catch((err) => {
        hasDbError = true;
        console.warn('listTables unavailable:', err);
        return [] as TableSummary[];
      });

      // Execute gateway datasets query (resilient tenant isolation)
      const gatewayPromise = listGatewayDatasets().catch((err) => {
        console.warn('listGatewayDatasets unavailable:', err);
        return [] as GatewayDatasetDetail[];
      });

      const [hRes, tRes, gRes] = await Promise.all([healthPromise, tablesPromise, gatewayPromise]);

      setHealth(hRes);
      fetchedTables = tRes || [];
      setTables(fetchedTables);
      setGatewayDatasets(gRes || []);

      if (hasDbError && !hRes) {
        setDbConnected(false);
        setError('PostgreSQL relational database service is offline or unreachable.');
        setErrorDetails('Database session handshake returned 500 / Network Error. Connect Postgres service to inspect table schemas.');
      } else {
        setDbConnected(true);
      }

      if (fetchedTables.length > 0) {
        setSelectedTable((prev) => (prev && fetchedTables.some((t) => t.table_name === prev) ? prev : fetchedTables[0].table_name));
      } else if (!selectedTable) {
        setSelectedTable('sales');
      }

      if (gRes && gRes.length > 0) {
        setSelectedGatewayDataset((prev) => {
          if (!prev) return gRes[0];
          const found = gRes.find((d) => (d.dataset_id || d.id) === (prev.dataset_id || prev.id));
          return found || gRes[0];
        });
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to query data layer metadata.');
      setErrorDetails(err);
      setDbConnected(false);
    } finally {
      setLoading(false);
    }
  }, [selectedTable]);

  useEffect(() => {
    fetchInitialData();
  }, [fetchInitialData]);

  useEffect(() => {
    let active = true;
    if (selectedTable && dbConnected) {
      setTableLoading(true);
      Promise.all([
        profileDataset(selectedTable).catch(() => null),
        auditQuality(selectedTable).catch(() => null),
      ])
        .then(([pRes, qRes]) => {
          if (active) {
            setProfile(pRes);
            setQuality(qRes);
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
  }, [selectedTable, dbConnected]);

  const processFile = async (file: File) => {
    setUploading(true);
    setUploadStep('Validating file format & size...');
    setUploadError(null);
    setIngestSuccess(null);

    try {
      setUploadStep('Uploading file to tenant-isolated storage...');
      const uploaded = await uploadGatewayDataset(file);

      setUploadStep('Profiling columns and computing deterministic quality rules...');
      setSelectedGatewayDataset(uploaded);
      setGatewayDatasets((prev) => [
        uploaded,
        ...prev.filter((d) => (d.dataset_id || d.id) !== (uploaded.dataset_id || uploaded.id)),
      ]);

      const dId = uploaded.dataset_id || uploaded.id;
      if (dId) {
        setUploadStep('Fetching sanitized sample preview...');
        const prev = await previewGatewayDataset(dId);
        setGatewayPreview(prev);
      }
    } catch (err: any) {
      setUploadError(err?.data?.detail || err?.message || 'Failed to process file through Data Gateway.');
    } finally {
      setUploading(false);
      setUploadStep('');
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      processFile(file);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) {
      processFile(file);
    }
  };

  const handlePreviewDataset = async (datasetId?: string) => {
    if (!datasetId) return;
    setPreviewLoading(true);
    try {
      const prev = await previewGatewayDataset(datasetId);
      setGatewayPreview(prev);
    } catch (err: any) {
      console.warn('Could not load dataset preview:', err);
    } finally {
      setPreviewLoading(false);
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
      setIngestSuccess(
        `Successfully ingested ${formatNumber(res.records_persisted)} records into ${entityName} model.`
      );
      // Update selected dataset status locally to reflect successful completion
      setSelectedGatewayDataset((prev) =>
        prev
          ? {
              ...prev,
              ingestion_status: 'COMPLETED',
              readiness_status: 'READY',
            }
          : null
      );
      setGatewayDatasets((prev) =>
        prev.map((d) =>
          (d.dataset_id || d.id) === dId
            ? { ...d, ingestion_status: 'COMPLETED', readiness_status: 'READY' }
            : d
        )
      );
      // Refresh database tables to reflect newly persisted records
      await fetchInitialData();
    } catch (err: any) {
      setUploadError(err?.data?.detail || err?.message || 'Failed to ingest records into core model.');
    } finally {
      setIngesting(false);
    }
  };

  // Determine posture status safely from live responses
  const failedCount = quality?.failed_rules ?? quality?.checks_failed ?? 0;
  const currentPosture: 'READY' | 'READY_WITH_WARNINGS' | 'INSUFFICIENT_DATA' | 'DISCONNECTED' =
    !dbConnected
      ? 'DISCONNECTED'
      : health?.status === 'ready'
      ? failedCount > 0
        ? 'READY_WITH_WARNINGS'
        : 'READY'
      : 'INSUFFICIENT_DATA';

  const filteredTables = (tables.length > 0 ? tables : CANONICAL_MODELS.map((m) => ({
    table_name: m.name,
    row_count: 0,
    column_count: 0,
    columns: [],
  }))).filter((t) => t.table_name.toLowerCase().includes(tableSearch.toLowerCase()));

  const populatedTablesCount = tables.filter((t) => t.row_count > 0).length;
  const emptyTablesCount = Math.max(0, (health?.registered_models || CANONICAL_MODELS.length) - populatedTablesCount);

  return (
    <ErrorBoundary fallbackTitle="Data Layer Diagnostics" onReset={fetchInitialData}>
      <div className="space-y-6 animate-in fade-in duration-200">
        {/* ========================================================= */}
        {/* 1. EXECUTIVE HEADER & REAL-TIME CONNECTION TELEMETRY     */}
        {/* ========================================================= */}
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-white/[0.08] pb-5">
          <div>
            <div className="flex flex-wrap items-center gap-2 mb-2">
              <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-800/50 text-cyan-400 font-mono text-[11px] font-semibold">
                <Database className="w-3.5 h-3.5" />
                <span>DATA GATEWAY & TELEMETRY</span>
              </div>

              {/* Dynamic Connection Status Badge */}
              {loading ? (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-slate-900 border border-slate-700 text-slate-300 font-mono text-[10px]">
                  <RefreshCw className="w-3 h-3 animate-spin text-cyan-400" />
                  <span>Checking Connection...</span>
                </span>
              ) : dbConnected ? (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-emerald-950/60 border border-emerald-600/40 text-emerald-400 font-mono text-[10px] font-semibold">
                  <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                  <span>PostgreSQL Connected</span>
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-rose-950/60 border border-rose-600/40 text-rose-300 font-mono text-[10px] font-semibold">
                  <span className="w-2 h-2 rounded-full bg-rose-400" />
                  <span>PostgreSQL Offline</span>
                </span>
              )}
            </div>

            <h1 className="text-2xl font-bold text-white tracking-tight font-sans">
              Data Gateway & Database Catalog
            </h1>
            <p className="text-xs text-slate-400 mt-1 max-w-2xl font-sans">
              Profile commercial spreadsheets, audit deterministic data quality constraints, verify entity schema mappings, and inspect live PostgreSQL storage.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <button
              onClick={fetchInitialData}
              disabled={loading}
              className="btn-secondary text-xs h-9 px-3"
              title="Refresh metadata catalog and connection telemetry"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-cyan-400' : ''}`} />
              <span className="hidden sm:inline">Refresh Telemetry</span>
            </button>

            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileUpload}
              accept=".csv,.xlsx,.xls"
              className="hidden"
              id="gateway-file-upload"
            />

            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="btn-primary text-xs h-9 px-3.5 shadow-sm"
              title="Upload CSV, XLSX, or XLS spreadsheet for deterministic profiling"
            >
              <UploadCloud className="w-4 h-4" />
              <span>{uploading ? 'Processing File...' : 'Upload CSV / XLSX'}</span>
            </button>
          </div>
        </div>

        {/* ========================================================= */}
        {/* 2. CONNECTION DIAGNOSTICS & RECOVERY PANEL (IF OFFLINE)  */}
        {/* ========================================================= */}
        {(!dbConnected || error) && (
          <div className="card-obsidian border-rose-900/40 bg-rose-950/20 p-5 space-y-3.5">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-start gap-3">
                <div className="w-9 h-9 rounded-xl bg-rose-950/80 border border-rose-800/60 flex items-center justify-center text-rose-400 shrink-0">
                  <AlertCircle className="w-5 h-5" />
                </div>
                <div className="space-y-0.5">
                  <div className="inline-flex items-center gap-1.5 text-[10px] font-mono text-rose-300 uppercase font-semibold">
                    <span>Database Connectivity Notice</span>
                  </div>
                  <h3 className="text-sm font-bold text-white font-sans">
                    PostgreSQL Relational Ledger Is Offline
                  </h3>
                  <p className="text-xs text-rose-200/90 font-sans leading-relaxed max-w-3xl">
                    The backend database session is currently unreachable. Live table row inspection, column profiles, and automated SQL quality rules are paused until database connectivity is restored.
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2 self-start sm:self-center shrink-0">
                <button
                  onClick={fetchInitialData}
                  disabled={loading}
                  className="px-3 py-1.5 rounded-lg bg-rose-900/40 hover:bg-rose-900/60 border border-rose-700/50 text-rose-200 text-xs font-mono font-semibold transition-all inline-flex items-center gap-1.5"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                  <span>Retry Connection</span>
                </button>
                <button
                  onClick={() => setShowTechnicalDiagnostics((prev) => !prev)}
                  className="px-2.5 py-1.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-slate-300 text-xs font-mono transition-all inline-flex items-center gap-1"
                >
                  <span>Diagnostics</span>
                  {showTechnicalDiagnostics ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>

            {showTechnicalDiagnostics && (
              <div className="pt-2 border-t border-rose-900/30 text-xs font-mono text-rose-300/80 bg-void/60 p-3 rounded-lg overflow-x-auto space-y-1">
                <div><strong>Endpoint:</strong> /api/v1/data/health &amp; /api/v1/data/tables</div>
                <div><strong>Error Trace:</strong> {errorDetails ? String(errorDetails) : error}</div>
                <div className="text-[11px] text-slate-400">
                  Note: Spreadsheet uploads through the Data Gateway can still be staged, validated, and reviewed in memory.
                </div>
              </div>
            )}
          </div>
        )}

        {/* Global Loading Spinner for initial telemetry */}
        {loading && <LoadingState message="Connecting to PostgreSQL catalog and auditing data quality..." />}

        {/* ========================================================= */}
        {/* 3. DATA LAYER HEALTH SCORECARD (21st.dev Stat Pattern)   */}
        {/* ========================================================= */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
          {/* Card 1: Data Layer Posture */}
          <div
            className="card-obsidian p-4 sm:p-5 flex flex-col justify-between border-white/[0.08] hover:border-slate-500/30 transition-all duration-200 min-w-0 group"
            title="Comprehensive data layer integrity status combining PostgreSQL connectivity, constraint compliance, and schema validation."
          >
            <div>
              <div className="flex items-center justify-between gap-2 mb-2.5">
                <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-medium truncate">
                  Data Layer Posture
                </span>
                <div
                  className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 border transition-colors ${
                    currentPosture === 'READY'
                      ? 'bg-emerald-950/40 border-emerald-800/40 text-emerald-400'
                      : currentPosture === 'READY_WITH_WARNINGS'
                      ? 'bg-amber-950/40 border-amber-800/40 text-amber-400'
                      : 'bg-rose-950/40 border-rose-800/40 text-rose-400'
                  }`}
                >
                  <Database className="w-3.5 h-3.5" />
                </div>
              </div>

              <div className="space-y-1.5 pt-0.5">
                <div>
                  <StatusBadge status={currentPosture} size="sm" />
                </div>
                <span className="text-[11px] font-mono text-slate-300 block truncate">
                  {!dbConnected
                    ? 'Connection Unreachable'
                    : currentPosture === 'READY'
                    ? 'All constraints verified'
                    : `${failedCount} Active warnings`}
                </span>
              </div>
            </div>

            <div className="mt-3 pt-2.5 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-slate-400 font-sans">
              <span className="truncate" title="Managed relational storage and schema gate">
                Managed storage &amp; schema gate
              </span>
            </div>
          </div>

          {/* Card 2: Total Record Coverage */}
          <div
            className="card-obsidian p-4 sm:p-5 flex flex-col justify-between border-white/[0.08] hover:border-cyan-500/30 transition-all duration-200 min-w-0 group"
            title="Total number of relational records persisted across all business domain entities in this tenant workspace."
          >
            <div>
              <div className="flex items-center justify-between gap-2 mb-2.5">
                <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-medium truncate">
                  Total Record Coverage
                </span>
                <div className="w-7 h-7 rounded-lg bg-cyan-950/40 border border-cyan-800/30 flex items-center justify-center text-cyan-400 shrink-0 group-hover:border-cyan-500/40 transition-colors">
                  <Layers className="w-3.5 h-3.5" />
                </div>
              </div>

              <div className="space-y-1">
                <p className="text-xl sm:text-2xl font-bold text-cyan-400 font-mono tabular-nums tracking-tight">
                  {dbConnected ? formatNumber(health?.total_records ?? 0) : '—'}
                </p>
                <span className="text-[10px] font-mono text-cyan-400/80 block truncate">
                  {dbConnected ? 'Relational Rows Managed' : 'Relational Ledger Offline'}
                </span>
              </div>
            </div>

            <div className="mt-3 pt-2.5 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-slate-400 font-sans">
              <span className="truncate" title="PostgreSQL transactional domain records">
                PostgreSQL transactional records
              </span>
            </div>
          </div>

          {/* Card 3: Active Source Tables */}
          <div
            className="card-obsidian p-4 sm:p-5 flex flex-col justify-between border-white/[0.08] hover:border-slate-400/30 transition-all duration-200 min-w-0 group"
            title="Count of core domain tables registered in the NEXUS unified schema catalog."
          >
            <div>
              <div className="flex items-center justify-between gap-2 mb-2.5">
                <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-medium truncate">
                  Active Source Tables
                </span>
                <div className="w-7 h-7 rounded-lg bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-slate-300 shrink-0 group-hover:border-white/[0.14] transition-colors">
                  <TableIcon className="w-3.5 h-3.5" />
                </div>
              </div>

              <div className="space-y-1">
                <p className="text-xl sm:text-2xl font-bold text-white font-mono tabular-nums tracking-tight">
                  {dbConnected ? `${tables.length} / ${health?.registered_models || 6}` : '0 / 6'}
                </p>
                <span className="text-[10px] font-mono text-slate-400 block truncate">
                  {dbConnected
                    ? `${populatedTablesCount} Populated • ${emptyTablesCount} Empty`
                    : 'PostgreSQL Catalog Offline'}
                </span>
              </div>
            </div>

            <div className="mt-3 pt-2.5 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-slate-400 font-sans">
              <span className="truncate" title="Registered business domain entities">
                Unified business entity models
              </span>
            </div>
          </div>

          {/* Card 4: Quality Constraints */}
          <div
            className="card-obsidian p-4 sm:p-5 flex flex-col justify-between border-white/[0.08] hover:border-emerald-500/30 transition-all duration-200 min-w-0 group"
            title="Automated business rules, foreign key referential integrity checks, and null rate threshold audits."
          >
            <div>
              <div className="flex items-center justify-between gap-2 mb-2.5">
                <span className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-medium truncate">
                  Quality Constraints
                </span>
                <div className="w-7 h-7 rounded-lg bg-emerald-950/40 border border-emerald-800/30 flex items-center justify-center text-emerald-400 shrink-0 group-hover:border-emerald-500/40 transition-colors">
                  <ShieldCheck className="w-3.5 h-3.5" />
                </div>
              </div>

              <div className="space-y-1">
                <p className="text-xl sm:text-2xl font-bold text-emerald-400 font-mono tabular-nums tracking-tight">
                  {!dbConnected
                    ? 'Offline'
                    : quality
                    ? `${quality.checks_passed ?? quality.passed_rules ?? 0}/${quality.checks_executed ?? quality.total_rules ?? 0} Passed`
                    : tableLoading
                    ? 'Auditing...'
                    : 'Select Table'}
                </p>
                <span className="text-[10px] font-mono text-emerald-400/80 block truncate">
                  {!dbConnected
                    ? 'Audit engine paused'
                    : quality && (quality.checks_executed ?? quality.total_rules ?? 0) > 0
                    ? `${Math.round(((quality.checks_passed ?? quality.passed_rules ?? 0) / (quality.checks_executed ?? quality.total_rules ?? 1)) * 100)}% Rule compliance`
                    : 'Deterministic boundary checks'}
                </span>
              </div>
            </div>

            <div className="mt-3 pt-2.5 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-slate-400 font-sans">
              <span className="truncate" title="Deterministic schema and relational constraint audits">
                Deterministic boundary checks
              </span>
            </div>
          </div>
        </section>

        {/* ========================================================= */}
        {/* 4. PRODUCTION DATA GATEWAY: SPREADSHEET INGESTION        */}
        {/* ========================================================= */}
        <section className="card-obsidian p-5 sm:p-6 space-y-5">
          {/* Gateway Section Header */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-white/[0.08] pb-4">
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <div className="inline-flex items-center gap-1.5 text-xs font-mono text-cyan-400 font-semibold">
                  <UploadCloud className="w-4 h-4" />
                  <span>COMMERCIAL SPREADSHEET &amp; FILE GATEWAY</span>
                </div>
                <span className="px-2 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-800/40 text-cyan-300 font-mono text-[10px]">
                  {gatewayDatasets.length} {gatewayDatasets.length === 1 ? 'Dataset Staged' : 'Datasets Staged'}
                </span>
              </div>
              <h2 className="text-base font-bold text-white font-sans">
                Commercial Data Ingestion &amp; Schema Mapping
              </h2>
              <p className="text-xs text-slate-400 font-sans max-w-2xl">
                Upload commercial CSV or Excel spreadsheets. NEXUS deterministically profiles data types, audits boundary constraints, and maps records into unified core models.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="btn-primary text-xs h-9 px-3.5"
                title="Select spreadsheet file from local filesystem"
              >
                <FileSpreadsheet className="w-4 h-4" />
                <span>{uploading ? 'Processing File...' : 'Select File to Stage'}</span>
              </button>
            </div>
          </div>

          {/* Drag & Drop Staging Area */}
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-2xl p-6 sm:p-8 text-center cursor-pointer transition-all flex flex-col items-center justify-center ${
              isDragging
                ? 'border-cyan-400 bg-cyan-950/40 shadow-[0_0_25px_rgba(6,182,212,0.2)]'
                : 'border-white/[0.12] hover:border-cyan-500/50 bg-void/50 hover:bg-void/80'
            }`}
          >
            <div className="w-12 h-12 rounded-xl bg-cyan-950/80 border border-cyan-500/30 flex items-center justify-center text-cyan-400 mb-3 shadow-inner">
              {uploading ? (
                <RefreshCw className="w-5 h-5 animate-spin text-cyan-300" />
              ) : (
                <UploadCloud className="w-6 h-6 text-cyan-400" />
              )}
            </div>

            <h3 className="text-sm font-semibold text-white">
              {uploading
                ? uploadStep || 'Analyzing dataset schema & computing quality scorecard...'
                : isDragging
                ? 'Release file to stage through Data Gateway'
                : 'Drag & drop commercial spreadsheets here, or browse files'}
            </h3>

            <p className="text-xs text-slate-400 mt-1.5 max-w-md">
              Supports CSV, XLSX, and XLS formats up to 50MB. Auto-maps to Sales, Customers, Products, Inventory, or Expense models.
            </p>

            {uploading && (
              <div className="mt-3 inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-950/80 border border-cyan-500/40 text-[11px] font-mono text-cyan-300 animate-pulse">
                <Activity className="w-3.5 h-3.5" />
                <span>Deterministic profiling &amp; rule verification in progress</span>
              </div>
            )}
          </div>

          {/* Upload and Ingest Status Alerts */}
          {uploadError && (
            <div className="p-3.5 rounded-xl bg-rose-950/60 border border-rose-500/40 flex items-center justify-between text-xs text-rose-200">
              <div className="flex items-center gap-3">
                <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
                <span>{uploadError}</span>
              </div>
              <button
                onClick={() => setUploadError(null)}
                className="text-rose-400 hover:text-rose-100 p-1"
                title="Dismiss error alert"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          )}

          {ingestSuccess && (
            <div className="p-3.5 rounded-xl bg-emerald-950/60 border border-emerald-500/40 flex items-center justify-between text-xs text-emerald-200">
              <div className="flex items-center gap-3">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                <span>{ingestSuccess}</span>
              </div>
              <button
                onClick={() => setIngestSuccess(null)}
                className="text-emerald-400 hover:text-emerald-100 p-1"
                title="Dismiss success alert"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          )}

          {/* Staged Datasets Source Cards Carousel / Grid */}
          {gatewayDatasets.length > 0 && (
            <div className="space-y-3 pt-2">
              <div className="flex items-center justify-between text-[11px] font-mono text-slate-400 uppercase tracking-wider">
                <span>Staged Datasets ({gatewayDatasets.length})</span>
                <span className="text-slate-500">Select dataset to inspect mapping or ingest</span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {gatewayDatasets.map((ds) => {
                  const dsId = ds.dataset_id || ds.id;
                  const isSelected = (selectedGatewayDataset?.dataset_id || selectedGatewayDataset?.id) === dsId;
                  const ingStatus = (ds.ingestion_status || 'PENDING').toUpperCase();
                  const isCompleted = ingStatus === 'COMPLETED';
                  const isFailed = ingStatus === 'FAILED';

                  return (
                    <button
                      key={dsId || ds.filename}
                      type="button"
                      onClick={() => {
                        setSelectedGatewayDataset(ds);
                        if (dsId) handlePreviewDataset(dsId);
                      }}
                      className={`text-left p-3.5 rounded-xl border transition-all flex flex-col justify-between space-y-2 relative group ${
                        isSelected
                          ? 'bg-cyan-950/40 border-cyan-500/50 shadow-[0_0_15px_rgba(6,182,212,0.1)]'
                          : 'bg-void/60 border-white/[0.08] hover:border-white/[0.18] hover:bg-void/90'
                      }`}
                    >
                      {isSelected && (
                        <span className="absolute top-0 left-0 right-0 h-0.5 bg-cyan-400 rounded-t-xl" />
                      )}

                      <div className="flex items-start justify-between gap-2 w-full">
                        <div className="flex items-center gap-2 truncate">
                          <FileSpreadsheet className={`w-4 h-4 shrink-0 ${isSelected ? 'text-cyan-400' : 'text-slate-400'}`} />
                          <span className="font-mono text-xs font-bold text-white truncate">
                            {ds.original_filename || ds.filename || 'dataset.csv'}
                          </span>
                        </div>

                        {/* Ingestion Status Pill */}
                        <span
                          className={`px-2 py-0.5 rounded-full font-mono text-[9px] font-semibold shrink-0 uppercase border ${
                            isCompleted
                              ? 'bg-emerald-950/70 border-emerald-600/40 text-emerald-300'
                              : isFailed
                              ? 'bg-rose-950/70 border-rose-600/40 text-rose-300'
                              : 'bg-cyan-950/60 border-cyan-700/40 text-cyan-300'
                          }`}
                        >
                          {isCompleted ? 'Persisted' : isFailed ? 'Failed' : 'Staged'}
                        </span>
                      </div>

                      <div className="flex items-center justify-between text-[11px] font-mono text-slate-400 pt-1 border-t border-white/[0.04] w-full">
                        <span>{formatNumber(ds.row_count ?? 0)} rows</span>
                        <span className="text-slate-500">•</span>
                        <span>{ds.target_entity || 'Core Model'}</span>
                        <span className="text-slate-500">•</span>
                        <span className="text-cyan-400 font-semibold">{ds.readiness_score ?? 70}% Ready</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Selected Dataset Detail & Action Workspace */}
          {selectedGatewayDataset ? (
            <div className="rounded-xl border border-white/[0.08] bg-void/80 p-5 space-y-4">
              {/* Selected File Overview Bar */}
              <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 border-b border-white/[0.08] pb-3 text-xs">
                <div className="flex flex-wrap items-center gap-2.5">
                  <FileCheck className="w-4 h-4 text-cyan-400" />
                  <span className="font-bold text-white font-mono text-sm">
                    {selectedGatewayDataset.original_filename || selectedGatewayDataset.filename || 'dataset.csv'}
                  </span>
                  <span className="px-2 py-0.5 rounded bg-surface border border-white/[0.08] font-mono text-[10px] text-slate-400">
                    {selectedGatewayDataset.file_size_bytes
                      ? `${(selectedGatewayDataset.file_size_bytes / 1024).toFixed(1)} KB`
                      : 'Tabular file'}
                  </span>
                  <span className="px-2 py-0.5 rounded bg-cyan-950/60 border border-cyan-800/40 font-mono text-[10px] text-cyan-300 uppercase">
                    {selectedGatewayDataset.file_type || selectedGatewayDataset.file_format || 'CSV'}
                  </span>
                  {selectedGatewayDataset.created_at && (
                    <span className="inline-flex items-center gap-1 font-mono text-[10px] text-slate-500">
                      <Clock className="w-3 h-3" />
                      <span>{new Date(selectedGatewayDataset.created_at).toLocaleDateString()}</span>
                    </span>
                  )}
                </div>

                <div className="flex flex-wrap items-center gap-3 font-mono text-[11px]">
                  <span className="text-slate-400">
                    Readiness: <strong className="text-cyan-400">{selectedGatewayDataset.readiness_score ?? 70}%</strong>
                  </span>
                  <span className="text-slate-400">
                    Quality: <strong className="text-emerald-400">{selectedGatewayDataset.quality_score ?? 100}/100</strong>
                  </span>
                  <span className="text-slate-400">
                    Rows: <strong className="text-white">{formatNumber(selectedGatewayDataset.row_count ?? 0)}</strong>
                  </span>
                  <span className="text-slate-400">
                    Cols: <strong className="text-white">{selectedGatewayDataset.column_count ?? 0}</strong>
                  </span>
                </div>
              </div>

              {/* Entity Mapping & Ingestion Trigger */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs font-mono">
                <div className="space-y-1">
                  <span className="text-slate-500 text-[10px] uppercase font-semibold">TARGET ENTITY MODEL</span>
                  <div className="text-white font-bold text-sm">
                    {selectedGatewayDataset.target_entity ||
                      selectedGatewayDataset.mapping_proposal?.target_entity ||
                      'Sale'}
                  </div>
                  <span className="text-[10px] text-slate-400 block">Unified Core Domain Model</span>
                </div>

                <div className="space-y-1">
                  <span className="text-slate-500 text-[10px] uppercase font-semibold">READINESS POSTURE</span>
                  <div className="text-cyan-400 font-bold text-sm">
                    {selectedGatewayDataset.readiness_status || 'READY'}
                  </div>
                  <span className="text-[10px] text-slate-400 block truncate">
                    {selectedGatewayDataset.readiness_reasons?.[0] || 'Validated for autonomous analysis'}
                  </span>
                </div>

                <div className="flex flex-wrap items-center justify-start sm:justify-end gap-2 pt-2 sm:pt-0">
                  <button
                    type="button"
                    onClick={() => handlePreviewDataset(selectedGatewayDataset.dataset_id || selectedGatewayDataset.id)}
                    disabled={previewLoading}
                    className="btn-secondary text-xs h-8 px-3"
                    title="Inspect top 15 sanitized sample records"
                  >
                    <Eye className="w-3.5 h-3.5 text-cyan-400" />
                    <span>{previewLoading ? 'Loading...' : gatewayPreview ? 'Refresh Preview' : 'Preview Rows'}</span>
                  </button>

                  <button
                    type="button"
                    disabled={
                      ingesting ||
                      (selectedGatewayDataset.readiness_score ?? 70) < 70 ||
                      !dbConnected
                    }
                    onClick={handleIngestDataset}
                    className={`btn-primary text-xs h-8 px-3.5 ${
                      selectedGatewayDataset.ingestion_status === 'COMPLETED'
                        ? 'bg-emerald-700 hover:bg-emerald-600 text-white border-emerald-500'
                        : ''
                    }`}
                    title={
                      !dbConnected
                        ? 'PostgreSQL database service offline. Connect database to persist records.'
                        : (selectedGatewayDataset.readiness_score ?? 70) < 70
                        ? 'Readiness score must be at least 70% to ingest'
                        : 'Commit validated records into PostgreSQL core model'
                    }
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    <span>
                      {ingesting
                        ? 'Ingesting Records...'
                        : selectedGatewayDataset.ingestion_status === 'COMPLETED'
                        ? 'Ingested to Core (Re-commit)'
                        : 'Ingest to Core'}
                    </span>
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
                  <div className="pt-2 border-t border-white/[0.06] space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-mono text-slate-400 uppercase tracking-wider block">
                        MAPPED SCHEMA ATTRIBUTES ({rawMappings.length}):
                      </span>
                      {selectedGatewayDataset.mapping_proposal?.missing_required_fields &&
                        selectedGatewayDataset.mapping_proposal.missing_required_fields.length > 0 && (
                          <span className="text-[10px] font-mono text-amber-400">
                            Missing required: {selectedGatewayDataset.mapping_proposal.missing_required_fields.join(', ')}
                          </span>
                        )}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {rawMappings.length > 0 ? (
                        rawMappings.map((m, idx) => (
                          <span
                            key={idx}
                            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-surface border border-white/[0.08] text-[11px] font-mono text-slate-300"
                          >
                            <span>{m.source_column || m.source || 'Column'}</span>
                            <ArrowRight className="w-3 h-3 text-cyan-400 shrink-0" />
                            <span className="text-emerald-400 font-semibold">{m.mapped_field || m.target || 'Field'}</span>
                          </span>
                        ))
                      ) : (
                        <span className="text-xs text-slate-500 font-mono">
                          Direct 1:1 relational mapping applied based on column names.
                        </span>
                      )}
                    </div>
                  </div>
                );
              })()}

              {/* Data Preview Table (if toggled) */}
              {gatewayPreview &&
                gatewayPreview.dataset_id === (selectedGatewayDataset.dataset_id || selectedGatewayDataset.id) && (
                  <div className="pt-4 border-t border-white/[0.08] space-y-3">
                    <div className="flex items-center justify-between text-xs font-mono text-slate-400">
                      <div className="flex items-center gap-2">
                        <Layers className="w-3.5 h-3.5 text-cyan-400" />
                        <span className="font-semibold text-slate-200">
                          Sanitized Sample Rows ({gatewayPreview.sample_rows.length} rows previewed)
                        </span>
                      </div>
                      <button
                        onClick={() => setGatewayPreview(null)}
                        className="text-slate-400 hover:text-white text-[11px] flex items-center gap-1 p-1"
                        title="Close sample preview table"
                      >
                        <X className="w-3 h-3" />
                        <span>Close Preview</span>
                      </button>
                    </div>

                    <div className="overflow-x-auto rounded-xl border border-white/[0.08] max-h-60 bg-void/90">
                      <table className="w-full text-left font-mono text-[11px]">
                        <thead className="bg-surface-elevated/80 text-slate-400 border-b border-white/[0.08] sticky top-0 z-10 backdrop-blur-sm">
                          <tr>
                            {gatewayPreview.columns.map((c) => (
                              <th key={c} className="p-2.5 whitespace-nowrap">
                                <div className="text-slate-200">{c}</div>
                                <div className="text-[9px] text-cyan-400 font-normal">
                                  {gatewayPreview.inferred_types[c] || 'TEXT'}
                                </div>
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-white/[0.04] text-slate-300">
                          {gatewayPreview.sample_rows.map((row, rIdx) => (
                            <tr key={rIdx} className="hover:bg-white/[0.02]">
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
            /* Actionable Empty State when 0 Datasets Staged */
            <div className="p-6 sm:p-8 rounded-xl bg-void/50 border border-white/[0.08] text-center space-y-4">
              <div className="w-12 h-12 rounded-2xl bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-slate-400 mx-auto">
                <FileSpreadsheet className="w-6 h-6 text-cyan-400" />
              </div>

              <div className="max-w-md mx-auto space-y-1.5">
                <h3 className="text-sm font-bold text-white font-sans">
                  No External Datasets Staged Yet
                </h3>
                <p className="text-xs text-slate-400 font-sans leading-relaxed">
                  Stage commercial records from POS, ERP, or CRM spreadsheets. NEXUS deterministically profiles data types, executes quality rule checks, and automates unified core model mapping.
                </p>
              </div>

              {/* 3-Step Lifecycle Guidance */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-2xl mx-auto pt-2 text-left text-xs font-sans">
                <div className="p-3 rounded-lg bg-surface/50 border border-white/[0.06] space-y-1">
                  <span className="font-mono text-[10px] text-cyan-400 font-bold uppercase">1. STAGE</span>
                  <p className="text-[11px] text-slate-300">Upload CSV or XLSX commercial transaction sheets.</p>
                </div>
                <div className="p-3 rounded-lg bg-surface/50 border border-white/[0.06] space-y-1">
                  <span className="font-mono text-[10px] text-emerald-400 font-bold uppercase">2. PROFILE</span>
                  <p className="text-[11px] text-slate-300">Deterministic type inference &amp; quality audits.</p>
                </div>
                <div className="p-3 rounded-lg bg-surface/50 border border-white/[0.06] space-y-1">
                  <span className="font-mono text-[10px] text-violet-400 font-bold uppercase">3. INGEST</span>
                  <p className="text-[11px] text-slate-300">Commit clean records to tenant PostgreSQL storage.</p>
                </div>
              </div>

              <div className="pt-2">
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="btn-secondary text-xs h-8 px-3.5 inline-flex items-center gap-1.5"
                >
                  <UploadCloud className="w-3.5 h-3.5 text-cyan-400" />
                  <span>Browse File to Stage</span>
                </button>
              </div>
            </div>
          )}
        </section>

        {/* ========================================================= */}
        {/* 5. RELATIONAL TABLE DIRECTORY & SCHEMA CATALOG           */}
        {/* ========================================================= */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Table Directory Sidebar */}
          <div className="card-obsidian p-5 space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono uppercase text-slate-400 tracking-wider font-semibold">
                Domain Tables ({tables.length > 0 ? tables.length : CANONICAL_MODELS.length})
              </span>
              <span className="text-[10px] font-mono text-slate-500 uppercase">
                {dbConnected ? 'PostgreSQL Schema' : 'Offline'}
              </span>
            </div>

            {/* Quick Filter */}
            <div className="relative">
              <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                type="text"
                placeholder="Filter domain tables..."
                value={tableSearch}
                onChange={(e) => setTableSearch(e.target.value)}
                className="input-obsidian pl-8 text-xs h-8"
              />
              {tableSearch && (
                <button
                  onClick={() => setTableSearch('')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white"
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>

            <div className="space-y-1.5 max-h-[480px] overflow-y-auto pr-1">
              {filteredTables.length > 0 ? (
                filteredTables.map((t) => {
                  const isSelected = selectedTable === t.table_name;
                  const isPopulated = t.row_count > 0;

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
                      className={`w-full text-left p-2.5 rounded-xl border transition-all flex items-center justify-between text-xs relative group ${
                        isSelected
                          ? 'bg-cyan-950/40 border-cyan-500/40 text-white font-semibold shadow-sm'
                          : 'bg-void/40 border-white/[0.06] text-slate-300 hover:bg-void/80 hover:border-white/[0.12]'
                      }`}
                    >
                      {isSelected && (
                        <span className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-5 rounded-r bg-cyan-400" />
                      )}
                      <div className="flex items-center gap-2.5 truncate pl-1">
                        <TableIcon className={`w-3.5 h-3.5 shrink-0 ${isSelected ? 'text-cyan-400' : 'text-slate-500'}`} />
                        <span className="truncate font-mono">{t.table_name}</span>
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        <span
                          className={`w-1.5 h-1.5 rounded-full ${
                            !dbConnected
                              ? 'bg-rose-500'
                              : isPopulated
                              ? 'bg-emerald-400'
                              : 'bg-slate-600'
                          }`}
                        />
                        <span className="font-mono text-[11px] text-slate-400 tabular-nums">
                          {!dbConnected ? 'Offline' : `${formatNumber(t.row_count)} rows`}
                        </span>
                      </div>
                    </button>
                  );
                })
              ) : (
                <div className="p-4 text-center text-xs text-slate-500 font-mono">
                  No tables match "{tableSearch}"
                </div>
              )}
            </div>

            {/* Offline notice under table sidebar if DB offline */}
            {!dbConnected && (
              <div className="p-3 rounded-lg bg-rose-950/30 border border-rose-900/40 text-[11px] text-rose-300 font-sans space-y-1">
                <span className="font-mono uppercase font-bold text-[10px] block text-rose-400">
                  Database Session Offline
                </span>
                <p>Showing canonical model definitions. Live table statistics will populate once PostgreSQL connection is established.</p>
              </div>
            )}
          </div>

          {/* Selected Table Inspection & Profile */}
          <div className="lg:col-span-2 card-obsidian p-5 sm:p-6 space-y-6 min-w-0">
            {tableLoading ? (
              <LoadingState message={`Profiling table ${selectedTable}...`} />
            ) : !dbConnected ? (
              /* Database Offline State for Table Profiler */
              <div className="p-8 rounded-xl bg-void/50 border border-white/[0.08] text-center space-y-3">
                <div className="w-12 h-12 rounded-2xl bg-rose-950/50 border border-rose-800/40 flex items-center justify-center text-rose-400 mx-auto">
                  <Database className="w-6 h-6" />
                </div>
                <h3 className="text-sm font-bold text-white font-sans">
                  PostgreSQL Table Profiler Offline
                </h3>
                <p className="text-xs text-slate-400 font-sans max-w-md mx-auto leading-relaxed">
                  Cannot query statistical profiles, null distributions, or automated quality constraints for <strong>{selectedTable}</strong> because the PostgreSQL database service is disconnected.
                </p>
                <div className="pt-2">
                  <button
                    onClick={fetchInitialData}
                    className="btn-secondary text-xs h-8 px-3 inline-flex items-center gap-1.5"
                  >
                    <RefreshCw className="w-3 h-3 text-cyan-400" />
                    <span>Retry Database Connection</span>
                  </button>
                </div>
              </div>
            ) : (
              <>
                {/* Table Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-white/[0.08] pb-4">
                  <div>
                    <span className="text-[10px] font-mono uppercase text-cyan-400 tracking-wider font-semibold">
                      POSTGRESQL TABLE PROFILE
                    </span>
                    <h3 className="text-lg font-bold text-white font-mono mt-0.5">
                      {selectedTable || 'sales'}
                    </h3>
                    <p className="text-xs text-slate-400 font-sans mt-0.5">
                      {CANONICAL_MODELS.find((m) => m.name === selectedTable)?.description ||
                        'Unified relational business entity model'}
                    </p>
                  </div>
                  <div className="text-left sm:text-right">
                    <span className="text-[10px] font-mono uppercase text-slate-500 block">
                      TOTAL CARDINALITY
                    </span>
                    <span className="text-sm font-bold font-mono text-cyan-400 tabular-nums">
                      {formatNumber(profile?.row_count ?? (profile as any)?.total_rows ?? 0)} records
                    </span>
                  </div>
                </div>

                {/* Column Schema Profile Table */}
                <div className="space-y-3">
                  <span className="text-xs font-mono uppercase text-slate-400 tracking-wider font-semibold block">
                    Column Schema &amp; Type Telemetry
                  </span>

                  {profile && Object.keys(profile.columns || {}).length > 0 ? (
                    <div className="overflow-x-auto rounded-xl border border-white/[0.08] max-h-72">
                      <table className="w-full text-left font-mono text-xs">
                        <thead className="bg-surface-elevated/60 text-slate-400 border-b border-white/[0.08] sticky top-0">
                          <tr>
                            <th className="p-3">Column</th>
                            <th className="p-3">Data Type</th>
                            <th className="p-3">Null %</th>
                            <th className="p-3">Distinct Values</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-white/[0.04] text-slate-300">
                          {Object.values(profile.columns || {}).map((c) => (
                            <tr key={c.column_name} className="hover:bg-white/[0.02]">
                              <td className="p-3 font-semibold text-white">{c.column_name}</td>
                              <td className="p-3 text-cyan-400">{c.data_type || (c as any).inferred_type || '—'}</td>
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
                              <td className="p-3 text-slate-400 tabular-nums">
                                {formatNumber(c.distinct_count ?? (c as any).unique_count ?? 0)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    /* Table has 0 records / not yet populated */
                    <div className="p-6 rounded-xl bg-void/50 border border-white/[0.08] text-center space-y-2">
                      <p className="text-xs text-slate-400 font-sans">
                        No records currently stored in <strong>{selectedTable}</strong>. Use the Data Gateway above to upload and ingest commercial spreadsheets targeting this entity.
                      </p>
                      <button
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                        className="btn-secondary text-xs h-7 px-3 mt-1 inline-flex items-center gap-1"
                      >
                        <UploadCloud className="w-3 h-3 text-cyan-400" />
                        <span>Stage Data for {selectedTable}</span>
                      </button>
                    </div>
                  )}
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
                            <div className="flex items-center gap-2 truncate pr-2">
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

export default DataPage;
