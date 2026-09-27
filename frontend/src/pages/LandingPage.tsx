import React, { useState } from 'react';
import {
  ArrowRight,
  Database,
  SearchCode,
  ShieldCheck,
  TrendingUp,
  Cpu,
  CheckCircle2,
  ChevronRight,
  UserCheck,
  Compass,
  Menu,
  X,
  HelpCircle,
} from 'lucide-react';
import { NexusLogo } from '../components/brand/NexusLogo';

interface LandingPageProps {
  onNavigate: (route: string) => void;
  isAuthenticated?: boolean;
}

export const LandingPage: React.FC<LandingPageProps> = ({
  onNavigate,
  isAuthenticated = false,
}) => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [activeProductTab, setActiveProductTab] = useState<
    'overview' | 'ask' | 'investigate' | 'forecast' | 'evidence'
  >('overview');

  const scrollToSection = (id: string) => {
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' });
    }
    setMobileMenuOpen(false);
  };

  return (
    <div className="min-h-screen bg-void text-slate-100 font-sans selection:bg-cyan-500/20 selection:text-cyan-200 relative overflow-x-hidden">
      {/* ─────────────────────────────────────────────────────────────
          1. NAVIGATION — MINIMAL, PROFESSIONAL, ENTERPRISE
      ───────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-50 backdrop-blur-xl bg-void/85 border-b border-surface-elevated/70 transition-all">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          {/* Brand Lockup */}
          <button
            onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
            className="cursor-pointer flex items-center gap-2 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 rounded"
            aria-label="NEXUS Home"
          >
            <NexusLogo imageSize={30} showTagline={false} />
          </button>

          {/* Desktop Navigation Links */}
          <nav className="hidden md:flex items-center space-x-8 text-xs font-mono tracking-wider text-slate-400">
            <button
              onClick={() => scrollToSection('how-it-works')}
              className="hover:text-cyan-400 transition-colors focus:outline-none focus-visible:text-cyan-400"
            >
              HOW IT WORKS
            </button>
            <button
              onClick={() => scrollToSection('capabilities')}
              className="hover:text-cyan-400 transition-colors focus:outline-none focus-visible:text-cyan-400"
            >
              CAPABILITIES
            </button>
            <button
              onClick={() => scrollToSection('trust')}
              className="hover:text-cyan-400 transition-colors focus:outline-none focus-visible:text-cyan-400"
            >
              TRUST & EVIDENCE
            </button>
            <button
              onClick={() => scrollToSection('product-preview')}
              className="hover:text-cyan-400 transition-colors focus:outline-none focus-visible:text-cyan-400"
            >
              PRODUCT
            </button>
          </nav>

          {/* Action CTAs */}
          <div className="hidden md:flex items-center space-x-4">
            {isAuthenticated ? (
              <button
                onClick={() => onNavigate('/')}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold text-xs tracking-wide transition-all shadow-[0_0_20px_rgba(0,242,254,0.25)] focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
              >
                Go to Workspace
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            ) : (
              <>
                <button
                  onClick={() => onNavigate('/login')}
                  className="px-4 py-2 text-xs font-mono text-slate-300 hover:text-white transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-slate-500 rounded"
                >
                  Sign In
                </button>
                <button
                  onClick={() => onNavigate('/signup')}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold text-xs tracking-wide transition-all shadow-[0_0_20px_rgba(0,242,254,0.25)] focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
                >
                  Get Started
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </>
            )}
          </div>

          {/* Mobile Menu Button */}
          <div className="md:hidden flex items-center">
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="p-2 text-slate-400 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 rounded"
              aria-label="Toggle navigation menu"
            >
              {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
            </button>
          </div>
        </div>

        {/* Mobile Dropdown */}
        {mobileMenuOpen && (
          <div className="md:hidden bg-surface-card/95 border-b border-surface-elevated/70 px-6 py-5 space-y-4">
            <button
              onClick={() => scrollToSection('how-it-works')}
              className="block w-full text-left text-sm font-mono text-slate-300 hover:text-cyan-400 py-1"
            >
              HOW IT WORKS
            </button>
            <button
              onClick={() => scrollToSection('capabilities')}
              className="block w-full text-left text-sm font-mono text-slate-300 hover:text-cyan-400 py-1"
            >
              CAPABILITIES
            </button>
            <button
              onClick={() => scrollToSection('trust')}
              className="block w-full text-left text-sm font-mono text-slate-300 hover:text-cyan-400 py-1"
            >
              TRUST & EVIDENCE
            </button>
            <button
              onClick={() => scrollToSection('product-preview')}
              className="block w-full text-left text-sm font-mono text-slate-300 hover:text-cyan-400 py-1"
            >
              PRODUCT
            </button>
            <div className="pt-3 border-t border-surface-elevated/70 flex flex-col gap-2.5">
              {isAuthenticated ? (
                <button
                  onClick={() => onNavigate('/')}
                  className="w-full text-center py-2.5 rounded-lg bg-cyan-500 text-slate-950 font-semibold text-xs"
                >
                  Go to Workspace
                </button>
              ) : (
                <>
                  <button
                    onClick={() => onNavigate('/login')}
                    className="w-full text-center py-2 text-xs font-mono text-slate-300 border border-surface-elevated rounded-lg"
                  >
                    Sign In
                  </button>
                  <button
                    onClick={() => onNavigate('/signup')}
                    className="w-full text-center py-2.5 rounded-lg bg-cyan-500 text-slate-950 font-semibold text-xs"
                  >
                    Get Started
                  </button>
                </>
              )}
            </div>
          </div>
        )}
      </header>

      {/* ─────────────────────────────────────────────────────────────
          2. HERO — VISUAL ANCHOR (NXST3), CONFIDENT POSITIONING
      ───────────────────────────────────────────────────────────── */}
      <section className="relative pt-12 pb-20 md:pt-16 md:pb-28 overflow-hidden">
        {/* Subtle Background Glow Accent */}
        <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[350px] bg-cyan-600/10 rounded-full blur-[140px] pointer-events-none" />

        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
          <div className="max-w-3xl mx-auto text-center">
            {/* Small Eyebrow */}
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-cyan-500/30 bg-cyan-950/20 text-cyan-300 text-xs font-mono tracking-widest uppercase mb-6">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
              AGENTIC BUSINESS INTELLIGENCE
            </div>

            {/* Main Headline */}
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight text-white leading-[1.12] mb-6">
              Where Business Data <br />
              <span className="bg-gradient-to-r from-cyan-400 via-sky-300 to-indigo-300 bg-clip-text text-transparent">
                Becomes Intelligence.
              </span>
            </h1>

            {/* Supporting Copy */}
            <p className="text-base sm:text-lg text-slate-300 font-normal leading-relaxed max-w-2xl mx-auto mb-8">
              NEXUS connects your business data, understands its context, investigates what changed,
              and delivers evidence-backed intelligence for better decisions.
            </p>

            {/* CTAs */}
            <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-14">
              <button
                onClick={() => onNavigate(isAuthenticated ? '/' : '/signup')}
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2.5 px-6 py-3.5 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-sm transition-all duration-200 shadow-[0_0_28px_rgba(0,242,254,0.35)] focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
              >
                Get Started
                <ArrowRight className="w-4 h-4" />
              </button>
              <button
                onClick={() => scrollToSection('how-it-works')}
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl bg-surface-card/80 hover:bg-surface-elevated border border-surface-elevated hover:border-slate-600 text-slate-300 hover:text-white font-medium text-sm transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
              >
                See How It Works
              </button>
            </div>
          </div>

          {/* Central NXST3 Artwork Visual Anchor */}
          <div className="max-w-4xl mx-auto relative mt-2 group">
            <div className="relative rounded-2xl overflow-hidden border border-cyan-500/25 bg-slate-950/60 shadow-[0_20px_60px_-15px_rgba(0,242,254,0.15)]">
              <img
                src="/brand/nexus-hero-nxst3.png"
                alt="NEXUS Agentic Intelligence Convergence Visual"
                className="w-full h-auto object-cover max-h-[460px] sm:max-h-[520px] filter brightness-95 contrast-105"
                loading="eager"
              />
              {/* Subtle Linear Vignette Overlay */}
              <div className="absolute inset-0 bg-gradient-to-t from-void via-transparent to-transparent opacity-80" />

              {/* Bottom Subtle Convergence Label */}
              <div className="absolute bottom-4 left-6 right-6 flex items-center justify-between text-xs font-mono text-slate-400">
                <span className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-cyan-400" />
                  NEXUS REASONING CORE
                </span>
                <span className="text-slate-500 hidden sm:inline">
                  Signals converge into verified business truth
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          3. HOW IT WORKS — ONE COMPACT TRANSFORMATION SECTION
      ───────────────────────────────────────────────────────────── */}
      <section id="how-it-works" className="py-20 border-t border-surface-elevated/70 bg-void/50 relative">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <div className="text-xs font-mono tracking-widest text-cyan-400 uppercase mb-2">
              PIPELINE ARCHITECTURE
            </div>
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white mb-4">
              From Business Data to Decision-Ready Intelligence.
            </h2>
            <p className="text-slate-400 text-sm sm:text-base leading-relaxed">
              NEXUS combines business context, deterministic analytics, AI reasoning and evidence
              to help you understand what is happening — and why.
            </p>
          </div>

          {/* 3-Stage Transformation Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 relative">
            {/* Stage 1: Data Ingestion */}
            <div className="p-6 rounded-2xl bg-surface-card/60 border border-surface-elevated hover:border-surface-border transition-all flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <span className="text-xs font-mono text-slate-400">01 / INPUT</span>
                  <Database className="w-4 h-4 text-cyan-400" />
                </div>
                <h3 className="text-lg font-bold text-white mb-2">Your Business Data</h3>
                <p className="text-xs text-slate-400 leading-relaxed mb-6">
                  Structured records representing commercial activity:
                </p>
                <div className="grid grid-cols-2 gap-2 text-xs font-mono text-slate-300 mb-6">
                  <div className="p-2 rounded bg-surface-base/80 border border-surface-elevated/60">Sales & Orders</div>
                  <div className="p-2 rounded bg-surface-base/80 border border-surface-elevated/60">Customer Cohorts</div>
                  <div className="p-2 rounded bg-surface-base/80 border border-surface-elevated/60">SKU Catalog</div>
                  <div className="p-2 rounded bg-surface-base/80 border border-surface-elevated/60">Inventory Levels</div>
                  <div className="p-2 rounded bg-surface-base/80 border border-surface-elevated/60 col-span-2">Operating Expenses</div>
                </div>
              </div>

              {/* Supported Connectors & Transparent Status */}
              <div className="pt-4 border-t border-surface-elevated/60">
                <div className="text-[11px] font-mono text-slate-400 mb-2">DATA CONNECTORS:</div>
                <div className="flex flex-wrap gap-1.5 text-[10px] font-mono">
                  <span className="px-2 py-0.5 rounded bg-emerald-950/40 text-emerald-300 border border-emerald-500/30">CSV (Live)</span>
                  <span className="px-2 py-0.5 rounded bg-emerald-950/40 text-emerald-300 border border-emerald-500/30">XLSX (Live)</span>
                  <span className="px-2 py-0.5 rounded bg-surface-base text-slate-400 border border-surface-elevated">SQL / API (Coming Soon)</span>
                  <span className="px-2 py-0.5 rounded bg-surface-base text-slate-400 border border-surface-elevated">Tally / ERP (Coming Soon)</span>
                </div>
              </div>
            </div>

            {/* Stage 2: NEXUS Reasoning Engine */}
            <div className="p-6 rounded-2xl bg-gradient-to-b from-cyan-950/30 to-surface-card/70 border border-cyan-500/30 shadow-[0_0_30px_rgba(0,242,254,0.06)] flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <span className="text-xs font-mono text-cyan-400">02 / NEXUS ENGINE</span>
                  <Cpu className="w-4 h-4 text-cyan-400" />
                </div>
                <h3 className="text-lg font-bold text-white mb-2">Deterministic Analysis</h3>
                <p className="text-xs text-slate-300 leading-relaxed mb-6">
                  Raw tabular rows are profiled, validated, and computed into verified metrics:
                </p>
                <div className="space-y-2.5 text-xs">
                  <div className="flex items-center gap-2.5 text-slate-200">
                    <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0" />
                    <span><strong className="text-white">Understand:</strong> Infers schema, date grain, and entity relationships</span>
                  </div>
                  <div className="flex items-center gap-2.5 text-slate-200">
                    <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0" />
                    <span><strong className="text-white">Investigate:</strong> Detects anomalies and decomposes metric variance</span>
                  </div>
                  <div className="flex items-center gap-2.5 text-slate-200">
                    <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0" />
                    <span><strong className="text-white">Validate:</strong> Reconciles calculations deterministically in SQL</span>
                  </div>
                  <div className="flex items-center gap-2.5 text-slate-200">
                    <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0" />
                    <span><strong className="text-white">Predict:</strong> Projects trend trajectories with confidence intervals</span>
                  </div>
                </div>
              </div>

              <div className="pt-4 border-t border-cyan-500/20 mt-6">
                <div className="text-[11px] font-mono text-cyan-300 flex items-center justify-between">
                  <span>GOVERNED KNOWLEDGE FABRIC</span>
                  <span className="text-emerald-400">ISOLATED</span>
                </div>
              </div>
            </div>

            {/* Stage 3: Decision Intelligence */}
            <div className="p-6 rounded-2xl bg-surface-card/60 border border-surface-elevated hover:border-surface-border transition-all flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <span className="text-xs font-mono text-slate-400">03 / OUTPUT</span>
                  <TrendingUp className="w-4 h-4 text-cyan-400" />
                </div>
                <h3 className="text-lg font-bold text-white mb-2">Business Intelligence</h3>
                <p className="text-xs text-slate-400 leading-relaxed mb-6">
                  Clear explanations and decision support backed by mathematical proof:
                </p>
                <div className="space-y-3 text-xs text-slate-300">
                  <div className="p-3 rounded-lg bg-surface-base/70 border border-surface-elevated">
                    <div className="font-semibold text-slate-200 mb-0.5">Root Cause Diagnosis</div>
                    <div className="text-slate-400 text-[11px]">Pinpoint the exact SKUs and regions driving margin shifts.</div>
                  </div>
                  <div className="p-3 rounded-lg bg-surface-base/70 border border-surface-elevated">
                    <div className="font-semibold text-slate-200 mb-0.5">Evidence-Backed Forecasts</div>
                    <div className="text-slate-400 text-[11px]">Forward-looking trajectories generated when data supports them.</div>
                  </div>
                  <div className="p-3 rounded-lg bg-surface-base/70 border border-surface-elevated">
                    <div className="font-semibold text-slate-200 mb-0.5">Decision Guidance</div>
                    <div className="text-slate-400 text-[11px]">Actionable recommendations grounded in your actual ledger.</div>
                  </div>
                </div>
              </div>

              <div className="pt-4 border-t border-surface-elevated/60 mt-4">
                <div className="text-[11px] font-mono text-slate-400">DECISION SUPPORT ONLY — HUMAN REMAINS IN CONTROL</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          4. CORE CAPABILITIES — 2x3 PROFESSIONAL GRID (EXACTLY 6)
      ───────────────────────────────────────────────────────────── */}
      <section id="capabilities" className="py-20 border-t border-surface-elevated/70">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <div className="text-xs font-mono tracking-widest text-cyan-400 uppercase mb-2">
              BUILT FOR BUSINESS OPERATORS
            </div>
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white mb-4">
              Core Capabilities
            </h2>
            <p className="text-slate-400 text-sm sm:text-base leading-relaxed">
              Six essential operational tools engineered to replace guesswork with verified business intelligence.
            </p>
          </div>

          {/* Exactly 6 Capabilities in a Clean 2x3 Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {/* Capability 1: Ask NEXUS */}
            <div className="p-6 rounded-2xl bg-surface-card border border-surface-elevated hover:border-cyan-500/40 transition-colors">
              <div className="w-10 h-10 rounded-xl bg-cyan-950/50 border border-cyan-500/30 flex items-center justify-center text-cyan-400 mb-4">
                <HelpCircle className="w-5 h-5" />
              </div>
              <h3 className="text-base font-bold text-white mb-2">1. Ask NEXUS</h3>
              <p className="text-xs text-slate-300 leading-relaxed">
                Query your commercial performance in natural language. Ask about revenue, customer retention,
                or margins and receive clear, conversational responses.
              </p>
            </div>

            {/* Capability 2: Investigate */}
            <div className="p-6 rounded-2xl bg-surface-card border border-surface-elevated hover:border-cyan-500/40 transition-colors">
              <div className="w-10 h-10 rounded-xl bg-cyan-950/50 border border-cyan-500/30 flex items-center justify-center text-cyan-400 mb-4">
                <SearchCode className="w-5 h-5" />
              </div>
              <h3 className="text-base font-bold text-white mb-2">2. Investigate</h3>
              <p className="text-xs text-slate-300 leading-relaxed">
                Understand why metrics changed. NEXUS automatically performs driver decomposition,
                identifying whether volume, pricing, or product mix caused metric shifts.
              </p>
            </div>

            {/* Capability 3: Predict */}
            <div className="p-6 rounded-2xl bg-surface-card border border-surface-elevated hover:border-cyan-500/40 transition-colors">
              <div className="w-10 h-10 rounded-xl bg-cyan-950/50 border border-cyan-500/30 flex items-center justify-center text-cyan-400 mb-4">
                <TrendingUp className="w-5 h-5" />
              </div>
              <h3 className="text-base font-bold text-white mb-2">3. Predict</h3>
              <p className="text-xs text-slate-300 leading-relaxed">
                Forecast revenue and inventory trajectories when historical depth allows.
                Predictions include confidence bounds and explicit data-readiness warnings.
              </p>
            </div>

            {/* Capability 4: Business Context */}
            <div className="p-6 rounded-2xl bg-surface-card border border-surface-elevated hover:border-cyan-500/40 transition-colors">
              <div className="w-10 h-10 rounded-xl bg-cyan-950/50 border border-cyan-500/30 flex items-center justify-center text-cyan-400 mb-4">
                <Compass className="w-5 h-5" />
              </div>
              <h3 className="text-base font-bold text-white mb-2">4. Business Context</h3>
              <p className="text-xs text-slate-300 leading-relaxed">
                Teach NEXUS your operational reality. Define your specific fiscal quarters, gross margin formulas,
                regional boundaries, and custom product category hierarchies.
              </p>
            </div>

            {/* Capability 5: Evidence */}
            <div className="p-6 rounded-2xl bg-surface-card border border-surface-elevated hover:border-cyan-500/40 transition-colors">
              <div className="w-10 h-10 rounded-xl bg-cyan-950/50 border border-cyan-500/30 flex items-center justify-center text-cyan-400 mb-4">
                <ShieldCheck className="w-5 h-5" />
              </div>
              <h3 className="text-base font-bold text-white mb-2">5. Evidence</h3>
              <p className="text-xs text-slate-300 leading-relaxed">
                Trace important answers back to supporting rows and calculations. Every insight includes
                an audit trail showing the exact records and SQL equations utilized.
              </p>
            </div>

            {/* Capability 6: Decide */}
            <div className="p-6 rounded-2xl bg-surface-card border border-surface-elevated hover:border-cyan-500/40 transition-colors">
              <div className="w-10 h-10 rounded-xl bg-cyan-950/50 border border-cyan-500/30 flex items-center justify-center text-cyan-400 mb-4">
                <UserCheck className="w-5 h-5" />
              </div>
              <h3 className="text-base font-bold text-white mb-2">6. Decide</h3>
              <p className="text-xs text-slate-300 leading-relaxed">
                Use grounded intelligence to support human decisions. NEXUS synthesizes trade-offs,
                scenarios, and risks so operators can act with certainty.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          5. TRUST / EVIDENCE SECTION — "AI THAT SHOWS ITS WORK"
      ───────────────────────────────────────────────────────────── */}
      <section id="trust" className="py-20 border-t border-surface-elevated/70 bg-void/60">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 items-center">
            {/* Left: Defensible Positioning & Flow */}
            <div className="lg:col-span-6 space-y-6">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-emerald-500/30 bg-emerald-950/20 text-emerald-300 text-xs font-mono">
                <ShieldCheck className="w-3.5 h-3.5" />
                DETERMINISTIC VERIFICATION
              </div>

              <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white leading-tight">
                AI That Shows Its Work.
              </h2>

              <p className="text-sm sm:text-base text-slate-300 leading-relaxed">
                NEXUS does not guess. Important answers are produced via deterministic calculations
                grounded in your actual records, accompanied by traceable equations.
              </p>

              {/* Step Pipeline */}
              <div className="space-y-4 pt-2">
                <div className="flex items-start gap-4">
                  <div className="w-7 h-7 rounded-full bg-surface-elevated flex items-center justify-center font-mono text-xs text-cyan-400 flex-shrink-0 mt-0.5">
                    1
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-white">Question</div>
                    <div className="text-xs text-slate-400">“Why did gross margin drop 4.2% in Q3?”</div>
                  </div>
                </div>

                <div className="flex items-start gap-4">
                  <div className="w-7 h-7 rounded-full bg-surface-elevated flex items-center justify-center font-mono text-xs text-cyan-400 flex-shrink-0 mt-0.5">
                    2
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-white">Investigation</div>
                    <div className="text-xs text-slate-400">Decomposes price vs. volume vs. raw cost changes across product mix.</div>
                  </div>
                </div>

                <div className="flex items-start gap-4">
                  <div className="w-7 h-7 rounded-full bg-surface-elevated flex items-center justify-center font-mono text-xs text-cyan-400 flex-shrink-0 mt-0.5">
                    3
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-white">Evidence</div>
                    <div className="text-xs text-slate-400">Isolates 1,420 sales lines, unit costs, and freight surcharges in August.</div>
                  </div>
                </div>

                <div className="flex items-start gap-4">
                  <div className="w-7 h-7 rounded-full bg-cyan-950 border border-cyan-500/40 flex items-center justify-center font-mono text-xs text-cyan-300 flex-shrink-0 mt-0.5">
                    4
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-white">Explanation</div>
                    <div className="text-xs text-slate-300">
                      78% of the contraction was concentrated in Category B due to an unhedged supplier price increase.
                    </div>
                  </div>
                </div>
              </div>

              {/* Defensible Disclaimer */}
              <div className="pt-2 text-xs font-mono text-slate-500">
                Evidence-grounded intelligence with traceable calculations. No ungrounded statistical assumptions.
              </div>
            </div>

            {/* Right: Traceable Evidence Visual Snippet */}
            <div className="lg:col-span-6">
              <div className="rounded-2xl border border-surface-elevated bg-surface-card p-6 shadow-2xl space-y-4">
                <div className="flex items-center justify-between border-b border-surface-elevated pb-3">
                  <div className="flex items-center gap-2">
                    <span className="w-2.5 h-2.5 rounded-full bg-emerald-400" />
                    <span className="text-xs font-mono text-slate-300">VERIFIED CALCULATION AUDIT</span>
                  </div>
                  <span className="text-[11px] font-mono text-emerald-400 bg-emerald-950/40 px-2 py-0.5 rounded border border-emerald-500/30">
                    MATCH: 100% RECONCILED
                  </span>
                </div>

                {/* Simulated SQL / Calculation Trace */}
                <div className="p-4 rounded-xl bg-void font-mono text-xs text-slate-300 border border-surface-elevated overflow-x-auto space-y-1">
                  <div className="text-slate-500">// Deterministic query executed over tenant ledger</div>
                  <div className="text-cyan-300">SELECT</div>
                  <div className="pl-4">p.category,</div>
                  <div className="pl-4">SUM(s.total_amount) AS revenue,</div>
                  <div className="pl-4">SUM(s.total_amount - (si.unit_cost * si.quantity)) AS gross_profit,</div>
                  <div className="pl-4">ROUND(SUM(...) / SUM(...) * 100, 2) AS gross_margin_pct</div>
                  <div className="text-cyan-300">FROM sales s</div>
                  <div className="text-cyan-300">JOIN sale_items si ON s.id = si.sale_id</div>
                  <div className="text-cyan-300">WHERE s.transaction_date BETWEEN '2025-07-01' AND '2025-09-30'</div>
                  <div className="text-cyan-300">GROUP BY p.category;</div>
                </div>

                {/* Evidence Metrics Summary */}
                <div className="grid grid-cols-3 gap-3 pt-2 text-center font-mono">
                  <div className="p-3 rounded-lg bg-surface-base border border-surface-elevated">
                    <div className="text-[10px] text-slate-400">ROWS AUDITED</div>
                    <div className="text-sm font-bold text-white mt-0.5">14,892</div>
                  </div>
                  <div className="p-3 rounded-lg bg-surface-base border border-surface-elevated">
                    <div className="text-[10px] text-slate-400">VARIANCE DELTA</div>
                    <div className="text-sm font-bold text-amber-400 mt-0.5">-4.2%</div>
                  </div>
                  <div className="p-3 rounded-lg bg-surface-base border border-surface-elevated">
                    <div className="text-[10px] text-slate-400">TRACE STATUS</div>
                    <div className="text-sm font-bold text-emerald-400 mt-0.5">GROUNDED</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          6. REAL PRODUCT PREVIEW — POLISHED COMPOSITION WITH TABS
      ───────────────────────────────────────────────────────────── */}
      <section id="product-preview" className="py-20 border-t border-surface-elevated/70">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-12">
            <div className="text-xs font-mono tracking-widest text-cyan-400 uppercase mb-2">
              REAL WORKBENCH
            </div>
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white mb-3">
              Explore the NEXUS Platform
            </h2>
            <p className="text-slate-400 text-sm sm:text-base">
              A single operational console uniting conversational intelligence, anomaly investigation,
              and grounded forecasting.
            </p>
            <div className="mt-3 text-xs font-mono text-slate-500">
              * Illustrative product preview demonstrating interface workflows.
            </div>
          </div>

          {/* Product Preview Composition Container */}
          <div className="rounded-2xl border border-surface-elevated bg-surface-card/90 overflow-hidden shadow-2xl">
            {/* Top Toolbar / Tab Bar */}
            <div className="flex flex-wrap items-center justify-between border-b border-surface-elevated px-6 py-3 bg-surface-base/80 gap-3">
              <div className="flex items-center space-x-1.5 overflow-x-auto">
                {(
                  [
                    { id: 'overview', label: 'Executive Overview' },
                    { id: 'ask', label: 'Ask NEXUS' },
                    { id: 'investigate', label: 'Investigation' },
                    { id: 'forecast', label: 'Forecast' },
                    { id: 'evidence', label: 'Evidence Engine' },
                  ] as const
                ).map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveProductTab(tab.id)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-mono transition-all ${
                      activeProductTab === tab.id
                        ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40'
                        : 'text-slate-400 hover:text-white hover:bg-surface-elevated'
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-2 text-xs font-mono text-slate-400">
                <span className="w-2 h-2 rounded-full bg-emerald-400" />
                <span>Tenant: Enterprise Workspace</span>
              </div>
            </div>

            {/* Tab Contents */}
            <div className="p-6 md:p-8 min-h-[380px]">
              {/* TAB 1: OVERVIEW */}
              {activeProductTab === 'overview' && (
                <div className="space-y-6">
                  {/* Metric Cards Row */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    <div className="p-4 rounded-xl bg-surface-base border border-surface-elevated">
                      <div className="text-xs font-mono text-slate-400">TOTAL REVENUE (MTD)</div>
                      <div className="text-2xl font-bold text-white mt-1">$482,900</div>
                      <div className="text-xs text-emerald-400 mt-1 flex items-center gap-1 font-mono">
                        <span>↑ +12.4%</span> vs prior month
                      </div>
                    </div>
                    <div className="p-4 rounded-xl bg-surface-base border border-surface-elevated">
                      <div className="text-xs font-mono text-slate-400">GROSS MARGIN</div>
                      <div className="text-2xl font-bold text-white mt-1">36.8%</div>
                      <div className="text-xs text-amber-400 mt-1 flex items-center gap-1 font-mono">
                        <span>↓ -1.8%</span> target: 38%
                      </div>
                    </div>
                    <div className="p-4 rounded-xl bg-surface-base border border-surface-elevated">
                      <div className="text-xs font-mono text-slate-400">ORDERS PROCESSED</div>
                      <div className="text-2xl font-bold text-white mt-1">3,491</div>
                      <div className="text-xs text-emerald-400 mt-1 flex items-center gap-1 font-mono">
                        <span>↑ +8.1%</span> vs prior month
                      </div>
                    </div>
                    <div className="p-4 rounded-xl bg-surface-base border border-surface-elevated">
                      <div className="text-xs font-mono text-slate-400">DATA READINESS</div>
                      <div className="text-2xl font-bold text-cyan-400 mt-1">94 / 100</div>
                      <div className="text-xs text-slate-400 mt-1 flex items-center gap-1 font-mono">
                        <span>6 dimensions passed</span>
                      </div>
                    </div>
                  </div>

                  {/* Summary Callout */}
                  <div className="p-5 rounded-xl bg-surface-base/60 border border-surface-elevated flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
                    <div>
                      <div className="text-xs font-mono text-cyan-400 uppercase">SYNTHESIZED INTELLIGENCE</div>
                      <div className="text-sm font-semibold text-white mt-0.5">
                        Strong sales momentum offset by supplier component increases in Audio category.
                      </div>
                      <div className="text-xs text-slate-400 mt-1">
                        Traceable across 3,491 order records and 18 active vendor invoices.
                      </div>
                    </div>
                    <button
                      onClick={() => setActiveProductTab('investigate')}
                      className="px-4 py-2 rounded-lg bg-surface-elevated hover:bg-slate-700 text-xs font-mono text-cyan-300 transition-colors flex-shrink-0"
                    >
                      Investigate Driver
                    </button>
                  </div>
                </div>
              )}

              {/* TAB 2: ASK NEXUS */}
              {activeProductTab === 'ask' && (
                <div className="space-y-4 max-w-3xl mx-auto">
                  <div className="p-4 rounded-xl bg-surface-elevated/50 border border-surface-elevated text-sm text-slate-200">
                    <span className="font-mono text-xs text-cyan-400 block mb-1">USER QUERY</span>
                    “Which product categories delivered the highest gross margin last month?”
                  </div>

                  <div className="p-5 rounded-xl bg-surface-base border border-cyan-500/30 text-sm text-slate-200 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs text-cyan-400">NEXUS RESPONSE</span>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-500/30">
                        EVIDENCE VERIFIED
                      </span>
                    </div>
                    <p className="text-xs leading-relaxed text-slate-300">
                      In the prior calendar month, <strong>Enterprise Storage</strong> recorded the highest gross margin at <strong>48.2%</strong> ($92,400 revenue),
                      followed by <strong>Security Hardware</strong> at <strong>41.6%</strong> ($68,100 revenue).
                      Consumer Accessories underperformed at <strong>24.1%</strong> due to freight surcharges.
                    </p>
                    <div className="p-3 rounded-lg bg-void border border-surface-elevated font-mono text-[11px] text-slate-400">
                      Calculated from 1,280 line items across 4 store channels. Confidence: 0.98.
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 3: INVESTIGATION */}
              {activeProductTab === 'investigate' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <h4 className="text-sm font-bold text-white">Gross Margin Variance Waterfall</h4>
                      <p className="text-xs text-slate-400">Root cause attribution for -1.8% margin variation</p>
                    </div>
                    <span className="text-xs font-mono text-slate-400">Period: Prior Month vs Baseline</span>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-xs">
                    <div className="p-4 rounded-xl bg-surface-base border border-surface-elevated">
                      <div className="text-slate-400">VOLUME EFFECT</div>
                      <div className="text-lg font-bold text-emerald-400 mt-1">+0.8%</div>
                      <div className="text-[11px] text-slate-500 mt-1">Higher unit sales across high-end lines</div>
                    </div>
                    <div className="p-4 rounded-xl bg-surface-base border border-surface-elevated">
                      <div className="text-slate-400">PRICE REALIZATION</div>
                      <div className="text-lg font-bold text-slate-300 mt-1">+0.1%</div>
                      <div className="text-[11px] text-slate-500 mt-1">Average selling price remained stable</div>
                    </div>
                    <div className="p-4 rounded-xl bg-surface-base border border-surface-elevated">
                      <div className="text-slate-400">COST INFLATION (ROOT CAUSE)</div>
                      <div className="text-lg font-bold text-rose-400 mt-1">-2.7%</div>
                      <div className="text-[11px] text-slate-500 mt-1">Vendor component hike in SKU-801, 804</div>
                    </div>
                  </div>

                  <div className="p-4 rounded-xl bg-surface-base/60 border border-surface-elevated text-xs text-slate-300">
                    <strong className="text-white">Recommendation:</strong> Review pricing or renegotiate supplier lot sizes for Audio components to recover 1.5% margin.
                  </div>
                </div>
              )}

              {/* TAB 4: FORECAST */}
              {activeProductTab === 'forecast' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <h4 className="text-sm font-bold text-white">Forward 90-Day Revenue Projection</h4>
                      <p className="text-xs text-slate-400">Deterministic regression with confidence intervals</p>
                    </div>
                    <span className="text-xs font-mono text-cyan-400 bg-cyan-950/40 px-2.5 py-1 rounded border border-cyan-500/30">
                      TRAINING DEPTH: 18 MONTHS
                    </span>
                  </div>

                  <div className="p-6 rounded-xl bg-surface-base border border-surface-elevated space-y-4">
                    <div className="flex items-center justify-between text-xs font-mono">
                      <span className="text-slate-400">PROJECTED RUN-RATE</span>
                      <span className="text-white font-bold">$510,000 — $545,000 / mo</span>
                    </div>
                    <div className="w-full bg-void rounded-full h-3 overflow-hidden flex border border-surface-elevated">
                      <div className="bg-slate-700 h-full w-[55%]" title="Historical Baseline" />
                      <div className="bg-cyan-500 h-full w-[30%]" title="Projected Median" />
                      <div className="bg-cyan-500/30 h-full w-[15%]" title="Upper Bound" />
                    </div>
                    <div className="flex items-center justify-between text-[11px] font-mono text-slate-500">
                      <span>Baseline: $482k</span>
                      <span>Median: $528k</span>
                      <span>Optimistic: $545k</span>
                    </div>
                  </div>

                  <div className="text-xs font-mono text-slate-400">
                    * Forecasts are updated upon new batch ingestion. Confidence band widens after 60 days.
                  </div>
                </div>
              )}

              {/* TAB 5: EVIDENCE */}
              {activeProductTab === 'evidence' && (
                <div className="space-y-4 font-mono text-xs">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-bold text-white font-sans">Evidence Audit Trail</h4>
                    <span className="text-emerald-400">HASH: SHA-256 VERIFIED</span>
                  </div>

                  <div className="p-4 rounded-xl bg-void border border-surface-elevated space-y-2 text-slate-300">
                    <div className="text-slate-500">// Source dataset record reference</div>
                    <div>Source File: sales_transactions_2025_q3.csv (3.4 MB)</div>
                    <div>Fingerprint: 8f4b1e...0d4a92c1</div>
                    <div>Ingested At: 2025-10-01T04:12:00Z</div>
                    <div>Tenant Scope: business_id=biz_0192e (Isolated)</div>
                  </div>

                  <div className="p-4 rounded-xl bg-surface-base border border-surface-elevated text-slate-300 leading-relaxed">
                    Every figure presented in the NEXUS dashboard links to exact tabular rows in your workspace database.
                    Calculations are transparent, audited, and exportable.
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          7. FINAL CTA & RESTRAINED FOOTER
      ───────────────────────────────────────────────────────────── */}
      <section className="py-20 border-t border-surface-elevated/70 bg-surface-card/30 relative">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center space-y-6">
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white">
            Turn your business data into intelligence.
          </h2>
          <p className="text-base text-slate-300 max-w-xl mx-auto">
            Connect your data and see what NEXUS can uncover. Deterministic, evidence-grounded decision support.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 pt-2">
            <button
              onClick={() => onNavigate(isAuthenticated ? '/' : '/signup')}
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-8 py-3.5 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-sm transition-all duration-200 shadow-[0_0_25px_rgba(0,242,254,0.35)] focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
            >
              Get Started
              <ArrowRight className="w-4 h-4" />
            </button>
            <button
              onClick={() => onNavigate('/login')}
              className="w-full sm:w-auto px-6 py-3.5 rounded-xl border border-surface-elevated hover:border-slate-500 text-slate-300 hover:text-white text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
            >
              Sign In
            </button>
          </div>
        </div>
      </section>

      {/* Restrained Footer */}
      <footer className="border-t border-surface-elevated py-12 bg-void text-xs font-mono text-slate-500">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-3">
            <NexusLogo imageSize={24} showTagline={false} />
            <span className="text-slate-400">| Traceable Business Intelligence</span>
          </div>

          <div className="flex items-center space-x-6 text-slate-400">
            <button
              onClick={() => scrollToSection('how-it-works')}
              className="hover:text-cyan-400 transition-colors"
            >
              Pipeline
            </button>
            <button
              onClick={() => scrollToSection('capabilities')}
              className="hover:text-cyan-400 transition-colors"
            >
              Capabilities
            </button>
            <button
              onClick={() => scrollToSection('trust')}
              className="hover:text-cyan-400 transition-colors"
            >
              Evidence
            </button>
            <button
              onClick={() => scrollToSection('product-preview')}
              className="hover:text-cyan-400 transition-colors"
            >
              Preview
            </button>
          </div>

          <div>
            © {new Date().getFullYear()} NEXUS Platform. All rights reserved.
          </div>
        </div>
      </footer>
    </div>
  );
};
