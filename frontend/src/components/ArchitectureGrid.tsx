import React from 'react';
import { 
  Layers, 
  Terminal, 
  Workflow, 
  BookMarked, 
  FileCheck2, 
  Store 
} from 'lucide-react';

interface ArchitectureModule {
  title: string;
  phase: string;
  status: 'implemented' | 'planned' | 'future';
  icon: React.ReactNode;
  description: string;
  highlights: string[];
}

const MODULES: ArchitectureModule[] = [
  {
    title: 'Core Backend & API Foundation',
    phase: 'Phase 1',
    status: 'implemented',
    icon: <Terminal className="w-5 h-5 text-cyan-400" />,
    description: 'FastAPI async server, SQLAlchemy 2.x engine, Pydantic v2 settings, Alembic, structured logging, and health telemetry.',
    highlights: ['FastAPI 0.110+', 'SQLAlchemy 2.x', 'Docker Compose', 'Pytest Suite'],
  },
  {
    title: 'Retail Business Domain Store',
    phase: 'Phase 1',
    status: 'implemented',
    icon: <Store className="w-5 h-5 text-emerald-400" />,
    description: 'Foundational models and schemas focused on small retail/distribution: sales, customers, products, inventory, and expenses.',
    highlights: ['Retail Schema Ready', 'PostgreSQL 16', 'Audit Mixins', 'Decoupled Models'],
  },
  {
    title: 'Deterministic Analytics Engine',
    phase: 'Phase 2',
    status: 'planned',
    icon: <Layers className="w-5 h-5 text-blue-400" />,
    description: 'Exact mathematical calculation engine for KPIs, variance decomposition, statistics, and time-series demand forecasting.',
    highlights: ['Pandas & NumPy', 'SciPy Statistics', 'scikit-learn', 'Zero LLM Math'],
  },
  {
    title: 'Stateful LangGraph Agent Layer',
    phase: 'Phase 3',
    status: 'planned',
    icon: <Workflow className="w-5 h-5 text-purple-400" />,
    description: 'Multi-node state machine orchestrating request planning, tool selection, SQL verification, and multi-turn analyst feedback.',
    highlights: ['LangGraph Workflows', 'Model-Agnostic', 'Tool Calling', 'State Checkpoints'],
  },
  {
    title: 'Semantic Business Layer',
    phase: 'Phase 3',
    status: 'planned',
    icon: <BookMarked className="w-5 h-5 text-amber-400" />,
    description: 'Explicit, auditable definitions of metrics (e.g. Revenue = Sales - Refunds, Gross Margin, Inventory Turn).',
    highlights: ['Metric Registry', 'KPI Formulas', 'Contextual RAG', 'Business Rules'],
  },
  {
    title: 'Evidence Verification & Auditing',
    phase: 'Phase 4',
    status: 'future',
    icon: <FileCheck2 className="w-4 h-4 text-rose-400" />,
    description: 'Every insight links directly to underlying SQL hashes, data slice timestamps, assumptions, and validation gates.',
    highlights: ['Traceable SQL', 'Data Slice Proofs', 'Analyst Signoff', 'Human-in-the-Loop'],
  },
];

export const ArchitectureGrid: React.FC = () => {
  return (
    <div className="glass-panel rounded-2xl p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-base font-semibold text-white">System Architecture & Roadmap</h3>
          <p className="text-xs text-slate-400">
            Decoupled, replaceable modules designed for enterprise reliability
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {MODULES.map((mod) => (
          <div
            key={mod.title}
            className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80 hover:border-slate-700/80 transition-all flex flex-col justify-between"
          >
            <div>
              <div className="flex items-center justify-between mb-3">
                <div className="p-2 rounded-lg bg-slate-800/80 border border-slate-700">
                  {mod.icon}
                </div>
                <span
                  className={`text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full uppercase tracking-wider ${
                    mod.status === 'implemented'
                      ? 'bg-emerald-950/80 text-emerald-400 border border-emerald-800'
                      : mod.status === 'planned'
                      ? 'bg-blue-950/80 text-blue-400 border border-blue-800'
                      : 'bg-purple-950/80 text-purple-400 border border-purple-800'
                  }`}
                >
                  {mod.phase} • {mod.status}
                </span>
              </div>

              <h4 className="text-sm font-bold text-white mb-1.5">{mod.title}</h4>
              <p className="text-xs text-slate-300 leading-relaxed mb-4">{mod.description}</p>
            </div>

            <div className="pt-3 border-t border-slate-800/80 flex flex-wrap gap-1.5">
              {mod.highlights.map((tag) => (
                <span
                  key={tag}
                  className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-400"
                >
                  {tag}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
