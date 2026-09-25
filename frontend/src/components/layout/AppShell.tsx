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
}

export const AppShell: React.FC<AppShellProps> = ({
  currentRoute,
  onNavigate,
  health,
  children,
  onAskQuery,
}) => {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex font-sans">
      {/* Desktop Sidebar */}
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
        <div className="fixed inset-0 z-50 flex md:hidden bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-150">
          <div className="w-72 bg-slate-950 h-full shadow-2xl">
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

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar
          currentRoute={currentRoute}
          onOpenCommand={() => setCommandPaletteOpen(true)}
          onOpenMobileMenu={() => setMobileMenuOpen(true)}
          onOpenAsk={() => onNavigate('/ask')}
          health={health}
        />

        <main className="flex-1 p-4 sm:p-6 lg:p-8 max-w-7xl w-full mx-auto space-y-8">
          {children}
        </main>

        <footer className="border-t border-slate-800/80 bg-slate-950 py-5 text-xs text-slate-400 mt-auto">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <span className="font-bold text-slate-200">NEXUS</span>
              <span>—</span>
              <span>Agentic Business Intelligence Platform</span>
            </div>

            <div className="flex items-center gap-4 font-mono text-[11px] text-slate-400">
              <span>Deterministic Precision</span>
              <span>•</span>
              <span>Stateful Reasoning</span>
              <span>•</span>
              <span>Verifiable Provenance</span>
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
