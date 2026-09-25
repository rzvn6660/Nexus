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
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { DatabaseHealth } from '../../types/api';
import { NexusLogo } from '../brand/NexusLogo';
import { NexusSymbol } from '../brand/NexusSymbol';

interface SidebarProps {
  currentRoute: string;
  onNavigate: (route: string) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  dbHealth?: DatabaseHealth | null;
  onCloseMobile?: () => void;
}

interface NavGroup {
  label?: string;
  items: Array<{
    title: string;
    route: string;
    icon: React.ElementType;
    badge?: string;
  }>;
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
      label: 'NEXUS INTELLIGENCE',
      items: [
        {
          title: 'Overview',
          route: '/',
          icon: LayoutDashboard,
          badge: 'Briefing',
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
          badge: 'Predictive',
        },
        {
          title: 'Analytics',
          route: '/analytics',
          icon: BarChart3,
        },
      ],
    },
    {
      label: 'DATA LAYER',
      items: [
        {
          title: 'Data Health & Schema',
          route: '/data',
          icon: Database,
        },
      ],
    },
    {
      label: 'KNOWLEDGE & ONTOLOGY',
      items: [
        {
          title: 'Context & KPI Dictionary',
          route: '/knowledge',
          icon: BookOpen,
        },
      ],
    },
    {
      label: 'HISTORY & GOVERNANCE',
      items: [
        {
          title: 'Analyses & Decisions',
          route: '/history',
          icon: History,
          badge: 'Audit',
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
      className={`h-screen sticky top-0 bg-void border-r border-surface-elevated flex flex-col justify-between transition-all duration-300 z-30 select-none ${
        collapsed ? 'w-20' : 'w-64'
      }`}
    >
      {/* Top Branding Section */}
      <div className="overflow-y-auto overflow-x-hidden">
        <div className="h-16 px-4 flex items-center justify-between border-b border-surface-elevated">
          <div
            onClick={() => handleItemClick('/')}
            className="cursor-pointer group flex items-center"
          >
            {collapsed ? (
              <NexusSymbol size={34} />
            ) : (
              <NexusLogo symbolSize={32} />
            )}
          </div>

          <button
            onClick={onToggleCollapse}
            className="hidden md:flex p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-surface-elevated transition-colors"
            title={collapsed ? 'Expand Workspace Rail' : 'Collapse Workspace Rail'}
            aria-label={collapsed ? 'Expand Workspace Rail' : 'Collapse Workspace Rail'}
          >
            {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          </button>
        </div>

        {/* Grouped Navigation */}
        <nav className="p-3 space-y-5 mt-2" aria-label="Main Navigation">
          {navGroups.map((group, gIdx) => (
            <div key={gIdx} className="space-y-1">
              {!collapsed && group.label && (
                <div className="px-3 text-[10px] font-mono tracking-widest text-slate-400 uppercase font-semibold mb-1">
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
                    className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl text-xs font-medium transition-all ${
                      isActive
                        ? 'bg-cyan-950/80 text-brand-cyan border border-brand-cyan/40 font-semibold shadow-sm'
                        : 'text-slate-400 hover:text-slate-200 hover:bg-surface/80 border border-transparent'
                    } ${collapsed ? 'justify-center px-0' : 'justify-between'}`}
                  >
                    <div className="flex items-center gap-2.5 truncate">
                      <Icon
                        className={`w-4 h-4 shrink-0 transition-colors ${
                          isActive ? 'text-brand-cyan' : 'text-slate-400 group-hover:text-slate-300'
                        }`}
                      />
                      {!collapsed && <span className="truncate">{item.title}</span>}
                    </div>

                    {!collapsed && item.badge && (
                      <span
                        className={`text-[9px] font-mono px-1.5 py-0.5 rounded uppercase font-semibold ${
                          isActive
                            ? 'bg-cyan-900/60 text-brand-cyan'
                            : 'bg-surface-elevated text-slate-400'
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
      <div className="p-3 border-t border-surface-elevated space-y-2">
        <div
          className={`flex items-center gap-2 p-2 rounded-xl bg-surface/60 border border-surface-elevated text-[11px] font-mono ${
            collapsed ? 'justify-center' : 'justify-between'
          }`}
        >
          <div className="flex items-center gap-2 truncate">
            <div
              className={`w-2 h-2 rounded-full shrink-0 ${
                isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-rose-500'
              }`}
            />
            {!collapsed && (
              <span className="text-slate-300 truncate">
                {isConnected ? 'PostgreSQL 16' : 'Database Offline'}
              </span>
            )}
          </div>
          {!collapsed && (
            <span className="text-slate-400 text-[10px]">
              {dbHealth?.latency_ms !== undefined && dbHealth?.latency_ms !== null
                ? `${dbHealth.latency_ms}ms`
                : 'ready'}
            </span>
          )}
        </div>

        {!collapsed && (
          <div className="px-2 py-1 text-[10px] font-mono text-slate-400 flex items-center justify-between">
            <span className="font-bold text-slate-400">NEXUS v1.0.0</span>
            <span className="text-brand-cyan/80">V1 Verified</span>
          </div>
        )}
      </div>
    </aside>
  );
};
