import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Building2,
  Database,
  CheckCircle2,
  AlertTriangle,
  Save,
  RefreshCw,
  Layers,
  ArrowRight,
  UserCheck,
  Calendar,
  Globe,
  Coins,
  Clock,
  X,
  ShieldAlert,
  LogIn,
  Lock,
  Copy,
  Check,
  Trash2,
  Sliders,
  AlertOctagon,
  ShieldCheck,
  ExternalLink,
} from 'lucide-react';
import {
  getOnboardingStatus,
  updateBusiness,
  deleteBusiness,
  OnboardingStatusResponse,
} from '../services/api';
import { AuthService, UserProfileResponse } from '../services/auth';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorBoundary } from '../components/common/ErrorBoundary';

interface BusinessSettingsPageProps {
  onNavigate: (route: string) => void;
}

const MONTH_NAMES = [
  'January (Standard Calendar Year)',
  'February',
  'March',
  'April (UK, India, Japan corporate standard)',
  'May',
  'June',
  'July (Australia, New Zealand standard)',
  'August',
  'September',
  'October (US Federal standard)',
  'November',
  'December',
];

const POPULAR_CURRENCIES = [
  { code: 'USD', label: 'USD — US Dollar ($)' },
  { code: 'EUR', label: 'EUR — Euro (€)' },
  { code: 'GBP', label: 'GBP — British Pound (£)' },
  { code: 'CAD', label: 'CAD — Canadian Dollar (CA$)' },
  { code: 'AUD', label: 'AUD — Australian Dollar (A$)' },
  { code: 'INR', label: 'INR — Indian Rupee (₹)' },
  { code: 'JPY', label: 'JPY — Japanese Yen (¥)' },
  { code: 'CHF', label: 'CHF — Swiss Franc (CHF)' },
  { code: 'SGD', label: 'SGD — Singapore Dollar (S$)' },
];

const POPULAR_TIMEZONES = [
  'UTC',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'Europe/London',
  'Europe/Berlin',
  'Europe/Paris',
  'Asia/Kolkata',
  'Asia/Singapore',
  'Asia/Tokyo',
  'Australia/Sydney',
];

const INDUSTRY_DOMAINS = [
  'Technology & Software (SaaS)',
  'E-Commerce & Retail',
  'Manufacturing & Industrial',
  'Healthcare & Life Sciences',
  'Financial Services & Fintech',
  'Logistics & Supply Chain',
  'Professional & Business Services',
  'Consumer Goods & Apparel',
  'Hospitality & Leisure',
];

const BUSINESS_MODELS = [
  'B2B Enterprise SaaS',
  'B2C E-Commerce & Retail',
  'B2B Wholesale & Distribution',
  'Marketplace & Multi-Sided Platform',
  'Direct-to-Consumer (D2C)',
  'Hybrid B2B / B2C Model',
];

export const BusinessSettingsPage: React.FC<BusinessSettingsPageProps> = ({ onNavigate }) => {
  const [activeTab, setActiveTab] = useState<'general' | 'localization' | 'governance' | 'danger'>('general');

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [authRequired, setAuthRequired] = useState(false);

  const [profile, setProfile] = useState<UserProfileResponse | null>(null);
  const [status, setStatus] = useState<OnboardingStatusResponse | null>(null);

  // Form Data State
  const [formData, setFormData] = useState({
    name: '',
    industry: 'Technology & Software (SaaS)',
    country: 'United States',
    currency: 'USD',
    timezone: 'UTC',
    business_type: 'B2B Enterprise SaaS',
    fiscal_year_start: 1,
  });
  const [initialFormData, setInitialFormData] = useState(formData);

  // Clipboard copy feedback
  const [copiedField, setCopiedField] = useState<string | null>(null);

  // Danger Zone / Delete Modal State
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleteConfirmationInput, setDeleteConfirmationInput] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const [userProfileResult, onbStatusResult] = await Promise.allSettled([
        AuthService.getMe(),
        getOnboardingStatus(),
      ]);

      let userProfile: UserProfileResponse | null = null;
      let onbStatus: OnboardingStatusResponse | null = null;

      if (userProfileResult.status === 'fulfilled') {
        userProfile = userProfileResult.value;
        setProfile(userProfile);
        setAuthRequired(false);
      } else {
        const reason = userProfileResult.reason;
        if (reason?.status === 401 || reason?.message?.toLowerCase().includes('token') || reason?.message?.toLowerCase().includes('auth')) {
          setAuthRequired(true);
        }
      }

      if (onbStatusResult.status === 'fulfilled') {
        onbStatus = onbStatusResult.value;
        setStatus(onbStatus);
      }

      const bizObj =
        onbStatus?.business ||
        userProfile?.tenants?.[0]?.businesses?.find(
          (b: any) => b.id === (onbStatus?.business_id || AuthService.getActiveBusinessId())
        ) ||
        userProfile?.tenants?.[0]?.businesses?.[0];

      if (bizObj || onbStatus?.business_name) {
        const loadedData = {
          name: bizObj?.name || onbStatus?.business_name || '',
          industry: bizObj?.industry || 'Technology & Software (SaaS)',
          country: (bizObj as any)?.country || 'United States',
          currency: bizObj?.currency || 'USD',
          timezone: (bizObj as any)?.timezone || 'UTC',
          business_type: (bizObj as any)?.business_type || 'B2B Enterprise SaaS',
          fiscal_year_start: Number((bizObj as any)?.fiscal_year_start) || 1,
        };
        setFormData(loadedData);
        setInitialFormData(loadedData);
      }
    } catch (err: any) {
      console.warn('Failed to load business profile:', err);
      setError(err?.message || 'Failed to load business workspace configuration.');
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await loadData();
  };

  const handleCopy = (text: string, fieldId: string) => {
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedField(fieldId);
    setTimeout(() => setCopiedField(null), 2000);
  };

  const isDirty = useMemo(() => {
    return (
      formData.name !== initialFormData.name ||
      formData.industry !== initialFormData.industry ||
      formData.country !== initialFormData.country ||
      formData.currency !== initialFormData.currency ||
      formData.timezone !== initialFormData.timezone ||
      formData.business_type !== initialFormData.business_type ||
      Number(formData.fiscal_year_start) !== Number(initialFormData.fiscal_year_start)
    );
  }, [formData, initialFormData]);

  const activeBusinessId = useMemo(() => {
    return (
      status?.business?.id ||
      status?.business_id ||
      profile?.tenants?.[0]?.businesses?.find(
        (b: any) => b.id === AuthService.getActiveBusinessId()
      )?.id ||
      profile?.tenants?.[0]?.businesses?.[0]?.id ||
      AuthService.getActiveBusinessId() ||
      'biz_default'
    );
  }, [status, profile]);

  const hasValidBusinessId = useMemo(() => {
    return Boolean(
      status?.business?.id ||
      status?.business_id ||
      profile?.tenants?.[0]?.businesses?.find(
        (b: any) => b.id === AuthService.getActiveBusinessId()
      )?.id ||
      profile?.tenants?.[0]?.businesses?.[0]?.id
    );
  }, [status, profile]);

  const confirmedWorkspaceName = useMemo(() => {
    return (
      initialFormData.name.trim() ||
      status?.business?.name?.trim() ||
      status?.business_name?.trim() ||
      ''
    );
  }, [initialFormData.name, status]);

  const currentOrg = profile?.tenants?.[0];
  const userRole = currentOrg?.role?.toLowerCase() || (authRequired ? 'unauthenticated' : profile ? 'member' : 'unknown');
  const isOwner = userRole === 'owner';

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name.trim()) {
      setError('Business legal name cannot be empty.');
      return;
    }

    if (formData.fiscal_year_start < 1 || formData.fiscal_year_start > 12) {
      setError('Fiscal year start month must be between 1 and 12.');
      return;
    }

    if (authRequired) {
      setError('An active authenticated workspace session is required to save configuration.');
      return;
    }

    setSaving(true);
    setError(null);
    setSuccess(null);

    try {
      await updateBusiness(activeBusinessId, {
        name: formData.name.trim(),
        industry: formData.industry,
        country: formData.country,
        currency: formData.currency,
        timezone: formData.timezone,
        business_type: formData.business_type,
        fiscal_year_start: Number(formData.fiscal_year_start),
      });

      setSuccess('Business workspace configuration committed successfully.');
      setInitialFormData(formData);
      setTimeout(() => setSuccess(null), 4000);
    } catch (err: any) {
      setError(err?.message || 'Failed to update business configuration.');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteBusiness = async () => {
    if (!confirmedWorkspaceName) {
      setDeleteError('No confirmed workspace name available to verify deletion.');
      return;
    }

    if (deleteConfirmationInput.trim() !== confirmedWorkspaceName) {
      setDeleteError(`Please type "${confirmedWorkspaceName}" exactly to confirm.`);
      return;
    }

    if (!hasValidBusinessId) {
      setDeleteError('No valid business workspace loaded to delete.');
      return;
    }

    setDeleting(true);
    setDeleteError(null);

    try {
      await deleteBusiness(activeBusinessId);
      setShowDeleteModal(false);
      onNavigate('/onboarding');
    } catch (err: any) {
      setDeleteError(err?.message || 'Failed to delete business workspace.');
    } finally {
      setDeleting(false);
    }
  };

  const datasetCount = status?.data_readiness?.total_datasets ?? status?.datasets?.length ?? 0;
  const rowCount = status?.data_readiness?.total_rows ?? 0;
  const readinessStatus = (status?.data_readiness?.status || status?.data_readiness_status || 'ACTIVE').toUpperCase();

  if (loading) {
    return (
      <div className="py-20 flex justify-center">
        <LoadingState message="Loading tenant workspace configuration..." />
      </div>
    );
  }

  return (
    <ErrorBoundary>
      <div className="space-y-6 animate-in fade-in duration-200">
        {/* Executive Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-white/[0.08] pb-5">
          <div>
            <div className="flex flex-wrap items-center gap-2 mb-2">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-800/50 text-cyan-400 font-mono text-[11px] font-semibold">
                <Building2 className="w-3.5 h-3.5" />
                <span>TENANT SOVEREIGN WORKSPACE</span>
              </span>
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-surface border border-white/[0.08] text-slate-400 font-mono text-[10px]">
                <ShieldCheck className="w-3 h-3 text-emerald-400" />
                <span>Enterprise Multi-Tenant Boundaries</span>
              </span>
            </div>

            <h1 className="text-2xl sm:text-3xl font-bold text-white tracking-tight font-sans">
              Workspace &amp; Business Settings
            </h1>
            <p className="text-xs sm:text-sm text-slate-400 mt-1 max-w-2xl font-sans leading-relaxed">
              Enterprise organization parameters, financial localization, schema governance, and deterministic intelligence scoping.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleRefresh}
              disabled={isRefreshing}
              className="btn-secondary text-xs h-9 px-3 inline-flex items-center gap-1.5"
              title="Refresh workspace profile"
            >
              <RefreshCw className={`w-3.5 h-3.5 text-cyan-400 ${isRefreshing ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline">Refresh Profile</span>
            </button>

            <button
              type="button"
              onClick={() => onNavigate('/onboarding')}
              className="btn-secondary text-xs h-9 px-3.5 inline-flex items-center gap-1.5"
            >
              <span>Onboarding Wizard</span>
              <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
            </button>
          </div>
        </div>

        {/* 21st.dev Precision Obsidian Metric Scorecard */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Card 1: Tenant Organization */}
          <div className="p-4 rounded-xl bg-void/60 border border-white/[0.08] flex flex-col justify-between space-y-3">
            <div className="flex items-center justify-between text-slate-400">
              <span className="text-[10px] font-mono tracking-wider uppercase font-semibold text-slate-400">
                TENANT ORGANIZATION
              </span>
              <div className="w-7 h-7 rounded-lg bg-cyan-950/60 border border-cyan-800/40 flex items-center justify-center text-cyan-400">
                <Building2 className="w-3.5 h-3.5" />
              </div>
            </div>
            <div>
              <div className="text-lg font-bold font-sans tracking-tight text-white truncate">
                {currentOrg?.organization_name || (authRequired ? 'Session Required' : currentOrg?.organization_id ? `Organization (${currentOrg.organization_id})` : 'Primary Organization (Unverified)')}
              </div>
              <div className="text-[11px] text-slate-400 mt-0.5 font-mono truncate">
                {currentOrg?.organization_slug ? `slug: ${currentOrg.organization_slug}` : authRequired ? 'slug: unauthenticated' : 'slug: default (unverified)'}
              </div>
            </div>
            <div className="pt-2 border-t border-white/[0.04] text-[10px] font-mono text-cyan-400/80">
              {currentOrg ? 'Multi-Tenant Isolated' : authRequired ? 'Auth Required' : 'Isolation Pending'}
            </div>
          </div>

          {/* Card 2: Authorized Role */}
          <div className="p-4 rounded-xl bg-void/60 border border-white/[0.08] flex flex-col justify-between space-y-3">
            <div className="flex items-center justify-between text-slate-400">
              <span className="text-[10px] font-mono tracking-wider uppercase font-semibold text-slate-400">
                ACCESS &amp; ROLE POSTURE
              </span>
              <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${
                authRequired
                  ? 'bg-amber-950/60 border border-amber-800/40 text-amber-400'
                  : 'bg-emerald-950/60 border border-emerald-800/40 text-emerald-400'
              }`}>
                <UserCheck className="w-3.5 h-3.5" />
              </div>
            </div>
            <div>
              <div className="text-lg font-bold font-mono tracking-tight uppercase flex items-center gap-2">
                <span className={authRequired ? 'text-amber-300' : 'text-emerald-300'}>{userRole}</span>
                <span className={`px-1.5 py-0.2 rounded-full border text-[9px] ${
                  authRequired
                    ? 'bg-amber-950/80 border-amber-600/40 text-amber-400'
                    : currentOrg?.role
                    ? 'bg-emerald-950/80 border-emerald-600/40 text-emerald-400'
                    : 'bg-slate-800 border-white/[0.08] text-slate-400'
                }`}>
                  {authRequired ? 'SESSION REQ' : currentOrg?.role ? 'VERIFIED' : 'DEFAULT'}
                </span>
              </div>
              <div className="text-[11px] text-slate-400 mt-0.5 font-mono truncate">
                {authRequired ? 'Sign in to verify RBAC role' : profile?.user?.email || 'authenticated user'}
              </div>
            </div>
            <div className={`pt-2 border-t border-white/[0.04] text-[10px] font-mono ${
              authRequired ? 'text-amber-400/80' : 'text-emerald-400/80'
            }`}>
              {authRequired ? 'Session Required' : isOwner ? 'Owner Authorized' : 'RBAC Authorized'}
            </div>
          </div>

          {/* Card 3: Data Readiness */}
          <div className="p-4 rounded-xl bg-void/60 border border-white/[0.08] flex flex-col justify-between space-y-3">
            <div className="flex items-center justify-between text-slate-400">
              <span className="text-[10px] font-mono tracking-wider uppercase font-semibold text-slate-400">
                DATA SCHEMA READINESS
              </span>
              <div className="w-7 h-7 rounded-lg bg-cyan-950/60 border border-cyan-800/40 flex items-center justify-center text-cyan-400">
                <Database className="w-3.5 h-3.5" />
              </div>
            </div>
            <div>
              <div className="text-lg font-bold font-mono tracking-tight text-white flex items-center gap-2">
                <span
                  className={`w-2 h-2 rounded-full ${
                    !status
                      ? 'bg-slate-500'
                      : readinessStatus === 'READY'
                      ? 'bg-emerald-400'
                      : 'bg-amber-400 animate-pulse'
                  }`}
                />
                <span>{readinessStatus}</span>
              </div>
              <div className="text-[11px] text-slate-400 mt-0.5 font-sans">
                {status ? `${datasetCount} Datasets • ${rowCount.toLocaleString()} Rows` : '— Datasets • — Rows'}
              </div>
            </div>
            <div className="pt-2 border-t border-white/[0.04] text-[10px] font-mono text-cyan-400/80">
              {status ? 'Deterministic Schema Ready' : 'Data Gateway Offline'}
            </div>
          </div>

          {/* Card 4: Synchronization Status */}
          <div className="p-4 rounded-xl bg-void/60 border border-white/[0.08] flex flex-col justify-between space-y-3">
            <div className="flex items-center justify-between text-slate-400">
              <span className="text-[10px] font-mono tracking-wider uppercase font-semibold text-slate-400">
                CONFIG SYNCHRONIZATION
              </span>
              <div
                className={`w-7 h-7 rounded-lg flex items-center justify-center ${
                  authRequired
                    ? 'bg-amber-950/60 border border-amber-800/40 text-amber-400'
                    : isDirty
                    ? 'bg-amber-950/60 border border-amber-800/40 text-amber-400'
                    : 'bg-emerald-950/60 border border-emerald-800/40 text-emerald-400'
                }`}
              >
                {authRequired ? <ShieldAlert className="w-3.5 h-3.5" /> : isDirty ? <Sliders className="w-3.5 h-3.5" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
              </div>
            </div>
            <div>
              <div
                className={`text-lg font-bold font-mono tracking-tight ${
                  authRequired || isDirty ? 'text-amber-300' : 'text-emerald-300'
                }`}
              >
                {authRequired ? 'Session Required' : isDirty ? 'Unsaved Edits' : 'Synchronized'}
              </div>
              <div className="text-[11px] text-slate-400 mt-0.5 font-sans">
                {authRequired ? 'Sign in to sync configuration' : `${formData.currency} • Month ${formData.fiscal_year_start} Start`}
              </div>
            </div>
            <div
              className={`pt-2 border-t border-white/[0.04] text-[10px] font-mono ${
                authRequired ? 'text-amber-400' : isDirty ? 'text-amber-400' : 'text-slate-400'
              }`}
            >
              {authRequired ? 'Sync Blocked' : isDirty ? 'Requires Save Action' : 'Server State Synced'}
            </div>
          </div>
        </div>

        {/* Dignified Workspace Session Required Notice */}
        {authRequired && (
          <div className="p-4 sm:p-5 rounded-2xl bg-amber-950/20 border border-amber-600/40 text-amber-200 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="flex items-start gap-3">
              <ShieldAlert className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <h3 className="font-semibold text-white text-sm font-sans">
                  Workspace Authentication Required for Settings Management
                </h3>
                <p className="text-xs text-amber-200/80 font-sans leading-relaxed max-w-2xl">
                  Business workspace settings, tenant boundaries, and financial configurations require an active workspace session. Please sign in to modify organizational parameters.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 self-start sm:self-auto shrink-0">
              <button
                type="button"
                onClick={() => onNavigate('/login')}
                className="btn-primary text-xs h-8 px-3 inline-flex items-center gap-1.5"
              >
                <LogIn className="w-3.5 h-3.5" />
                <span>Sign In to Workspace</span>
              </button>
              <button
                type="button"
                onClick={handleRefresh}
                className="btn-secondary text-xs h-8 px-3 inline-flex items-center gap-1.5"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span>Retry</span>
              </button>
            </div>
          </div>
        )}

        {/* Success Alert */}
        {success && (
          <div className="p-4 rounded-xl bg-emerald-950/60 border border-emerald-500/40 text-emerald-200 text-xs flex items-center justify-between animate-in fade-in duration-150">
            <div className="flex items-center gap-2.5">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span className="font-medium font-sans">{success}</span>
            </div>
            <button onClick={() => setSuccess(null)} className="text-emerald-400 hover:text-white transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Error Alert */}
        {error && !authRequired && (
          <div className="p-4 rounded-xl bg-rose-950/60 border border-rose-500/40 text-rose-200 text-xs flex items-center justify-between animate-in fade-in duration-150">
            <div className="flex items-center gap-2.5">
              <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
              <span className="font-medium font-sans">{error}</span>
            </div>
            <button onClick={() => setError(null)} className="text-rose-400 hover:text-white transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Section Navigation Tabs */}
        <div className="border-b border-white/[0.08] flex items-center gap-1 overflow-x-auto pb-px">
          <button
            type="button"
            onClick={() => setActiveTab('general')}
            className={`px-4 py-2.5 text-xs font-semibold rounded-t-lg transition-all flex items-center gap-2 whitespace-nowrap border-b-2 ${
              activeTab === 'general'
                ? 'border-cyan-400 text-cyan-300 bg-void/60'
                : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-void/30'
            }`}
          >
            <Building2 className="w-3.5 h-3.5" />
            <span>General Profile</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('localization')}
            className={`px-4 py-2.5 text-xs font-semibold rounded-t-lg transition-all flex items-center gap-2 whitespace-nowrap border-b-2 ${
              activeTab === 'localization'
                ? 'border-cyan-400 text-cyan-300 bg-void/60'
                : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-void/30'
            }`}
          >
            <Coins className="w-3.5 h-3.5" />
            <span>Financial &amp; Localization</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('governance')}
            className={`px-4 py-2.5 text-xs font-semibold rounded-t-lg transition-all flex items-center gap-2 whitespace-nowrap border-b-2 ${
              activeTab === 'governance'
                ? 'border-cyan-400 text-cyan-300 bg-void/60'
                : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-void/30'
            }`}
          >
            <Database className="w-3.5 h-3.5" />
            <span>Tenant Boundaries &amp; Data</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('danger')}
            className={`px-4 py-2.5 text-xs font-semibold rounded-t-lg transition-all flex items-center gap-2 whitespace-nowrap border-b-2 ${
              activeTab === 'danger'
                ? 'border-rose-400 text-rose-300 bg-void/60'
                : 'border-transparent text-slate-400 hover:text-rose-300 hover:bg-void/30'
            }`}
          >
            <AlertOctagon className="w-3.5 h-3.5 text-rose-400" />
            <span>Administrative Danger Zone</span>
          </button>
        </div>

        {/* ======================================================== */}
        {/* TAB 1: GENERAL PROFILE */}
        {/* ======================================================== */}
        {activeTab === 'general' && (
          <form onSubmit={handleSave} className="card-obsidian p-6 space-y-6">
            <div className="border-b border-white/[0.08] pb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <h2 className="text-base font-bold text-white font-sans">Business Identity &amp; Industry Scope</h2>
                <p className="text-xs text-slate-400 mt-0.5 font-sans">
                  Configures the commercial entity name, industry ontology, and business model for causal reasoning.
                </p>
              </div>
              {isDirty && (
                <span className="px-2.5 py-0.5 rounded-full bg-amber-500/20 border border-amber-500/40 text-[10px] font-mono text-amber-300 font-semibold self-start sm:self-auto animate-pulse">
                  Unsaved Changes
                </span>
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              {/* Business Legal Name */}
              <div className="space-y-1.5">
                <label className="text-xs font-mono text-slate-300 flex items-center justify-between">
                  <span className="flex items-center gap-1.5">
                    <Building2 className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Business Legal Name *</span>
                  </span>
                  <span className="text-[10px] text-slate-500 font-normal">Primary Identity</span>
                </label>
                <input
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="e.g. Acme Corporation"
                  className="input-obsidian text-sm"
                />
                <p className="text-[11px] text-slate-400">
                  Used across executive intelligence reports, audit trails, and agent synthesis.
                </p>
              </div>

              {/* Industry Domain */}
              <div className="space-y-1.5">
                <label className="text-xs font-mono text-slate-300 flex items-center justify-between">
                  <span className="flex items-center gap-1.5">
                    <Layers className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Industry Domain</span>
                  </span>
                  <span className="text-[10px] text-slate-500 font-normal">Ontology Scoping</span>
                </label>
                <select
                  value={formData.industry}
                  onChange={(e) => setFormData({ ...formData, industry: e.target.value })}
                  className="input-obsidian text-sm"
                >
                  {INDUSTRY_DOMAINS.map((ind) => (
                    <option key={ind} value={ind}>
                      {ind}
                    </option>
                  ))}
                </select>
                <p className="text-[11px] text-slate-400">
                  Calibrates default KPI hierarchies, benchmark metrics, and investigative causal trees.
                </p>
              </div>

              {/* Operating Country / Jurisdiction */}
              <div className="space-y-1.5">
                <label className="text-xs font-mono text-slate-300 flex items-center justify-between">
                  <span className="flex items-center gap-1.5">
                    <Globe className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Operating Country / Jurisdiction</span>
                  </span>
                  <span className="text-[10px] text-slate-500 font-normal">Regulatory Context</span>
                </label>
                <input
                  type="text"
                  value={formData.country}
                  onChange={(e) => setFormData({ ...formData, country: e.target.value })}
                  placeholder="e.g. United States, United Kingdom, Germany"
                  className="input-obsidian text-sm"
                />
                <p className="text-[11px] text-slate-400">
                  Jurisdictional boundaries for fiscal calendar patterns and holiday seasonality.
                </p>
              </div>

              {/* Business Model */}
              <div className="space-y-1.5">
                <label className="text-xs font-mono text-slate-300 flex items-center justify-between">
                  <span className="flex items-center gap-1.5">
                    <Sliders className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Business Model Structure</span>
                  </span>
                  <span className="text-[10px] text-slate-500 font-normal">Transaction Pattern</span>
                </label>
                <select
                  value={formData.business_type}
                  onChange={(e) => setFormData({ ...formData, business_type: e.target.value })}
                  className="input-obsidian text-sm"
                >
                  {BUSINESS_MODELS.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                </select>
                <p className="text-[11px] text-slate-400">
                  Configures whether the agent evaluates ARR/churn vs SKU-level basket margins.
                </p>
              </div>
            </div>

            {/* Bottom Form Actions */}
            <div className="pt-4 border-t border-white/[0.08] flex items-center justify-between">
              <span className="text-[11px] font-mono text-slate-400">
                {isDirty ? 'Unsaved changes detected.' : 'All general profile parameters saved.'}
              </span>
              <div className="flex items-center gap-3">
                {isDirty && (
                  <button
                    type="button"
                    onClick={() => setFormData(initialFormData)}
                    disabled={saving}
                    className="btn-secondary text-xs h-9 px-4"
                  >
                    <span>Discard Changes</span>
                  </button>
                )}
                <button
                  type="submit"
                  disabled={saving || !isDirty}
                  className="btn-primary text-xs h-9 px-4 disabled:opacity-50"
                >
                  <Save className="w-4 h-4" />
                  <span>{saving ? 'Updating...' : 'Save Configuration'}</span>
                </button>
              </div>
            </div>
          </form>
        )}

        {/* ======================================================== */}
        {/* TAB 2: FINANCIAL & LOCALIZATION */}
        {/* ======================================================== */}
        {activeTab === 'localization' && (
          <form onSubmit={handleSave} className="card-obsidian p-6 space-y-6">
            <div className="border-b border-white/[0.08] pb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <h2 className="text-base font-bold text-white font-sans">Financial &amp; Temporal Localization</h2>
                <p className="text-xs text-slate-400 mt-0.5 font-sans">
                  Sets operational timezone, primary reporting currency, and corporate fiscal year calendar boundaries.
                </p>
              </div>
              {isDirty && (
                <span className="px-2.5 py-0.5 rounded-full bg-amber-500/20 border border-amber-500/40 text-[10px] font-mono text-amber-300 font-semibold self-start sm:self-auto animate-pulse">
                  Unsaved Changes
                </span>
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
              {/* Reporting Currency */}
              <div className="space-y-1.5">
                <label className="text-xs font-mono text-slate-300 flex items-center justify-between">
                  <span className="flex items-center gap-1.5">
                    <Coins className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Reporting Currency</span>
                  </span>
                  <span className="text-[10px] text-slate-500 font-normal">ISO 4217</span>
                </label>
                <select
                  value={formData.currency}
                  onChange={(e) => setFormData({ ...formData, currency: e.target.value })}
                  className="input-obsidian text-sm"
                >
                  {POPULAR_CURRENCIES.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.label}
                    </option>
                  ))}
                </select>
                <p className="text-[11px] text-slate-400">
                  Global currency symbol formatted across forecasts, revenues, and executive answers.
                </p>
              </div>

              {/* Timezone */}
              <div className="space-y-1.5">
                <label className="text-xs font-mono text-slate-300 flex items-center justify-between">
                  <span className="flex items-center gap-1.5">
                    <Clock className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Operational Timezone</span>
                  </span>
                  <span className="text-[10px] text-slate-500 font-normal">IANA Timezone</span>
                </label>
                <select
                  value={formData.timezone}
                  onChange={(e) => setFormData({ ...formData, timezone: e.target.value })}
                  className="input-obsidian text-sm"
                >
                  {POPULAR_TIMEZONES.map((tz) => (
                    <option key={tz} value={tz}>
                      {tz}
                    </option>
                  ))}
                </select>
                <p className="text-[11px] text-slate-400">
                  Aligns date partition aggregations (e.g. daily, weekly, monthly cutoff timestamps).
                </p>
              </div>

              {/* Fiscal Year Start Month */}
              <div className="space-y-1.5">
                <label className="text-xs font-mono text-slate-300 flex items-center justify-between">
                  <span className="flex items-center gap-1.5">
                    <Calendar className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Fiscal Year Start Month</span>
                  </span>
                  <span className="text-[10px] text-slate-500 font-normal">Corporate Cycle</span>
                </label>
                <select
                  value={formData.fiscal_year_start}
                  onChange={(e) =>
                    setFormData({ ...formData, fiscal_year_start: parseInt(e.target.value) || 1 })
                  }
                  className="input-obsidian text-sm"
                >
                  {MONTH_NAMES.map((name, idx) => (
                    <option key={idx + 1} value={idx + 1}>
                      {idx + 1} — {name}
                    </option>
                  ))}
                </select>
                <p className="text-[11px] text-slate-400">
                  Determines Year-to-Date (YTD) and fiscal quarterly (Q1–Q4) boundary calculations.
                </p>
              </div>
            </div>

            {/* Context Notice */}
            <div className="p-4 rounded-xl bg-void/80 border border-white/[0.08] text-xs text-slate-300 space-y-1.5 font-sans leading-relaxed">
              <span className="text-[10px] font-mono uppercase text-cyan-400 font-semibold block">
                ANALYTICAL ENGINE IMPACT:
              </span>
              <p>
                When you set the fiscal start month to <strong className="text-white">Month {formData.fiscal_year_start} ({MONTH_NAMES[formData.fiscal_year_start - 1]})</strong>, the NEXUS SQL query generators calibrate all quarterly comparisons (Q1 to Q4) and seasonal decomposition routines to respect your organization&apos;s corporate reporting calendar rather than raw calendar years.
              </p>
            </div>

            {/* Bottom Form Actions */}
            <div className="pt-4 border-t border-white/[0.08] flex items-center justify-between">
              <span className="text-[11px] font-mono text-slate-400">
                {isDirty ? 'Unsaved changes detected.' : 'All financial parameters saved.'}
              </span>
              <div className="flex items-center gap-3">
                {isDirty && (
                  <button
                    type="button"
                    onClick={() => setFormData(initialFormData)}
                    disabled={saving}
                    className="btn-secondary text-xs h-9 px-4"
                  >
                    <span>Discard Changes</span>
                  </button>
                )}
                <button
                  type="submit"
                  disabled={saving || !isDirty}
                  className="btn-primary text-xs h-9 px-4 disabled:opacity-50"
                >
                  <Save className="w-4 h-4" />
                  <span>{saving ? 'Updating...' : 'Save Configuration'}</span>
                </button>
              </div>
            </div>
          </form>
        )}

        {/* ======================================================== */}
        {/* TAB 3: TENANT BOUNDARIES & DATA */}
        {/* ======================================================== */}
        {activeTab === 'governance' && (
          <div className="space-y-6">
            {/* Read-Only Multi-Tenant Identifiers */}
            <div className="card-obsidian p-6 space-y-4">
              <div className="border-b border-white/[0.08] pb-3 flex items-center justify-between">
                <div>
                  <h2 className="text-base font-bold text-white font-sans">Multi-Tenant Boundaries &amp; Identifiers</h2>
                  <p className="text-xs text-slate-400 mt-0.5 font-sans">
                    Read-only platform sovereign boundary parameters used for API authorization and tenant isolation.
                  </p>
                </div>
                <div className="flex items-center gap-1 text-[11px] font-mono text-slate-500">
                  <Lock className="w-3.5 h-3.5 text-slate-400" />
                  <span>Read-Only</span>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 font-mono text-xs">
                {/* Organization ID */}
                <div className="p-3.5 rounded-xl bg-void/80 border border-white/[0.06] space-y-1">
                  <div className="flex items-center justify-between text-slate-500 text-[10px] uppercase font-semibold">
                    <span>ORGANIZATION ID</span>
                    <button
                      type="button"
                      onClick={() => handleCopy(currentOrg?.organization_id || '', 'org_id')}
                      className="text-slate-400 hover:text-cyan-300 transition-colors"
                      title="Copy Organization ID"
                    >
                      {copiedField === 'org_id' ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    </button>
                  </div>
                  <div className="text-white font-semibold truncate text-[11px]">
                    {currentOrg?.organization_id || 'org_default'}
                  </div>
                </div>

                {/* Business Workspace ID */}
                <div className="p-3.5 rounded-xl bg-void/80 border border-white/[0.06] space-y-1">
                  <div className="flex items-center justify-between text-slate-500 text-[10px] uppercase font-semibold">
                    <span>WORKSPACE ID (ACTIVE BIZ)</span>
                    <button
                      type="button"
                      onClick={() => handleCopy(activeBusinessId, 'biz_id')}
                      className="text-slate-400 hover:text-cyan-300 transition-colors"
                      title="Copy Business Workspace ID"
                    >
                      {copiedField === 'biz_id' ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    </button>
                  </div>
                  <div className="text-cyan-400 font-semibold truncate text-[11px]">
                    {activeBusinessId}
                  </div>
                </div>

                {/* Organization Slug */}
                <div className="p-3.5 rounded-xl bg-void/80 border border-white/[0.06] space-y-1">
                  <div className="flex items-center justify-between text-slate-500 text-[10px] uppercase font-semibold">
                    <span>ORGANIZATION SLUG</span>
                    <button
                      type="button"
                      onClick={() => handleCopy(currentOrg?.organization_slug || '', 'slug')}
                      className="text-slate-400 hover:text-cyan-300 transition-colors"
                      title="Copy Slug"
                    >
                      {copiedField === 'slug' ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    </button>
                  </div>
                  <div className="text-slate-300 font-semibold truncate text-[11px]">
                    {currentOrg?.organization_slug || 'default'}
                  </div>
                </div>
              </div>
            </div>

            {/* Ingested Datasets Breakdown */}
            <div className="card-obsidian p-6 space-y-4">
              <div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
                <div>
                  <h2 className="text-base font-bold text-white font-sans">
                    Ingested Datasets ({status?.datasets?.length || 0})
                  </h2>
                  <p className="text-xs text-slate-400 mt-0.5 font-sans">
                    Commercial datasets partitioned under this business workspace powering deterministic calculations.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => onNavigate('/data')}
                  className="btn-secondary text-xs h-8 px-3 inline-flex items-center gap-1.5"
                >
                  <span>Data Gateway</span>
                  <ExternalLink className="w-3.5 h-3.5 text-cyan-400" />
                </button>
              </div>

              {status?.datasets && status.datasets.length > 0 ? (
                <div className="divide-y divide-white/[0.06]">
                  {status.datasets.map((ds) => (
                    <div key={ds.id} className="py-3 flex items-center justify-between text-xs">
                      <div className="space-y-0.5">
                        <span className="font-semibold text-slate-200 font-sans">{ds.filename}</span>
                        <div className="text-[10px] font-mono text-slate-400 flex items-center gap-2">
                          <span>{ds.row_count.toLocaleString()} rows</span>
                          <span>•</span>
                          <span>{ds.column_count} columns</span>
                          <span>•</span>
                          <span className="uppercase">{ds.file_type}</span>
                        </div>
                      </div>
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase font-semibold ${
                          ds.readiness_status === 'ready'
                            ? 'bg-emerald-950 border border-emerald-500/40 text-emerald-300'
                            : 'bg-amber-950 border border-amber-500/40 text-amber-300'
                        }`}
                      >
                        {ds.readiness_status}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-8 text-center text-xs text-slate-400 space-y-2">
                  <Database className="w-7 h-7 text-slate-600 mx-auto" />
                  <p className="font-semibold text-slate-300">No datasets ingested under this workspace yet.</p>
                  <p className="text-[11px] leading-relaxed max-w-sm mx-auto">
                    Visit the Data Gateway to upload sales, financial, or customer datasets.
                  </p>
                  <button
                    type="button"
                    onClick={() => onNavigate('/data')}
                    className="btn-primary text-xs h-8 px-3.5 mt-2"
                  >
                    <span>Upload Datasets</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ======================================================== */}
        {/* TAB 4: ADMINISTRATIVE DANGER ZONE */}
        {/* ======================================================== */}
        {activeTab === 'danger' && (
          <div className="card-obsidian p-6 border-rose-900/40 bg-rose-950/10 space-y-6">
            <div className="border-b border-rose-900/40 pb-4">
              <div className="flex items-center gap-2 text-rose-400 mb-1">
                <AlertOctagon className="w-5 h-5" />
                <h2 className="text-base font-bold text-white font-sans">Administrative Danger Zone</h2>
              </div>
              <p className="text-xs text-slate-400 font-sans leading-relaxed max-w-2xl">
                Consequential and irreversible administrative actions. Modifications here affect workspace data retention, tenant boundaries, and model histories.
              </p>
            </div>

            {/* RBAC Verification Notice */}
            <div className="p-4 rounded-xl bg-void/80 border border-white/[0.08] space-y-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-mono text-slate-400 uppercase text-[10px] font-semibold">
                  AUTHORIZATION REQUIREMENTS
                </span>
                <span className="px-2 py-0.5 rounded bg-surface border border-white/[0.08] font-mono text-[10px] text-slate-300">
                  Current Role: {userRole.toUpperCase()}
                </span>
              </div>
              <p className="text-slate-300 font-sans leading-relaxed">
                Server-side authorization strictly verifies role credentials before executing destructive mutations. Only organization <strong className="text-white">OWNER</strong> roles are authorized to delete a business workspace.
              </p>
            </div>

            {/* Delete Workspace Row */}
            <div className="p-5 rounded-xl border border-rose-800/40 bg-void/80 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="space-y-1">
                <h3 className="text-sm font-bold text-white font-sans flex items-center gap-2">
                  <Trash2 className="w-4 h-4 text-rose-400" />
                  <span>Delete Workspace &ldquo;{confirmedWorkspaceName || 'Current Workspace'}&rdquo;</span>
                </h3>
                <p className="text-xs text-slate-400 font-sans max-w-lg leading-relaxed">
                  Permanently deletes this business workspace, ingested data tables, analytical execution histories, and semantic model revisions. This action cannot be undone.
                </p>
              </div>

              <button
                type="button"
                disabled={!isOwner || !hasValidBusinessId || !confirmedWorkspaceName}
                onClick={() => {
                  setDeleteConfirmationInput('');
                  setDeleteError(null);
                  setShowDeleteModal(true);
                }}
                className={`text-xs h-9 px-4 rounded-xl font-semibold transition-all shrink-0 inline-flex items-center gap-1.5 ${
                  isOwner && hasValidBusinessId && confirmedWorkspaceName
                    ? 'bg-rose-950/80 border border-rose-600/60 text-rose-300 hover:bg-rose-900 hover:text-white'
                    : 'bg-surface border border-white/[0.08] text-slate-500 cursor-not-allowed opacity-60'
                }`}
                title={
                  !isOwner
                    ? 'Owner role required to delete workspace'
                    : !hasValidBusinessId
                    ? 'No loaded business workspace to delete'
                    : 'Delete workspace'
                }
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>
                  {!isOwner
                    ? 'Owner Role Required'
                    : !hasValidBusinessId
                    ? 'No Workspace Loaded'
                    : 'Delete Workspace'}
                </span>
              </button>
            </div>
          </div>
        )}

        {/* Delete Confirmation Modal */}
        {showDeleteModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-void/90 backdrop-blur-sm animate-in fade-in duration-150">
            <div className="card-obsidian max-w-md w-full p-6 border-rose-800/60 bg-surface/95 space-y-5 shadow-2xl">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2.5 text-rose-400">
                  <AlertTriangle className="w-5 h-5 shrink-0" />
                  <h3 className="text-base font-bold text-white font-sans">
                    Confirm Irreversible Deletion
                  </h3>
                </div>
                <button
                  type="button"
                  onClick={() => setShowDeleteModal(false)}
                  className="text-slate-400 hover:text-white transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="space-y-3 text-xs text-slate-300 font-sans leading-relaxed">
                <p>
                  You are about to permanently delete the business workspace:
                </p>
                <div className="p-3 rounded-lg bg-void border border-white/[0.08] font-mono text-cyan-300 font-bold text-center">
                  {confirmedWorkspaceName}
                </div>
                <p>
                  All associated analytical run ledgers, ingested dataset partitions, and semantic ontology revisions will be removed.
                </p>
                <p className="font-semibold text-slate-200">
                  To confirm, type <span className="font-mono text-rose-400 font-bold">&ldquo;{confirmedWorkspaceName}&rdquo;</span> below:
                </p>
                <input
                  type="text"
                  value={deleteConfirmationInput}
                  onChange={(e) => setDeleteConfirmationInput(e.target.value)}
                  placeholder={`Type "${confirmedWorkspaceName}" to confirm`}
                  className="input-obsidian text-xs font-mono text-white"
                />

                {deleteError && (
                  <p className="text-xs text-rose-400 font-mono">{deleteError}</p>
                )}
              </div>

              <div className="pt-2 border-t border-white/[0.08] flex items-center justify-end gap-2.5">
                <button
                  type="button"
                  onClick={() => setShowDeleteModal(false)}
                  disabled={deleting}
                  className="btn-secondary text-xs h-8 px-3"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleDeleteBusiness}
                  disabled={deleting || !confirmedWorkspaceName || deleteConfirmationInput.trim() !== confirmedWorkspaceName}
                  className="px-3.5 py-1.5 rounded-xl bg-rose-600 hover:bg-rose-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold shadow-md transition-all inline-flex items-center gap-1.5"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  <span>{deleting ? 'Deleting...' : 'I Understand, Delete Workspace'}</span>
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </ErrorBoundary>
  );
};

export default BusinessSettingsPage;

