import React, { useEffect, useState, useCallback } from 'react';
import { Header } from './components/Header';
import { SystemStatusCard } from './components/SystemStatusCard';
import { WorkflowPipeline } from './components/WorkflowPipeline';
import { ArchitectureGrid } from './components/ArchitectureGrid';
import { DomainDataPreview } from './components/DomainDataPreview';
import { getHealthStatus } from './services/api';
import { HealthResponse } from './types/api';
import { Sparkles, Terminal, ShieldCheck } from 'lucide-react';


export const App: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const checkHealth = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getHealthStatus();
      setHealth(data);
    } catch (err: any) {
      setError(err?.message || 'Could not connect to NEXUS backend.');
      setHealth(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    checkHealth();
  }, [checkHealth]);

  const isHealthy = health ? health.status === 'healthy' : error ? false : null;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Header isBackendHealthy={isHealthy} />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* Hero Section */}
        <section className="relative rounded-3xl p-8 sm:p-12 overflow-hidden glass-panel-glow border border-slate-800">
          <div className="absolute top-0 right-0 -mr-20 -mt-20 w-80 h-80 rounded-full bg-cyan-500/10 blur-3xl pointer-events-none" />
          <div className="absolute bottom-0 left-0 -ml-20 -mb-20 w-80 h-80 rounded-full bg-blue-600/10 blur-3xl pointer-events-none" />

          <div className="relative z-10 max-w-3xl">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-950/80 border border-cyan-800/80 text-cyan-400 text-xs font-mono font-medium mb-4">
              <Sparkles className="w-3.5 h-3.5" />
              <span>NEXUS Platform Initialization</span>
            </div>

            <h2 className="text-3xl sm:text-5xl font-extrabold tracking-tight text-white leading-tight">
              Where Business Data <br />
              <span className="bg-gradient-to-r from-cyan-400 via-sky-300 to-blue-500 bg-clip-text text-transparent">
                Becomes Intelligence.
              </span>
            </h2>

            <p className="mt-4 text-sm sm:text-base text-slate-300 leading-relaxed">
              NEXUS is an enterprise agentic business intelligence platform built to augment professional 
              analysts and make strategic intelligence accessible to non-technical operators. 
              Built on hybrid intelligence: deterministic mathematical precision powered by SQL and scientific 
              libraries, orchestrated through stateful agent reasoning.
            </p>

            <div className="mt-6 flex flex-wrap gap-3">
              <a
                href="http://localhost:8000/docs"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold shadow-md shadow-cyan-600/30 transition-all"
              >
                <Terminal className="w-4 h-4" />
                <span>OpenAPI Interactive Docs</span>
              </a>

              <button
                onClick={checkHealth}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-semibold transition-all"
              >
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                <span>Verify Live Backend</span>
              </button>
            </div>
          </div>
        </section>

        {/* System Status Panel */}
        <section>
          <SystemStatusCard
            health={health}
            loading={loading}
            error={error}
            onRefresh={checkHealth}
          />
        </section>

        {/* 11-Step Workflow Pipeline */}
        <section>
          <WorkflowPipeline />
        </section>

        {/* Target Initial Business Domain */}
        <section>
          <DomainDataPreview />
        </section>

        {/* System Architecture Grid */}
        <section>
          <ArchitectureGrid />
        </section>
      </main>

      <footer className="border-t border-slate-800/80 bg-slate-950 py-6 text-xs text-slate-400">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="font-bold text-slate-200">NEXUS</span>
            <span>—</span>
            <span>Agentic Business Intelligence Platform</span>
          </div>

          <div className="flex items-center gap-4 font-mono text-[11px] text-slate-400">
            <span>FastAPI 0.110+</span>
            <span>•</span>
            <span>SQLAlchemy 2.x</span>
            <span>•</span>
            <span>PostgreSQL 16</span>
            <span>•</span>
            <span>React 18 + Vite</span>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default App;
