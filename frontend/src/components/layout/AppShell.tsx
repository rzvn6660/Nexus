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
}) => {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);

  return (
    <div className="min-h-screen bg-void text-slate-100 flex font-sans selection:bg-cyan-500/20 selection:text-cyan-200">
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

      {/* Mobile Drawer Navigation */}
      {mobileMenuOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden bg-void/80 backdrop-blur-sm animate-in fade-in duration-150">
          <div className="w-72 bg-void h-full shadow-2xl">
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
            className="flex-1"
            onClick={() => setMobileMenuOpen(false)}
            aria-label="Close navigation"
          />
        </div>
      )}

      {/* Main Intelligence Workspace Canvas */}
      <div className="flex-1 flex flex-col min-w-0">
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
        />

        <main className="flex-1 p-4 sm:p-6 lg:p-8 max-w-7xl w-full mx-auto space-y-8">
          {children}
        </main>

        {/* Quiet Workspace Footer */}
        <footer className="border-t border-surface-elevated/70 bg-void py-5 text-xs text-slate-400 mt-auto">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <span className="font-bold text-slate-100 tracking-[0.2em] font-sans uppercase">NEXUS</span>
              <span>—</span>
              <span className="text-slate-300">Where Business Data Becomes Intelligence</span>
            </div>

            <div className="flex items-center gap-3 font-mono text-[11px] text-slate-400 flex-wrap justify-center">
              <span>Deterministic Analytics</span>
              <span>•</span>
              <span>Agentic Reasoning</span>
              <span>•</span>
              <span>Verifiable Provenance</span>
              <span>•</span>
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
