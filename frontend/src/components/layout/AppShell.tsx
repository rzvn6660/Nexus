import React, { useState } from 'react';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { CommandPalette } from '../common/CommandPalette';
import { HealthResponse } from '../../types/api';

interface AppShellProps {
  currentRoute: string;
  onNavigate: (route: string) => void;
  health?: HealthResponse | null;
  children: React.ReactNode;
  onAskQuery?: (query: string) => void;
  activeBusinessName?: string;
  userRole?: string;
  onLogout?: () => void;
  businesses?: Array<{ id: string; name: string }>;
  activeBusinessId?: string;
  onSwitchBusiness?: (businessId: string) => void;
}

export const AppShell: React.FC<AppShellProps> = ({
  currentRoute,
  onNavigate,
  health,
  children,
  onAskQuery,
  activeBusinessName,
  userRole,
  onLogout,
  businesses,
  activeBusinessId,
  onSwitchBusiness,
}) => {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);

  return (
    <div className="min-h-screen bg-void text-slate-100 flex font-sans selection:bg-cyan-500/20 selection:text-cyan-200 w-full overflow-x-hidden">
      {/* Desktop Workspace Sidebar */}
      <div className="hidden md:block shrink-0">
        <Sidebar
          currentRoute={currentRoute}
          onNavigate={onNavigate}
          collapsed={collapsed}
          onToggleCollapse={() => setCollapsed(!collapsed)}
          dbHealth={health?.database}
        />
      </div>

      {/* Mobile Drawer Navigation with backdrop blur & slide animation */}
      {mobileMenuOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden bg-void/85 backdrop-blur-md animate-in fade-in duration-200">
          <div className="w-72 bg-void h-full shadow-2xl border-r border-surface-elevated/80 animate-in slide-in-from-left duration-200 flex flex-col">
            <Sidebar
              currentRoute={currentRoute}
              onNavigate={onNavigate}
              collapsed={false}
              onToggleCollapse={() => setMobileMenuOpen(false)}
              dbHealth={health?.database}
              onCloseMobile={() => setMobileMenuOpen(false)}
            />
          </div>
          <div
            className="flex-1 cursor-pointer"
            onClick={() => setMobileMenuOpen(false)}
            aria-label="Close navigation overlay"
          />
        </div>
      )}

      {/* Main Intelligence Workspace Canvas */}
      <div className="flex-1 flex flex-col min-w-0 w-full overflow-x-hidden">
        <TopBar
          currentRoute={currentRoute}
          onOpenCommand={() => setCommandPaletteOpen(true)}
          onOpenMobileMenu={() => setMobileMenuOpen(true)}
          onOpenAsk={() => onNavigate('/ask')}
          health={health}
          onNavigate={onNavigate}
          onLogout={onLogout}
          activeBusinessName={activeBusinessName}
          userRole={userRole}
          businesses={businesses}
          activeBusinessId={activeBusinessId}
          onSwitchBusiness={onSwitchBusiness}
        />

        {/* Primary Content Container: constrained max width, responsive padding, zero horizontal overflow */}
        <main className="flex-1 p-4 sm:p-6 lg:p-8 max-w-7xl w-full mx-auto space-y-8 min-w-0">
          {children}
        </main>

        {/* Quiet Enterprise Workspace Footer */}
        <footer className="border-t border-surface-elevated/70 bg-void-sub/40 py-5 text-xs text-slate-400 mt-auto shrink-0">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <span className="font-bold text-white tracking-[0.2em] font-sans uppercase text-[11px]">NEXUS</span>
              <span className="text-slate-600">—</span>
              <span className="text-slate-400 font-sans text-xs">Where Business Data Becomes Intelligence</span>
            </div>

            <div className="flex items-center gap-3 font-sans text-xs text-slate-400 flex-wrap justify-center">
              <span>Deterministic Analytics</span>
              <span className="text-slate-600">•</span>
              <span>Agentic Reasoning</span>
              <span className="text-slate-600">•</span>
              <span>Verifiable Provenance</span>
              <span className="text-slate-600">•</span>
              <span>Human Authority</span>
            </div>
          </div>
        </footer>
      </div>

      {/* Command Palette / Search Dialog */}
      <CommandPalette
        isOpen={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
        onNavigate={onNavigate}
        onAskQuery={onAskQuery}
      />
    </div>
  );
};
