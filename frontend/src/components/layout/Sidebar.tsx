import React from 'react';
import {
  LayoutDashboard,
  BarChart3,
  SearchCode,
  TrendingUp,
  MessageSquare,
  Database,
  BookOpen,
  History,
  Building2,
  ChevronLeft,
  ChevronRight,
  X,
  Radio,
} from 'lucide-react';
import { DatabaseHealth } from '../../types/api';
import { NexusLogo } from '../brand/NexusLogo';

interface SidebarProps {
  currentRoute: string;
  onNavigate: (route: string) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  dbHealth?: DatabaseHealth | null;
  onCloseMobile?: () => void;
}

interface NavItem {
  title: string;
  route: string;
  icon: React.ElementType;
  badge?: string;
  description?: string;
}

interface NavGroup {
  label?: string;
  items: NavItem[];
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentRoute,
  onNavigate,
  collapsed,
  onToggleCollapse,
  dbHealth,
  onCloseMobile,
}) => {
  const navGroups: NavGroup[] = [
    {
      label: 'INTELLIGENCE WORKSPACE',
      items: [
        {
          title: 'Overview',
          route: '/',
          icon: LayoutDashboard,
          badge: 'Live',
        },
        {
          title: 'Ask NEXUS',
          route: '/ask',
          icon: MessageSquare,
          badge: 'Console',
        },
        {
          title: 'Investigate',
          route: '/investigations',
          icon: SearchCode,
          badge: 'Diagnostic',
        },
        {
          title: 'Forecast',
          route: '/forecasts',
          icon: TrendingUp,
          badge: 'Horizon',
        },
        {
          title: 'Analytics',
          route: '/analytics',
          icon: BarChart3,
        },
      ],
    },
    {
      label: 'DATA & ONTOLOGY',
      items: [
        {
          title: 'Data Health & Schema',
          route: '/data',
          icon: Database,
        },
        {
          title: 'Knowledge & KPIs',
          route: '/knowledge',
          icon: BookOpen,
        },
      ],
    },
    {
      label: 'GOVERNANCE & AUDIT',
      items: [
        {
          title: 'Analyses & Decisions',
          route: '/history',
          icon: History,
          badge: 'Audit',
        },
      ],
    },
    {
      label: 'WORKSPACE SETTINGS',
      items: [
        {
          title: 'Business Profile',
          route: '/business',
          icon: Building2,
          badge: 'Tenant',
        },
      ],
    },
  ];

  const handleItemClick = (route: string) => {
    onNavigate(route);
    if (onCloseMobile) {
      onCloseMobile();
    }
  };

  const isConnected = dbHealth?.status === 'connected';

  return (
    <aside
      className={`h-screen sticky top-0 bg-void border-r border-surface-elevated/80 flex flex-col justify-between transition-all duration-200 z-30 select-none ${
        collapsed ? 'w-20' : 'w-64'
      }`}
      aria-label="Main Navigation"
    >
      {/* Top Branding Section */}
      <div className="overflow-y-auto overflow-x-hidden flex-1 flex flex-col min-h-0">
        <div className="h-16 px-4 flex items-center justify-between border-b border-surface-elevated/80 shrink-0">
          <div
            onClick={() => handleItemClick('/')}
            className="cursor-pointer group flex items-center min-w-0"
            title="NEXUS Workspace Home"
          >
            <NexusLogo collapsed={collapsed} size={32} />
          </div>

          {/* Desktop collapse toggle */}
          <button
            onClick={onToggleCollapse}
            className="hidden md:flex p-1.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-surface-elevated transition-colors"
            title={collapsed ? 'Expand Workspace Sidebar' : 'Collapse Workspace Sidebar'}
            aria-label={collapsed ? 'Expand Workspace Sidebar' : 'Collapse Workspace Sidebar'}
          >
            {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          </button>

          {/* Mobile close button */}
          {onCloseMobile && (
            <button
              onClick={onCloseMobile}
              className="md:hidden p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-surface-elevated transition-colors"
              aria-label="Close navigation"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>

        {/* Grouped Navigation */}
        <nav className="p-3 space-y-5 mt-2 flex-1 overflow-y-auto" aria-label="Workspace Pages">
          {navGroups.map((group, gIdx) => (
            <div key={gIdx} className="space-y-1">
              {!collapsed && group.label && (
                <div className="px-3 text-[10px] font-semibold tracking-wider text-slate-400 uppercase mb-1.5 font-sans">
                  {group.label}
                </div>
              )}

              {group.items.map((item) => {
                const Icon = item.icon;
                const isActive =
                  item.route === '/'
                    ? currentRoute === '/'
                    : currentRoute === item.route || currentRoute.startsWith(`${item.route}/`);

                return (
                  <button
                    key={item.route}
                    onClick={() => handleItemClick(item.route)}
                    title={collapsed ? item.title : undefined}
                    aria-current={isActive ? 'page' : undefined}
                    className={`relative w-full flex items-center gap-3 px-3 py-2 rounded-xl text-xs transition-all group ${
                      isActive
                        ? 'bg-cyan-950/50 text-cyan-300 font-semibold border border-cyan-500/30 shadow-[0_0_12px_rgba(6,182,212,0.12)]'
                        : 'text-slate-400 hover:text-slate-100 hover:bg-surface-elevated/70 border border-transparent font-medium'
                    } ${collapsed ? 'justify-center px-0' : 'justify-between'}`}
                  >
                    {/* Active Accent Pill on left edge */}
                    {isActive && (
                      <span
                        className="absolute left-0 top-1.5 bottom-1.5 w-1 bg-cyan-400 rounded-r shadow-[0_0_8px_rgba(6,182,212,0.8)]"
                        aria-hidden="true"
                      />
                    )}

                    <div className="flex items-center gap-2.5 truncate min-w-0">
                      <Icon
                        className={`w-4 h-4 shrink-0 transition-colors ${
                          isActive
                            ? 'text-cyan-400 drop-shadow-[0_0_6px_rgba(6,182,212,0.6)]'
                            : 'text-slate-400 group-hover:text-slate-200'
                        }`}
                      />
                      {!collapsed && <span className="truncate">{item.title}</span>}
                    </div>

                    {!collapsed && item.badge && (
                      <span
                        className={`text-[9px] font-mono px-1.5 py-0.5 rounded uppercase font-semibold shrink-0 transition-colors ${
                          isActive
                            ? 'bg-cyan-900/60 text-cyan-200 border border-cyan-500/30'
                            : 'bg-surface-elevated text-slate-400 border border-white/5'
                        }`}
                      >
                        {item.badge}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>
      </div>

      {/* Bottom Infrastructure & System Status */}
      <div className="p-3 border-t border-surface-elevated/80 space-y-2 shrink-0 bg-void-sub/40">
        <div
          className={`flex items-center gap-2 p-2.5 rounded-xl bg-surface/70 border border-surface-elevated/80 text-xs ${
            collapsed ? 'justify-center' : 'justify-between'
          }`}
          title={`Database: ${isConnected ? 'Connected' : 'Offline'} (${dbHealth?.latency_ms ? `${dbHealth.latency_ms}ms` : 'healthy'})`}
        >
          <div className="flex items-center gap-2 truncate">
            <span
              className={`w-2 h-2 rounded-full shrink-0 ${
                isConnected ? 'bg-emerald-400' : dbHealth === null ? 'bg-amber-400' : 'bg-rose-500'
              }`}
            />
            {!collapsed && (
              <span className="text-slate-200 font-medium truncate font-sans text-xs">
                {isConnected ? 'PostgreSQL 16' : dbHealth === null ? 'Connecting...' : 'Database Offline'}
              </span>
            )}
          </div>
          {!collapsed && (
            <span className="text-slate-400 font-mono text-[10px] shrink-0">
              {dbHealth?.latency_ms !== undefined && dbHealth?.latency_ms !== null
                ? `${dbHealth.latency_ms}ms`
                : isConnected ? 'ready' : '—'}
            </span>
          )}
        </div>

        {!collapsed && (
          <div className="px-2 py-0.5 text-[10px] text-slate-400 flex items-center justify-between font-sans">
            <span className="font-semibold text-slate-400">NEXUS Platform</span>
            <span className="inline-flex items-center gap-1 text-slate-400 font-mono text-[10px]">
              <Radio className="w-2.5 h-2.5 text-cyan-400" />
              v1.0.0
            </span>
          </div>
        )}
      </div>
    </aside>
  );
};
