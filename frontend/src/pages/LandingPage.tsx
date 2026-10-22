import React, { useState } from 'react';
import {
  ArrowRight,
  ArrowUpRight,
  ArrowDownRight,
  Database,
  SearchCode,
  ShieldCheck,
  TrendingUp,
  Cpu,
  CheckCircle2,
  ChevronRight,
  UserCheck,
  Menu,
  X,
  HelpCircle,
  Layers,
  Users,
  BarChart3,
  Calculator,
  ArrowDown,
  Sparkles,
  FileText,
} from 'lucide-react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceDot,
} from 'recharts';
import { NexusLogo } from '../components/brand/NexusLogo';
import { NexusSymbol } from '../components/brand/NexusSymbol';

interface RevenueDataPoint {
  period: string;
  revenue: number; // in thousands ($k)
  margin: number;  // in percent (%)
}

interface HeroDataset {
  label: string;
  periodLabel: string;
  kpis: {
    revenue: string;
    revenueDelta: number;
    revenuePeriod: string;
    margin: string;
    marginDelta: number;
    marginTarget: string;
    orders: string;
    ordersDelta: number;
    ordersFulfillment: string;
  };
  anomaly: {
    period: string;
    revenue: number;
    badge: string;
    finding: string;
    auditCount: string;
    lineage: string;
  };
  points: RevenueDataPoint[];
}

const HERO_DATASETS: Record<'30d' | '90d' | '12m', HeroDataset> = {
  '30d': {
    label: '30 Days',
    periodLabel: '30-Day Daily Interval',
    kpis: {
      revenue: '$1,248,500',
      revenueDelta: 12.4,
      revenuePeriod: 'vs prior 30d',
      margin: '38.2%',
      marginDelta: -2.6,
      marginTarget: 'Target: 40.0%',
      orders: '18,420',
      ordersDelta: 6.8,
      ordersFulfillment: '98.4% fulfilled',
    },
    anomaly: {
      period: 'Day 22',
      revenue: 35.2,
      badge: 'Day 22 Variance Flagged',
      finding: 'Freight surcharge adjustment on SKU category 40 shifted gross margin by -2.6% on Day 22, offset by repeat order volume.',
      auditCount: 'Sample Scope: 4,820 rows',
      lineage: 'orders.csv ➔ shipping_costs.csv',
    },
    points: [
      { period: 'Day 02', revenue: 34.2, margin: 40.1 },
      { period: 'Day 06', revenue: 36.8, margin: 40.4 },
      { period: 'Day 10', revenue: 38.5, margin: 39.8 },
      { period: 'Day 14', revenue: 41.2, margin: 40.2 },
      { period: 'Day 18', revenue: 43.6, margin: 39.5 },
      { period: 'Day 22', revenue: 35.2, margin: 35.6 },
      { period: 'Day 26', revenue: 44.8, margin: 39.1 },
      { period: 'Day 30', revenue: 47.4, margin: 39.7 },
    ],
  },
  '90d': {
    label: '90 Days',
    periodLabel: '90-Day Weekly Interval',
    kpis: {
      revenue: '$3,820,000',
      revenueDelta: 14.1,
      revenuePeriod: 'vs prior 90d',
      margin: '39.4%',
      marginDelta: -1.2,
      marginTarget: 'Target: 40.0%',
      orders: '56,190',
      ordersDelta: 9.2,
      ordersFulfillment: '98.9% fulfilled',
    },
    anomaly: {
      period: 'Wk 08',
      revenue: 278,
      badge: 'Week 8 Margin Compression',
      finding: 'Promotional discount on Home Essentials lifted sales volume +22% but compressed category gross margin by -3.1%.',
      auditCount: 'Sample Scope: 14,290 rows',
      lineage: 'promotions.csv ➔ sales_items.csv',
    },
    points: [
      { period: 'Wk 02', revenue: 290, margin: 40.2 },
      { period: 'Wk 04', revenue: 305, margin: 40.0 },
      { period: 'Wk 06', revenue: 320, margin: 39.8 },
      { period: 'Wk 08', revenue: 278, margin: 36.7 },
      { period: 'Wk 10', revenue: 340, margin: 39.4 },
      { period: 'Wk 12', revenue: 365, margin: 40.1 },
    ],
  },
  '12m': {
    label: '12 Months',
    periodLabel: '12-Month Monthly Interval',
    kpis: {
      revenue: '$15,420,000',
      revenueDelta: 18.6,
      revenuePeriod: 'YoY Growth',
      margin: '40.6%',
      marginDelta: 1.1,
      marginTarget: 'Target: 40.0%',
      orders: '228,400',
      ordersDelta: 12.3,
      ordersFulfillment: '99.1% fulfilled',
    },
    anomaly: {
      period: 'Aug',
      revenue: 1390,
      badge: 'August Rebate Reconciliation',
      finding: 'Annual supplier volume rebate reconciliations in August recovered +1.8% gross margin across Electronics category.',
      auditCount: 'Sample Scope: 58,900 rows',
      lineage: 'vendor_rebates.csv ➔ inventory.csv',
    },
    points: [
      { period: 'Nov', revenue: 1120, margin: 39.5 },
      { period: 'Jan', revenue: 1180, margin: 39.8 },
      { period: 'Mar', revenue: 1240, margin: 40.1 },
      { period: 'May', revenue: 1290, margin: 40.0 },
      { period: 'Jul', revenue: 1340, margin: 39.7 },
      { period: 'Aug', revenue: 1390, margin: 42.4 },
      { period: 'Oct', revenue: 1460, margin: 40.6 },
    ],
  },
};

const PIPELINE_ENGINE_STAGES = [
  {
    name: 'Validation',
    icon: CheckCircle2,
    rule: 'Schema typing, temporal grain & foreign key integrity',
  },
  {
    name: 'Calculations',
    icon: Calculator,
    rule: 'Deterministic metric math: Revenue, Margin & Order volumes',
  },
  {
    name: 'Drivers',
    icon: SearchCode,
    rule: 'Price-Volume-Mix decomposition & variance attribution',
  },
  {
    name: 'Forecasts',
    icon: TrendingUp,
    rule: 'Historical trend models with uncertainty corridors (sample data)',
  },
];

interface LandingPageProps {
  onNavigate: (route: string) => void;
  isAuthenticated?: boolean;
}

export const LandingPage: React.FC<LandingPageProps> = ({
  onNavigate,
  isAuthenticated = false,
}) => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [heroTimeRange, setHeroTimeRange] = useState<'30d' | '90d' | '12m'>('30d');
  const [pipelineEngineStage, setPipelineEngineStage] = useState<number>(1);
  const [activeTrustStep, setActiveTrustStep] = useState<number>(2);
  const [trustInspectionView, setTrustInspectionView] = useState<'business' | 'formula'>('business');
  const [activeProductTab, setActiveProductTab] = useState<
    'overview' | 'ask' | 'investigate' | 'forecast' | 'evidence'
  >('overview');

  const currentDataset = HERO_DATASETS[heroTimeRange];

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
          1. NAVIGATION — ARCHITECTURAL, MINIMAL, REFINED
      ───────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-50 backdrop-blur-xl bg-void/90 border-b border-surface-elevated/80 transition-all">
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
              PIPELINE
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
              VERIFICATION
            </button>
            <button
              onClick={() => scrollToSection('product-preview')}
              className="hover:text-cyan-400 transition-colors focus:outline-none focus-visible:text-cyan-400"
            >
              WORKBENCH
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
              PIPELINE ARCHITECTURE
            </button>
            <button
              onClick={() => scrollToSection('capabilities')}
              className="block w-full text-left text-sm font-mono text-slate-300 hover:text-cyan-400 py-1"
            >
              CORE CAPABILITIES
            </button>
            <button
              onClick={() => scrollToSection('trust')}
              className="block w-full text-left text-sm font-mono text-slate-300 hover:text-cyan-400 py-1"
            >
              VERIFICATION
            </button>
            <button
              onClick={() => scrollToSection('product-preview')}
              className="block w-full text-left text-sm font-mono text-slate-300 hover:text-cyan-400 py-1"
            >
              PLATFORM WORKBENCH
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
          2. HERO — DATA-LED EXECUTIVE ANALYTICS DASHBOARD
      ───────────────────────────────────────────────────────────── */}
      <section className="relative min-h-[calc(100svh-4rem)] flex flex-col justify-center py-6 sm:py-8 lg:py-6 xl:py-8 overflow-hidden">
        {/* Soft Ambient Background Glow */}
        <div 
          className="absolute top-1/2 right-1/4 -translate-y-1/2 w-[520px] h-[360px] bg-cyan-500/10 rounded-full blur-[130px] pointer-events-none" 
          aria-hidden="true"
        />
        <div 
          className="absolute -top-12 left-10 w-[300px] h-[250px] bg-slate-800/20 rounded-full blur-[100px] pointer-events-none" 
          aria-hidden="true"
        />

        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10 w-full">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-8 xl:gap-12 items-center">
            
            {/* Left Column: Product Positioning & Value Prop */}
            <div className="lg:col-span-6 flex flex-col items-start text-left">
              {/* Editorial Category Eyebrow */}
              <div className="flex items-center gap-2.5 mb-3 text-[11px] sm:text-xs font-mono tracking-widest text-cyan-400/90 font-medium select-none">
                <span className="w-4 h-px bg-cyan-400/60" aria-hidden="true" />
                <span>BUSINESS INTELLIGENCE, WITH EVIDENCE</span>
              </div>

              {/* Primary Headline */}
              <h1 className="text-3xl sm:text-4xl md:text-5xl lg:text-[2.65rem] xl:text-[3.15rem] font-extrabold tracking-tight text-white leading-[1.12] mb-3.5">
                From business questions <br className="hidden sm:inline" />
                <span className="bg-gradient-to-r from-cyan-300 via-sky-200 to-indigo-200 bg-clip-text text-transparent">
                  to answers you can verify.
                </span>
              </h1>

              {/* Supporting Copy */}
              <p className="text-sm sm:text-base text-slate-300 font-normal leading-relaxed max-w-xl mb-6">
                NEXUS turns operational business data into actionable analysis, calculated variance drivers, and traceable evidence you can inspect down to the underlying ledger row.
              </p>

              {/* CTAs */}
              <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 w-full sm:w-auto mb-6">
                <button
                  onClick={() => onNavigate(isAuthenticated ? '/' : '/signup')}
                  className="inline-flex items-center justify-center gap-2 px-5 py-2.5 sm:py-3 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-xs sm:text-sm transition-all duration-200 shadow-[0_0_20px_rgba(6,182,212,0.25)] focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 active:scale-[0.98]"
                >
                  Get Started
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => scrollToSection('how-it-works')}
                  className="inline-flex items-center justify-center gap-2 px-5 py-2.5 sm:py-3 rounded-lg bg-surface-card/90 hover:bg-surface-elevated border border-surface-elevated hover:border-slate-600 text-slate-300 hover:text-white font-medium text-xs sm:text-sm transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 active:scale-[0.98]"
                >
                  See How It Works
                </button>
              </div>

              {/* Refined Horizontal Trust Strip */}
              <div className="pt-4 border-t border-surface-elevated/70 w-full flex flex-wrap items-center gap-y-2 gap-x-3.5 sm:gap-x-5 text-xs text-slate-400 font-sans">
                <div className="flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400/90 shrink-0" />
                  <span className="text-slate-300 font-medium">Deterministic analytics</span>
                </div>
                <span className="text-slate-700 select-none hidden sm:inline" aria-hidden="true">•</span>
                <div className="flex items-center gap-1.5">
                  <ShieldCheck className="w-3.5 h-3.5 text-cyan-400/90 shrink-0" />
                  <span className="text-slate-300 font-medium">Traceable evidence</span>
                </div>
                <span className="text-slate-700 select-none hidden sm:inline" aria-hidden="true">•</span>
                <div className="flex items-center gap-1.5">
                  <UserCheck className="w-3.5 h-3.5 text-cyan-400/90 shrink-0" />
                  <span className="text-slate-300 font-medium">Human-controlled decisions</span>
                </div>
              </div>
            </div>

            {/* Right Column: Production-Quality Recharts Executive Dashboard */}
            <div className="lg:col-span-6 w-full">
              <div className="relative mx-auto max-w-lg lg:max-w-none">
                {/* Subtle backplate glow */}
                <div 
                  className="absolute -inset-1 rounded-2xl bg-gradient-to-b from-cyan-500/15 via-sky-500/5 to-transparent blur-xl opacity-50 pointer-events-none"
                  aria-hidden="true" 
                />

                {/* Dashboard Frame Window */}
                <div className="relative rounded-xl border border-surface-elevated bg-slate-950/95 shadow-2xl overflow-hidden backdrop-blur-md">
                  {/* Minimal NEXUS Workspace Header */}
                  <div className="px-3.5 py-2.5 border-b border-surface-elevated bg-surface-card/75 flex items-center justify-between gap-3 flex-wrap">
                    <div className="flex items-center gap-2 min-w-0">
                      <NexusSymbol size={16} alt="" />
                      <span className="text-xs font-semibold text-slate-200 tracking-tight select-none">
                        Executive overview
                      </span>
                      <span className="text-slate-600 font-mono text-[11px] hidden sm:inline">•</span>
                      <span className="text-[11px] font-mono text-slate-400 select-none hidden sm:inline">
                        Operational Intelligence
                      </span>
                    </div>

                    {/* Interactive Time-Range Selector and Sample Label */}
                    <div className="flex items-center gap-2">
                      <div className="flex items-center gap-0.5 bg-surface-elevated/80 p-0.5 rounded-md border border-slate-700/60" role="tablist" aria-label="Select analysis time window">
                        {(['30d', '90d', '12m'] as const).map((range) => (
                          <button
                            key={range}
                            onClick={() => setHeroTimeRange(range)}
                            role="tab"
                            aria-selected={heroTimeRange === range}
                            className={`px-2 py-0.5 text-[11px] font-mono rounded transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400 ${
                              heroTimeRange === range
                                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 font-semibold'
                                : 'text-slate-400 hover:text-slate-200'
                            }`}
                          >
                            {range.toUpperCase()}
                          </button>
                        ))}
                      </div>

                      <span className="text-[10px] font-mono text-slate-400 px-1.5 py-0.5 rounded bg-surface-elevated/60 border border-slate-700/50 select-none">
                        Sample Data
                      </span>
                    </div>
                  </div>

                  {/* Dashboard Content */}
                  <div className="p-3.5 sm:p-4 space-y-3">
                    {/* Compact Metrics Row */}
                    <div className="grid grid-cols-3 gap-2 sm:gap-2.5">
                      {/* Metric 1: Net Revenue */}
                      <div className="p-2.5 sm:p-3 rounded-lg bg-surface-card/80 border border-surface-elevated/80 flex flex-col">
                        <span className="text-[11px] font-medium text-slate-400 truncate">
                          Net Revenue
                        </span>
                        <div className="mt-1 flex items-baseline justify-between gap-1 flex-wrap">
                          <span className="text-base sm:text-lg font-bold text-white tracking-tight tabular-nums">
                            {currentDataset.kpis.revenue}
                          </span>
                          <span className="inline-flex items-center text-[10px] sm:text-[11px] font-semibold text-emerald-400 tabular-nums">
                            <ArrowUpRight className="w-3 h-3 mr-0.5 shrink-0" />
                            +{currentDataset.kpis.revenueDelta}%
                          </span>
                        </div>
                        <span className="text-[10px] text-slate-400 font-mono mt-0.5">
                          {currentDataset.kpis.revenuePeriod}
                        </span>
                      </div>

                      {/* Metric 2: Gross Margin */}
                      <div className="p-2.5 sm:p-3 rounded-lg bg-surface-card/80 border border-surface-elevated/80 flex flex-col">
                        <span className="text-[11px] font-medium text-slate-400 truncate">
                          Gross Margin
                        </span>
                        <div className="mt-1 flex items-baseline justify-between gap-1 flex-wrap">
                          <span className="text-base sm:text-lg font-bold text-white tracking-tight tabular-nums">
                            {currentDataset.kpis.margin}
                          </span>
                          <span 
                            className={`inline-flex items-center text-[10px] sm:text-[11px] font-semibold tabular-nums ${
                              currentDataset.kpis.marginDelta < 0 ? 'text-rose-400' : 'text-emerald-400'
                            }`}
                          >
                            {currentDataset.kpis.marginDelta < 0 ? (
                              <ArrowDownRight className="w-3 h-3 mr-0.5 shrink-0" />
                            ) : (
                              <ArrowUpRight className="w-3 h-3 mr-0.5 shrink-0" />
                            )}
                            {currentDataset.kpis.marginDelta > 0 ? '+' : ''}{currentDataset.kpis.marginDelta}%
                          </span>
                        </div>
                        <span className="text-[10px] text-slate-400 font-mono mt-0.5">
                          {currentDataset.kpis.marginTarget}
                        </span>
                      </div>

                      {/* Metric 3: Total Orders */}
                      <div className="p-2.5 sm:p-3 rounded-lg bg-surface-card/80 border border-surface-elevated/80 flex flex-col">
                        <span className="text-[11px] font-medium text-slate-400 truncate">
                          Total Orders
                        </span>
                        <div className="mt-1 flex items-baseline justify-between gap-1 flex-wrap">
                          <span className="text-base sm:text-lg font-bold text-white tracking-tight tabular-nums">
                            {currentDataset.kpis.orders}
                          </span>
                          <span className="inline-flex items-center text-[10px] sm:text-[11px] font-semibold text-emerald-400 tabular-nums">
                            <ArrowUpRight className="w-3 h-3 mr-0.5 shrink-0" />
                            +{currentDataset.kpis.ordersDelta}%
                          </span>
                        </div>
                        <span className="text-[10px] text-slate-400 font-mono mt-0.5">
                          {currentDataset.kpis.ordersFulfillment}
                        </span>
                      </div>
                    </div>

                    {/* Recharts Revenue Trajectory & Anomaly Chart */}
                    <div className="p-3 rounded-lg bg-surface-card/60 border border-surface-elevated/80">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-[11px] sm:text-xs font-medium text-slate-300">
                          Revenue Trajectory ({currentDataset.periodLabel})
                        </span>
                        <span className="text-[10px] font-mono text-cyan-300 bg-cyan-950/40 px-2 py-0.5 rounded border border-cyan-800/40 font-medium">
                          {currentDataset.anomaly.badge}
                        </span>
                      </div>
                      
                      <div className="h-[155px] sm:h-[165px] w-full pt-0.5" role="img" aria-label={`Revenue and margin trajectory for ${currentDataset.label}`}>
                        <ResponsiveContainer width="100%" height="100%">
                          <AreaChart data={currentDataset.points} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                            <defs>
                              <linearGradient id="heroRevGrad" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#06b6d4" stopOpacity="0.2" />
                                <stop offset="100%" stopColor="#06b6d4" stopOpacity="0.01" />
                              </linearGradient>
                            </defs>
                            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" vertical={false} />
                            <XAxis 
                              dataKey="period" 
                              stroke="#64748b" 
                              fontSize={10} 
                              tickLine={false} 
                              axisLine={false} 
                              dy={5}
                            />
                            <YAxis 
                              stroke="#64748b" 
                              fontSize={10} 
                              tickLine={false} 
                              axisLine={false} 
                              tickFormatter={(val) => `$${val}k`}
                              domain={['auto', 'auto']}
                            />
                            <Tooltip
                              content={({ active, payload, label }) => {
                                if (active && payload && payload.length) {
                                  const data = payload[0].payload as RevenueDataPoint;
                                  return (
                                    <div className="rounded-lg bg-slate-950/95 border border-surface-elevated p-2.5 shadow-xl text-xs font-mono">
                                      <p className="text-slate-400 mb-1 font-medium">{label}</p>
                                      <p className="text-white font-bold flex items-center justify-between gap-3">
                                        <span className="text-cyan-400">Net Revenue:</span>
                                        <span className="tabular-nums">${data.revenue}k</span>
                                      </p>
                                      <p className="text-slate-300 flex items-center justify-between gap-3 mt-0.5">
                                        <span className="text-slate-400">Gross Margin:</span>
                                        <span className="tabular-nums">{data.margin}%</span>
                                      </p>
                                    </div>
                                  );
                                }
                                return null;
                              }}
                            />
                            <Area
                              type="monotone"
                              dataKey="revenue"
                              stroke="#06b6d4"
                              strokeWidth={2}
                              fill="url(#heroRevGrad)"
                              activeDot={{ r: 4, stroke: '#22d3ee', strokeWidth: 1.5, fill: '#083344' }}
                            />
                            {currentDataset.points.find((p) => p.period === currentDataset.anomaly.period) && (
                              <ReferenceDot
                                x={currentDataset.anomaly.period}
                                y={currentDataset.anomaly.revenue}
                                r={5}
                                fill="#fb7185"
                                stroke="#0f172a"
                                strokeWidth={2}
                              />
                            )}
                          </AreaChart>
                        </ResponsiveContainer>
                      </div>
                    </div>

                    {/* Diagnostic Finding Panel */}
                    <div className="p-2.5 sm:p-3 rounded-lg bg-surface-card/90 border border-cyan-500/25 space-y-2">
                      <div className="flex items-start gap-2.5">
                        <div className="p-1 rounded-md bg-cyan-950/70 border border-cyan-500/30 text-cyan-300 shrink-0 mt-0.5">
                          <SearchCode className="w-3.5 h-3.5" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center justify-between gap-2 flex-wrap">
                            <span className="text-xs font-semibold text-slate-200">
                              Variance Root Cause: {currentDataset.anomaly.period}
                            </span>
                            <span className="text-[10px] font-mono text-cyan-300 font-medium">
                              Calculated Variance Attribution
                            </span>
                          </div>
                          <p className="text-xs text-slate-300 mt-0.5 leading-relaxed">
                            {currentDataset.anomaly.finding}
                          </p>
                        </div>
                      </div>

                      {/* Lineage Footnote */}
                      <div className="pt-1.5 border-t border-surface-elevated/70 flex items-center justify-between text-[10px] font-mono text-slate-400">
                        <div className="flex items-center gap-1.5">
                          <ShieldCheck className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                          <span>{currentDataset.anomaly.auditCount}</span>
                        </div>
                        <span className="text-slate-400">
                          {currentDataset.anomaly.lineage}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Frame Footer Disclosure */}
                  <div className="px-3.5 py-1.5 bg-void/70 border-t border-surface-elevated/60 flex items-center justify-between text-[10px] text-slate-400">
                    <span className="font-mono text-[10px]">Deterministic SQL verification</span>
                    <span className="italic text-[10px] text-slate-400">Illustrative preview with sample retail data</span>
                  </div>
                </div>
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          3. PIPELINE ARCHITECTURE — INK ORBIT-INSPIRED BENTO
      ───────────────────────────────────────────────────────────── */}
      <section id="how-it-works" className="py-10 sm:py-14 border-t border-surface-elevated/70 bg-void/70 relative overflow-hidden">
        {/* Ambient backdrop glow */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[720px] h-[280px] bg-cyan-950/20 blur-[110px] rounded-full pointer-events-none" />

        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
          {/* Section Heading */}
          <div className="text-center max-w-2xl mx-auto mb-6 sm:mb-8">
            <div className="inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-500/30 text-cyan-300 text-[10px] font-mono tracking-wider uppercase mb-2 shadow-sm">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
              <span>PIPELINE ARCHITECTURE</span>
            </div>
            <h2 className="text-2xl sm:text-3xl lg:text-[32px] font-bold tracking-tight text-white mb-2 font-sans">
              From business data to better decisions.
            </h2>
            <p className="text-slate-300 text-xs sm:text-sm leading-relaxed max-w-lg mx-auto font-sans">
              NEXUS combines business context, deterministic calculations, and inspectable evidence to explain what moved and why.
            </p>
          </div>

          {/* Asymmetric Bento Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 lg:gap-5 items-stretch relative">
            
            {/* PANEL 1: BUSINESS DATA */}
            <div className="lg:col-span-3 rounded-2xl border border-surface-elevated/90 bg-surface-card/60 p-4 sm:p-5 flex flex-col justify-between space-y-3.5 relative group">
              <div className="absolute top-2 left-2 w-1.5 h-1.5 border-t border-l border-slate-700/70 pointer-events-none" />
              <div className="absolute top-2 right-2 w-1.5 h-1.5 border-t border-r border-slate-700/70 pointer-events-none" />
              <div className="absolute bottom-2 left-2 w-1.5 h-1.5 border-b border-l border-slate-700/70 pointer-events-none" />
              <div className="absolute bottom-2 right-2 w-1.5 h-1.5 border-b border-r border-slate-700/70 pointer-events-none" />

              <div className="flex items-center justify-between border-b border-surface-elevated/60 pb-2.5">
                <div className="flex items-center gap-2">
                  <div className="w-7 h-7 rounded-lg bg-surface-elevated/80 border border-slate-700/60 flex items-center justify-center text-cyan-400">
                    <Database className="w-3.5 h-3.5" />
                  </div>
                  <div>
                    <span className="text-[10px] font-mono text-cyan-400 uppercase tracking-wider block font-medium">Stage 1</span>
                    <h3 className="text-sm font-semibold text-white font-sans">Business Data</h3>
                  </div>
                </div>
                <span className="text-[10px] font-mono text-slate-300 bg-surface-elevated/70 border border-slate-700/60 px-2 py-0.5 rounded-full">
                  CSV & XLSX
                </span>
              </div>

              {/* Source Nodes ➔ Gateway Hub */}
              <div className="relative rounded-xl bg-void/85 border border-surface-elevated/70 p-3 h-[148px] flex flex-col justify-center overflow-hidden">
                <div className="relative w-full h-[100px]">
                  <svg viewBox="0 0 250 100" className="w-full h-full overflow-visible" preserveAspectRatio="none">
                    <path
                      d="M 102 18 C 146 18, 146 50, 192 50"
                      fill="none"
                      stroke="rgba(100, 116, 139, 0.35)"
                      strokeWidth="1.2"
                      strokeDasharray="3 3"
                    />
                    <path
                      d="M 102 50 L 192 50"
                      fill="none"
                      stroke="rgba(100, 116, 139, 0.35)"
                      strokeWidth="1.2"
                      strokeDasharray="3 3"
                    />
                    <path
                      d="M 102 82 C 146 82, 146 50, 192 50"
                      fill="none"
                      stroke="rgba(100, 116, 139, 0.35)"
                      strokeWidth="1.2"
                      strokeDasharray="3 3"
                    />

                    <circle r="2" fill="#22d3ee" className="motion-safe:block hidden opacity-80">
                      <animateMotion
                        path="M 102 18 C 146 18, 146 50, 192 50"
                        dur="5s"
                        repeatCount="indefinite"
                      />
                    </circle>
                    <circle r="2" fill="#38bdf8" className="motion-safe:block hidden opacity-80">
                      <animateMotion
                        path="M 102 50 L 192 50"
                        dur="5s"
                        begin="1.7s"
                        repeatCount="indefinite"
                      />
                    </circle>
                    <circle r="2" fill="#22d3ee" className="motion-safe:block hidden opacity-80">
                      <animateMotion
                        path="M 102 82 C 146 82, 146 50, 192 50"
                        dur="5s"
                        begin="3.4s"
                        repeatCount="indefinite"
                      />
                    </circle>
                  </svg>

                  <div className="absolute left-0 top-0 bottom-0 w-[102px] flex flex-col justify-between">
                    <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-surface-elevated/80 border border-slate-700/60 text-[10px] text-slate-300">
                      <BarChart3 className="w-3 h-3 text-cyan-400 shrink-0" />
                      <span className="truncate">Orders & Sales</span>
                    </div>
                    <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-surface-elevated/80 border border-slate-700/60 text-[10px] text-slate-300">
                      <Users className="w-3 h-3 text-emerald-400 shrink-0" />
                      <span className="truncate">Customers</span>
                    </div>
                    <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-surface-elevated/80 border border-slate-700/60 text-[10px] text-slate-300">
                      <Layers className="w-3 h-3 text-amber-400 shrink-0" />
                      <span className="truncate">Stock & Costs</span>
                    </div>
                  </div>

                  <div className="absolute right-0 top-1/2 -translate-y-1/2 flex flex-col items-center">
                    <div className="w-10 h-10 rounded-xl bg-cyan-950/85 border border-cyan-500/40 flex items-center justify-center text-cyan-300 shadow-[0_0_16px_rgba(6,182,212,0.18)] relative">
                      <Database className="w-4 h-4" />
                      <span className="absolute -top-0.5 -right-0.5 flex h-2 w-2">
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-400" />
                      </span>
                    </div>
                    <span className="text-[10px] font-mono text-slate-400 mt-1">Ingestion Hub</span>
                  </div>
                </div>
              </div>

              <div className="pt-0.5 font-sans">
                <p className="text-xs text-slate-300 leading-relaxed">
                  Bring sales, product, customer, inventory, and expense data together.
                </p>
              </div>

              <div className="hidden lg:flex absolute -right-3 top-1/2 -translate-y-1/2 z-20 w-6 h-6 rounded-full bg-void border border-surface-elevated items-center justify-center text-slate-500 shadow-md">
                <ArrowRight className="w-3 h-3 text-cyan-400" />
              </div>
            </div>

            <div className="lg:hidden flex items-center justify-center py-0.5 text-slate-500">
              <ArrowDown className="w-4 h-4 text-cyan-400/80" />
            </div>

            {/* PANEL 2: INTELLIGENCE ENGINE */}
            <div className="lg:col-span-5 rounded-2xl border-2 border-cyan-500/35 bg-gradient-to-b from-cyan-950/30 via-surface-card/95 to-void/90 p-4 sm:p-5 shadow-[0_0_35px_rgba(6,182,212,0.08)] flex flex-col justify-between space-y-3.5 relative group">
              <div className="absolute top-2 left-2 w-1.5 h-1.5 border-t border-l border-cyan-400/70 pointer-events-none" />
              <div className="absolute top-2 right-2 w-1.5 h-1.5 border-t border-r border-cyan-400/70 pointer-events-none" />
              <div className="absolute bottom-2 left-2 w-1.5 h-1.5 border-b border-l border-cyan-400/70 pointer-events-none" />
              <div className="absolute bottom-2 right-2 w-1.5 h-1.5 border-b border-r border-cyan-400/70 pointer-events-none" />

              <div className="flex items-center justify-between border-b border-cyan-500/25 pb-2.5">
                <div className="flex items-center gap-2">
                  <div className="w-7 h-7 rounded-lg bg-cyan-950/80 border border-cyan-500/40 flex items-center justify-center text-cyan-300 shadow-cyan-subtle">
                    <Cpu className="w-3.5 h-3.5" />
                  </div>
                  <div>
                    <span className="text-[10px] font-mono text-cyan-400 uppercase tracking-wider block font-semibold">Stage 2</span>
                    <h3 className="text-sm font-semibold text-white font-sans">Intelligence Engine</h3>
                  </div>
                </div>
                <span className="text-[10px] font-mono text-cyan-300 bg-cyan-950/70 border border-cyan-500/30 px-2 py-0.5 rounded-full">
                  Deterministic Math
                </span>
              </div>

              <div className="relative rounded-xl bg-void/85 border border-cyan-500/20 p-2.5 h-[148px] flex flex-col justify-between overflow-hidden">
                <div className="flex items-center justify-between text-[10px] font-mono text-slate-400">
                  <span>ANALYTICAL CIRCUIT</span>
                  <span className="text-cyan-400/90">Select to inspect</span>
                </div>

                <div className="relative my-auto">
                  <div className="absolute top-[16px] left-[12%] right-[12%] h-[2px] bg-slate-800/80 -z-0">
                    <div
                      className="h-full bg-cyan-400/80 transition-all duration-300 motion-reduce:transition-none"
                      style={{ width: `${(pipelineEngineStage / 3) * 100}%` }}
                    />
                  </div>

                  <div className="relative z-10 grid grid-cols-4 gap-1.5">
                    {PIPELINE_ENGINE_STAGES.map((stg, idx) => {
                      const IconComponent = stg.icon;
                      const isActive = pipelineEngineStage === idx;
                      const isPast = pipelineEngineStage > idx;
                      return (
                        <button
                          key={stg.name}
                          type="button"
                          onClick={() => setPipelineEngineStage(idx)}
                          className={`flex flex-col items-center text-center p-1 rounded-lg transition-all focus:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400 ${
                            isActive
                              ? 'bg-cyan-950/80 border border-cyan-500/60 text-white shadow-[0_0_12px_rgba(6,182,212,0.25)]'
                              : isPast
                              ? 'bg-surface-elevated/40 text-slate-300 border border-slate-700/50 hover:border-slate-600'
                              : 'text-slate-500 hover:text-slate-400 border border-transparent'
                          }`}
                        >
                          <div
                            className={`w-6 h-6 rounded-lg flex items-center justify-center transition-colors mb-1 ${
                              isActive
                                ? 'bg-cyan-500 text-slate-950 font-bold'
                                : isPast
                                ? 'bg-surface-elevated text-cyan-400 border border-cyan-500/20'
                                : 'bg-void-dark text-slate-500 border border-slate-800'
                            }`}
                          >
                            <IconComponent className="w-3 h-3" />
                          </div>
                          <span className="text-[10px] font-semibold tracking-tight truncate max-w-full">
                            {stg.name}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="px-2.5 py-1 rounded bg-void-dark/90 border border-white/[0.06] text-[10px] font-mono text-cyan-300/90 truncate">
                  {PIPELINE_ENGINE_STAGES[pipelineEngineStage].rule}
                </div>
              </div>

              <div className="pt-0.5 font-sans">
                <p className="text-xs text-slate-300 leading-relaxed">
                  Validate data, calculate reliable metrics, and explain performance drivers.
                </p>
              </div>

              <div className="hidden lg:flex absolute -right-3 top-1/2 -translate-y-1/2 z-20 w-6 h-6 rounded-full bg-void border border-surface-elevated items-center justify-center text-slate-500 shadow-md">
                <ArrowRight className="w-3 h-3 text-cyan-400" />
              </div>
            </div>

            <div className="lg:hidden flex items-center justify-center py-0.5 text-slate-500">
              <ArrowDown className="w-4 h-4 text-cyan-400/80" />
            </div>

            {/* PANEL 3: BUSINESS INTELLIGENCE */}
            <div className="lg:col-span-4 rounded-2xl border border-surface-elevated/90 bg-surface-card/60 p-4 sm:p-5 flex flex-col justify-between space-y-3.5 relative group">
              <div className="absolute top-2 left-2 w-1.5 h-1.5 border-t border-l border-slate-700/70 pointer-events-none" />
              <div className="absolute top-2 right-2 w-1.5 h-1.5 border-t border-r border-slate-700/70 pointer-events-none" />
              <div className="absolute bottom-2 left-2 w-1.5 h-1.5 border-b border-l border-slate-700/70 pointer-events-none" />
              <div className="absolute bottom-2 right-2 w-1.5 h-1.5 border-b border-r border-slate-700/70 pointer-events-none" />

              <div className="flex items-center justify-between border-b border-surface-elevated/60 pb-2.5">
                <div className="flex items-center gap-2">
                  <div className="w-7 h-7 rounded-lg bg-surface-elevated/80 border border-slate-700/60 flex items-center justify-center text-cyan-400">
                    <TrendingUp className="w-3.5 h-3.5" />
                  </div>
                  <div>
                    <span className="text-[10px] font-mono text-cyan-400 uppercase tracking-wider block font-medium">Stage 3</span>
                    <h3 className="text-sm font-semibold text-white font-sans">Business Intelligence</h3>
                  </div>
                </div>
                <span className="text-[10px] font-mono text-slate-300 bg-surface-elevated/70 border border-slate-700/60 px-2 py-0.5 rounded-full">
                  Sample Output
                </span>
              </div>

              {/* Trajectory & Forecast */}
              <div className="relative rounded-xl bg-void/85 border border-surface-elevated/70 p-2.5 h-[148px] flex flex-col justify-between overflow-hidden">
                <div className="flex items-center justify-between text-[10px] font-mono text-slate-400">
                  <span>METRIC TRAJECTORY (SAMPLE)</span>
                  <span className="text-cyan-400/90 font-medium">Projection Corridor</span>
                </div>

                <div className="relative w-full h-[88px] my-auto">
                  <svg viewBox="0 0 260 88" className="w-full h-full overflow-visible" preserveAspectRatio="none">
                    <defs>
                      <linearGradient id="orbit-corridor-grad" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" stopColor="#06b6d4" stopOpacity="0.22" />
                        <stop offset="100%" stopColor="#06b6d4" stopOpacity="0.02" />
                      </linearGradient>
                    </defs>

                    <line x1="8" y1="22" x2="252" y2="22" stroke="rgba(255,255,255,0.06)" strokeDasharray="2 2" />
                    <line x1="8" y1="48" x2="252" y2="48" stroke="rgba(255,255,255,0.06)" strokeDasharray="2 2" />
                    <line x1="8" y1="74" x2="252" y2="74" stroke="rgba(255,255,255,0.06)" strokeDasharray="2 2" />

                    <line x1="175" y1="8" x2="175" y2="80" stroke="rgba(148,163,184,0.3)" strokeDasharray="3 3" />
                    <text x="175" y="18" fill="rgba(148,163,184,0.7)" fontSize="9" fontFamily="monospace">
                      SAMPLE FORECAST
                    </text>

                    <polygon
                      points="175,46 215,30 252,22 252,60 215,56 175,46"
                      fill="url(#orbit-corridor-grad)"
                      stroke="rgba(6,182,212,0.35)"
                      strokeDasharray="2 2"
                    />

                    <path
                      d="M 12 60 Q 48 72 82 50 T 145 36 T 175 46"
                      fill="none"
                      stroke="#f1f5f9"
                      strokeWidth="1.8"
                    />

                    <path
                      d="M 175 46 Q 215 39 252 35"
                      fill="none"
                      stroke="#22d3ee"
                      strokeWidth="1.8"
                      strokeDasharray="3 3"
                    />

                    <circle cx="145" cy="36" r="4" fill="#fb7185" stroke="#0f172a" strokeWidth="2" />
                    <circle cx="252" cy="35" r="3" fill="#22d3ee" stroke="#0f172a" strokeWidth="1.5" />
                  </svg>

                  <div className="absolute left-[20%] top-[4px] px-1.5 py-0.5 rounded bg-rose-950/90 border border-rose-500/40 text-[10px] font-mono text-rose-200 shadow-sm flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
                    <span>Sample: Margin -2.6%</span>
                  </div>
                </div>

                <div className="relative z-10 flex items-center justify-between pt-1 border-t border-surface-elevated/60 text-[10px] font-mono">
                  <div className="flex items-center gap-1.5 text-slate-300 min-w-0">
                    <ShieldCheck className="w-3 h-3 text-cyan-400 shrink-0" />
                    <span className="truncate">Sample lineage: orders.csv ➔ shipping_costs.csv</span>
                  </div>
                </div>
              </div>

              <div className="pt-0.5 font-sans">
                <p className="text-xs text-slate-300 leading-relaxed">
                  Understand what changed, explore supported forecasts, and review the evidence.
                </p>
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          4. CORE CAPABILITIES — ASYMMETRIC PRECISION BENTO
      ───────────────────────────────────────────────────────────── */}
      <section id="capabilities" className="py-16 sm:py-20 border-t border-surface-elevated/70 relative">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          {/* Section Header */}
          <div className="max-w-3xl mb-10 sm:mb-12">
            <div className="inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full bg-surface-elevated/80 border border-slate-700/60 text-cyan-400 text-[10px] font-mono tracking-wider uppercase mb-3">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
              <span>CORE CAPABILITIES</span>
            </div>
            <h2 className="text-2xl sm:text-3xl lg:text-4xl font-bold tracking-tight text-white mb-3">
              Engineered for decision certainty.
            </h2>
            <p className="text-slate-300 text-sm sm:text-base leading-relaxed">
              Replacing manual spreadsheets and ungrounded guesswork with natural-language discovery, mathematical variance decomposition, and human-in-the-loop governance.
            </p>
          </div>

          {/* Asymmetric Bento Showcase */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-stretch">
            
            {/* HERO FEATURE (Col span 7): Ask NEXUS — Conversational Commercial Intelligence */}
            <div className="lg:col-span-7 rounded-2xl border border-surface-elevated/90 bg-gradient-to-br from-surface-card/95 via-surface-card/80 to-void/90 p-5 sm:p-6 flex flex-col justify-between shadow-xl relative overflow-hidden group">
              <div className="absolute top-2 left-2 w-1.5 h-1.5 border-t border-l border-slate-700/80 pointer-events-none" />
              <div className="absolute top-2 right-2 w-1.5 h-1.5 border-t border-r border-slate-700/80 pointer-events-none" />
              <div className="absolute bottom-2 left-2 w-1.5 h-1.5 border-b border-l border-slate-700/80 pointer-events-none" />
              <div className="absolute bottom-2 right-2 w-1.5 h-1.5 border-b border-r border-slate-700/80 pointer-events-none" />

              <div>
                <div className="flex items-center justify-between mb-4 pb-3 border-b border-surface-elevated/70">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-cyan-950/80 border border-cyan-500/40 flex items-center justify-center text-cyan-300 shadow-cyan-subtle">
                      <HelpCircle className="w-4 h-4" />
                    </div>
                    <div>
                      <span className="text-[10px] font-mono text-cyan-400 tracking-wider uppercase block font-semibold">
                        01 / CONVERSATIONAL DISCOVERY
                      </span>
                      <h3 className="text-base sm:text-lg font-bold text-white font-sans">
                        Ask NEXUS
                      </h3>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono text-slate-400 bg-surface-elevated/70 px-2 py-0.5 rounded-full border border-slate-700/60">
                    Natural Language
                  </span>
                </div>

                <p className="text-xs sm:text-sm text-slate-300 leading-relaxed mb-4">
                  Query commercial performance in plain business terms. Ask about margin shifts, customer retention, or inventory velocity and receive immediate, structured answers with inspectable calculations.
                </p>

                {/* Simulated Interactive Query Terminal Preview */}
                <div className="rounded-xl border border-cyan-500/20 bg-void/90 p-3.5 sm:p-4 space-y-3 font-mono text-xs">
                  {/* User Query Bubble */}
                  <div className="flex items-start gap-2.5 bg-surface-elevated/40 p-2.5 rounded-lg border border-slate-800">
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 font-semibold shrink-0">
                      QUERY
                    </span>
                    <span className="text-slate-200 text-xs font-sans">
                      “Why did Gross Margin compress by 2.6% in SKU Category 40 during Day 22?”
                    </span>
                  </div>

                  {/* Structured Engine Response */}
                  <div className="space-y-2 pt-1 border-t border-surface-elevated/60">
                    <div className="flex items-center justify-between text-[10px]">
                      <span className="text-cyan-400 font-semibold flex items-center gap-1">
                        <Sparkles className="w-3 h-3" />
                        DECOMPOSED FINDING
                      </span>
                      <span className="text-slate-400">4,820 rows audited (sample)</span>
                    </div>

                    <div className="p-2.5 rounded-lg bg-surface-card/90 border border-surface-elevated/70 text-slate-300 text-xs font-sans leading-relaxed">
                      Gross margin contracted from <strong>40.1%</strong> to <strong>35.6%</strong> due to an unhedged <strong>+$4.20/unit freight surcharge</strong> across 1,840 expedited shipments, offset by repeat order volume (+6.8%).
                    </div>

                    {/* Quick Evidence Chips */}
                    <div className="flex flex-wrap items-center gap-2 pt-1 text-[10px]">
                      <span className="text-slate-400">Linked Sources:</span>
                      <span className="px-2 py-0.5 rounded bg-surface-elevated/80 text-cyan-300 border border-slate-700/60 flex items-center gap-1">
                        <FileText className="w-2.5 h-2.5" />
                        orders.csv
                      </span>
                      <span className="px-2 py-0.5 rounded bg-surface-elevated/80 text-cyan-300 border border-slate-700/60 flex items-center gap-1">
                        <FileText className="w-2.5 h-2.5" />
                        shipping_costs.csv
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="pt-4 mt-3 border-t border-surface-elevated/70 flex items-center justify-between text-[11px] font-mono text-slate-400">
                <span>Deterministic SQL translation</span>
                <span className="text-cyan-400">Interactive Preview</span>
              </div>
            </div>

            {/* SECONDARY TILES (Col span 5): Stacked Investigation & Predict */}
            <div className="lg:col-span-5 flex flex-col justify-between gap-5">
              
              {/* TILE 2: Investigate (Driver Decomposition) */}
              <div className="rounded-2xl border border-surface-elevated/90 bg-surface-card/60 p-5 flex flex-col justify-between shadow-lg relative overflow-hidden group">
                <div>
                  <div className="flex items-center justify-between mb-3 pb-2 border-b border-surface-elevated/60">
                    <div className="flex items-center gap-2">
                      <div className="w-7 h-7 rounded-lg bg-surface-elevated/80 border border-slate-700/60 flex items-center justify-center text-cyan-400">
                        <SearchCode className="w-3.5 h-3.5" />
                      </div>
                      <div>
                        <span className="text-[10px] font-mono text-cyan-400 uppercase tracking-wider block font-medium">02 / DECOMPOSITION</span>
                        <h3 className="text-sm font-semibold text-white font-sans">Investigate</h3>
                      </div>
                    </div>
                    <span className="text-[10px] font-mono text-slate-400 bg-surface-elevated/60 px-2 py-0.5 rounded-full border border-slate-700/50">
                      PVM Math
                    </span>
                  </div>

                  <p className="text-xs text-slate-300 leading-relaxed mb-3">
                    Isolate whether commercial movement was driven by unit pricing, volume surges, product mix shifts, or raw cost inflation.
                  </p>

                  {/* Micro Waterfall Metric Breakdown */}
                  <div className="grid grid-cols-3 gap-2 font-mono text-center">
                    <div className="p-2 rounded bg-void/80 border border-surface-elevated">
                      <div className="text-[10px] text-slate-400">VOLUME</div>
                      <div className="text-xs font-bold text-emerald-400 mt-0.5">+1.2%</div>
                    </div>
                    <div className="p-2 rounded bg-void/80 border border-surface-elevated">
                      <div className="text-[10px] text-slate-400">PRICE MIX</div>
                      <div className="text-xs font-bold text-slate-300 mt-0.5">-0.4%</div>
                    </div>
                    <div className="p-2 rounded bg-void/80 border border-rose-500/25 bg-rose-950/20">
                      <div className="text-[10px] text-rose-300">SURCHARGE</div>
                      <div className="text-xs font-bold text-rose-400 mt-0.5">-3.4%</div>
                    </div>
                  </div>
                </div>

                <div className="pt-3 mt-3 border-t border-surface-elevated/60 text-[10px] font-mono text-slate-400 flex items-center justify-between">
                  <span>Price-Volume-Mix Attribution</span>
                  <span className="text-slate-400">Sample Model</span>
                </div>
              </div>

              {/* TILE 3: Predict (Supported Forecasting) */}
              <div className="rounded-2xl border border-surface-elevated/90 bg-surface-card/60 p-5 flex flex-col justify-between shadow-lg relative overflow-hidden group">
                <div>
                  <div className="flex items-center justify-between mb-3 pb-2 border-b border-surface-elevated/60">
                    <div className="flex items-center gap-2">
                      <div className="w-7 h-7 rounded-lg bg-surface-elevated/80 border border-slate-700/60 flex items-center justify-center text-cyan-400">
                        <TrendingUp className="w-3.5 h-3.5" />
                      </div>
                      <div>
                        <span className="text-[10px] font-mono text-cyan-400 uppercase tracking-wider block font-medium">03 / FORECASTING</span>
                        <h3 className="text-sm font-semibold text-white font-sans">Predict</h3>
                      </div>
                    </div>
                    <span className="text-[10px] font-mono text-slate-400 bg-surface-elevated/60 px-2 py-0.5 rounded-full border border-slate-700/50">
                      Trend & Horizon
                    </span>
                  </div>

                  <p className="text-xs text-slate-300 leading-relaxed mb-3">
                    Forward-looking run-rate modeling with visible uncertainty corridors. Explicit data-depth gates warn when sample history is insufficient.
                  </p>

                  {/* Micro Forecast Horizon Bar */}
                  <div className="p-2.5 rounded-lg bg-void/80 border border-surface-elevated space-y-1.5 font-mono text-[10px]">
                    <div className="flex items-center justify-between text-slate-400">
                      <span>90-Day Projection Band (Sample)</span>
                      <span className="text-cyan-300 font-bold">$510k – $545k</span>
                    </div>
                    <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden flex">
                      <div className="bg-slate-600 h-full w-[45%]" />
                      <div className="bg-cyan-500 h-full w-[35%]" />
                      <div className="bg-cyan-400/30 h-full w-[20%]" />
                    </div>
                  </div>
                </div>

                <div className="pt-3 mt-3 border-t border-surface-elevated/60 text-[10px] font-mono text-slate-400 flex items-center justify-between">
                  <span>Historical Depth: 18 Months</span>
                  <span className="text-slate-400">Sample Bounds</span>
                </div>
              </div>

            </div>

            {/* INTEGRATED FOUNDATION BAR (Col span 12): Provenance Lineage & Governance */}
            <div className="lg:col-span-12 rounded-2xl border border-surface-elevated/80 bg-surface-card/40 p-5 sm:p-6 grid grid-cols-1 md:grid-cols-2 gap-6 items-center">
              {/* Evidence & Lineage */}
              <div className="flex items-start gap-3.5">
                <div className="w-8 h-8 rounded-lg bg-surface-elevated/80 border border-slate-700/60 flex items-center justify-center text-cyan-400 shrink-0 mt-0.5">
                  <ShieldCheck className="w-4 h-4" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono text-cyan-400 uppercase tracking-wider font-semibold">04 / PROVENANCE</span>
                    <span className="text-slate-500">•</span>
                    <h4 className="text-sm font-semibold text-white font-sans">Evidence & Audit Lineage</h4>
                  </div>
                  <p className="text-xs text-slate-300 leading-relaxed mt-1">
                    Every generated metric links back to its underlying raw dataset columns. Calculations pair transparent SQL math with exportable file-level references.
                  </p>
                </div>
              </div>

              {/* Decision Guidance */}
              <div className="flex items-start gap-3.5 border-t md:border-t-0 md:border-l border-surface-elevated/70 pt-4 md:pt-0 md:pl-6">
                <div className="w-8 h-8 rounded-lg bg-surface-elevated/80 border border-slate-700/60 flex items-center justify-center text-cyan-400 shrink-0 mt-0.5">
                  <UserCheck className="w-4 h-4" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono text-cyan-400 uppercase tracking-wider font-semibold">05 / GOVERNANCE</span>
                    <span className="text-slate-500">•</span>
                    <h4 className="text-sm font-semibold text-white font-sans">Decision Guidance</h4>
                  </div>
                  <p className="text-xs text-slate-300 leading-relaxed mt-1">
                    Intelligence remains strictly advisory. Human operators inspect scenario trade-offs, review risk factors, and retain full operational authority.
                  </p>
                </div>
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          5. SIGNATURE EXPERIENCE — "AI THAT SHOWS ITS WORK"
      ───────────────────────────────────────────────────────────── */}
      <section id="trust" className="py-16 sm:py-20 border-t border-surface-elevated/70 bg-void/80 relative">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          
          {/* Section Header */}
          <div className="text-center max-w-2xl mx-auto mb-10 sm:mb-12">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-emerald-500/30 bg-emerald-950/30 text-emerald-300 text-xs font-mono mb-3">
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>DETERMINISTIC VERIFICATION</span>
            </div>
            <h2 className="text-2xl sm:text-3xl lg:text-4xl font-bold tracking-tight text-white mb-3">
              AI That Shows Its Work.
            </h2>
            <p className="text-slate-300 text-sm sm:text-base leading-relaxed">
              No black-box answers. NEXUS grounds every finding in transparent calculation traces, inspectable variance decomposition, and auditable raw dataset records.
            </p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
            
            {/* Left: 4-Step Interactive Verification Journey */}
            <div className="lg:col-span-5 space-y-3">
              {[
                {
                  step: 1,
                  title: 'Business Question',
                  preview: '“Why did gross margin drop 2.6% on Day 22?”',
                  detail: 'User asks a natural-language commercial question. NEXUS extracts grain, filters, and target metrics.',
                },
                {
                  step: 2,
                  title: 'Analytical Investigation',
                  preview: 'Price-Volume-Mix (PVM) mathematical decomposition',
                  detail: 'Deterministic arithmetic isolates price variations, unit volume shifts, and cost surcharges across categories.',
                },
                {
                  step: 3,
                  title: 'Supporting Evidence',
                  preview: 'Lineage: orders.csv ➔ shipping_costs.csv',
                  detail: 'Directly references 4,820 order entries and freight adjustment records without sampling distortion.',
                },
                {
                  step: 4,
                  title: 'Executive Explanation',
                  preview: 'Actionable root cause with advisory trade-off',
                  detail: 'Plain-English summary explains why margin contracted and suggests renegotiation or pricing adjustments.',
                },
              ].map((item) => {
                const isSelected = activeTrustStep === item.step;
                return (
                  <button
                    key={item.step}
                    type="button"
                    onClick={() => setActiveTrustStep(item.step)}
                    className={`w-full text-left p-3.5 rounded-xl border transition-all flex items-start gap-3.5 focus:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400 ${
                      isSelected
                        ? 'bg-surface-card border-cyan-500/60 shadow-[0_0_20px_rgba(6,182,212,0.12)]'
                        : 'bg-surface-card/40 border-surface-elevated/70 hover:border-slate-700 text-slate-400'
                    }`}
                  >
                    <div
                      className={`w-7 h-7 rounded-lg flex items-center justify-center font-mono text-xs font-bold shrink-0 transition-colors ${
                        isSelected
                          ? 'bg-cyan-500 text-slate-950 shadow-sm'
                          : 'bg-surface-elevated text-slate-400 border border-slate-700/60'
                      }`}
                    >
                      {item.step}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between">
                        <span className={`text-xs font-semibold ${isSelected ? 'text-white' : 'text-slate-300'}`}>
                          {item.title}
                        </span>
                        {isSelected && (
                          <span className="text-[10px] font-mono text-cyan-400 bg-cyan-950/70 px-2 py-0.5 rounded border border-cyan-500/30">
                            Active Step
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] font-mono text-cyan-300/90 truncate mt-0.5">
                        {item.preview}
                      </p>
                      <p className="text-[11px] text-slate-400 font-sans mt-1 leading-relaxed">
                        {item.detail}
                      </p>
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Right: Inspection Console (Dual View: Business vs Formula) */}
            <div className="lg:col-span-7">
              <div className="rounded-2xl border border-surface-elevated bg-surface-card shadow-2xl overflow-hidden">
                {/* Console Top Toolbar */}
                <div className="px-4 py-3 border-b border-surface-elevated bg-void/80 flex items-center justify-between flex-wrap gap-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
                    <span className="text-xs font-mono text-slate-200 font-medium">
                      INSPECTION CONSOLE (SAMPLE DATA)
                    </span>
                    <span className="text-[10px] font-mono text-cyan-300 bg-cyan-950/80 px-2 py-0.5 rounded border border-cyan-500/30">
                      {activeTrustStep === 1 && 'Focus: 01 / Business Question'}
                      {activeTrustStep === 2 && 'Focus: 02 / PVM Decomposition'}
                      {activeTrustStep === 3 && 'Focus: 03 / Supporting Lineage'}
                      {activeTrustStep === 4 && 'Focus: 04 / Executive Explanation'}
                    </span>
                  </div>

                  {/* Dual Mode Switcher */}
                  <div className="flex items-center bg-surface-elevated/80 p-0.5 rounded-lg border border-slate-700/60">
                    <button
                      type="button"
                      onClick={() => setTrustInspectionView('business')}
                      className={`px-2.5 py-1 text-[11px] font-mono rounded transition-colors ${
                        trustInspectionView === 'business'
                          ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 font-semibold'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      Business Breakdown
                    </button>
                    <button
                      type="button"
                      onClick={() => setTrustInspectionView('formula')}
                      className={`px-2.5 py-1 text-[11px] font-mono rounded transition-colors ${
                        trustInspectionView === 'formula'
                          ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 font-semibold'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      Formula Proof
                    </button>
                  </div>
                </div>

                {/* Console Main Content Area */}
                <div className="p-5 sm:p-6 space-y-4">
                  {trustInspectionView === 'business' ? (
                    <div className="space-y-3.5">
                      {/* Step 1: Executive Context Header / Question Focus */}
                      <div className={`p-3 rounded-xl border transition-all ${
                        activeTrustStep === 1
                          ? 'bg-cyan-950/30 border-cyan-500/60 ring-1 ring-cyan-500/30 shadow-[0_0_16px_rgba(6,182,212,0.12)]'
                          : 'bg-void/40 border-surface-elevated/70'
                      }`}>
                        <div className="flex items-center justify-between pb-2 border-b border-surface-elevated/60">
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="text-[10px] font-mono text-slate-400 uppercase">SUBJECT METRIC</span>
                              {activeTrustStep === 1 && (
                                <span className="text-[10px] font-mono text-cyan-300 bg-cyan-950 px-1.5 py-0.5 rounded border border-cyan-500/40">
                                  Step 1 Target
                                </span>
                              )}
                            </div>
                            <div className="text-sm font-bold text-white font-sans mt-0.5">
                              Gross Margin Variance Attribution: Day 22
                            </div>
                          </div>
                          <div className="text-right">
                            <div className="text-[10px] font-mono text-slate-400 uppercase">NET SHIFT</div>
                            <div className="text-sm font-mono font-bold text-rose-400 mt-0.5">-2.6% ($18,200)</div>
                          </div>
                        </div>
                        <div className="text-[11px] text-slate-400 mt-2 font-mono flex items-center justify-between">
                          <span>Target Baseline: 38.2% ➔ Actual: 35.6%</span>
                          <span className="text-cyan-400">Query Grain: Daily Store Channel</span>
                        </div>
                      </div>

                      {/* Step 2: Decomposed Drivers Visual Grid */}
                      <div className={`p-3 rounded-xl border transition-all ${
                        activeTrustStep === 2
                          ? 'bg-cyan-950/20 border-cyan-500/60 ring-1 ring-cyan-500/30 shadow-[0_0_16px_rgba(6,182,212,0.12)]'
                          : 'bg-void/40 border-surface-elevated/70'
                      }`}>
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-[10px] font-mono text-slate-400 uppercase">02 / PVM DRIVER DECOMPOSITION</span>
                          {activeTrustStep === 2 && (
                            <span className="text-[10px] font-mono text-cyan-300 bg-cyan-950 px-1.5 py-0.5 rounded border border-cyan-500/40">
                              Step 2 Decomposition
                            </span>
                          )}
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                          <div className="p-2.5 rounded-lg bg-void/90 border border-surface-elevated flex flex-col justify-between">
                            <span className="text-[10px] font-mono text-slate-400">FREIGHT SURCHARGE</span>
                            <div className="my-1">
                              <span className="text-base font-bold text-rose-400 font-mono">-3.4%</span>
                              <p className="text-[10px] text-slate-400 mt-0.5">Expedited logistics on SKU 40</p>
                            </div>
                            <span className="text-[10px] font-mono text-slate-400">1,840 shipments</span>
                          </div>

                          <div className="p-2.5 rounded-lg bg-void/90 border border-surface-elevated flex flex-col justify-between">
                            <span className="text-[10px] font-mono text-slate-400">VOLUME OFFSET</span>
                            <div className="my-1">
                              <span className="text-base font-bold text-emerald-400 font-mono">+1.2%</span>
                              <p className="text-[10px] text-slate-400 mt-0.5">Bulk reorders cushioned margin</p>
                            </div>
                            <span className="text-[10px] font-mono text-slate-400">2,980 repeat orders</span>
                          </div>

                          <div className="p-2.5 rounded-lg bg-void/90 border border-surface-elevated flex flex-col justify-between">
                            <span className="text-[10px] font-mono text-slate-400">MIX SHIFT</span>
                            <div className="my-1">
                              <span className="text-base font-bold text-slate-300 font-mono">-0.4%</span>
                              <p className="text-[10px] text-slate-400 mt-0.5">Lower-margin accessory share</p>
                            </div>
                            <span className="text-[10px] font-mono text-slate-400">Basket mix variation</span>
                          </div>
                        </div>
                      </div>

                      {/* Step 3: Evidence Trail Footnote */}
                      <div className={`p-3 rounded-xl border transition-all flex items-center justify-between text-xs font-mono text-slate-300 ${
                        activeTrustStep === 3
                          ? 'bg-cyan-950/30 border-cyan-500/60 ring-1 ring-cyan-500/30 shadow-[0_0_16px_rgba(6,182,212,0.12)]'
                          : 'bg-void/60 border-surface-elevated'
                      }`}>
                        <div className="flex items-center gap-2 min-w-0">
                          <ShieldCheck className="w-4 h-4 text-cyan-400 shrink-0" />
                          <span className="truncate">Sample Scope: 4,820 transactions across 2 CSV ledgers</span>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          {activeTrustStep === 3 && (
                            <span className="text-[10px] font-mono text-cyan-300 bg-cyan-950 px-1.5 py-0.5 rounded border border-cyan-500/40">
                              Step 3 Lineage
                            </span>
                          )}
                          <span className="text-slate-400 text-[10px]">Deterministic SQL</span>
                        </div>
                      </div>

                      {/* Step 4: Executive Explanation & Advisory */}
                      <div className={`p-3 rounded-xl border transition-all ${
                        activeTrustStep === 4
                          ? 'bg-cyan-950/30 border-cyan-500/60 ring-1 ring-cyan-500/30 shadow-[0_0_16px_rgba(6,182,212,0.12)]'
                          : 'bg-void/40 border-surface-elevated/70'
                      }`}>
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-[10px] font-mono text-cyan-400 uppercase font-semibold">04 / EXECUTIVE ACTION ADVISORY</span>
                          {activeTrustStep === 4 && (
                            <span className="text-[10px] font-mono text-cyan-300 bg-cyan-950 px-1.5 py-0.5 rounded border border-cyan-500/40">
                              Step 4 Explanation
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-slate-300 leading-relaxed font-sans">
                          <strong>Decision Advisory:</strong> Freight surcharge inflation on SKU 40 drove 130% of gross margin contraction. Revert non-critical replenishment shipments to standard transit schedule or adjust SKU 40 FOB terms to recover ~1.5% margin.
                        </p>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-3 font-mono text-xs">
                      <div className="text-slate-400 text-[10px]">
                        // Deterministic metric calculation trace (sample representation)
                      </div>
                      
                      <div className="p-3.5 rounded-xl bg-void border border-surface-elevated space-y-2 text-slate-300">
                        <div className={`p-2 rounded-lg transition-colors ${activeTrustStep === 1 ? 'bg-cyan-950/40 border border-cyan-500/40' : ''}`}>
                          <div className="text-cyan-300 font-semibold">-- STEP 1: Calculate Gross Margin Delta</div>
                          <div className="text-slate-400 pl-3">
                            margin_day22 = (net_revenue - cogs) / net_revenue = 35.6%
                          </div>
                          <div className="text-slate-400 pl-3">
                            baseline_margin = 38.2% (Target: 40.0%)
                          </div>
                          <div className="text-slate-400 pl-3">
                            variance_delta = 35.6% - 38.2% = <span className="text-rose-400 font-bold">-2.6%</span>
                          </div>
                        </div>

                        <div className={`p-2 rounded-lg transition-colors ${activeTrustStep === 2 ? 'bg-cyan-950/40 border border-cyan-500/40' : ''}`}>
                          <div className="text-cyan-300 font-semibold">-- STEP 2: Isolate PVM Driver Components</div>
                          <div className="text-slate-400 pl-3">
                            freight_delta = SUM(freight_surcharge) / net_revenue = <span className="text-rose-400 font-bold">-3.4%</span>
                          </div>
                          <div className="text-slate-400 pl-3">
                            volume_benefit = (actual_units - budget_units) * margin_rate = <span className="text-emerald-400 font-bold">+1.2%</span>
                          </div>
                          <div className="text-slate-400 pl-3">
                            mix_effect = net_variance - (freight_delta + volume_benefit) = <span className="text-slate-300">-0.4%</span>
                          </div>
                        </div>

                        <div className={`p-2 rounded-lg transition-colors ${activeTrustStep >= 3 ? 'bg-cyan-950/40 border border-cyan-500/40' : ''}`}>
                          <div className="text-cyan-300 font-semibold">-- STEP 3 & 4: Evidence Lineage & Attribution Trace</div>
                          <div className="text-slate-400 pl-3">
                            source_lineage = orders.csv (4,820 rows) ➔ shipping_costs.csv (1,840 matches)
                          </div>
                          <div className="text-slate-400 pl-3">
                            advisory_tradeoff = &apos;Carrier renegotiation or FOB tier adjustment (+1.5% margin recovery)&apos;
                          </div>
                        </div>
                      </div>

                      <div className="text-[10px] text-slate-400 italic">
                        * All platform calculations execute deterministically on your isolated workspace database (Sample proof shown).
                      </div>
                    </div>
                  )}
                </div>

                {/* Console Footer */}
                <div className="px-5 py-2.5 bg-void/90 border-t border-surface-elevated/70 flex items-center justify-between text-[11px] font-mono text-slate-400">
                  <span>Traceability: Deterministic ledger mapping (Sample)</span>
                  <span className="text-cyan-400">Grounding: Deterministic calculations only (Sample)</span>
                </div>
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          6. PLATFORM WORKBENCH — FULLY COMPOSED PRODUCT SHOWCASE
      ───────────────────────────────────────────────────────────── */}
      <section id="product-preview" className="py-16 sm:py-20 border-t border-surface-elevated/70">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          
          {/* Section Header */}
          <div className="text-center max-w-2xl mx-auto mb-10 sm:mb-12">
            <div className="inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-500/30 text-cyan-300 text-[10px] font-mono tracking-wider uppercase mb-2 shadow-sm">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
              <span>PLATFORM SHOWCASE</span>
            </div>
            <h2 className="text-2xl sm:text-3xl lg:text-4xl font-bold tracking-tight text-white mb-2">
              Explore the NEXUS Platform.
            </h2>
            <p className="text-slate-300 text-xs sm:text-sm max-w-xl mx-auto leading-relaxed">
              A unified operational environment combining executive overviews, conversational discovery, variance decomposition, and evidence lineage.
            </p>
            <div className="mt-2 text-[11px] font-mono text-slate-400">
              * Illustrative preview demonstrating actual product interface workflows with sample retail data.
            </div>
          </div>

          {/* Workbench Frame */}
          <div className="rounded-2xl border border-surface-elevated bg-surface-card/90 overflow-hidden shadow-2xl">
            {/* Workbench Top Chrome */}
            <div className="flex flex-wrap items-center justify-between border-b border-surface-elevated px-4 sm:px-6 py-3 bg-surface-base/90 gap-3">
              {/* Functional Interactive Tabs */}
              <div className="flex items-center space-x-1.5 overflow-x-auto pb-1 sm:pb-0" role="tablist">
                {(
                  [
                    { id: 'overview', label: 'Executive Overview' },
                    { id: 'ask', label: 'Ask NEXUS' },
                    { id: 'investigate', label: 'Investigation' },
                    { id: 'forecast', label: 'Forecast Model' },
                    { id: 'evidence', label: 'Evidence Engine' },
                  ] as const
                ).map((tab) => (
                  <button
                    key={tab.id}
                    role="tab"
                    aria-selected={activeProductTab === tab.id}
                    onClick={() => setActiveProductTab(tab.id)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-mono transition-all focus:outline-none focus-visible:ring-1 focus-visible:ring-cyan-400 whitespace-nowrap ${
                      activeProductTab === tab.id
                        ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 font-semibold shadow-sm'
                        : 'text-slate-400 hover:text-white hover:bg-surface-elevated'
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              {/* Status Indicator */}
              <div className="flex items-center gap-2 text-xs font-mono text-slate-400">
                <span className="w-2 h-2 rounded-full bg-emerald-400" />
                <span>Workspace: Retail Operations Demo</span>
              </div>
            </div>

            {/* Tab Body */}
            <div className="p-5 sm:p-8 min-h-[380px]">
              
              {/* TAB 1: EXECUTIVE OVERVIEW */}
              {activeProductTab === 'overview' && (
                <div className="space-y-6">
                  {/* High Density KPI Row */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    <div className="p-4 rounded-xl bg-surface-base border border-surface-elevated">
                      <div className="text-[10px] font-mono text-slate-400 uppercase">NET REVENUE (MTD)</div>
                      <div className="text-2xl font-bold text-white mt-1 font-mono">$482,900</div>
                      <div className="text-xs text-emerald-400 mt-1 flex items-center gap-1 font-mono">
                        <ArrowUpRight className="w-3 h-3" />
                        <span>+12.4%</span> vs prior month
                      </div>
                    </div>

                    <div className="p-4 rounded-xl bg-surface-base border border-surface-elevated">
                      <div className="text-[10px] font-mono text-slate-400 uppercase">GROSS MARGIN</div>
                      <div className="text-2xl font-bold text-white mt-1 font-mono">36.8%</div>
                      <div className="text-xs text-rose-400 mt-1 flex items-center gap-1 font-mono">
                        <ArrowDownRight className="w-3 h-3" />
                        <span>-1.8%</span> target: 38.0%
                      </div>
                    </div>

                    <div className="p-4 rounded-xl bg-surface-base border border-surface-elevated">
                      <div className="text-[10px] font-mono text-slate-400 uppercase">TOTAL ORDERS</div>
                      <div className="text-2xl font-bold text-white mt-1 font-mono">3,491</div>
                      <div className="text-xs text-emerald-400 mt-1 flex items-center gap-1 font-mono">
                        <ArrowUpRight className="w-3 h-3" />
                        <span>+8.1%</span> vs prior month
                      </div>
                    </div>

                    <div className="p-4 rounded-xl bg-surface-base border border-surface-elevated">
                      <div className="text-[10px] font-mono text-slate-400 uppercase">DATA HEALTH SCORE</div>
                      <div className="text-2xl font-bold text-cyan-400 mt-1 font-mono">94 / 100</div>
                      <div className="text-xs text-slate-400 mt-1 flex items-center gap-1 font-mono">
                        <span>6 validation checks passed</span>
                      </div>
                    </div>
                  </div>

                  {/* Synthesized Intelligence Finding */}
                  <div className="p-5 rounded-xl bg-void/80 border border-cyan-500/30 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="w-2 h-2 rounded-full bg-cyan-400" />
                        <span className="text-xs font-mono text-cyan-400 uppercase font-semibold">SYNTHESIZED INTELLIGENCE</span>
                      </div>
                      <div className="text-sm font-semibold text-white">
                        Strong sales momentum offset by freight surcharge increases on SKU Category 40.
                      </div>
                      <div className="text-xs text-slate-400 mt-1 font-mono">
                        Sample lineage traced across 3,491 order records and supplier rate cards.
                      </div>
                    </div>
                    <button
                      onClick={() => setActiveProductTab('investigate')}
                      className="px-4 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 text-xs font-semibold font-sans transition-colors shrink-0"
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
                    <span className="font-mono text-xs text-cyan-400 block mb-1">EXECUTIVE QUERY</span>
                    “Which product categories delivered the highest gross margin last month?”
                  </div>

                  <div className="p-5 rounded-xl bg-surface-base border border-cyan-500/30 text-sm text-slate-200 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs text-cyan-400 font-semibold flex items-center gap-1.5">
                        <Sparkles className="w-3.5 h-3.5" />
                        NEXUS SYNTHESIS
                      </span>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-500/30">
                        Lineage Verified (Sample)
                      </span>
                    </div>
                    <p className="text-xs sm:text-sm leading-relaxed text-slate-300 font-sans">
                      In the prior month, <strong>Enterprise Storage</strong> recorded the highest gross margin at <strong>48.2%</strong> ($92,400 revenue),
                      followed by <strong>Security Hardware</strong> at <strong>41.6%</strong> ($68,100 revenue).
                      Consumer Accessories underperformed at <strong>24.1%</strong> due to freight surcharges.
                    </p>
                    <div className="p-3 rounded-lg bg-void border border-surface-elevated font-mono text-[11px] text-slate-400">
                      Calculated from 1,280 line items across 4 store channels. Sample data preview.
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 3: INVESTIGATION */}
              {activeProductTab === 'investigate' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <div>
                      <h4 className="text-sm font-bold text-white font-sans">Gross Margin Variance Waterfall</h4>
                      <p className="text-xs text-slate-400 font-sans">Root cause decomposition for -1.8% gross margin variance</p>
                    </div>
                    <span className="text-xs font-mono text-slate-400">Period: Prior Month vs Baseline</span>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-xs">
                    <div className="p-4 rounded-xl bg-surface-base border border-surface-elevated">
                      <div className="text-slate-400 text-[10px]">VOLUME EFFECT</div>
                      <div className="text-lg font-bold text-emerald-400 mt-1">+0.8%</div>
                      <div className="text-[11px] text-slate-400 mt-1">Higher unit reorders across high-end lines</div>
                    </div>
                    <div className="p-4 rounded-xl bg-surface-base border border-surface-elevated">
                      <div className="text-slate-400 text-[10px]">PRICE REALIZATION</div>
                      <div className="text-lg font-bold text-slate-300 mt-1">+0.1%</div>
                      <div className="text-[11px] text-slate-400 mt-1">Average selling price remained steady</div>
                    </div>
                    <div className="p-4 rounded-xl bg-surface-base border border-rose-500/30 bg-rose-950/10">
                      <div className="text-rose-300 text-[10px]">COST SURCHARGES (ROOT CAUSE)</div>
                      <div className="text-lg font-bold text-rose-400 mt-1">-2.7%</div>
                      <div className="text-[11px] text-rose-300/80 mt-1">Expedited freight adjustment in SKU-801, 804</div>
                    </div>
                  </div>

                  <div className="p-4 rounded-xl bg-surface-base/60 border border-surface-elevated text-xs text-slate-300 font-sans leading-relaxed">
                    <strong className="text-white">Commercial Recommendation:</strong> Review fulfillment routing or renegotiate supplier carrier agreements for Audio components to recover an estimated 1.5% margin.
                  </div>
                </div>
              )}

              {/* TAB 4: FORECAST MODEL */}
              {activeProductTab === 'forecast' && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <div>
                      <h4 className="text-sm font-bold text-white font-sans">Forward 90-Day Revenue Projection (Sample)</h4>
                      <p className="text-xs text-slate-400 font-sans">Historical regression models with explicit uncertainty bounds</p>
                    </div>
                    <span className="text-xs font-mono text-cyan-400 bg-cyan-950/40 px-2.5 py-1 rounded border border-cyan-500/30">
                      HISTORICAL DEPTH: 18 MONTHS
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
                    <div className="flex items-center justify-between text-[11px] font-mono text-slate-400">
                      <span>Baseline: $482k</span>
                      <span>Median: $528k</span>
                      <span>Optimistic: $545k</span>
                    </div>
                  </div>

                  <div className="text-xs font-mono text-slate-400">
                    * Forecast models recalculate automatically upon new tabular batch ingestion. Uncertainty bands widen over longer horizons.
                  </div>
                </div>
              )}

              {/* TAB 5: EVIDENCE ENGINE */}
              {activeProductTab === 'evidence' && (
                <div className="space-y-4 font-mono text-xs">
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <h4 className="text-sm font-bold text-white font-sans">Evidence Audit Trail (Sample Representation)</h4>
                    <span className="text-cyan-400">FILE LINEAGE MAPPING</span>
                  </div>

                  <div className="p-4 rounded-xl bg-void border border-surface-elevated space-y-2 text-slate-300">
                    <div className="text-slate-400">// Dataset provenance metadata</div>
                    <div>Source File: sales_transactions_2025_q3.csv (3.4 MB)</div>
                    <div>Fingerprint: 8f4b1e...0d4a92c1</div>
                    <div>Ingested: 2025-10-01T04:12:00Z</div>
                    <div>Tenant Isolation: business_id=biz_0192e (Isolated schema sample)</div>
                  </div>

                  <div className="p-4 rounded-xl bg-surface-base border border-surface-elevated text-slate-300 leading-relaxed font-sans text-xs">
                    Every metric shown in the NEXUS interface links directly to specific rows in your uploaded CSV/XLSX records. Calculations are transparent, verifiable, and exportable.
                  </div>
                </div>
              )}

            </div>
          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          7. FINAL CTA — ARCHITECTURAL, CONCISE, DEFINITIVE
      ───────────────────────────────────────────────────────────── */}
      <section className="py-16 sm:py-20 border-t border-surface-elevated/70 bg-gradient-to-b from-void via-surface-card/30 to-void relative overflow-hidden">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center relative z-10">
          
          <div className="inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-500/30 text-cyan-300 text-[10px] font-mono tracking-wider uppercase mb-3 shadow-sm">
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
            <span>OPERATIONAL CLARITY</span>
          </div>

          <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-white mb-3 font-sans">
            Turn your business data into intelligence.
          </h2>

          <p className="text-sm sm:text-base text-slate-300 max-w-xl mx-auto mb-8 font-sans leading-relaxed">
            Deterministic calculations, inspectable driver decomposition, and evidence-grounded decision support for retail and distribution operations.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-3.5 mb-8">
            <button
              onClick={() => onNavigate(isAuthenticated ? '/' : '/signup')}
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-7 py-3 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-xs sm:text-sm transition-all duration-200 shadow-[0_0_25px_rgba(6,182,212,0.3)] focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 active:scale-[0.98]"
            >
              Get Started
              <ArrowRight className="w-4 h-4" />
            </button>
            <button
              onClick={() => onNavigate('/login')}
              className="w-full sm:w-auto px-6 py-3 rounded-xl border border-surface-elevated hover:border-slate-600 bg-surface-card/60 text-slate-300 hover:text-white text-xs sm:text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 active:scale-[0.98]"
            >
              Sign In
            </button>
          </div>

          {/* Minimal 3-Point Validation Strip */}
          <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs font-mono text-slate-400">
            <span className="flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400" />
              CSV & XLSX Ingestion
            </span>
            <span className="text-slate-700 hidden sm:inline">•</span>
            <span className="flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400" />
              Deterministic Metric Engine
            </span>
            <span className="text-slate-700 hidden sm:inline">•</span>
            <span className="flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400" />
              Human-Governed Decisions
            </span>
          </div>

        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          8. RESTRAINED ENTERPRISE FOOTER
      ───────────────────────────────────────────────────────────── */}
      <footer className="border-t border-surface-elevated py-12 bg-void text-xs font-mono text-slate-400">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-8 mb-8">
            <div className="space-y-3 md:col-span-1">
              <NexusLogo imageSize={24} showTagline={false} />
              <p className="text-slate-400 text-xs font-sans leading-relaxed">
                Evidence-grounded business intelligence for commercial operations.
              </p>
            </div>

            <div>
              <div className="text-[11px] font-mono text-slate-300 font-semibold uppercase tracking-wider mb-3">
                Platform
              </div>
              <ul className="space-y-2 text-slate-400">
                <li>
                  <button onClick={() => scrollToSection('how-it-works')} className="hover:text-cyan-400 transition-colors">
                    Pipeline Architecture
                  </button>
                </li>
                <li>
                  <button onClick={() => scrollToSection('capabilities')} className="hover:text-cyan-400 transition-colors">
                    Core Capabilities
                  </button>
                </li>
                <li>
                  <button onClick={() => scrollToSection('trust')} className="hover:text-cyan-400 transition-colors">
                    Verification Audit
                  </button>
                </li>
                <li>
                  <button onClick={() => scrollToSection('product-preview')} className="hover:text-cyan-400 transition-colors">
                    Workbench Preview
                  </button>
                </li>
              </ul>
            </div>

            <div>
              <div className="text-[11px] font-mono text-slate-300 font-semibold uppercase tracking-wider mb-3">
                Capabilities
              </div>
              <ul className="space-y-2 text-slate-400">
                <li>Ask NEXUS (Conversational)</li>
                <li>Investigate (PVM Decomposition)</li>
                <li>Predict (Horizon Modeling)</li>
                <li>Audit Lineage (Row Provenance)</li>
              </ul>
            </div>

            <div>
              <div className="text-[11px] font-mono text-slate-300 font-semibold uppercase tracking-wider mb-3">
                Integrity
              </div>
              <ul className="space-y-2 text-slate-400">
                <li>Deterministic Calculations</li>
                <li>Tenant-Isolated Schemas</li>
                <li>Inspectable Provenance</li>
                <li>Human Decision Control</li>
              </ul>
            </div>
          </div>

          <div className="pt-8 border-t border-surface-elevated/70 flex flex-col sm:flex-row items-center justify-between gap-4 text-[11px]">
            <div>
              © {new Date().getFullYear()} NEXUS Platform. All rights reserved.
            </div>
            <div className="text-slate-400 italic">
              Illustrative product preview with sample retail data.
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
};
