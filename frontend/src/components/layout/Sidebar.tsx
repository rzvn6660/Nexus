import React from 'react';
import {
  LayoutDashboard,
  BarChart3,
  SearchCode,
  TrendingUp,
  MessageSquare,
  Database,
  BookOpen,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { DatabaseHealth } from '../../types/api';

interface SidebarProps {
  currentRoute: string;
  onNavigate: (route: string) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  dbHealth?: DatabaseHealth | null;
  onCloseMobile?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentRoute,
  onNavigate,
  collapsed,
  onToggleCollapse,
  dbHealth,
  onCloseMobile,
}) => {
  const navItems = [
    {
      title: 'Overview',
      route: '/',
      icon: LayoutDashboard,
      badge: 'Live',
    },
    {
      title: 'Analytics',
      route: '/analytics',
      icon: BarChart3,
    },
    {
      title: 'Investigations',
      route: '/investigations',
      icon: SearchCode,
      badge: 'Diagnostic',
    },
    {
      title: 'Forecasts',
      route: '/forecasts',
      icon: TrendingUp,
      badge: 'Predictive',
    },
    {
      title: 'Ask NEXUS',
      route: '/ask',
      icon: MessageSquare,
      badge: 'Agent',
    },
    {
      title: 'Data Health',
      route: '/data',
      icon: Database,
    },
    {
      title: 'Knowledge & KPIs',
      route: '/knowledge',
      icon: BookOpen,
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
      className={`h-screen sticky top-0 bg-slate-950/95 border-r border-slate-800/80 flex flex-col justify-between transition-all duration-300 z-30 select-none ${
        collapsed ? 'w-20' : 'w-64'
      }`}
    >
      {/* Top Branding Section */}
      <div>
        <div className="h-16 px-4 flex items-center justify-between border-b border-slate-800/60">
          <div
            onClick={() => handleItemClick('/')}
            className="flex items-center gap-3 cursor-pointer group"
          >
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-cyan-600 to-sky-400 flex items-center justify-center shadow-lg shadow-cyan-500/20 group-hover:scale-105 transition-transform">
              <span className="font-extrabold text-white text-base tracking-wider font-mono">N</span>
            </div>
            {!collapsed && (
              <div className="flex flex-col">
                <span className="font-extrabold text-base tracking-wider text-white">NEXUS</span>
                <span className="text-[10px] font-mono text-cyan-400 uppercase tracking-widest -mt-1">
                  Intelligence
                </span>
              </div>
            )}
          </div>

          <button
            onClick={onToggleCollapse}
            className="hidden md:flex p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-900 transition-colors"
            title={collapsed ? 'Expand Sidebar' : 'Collapse Sidebar'}
            aria-label={collapsed ? 'Expand Sidebar' : 'Collapse Sidebar'}
          >
            {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          </button>
        </div>

        {/* Navigation Item List */}
        <nav className="p-3 space-y-1.5 mt-2" aria-label="Main Navigation">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive =
              currentRoute === item.route ||
              (item.route !== '/' && currentRoute.startsWith(item.route));

            return (
              <button
                key={item.route}
                onClick={() => handleItemClick(item.route)}
                title={collapsed ? item.title : undefined}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-medium transition-all ${
                  isActive
                    ? 'bg-cyan-950/80 text-cyan-300 border border-cyan-800/60 shadow-sm font-semibold'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/70 border border-transparent'
                } ${collapsed ? 'justify-center px-0' : 'justify-between'}`}
              >
                <div className="flex items-center gap-3">
                  <Icon
                    className={`w-4 h-4 shrink-0 transition-colors ${
                      isActive ? 'text-cyan-400' : 'text-slate-400 group-hover:text-slate-300'
                    }`}
                  />
                  {!collapsed && <span>{item.title}</span>}
                </div>

                {!collapsed && item.badge && (
                  <span
                    className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                      isActive
                        ? 'bg-cyan-800/60 text-cyan-200'
                        : 'bg-slate-800/60 text-slate-400'
                    }`}
                  >
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Bottom Infrastructure & System Status */}
      <div className="p-3 border-t border-slate-800/60 space-y-2">
        <div
          className={`flex items-center gap-2 p-2 rounded-xl bg-slate-900/60 border border-slate-800 text-[11px] font-mono ${
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
            <span>NEXUS v0.1.0</span>
            <span className="text-cyan-400/80">Phase 8 UI</span>
          </div>
        )}
      </div>
    </aside>
  );
};
