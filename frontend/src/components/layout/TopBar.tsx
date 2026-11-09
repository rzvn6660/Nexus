import React, { useState, useRef, useEffect } from 'react';
import {
  Search,
  Menu,
  ShieldCheck,
  Building2,
  Sparkles,
  Key,
  LogOut,
  ChevronDown,
  Check,
  Settings,
  Sun,
  Moon,
  Laptop,
} from 'lucide-react';
import { HealthResponse } from '../../types/api';
import { NexusSymbol } from '../brand/NexusSymbol';
import { useTheme, ThemeChoice } from '../../context/ThemeContext';

interface TopBarProps {
  currentRoute: string;
  onOpenCommand: () => void;
  onOpenMobileMenu: () => void;
  onOpenAsk: () => void;
  health?: HealthResponse | null;
  onNavigate?: (route: string) => void;
  onLogout?: () => void;
  activeBusinessName?: string;
  userRole?: string;
  businesses?: Array<{ id: string; name: string }>;
  activeBusinessId?: string;
  onSwitchBusiness?: (businessId: string) => void;
}

export const TopBar: React.FC<TopBarProps> = ({
  currentRoute,
  onOpenCommand,
  onOpenMobileMenu,
  onOpenAsk,
  health,
  onNavigate,
  onLogout,
  activeBusinessName = 'Workspace',
  userRole,
  businesses = [],
  activeBusinessId,
  onSwitchBusiness,
}) => {
  const [workspaceMenuOpen, setWorkspaceMenuOpen] = useState(false);
  const [themeMenuOpen, setThemeMenuOpen] = useState(false);
  const workspaceMenuRef = useRef<HTMLDivElement>(null);
  const themeMenuRef = useRef<HTMLDivElement>(null);

  const { theme, setTheme, resolvedTheme } = useTheme();

  // Close menus on outside click or Escape key
  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (workspaceMenuRef.current && !workspaceMenuRef.current.contains(e.target as Node)) {
        setWorkspaceMenuOpen(false);
      }
      if (themeMenuRef.current && !themeMenuRef.current.contains(e.target as Node)) {
        setThemeMenuOpen(false);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setWorkspaceMenuOpen(false);
        setThemeMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, []);

  const getRouteInfo = (route: string) => {
    switch (route) {
      case '/':
        return {
          title: 'Executive Overview',
          subtitle: 'Commercial telemetry, headline KPI performance, and critical variance signals',
          badge: 'Executive',
        };
      case '/ask':
        return {
          title: 'Ask NEXUS',
          subtitle: 'Natural-language inquiries backed by deterministic analytics and verified evidence',
          badge: 'Agentic',
        };
      case '/retention':
        return {
          title: 'Customer Retention & Churn Intelligence',
          subtitle: 'Prescriptive retention actions, merchant approval workflows, and outcome evaluation',
          badge: 'Retention',
        };
      case '/pulse':
        return {
          title: 'NEXUS Pulse',
          subtitle: 'Automated executive reports, multi-channel dispatches, and delivery audit trails',
          badge: 'Automated',
        };
      case '/settings':
        return {
          title: 'Global Settings Center',
          subtitle: 'Appearance themes, notification channels, report preferences, and system telemetry',
          badge: 'Settings',
        };
      case '/connectors':
        return {
          title: 'Connectors & Period Close',
          subtitle: 'Shopify, Stripe, and file data sources with multi-source reconciliation',
          badge: 'Integrations',
        };
      case '/analytics':
        return {
          title: 'Financial & Product Analytics',
          subtitle: 'Mathematical metric exploration, multidimensional breakdowns, and cohort trends',
          badge: 'Analytics',
        };
      case '/forecasts':
        return {
          title: 'Predictive Forecasts',
          subtitle: 'Prospective time-series forecasting with empirical prediction intervals',
          badge: 'Forecasts',
        };
      case '/investigations':
        return {
          title: 'Diagnostic Investigations',
          subtitle: 'Root cause analysis and driver decomposition with causality safeguards',
          badge: 'Diagnostic',
        };
      case '/data':
        return {
          title: 'Data Gateway',
          subtitle: 'Dataset schema profiles, statistical coverage, and quality scorecards',
          badge: 'Data Layer',
        };
      case '/knowledge':
        return {
          title: 'Knowledge & KPI Dictionary',
          subtitle: 'Business context policies, semantic ontology, and term resolution',
          badge: 'Ontology',
        };
      case '/history':
        return {
          title: 'Analyses & Governance',
          subtitle: 'Audit log of historical runs and human approval review gates',
          badge: 'Governance',
        };
      case '/business':
        return {
          title: 'Business Profile',
          subtitle: 'Multi-tenant organization profile, currency formatting, and operating parameters',
          badge: 'Tenant Profile',
        };
      default:
        return {
          title: 'NEXUS Intelligence',
          subtitle: 'Where Business Data Becomes Intelligence',
          badge: 'Intelligence',
        };
    }
  };

  const { title, subtitle, badge } = getRouteInfo(currentRoute);
  const isHealthy = health?.status === 'healthy';

  const themeOptions: Array<{ id: ThemeChoice; label: string; icon: React.ElementType }> = [
    { id: 'light', label: 'Light', icon: Sun },
    { id: 'dark', label: 'Dark', icon: Moon },
    { id: 'system', label: 'System', icon: Laptop },
  ];

  const CurrentThemeIcon = theme === 'system' ? Laptop : resolvedTheme === 'dark' ? Moon : Sun;

  return (
    <header className="h-16 px-4 sm:px-6 lg:px-8 border-b border-surface-elevated/80 bg-void/85 backdrop-blur-xl shrink-0 z-20 flex items-center justify-between gap-4">
      {/* Left: Mobile Toggle & Page Title */}
      <div className="flex items-center gap-3 min-w-0">
        <button
          onClick={onOpenMobileMenu}
          className="md:hidden p-2 rounded-xl bg-surface/80 border border-surface-elevated text-slate-300 hover:text-white transition-colors"
          aria-label="Open mobile navigation"
        >
          <Menu className="w-5 h-5" />
        </button>

        <div className="md:hidden shrink-0 flex items-center">
          <NexusSymbol size={28} />
        </div>

        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="text-sm sm:text-base font-bold text-white truncate font-sans">
              {title}
            </h1>
            <span className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-500/30 text-[10px] font-sans font-medium text-cyan-400 shrink-0">
              {badge}
            </span>
            {(activeBusinessName.toLowerCase().includes('sandbox') || activeBusinessName.toLowerCase().includes('demo')) && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/20 border border-amber-500/40 text-[10px] font-mono font-bold text-amber-300 shrink-0" title="Demonstration workspace: Operating under synthetic validation">
                SANDBOX / DEMO
              </span>
            )}
          </div>
          <p className="text-[11px] text-slate-400 truncate hidden sm:block font-sans">
            {subtitle}
          </p>
        </div>
      </div>

      {/* Right Controls: Command Bar, Quick Ask, Theme Toggle, Settings, System Health, Workspace Switcher */}
      <div className="flex items-center gap-2 sm:gap-2.5 shrink-0">
        {/* Global Search / Command Bar Trigger */}
        <button
          onClick={onOpenCommand}
          className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-surface/70 hover:bg-surface-elevated border border-surface-elevated text-slate-400 hover:text-white text-xs transition-all shadow-sm group"
          title="Search NEXUS Workspace (Ctrl+K or ⌘K)"
          aria-label="Search NEXUS Workspace"
        >
          <Search className="w-3.5 h-3.5 group-hover:text-cyan-400 transition-colors" />
          <span className="hidden md:inline font-sans">Command...</span>
          <kbd className="hidden lg:inline-block px-1.5 py-0.5 rounded bg-void border border-surface-elevated text-[10px] font-mono text-slate-400">
            ⌘K
          </kbd>
        </button>

        {/* Quick Ask Trigger */}
        <button
          onClick={onOpenAsk}
          className="btn-primary py-1.5 px-3 text-xs shadow-cyan-subtle"
          title="Open AI Intelligence Console"
        >
          <Sparkles className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Ask NEXUS</span>
        </button>

        {/* Adaptive Theme Quick Selector */}
        <div className="relative" ref={themeMenuRef}>
          <button
            onClick={() => setThemeMenuOpen(!themeMenuOpen)}
            className="p-2 rounded-xl bg-surface/80 hover:bg-surface-elevated border border-surface-elevated text-slate-400 hover:text-white text-xs transition-colors"
            title={`Current Theme: ${theme.toUpperCase()} (${resolvedTheme} active)`}
            aria-label="Select theme appearance"
            aria-expanded={themeMenuOpen}
          >
            <CurrentThemeIcon className="w-4 h-4 text-cyan-400" />
          </button>

          {themeMenuOpen && (
            <div className="absolute right-0 mt-2 w-36 rounded-2xl bg-surface border border-surface-highlight shadow-2xl p-1.5 z-50 animate-in fade-in zoom-in-95 duration-100">
              <div className="px-2.5 py-1 text-[9px] font-semibold text-slate-400 uppercase tracking-wider font-sans border-b border-surface-highlight/60 mb-1">
                Appearance
              </div>
              {themeOptions.map((opt) => {
                const Icon = opt.icon;
                const isSelected = theme === opt.id;
                return (
                  <button
                    key={opt.id}
                    onClick={() => {
                      setTheme(opt.id);
                      setThemeMenuOpen(false);
                    }}
                    className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-xl text-xs text-left transition-all ${
                      isSelected
                        ? 'bg-cyan-950/60 text-cyan-400 font-semibold border border-cyan-500/30'
                        : 'text-slate-300 hover:text-white hover:bg-surface-elevated'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <Icon className="w-3.5 h-3.5 text-cyan-400" />
                      <span>{opt.label}</span>
                    </div>
                    {isSelected && <Check className="w-3 h-3 text-cyan-400" />}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Global Settings Direct Button */}
        <button
          onClick={() => onNavigate?.('/settings')}
          className={`p-2 rounded-xl border text-xs transition-colors ${
            currentRoute === '/settings'
              ? 'bg-cyan-950/60 text-cyan-400 border-cyan-500/30'
              : 'bg-surface/80 hover:bg-surface-elevated border-surface-elevated text-slate-400 hover:text-white'
          }`}
          title="Open Global Settings Center"
          aria-label="Global Settings"
        >
          <Settings className="w-4 h-4" />
        </button>

        {/* Security & Health Status Indicator */}
        <div className="hidden xl:flex items-center gap-2 px-2.5 py-1.5 rounded-xl bg-surface/60 border border-surface-elevated/80 text-[11px] font-mono text-slate-300">
          <div className="flex items-center gap-1 text-slate-400" title="API Key / JWT Session Active">
            <Key className="w-3 h-3 text-cyan-400" />
            <span className="text-[10px]">Auth</span>
          </div>
          <span className="text-slate-400">•</span>
          <div className="flex items-center gap-1.5" title={`System Status: ${isHealthy ? 'Operational' : 'Checking'}`}>
            <ShieldCheck className={`w-3.5 h-3.5 ${isHealthy ? 'text-emerald-400' : 'text-amber-400'}`} />
            <span>{isHealthy ? 'Healthy' : 'Checking'}</span>
          </div>
        </div>

        {/* Active Workspace Switcher & User Profile */}
        <div className="relative flex items-center pl-1 border-l border-surface-elevated/80" ref={workspaceMenuRef}>
          {businesses.length > 1 ? (
            <div>
              <button
                onClick={() => setWorkspaceMenuOpen(!workspaceMenuOpen)}
                className="flex items-center gap-2 px-2.5 py-1.5 rounded-xl bg-surface/80 hover:bg-surface-elevated border border-surface-elevated text-xs transition-all"
                title="Switch Active Business Workspace"
                aria-expanded={workspaceMenuOpen}
                aria-haspopup="true"
              >
                <Building2 className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                <span className="font-semibold text-slate-200 max-w-[120px] truncate font-sans">
                  {activeBusinessName}
                </span>
                <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
              </button>

              {/* Workspace Switcher Dropdown */}
              {workspaceMenuOpen && (
                <div className="absolute right-0 mt-2 w-64 rounded-2xl bg-surface border border-surface-highlight shadow-2xl p-2 z-50 animate-in fade-in zoom-in-95 duration-100">
                  <div className="px-3 py-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-wider font-sans border-b border-surface-highlight/60">
                    Switch Business Workspace
                  </div>
                  <div className="py-1 max-h-48 overflow-y-auto space-y-0.5">
                    {businesses.map((b) => {
                      const isSelected = b.id === activeBusinessId || b.name === activeBusinessName;
                      return (
                        <button
                          key={b.id}
                          onClick={() => {
                            if (onSwitchBusiness) {
                              onSwitchBusiness(b.id);
                            }
                            setWorkspaceMenuOpen(false);
                          }}
                          className={`w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs text-left transition-all ${
                            isSelected
                              ? 'bg-cyan-950/60 text-cyan-400 font-semibold border border-cyan-500/30'
                              : 'text-slate-300 hover:text-white hover:bg-surface-elevated'
                          }`}
                        >
                          <span className="truncate">{b.name}</span>
                          {isSelected && <Check className="w-3.5 h-3.5 text-cyan-400 shrink-0" />}
                        </button>
                      );
                    })}
                  </div>
                  <div className="pt-1 mt-1 border-t border-surface-highlight/60">
                    <button
                      onClick={() => {
                        setWorkspaceMenuOpen(false);
                        onNavigate?.('/settings');
                      }}
                      className="w-full flex items-center gap-2 px-3 py-2 rounded-xl text-xs text-slate-400 hover:text-cyan-400 hover:bg-surface-elevated transition-all font-medium"
                    >
                      <Settings className="w-3.5 h-3.5" />
                      <span>Global Settings</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <button
              onClick={() => onNavigate?.('/settings')}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl bg-surface/80 hover:bg-surface-elevated border border-surface-elevated text-xs transition-all"
              title="Workspace Business Profile Settings"
            >
              <Building2 className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
              <span className="font-semibold text-slate-200 max-w-[120px] truncate font-sans">
                {activeBusinessName}
              </span>
              {userRole && (
                <span className="px-1.5 py-0.5 rounded bg-cyan-950/60 border border-cyan-500/30 text-[9px] font-mono text-cyan-400 uppercase">
                  {userRole}
                </span>
              )}
            </button>
          )}

          {/* User Sign Out */}
          {onLogout && (
            <button
              onClick={onLogout}
              className="ml-1 p-2 rounded-xl text-slate-400 hover:text-rose-400 hover:bg-surface-elevated transition-colors"
              title="Sign Out"
              aria-label="Sign Out"
            >
              <LogOut className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
    </header>
  );
};
