import React, { useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Eye,
  EyeOff,
  Lock,
  Mail,
  ShieldAlert,
} from 'lucide-react';
import { AuthService } from '../services/auth';
import { NexusSymbol } from '../components/brand/NexusSymbol';

interface LoginPageProps {
  onNavigate: (route: string) => void;
  onLoginSuccess: () => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onNavigate, onLoginSuccess }) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Email format validation helper
  const isValidEmail = (emailStr: string): boolean => {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailStr);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError('Please enter both your work email and password.');
      return;
    }
    if (!isValidEmail(email.trim())) {
      setError('Please enter a valid work email address format.');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await AuthService.login({ email: email.trim(), password });
      onLoginSuccess();
      if (res.business?.onboarding_step !== 'completed') {
        onNavigate('/onboarding');
      } else {
        onNavigate('/');
      }
    } catch (err: any) {
      setError(
        err?.data?.detail ||
          err?.message ||
          'Sign in failed. Please verify your credentials or network connection.'
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen w-full bg-void text-slate-100 flex flex-col justify-between items-center px-4 sm:px-6 py-4 sm:py-6 relative overflow-hidden font-sans selection:bg-cyan-500/20 selection:text-cyan-200">
      {/* Subtle Static Background Gradient & Fine Analytical Motif */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_60%_50%_at_50%_0%,rgba(0,242,254,0.04),transparent_70%)] pointer-events-none" />
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#1e293b08_1px,transparent_1px),linear-gradient(to_bottom,#1e293b08_1px,transparent_1px)] bg-[size:3.5rem_3.5rem] pointer-events-none" />

      {/* Top Header: Clean, Purposeful Back Navigation */}
      <header className="w-full max-w-[420px] mx-auto flex items-center justify-start relative z-10 pb-1">
        <button
          type="button"
          onClick={() => onNavigate('/')}
          className="inline-flex items-center gap-1.5 text-xs font-mono text-slate-400 hover:text-cyan-300 transition-colors group cursor-pointer"
        >
          <ArrowLeft className="w-3.5 h-3.5 text-slate-500 group-hover:text-cyan-300 group-hover:-translate-x-0.5 transition-transform" />
          <span>Back to Overview</span>
        </button>
      </header>

      {/* Centered Sign-In Content Card */}
      <main className="w-full max-w-[420px] mx-auto my-auto space-y-4 relative z-10">
        {/* Brand Lockup & Modest Heading */}
        <div className="text-center space-y-1.5">
          <div className="flex justify-center mb-0.5">
            <NexusSymbol size={36} className="drop-shadow-[0_0_16px_rgba(0,242,254,0.22)]" />
          </div>
          <div className="flex items-center justify-center gap-2">
            <span className="text-xl font-bold tracking-[0.18em] text-white font-sans">NEXUS</span>
          </div>
          <h1 className="text-2xl sm:text-[26px] font-semibold tracking-tight text-white font-sans">
            Welcome back.
          </h1>
          <p className="text-xs sm:text-sm text-slate-400 font-sans max-w-sm mx-auto">
            Sign in to continue to your business intelligence workspace.
          </p>
        </div>

        {/* Form Card Container */}
        <div className="rounded-2xl border border-white/[0.08] bg-surface-card/85 p-5 sm:p-6.5 shadow-obsidian backdrop-blur-xl space-y-4">
          {/* Accessible Error Banner */}
          {error && (
            <div
              role="alert"
              className="p-3 rounded-xl bg-rose-950/60 border border-rose-500/40 flex items-start gap-2.5 text-xs text-rose-200 animate-in fade-in duration-150"
            >
              <ShieldAlert className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
              <div className="space-y-0.5">
                <span className="font-semibold block">Authentication Notice</span>
                <span className="text-rose-300 leading-relaxed">{error}</span>
              </div>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-3.5" noValidate>
            {/* Work Email Field */}
            <div>
              <label htmlFor="login-email" className="block text-xs font-medium text-slate-200 mb-1.5 font-sans">
                Work email address <span className="text-cyan-400">*</span>
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                  <Mail className="w-4 h-4" />
                </div>
                <input
                  id="login-email"
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
                  className="input-obsidian text-sm h-11 pl-9 w-full font-sans border-white/[0.08]"
                />
              </div>
            </div>

            {/* Password Field with Accessible Visibility Toggle */}
            <div>
              <label htmlFor="login-password" className="block text-xs font-medium text-slate-200 mb-1.5 font-sans">
                Password <span className="text-cyan-400">*</span>
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                  <Lock className="w-4 h-4" />
                </div>
                <input
                  id="login-password"
                  type={showPassword ? 'text' : 'password'}
                  required
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    if (error) setError(null);
                  }}
                  placeholder="••••••••••••"
                  disabled={loading}
                  className="input-obsidian text-sm h-11 pl-9 pr-10 w-full font-sans border-white/[0.08]"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-400 hover:text-slate-200 focus:text-cyan-300 focus:outline-none transition-colors cursor-pointer"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Submit Action Button */}
            <div className="pt-1.5">
              <button
                type="submit"
                disabled={loading || !email.trim() || !password}
                className="w-full h-11 px-4 rounded-xl bg-cyan-500 hover:bg-cyan-400 active:scale-[0.99] disabled:opacity-50 disabled:pointer-events-none text-slate-950 text-sm font-semibold shadow-lg shadow-cyan-950/40 flex items-center justify-center gap-2 transition-all cursor-pointer"
              >
                {loading ? (
                  <>
                    <div className="w-4 h-4 border-2 border-slate-950/30 border-t-slate-950 rounded-full animate-spin shrink-0" />
                    <span>Signing in to workspace...</span>
                  </>
                ) : (
                  <>
                    <span>Sign in</span>
                    <ArrowRight className="w-4 h-4" />
                  </>
                )}
              </button>
            </div>
          </form>

          {/* Registration Navigation Link */}
          <div className="pt-3.5 border-t border-white/[0.06] text-center">
            <p className="text-xs text-slate-400 font-sans">
              Don&apos;t have an account?{' '}
              <button
                type="button"
                onClick={() => onNavigate('/signup')}
                className="font-semibold text-cyan-400 hover:text-cyan-300 transition-colors ml-1 cursor-pointer hover:underline"
              >
                Create an account
              </button>
            </p>
          </div>
        </div>
      </main>

      {/* Consolidated Factual Footer */}
      <footer className="w-full max-w-[420px] mx-auto text-center text-[11px] font-mono text-slate-500/80 pt-2 pb-1 relative z-10">
        <span>Tenant-scoped workspace • Role-based access controls</span>
      </footer>
    </div>
  );
};
