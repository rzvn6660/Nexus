import React, { useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Building,
  Check,
  Eye,
  EyeOff,
  Lock,
  Mail,
  ShieldAlert,
  Store,
  User,
} from 'lucide-react';
import { AuthService } from '../services/auth';
import { NexusSymbol } from '../components/brand/NexusSymbol';

interface SignupPageProps {
  onNavigate: (route: string) => void;
  onSignupSuccess: () => void;
}

export const SignupPage: React.FC<SignupPageProps> = ({ onNavigate, onSignupSuccess }) => {
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [orgName, setOrgName] = useState('');
  const [businessName, setBusinessName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Email format validation helper
  const isValidEmailFormat = (emailStr: string): boolean => {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailStr);
  };

  // Calm password strength evaluation
  const getPasswordStrength = (pwd: string) => {
    if (!pwd) return { score: 0, label: '', textClass: 'text-slate-500' };
    let score = 0;
    if (pwd.length >= 8) score += 1;
    if (/[A-Z]/.test(pwd) && /[a-z]/.test(pwd)) score += 1;
    if (/[0-9]/.test(pwd)) score += 1;
    if (/[^A-Za-z0-9]/.test(pwd) || pwd.length >= 12) score += 1;

    switch (score) {
      case 1:
        return { score: 1, label: 'Weak (8+ characters required)', textClass: 'text-amber-400' };
      case 2:
        return { score: 2, label: 'Fair (add numbers or symbols)', textClass: 'text-amber-300' };
      case 3:
        return { score: 3, label: 'Good', textClass: 'text-cyan-400' };
      case 4:
        return { score: 4, label: 'Strong', textClass: 'text-emerald-400' };
      default:
        return { score: 0, label: '', textClass: 'text-slate-500' };
    }
  };

  const strength = getPasswordStrength(password);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) {
      setError('Please provide your work email address.');
      return;
    }
    if (!isValidEmailFormat(email.trim())) {
      setError('Please enter a valid work email format (e.g. name@company.com).');
      return;
    }
    if (!password || password.length < 8) {
      setError('Password must be at least 8 characters long.');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      await AuthService.signup({
        email: email.trim(),
        password,
        full_name: fullName.trim() || undefined,
        organization_name: orgName.trim() || undefined,
        business_name: businessName.trim() || undefined,
      });
      onSignupSuccess();
      onNavigate('/onboarding');
    } catch (err: any) {
      setError(
        err?.data?.detail ||
          err?.message ||
          'Registration failed. Please check your credentials or network connection.'
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen w-full bg-void text-slate-100 flex flex-col lg:flex-row relative overflow-hidden font-sans selection:bg-cyan-500/20 selection:text-cyan-200">
      {/* Ambient background depth */}
      <div className="absolute top-0 left-0 w-full h-full bg-[radial-gradient(ellipse_70%_50%_at_30%_0%,rgba(0,242,254,0.04),transparent_60%)] pointer-events-none" />

      {/* ========================================================
          LEFT COLUMN: THE INTELLIGENCE CANVAS (EDITORIAL BRAND)
          ======================================================== */}
      <div className="hidden lg:flex lg:w-[50%] xl:w-[48%] flex-col justify-between p-8 xl:p-14 2xl:p-16 border-r border-white/[0.04] bg-void-sub/20 backdrop-blur-sm relative z-10">
        {/* Top: Restrained brand lockup & back navigation */}
        <div className="space-y-5">
          <button
            type="button"
            onClick={() => onNavigate('/')}
            className="inline-flex items-center gap-2 text-xs font-mono text-slate-400 hover:text-cyan-300 transition-colors group cursor-pointer"
          >
            <ArrowLeft className="w-3.5 h-3.5 text-slate-500 group-hover:text-cyan-300 group-hover:-translate-x-0.5 transition-transform" />
            <span>Back to Overview</span>
          </button>

          <div className="flex items-center gap-3">
            <NexusSymbol size={32} className="drop-shadow-[0_0_16px_rgba(0,242,254,0.25)]" />
            <div className="flex items-center gap-2.5">
              <span className="text-xl font-bold tracking-[0.18em] text-white font-sans">NEXUS</span>
              <span className="h-3 w-px bg-white/10" />
              <span className="text-[11px] font-mono tracking-wider text-slate-400 uppercase">
                Intelligence Platform
              </span>
            </div>
          </div>
        </div>

        {/* Center: Editorial Concept & Bespoke Flow Illustration */}
        <div className="py-6 xl:py-8 space-y-6 max-w-xl">
          <div className="space-y-3">
            <span className="text-[11px] font-mono tracking-[0.2em] text-cyan-400/90 uppercase block font-semibold">
              The Intelligence Canvas
            </span>
            <h1 className="text-3xl sm:text-4xl xl:text-5xl font-light tracking-tight text-white leading-[1.14] font-sans">
              Make every business decision <span className="font-semibold text-slate-100">easier to explain.</span>
            </h1>
            <p className="text-sm xl:text-base text-slate-400 font-normal leading-relaxed max-w-md font-sans pt-1">
              NEXUS connects your operational data to deterministic analytics—giving leaders clear numbers, direct drivers, and inspectable evidence.
            </p>
          </div>

          {/* Bespoke SVG: Flowing connections between business data, analysis, and traceable evidence */}
          <div className="relative pt-2">
            <svg
              viewBox="0 0 540 220"
              className="w-full max-w-[490px] h-auto"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              aria-label="Illustration showing business data flowing through deterministic analysis into traceable evidence"
            >
              <defs>
                <linearGradient id="flowLineGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#00F2FE" stopOpacity="0.6" />
                  <stop offset="50%" stopColor="#38BDF8" stopOpacity="0.8" />
                  <stop offset="100%" stopColor="#10B981" stopOpacity="0.7" />
                </linearGradient>
                <radialGradient id="nodeGlow" cx="50%" cy="50%" r="50%">
                  <stop offset="0%" stopColor="#00F2FE" stopOpacity="0.25" />
                  <stop offset="100%" stopColor="#00F2FE" stopOpacity="0" />
                </radialGradient>
              </defs>

              {/* Faint subtle grid guides */}
              <line x1="60" y1="20" x2="60" y2="180" stroke="#1E293B" strokeWidth="0.75" strokeDasharray="3 3" opacity="0.4" />
              <line x1="270" y1="20" x2="270" y2="180" stroke="#1E293B" strokeWidth="0.75" strokeDasharray="3 3" opacity="0.4" />
              <line x1="470" y1="20" x2="470" y2="180" stroke="#1E293B" strokeWidth="0.75" strokeDasharray="3 3" opacity="0.4" />

              {/* Left Data Nodes (Business data) */}
              <circle cx="60" cy="50" r="14" fill="url(#nodeGlow)" />
              <circle cx="60" cy="50" r="4" fill="#00F2FE" />
              <circle cx="60" cy="50" r="8" stroke="#00F2FE" strokeWidth="1" strokeOpacity="0.4" />

              <circle cx="60" cy="110" r="14" fill="url(#nodeGlow)" />
              <circle cx="60" cy="110" r="4" fill="#38BDF8" />
              <circle cx="60" cy="110" r="8" stroke="#38BDF8" strokeWidth="1" strokeOpacity="0.4" />

              <circle cx="60" cy="170" r="14" fill="url(#nodeGlow)" />
              <circle cx="60" cy="170" r="4" fill="#0284C7" />
              <circle cx="60" cy="170" r="8" stroke="#0284C7" strokeWidth="1" strokeOpacity="0.4" />

              {/* Flowing connector paths converging into central field */}
              <path
                d="M 68 50 C 140 50, 180 110, 254 110"
                stroke="url(#flowLineGrad)"
                strokeWidth="1.5"
                opacity="0.85"
              />
              <path
                d="M 68 110 L 254 110"
                stroke="url(#flowLineGrad)"
                strokeWidth="1.5"
                opacity="0.9"
              />
              <path
                d="M 68 170 C 140 170, 180 110, 254 110"
                stroke="url(#flowLineGrad)"
                strokeWidth="1.5"
                opacity="0.85"
              />

              {/* Subtle harmonic arcs */}
              <path
                d="M 68 50 C 120 70, 170 110, 254 110"
                stroke="#00F2FE"
                strokeWidth="0.75"
                strokeDasharray="2 4"
                opacity="0.3"
              />
              <path
                d="M 68 170 C 120 150, 170 110, 254 110"
                stroke="#00F2FE"
                strokeWidth="0.75"
                strokeDasharray="2 4"
                opacity="0.3"
              />

              {/* Central Analytical Field (Deterministic analysis) */}
              <circle cx="270" cy="110" r="32" stroke="#00F2FE" strokeWidth="1" strokeOpacity="0.2" strokeDasharray="4 3" />
              <circle cx="270" cy="110" r="22" stroke="#38BDF8" strokeWidth="1.25" strokeOpacity="0.5" />
              <circle cx="270" cy="110" r="14" fill="#090E17" stroke="#00F2FE" strokeWidth="1.5" strokeOpacity="0.8" />
              <circle cx="270" cy="110" r="4.5" fill="#00F2FE" />

              {/* Crosshair telemetry guides */}
              <line x1="270" y1="82" x2="270" y2="92" stroke="#00F2FE" strokeWidth="1" opacity="0.6" />
              <line x1="270" y1="128" x2="270" y2="138" stroke="#00F2FE" strokeWidth="1" opacity="0.6" />
              <line x1="242" y1="110" x2="252" y2="110" stroke="#00F2FE" strokeWidth="1" opacity="0.6" />
              <line x1="288" y1="110" x2="298" y2="110" stroke="#00F2FE" strokeWidth="1" opacity="0.6" />

              {/* Vector line to evidence endpoint */}
              <path
                d="M 286 110 L 460 110"
                stroke="url(#flowLineGrad)"
                strokeWidth="1.75"
                opacity="0.95"
              />
              <path
                d="M 286 110 C 340 100, 400 100, 460 110"
                stroke="#10B981"
                strokeWidth="0.75"
                strokeDasharray="3 3"
                opacity="0.4"
              />

              {/* Right Endpoint Node (Traceable evidence) */}
              <circle cx="470" cy="110" r="16" fill="url(#nodeGlow)" />
              <circle cx="470" cy="110" r="10" fill="#071912" stroke="#10B981" strokeWidth="1.5" />
              <circle cx="470" cy="110" r="4" fill="#10B981" />

              {/* Precision tick marks around endpoint */}
              <circle cx="470" cy="110" r="18" stroke="#10B981" strokeWidth="0.75" strokeOpacity="0.3" strokeDasharray="2 3" />

              {/* ========================================================
                  THREE UNDERSTATED LABELS (HIGH CONTRAST & CRISP)
                  ======================================================== */}
              <text x="60" y="206" fill="#E2E8F0" fontSize="11" fontFamily="monospace" fontWeight="600" textAnchor="middle" letterSpacing="0.05em">
                Business data
              </text>
              <text x="270" y="206" fill="#E2E8F0" fontSize="11" fontFamily="monospace" fontWeight="600" textAnchor="middle" letterSpacing="0.05em">
                Deterministic analysis
              </text>
              <text x="470" y="206" fill="#E2E8F0" fontSize="11" fontFamily="monospace" fontWeight="600" textAnchor="middle" letterSpacing="0.05em">
                Traceable evidence
              </text>
            </svg>
          </div>
        </div>

        {/* Bottom: Minimalist, factual reassurance */}
        <div className="pt-6 border-t border-white/[0.04] text-[11px] font-mono text-slate-400 flex items-center justify-between">
          <span>Tenant workspace scoping</span>
          <span>Inspectable SQL provenance</span>
        </div>
      </div>

      {/* ========================================================
          RIGHT COLUMN: REFINED REGISTRATION FORM
          ======================================================== */}
      <div className="w-full lg:w-[50%] xl:w-[52%] flex flex-col justify-center items-center p-6 sm:p-10 xl:p-14 2xl:p-16 relative z-10 overflow-y-auto">
        <div className="w-full max-w-[440px] mx-auto space-y-6">
          {/* Mobile Top Header */}
          <div className="lg:hidden flex items-center justify-between pb-4 border-b border-surface-elevated/60">
            <div className="flex items-center gap-2.5">
              <NexusSymbol size={28} />
              <span className="text-lg font-bold tracking-[0.18em] text-white">NEXUS</span>
            </div>
            <button
              type="button"
              onClick={() => onNavigate('/')}
              className="text-xs font-mono text-slate-400 hover:text-cyan-300 transition-colors"
            >
              ← Overview
            </button>
          </div>

          {/* Form Title & Subtitle */}
          <div className="space-y-1.5">
            <h2 className="text-2xl sm:text-3xl font-semibold tracking-tight text-white font-sans">
              Create your workspace
            </h2>
            <p className="text-xs sm:text-sm text-slate-400 font-sans">
              Set up your account to explore evidence-backed business intelligence.
            </p>
          </div>

          {/* Form Card Container */}
          <div className="rounded-2xl border border-white/[0.07] bg-void-sub/75 p-6 sm:p-8 shadow-2xl backdrop-blur-xl space-y-5">
            {/* Error Banner */}
            {error && (
              <div
                role="alert"
                className="p-3.5 rounded-xl bg-rose-950/60 border border-rose-500/40 flex items-start gap-3 text-xs text-rose-200 animate-in fade-in duration-150"
              >
                <ShieldAlert className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                <div className="space-y-0.5">
                  <span className="font-semibold block">Registration Notice</span>
                  <span className="text-rose-300 leading-relaxed">{error}</span>
                </div>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4" noValidate>
              {/* Row 1: Full Name & Work Email */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                <div>
                  <label htmlFor="reg-fullname" className="block text-xs font-medium text-slate-200 mb-1.5 font-sans">
                    Full name <span className="text-slate-500 font-normal ml-0.5">(Optional)</span>
                  </label>
                  <div className="relative">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-500">
                      <User className="w-4 h-4" />
                    </div>
                    <input
                      id="reg-fullname"
                      type="text"
                      autoComplete="name"
                      value={fullName}
                      onChange={(e) => setFullName(e.target.value)}
                      placeholder="Alex Morgan"
                      disabled={loading}
                      className="input-obsidian text-sm h-11 pl-9 w-full font-sans"
                    />
                  </div>
                </div>

                <div>
                  <label htmlFor="reg-email" className="block text-xs font-medium text-slate-200 mb-1.5 font-sans">
                    Work email address <span className="text-cyan-400 ml-0.5">*</span>
                  </label>
                  <div className="relative">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-500">
                      <Mail className="w-4 h-4" />
                    </div>
                    <input
                      id="reg-email"
                      type="email"
                      required
                      autoComplete="email"
                      value={email}
                      onChange={(e) => {
                        setEmail(e.target.value);
                        if (error) setError(null);
                      }}
                      placeholder="name@company.com"
                      disabled={loading}
                      className={`input-obsidian text-sm h-11 pl-9 w-full font-sans ${
                        email && !isValidEmailFormat(email)
                          ? 'border-amber-500/50 focus:border-amber-400'
                          : email && isValidEmailFormat(email)
                          ? 'border-emerald-500/40 focus:border-emerald-400'
                          : ''
                      }`}
                    />
                  </div>
                </div>
              </div>

              {/* Row 2: Master Password with Understated Strength Feedback */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label htmlFor="reg-password" className="block text-xs font-medium text-slate-200 font-sans">
                    Password <span className="text-cyan-400 ml-0.5">*</span>
                  </label>
                  {password.length > 0 && (
                    <span className={`text-[11px] font-mono ${strength.textClass} font-semibold`}>
                      {strength.label}
                    </span>
                  )}
                </div>

                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-500">
                    <Lock className="w-4 h-4" />
                  </div>
                  <input
                    id="reg-password"
                    type={showPassword ? 'text' : 'password'}
                    required
                    minLength={8}
                    autoComplete="new-password"
                    value={password}
                    onChange={(e) => {
                      setPassword(e.target.value);
                      if (error) setError(null);
                    }}
                    placeholder="Min 8 characters..."
                    disabled={loading}
                    className={`input-obsidian text-sm h-11 pl-9 pr-10 w-full font-sans ${
                      password.length > 0 && password.length < 8
                        ? 'border-amber-500/50 focus:border-amber-400'
                        : password.length >= 8
                        ? 'border-emerald-500/50 focus:border-emerald-400'
                        : ''
                    }`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                    className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-400 hover:text-slate-200 transition-colors cursor-pointer"
                  >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>

                {/* Subtle Password Strength Indicator */}
                <div className="mt-2 space-y-1.5">
                  <div className="grid grid-cols-4 gap-1.5 h-1">
                    {[1, 2, 3, 4].map((step) => {
                      const isActive = strength.score >= step;
                      const activeColor =
                        strength.score === 1
                          ? 'bg-amber-500'
                          : strength.score === 2
                          ? 'bg-amber-400'
                          : strength.score === 3
                          ? 'bg-cyan-500'
                          : 'bg-emerald-500';

                      return (
                        <div
                          key={step}
                          className={`h-full rounded-full transition-colors duration-200 ${
                            isActive ? activeColor : 'bg-surface-elevated/70'
                          }`}
                        />
                      );
                    })}
                  </div>

                  <div className="flex items-center justify-between text-[11px] text-slate-500 font-mono">
                    <span>Minimum 8 characters</span>
                    {password.length >= 8 && (
                      <span className="text-emerald-400 inline-flex items-center gap-1 font-semibold">
                        <Check className="w-3 h-3 text-emerald-400" /> Meets minimum
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Row 3: Organization & Initial Business Workspace */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5 pt-1">
                <div>
                  <label htmlFor="reg-orgname" className="block text-xs font-medium text-slate-200 mb-1.5 font-sans">
                    Organization <span className="text-slate-500 font-normal ml-0.5">(Optional)</span>
                  </label>
                  <div className="relative">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-500">
                      <Building className="w-4 h-4" />
                    </div>
                    <input
                      id="reg-orgname"
                      type="text"
                      autoComplete="organization"
                      value={orgName}
                      onChange={(e) => setOrgName(e.target.value)}
                      placeholder="Acme Corp"
                      disabled={loading}
                      className="input-obsidian text-sm h-11 pl-9 w-full font-sans"
                    />
                  </div>
                </div>

                <div>
                  <label htmlFor="reg-businessname" className="block text-xs font-medium text-slate-200 mb-1.5 font-sans">
                    Workspace name <span className="text-slate-500 font-normal ml-0.5">(Optional)</span>
                  </label>
                  <div className="relative">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-500">
                      <Store className="w-4 h-4" />
                    </div>
                    <input
                      id="reg-businessname"
                      type="text"
                      value={businessName}
                      onChange={(e) => setBusinessName(e.target.value)}
                      placeholder="Retail Division"
                      disabled={loading}
                      className="input-obsidian text-sm h-11 pl-9 w-full font-sans"
                    />
                  </div>
                </div>
              </div>

              {/* Primary Action Button */}
              <div className="pt-2">
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full h-11 px-4 rounded-xl bg-cyan-500 hover:bg-cyan-400 active:scale-[0.99] disabled:opacity-60 text-slate-950 text-sm font-semibold shadow-lg shadow-cyan-950/40 flex items-center justify-center gap-2 transition-all cursor-pointer"
                >
                  {loading ? (
                    <>
                      <div className="w-4 h-4 border-2 border-slate-950/30 border-t-slate-950 rounded-full animate-spin shrink-0" />
                      <span>Provisioning workspace...</span>
                    </>
                  ) : (
                    <>
                      <span>Initialize Workspace</span>
                      <ArrowRight className="w-4 h-4" />
                    </>
                  )}
                </button>
              </div>
            </form>

            {/* Existing-Account Sign-In Link */}
            <div className="pt-4 border-t border-white/[0.06] text-center">
              <p className="text-xs text-slate-400 font-sans">
                Already have an account?{' '}
                <button
                  type="button"
                  onClick={() => onNavigate('/login')}
                  className="font-semibold text-cyan-400 hover:text-cyan-300 transition-colors ml-1 cursor-pointer hover:underline"
                >
                  Sign in
                </button>
              </p>
            </div>
          </div>

          {/* Understated Factual Reassurance */}
          <div className="text-center text-[11px] font-mono text-slate-500">
            <span>Tenant-scoped workspace • Role-based access controls</span>
          </div>
        </div>
      </div>
    </div>
  );
};
