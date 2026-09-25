import React from 'react';
import {
  Search,
  Menu,
  ShieldCheck,
  Building2,
  Sparkles,
  Key,
} from 'lucide-react';
import { HealthResponse } from '../../types/api';

interface TopBarProps {
  currentRoute: string;
  onOpenCommand: () => void;
  onOpenMobileMenu: () => void;
  onOpenAsk: () => void;
  health?: HealthResponse | null;
}

export const TopBar: React.FC<TopBarProps> = ({
  currentRoute,
  onOpenCommand,
  onOpenMobileMenu,
  onOpenAsk,
  health,
}) => {
  const getRouteInfo = (route: string) => {
    switch (route) {
      case '/':
        return {
          title: 'Executive Intelligence Briefing',
          subtitle: 'Real-time commercial telemetry and critical observed variance signals',
          badge: 'Commercial Briefing',
        };
      case '/ask':
        return {
          title: 'Intelligence Console',
          subtitle: 'Natural language strategic inquiries backed by deterministic analytics & RAG',
          badge: 'Agentic Console',
        };
      case '/investigations':
        return {
          title: 'Diagnostic Investigations',
          subtitle: 'Multi-step diagnostic engine answering "Why did this happen?" with causality safeguards',
          badge: 'Diagnostic Engine',
        };
      case '/forecasts':
        return {
          title: 'Predictive Intelligence',
          subtitle: 'Backtested prospective time-series forecasting with prediction intervals',
          badge: 'Predictive Horizon',
        };
      case '/analytics':
        return {
          title: 'Deterministic Analytics',
          subtitle: 'Granular mathematical metric exploration with verified evidence',
          badge: 'Deterministic Layer',
        };
      case '/data':
        return {
          title: 'Data Health & Catalog',
          subtitle: 'Dataset schema profiles, statistical coverage, and quality scorecards',
          badge: 'Data Layer',
        };
      case '/knowledge':
        return {
          title: 'Knowledge & KPI Dictionary',
          subtitle: 'Business context policies, semantic ontology, and term resolution',
          badge: 'Semantic Layer',
        };
      case '/history':
        return {
          title: 'Analyses & Human Governance',
          subtitle: 'Audit log of historical runs and human approval review gates',
          badge: 'Governance & Audit',
        };
      default:
        return {
          title: 'NEXUS Intelligence',
          subtitle: 'Where Business Data Becomes Intelligence',
          badge: 'Intelligence Workspace',
        };
    }
  };

  const { title, subtitle, badge } = getRouteInfo(currentRoute);
  const isHealthy = health?.status === 'healthy';

  return (
    <header className="h-16 px-4 sm:px-6 lg:px-8 border-b border-surface-elevated bg-void/80 backdrop-blur-md sticky top-0 z-20 flex items-center justify-between gap-4">
      {/* Left: Mobile Toggle & Page Title */}
      <div className="flex items-center gap-3 min-w-0">
        <button
          onClick={onOpenMobileMenu}
          className="md:hidden p-2 rounded-xl bg-surface border border-surface-elevated text-slate-300 hover:text-white"
          aria-label="Open mobile navigation"
        >
          <Menu className="w-5 h-5" />
        </button>

        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="text-sm sm:text-base font-bold text-slate-100 truncate font-sans">
              {title}
            </h1>
            <span className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-cyan-950/70 border border-brand-cyan/30 text-[10px] font-mono text-brand-cyan">
              <Building2 className="w-3 h-3 text-brand-cyan" />
              {badge}
            </span>
          </div>
          <p className="text-[11px] text-slate-400 truncate hidden sm:block font-sans">
            {subtitle}
          </p>
        </div>
      </div>

      {/* Right Controls: Command Bar, Quick Ask, Auth Perimeter, System Health */}
      <div className="flex items-center gap-2 sm:gap-3 shrink-0">
        {/* Global Search / Command Bar Trigger */}
        <button
          onClick={onOpenCommand}
          className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-surface hover:bg-surface-elevated border border-surface-elevated text-slate-400 hover:text-slate-200 text-xs transition-all shadow-sm"
          title="Search NEXUS Workspace (Ctrl+K or ⌘K)"
        >
          <Search className="w-3.5 h-3.5" />
          <span className="hidden md:inline">Command...</span>
          <kbd className="hidden lg:inline-block px-1.5 py-0.5 rounded bg-void border border-surface-elevated text-[10px] font-mono text-slate-400">
            ⌘K
          </kbd>
        </button>

        {/* Quick Ask Trigger */}
        <button
          onClick={onOpenAsk}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold shadow-sm transition-all"
        >
          <Sparkles className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Ask NEXUS</span>
        </button>

        {/* Security & Health Status Indicator */}
        <div className="hidden sm:flex items-center gap-2 px-2.5 py-1 rounded-xl bg-surface/70 border border-surface-elevated text-[11px] font-mono text-slate-300">
          <div className="flex items-center gap-1 text-slate-400" title="API Key Authentication Perimeter Active">
            <Key className="w-3 h-3 text-cyan-400" />
            <span className="text-[10px]">Auth</span>
          </div>
          <span className="text-slate-600">•</span>
          <div className="flex items-center gap-1.5">
            <ShieldCheck className={`w-3.5 h-3.5 ${isHealthy ? 'text-emerald-400' : 'text-amber-400'}`} />
            <span>{isHealthy ? 'Healthy' : 'Checking'}</span>
          </div>
        </div>
      </div>
    </header>
  );
};
