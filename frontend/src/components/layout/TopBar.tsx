import React from 'react';
import {
  Search,
  Menu,
  ShieldCheck,
  Building2,
  Sparkles,
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
          title: 'Business Overview',
          subtitle: 'Executive intelligence and commercial performance at a glance',
        };
      case '/analytics':
        return {
          title: 'Deterministic Analytics',
          subtitle: 'Granular mathematical metric exploration with verified evidence',
        };
      case '/investigations':
        return {
          title: 'Diagnostic Investigations',
          subtitle: 'Multi-step diagnostic engine answering "Why did this happen?"',
        };
      case '/forecasts':
        return {
          title: 'Predictive Intelligence',
          subtitle: 'Backtested prospective time-series forecasting with prediction intervals',
        };
      case '/ask':
        return {
          title: 'Ask NEXUS Workspace',
          subtitle: 'Agentic intelligence with grounded provenance and semantic verification',
        };
      case '/data':
        return {
          title: 'Data Health & Catalog',
          subtitle: 'Dataset schema profiles, statistical coverage, and quality scorecards',
        };
      case '/knowledge':
        return {
          title: 'Knowledge & KPI Dictionary',
          subtitle: 'Business context policies, semantic ontology, and term resolution',
        };
      default:
        return {
          title: 'NEXUS Intelligence',
          subtitle: 'Where Business Data Becomes Intelligence',
        };
    }
  };

  const { title, subtitle } = getRouteInfo(currentRoute);
  const isHealthy = health?.status === 'healthy';

  return (
    <header className="h-16 px-4 sm:px-6 lg:px-8 border-b border-slate-800/80 bg-slate-950/80 backdrop-blur-md sticky top-0 z-20 flex items-center justify-between gap-4">
      {/* Left: Mobile Toggle & Page Title */}
      <div className="flex items-center gap-3 min-w-0">
        <button
          onClick={onOpenMobileMenu}
          className="md:hidden p-2 rounded-xl bg-slate-900 border border-slate-800 text-slate-300 hover:text-white"
          aria-label="Open mobile navigation"
        >
          <Menu className="w-5 h-5" />
        </button>

        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="text-base sm:text-lg font-bold text-slate-100 truncate">{title}</h1>
            <span className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-cyan-950/70 border border-cyan-800/60 text-[10px] font-mono text-cyan-300">
              <Building2 className="w-3 h-3 text-cyan-400" />
              Retail Enterprise
            </span>
          </div>
          <p className="text-xs text-slate-400 truncate hidden sm:block">{subtitle}</p>
        </div>
      </div>

      {/* Right Controls: Search, Quick Ask, System Status */}
      <div className="flex items-center gap-2 sm:gap-3 shrink-0">
        {/* Global Search / Command Bar Trigger */}
        <button
          onClick={onOpenCommand}
          className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-900/80 hover:bg-slate-800 border border-slate-800 text-slate-400 hover:text-slate-200 text-xs transition-all shadow-sm"
          title="Search NEXUS (Ctrl+K)"
        >
          <Search className="w-3.5 h-3.5" />
          <span className="hidden md:inline">Search / Ask...</span>
          <kbd className="hidden lg:inline-block px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-[10px] font-mono text-slate-400">
            ⌘K
          </kbd>
        </button>

        {/* Ask NEXUS Quick Trigger */}
        <button
          onClick={onOpenAsk}
          className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-cyan-600 to-sky-500 hover:from-cyan-500 hover:to-sky-400 text-white text-xs font-semibold shadow-md shadow-cyan-600/25 transition-all"
        >
          <Sparkles className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Ask NEXUS</span>
        </button>

        {/* System Health Badge */}
        <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-slate-900/60 border border-slate-800/80 text-[11px] font-mono text-slate-300">
          <ShieldCheck className={`w-3.5 h-3.5 ${isHealthy ? 'text-emerald-400' : 'text-amber-400'}`} />
          <span>{isHealthy ? 'Live' : 'Checking'}</span>
        </div>
      </div>
    </header>
  );
};
