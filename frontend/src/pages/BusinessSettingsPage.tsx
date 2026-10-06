import React, { useState, useEffect } from 'react';
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
} from 'lucide-react';
import {
  getOnboardingStatus,
  updateBusiness,
  OnboardingStatusResponse,
} from '../services/api';
import { AuthService, UserProfileResponse } from '../services/auth';

interface BusinessSettingsPageProps {
  onNavigate: (route: string) => void;
}

export const BusinessSettingsPage: React.FC<BusinessSettingsPageProps> = ({ onNavigate }) => {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [profile, setProfile] = useState<UserProfileResponse | null>(null);
  const [status, setStatus] = useState<OnboardingStatusResponse | null>(null);

  const [formData, setFormData] = useState({
    name: '',
    industry: '',
    country: '',
    currency: '',
    timezone: '',
    business_type: '',
    fiscal_year_start: 1,
  });

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [userProfile, onbStatus] = await Promise.all([
        AuthService.getMe(),
        getOnboardingStatus(),
      ]);

      setProfile(userProfile);
      setStatus(onbStatus);

      const bizObj =
        onbStatus.business ||
        userProfile?.tenants?.[0]?.businesses?.find(
          (b: any) => b.id === (onbStatus.business_id || AuthService.getActiveBusinessId())
        ) ||
        userProfile?.tenants?.[0]?.businesses?.[0];

      if (bizObj || onbStatus.business_name) {
        setFormData({
          name: bizObj?.name || onbStatus.business_name || '',
          industry: bizObj?.industry || 'Technology',
          country: (bizObj as any)?.country || 'United States',
          currency: bizObj?.currency || 'USD',
          timezone: (bizObj as any)?.timezone || 'UTC',
          business_type: (bizObj as any)?.business_type || 'B2B/B2C Retail',
          fiscal_year_start: (bizObj as any)?.fiscal_year_start || 1,
        });
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load business profile.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    const bizId =
      status?.business?.id ||
      status?.business_id ||
      profile?.tenants?.[0]?.businesses?.[0]?.id;
    if (!bizId) return;

    setSaving(true);
    setError(null);
    setSuccess(null);

    try {
      await updateBusiness(bizId, {
        name: formData.name,
        industry: formData.industry,
        country: formData.country,
        currency: formData.currency,
        timezone: formData.timezone,
        business_type: formData.business_type,
        fiscal_year_start: Number(formData.fiscal_year_start),
      });

      setSuccess('Business profile updated successfully.');
      setTimeout(() => setSuccess(null), 3000);
      await loadData();
    } catch (err: any) {
      setError(err?.message || 'Failed to update business configuration.');
    } finally {
      setSaving(false);
    }
  };

  const currentOrg = profile?.tenants?.[0];
  const userRole = currentOrg?.role || 'owner';

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="flex flex-col items-center gap-3">
          <RefreshCw className="w-6 h-6 animate-spin text-brand-cyan" />
          <span className="text-xs font-mono text-slate-400">Loading Business Workspace...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page Title & Breadcrumb */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-white tracking-tight">Business Workspace</h1>
            <span className="px-2 py-0.5 rounded-full bg-cyan-950/70 border border-brand-cyan/30 text-[10px] font-mono text-brand-cyan uppercase">
              Tenant Sovereign
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Enterprise multi-tenant boundaries, organization governance, and deterministic schema readiness.
          </p>
        </div>

        <button
          onClick={() => onNavigate('/onboarding')}
          className="px-3.5 py-1.5 rounded-xl bg-surface hover:bg-surface-elevated border border-surface-elevated text-xs font-medium text-slate-300 transition-all flex items-center gap-2 self-start sm:self-auto"
        >
          <span>Revisit Onboarding Wizard</span>
          <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
        </button>
      </div>

      {/* Alerts */}
      {error && (
        <div className="p-4 rounded-xl bg-rose-950/60 border border-rose-500/40 text-rose-200 text-xs flex items-center gap-3">
          <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {success && (
        <div className="p-4 rounded-xl bg-emerald-950/60 border border-emerald-500/40 text-emerald-200 text-xs flex items-center gap-3">
          <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
          <span>{success}</span>
        </div>
      )}

      {/* Overview Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* Organization Card */}
        <div className="p-5 rounded-2xl bg-surface/60 border border-surface-elevated backdrop-blur-sm">
          <div className="flex items-center justify-between text-slate-400 text-xs font-mono mb-2">
            <span>ORGANIZATION</span>
            <Building2 className="w-4 h-4 text-brand-cyan" />
          </div>
          <p className="text-base font-bold text-white truncate">
            {currentOrg?.organization_name || 'Primary Organization'}
          </p>
          <div className="mt-2 flex items-center gap-2">
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-void border border-surface-elevated text-slate-300">
              Slug: {currentOrg?.organization_slug || 'default'}
            </span>
          </div>
        </div>

        {/* User Identity & Role */}
        <div className="p-5 rounded-2xl bg-surface/60 border border-surface-elevated backdrop-blur-sm">
          <div className="flex items-center justify-between text-slate-400 text-xs font-mono mb-2">
            <span>USER IDENTITY</span>
            <UserCheck className="w-4 h-4 text-emerald-400" />
          </div>
          <p className="text-base font-bold text-white truncate">
            {profile?.user.full_name || profile?.user.email}
          </p>
          <div className="mt-2 flex items-center gap-2">
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950/70 border border-emerald-500/30 text-emerald-300 uppercase font-semibold">
              Role: {userRole}
            </span>
            <span className="text-[10px] font-mono text-slate-400 truncate">
              {profile?.user.email}
            </span>
          </div>
        </div>

        {/* Data Readiness Scorecard */}
        <div className="p-5 rounded-2xl bg-surface/60 border border-surface-elevated backdrop-blur-sm">
          <div className="flex items-center justify-between text-slate-400 text-xs font-mono mb-2">
            <span>DATA READINESS</span>
            <Database className="w-4 h-4 text-brand-cyan" />
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                (status?.data_readiness?.status || status?.data_readiness_status || '').toLowerCase() === 'ready'
                  ? 'bg-emerald-400 animate-pulse'
                  : 'bg-amber-400'
              }`}
            />
            <p className="text-base font-bold text-white uppercase font-mono">
              {status?.data_readiness?.status || status?.data_readiness_status || 'Active'}
            </p>
          </div>
          <p className="text-[11px] text-slate-400 mt-2 truncate">
            {status?.data_readiness?.total_datasets ?? (status as any)?.readiness_report?.total_datasets ?? (status as any)?.readiness_report?.dataset_count ?? 0} datasets •{' '}
            {status?.data_readiness?.total_rows ?? (status as any)?.readiness_report?.total_rows ?? 0} rows ingested
          </p>
        </div>
      </div>

      {/* Business Profile Configuration Form */}
      <div className="p-6 rounded-2xl bg-surface/60 border border-surface-elevated backdrop-blur-sm">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-white">Business Parameters</h2>
            <p className="text-xs text-slate-400 mt-0.5">
              These operational settings scope all intelligence analysis, RAG context, and financial reporting.
            </p>
          </div>
        </div>

        <form onSubmit={handleSave} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
                <Building2 className="w-3.5 h-3.5 text-brand-cyan" />
                <span>Business Name *</span>
              </label>
              <input
                type="text"
                required
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-3.5 py-2.5 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan text-slate-200 text-sm focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-brand-cyan" />
                <span>Industry Domain</span>
              </label>
              <input
                type="text"
                value={formData.industry}
                onChange={(e) => setFormData({ ...formData, industry: e.target.value })}
                className="w-full px-3.5 py-2.5 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan text-slate-200 text-sm focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
                <Globe className="w-3.5 h-3.5 text-brand-cyan" />
                <span>Operating Country</span>
              </label>
              <input
                type="text"
                value={formData.country}
                onChange={(e) => setFormData({ ...formData, country: e.target.value })}
                className="w-full px-3.5 py-2.5 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan text-slate-200 text-sm focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
                <Coins className="w-3.5 h-3.5 text-brand-cyan" />
                <span>Reporting Currency</span>
              </label>
              <input
                type="text"
                value={formData.currency}
                onChange={(e) => setFormData({ ...formData, currency: e.target.value })}
                className="w-full px-3.5 py-2.5 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan text-slate-200 text-sm focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-brand-cyan" />
                <span>Timezone</span>
              </label>
              <input
                type="text"
                value={formData.timezone}
                onChange={(e) => setFormData({ ...formData, timezone: e.target.value })}
                className="w-full px-3.5 py-2.5 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan text-slate-200 text-sm focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
                <Calendar className="w-3.5 h-3.5 text-brand-cyan" />
                <span>Fiscal Year Start Month (1-12)</span>
              </label>
              <input
                type="number"
                min={1}
                max={12}
                value={formData.fiscal_year_start}
                onChange={(e) =>
                  setFormData({ ...formData, fiscal_year_start: parseInt(e.target.value) || 1 })
                }
                className="w-full px-3.5 py-2.5 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan text-slate-200 text-sm focus:outline-none"
              />
            </div>
          </div>

          <div className="pt-4 flex justify-end">
            <button
              type="submit"
              disabled={saving}
              className="px-6 py-2.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-semibold text-xs transition-all flex items-center gap-2 shadow-sm disabled:opacity-50"
            >
              <Save className="w-4 h-4" />
              <span>{saving ? 'Updating...' : 'Save Configuration'}</span>
            </button>
          </div>
        </form>
      </div>

      {/* Ingested Datasets Breakdown */}
      {status?.datasets && status.datasets.length > 0 && (
        <div className="p-6 rounded-2xl bg-surface/60 border border-surface-elevated backdrop-blur-sm space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-bold text-white">Ingested Datasets</h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Tenant-scoped commercial datasets powering deterministic analytics and causal reasoning.
              </p>
            </div>
            <button
              onClick={() => onNavigate('/data')}
              className="text-xs text-brand-cyan hover:underline"
            >
              View Data Catalog &rarr;
            </button>
          </div>

          <div className="divide-y divide-surface-elevated">
            {status.datasets.map((ds) => (
              <div key={ds.id} className="py-3 flex items-center justify-between text-xs">
                <div>
                  <span className="font-semibold text-slate-200">{ds.filename}</span>
                  <div className="text-[10px] font-mono text-slate-400 mt-0.5 flex items-center gap-2">
                    <span>{ds.row_count} rows</span>
                    <span>•</span>
                    <span>{ds.column_count} columns</span>
                    <span>•</span>
                    <span className="uppercase">{ds.file_type}</span>
                  </div>
                </div>
                <span
                  className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase font-semibold ${
                    ds.readiness_status === 'ready'
                      ? 'bg-emerald-950 border border-emerald-500/30 text-emerald-300'
                      : 'bg-amber-950 border border-amber-500/30 text-amber-300'
                  }`}
                >
                  {ds.readiness_status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
