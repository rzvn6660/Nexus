import React, { useState } from 'react';
import { ArrowRight, Lock, Mail, ShieldAlert, Sparkles } from 'lucide-react';
import { AuthService } from '../services/auth';
import { NexusSymbol } from '../components/brand/NexusSymbol';

interface LoginPageProps {
  onNavigate: (route: string) => void;
  onLoginSuccess: () => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onNavigate, onLoginSuccess }) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      setError('Please provide both email and password.');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await AuthService.login({ email, password });
      onLoginSuccess();
      if (res.business?.onboarding_step !== 'completed') {
        onNavigate('/onboarding');
      } else {
        onNavigate('/');
      }
    } catch (err: any) {
      setError(err?.data?.detail || err?.message || 'Login failed. Please verify your credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-void flex flex-col justify-center items-center px-4 sm:px-6 lg:px-8 py-12 selection:bg-cyan-500/20 selection:text-cyan-200">
      <div className="w-full max-w-md space-y-8">
        {/* Back to Landing Navigation */}
        <div className="flex justify-start">
          <button
            type="button"
            onClick={() => onNavigate('/')}
            className="text-xs font-mono text-slate-400 hover:text-cyan-400 transition-colors inline-flex items-center gap-1 cursor-pointer"
          >
            <span>← Back to NEXUS Overview</span>
          </button>
        </div>

        {/* Brand Header */}
        <div className="text-center space-y-3">
          <div className="flex justify-center mb-1">
            <NexusSymbol size={48} className="mx-auto" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-white font-sans">
            Sign In to <span className="tracking-[0.16em]">NEXUS</span>
          </h1>
          <p className="text-xs sm:text-sm text-slate-400">
            Agentic Business Intelligence Platform for Modern Enterprises
          </p>
        </div>

        {/* Auth Form Card */}
        <div className="bg-surface/80 border border-surface-elevated/80 rounded-2xl p-6 sm:p-8 shadow-2xl backdrop-blur-xl">
          {error && (
            <div className="mb-6 p-3.5 rounded-xl bg-rose-950/60 border border-rose-500/30 flex items-start gap-3 text-xs text-rose-300">
              <ShieldAlert className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
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
                  placeholder="name@company.com"
                  className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan/60 focus:ring-1 focus:ring-brand-cyan/40 text-sm text-slate-100 placeholder-slate-500 transition-all font-sans"
                />
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="block text-xs font-medium text-slate-300 font-sans">
                  Password
                </label>
                <span className="text-[11px] text-cyan-400 hover:text-cyan-300 cursor-pointer">
                  Forgot password?
                </span>
              </div>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500">
                  <Lock className="w-4 h-4" />
                </div>
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-void border border-surface-elevated focus:border-brand-cyan/60 focus:ring-1 focus:ring-brand-cyan/40 text-sm text-slate-100 placeholder-slate-500 transition-all font-sans"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 px-4 rounded-xl bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white text-sm font-semibold shadow-lg shadow-cyan-950/50 flex items-center justify-center gap-2 transition-all cursor-pointer"
            >
              {loading ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/20 border-t-white rounded-full animate-spin" />
                  <span>Verifying identity...</span>
                </>
              ) : (
                <>
                  <span>Sign In to Workspace</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>

          <div className="mt-6 pt-6 border-t border-surface-elevated/60 text-center">
            <p className="text-xs text-slate-400">
              New to NEXUS?{' '}
              <button
                type="button"
                onClick={() => onNavigate('/signup')}
                className="font-medium text-cyan-400 hover:text-cyan-300 transition-colors ml-1 cursor-pointer"
              >
                Create your business workspace
              </button>
            </p>
          </div>
        </div>

        {/* Security Assurance Guarantee */}
        <div className="flex items-center justify-center gap-2 text-[11px] font-mono text-slate-500">
          <Sparkles className="w-3.5 h-3.5 text-cyan-400/80" />
          <span>Multi-Tenant Data Isolation • Zero Cross-Tenant Leakage</span>
        </div>
      </div>
    </div>
  );
};
