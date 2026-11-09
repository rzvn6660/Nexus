import React, { useState, useEffect, useCallback } from 'react';
import {
  Radio,
  ShieldCheck,
  ShieldAlert,
  RefreshCw,
  Key,
  CheckCircle2,
  AlertTriangle,
  Lock,
  Copy,
  Check,
  FileCheck,
  History,
  X,
  Activity,
  AlertCircle,
} from 'lucide-react';
import {
  listConnectorCredentials,
  registerConnectorCredentials,
  listSyncCheckpoints,
  getWebhookInboxSummary,
  getPeriodCloseHistory,
  verifyHistoricalPackage,
  ConnectorCredentialSummary,
  CheckpointSummary,
  WebhookInboxStatusSummary,
  PeriodCloseSubmissionSummary,
  VerifyHistoricalPackageResult,
} from '../services/connectors';
import { getCustomerCadence } from '../services/analytics';
import { CadenceSafetyVerdict, SeasonalCautionDisclosure } from '../types/api';
import { CadenceSafetyBadge } from '../components/common/CadenceSafetyBadge';
import { SeasonalCautionBanner } from '../components/common/SeasonalCautionBanner';
import { LoadingState } from '../components/common/LoadingState';
import { formatNumber } from '../utils/formatters';

interface ConnectorsPageProps {
  onNavigate?: (route: string) => void;
}

const APEX_TENANT_ID = 'ab044b1a-835a-4a38-bf45-62fe38624151';

export const ConnectorsPage: React.FC<ConnectorsPageProps> = () => {
  const [activeTab, setActiveTab] = useState<'credentials' | 'checkpoints' | 'period-close'>('credentials');
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // Tenant state
  const businessId = (typeof window !== 'undefined' ? localStorage.getItem('nexus_business_id') : null) || APEX_TENANT_ID;
  const isApex = businessId === APEX_TENANT_ID || businessId.toLowerCase().includes('apex');

  // Data states
  const [credentials, setCredentials] = useState<ConnectorCredentialSummary[]>([]);
  const [checkpoints, setCheckpoints] = useState<CheckpointSummary[]>([]);
  const [webhookSummaries, setWebhookSummaries] = useState<WebhookInboxStatusSummary[]>([]);
  const [submissions, setSubmissions] = useState<PeriodCloseSubmissionSummary[]>([]);
  const [cadenceVerdict, setCadenceVerdict] = useState<CadenceSafetyVerdict | null>(null);
  const [seasonalCaution, setSeasonalCaution] = useState<SeasonalCautionDisclosure | null>(null);

  // Credential Modal State
  const [showCredModal, setShowCredModal] = useState<boolean>(false);
  const [credProvider, setCredProvider] = useState<'shopify' | 'stripe'>('shopify');
  const [credAccountId, setCredAccountId] = useState<string>('');
  const [credSecret, setCredSecret] = useState<string>('');
  const [credKmsKey, setCredKmsKey] = useState<string>('local_kms_vault');
  const [credScopes, setCredScopes] = useState<string>('read_orders, read_products');
  const [credSaving, setCredSaving] = useState<boolean>(false);
  const [credSuccessMsg, setCredSuccessMsg] = useState<string | null>(null);
  const [credErrorMsg, setCredErrorMsg] = useState<string | null>(null);

  // Verification Modal State
  const [verifyingManifestId, setVerifyingManifestId] = useState<string | null>(null);
  const [verifyResult, setVerifyResult] = useState<VerifyHistoricalPackageResult | null>(null);
  const [verifyLoading, setVerifyLoading] = useState<boolean>(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [credsRes, checkpointsRes, webhooksRes, historyRes, cadenceRes] = await Promise.all([
        listConnectorCredentials(businessId).catch((err) => {
          console.warn('Connector credentials error:', err);
          return [];
        }),
        listSyncCheckpoints(businessId).catch((err) => {
          console.warn('Sync checkpoints error:', err);
          return [];
        }),
        getWebhookInboxSummary(businessId).catch((err) => {
          console.warn('Webhook inbox summary error:', err);
          return [];
        }),
        getPeriodCloseHistory(businessId).catch((err) => {
          console.warn('Period-close history error:', err);
          return [];
        }),
        getCustomerCadence().catch((err) => {
          console.warn('Customer cadence fetch error:', err);
          return null;
        }),
      ]);

      setCredentials(credsRes);
      setCheckpoints(checkpointsRes);
      setWebhookSummaries(webhooksRes);
      setSubmissions(historyRes);

      if (cadenceRes && cadenceRes.data) {
        setCadenceVerdict(cadenceRes.data.safety_verdict || null);
        setSeasonalCaution(cadenceRes.data.safety_verdict?.seasonal_disclosure || null);
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load connector information.');
    } finally {
      setLoading(false);
    }
  }, [businessId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleSaveCredential = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isApex) {
      setCredErrorMsg('Credential registration is forbidden on protected reference tenant Apex Specialty Commerce.');
      return;
    }
    setCredSaving(true);
    setCredErrorMsg(null);
    setCredSuccessMsg(null);
    try {
      const scopesArr = credScopes.split(',').map((s) => s.trim()).filter(Boolean);
      await registerConnectorCredentials({
        business_id: businessId,
        provider: credProvider,
        provider_account_id: credAccountId,
        credentials: {
          secret_key: credSecret,
          account_id: credAccountId,
          api_version: credProvider === 'shopify' ? '2025-01' : '2024-06-20',
        },
        scopes: scopesArr,
        kms_key_id: credKmsKey,
      });
      setCredSuccessMsg(`Successfully registered encrypted credentials for ${credProvider.toUpperCase()}.`);
      setCredSecret('');
      await loadData();
      setTimeout(() => {
        setShowCredModal(false);
        setCredSuccessMsg(null);
      }, 1500);
    } catch (err: any) {
      setCredErrorMsg(err?.data?.detail || err?.message || 'Failed to register credentials.');
    } finally {
      setCredSaving(false);
    }
  };

  const handleVerifyHistorical = async (manifestId: string) => {
    setVerifyingManifestId(manifestId);
    setVerifyLoading(true);
    setVerifyError(null);
    setVerifyResult(null);
    try {
      const res = await verifyHistoricalPackage(manifestId, businessId);
      setVerifyResult(res);
    } catch (err: any) {
      setVerifyError(err?.data?.detail || err?.message || 'Failed to verify historical package.');
    } finally {
      setVerifyLoading(false);
    }
  };

  const shopifyCred = credentials.find((c) => c.provider === 'shopify');
  const stripeCred = credentials.find((c) => c.provider === 'stripe');

  return (
    <div className="space-y-6 pb-12">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-elevated/80 pb-6">
        <div>
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-cyan-950/60 border border-cyan-500/30 text-cyan-400">
              <Radio className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-3">
                Connectors & Period Close
                {isApex && (
                  <span className="text-xs font-mono px-2.5 py-0.5 rounded-md bg-amber-950/80 text-amber-300 border border-amber-500/40">
                    DIAGNOSTIC_ONLY REFERENCE TENANT
                  </span>
                )}
              </h1>
              <p className="text-xs text-slate-400 mt-1">
                Multi-source commercial & payment evidence pipeline, durable webhook inbox, and cryptographic ledger verification.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {cadenceVerdict && <CadenceSafetyBadge verdict={cadenceVerdict} />}
          <button
            onClick={loadData}
            disabled={loading}
            className="btn-secondary text-xs flex items-center gap-2"
            title="Refresh Connectors & Ledger"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-cyan-400' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Seasonal Caution Banner if active */}
      {seasonalCaution && <SeasonalCautionBanner disclosure={seasonalCaution} />}

      {/* Error Alert */}
      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-950/20 p-4 text-xs text-rose-200 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-rose-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Protected Reference Tenant Advisory */}
      {isApex && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-950/20 p-4 text-xs text-amber-200/90 flex items-start gap-3">
          <ShieldAlert className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="font-semibold text-amber-300">
              Protected Acceptance-Test Tenant: Apex Specialty Commerce
            </p>
            <p className="leading-relaxed">
              Apex Specialty Commerce contains 1,000 customers, 3,500 sales, and 11,221 sale items reserved strictly for diagnostic testing and acceptance evaluation. Tenant certification policy strictly forbids live external API calls, webhook mutations, and synthetic watermark promotions on this tenant.
            </p>
          </div>
        </div>
      )}

      {/* Tabs Navigation */}
      <div className="flex border-b border-surface-elevated text-xs font-medium">
        <button
          onClick={() => setActiveTab('credentials')}
          className={`px-4 py-2.5 border-b-2 transition-all flex items-center gap-2 ${
            activeTab === 'credentials'
              ? 'border-cyan-400 text-cyan-300 bg-cyan-950/20'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Key className="w-4 h-4" />
          <span>Source Connectors & KMS</span>
          <span className="ml-1 px-1.5 py-0.2 rounded-full bg-surface-elevated text-[10px]">
            {credentials.length}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('checkpoints')}
          className={`px-4 py-2.5 border-b-2 transition-all flex items-center gap-2 ${
            activeTab === 'checkpoints'
              ? 'border-cyan-400 text-cyan-300 bg-cyan-950/20'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Activity className="w-4 h-4" />
          <span>Sync Checkpoints & Webhooks</span>
          <span className="ml-1 px-1.5 py-0.2 rounded-full bg-surface-elevated text-[10px]">
            {checkpoints.length}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('period-close')}
          className={`px-4 py-2.5 border-b-2 transition-all flex items-center gap-2 ${
            activeTab === 'period-close'
              ? 'border-cyan-400 text-cyan-300 bg-cyan-950/20'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <History className="w-4 h-4" />
          <span>Period-Close & Evidence Ledger</span>
          <span className="ml-1 px-1.5 py-0.2 rounded-full bg-surface-elevated text-[10px]">
            {submissions.length}
          </span>
        </button>
      </div>

      {loading && <LoadingState message="Querying connector registries and ledger packages..." />}

      {/* TAB 1: SOURCE CONNECTORS */}
      {!loading && activeTab === 'credentials' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-white">Commercial & Payment Connectors</h2>
              <p className="text-xs text-slate-400">
                Credentials are context-bound and encrypted via AES-256-GCM envelope encryption. Secrets are never returned in plaintext.
              </p>
            </div>
            {!isApex && (
              <button
                onClick={() => {
                  setCredProvider('shopify');
                  setCredAccountId('');
                  setCredSecret('');
                  setShowCredModal(true);
                }}
                className="btn-primary text-xs flex items-center gap-2"
              >
                <Key className="w-3.5 h-3.5" />
                <span>Register Connector</span>
              </button>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Shopify Connector Card */}
            <div className="card-obsidian p-6 space-y-4 border border-white/[0.08] hover:border-cyan-500/30 transition-all">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-emerald-950/60 border border-emerald-500/30 flex items-center justify-center text-emerald-400 font-bold text-lg">
                    S
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-white">Shopify Commercial Orders</h3>
                    <p className="text-xs text-slate-400">GraphQL Admin API (2025-01)</p>
                  </div>
                </div>
                {shopifyCred ? (
                  <span className="px-2.5 py-1 rounded-md text-[11px] font-mono bg-emerald-950/80 text-emerald-300 border border-emerald-500/40 flex items-center gap-1.5">
                    <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                    CONFIGURED
                  </span>
                ) : (
                  <span className="px-2.5 py-1 rounded-md text-[11px] font-mono bg-slate-800 text-slate-400 border border-slate-700">
                    NOT CONFIGURED
                  </span>
                )}
              </div>

              <div className="space-y-2 text-xs pt-2 border-t border-white/[0.06]">
                <div className="flex justify-between py-1">
                  <span className="text-slate-400">Store Domain / ID:</span>
                  <span className="text-slate-200 font-mono">
                    {shopifyCred?.provider_account_id || 'test-store.myshopify.com'}
                  </span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-slate-400">Encrypted Secret:</span>
                  <span className="text-slate-400 font-mono">
                    {shopifyCred?.credentials_masked || '***REDACTED***'}
                  </span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-slate-400">KMS Envelope Key:</span>
                  <span className="text-cyan-300 font-mono">
                    {shopifyCred?.kms_key_id || 'local_kms_vault'}
                  </span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-slate-400">Granted Scopes:</span>
                  <span className="text-slate-300 font-mono">
                    {shopifyCred?.scopes?.join(', ') || 'read_orders, read_products, read_customers'}
                  </span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-slate-400">Last Key Rotation:</span>
                  <span className="text-slate-300">
                    {shopifyCred?.last_rotated_at ? new Date(shopifyCred.last_rotated_at).toLocaleString() : 'Initial Registration'}
                  </span>
                </div>
              </div>

              <div className="pt-2 flex items-center justify-end">
                <button
                  disabled={isApex}
                  onClick={() => {
                    setCredProvider('shopify');
                    setCredAccountId(shopifyCred?.provider_account_id || 'test-store.myshopify.com');
                    setShowCredModal(true);
                  }}
                  className="btn-secondary text-xs w-full justify-center"
                >
                  {shopifyCred ? 'Rotate Credentials' : 'Connect Shopify Store'}
                </button>
              </div>
            </div>

            {/* Stripe Connector Card */}
            <div className="card-obsidian p-6 space-y-4 border border-white/[0.08] hover:border-cyan-500/30 transition-all">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-indigo-950/60 border border-indigo-500/30 flex items-center justify-center text-indigo-400 font-bold text-lg">
                    ⚡
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-white">Stripe Settlement & Balances</h3>
                    <p className="text-xs text-slate-400">Payment & Balance Transactions API (2024-06-20)</p>
                  </div>
                </div>
                {stripeCred ? (
                  <span className="px-2.5 py-1 rounded-md text-[11px] font-mono bg-emerald-950/80 text-emerald-300 border border-emerald-500/40 flex items-center gap-1.5">
                    <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                    CONFIGURED
                  </span>
                ) : (
                  <span className="px-2.5 py-1 rounded-md text-[11px] font-mono bg-slate-800 text-slate-400 border border-slate-700">
                    NOT CONFIGURED
                  </span>
                )}
              </div>

              <div className="space-y-2 text-xs pt-2 border-t border-white/[0.06]">
                <div className="flex justify-between py-1">
                  <span className="text-slate-400">Stripe Account ID:</span>
                  <span className="text-slate-200 font-mono">
                    {stripeCred?.provider_account_id || 'acct_sandbox_test'}
                  </span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-slate-400">Encrypted Secret:</span>
                  <span className="text-slate-400 font-mono">
                    {stripeCred?.credentials_masked || '***REDACTED***'}
                  </span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-slate-400">KMS Envelope Key:</span>
                  <span className="text-cyan-300 font-mono">
                    {stripeCred?.kms_key_id || 'local_kms_vault'}
                  </span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-slate-400">Granted Scopes:</span>
                  <span className="text-slate-300 font-mono">
                    {stripeCred?.scopes?.join(', ') || 'charges:read, balance_transactions:read'}
                  </span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-slate-400">Last Key Rotation:</span>
                  <span className="text-slate-300">
                    {stripeCred?.last_rotated_at ? new Date(stripeCred.last_rotated_at).toLocaleString() : 'Initial Registration'}
                  </span>
                </div>
              </div>

              <div className="pt-2 flex items-center justify-end">
                <button
                  disabled={isApex}
                  onClick={() => {
                    setCredProvider('stripe');
                    setCredAccountId(stripeCred?.provider_account_id || 'acct_sandbox_test');
                    setShowCredModal(true);
                  }}
                  className="btn-secondary text-xs w-full justify-center"
                >
                  {stripeCred ? 'Rotate Credentials' : 'Connect Stripe Account'}
                </button>
              </div>
            </div>
          </div>

          {/* Envelope Encryption Architecture Callout */}
          <div className="card-obsidian p-5 rounded-xl border border-white/[0.06] bg-void/50 space-y-2">
            <div className="flex items-center gap-2 text-xs font-semibold text-cyan-300">
              <Lock className="w-4 h-4 text-cyan-400" />
              <span>Context-Bound AES-256-GCM Envelope Encryption (NIST SP 800-38D)</span>
            </div>
            <p className="text-xs text-slate-400 leading-relaxed">
              Connector credentials are never persisted in plaintext. Each credential registration generates a unique data encryption key (DEK) encrypted under a key encryption key (KEK) via the configured KMS driver (AWS KMS, GCP KMS, HashiCorp Vault, or local AES-256-GCM vault). Decryption requires exact cryptographic tenant context matching (<code className="text-cyan-400 font-mono">business_id:provider:account_id</code>).
            </p>
          </div>
        </div>
      )}

      {/* TAB 2: SYNC CHECKPOINTS & WEBHOOK INBOX */}
      {!loading && activeTab === 'checkpoints' && (
        <div className="space-y-6">
          {/* Webhook Inbox Summary Cards */}
          <div>
            <h2 className="text-base font-semibold text-white mb-1">Durable Webhook Inbox</h2>
            <p className="text-xs text-slate-400 mb-4">
              Events are recorded durably with cryptographic payload digests prior to worker execution. Mutated payloads and cross-tenant deliveries are quarantined.
            </p>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              {webhookSummaries.length === 0 ? (
                <div className="col-span-4 card-obsidian p-5 text-center text-xs text-slate-400">
                  No webhook events recorded for this tenant. Events delivered to `/api/v1/connectors/{'{provider}'}/webhook` appear here durably.
                </div>
              ) : (
                webhookSummaries.map((sum) => (
                  <React.Fragment key={sum.provider}>
                    <div className="card-obsidian p-4 border border-white/[0.06]">
                      <span className="text-[10px] font-mono uppercase text-slate-400">
                        {sum.provider} • Total Events
                      </span>
                      <p className="text-xl font-bold text-white mt-1">{sum.total_events}</p>
                    </div>
                    <div className="card-obsidian p-4 border border-white/[0.06]">
                      <span className="text-[10px] font-mono uppercase text-emerald-400">
                        {sum.provider} • Completed
                      </span>
                      <p className="text-xl font-bold text-emerald-300 mt-1">{sum.completed_events}</p>
                    </div>
                    <div className="card-obsidian p-4 border border-white/[0.06]">
                      <span className="text-[10px] font-mono uppercase text-cyan-400">
                        {sum.provider} • Pending / Processing
                      </span>
                      <p className="text-xl font-bold text-cyan-300 mt-1">
                        {sum.pending_or_processing_events}
                      </p>
                    </div>
                    <div className="card-obsidian p-4 border border-amber-500/30 bg-amber-950/10">
                      <span className="text-[10px] font-mono uppercase text-amber-400 flex items-center gap-1">
                        <AlertTriangle className="w-3 h-3" />
                        {sum.provider} • Quarantined
                      </span>
                      <p className="text-xl font-bold text-amber-300 mt-1">{sum.quarantined_events}</p>
                    </div>
                  </React.Fragment>
                ))
              )}
            </div>
          </div>

          {/* Sync Checkpoints */}
          <div>
            <h2 className="text-base font-semibold text-white mb-1">Synchronization Checkpoints</h2>
            <p className="text-xs text-slate-400 mb-4">
              Row-locked pagination checkpoints protecting incremental and initial synchronization against duplicate extraction and worker collisions.
            </p>

            {checkpoints.length === 0 ? (
              <div className="card-obsidian p-6 text-center text-xs text-slate-400">
                No synchronization checkpoints recorded for this tenant yet.
              </div>
            ) : (
              <div className="card-obsidian overflow-hidden border border-white/[0.08]">
                <table className="w-full text-left text-xs">
                  <thead className="bg-surface-elevated/60 text-slate-400 font-mono text-[11px] uppercase border-b border-white/[0.06]">
                    <tr>
                      <th className="p-3">Provider</th>
                      <th className="p-3">Sync Mode</th>
                      <th className="p-3">Period Window</th>
                      <th className="p-3">Extracted</th>
                      <th className="p-3">Status</th>
                      <th className="p-3">Worker ID</th>
                      <th className="p-3">Cursor Hash</th>
                      <th className="p-3">Completed At</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04] text-slate-300 font-mono">
                    {checkpoints.map((cp) => (
                      <tr key={cp.id} className="hover:bg-white/[0.02] transition-colors">
                        <td className="p-3 font-semibold text-white">{cp.provider.toUpperCase()}</td>
                        <td className="p-3 text-slate-400">{cp.sync_mode}</td>
                        <td className="p-3 text-[11px] text-slate-300">
                          {new Date(cp.period_start).toLocaleDateString()} →{' '}
                          {new Date(cp.period_end).toLocaleDateString()}
                        </td>
                        <td className="p-3 text-cyan-300 font-semibold">{cp.records_extracted}</td>
                        <td className="p-3">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] ${
                              cp.status === 'COMPLETED'
                                ? 'bg-emerald-950/60 text-emerald-300 border border-emerald-500/30'
                                : cp.status === 'IN_PROGRESS'
                                ? 'bg-cyan-950/60 text-cyan-300 border border-cyan-500/30'
                                : 'bg-rose-950/60 text-rose-300 border border-rose-500/30'
                            }`}
                          >
                            {cp.status}
                          </span>
                        </td>
                        <td className="p-3 text-slate-400">{cp.worker_id || '—'}</td>
                        <td className="p-3 text-[11px] text-slate-400" title={cp.current_cursor || ''}>
                          {cp.current_cursor ? `${cp.current_cursor.slice(0, 16)}...` : '—'}
                        </td>
                        <td className="p-3 text-slate-400">
                          {cp.completed_at ? new Date(cp.completed_at).toLocaleString() : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* TAB 3: PERIOD-CLOSE & EVIDENCE LEDGER */}
      {!loading && activeTab === 'period-close' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-white">Immutable Period-Close Evidence Ledger</h2>
              <p className="text-xs text-slate-400">
                Cryptographically signed packages binding cross-source commercial and payment evidence to the PostgreSQL database.
              </p>
            </div>
          </div>

          {submissions.length === 0 ? (
            <div className="card-obsidian p-8 text-center space-y-3">
              <FileCheck className="w-10 h-10 text-slate-500 mx-auto" />
              <h3 className="text-sm font-semibold text-white">No Signed Manifest Packages Found</h3>
              <p className="text-xs text-slate-400 max-w-md mx-auto">
                Period-close evidence packages are created during multi-source period close rehearsal or certification.
              </p>
            </div>
          ) : (
            <div className="card-obsidian overflow-hidden border border-white/[0.08]">
              <table className="w-full text-left text-xs">
                <thead className="bg-surface-elevated/60 text-slate-400 font-mono text-[11px] uppercase border-b border-white/[0.06]">
                  <tr>
                    <th className="p-3">Package / Manifest ID</th>
                    <th className="p-3">Version</th>
                    <th className="p-3">Period Window</th>
                    <th className="p-3">Persisted Rows</th>
                    <th className="p-3">Gross Total</th>
                    <th className="p-3">Signature</th>
                    <th className="p-3">Lineage</th>
                    <th className="p-3 text-right">Verification Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04] text-slate-300 font-mono">
                  {submissions.map((sub) => (
                    <tr key={sub.manifest_id} className="hover:bg-white/[0.02] transition-colors">
                      <td className="p-3">
                        <div className="flex items-center gap-1.5 font-mono text-cyan-300">
                          <span>{sub.manifest_id.slice(0, 16)}...</span>
                          <button
                            onClick={() => copyToClipboard(sub.manifest_id, sub.manifest_id)}
                            className="text-slate-400 hover:text-white"
                            title="Copy full package ID"
                          >
                            {copiedId === sub.manifest_id ? (
                              <Check className="w-3.5 h-3.5 text-emerald-400" />
                            ) : (
                              <Copy className="w-3.5 h-3.5" />
                            )}
                          </button>
                        </div>
                      </td>
                      <td className="p-3 font-semibold text-white">v{sub.version_number}</td>
                      <td className="p-3 text-[11px] text-slate-300">
                        {sub.period_start ? new Date(sub.period_start).toLocaleDateString() : '—'} →{' '}
                        {sub.period_end ? new Date(sub.period_end).toLocaleDateString() : '—'}
                      </td>
                      <td className="p-3 text-slate-200">{sub.persisted_row_count ?? '—'}</td>
                      <td className="p-3 text-emerald-300 font-semibold">
                        {sub.persisted_gross_total ? `$${formatNumber(parseFloat(sub.persisted_gross_total))}` : '—'}
                      </td>
                      <td className="p-3">
                        {sub.signature_valid ? (
                          <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-950/60 text-emerald-300 border border-emerald-500/30 flex items-center gap-1 w-fit">
                            <ShieldCheck className="w-3 h-3 text-emerald-400" />
                            Ed25519 Valid
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded text-[10px] bg-rose-950/60 text-rose-300 border border-rose-500/30">
                            INVALID
                          </span>
                        )}
                      </td>
                      <td className="p-3">
                        {sub.is_superseded ? (
                          <span className="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-slate-400 border border-slate-700">
                            Superseded
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded text-[10px] bg-cyan-950/60 text-cyan-300 border border-cyan-500/30 font-semibold">
                            ACTIVE HEAD
                          </span>
                        )}
                      </td>
                      <td className="p-3 text-right">
                        <button
                          onClick={() => handleVerifyHistorical(sub.manifest_id)}
                          className="btn-secondary text-[11px] py-1 px-2.5 inline-flex items-center gap-1.5"
                        >
                          <ShieldCheck className="w-3.5 h-3.5 text-cyan-400" />
                          <span>Verify Package</span>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* CREDENTIAL REGISTRATION MODAL */}
      {showCredModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-void/80 backdrop-blur-sm">
          <div className="card-obsidian w-full max-w-lg p-6 space-y-5 border border-cyan-500/30 shadow-2xl relative">
            <button
              onClick={() => setShowCredModal(false)}
              className="absolute top-4 right-4 text-slate-400 hover:text-white"
            >
              <X className="w-5 h-5" />
            </button>

            <div>
              <span className="text-[10px] font-mono uppercase text-cyan-400 tracking-wider">
                Envelope Encryption Registration
              </span>
              <h3 className="text-lg font-bold text-white mt-1">
                Register Connector Credentials
              </h3>
              <p className="text-xs text-slate-400 mt-1">
                Context-bound envelope encryption via AES-256-GCM.
              </p>
            </div>

            {credSuccessMsg && (
              <div className="p-3 rounded-lg bg-emerald-950/60 border border-emerald-500/40 text-emerald-300 text-xs flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                <span>{credSuccessMsg}</span>
              </div>
            )}

            {credErrorMsg && (
              <div className="p-3 rounded-lg bg-rose-950/60 border border-rose-500/40 text-rose-300 text-xs flex items-center gap-2">
                <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
                <span>{credErrorMsg}</span>
              </div>
            )}

            <form onSubmit={handleSaveCredential} className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-300 font-mono mb-1.5">Provider Source</label>
                <select
                  value={credProvider}
                  onChange={(e) => setCredProvider(e.target.value as 'shopify' | 'stripe')}
                  className="input-obsidian w-full text-xs"
                >
                  <option value="shopify">Shopify GraphQL Admin API</option>
                  <option value="stripe">Stripe Test Mode</option>
                </select>
              </div>

              <div>
                <label className="block text-slate-300 font-mono mb-1.5">
                  {credProvider === 'shopify' ? 'Shopify Store Domain' : 'Stripe Account ID'}
                </label>
                <input
                  type="text"
                  required
                  value={credAccountId}
                  onChange={(e) => setCredAccountId(e.target.value)}
                  placeholder={credProvider === 'shopify' ? 'store.myshopify.com' : 'acct_1234567890'}
                  className="input-obsidian w-full text-xs"
                />
              </div>

              <div>
                <label className="block text-slate-300 font-mono mb-1.5">
                  {credProvider === 'shopify' ? 'Admin API Access Token' : 'Restricted API Secret Key'}
                </label>
                <input
                  type="password"
                  required
                  value={credSecret}
                  onChange={(e) => setCredSecret(e.target.value)}
                  placeholder={credProvider === 'shopify' ? 'shpat_xxxxxxxxxxxx' : 'sk_test_xxxxxxxxxxxx'}
                  className="input-obsidian w-full text-xs"
                />
              </div>

              <div>
                <label className="block text-slate-300 font-mono mb-1.5">KMS Key Identifier</label>
                <select
                  value={credKmsKey}
                  onChange={(e) => setCredKmsKey(e.target.value)}
                  className="input-obsidian w-full text-xs"
                >
                  <option value="local_kms_vault">Local AES-256-GCM Vault (Development/Sandbox)</option>
                  <option value="arn:aws:kms:us-east-1:123456789012:key/nexus-prod">AWS KMS Production Key</option>
                  <option value="projects/nexus/locations/global/keyRings/prod/cryptoKeys/nexus">GCP Cloud KMS Production Key</option>
                  <option value="vault:transit:nexus-prod">HashiCorp Vault Transit Key</option>
                </select>
              </div>

              <div>
                <label className="block text-slate-300 font-mono mb-1.5">Granted Scopes (Comma-separated)</label>
                <input
                  type="text"
                  value={credScopes}
                  onChange={(e) => setCredScopes(e.target.value)}
                  placeholder="read_orders, read_products, charges:read"
                  className="input-obsidian w-full text-xs"
                />
              </div>

              <div className="pt-3 flex items-center justify-end gap-3 border-t border-white/[0.08]">
                <button
                  type="button"
                  onClick={() => setShowCredModal(false)}
                  className="btn-secondary text-xs"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={credSaving}
                  className="btn-primary text-xs flex items-center gap-2"
                >
                  {credSaving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Lock className="w-3.5 h-3.5" />}
                  <span>{credSaving ? 'Encrypting & Storing...' : 'Save Encrypted Credential'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* HISTORICAL VERIFICATION RESULT MODAL */}
      {verifyingManifestId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-void/80 backdrop-blur-sm">
          <div className="card-obsidian w-full max-w-xl p-6 space-y-5 border border-cyan-500/30 shadow-2xl relative">
            <button
              onClick={() => setVerifyingManifestId(null)}
              className="absolute top-4 right-4 text-slate-400 hover:text-white"
            >
              <X className="w-5 h-5" />
            </button>

            <div>
              <span className="text-[10px] font-mono uppercase text-cyan-400 tracking-wider">
                Cryptographic Evidence Audit
              </span>
              <h3 className="text-lg font-bold text-white mt-1">
                Historical Package Verification
              </h3>
              <p className="text-xs text-slate-400 mt-1 font-mono">
                {verifyingManifestId}
              </p>
            </div>

            {verifyLoading && (
              <div className="py-8 text-center space-y-3">
                <RefreshCw className="w-8 h-8 text-cyan-400 animate-spin mx-auto" />
                <p className="text-xs text-slate-300">
                  Verifying Ed25519 signature, KMS key state, and live PostgreSQL dataset divergence...
                </p>
              </div>
            )}

            {verifyError && (
              <div className="p-4 rounded-lg bg-rose-950/60 border border-rose-500/40 text-rose-300 text-xs flex items-center gap-3">
                <AlertCircle className="w-5 h-5 text-rose-400 shrink-0" />
                <span>{verifyError}</span>
              </div>
            )}

            {verifyResult && (
              <div className="space-y-4 text-xs">
                {/* Overall Verification Status Banner */}
                {verifyResult.historical_signature_valid && !verifyResult.current_dataset_diverged ? (
                  <div className="p-4 rounded-xl bg-emerald-950/40 border border-emerald-500/40 text-emerald-200 flex items-start gap-3">
                    <ShieldCheck className="w-6 h-6 text-emerald-400 shrink-0 mt-0.5" />
                    <div>
                      <p className="font-semibold text-emerald-300 text-sm">
                        Cryptographically Valid & Zero Divergence Detected
                      </p>
                      <p className="text-xs mt-1 leading-relaxed">
                        The historical Ed25519 signature is authentic and the current persisted database records match the signed canonical digest exactly. No post-close mutations have occurred.
                      </p>
                    </div>
                  </div>
                ) : verifyResult.current_dataset_diverged ? (
                  <div className="p-4 rounded-xl bg-amber-950/40 border border-amber-500/40 text-amber-200 flex items-start gap-3">
                    <AlertTriangle className="w-6 h-6 text-amber-400 shrink-0 mt-0.5" />
                    <div>
                      <p className="font-semibold text-amber-300 text-sm">
                        Historical Signature Authentic • Source Dataset Divergence Detected
                      </p>
                      <p className="text-xs mt-1 leading-relaxed">
                        The historical package signature remains valid for the exact evidence validated at period-close. However, current database records have mutated since the package was signed, invalidating current certification.
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-500/40 text-rose-200 flex items-start gap-3">
                    <AlertCircle className="w-6 h-6 text-rose-400 shrink-0 mt-0.5" />
                    <div>
                      <p className="font-semibold text-rose-300 text-sm">
                        Historical Signature Verification Failed
                      </p>
                      <p className="text-xs mt-1 leading-relaxed">
                        The Ed25519 signature does not match the canonical manifest content. The evidence package may have been tampered with.
                      </p>
                    </div>
                  </div>
                )}

                {/* Audit Attributes Grid */}
                <div className="card-obsidian p-4 rounded-xl border border-white/[0.06] space-y-2.5 font-mono">
                  <div className="flex justify-between py-1 border-b border-white/[0.04]">
                    <span className="text-slate-400">Package Version:</span>
                    <span className="text-white font-semibold">v{verifyResult.version_number}</span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-white/[0.04]">
                    <span className="text-slate-400">Historical Signature:</span>
                    <span className={verifyResult.historical_signature_valid ? 'text-emerald-400 font-semibold' : 'text-rose-400 font-semibold'}>
                      {verifyResult.historical_signature_valid ? 'VALID (Ed25519)' : 'INVALID'}
                    </span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-white/[0.04]">
                    <span className="text-slate-400">Signing Key ID:</span>
                    <span className="text-cyan-300">{verifyResult.signing_key_id}</span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-white/[0.04]">
                    <span className="text-slate-400">Key Status at Signing:</span>
                    <span className="text-slate-200">{verifyResult.key_status_at_signing}</span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-white/[0.04]">
                    <span className="text-slate-400">Current Key Status:</span>
                    <span className="text-slate-200">{verifyResult.current_key_status}</span>
                  </div>
                  <div className="flex justify-between py-1 border-b border-white/[0.04]">
                    <span className="text-slate-400">Canonical Digest Intact:</span>
                    <span className={verifyResult.canonical_digest_matches ? 'text-emerald-400' : 'text-rose-400'}>
                      {verifyResult.canonical_digest_matches ? 'MATCH' : 'MISMATCH'}
                    </span>
                  </div>
                  <div className="flex justify-between py-1">
                    <span className="text-slate-400">Current Dataset Diverged:</span>
                    <span className={verifyResult.current_dataset_diverged ? 'text-amber-400 font-semibold' : 'text-emerald-400 font-semibold'}>
                      {verifyResult.current_dataset_diverged ? 'YES (Source Mutated)' : 'NO (Exact Match)'}
                    </span>
                  </div>
                </div>

                {verifyResult.divergence_details && (
                  <div className="p-3 rounded-lg bg-void border border-white/[0.08] text-[11px] text-slate-300 font-mono space-y-1">
                    <span className="text-amber-400 font-semibold">Divergence Details:</span>
                    <p>{verifyResult.divergence_details}</p>
                  </div>
                )}

                <div className="pt-2 flex justify-end">
                  <button
                    onClick={() => setVerifyingManifestId(null)}
                    className="btn-secondary text-xs"
                  >
                    Close Verification
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
