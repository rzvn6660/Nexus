import React, { useState } from 'react';
import { 
  Database, 
  BrainCircuit, 
  CheckCheck, 
  BarChart3, 
  SearchCode, 
  ShieldAlert, 
  MessageSquareQuote, 
  TrendingUp, 
  Sparkles, 
  UserCheck, 
  Gauge 
} from 'lucide-react';

interface WorkflowStep {
  id: string;
  name: string;
  category: 'deterministic' | 'hybrid' | 'human';
  icon: React.ReactNode;
  summary: string;
  description: string;
  technology: string;
}

const WORKFLOW_STEPS: WorkflowStep[] = [
  {
    id: 'data',
    name: '1. Data',
    category: 'deterministic',
    icon: <Database className="w-4 h-4 text-cyan-400" />,
    summary: 'Source Ingestion & Connectors',
    description: 'Connects to structured retail databases (PostgreSQL), transaction logs, and analytical warehouses.',
    technology: 'SQLAlchemy, PostgreSQL, Connectors',
  },
  {
    id: 'understand',
    name: '2. Understand',
    category: 'hybrid',
    icon: <BrainCircuit className="w-4 h-4 text-purple-400" />,
    summary: 'Intent Parsing & Retrieval',
    description: 'NLU parses natural-language stakeholder questions and maps them to semantic KPIs and dimensional entities.',
    technology: 'LLM Orchestrator, Semantic Layer',
  },
  {
    id: 'check',
    name: '3. Check',
    category: 'deterministic',
    icon: <CheckCheck className="w-4 h-4 text-emerald-400" />,
    summary: 'Data Quality & Profiling',
    description: 'Verifies missingness, schema constraints, cardinality, and fresh timestamps before running analytical routines.',
    technology: 'Pandas, Profiling Rules',
  },
  {
    id: 'analyze',
    name: '4. Analyze',
    category: 'deterministic',
    icon: <BarChart3 className="w-4 h-4 text-blue-400" />,
    summary: 'Deterministic Computation',
    description: 'Executes exact SQL queries, descriptive statistics, gross margin, and revenue aggregations without hallucination.',
    technology: 'SQL Engine, NumPy, SciPy',
  },
  {
    id: 'investigate',
    name: '5. Investigate',
    category: 'hybrid',
    icon: <SearchCode className="w-4 h-4 text-amber-400" />,
    summary: 'Diagnostic Deep-Dive',
    description: 'Drills down into product categories, customer cohorts, and anomalous variance to isolate root drivers.',
    technology: 'Diagnostic Analytics, LangGraph',
  },
  {
    id: 'validate',
    name: '6. Validate',
    category: 'deterministic',
    icon: <ShieldAlert className="w-4 h-4 text-rose-400" />,
    summary: 'Evidence & Fact Verification',
    description: 'Cross-verifies claims against generated evidence tables, query execution hashes, and confidence intervals.',
    technology: 'Evidence Engine, Statistical Tests',
  },
  {
    id: 'explain',
    name: '7. Explain',
    category: 'hybrid',
    icon: <MessageSquareQuote className="w-4 h-4 text-indigo-400" />,
    summary: 'Executive Translation',
    description: 'Translates statistical findings and variance tables into actionable, crystal-clear business narratives.',
    technology: 'Structured LLM Output',
  },
  {
    id: 'predict',
    name: '8. Predict',
    category: 'deterministic',
    icon: <TrendingUp className="w-4 h-4 text-sky-400" />,
    summary: 'Forecasting & Extrapolation',
    description: 'Runs deterministic time-series models (demand trends, seasonal stock depletion) with explicit error bands.',
    technology: 'scikit-learn, Time-Series Models',
  },
  {
    id: 'recommend',
    name: '9. Recommend',
    category: 'hybrid',
    icon: <Sparkles className="w-4 h-4 text-yellow-400" />,
    summary: 'Prescriptive Scenarios',
    description: 'Generates specific operational suggestions (e.g., inventory reorder thresholds, discount recalibrations).',
    technology: 'Prescriptive Engine, Business Rules',
  },
  {
    id: 'human',
    name: '10. Human Decision',
    category: 'human',
    icon: <UserCheck className="w-4 h-4 text-emerald-400" />,
    summary: 'Human-in-the-Loop Review',
    description: 'Business owner or analyst reviews audit trail, assumptions, and recommendations before executing decisions.',
    technology: 'Approval Gate, Analyst UI',
  },
  {
    id: 'measure',
    name: '11. Measure Outcome',
    category: 'deterministic',
    icon: <Gauge className="w-4 h-4 text-cyan-400" />,
    summary: 'Closed-Loop Tracking',
    description: 'Measures post-decision actuals vs. predicted outcomes to calibrate future intelligence and baseline models.',
    technology: 'Outcome Tracker, Historical Memory',
  },
];

export const WorkflowPipeline: React.FC = () => {
  const [activeStepId, setActiveStepId] = useState<string>('analyze');
  const activeStep = WORKFLOW_STEPS.find((s) => s.id === activeStepId) || WORKFLOW_STEPS[3];

  return (
    <div className="glass-panel rounded-2xl p-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-6 gap-2">
        <div>
          <h3 className="text-base font-semibold text-white flex items-center gap-2">
            <span>NEXUS Core Intelligence Workflow</span>
            <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">
              11-Step Hybrid Engine
            </span>
          </h3>
          <p className="text-xs text-slate-400">
            Deterministic execution coupled with agentic reasoning — no LLM calculation hallucinations.
          </p>
        </div>

        <div className="flex items-center gap-3 text-xs">
          <span className="flex items-center gap-1.5 text-slate-300">
            <span className="w-2.5 h-2.5 rounded-full bg-cyan-500/80 inline-block" /> Deterministic
          </span>
          <span className="flex items-center gap-1.5 text-slate-300">
            <span className="w-2.5 h-2.5 rounded-full bg-purple-500/80 inline-block" /> Hybrid / LLM
          </span>
          <span className="flex items-center gap-1.5 text-slate-300">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/80 inline-block" /> Human Gate
          </span>
        </div>
      </div>

      {/* Horizontal step visualizer */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-11 gap-2 mb-6">
        {WORKFLOW_STEPS.map((step) => {
          const isSelected = step.id === activeStepId;
          return (
            <button
              key={step.id}
              onClick={() => setActiveStepId(step.id)}
              className={`p-2.5 rounded-xl text-left transition-all border flex flex-col justify-between ${
                isSelected
                  ? 'bg-cyan-950/60 border-cyan-500/60 shadow-lg shadow-cyan-950/50'
                  : 'bg-slate-900/40 border-slate-800/80 hover:bg-slate-800/50 hover:border-slate-700'
              }`}
            >
              <div className="flex items-center justify-between w-full mb-1.5">
                <span className="p-1 rounded-md bg-slate-800/80 border border-slate-700">
                  {step.icon}
                </span>
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    step.category === 'deterministic'
                      ? 'bg-cyan-400'
                      : step.category === 'hybrid'
                      ? 'bg-purple-400'
                      : 'bg-emerald-400'
                  }`}
                />
              </div>
              <span className="text-xs font-semibold text-slate-200 truncate block">
                {step.name}
              </span>
              <span className="text-[10px] text-slate-400 truncate block mt-0.5">
                {step.summary}
              </span>
            </button>
          );
        })}
      </div>

      {/* Step details inspection card */}
      <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="p-2.5 rounded-xl bg-slate-800 border border-slate-700 mt-0.5">
            {activeStep.icon}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-bold text-white">{activeStep.name}</h4>
              <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-slate-800 text-cyan-400 border border-slate-700">
                {activeStep.summary}
              </span>
              <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-slate-800/80 text-slate-400">
                {activeStep.category}
              </span>
            </div>
            <p className="text-xs text-slate-300 mt-1">{activeStep.description}</p>
          </div>
        </div>

        <div className="shrink-0 text-left sm:text-right border-t sm:border-t-0 sm:border-l border-slate-800 pt-2 sm:pt-0 sm:pl-4">
          <span className="text-[10px] uppercase tracking-wider text-slate-400 block font-semibold">
            Underlying Stack
          </span>
          <span className="text-xs font-mono text-cyan-300 font-medium">
            {activeStep.technology}
          </span>
        </div>
      </div>
    </div>
  );
};
