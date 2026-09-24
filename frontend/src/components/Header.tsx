import React from 'react';
import { Github, ExternalLink } from 'lucide-react';


interface HeaderProps {
  isBackendHealthy: boolean | null;
}

export const Header: React.FC<HeaderProps> = ({ isBackendHealthy }) => {
  return (
    <header className="border-b border-slate-800 bg-slate-900/60 backdrop-blur-md sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-600 to-blue-500 flex items-center justify-center shadow-lg shadow-cyan-500/20">
            <span className="text-xl font-black text-white tracking-wider">NX</span>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold tracking-tight text-white">NEXUS</h1>
              <span className="text-xs px-2 py-0.5 rounded-full font-mono font-medium bg-cyan-950 text-cyan-400 border border-cyan-800">
                Phase 1: Foundation
              </span>
            </div>
            <p className="text-xs text-slate-400 hidden sm:block">Where Business Data Becomes Intelligence.</p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/80 border border-slate-700/60 text-xs">
            <span
              className={`w-2 h-2 rounded-full animate-pulse ${
                isBackendHealthy === true
                  ? 'bg-emerald-400 shadow-emerald-400/50 shadow-sm'
                  : isBackendHealthy === false
                  ? 'bg-rose-500 shadow-rose-500/50 shadow-sm'
                  : 'bg-amber-400 shadow-amber-400/50 shadow-sm'
              }`}
            />
            <span className="font-mono text-slate-300">
              API:{' '}
              {isBackendHealthy === true
                ? 'Online'
                : isBackendHealthy === false
                ? 'Offline'
                : 'Connecting...'}
            </span>
          </div>

          <a
            href="http://localhost:8000/docs"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 text-xs text-slate-300 hover:text-cyan-400 transition-colors px-2.5 py-1.5 rounded-lg hover:bg-slate-800/50"
          >
            <span>API Docs</span>
            <ExternalLink className="w-3.5 h-3.5" />
          </a>

          <a
            href="https://github.com/rzvn6660/Nexus"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 text-xs text-slate-300 hover:text-white transition-colors px-2.5 py-1.5 rounded-lg hover:bg-slate-800/50"
          >
            <Github className="w-4 h-4" />
            <span className="hidden sm:inline">GitHub</span>
          </a>
        </div>
      </div>
    </header>
  );
};
