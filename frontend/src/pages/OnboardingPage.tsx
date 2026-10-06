import React, { useState, useEffect } from 'react';
import {
  Building2,
  BookOpen,
  UploadCloud,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  ArrowLeft,
  FileSpreadsheet,
  Sparkles,
  Info,
  Database,
  RefreshCw,
} from 'lucide-react';
import {
  getOnboardingStatus,
  saveOnboardingBusiness,
  saveOnboardingContext,
  uploadOnboardingData,
  completeOnboarding,
  OnboardingStatusResponse,
} from '../services/api';
import { AuthService } from '../services/auth';
import { NexusLogo } from '../components/brand/NexusLogo';

interface OnboardingPageProps {
  onComplete: () => void;
  onNavigate: (route: string) => void;
}

export const OnboardingPage: React.FC<OnboardingPageProps> = ({
  onComplete,
  onNavigate,
}) => {
  const [step, setStep] = useState<number>(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Step 1: Business Profile State
  const [bizForm, setBizForm] = useState({
    name: 'Apex Commercial Analytics',
    industry: 'Retail & E-Commerce',
    country: 'United States',
    currency: 'USD',
    timezone: 'UTC',
    business_type: 'B2B/B2C Retail',
    fiscal_year_start: 1,
  });

  // Step 2: Business Context (Optional) State
  const [contextForm, setContextForm] = useState({
    ruleName: 'Standard Gross Margin Target',
    ruleLogic: 'Gross margin should remain above 35% on all finished goods inventory.',
    term: 'MRR',
    definition: 'Monthly Recurring Revenue derived from committed customer contracts.',
    notes: 'Operating standard fiscal calendar with quarterly closing audits.',
  });

  // Step 3 & 4: Data Upload & Readiness State
  const [onboardingData, setOnboardingData] = useState<OnboardingStatusResponse | null>(null);
  const [uploadProgress, setUploadProgress] = useState(false);

  // Load initial onboarding status
  const refreshStatus = async () => {
    try {
      const res = await getOnboardingStatus();
      setOnboardingData(res);
      if (res.business) {
        const b = res.business;
        setBizForm((prev) => ({
          ...prev,
          name: b.name || prev.name,
          industry: b.industry || prev.industry,
          currency: b.currency || prev.currency,
        }));
      }
    } catch (err: any) {
      console.warn('Onboarding status fetch:', err);
    }
  };

  useEffect(() => {
    refreshStatus();
  }, []);

  // Step 1 Submission
  const handleSaveBusiness = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await saveOnboardingBusiness({
        name: bizForm.name,
        industry: bizForm.industry,
        country: bizForm.country,
        currency: bizForm.currency,
        timezone: bizForm.timezone,
        business_type: bizForm.business_type,
        fiscal_year_start: Number(bizForm.fiscal_year_start),
      });
      if (res.business?.id) {
        AuthService.setActiveBusinessId(res.business.id);
      }
      await refreshStatus();
      setStep(2);
    } catch (err: any) {
      setError(err?.message || 'Failed to save business profile.');
    } finally {
      setLoading(false);
    }
  };

  // Step 2 Submission (or Skip)
  const handleSaveContext = async (skip: boolean = false) => {
    setError(null);
    if (skip) {
      setStep(3);
      return;
    }

    setLoading(true);
    try {
      await saveOnboardingContext({
        rules: contextForm.ruleName
          ? [
              {
                name: contextForm.ruleName,
                rule_type: 'business_policy',
                rule_logic: contextForm.ruleLogic,
                priority: 1,
              },
            ]
          : [],
        terms: contextForm.term
          ? [{ term: contextForm.term, definition: contextForm.definition }]
          : [],
        notes: contextForm.notes,
      });
      setSuccessMsg('Business context registered successfully.');
      setTimeout(() => setSuccessMsg(null), 3000);
      await refreshStatus();
      setStep(3);
    } catch (err: any) {
      setError(err?.message || 'Failed to register business context.');
    } finally {
      setLoading(false);
    }
  };

  // Step 3: Handle File Upload
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setError(null);
    setUploadProgress(true);

    try {
      await uploadOnboardingData(file);
      await refreshStatus();
      setSuccessMsg(`"${file.name}" ingested and profiled successfully.`);
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err: any) {
      setError(err?.message || 'Failed to upload and profile dataset.');
    } finally {
      setUploadProgress(false);
    }
  };

  // Step 4: Complete Onboarding & Enter Workspace
  const handleComplete = async () => {
    setError(null);
    setLoading(true);
    try {
      await completeOnboarding();
      onComplete();
    } catch (err: any) {
      setError(err?.message || 'Failed to finalize onboarding.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-void text-slate-100 flex flex-col selection:bg-cyan-500/20 selection:text-cyan-200">
      {/* Top Header */}
      <header className="h-16 px-6 border-b border-surface-elevated bg-void/80 backdrop-blur-md flex items-center justify-between">
        <div className="flex items-center gap-3">
          <NexusLogo imageSize={36} />
          <span className="text-xs font-mono text-slate-500">•</span>
          <span className="text-xs font-mono tracking-wider uppercase text-slate-400">
            Tenant Onboarding
          </span>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => onNavigate('/')}
            className="text-xs text-slate-400 hover:text-slate-200"
          >
            Skip to Dashboard
          </button>
        </div>
      </header>

      {/* Main Container */}
      <div className="flex-1 max-w-4xl w-full mx-auto p-6 md:p-10 flex flex-col justify-center">
        {/* Stepper Navigation */}
        <div className="mb-10">
          <div className="flex items-center justify-between relative">
            <div className="absolute left-0 top-1/2 -translate-y-1/2 h-0.5 w-full bg-surface-elevated -z-0" />
            {[
              { num: 1, title: 'Business Profile', icon: Building2 },
              { num: 2, title: 'Context (Optional)', icon: BookOpen },
              { num: 3, title: 'Connect Data', icon: UploadCloud },
              { num: 4, title: 'Readiness & Launch', icon: CheckCircle2 },
            ].map((s) => {
              const Icon = s.icon;
              const isPast = step > s.num;
              const isCurrent = step === s.num;
              return (
                <div
                  key={s.num}
                  className="flex flex-col items-center gap-2 relative z-10 bg-void px-2"
                >
                  <div
                    className={`w-10 h-10 rounded-full flex items-center justify-center font-mono text-xs font-bold transition-all ${
                      isPast
                        ? 'bg-cyan-500 text-void shadow-glow-cyan'
                        : isCurrent
                        ? 'bg-cyan-950 text-brand-cyan border-2 border-brand-cyan shadow-sm'
                        : 'bg-surface text-slate-500 border border-surface-elevated'
                    }`}
                  >
                    {isPast ? <CheckCircle2 className="w-5 h-5" /> : <Icon className="w-4 h-4" />}
                  </div>
                  <span
                    className={`text-xs font-sans font-medium hidden sm:block ${
                      isCurrent ? 'text-brand-cyan font-bold' : isPast ? 'text-slate-300' : 'text-slate-500'
                    }`}
                  >
                    {s.title}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Feedback Alerts */}
        {error && (
          <div className="mb-6 p-4 rounded-xl bg-rose-950/60 border border-rose-500/40 text-rose-200 text-xs flex items-center gap-3">
            <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
        )}
        {successMsg && (
          <div className="mb-6 p-4 rounded-xl bg-emerald-950/60 border border-emerald-500/40 text-emerald-200 text-xs flex items-center gap-3">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{successMsg}</span>
          </div>
        )}

        {/* STEP 1: BUSINESS PROFILE */}
        {step === 1 && (
          <div className="bg-surface/60 border border-surface-elevated rounded-2xl p-6 sm:p-8 backdrop-blur-sm shadow-xl">
            <div className="mb-6">
              <span className="text-[11px] font-mono uppercase text-brand-cyan font-semibold tracking-wider">
                Step 1 of 4
              </span>
              <h2 className="text-xl font-bold text-white mt-1">Configure Business Profile</h2>
              <p className="text-xs text-slate-400 mt-1">
                Establish the sovereign organization workspace parameters for your commercial entity.
              </p>
            </div>

            <form onSubmit={handleSaveBusiness} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-mono text-slate-300 mb-1.5">
                    Business Name *
                  </label>
                  <input
                    type="text"
                    required
                    value={bizForm.name}
                    onChange={(e) => setBizForm({ ...bizForm, name: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan text-slate-200 text-sm focus:outline-none"
                    placeholder="e.g. Apex Industrial Supply"
                  />
                </div>

                <div>
                  <label className="block text-xs font-mono text-slate-300 mb-1.5">
                    Industry Domain
                  </label>
                  <select
                    value={bizForm.industry}
                    onChange={(e) => setBizForm({ ...bizForm, industry: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan text-slate-200 text-sm focus:outline-none"
                  >
                    <option value="Retail & E-Commerce">Retail & E-Commerce</option>
                    <option value="SaaS & Cloud Software">SaaS & Cloud Software</option>
                    <option value="Manufacturing & Logistics">Manufacturing & Logistics</option>
                    <option value="Professional Services">Professional Services</option>
                    <option value="Healthcare & Life Sciences">Healthcare & Life Sciences</option>
                    <option value="Financial Services">Financial Services</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-mono text-slate-300 mb-1.5">
                    Operating Country
                  </label>
                  <input
                    type="text"
                    value={bizForm.country}
                    onChange={(e) => setBizForm({ ...bizForm, country: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan text-slate-200 text-sm focus:outline-none"
                  />
                </div>

                <div>
                  <label className="block text-xs font-mono text-slate-300 mb-1.5">
                    Reporting Currency
                  </label>
                  <input
                    type="text"
                    value={bizForm.currency}
                    onChange={(e) => setBizForm({ ...bizForm, currency: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan text-slate-200 text-sm focus:outline-none"
                    placeholder="USD, EUR, GBP, INR"
                  />
                </div>

                <div>
                  <label className="block text-xs font-mono text-slate-300 mb-1.5">
                    Timezone
                  </label>
                  <input
                    type="text"
                    value={bizForm.timezone}
                    onChange={(e) => setBizForm({ ...bizForm, timezone: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan text-slate-200 text-sm focus:outline-none"
                    placeholder="UTC, America/New_York"
                  />
                </div>

                <div>
                  <label className="block text-xs font-mono text-slate-300 mb-1.5">
                    Fiscal Year Start (Month 1-12)
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={12}
                    value={bizForm.fiscal_year_start}
                    onChange={(e) =>
                      setBizForm({ ...bizForm, fiscal_year_start: parseInt(e.target.value) || 1 })
                    }
                    className="w-full px-3.5 py-2.5 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan text-slate-200 text-sm focus:outline-none"
                  />
                </div>
              </div>

              <div className="pt-4 flex justify-end">
                <button
                  type="submit"
                  disabled={loading}
                  className="px-6 py-2.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-semibold text-xs transition-all flex items-center gap-2 shadow-sm disabled:opacity-50"
                >
                  <span>{loading ? 'Saving...' : 'Save & Continue'}</span>
                  <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            </form>
          </div>
        )}

        {/* STEP 2: BUSINESS CONTEXT (OPTIONAL) */}
        {step === 2 && (
          <div className="bg-surface/60 border border-surface-elevated rounded-2xl p-6 sm:p-8 backdrop-blur-sm shadow-xl">
            <div className="flex items-start justify-between mb-6">
              <div>
                <span className="text-[11px] font-mono uppercase text-brand-cyan font-semibold tracking-wider">
                  Step 2 of 4 (Optional)
                </span>
                <h2 className="text-xl font-bold text-white mt-1">Teach NEXUS Your Business Context</h2>
                <p className="text-xs text-slate-400 mt-1">
                  Feed organizational policies, custom KPIs, and domain terminology into your tenant-isolated RAG layer.
                </p>
              </div>
              <span className="px-2.5 py-1 rounded-full bg-surface-elevated border border-slate-700 text-[10px] font-mono text-slate-400">
                Optional
              </span>
            </div>

            <div className="space-y-4">
              <div className="p-3.5 rounded-xl bg-cyan-950/40 border border-cyan-500/20 text-xs text-cyan-200 flex items-center gap-3">
                <Info className="w-4 h-4 text-brand-cyan shrink-0" />
                <span>
                  Business context informs intelligence reasoning, but deterministic analytics remains authoritative for factual numbers. You can skip this step at any time.
                </span>
              </div>

              <div>
                <label className="block text-xs font-mono text-slate-300 mb-1.5">
                  Core Business Rule / Policy Name
                </label>
                <input
                  type="text"
                  value={contextForm.ruleName}
                  onChange={(e) => setContextForm({ ...contextForm, ruleName: e.target.value })}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan text-slate-200 text-sm focus:outline-none"
                  placeholder="e.g. Target Operating Margin"
                />
              </div>

              <div>
                <label className="block text-xs font-mono text-slate-300 mb-1.5">
                  Rule Logic / Standard
                </label>
                <textarea
                  rows={2}
                  value={contextForm.ruleLogic}
                  onChange={(e) => setContextForm({ ...contextForm, ruleLogic: e.target.value })}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan text-slate-200 text-sm focus:outline-none"
                  placeholder="Describe your standard threshold or requirement..."
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-mono text-slate-300 mb-1.5">
                    Custom Term / Acronym
                  </label>
                  <input
                    type="text"
                    value={contextForm.term}
                    onChange={(e) => setContextForm({ ...contextForm, term: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan text-slate-200 text-sm focus:outline-none"
                    placeholder="e.g. GMV, CAC, SKU"
                  />
                </div>
                <div>
                  <label className="block text-xs font-mono text-slate-300 mb-1.5">
                    Definition
                  </label>
                  <input
                    type="text"
                    value={contextForm.definition}
                    onChange={(e) => setContextForm({ ...contextForm, definition: e.target.value })}
                    className="w-full px-3.5 py-2.5 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan text-slate-200 text-sm focus:outline-none"
                    placeholder="Explain how your business defines this term"
                  />
                </div>
              </div>

              <div className="pt-4 flex items-center justify-between">
                <button
                  type="button"
                  onClick={() => setStep(1)}
                  className="px-4 py-2 rounded-xl text-xs text-slate-400 hover:text-slate-200 flex items-center gap-1.5"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  <span>Back</span>
                </button>

                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => handleSaveContext(true)}
                    className="px-4 py-2 rounded-xl border border-surface-elevated hover:bg-surface-elevated text-xs text-slate-300 font-medium transition-all"
                  >
                    Skip Context
                  </button>
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => handleSaveContext(false)}
                    className="px-6 py-2.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-semibold text-xs transition-all flex items-center gap-2 shadow-sm disabled:opacity-50"
                  >
                    <span>{loading ? 'Registering...' : 'Save & Continue'}</span>
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* STEP 3: CONNECT DATA */}
        {step === 3 && (
          <div className="bg-surface/60 border border-surface-elevated rounded-2xl p-6 sm:p-8 backdrop-blur-sm shadow-xl">
            <div className="mb-6">
              <span className="text-[11px] font-mono uppercase text-brand-cyan font-semibold tracking-wider">
                Step 3 of 4
              </span>
              <h2 className="text-xl font-bold text-white mt-1">Connect Your Business Data</h2>
              <p className="text-xs text-slate-400 mt-1">
                Upload commercial records (Sales, Customers, Products, or Expenses) in CSV or XLSX format for tenant-scoped ingestion.
              </p>
            </div>

            <div className="space-y-6">
              {/* File Dropzone */}
              <label
                className={`border-2 border-dashed rounded-2xl p-8 flex flex-col items-center justify-center text-center cursor-pointer transition-all ${
                  uploadProgress
                    ? 'border-brand-cyan bg-cyan-950/20'
                    : 'border-surface-elevated hover:border-brand-cyan/60 hover:bg-surface/80'
                }`}
              >
                <input
                  type="file"
                  accept=".csv, .xlsx, .xls"
                  onChange={handleFileUpload}
                  disabled={uploadProgress}
                  className="hidden"
                />
                <div className="w-14 h-14 rounded-2xl bg-cyan-950/80 border border-brand-cyan/30 flex items-center justify-center text-brand-cyan mb-3">
                  {uploadProgress ? (
                    <RefreshCw className="w-6 h-6 animate-spin text-brand-cyan" />
                  ) : (
                    <UploadCloud className="w-6 h-6" />
                  )}
                </div>
                <h3 className="text-sm font-semibold text-slate-100">
                  {uploadProgress ? 'Profiling and Ingesting Dataset...' : 'Click or drag CSV or XLSX file here'}
                </h3>
                <p className="text-xs text-slate-400 mt-1 max-w-sm">
                  Support for tabular sales transactions, customer cohorts, product catalogs, and operational ledgers up to 50MB.
                </p>
              </label>

              {/* Uploaded Datasets List */}
              {onboardingData?.datasets && onboardingData.datasets.length > 0 && (
                <div className="space-y-3">
                  <h4 className="text-xs font-mono uppercase tracking-wider text-slate-400">
                    Uploaded Datasets ({onboardingData.datasets.length})
                  </h4>
                  <div className="space-y-2">
                    {onboardingData.datasets.map((ds) => (
                      <div
                        key={ds.id}
                        className="p-3.5 rounded-xl bg-void border border-surface-elevated flex items-center justify-between text-xs"
                      >
                        <div className="flex items-center gap-3">
                          <FileSpreadsheet className="w-4 h-4 text-brand-cyan" />
                          <div>
                            <span className="font-semibold text-slate-200">{ds.filename}</span>
                            <div className="flex items-center gap-2 text-[10px] font-mono text-slate-400 mt-0.5">
                              <span>{ds.row_count} rows</span>
                              <span>•</span>
                              <span>{ds.column_count} columns</span>
                              <span>•</span>
                              <span className="uppercase">{ds.file_type}</span>
                            </div>
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

              <div className="pt-4 flex items-center justify-between">
                <button
                  type="button"
                  onClick={() => setStep(2)}
                  className="px-4 py-2 rounded-xl text-xs text-slate-400 hover:text-slate-200 flex items-center gap-1.5"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  <span>Back</span>
                </button>

                <button
                  type="button"
                  onClick={() => setStep(4)}
                  className="px-6 py-2.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-semibold text-xs transition-all flex items-center gap-2 shadow-sm"
                >
                  <span>Review Data Readiness</span>
                  <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        )}

        {/* STEP 4: DATA READINESS & LAUNCH */}
        {step === 4 && (
          <div className="bg-surface/60 border border-surface-elevated rounded-2xl p-6 sm:p-8 backdrop-blur-sm shadow-xl">
            <div className="mb-6">
              <span className="text-[11px] font-mono uppercase text-brand-cyan font-semibold tracking-wider">
                Step 4 of 4
              </span>
              <h2 className="text-xl font-bold text-white mt-1">Data Readiness Assessment</h2>
              <p className="text-xs text-slate-400 mt-1">
                Deterministic profile scorecard verifying tenant data isolation, row coverage, and schema fidelity.
              </p>
            </div>

            <div className="space-y-6">
              {/* Readiness Banner */}
              <div
                className={`p-5 rounded-2xl border flex items-start gap-4 ${
                  onboardingData?.data_readiness?.status === 'ready'
                    ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-200'
                    : onboardingData?.data_readiness?.status === 'partial'
                    ? 'bg-amber-950/40 border-amber-500/40 text-amber-200'
                    : 'bg-surface border-surface-elevated text-slate-300'
                }`}
              >
                <div
                  className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 ${
                    onboardingData?.data_readiness?.status === 'ready'
                      ? 'bg-emerald-900/60 text-emerald-400 border border-emerald-500/40'
                      : 'bg-amber-900/60 text-amber-400 border border-amber-500/40'
                  }`}
                >
                  <Database className="w-5 h-5" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-bold text-sm tracking-wide uppercase font-mono">
                      {onboardingData?.data_readiness?.status === 'ready'
                        ? 'DATA READY'
                        : onboardingData?.data_readiness?.status === 'partial'
                        ? 'DATA PARTIALLY READY'
                        : 'READY FOR EXPLORATION'}
                    </h3>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-void/60 border border-white/10 uppercase">
                      {onboardingData?.data_readiness?.status || 'Active'}
                    </span>
                  </div>
                  <p className="text-xs text-slate-300 mt-1">
                    {onboardingData?.data_readiness?.summary ||
                      'Tenant data workspace ready for deterministic queries and agentic intelligence inquiries.'}
                  </p>
                </div>
              </div>

              {/* Ingested Dataset Summary */}
              {onboardingData?.datasets && onboardingData.datasets.length > 0 ? (
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div className="p-4 rounded-xl bg-void border border-surface-elevated text-center">
                    <span className="text-[10px] font-mono uppercase text-slate-400">Total Datasets</span>
                    <p className="text-xl font-bold font-mono text-white mt-1">
                      {onboardingData.data_readiness?.total_datasets || onboardingData.datasets.length}
                    </p>
                  </div>
                  <div className="p-4 rounded-xl bg-void border border-surface-elevated text-center">
                    <span className="text-[10px] font-mono uppercase text-slate-400">Total Rows</span>
                    <p className="text-xl font-bold font-mono text-brand-cyan mt-1">
                      {onboardingData.data_readiness?.total_rows || 0}
                    </p>
                  </div>
                  <div className="p-4 rounded-xl bg-void border border-surface-elevated text-center">
                    <span className="text-[10px] font-mono uppercase text-slate-400">Domains Identified</span>
                    <p className="text-xl font-bold font-mono text-white mt-1">
                      {onboardingData.data_readiness?.domains_covered?.length || 1}
                    </p>
                  </div>
                </div>
              ) : (
                <div className="p-6 rounded-xl bg-void border border-surface-elevated text-center">
                  <p className="text-xs text-slate-400">
                    No custom datasets uploaded yet. You can launch into your workspace now and upload anytime in Data Health.
                  </p>
                </div>
              )}

              {/* Action Buttons */}
              <div className="pt-4 flex items-center justify-between">
                <button
                  type="button"
                  onClick={() => setStep(3)}
                  className="px-4 py-2 rounded-xl text-xs text-slate-400 hover:text-slate-200 flex items-center gap-1.5"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  <span>Upload More Data</span>
                </button>

                <button
                  type="button"
                  disabled={loading}
                  onClick={handleComplete}
                  className="px-8 py-3 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-xs tracking-wider uppercase font-mono transition-all flex items-center gap-2 shadow-glow-cyan disabled:opacity-50"
                >
                  <Sparkles className="w-4 h-4 text-cyan-200" />
                  <span>{loading ? 'Initializing...' : 'Enter NEXUS Workspace'}</span>
                  <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
