import React from 'react';
import {
  Database,
  BrainCircuit,
  SearchCode,
  ShieldCheck,
  TrendingUp,
  FileSpreadsheet,
  CheckCircle2,
  ChevronRight,
} from 'lucide-react';

interface StageItem {
  id: string;
  stageNumber: string;
  name: string;
  role: string;
  icon: React.ElementType;
  route?: string;
  tag: string;
}

const STAGES: StageItem[] = [
  {
    id: 'data',
    stageNumber: '01',
    name: 'DATA',
    role: 'Transactional Schema & Logs',
    icon: Database,
    route: '/data',
    tag: 'Verified Sources',
  },
  {
    id: 'understand',
    stageNumber: '02',
    name: 'UNDERSTAND',
    role: 'Semantic Layer & KPI Ontology',
    icon: BrainCircuit,
    route: '/knowledge',
    tag: 'Strict Semantics',
  },
  {
    id: 'investigate',
    stageNumber: '03',
    name: 'INVESTIGATE',
    role: 'Diagnostic Root-Cause Engine',
    icon: SearchCode,
    route: '/investigations',
    tag: 'Multi-Hypothesis',
  },
  {
    id: 'validate',
    stageNumber: '04',
    name: 'VALIDATE',
    role: 'Evidence Validation & Provenance',
    icon: ShieldCheck,
    route: '/analytics',
    tag: 'Verifiable Lineage',
  },
  {
    id: 'predict',
    stageNumber: '05',
    name: 'PREDICT',
    role: 'ML Horizon & Uncertainty',
    icon: TrendingUp,
    route: '/forecasts',
    tag: 'Confidence Bands',
  },
  {
    id: 'explain',
    stageNumber: '06',
    name: 'EXPLAIN',
    role: 'Structured Intelligence Dossier',
    icon: FileSpreadsheet,
    route: '/ask',
    tag: 'Executive Brief',
  },
  {
    id: 'decide',
    stageNumber: '07',
    name: 'DECIDE',
    role: 'Human-in-the-Loop Governance',
    icon: CheckCircle2,
    route: '/history',
    tag: 'Human Review',
  },
];

interface WorkflowPathProps {
  onNavigate?: (route: string) => void;
  className?: string;
  compact?: boolean;
}

export const WorkflowPath: React.FC<WorkflowPathProps> = ({
  onNavigate,
  className = '',
  compact = false,
}) => {
  return (
    <div className={`space-y-3 ${className}`}>
      <div className="flex items-center justify-between text-xs">
        <span className="font-mono text-[11px] uppercase tracking-wider text-slate-400 font-semibold flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-brand-cyan animate-pulse" />
          The NEXUS Epistemic Progression
        </span>
        <span className="font-mono text-[10px] text-slate-500 hidden sm:inline">
          Continuous Intelligence • Not a Chatbot
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2">
        {STAGES.map((s, idx) => {
          const Icon = s.icon;
          return (
            <div
              key={s.id}
              onClick={() => s.route && onNavigate && onNavigate(s.route)}
              className={`group relative rounded-xl border border-surface-elevated bg-surface/40 hover:bg-surface-elevated/70 hover:border-brand-cyan/40 transition-all duration-200 p-2.5 flex flex-col justify-between cursor-pointer select-none ${
                compact ? 'min-h-[76px]' : 'min-h-[92px]'
              }`}
            >
              {/* Top row: Stage number & Connector hint */}
              <div className="flex items-center justify-between">
                <span className="font-mono text-[10px] text-slate-500 group-hover:text-brand-cyan transition-colors">
                  {s.stageNumber}
                </span>
                <Icon className="w-3.5 h-3.5 text-slate-400 group-hover:text-brand-cyan transition-colors" />
              </div>

              {/* Middle: Stage Name */}
              <div className="py-1">
                <div className="font-sans font-bold text-xs text-white tracking-wide group-hover:text-brand-cyan transition-colors">
                  {s.name}
                </div>
                <div className="text-[10px] font-mono text-slate-400 line-clamp-1 leading-tight mt-0.5">
                  {s.role}
                </div>
              </div>

              {/* Bottom tag */}
              <div className="pt-1 border-t border-surface-highlight/40 flex items-center justify-between">
                <span className="text-[9px] font-mono text-slate-400 group-hover:text-slate-200 truncate">
                  {s.tag}
                </span>
                {idx < STAGES.length - 1 && (
                  <ChevronRight className="w-2.5 h-2.5 text-slate-600 group-hover:text-brand-cyan hidden lg:block shrink-0 -mr-1" />
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
