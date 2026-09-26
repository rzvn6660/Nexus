import React, { useState } from 'react';
import { ArrowRight, Building, CheckCircle2, Lock, Mail, ShieldAlert, User } from 'lucide-react';
import { AuthService } from '../services/auth';

interface SignupPageProps {
  onNavigate: (route: string) => void;
  onSignupSuccess: () => void;
}

export const SignupPage: React.FC<SignupPageProps> = ({ onNavigate, onSignupSuccess }) => {
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [orgName, setOrgName] = useState('');
  const [businessName, setBusinessName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password || password.length < 8) {
      setError('Please provide a valid email and a password of at least 8 characters.');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      await AuthService.signup({
        email,
        password,
        full_name: fullName || undefined,
        organization_name: orgName || undefined,
        business_name: businessName || undefined,
      });
      onSignupSuccess();
      onNavigate('/onboarding');
    } catch (err: any) {
      setError(err?.data?.detail || err?.message || 'Registration failed. Please check your information.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-void flex flex-col justify-center items-center px-4 sm:px-6 lg:px-8 py-12 selection:bg-cyan-500/20 selection:text-cyan-200">
      <div className="w-full max-w-lg space-y-8">
        {/* Brand Header */}
        <div className="text-center space-y-3">
          <div className="inline-flex items-center justify-center p-3 rounded-2xl bg-cyan-950/40 border border-brand-cyan/30 shadow-lg shadow-cyan-950/50 mb-2">
            <img
              src="/brand/nexus-logo-bg.png"
              alt="NEXUS"
              className="w-10 h-10 object-contain select-none"
              draggable={false}
            />
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-white font-sans">
            Start Your <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-sky-300">NEXUS</span> Intelligence Trial
          </h1>
          <p className="text-xs sm:text-sm text-slate-400">
            Isolated tenant workspace, deterministic analytics, and verifiable provenance
          </p>
        </div>

        {/* Signup Form Card */}
        <div className="bg-surface/80 border border-surface-elevated/80 rounded-2xl p-6 sm:p-8 shadow-2xl backdrop-blur-xl">
          {error && (
            <div className="mb-6 p-3.5 rounded-xl bg-rose-950/60 border border-rose-500/30 flex items-start gap-3 text-xs text-rose-300">
              <ShieldAlert className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5 font-sans">
                  Your Name
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500">
                    <User className="w-4 h-4" />
                  </div>
                  <input
                    type="text"
                    required
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="Alex Morgan"
                    className="w-full pl-10 pr-4 py-2 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan/60 text-sm text-slate-100 placeholder-slate-500 font-sans"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5 font-sans">
                  Work Email Address
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500">
                    <Mail className="w-4 h-4" />
                  </div>
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="alex@company.com"
                    className="w-full pl-10 pr-4 py-2 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan/60 text-sm text-slate-100 placeholder-slate-500 font-sans"
                  />
                </div>
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1.5 font-sans">
                Password (minimum 8 characters)
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500">
                  <Lock className="w-4 h-4" />
                </div>
                <input
                  type="password"
                  required
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="w-full pl-10 pr-4 py-2 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan/60 text-sm text-slate-100 placeholder-slate-500 font-sans"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5 font-sans">
                  Company / Organization
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500">
                    <Building className="w-4 h-4" />
                  </div>
                  <input
                    type="text"
                    value={orgName}
                    onChange={(e) => setOrgName(e.target.value)}
                    placeholder="Acme Global Inc."
                    className="w-full pl-10 pr-4 py-2 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan/60 text-sm text-slate-100 placeholder-slate-500 font-sans"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5 font-sans">
                  Business Workspace Name
                </label>
                <input
                  type="text"
                  value={businessName}
                  onChange={(e) => setBusinessName(e.target.value)}
                  placeholder="Acme Retail Division"
                  className="w-full px-4 py-2 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan/60 text-sm text-slate-100 placeholder-slate-500 font-sans"
                />
              </div>
            </div>

            <div className="pt-2">
              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 px-4 rounded-xl bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white text-sm font-semibold shadow-lg shadow-cyan-950/50 flex items-center justify-center gap-2 transition-all cursor-pointer"
              >
                {loading ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white/20 border-t-white rounded-full animate-spin" />
                    <span>Provisioning tenant workspace...</span>
                  </>
                ) : (
                  <>
                    <span>Create Account & Continue</span>
                    <ArrowRight className="w-4 h-4" />
                  </>
                )}
              </button>
            </div>
          </form>

          <div className="mt-5 pt-5 border-t border-surface-elevated/60 text-center">
            <p className="text-xs text-slate-400">
              Already have an account?{' '}
              <button
                type="button"
                onClick={() => onNavigate('/login')}
                className="font-medium text-cyan-400 hover:text-cyan-300 transition-colors ml-1 cursor-pointer"
              >
                Sign In
              </button>
            </p>
          </div>
        </div>

        {/* Feature Highlights */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-center text-[11px] text-slate-400 font-mono">
          <div className="p-2.5 rounded-xl bg-surface/50 border border-surface-elevated/50 flex items-center justify-center gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400" />
            <span>Dedicated Tenant Scope</span>
          </div>
          <div className="p-2.5 rounded-xl bg-surface/50 border border-surface-elevated/50 flex items-center justify-center gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400" />
            <span>CSV / XLSX Ingestion</span>
          </div>
          <div className="p-2.5 rounded-xl bg-surface/50 border border-surface-elevated/50 flex items-center justify-center gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400" />
            <span>Verifiable Evidence</span>
          </div>
        </div>
      </div>
    </div>
  );
};
